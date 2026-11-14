"""Deployable REST adapter for the knowledge-compression core.

Run locally with::

    uvicorn app.api:app --host 0.0.0.0 --port 8000

The endpoints accept raw document bytes to avoid multipart and Base64 overhead.
Generated packages can be stored in Ericsson's existing object store, while
their returned SHA-256 values can be used as immutable registry identifiers.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Annotated, Callable

from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.integration import (
    MAX_INPUT_BYTES,
    KnowledgeArtifact,
    build_exact_artifact,
    build_pdf_artifact,
    build_pptx_artifact,
    build_video_artifact,
    restore_exact_artifact,
    search_knowledge_package,
)


MAX_VIDEO_INPUT_BYTES = 10 * 1024 * 1024 * 1024
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


app = FastAPI(
    title="Ericsson Knowledge Compression API",
    version="1.0.0",
    description=(
        "Integration API for turning documents into compact, searchable knowledge "
        "packages. Streamlit is a demo client, not a runtime dependency."
    ),
)


def _package_response(artifact: KnowledgeArtifact) -> Response:
    metadata = artifact.metadata()
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{artifact.kind}-{artifact.source_sha256[:16]}.kp"'
        ),
        "X-KP-Source-SHA256": artifact.source_sha256,
        "X-KP-Package-SHA256": artifact.package_sha256,
        "X-KP-Codec": artifact.codec,
        "X-KP-Original-Bytes": str(artifact.original_bytes),
        "X-KP-Package-Bytes": str(artifact.package_bytes),
        "X-KP-Saved-Bytes": str(artifact.saved_bytes),
        "X-KP-Saved-Percent": f"{artifact.saved_percent:.6f}",
        "X-KP-Units": str(artifact.units),
        "X-KP-Fidelity": artifact.fidelity,
        "X-KP-Reversible": str(artifact.reversible).lower(),
        "X-KP-Searchable": str(artifact.searchable).lower(),
        "X-KP-AI-Ready": str(artifact.ai_ready).lower(),
        "X-KP-Transcript-Bytes": str(metadata["transcript_bytes"]),
        "X-KP-Graph-Manifest-Bytes": str(metadata["graph_manifest_bytes"]),
        "X-KP-Reference-Bytes": str(metadata["reference_bytes"]),
        "X-KP-Unique-Visual-Bytes": str(metadata["unique_visual_bytes"]),
        "X-KP-Deduplicated-Bytes": str(metadata["deduplicated_bytes"]),
        "X-KP-Archive-Header-Overhead": str(metadata["archive_header_overhead"]),
        "X-KP-Largest-Component": str(metadata["largest_component"]),
    }
    return Response(
        content=artifact.payload,
        media_type="application/vnd.ericsson.knowledge-package",
        headers=headers,
    )


def _build_or_422(builder: Callable[[], KnowledgeArtifact]) -> KnowledgeArtifact:
    try:
        return builder()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "knowledge-compression", "version": "1.0.0"}


@app.get("/v1/capabilities")
def capabilities() -> dict[str, object]:
    return {
        "input_limit_bytes": MAX_INPUT_BYTES,
        "formats": {
            "exact": {
                "mode": "lossless byte-for-byte",
                "preserves": ["every original byte", "source SHA-256"],
                "round_trip": "POST /v1/packages/exact then POST /v1/restore/exact",
                "tradeoff": "typically much lower reduction for already-compressed files",
            },
            "pdf": {
                "mode": "semantic",
                "preserves": ["searchable text", "page order", "links", "asset identities"],
                "does_not_preserve": ["original rendering", "embedded image pixels"],
            },
            "pptx": {
                "mode": "semantic",
                "preserves": ["text", "notes", "shape geometry", "relationships"],
                "optional": ["pixel-identical embedded media"],
                "does_not_preserve": ["editable PowerPoint reconstruction"],
            },
            "video": {
                "mode": "semantic streaming ingest",
                "input_limit_bytes": MAX_VIDEO_INPUT_BYTES,
                "preserves": ["transcript timeline", "representative keyframes", "source hash"],
                "does_not_preserve": ["discarded motion", "original audio"],
            },
        },
        "package_search": {
            "endpoint": "POST /v1/search",
            "supported_formats": ["pdf", "pptx"],
            "video": "index KP2 with src.search before querying; direct KP2 search is not implemented",
        },
        "integration": ["Python library", "REST/OpenAPI", "object-storage compatible bytes"],
    }


@app.post("/v1/packages/pdf", response_class=Response)
def package_pdf(
    document: Annotated[bytes, Body(media_type="application/pdf")],
) -> Response:
    artifact = _build_or_422(lambda: build_pdf_artifact(document))
    return _package_response(artifact)


@app.post("/v1/packages/exact", response_class=Response)
def package_exact(
    document: Annotated[bytes, Body(media_type="application/octet-stream")],
) -> Response:
    artifact = _build_or_422(lambda: build_exact_artifact(document))
    return _package_response(artifact)


@app.post("/v1/restore/exact", response_class=Response)
def restore_exact(
    package: Annotated[
        bytes,
        Body(media_type="application/vnd.ericsson.knowledge-package"),
    ],
) -> Response:
    try:
        restored = restore_exact_artifact(package)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(
        content=restored,
        media_type="application/octet-stream",
        headers={"X-KP-Restored-SHA256": hashlib.sha256(restored).hexdigest()},
    )


@app.post("/v1/packages/pptx", response_class=Response)
def package_pptx(
    document: Annotated[
        bytes,
        Body(
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
    ],
    include_media: Annotated[bool, Query()] = True,
) -> Response:
    artifact = _build_or_422(
        lambda: build_pptx_artifact(document, include_media=include_media)
    )
    return _package_response(artifact)


@app.post("/v1/packages/video", response_class=Response)
async def package_video(
    request: Request,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    transcribe_audio: Annotated[bool, Query()] = True,
    model_name: Annotated[str, Query(pattern=r"^[A-Za-z0-9._-]{1,40}$")] = "base",
) -> Response:
    """Stream a large recording through the existing video-to-KP pipeline."""
    suffix = Path(filename).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise HTTPException(status_code=415, detail="Unsupported video filename extension")
    declared_size = request.headers.get("content-length")
    if declared_size:
        try:
            if int(declared_size) > MAX_VIDEO_INPUT_BYTES:
                raise HTTPException(status_code=413, detail="Video exceeds the 10 GiB limit")
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from error

    with tempfile.TemporaryDirectory(prefix="knowledge-video-api-") as directory:
        workspace = Path(directory)
        source = workspace / f"source{suffix}"
        received = 0
        with source.open("wb") as output:
            async for chunk in request.stream():
                received += len(chunk)
                if received > MAX_VIDEO_INPUT_BYTES:
                    raise HTTPException(status_code=413, detail="Video exceeds the 10 GiB limit")
                output.write(chunk)
        try:
            artifact = await run_in_threadpool(
                build_video_artifact,
                source,
                workspace,
                transcribe_audio=transcribe_audio,
                model_name=model_name,
            )
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _package_response(artifact)


@app.post("/v1/search")
def search_package(
    package: Annotated[
        bytes,
        Body(media_type="application/vnd.ericsson.knowledge-package"),
    ],
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    try:
        return search_knowledge_package(package, q, limit=limit)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
