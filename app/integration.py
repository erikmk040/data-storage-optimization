"""Framework-independent integration contract for Ericsson knowledge packages.

Streamlit and the HTTP API are adapters around this module.  Ericsson can use
the functions directly in a Python worker, or deploy ``app.api`` as a sidecar
without importing Streamlit or writing uploaded documents to disk.
"""

from __future__ import annotations

import hashlib
import gzip
import json
import lzma
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.pdf_semantic import package_pdf_semantic, read_semantic_pdf_graph
from app.pptx_semantic import package_pptx_semantic, read_semantic_pptx_graph
from src.savings.pack import pack
from src.video.package import build_package


MAX_INPUT_BYTES = 200 * 1024 * 1024
MAX_QUERY_CHARACTERS = 500
EXACT_MAGIC = b"KEX1"
EXACT_CODEC_MARKERS = {"brotli": b"B", "xz": b"X", "zstd": b"Z", "gzip": b"G"}


@dataclass(frozen=True)
class KnowledgeArtifact:
    """A transport-neutral result suitable for object storage or a message bus."""

    payload: bytes
    kind: Literal["pdf", "pptx", "video", "exact"]
    codec: str
    original_bytes: int
    package_bytes: int
    source_sha256: str
    package_sha256: str
    fidelity: str
    units: int
    text_characters: int
    reversible: bool
    searchable: bool
    ai_ready: bool
    component_bytes: dict[str, int] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()

    @property
    def saved_bytes(self) -> int:
        return self.original_bytes - self.package_bytes

    @property
    def saved_percent(self) -> float:
        if not self.original_bytes:
            return 0.0
        return self.saved_bytes / self.original_bytes * 100

    def metadata(self) -> dict[str, Any]:
        transcript_bytes = self.component_bytes.get("text", 0)
        graph_manifest_bytes = self.component_bytes.get(
            "semantic_graph_uncompressed", transcript_bytes
        )
        reference_bytes = self.component_bytes.get("references", 0)
        unique_visual_bytes = self.component_bytes.get(
            "frames", self.component_bytes.get("embedded_media_uncompressed", 0)
        )
        deduplicated_bytes = self.component_bytes.get("dedup_removed", 0)
        archive_header_overhead = self.component_bytes.get("container_header", 0)
        return {
            "kind": self.kind,
            "codec": self.codec,
            "original_bytes": self.original_bytes,
            "package_bytes": self.package_bytes,
            "saved_bytes": self.saved_bytes,
            "saved_percent": self.saved_percent,
            "source_sha256": self.source_sha256,
            "package_sha256": self.package_sha256,
            "fidelity": self.fidelity,
            "units": self.units,
            "text_characters": self.text_characters,
            "reversible": self.reversible,
            "searchable": self.searchable,
            "ai_ready": self.ai_ready,
            "largest_component": max(
                self.component_bytes,
                key=self.component_bytes.get,
                default="none",
            ),
            "component_bytes": dict(self.component_bytes),
            "transcript_bytes": transcript_bytes,
            "graph_manifest_bytes": graph_manifest_bytes,
            "reference_bytes": reference_bytes,
            "unique_visual_bytes": unique_visual_bytes,
            "deduplicated_bytes": deduplicated_bytes,
            "archive_header_overhead": archive_header_overhead,
            "limitations": list(self.limitations),
        }


def _validate_input(data: bytes) -> None:
    if not data:
        raise ValueError("The input document is empty")
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError(f"Input exceeds the {MAX_INPUT_BYTES // (1024 * 1024)} MiB limit")


def _exact_candidates(data: bytes) -> dict[str, bytes]:
    candidates = {
        "gzip-9": gzip.compress(data, compresslevel=9, mtime=0),
        "xz-9e": lzma.compress(data, format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME),
    }
    try:
        import brotli

        candidates["brotli-11"] = brotli.compress(data, quality=11, lgwin=24)
    except ImportError:
        pass
    try:
        import zstandard as zstd

        candidates["zstd-22"] = zstd.ZstdCompressor(level=22).compress(data)
    except (ImportError, ValueError):
        pass
    return candidates


def restore_exact_artifact(package: bytes) -> bytes:
    """Restore and integrity-check an exact-file package."""
    header_size = len(EXACT_MAGIC) + 1 + 8 + 32
    if len(package) <= header_size or not package.startswith(EXACT_MAGIC):
        raise ValueError("Invalid exact-file package")
    marker = package[len(EXACT_MAGIC):len(EXACT_MAGIC) + 1]
    family = next(
        (name for name, value in EXACT_CODEC_MARKERS.items() if value == marker),
        None,
    )
    if family is None:
        raise ValueError("Unknown exact-file codec")
    offset = len(EXACT_MAGIC) + 1
    original_size = struct.unpack(">Q", package[offset:offset + 8])[0]
    if original_size > MAX_INPUT_BYTES:
        raise ValueError("Exact-file package expands beyond the safety limit")
    expected_hash = package[offset + 8:offset + 40]
    payload = package[offset + 40:]
    if family == "gzip":
        decoder = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
        restored = decoder.decompress(payload, original_size + 1)
        restored += decoder.flush()
    elif family == "xz":
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
        restored = decoder.decompress(payload, max_length=original_size + 1)
    elif family == "brotli":
        import brotli

        decoder = brotli.Decompressor()
        chunks = []
        restored_size = 0
        for start in range(0, len(payload), 64 * 1024):
            chunk = decoder.process(payload[start:start + 64 * 1024])
            restored_size += len(chunk)
            if restored_size > original_size:
                raise ValueError("Exact-file package expands beyond its declared size")
            chunks.append(chunk)
        restored = b"".join(chunks)
    else:
        import zstandard as zstd

        restored = zstd.ZstdDecompressor().decompress(
            payload, max_output_size=original_size
        )
    if len(restored) != original_size or hashlib.sha256(restored).digest() != expected_hash:
        raise ValueError("Exact-file package integrity check failed")
    return restored


def build_exact_artifact(data: bytes) -> KnowledgeArtifact:
    """Compress arbitrary bytes and prove byte-for-byte restoration."""
    _validate_input(data)
    codec, payload = min(_exact_candidates(data).items(), key=lambda item: len(item[1]))
    family = codec.split("-", 1)[0]
    source_hash = hashlib.sha256(data).digest()
    package = (
        EXACT_MAGIC
        + EXACT_CODEC_MARKERS[family]
        + struct.pack(">Q", len(data))
        + source_hash
        + payload
    )
    if restore_exact_artifact(package) != data:
        raise ValueError("Exact-file round-trip verification failed")
    return KnowledgeArtifact(
        payload=package,
        kind="exact",
        codec=codec,
        original_bytes=len(data),
        package_bytes=len(package),
        source_sha256=source_hash.hex(),
        package_sha256=hashlib.sha256(package).hexdigest(),
        fidelity="byte-for-byte reversible original file",
        units=1,
        text_characters=0,
        reversible=True,
        searchable=False,
        ai_ready=False,
        component_bytes={
            "compressed_payload": len(payload),
            "container_header": len(package) - len(payload),
        },
        limitations=(
            "Already-compressed inputs may grow because the integrity envelope has overhead.",
        ),
    )


def build_pdf_artifact(data: bytes) -> KnowledgeArtifact:
    """Create a compact searchable package from PDF bytes, entirely in memory."""
    _validate_input(data)
    result = package_pdf_semantic(data)
    graph = read_semantic_pdf_graph(result.package)
    return KnowledgeArtifact(
        payload=result.package,
        kind="pdf",
        codec=result.codec,
        original_bytes=result.original_bytes,
        package_bytes=result.packed_bytes,
        source_sha256=result.source_sha256,
        package_sha256=result.package_sha256,
        fidelity=str(graph["fidelity"]),
        units=result.page_count,
        text_characters=result.text_characters,
        reversible=False,
        searchable=True,
        ai_ready=True,
        component_bytes={
            "semantic_graph_uncompressed": result.graph_bytes,
            "indexed_asset_identities": result.indexed_asset_bytes,
            "container_header": 6,
        },
        limitations=(
            "Original rendering and embedded image pixels are not preserved.",
            "OCR quality depends on the source document.",
        ),
    )


def build_pptx_artifact(data: bytes, *, include_media: bool = True) -> KnowledgeArtifact:
    """Create a compact searchable package from PowerPoint bytes in memory."""
    _validate_input(data)
    result = package_pptx_semantic(data, include_media=include_media)
    return KnowledgeArtifact(
        payload=result.package,
        kind="pptx",
        codec=result.codec,
        original_bytes=result.original_bytes,
        package_bytes=result.packed_bytes,
        source_sha256=result.source_sha256,
        package_sha256=result.package_sha256,
        fidelity=result.fidelity,
        units=result.slide_count,
        text_characters=result.text_characters,
        reversible=False,
        searchable=True,
        ai_ready=True,
        component_bytes={
            "semantic_graph_uncompressed": result.graph_bytes,
            "embedded_media_uncompressed": result.optimized_media_bytes,
            "container_header": 5,
        },
        limitations=(
            "The editable PowerPoint file cannot be reconstructed from semantic mode.",
            "Embedded media is preserved only when include_media is enabled.",
        ),
    )


def build_video_artifact(
    source: Path,
    workspace: Path,
    *,
    transcribe_audio: bool = True,
    model_name: str = "base",
) -> KnowledgeArtifact:
    """Build a video KP artifact from a streamed-to-disk source file.

    ``workspace`` is supplied by the host so production can place temporary
    data on an encrypted volume. The caller owns workspace cleanup.
    """
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("The input video is empty or missing")
    package_json = build_package(
        source,
        workspace / "package",
        model_name=model_name,
        transcribe_audio=transcribe_audio,
    )
    output = workspace / "recording.kp"
    report = pack(package_json, output)
    package = json.loads(package_json.read_text(encoding="utf-8"))
    payload = output.read_bytes()
    segments = package.get("segments", [])
    frames = package.get("frames", [])
    return KnowledgeArtifact(
        payload=payload,
        kind="video",
        codec=report.codec,
        original_bytes=source.stat().st_size,
        package_bytes=len(payload),
        source_sha256=str(package["source"]["sha256"]),
        package_sha256=hashlib.sha256(payload).hexdigest(),
        fidelity=(
            "searchable transcript timeline and representative keyframes; "
            "discarded motion and audio are not reversible"
        ),
        units=len(frames),
        text_characters=sum(len(str(segment.get("text", ""))) for segment in segments),
        reversible=False,
        searchable=True,
        ai_ready=True,
        component_bytes={**report.component_bytes, "container_header": 4},
        limitations=(
            "Discarded motion and original audio are not reversible.",
            "Automatic speaker diarization is not implemented.",
        ),
    )


def _snippet(text: str, query: str, *, radius: int = 100) -> str:
    compact = " ".join(text.split())
    position = compact.casefold().find(query.casefold())
    if position < 0:
        position = 0
    start = max(position - radius, 0)
    end = min(position + len(query) + radius, len(compact))
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"


def search_knowledge_package(package: bytes, query: str, *, limit: int = 20) -> dict[str, Any]:
    """Search a PDF or PowerPoint knowledge package without an external database."""
    query = query.strip()
    if not query:
        raise ValueError("Search query must not be empty")
    if len(query) > MAX_QUERY_CHARACTERS:
        raise ValueError(f"Search query exceeds {MAX_QUERY_CHARACTERS} characters")
    if not 1 <= limit <= 100:
        raise ValueError("Search limit must be between 1 and 100")

    if package.startswith(b"KPDF1"):
        graph = read_semantic_pdf_graph(package)
        kind = "pdf"
        records = [
            (
                int(page["page"]),
                f'{page.get("text", "")}\n{page.get("ocr_text", "")}',
            )
            for page in graph["pages"]
        ]
        unit_name = "page"
    elif package.startswith(b"KPS1"):
        graph = read_semantic_pptx_graph(package)
        kind = "pptx"
        records = [
            (
                int(slide["slide"]),
                "\n".join([*slide.get("text", []), *slide.get("notes", [])]),
            )
            for slide in graph["slides"]
        ]
        unit_name = "slide"
    else:
        raise ValueError("Unsupported knowledge package format")

    needle = query.casefold()
    hits = []
    for unit, text in records:
        occurrences = text.casefold().count(needle)
        if occurrences:
            hits.append(
                {
                    unit_name: unit,
                    "occurrences": occurrences,
                    "snippet": _snippet(text, query),
                }
            )
    hits.sort(key=lambda hit: (-hit["occurrences"], hit[unit_name]))
    return {"kind": kind, "query": query, "total_hits": len(hits), "hits": hits[:limit]}
