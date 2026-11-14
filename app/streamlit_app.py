import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hashlib
import io
import json
import mimetypes
import shutil
import subprocess
import tempfile
from typing import Any

import streamlit as st
from app.evidence import load_benchmark_evidence
from app.integration import build_exact_artifact
from app.pdf_semantic import package_pdf_semantic, read_semantic_pdf_graph
from app.pptx_semantic import package_pptx_semantic, read_semantic_pptx_graph
from src.search.index import index_package
from src.search.make_mock import make
from src.search.query import search
from src.savings.pack import pack
from src.video.package import build_package

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}

st.set_page_config(
    page_title="Ericsson Knowledge Compression",
    page_icon=":material/database:",
    layout="wide",
)

@st.cache_resource
def ensure_demo_index() -> str:
    """Create a small portable demo index when running on a fresh host."""
    package_path = Path("data/sample/rec_mock/package.json")
    # Rebuild the tiny demo deterministically so a persistent cloud volume
    # cannot keep an older package or stale FTS rows after an app update.
    make(package_path.parent)
    index_package(package_path)
    jury_package = Path("data/sample/jury_prizes/package.json")
    if jury_package.is_file():
        try:
            index_package(jury_package)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            # Optional local evidence must never prevent the clean demo index
            # from starting. Its integrity is validated separately below.
            pass
    return str(package_path)


def uploaded_search_results(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search the demo index and all semantic packages created in this session."""
    results = search(query)
    searched_databases: set[str] = set()
    for measurement in st.session_state.get("upload_measurements", {}).values():
        database = measurement.get("search_db")
        if database and database not in searched_databases and Path(database).is_file():
            searched_databases.add(database)
            results.extend(search(query, db_path=Path(database)))
    return sorted(results, key=lambda item: item.get("score", 0))[:limit]


def measured_savings(original_bytes: int, output_bytes: int) -> tuple[int, float]:
    """Return the signed byte and percentage change for measured data."""
    saved_bytes = original_bytes - output_bytes
    saved_percent = (saved_bytes / original_bytes * 100) if original_bytes else 0.0
    return saved_bytes, saved_percent


@st.cache_data(max_entries=128, show_spinner=False)
def load_search_frame(path: str, modified_ns: int) -> bytes:
    """Read a result frame into Streamlit instead of exposing a fragile path."""
    del modified_ns  # Included only to invalidate the cache when the file changes.
    return Path(path).read_bytes()


@st.cache_data
def prepared_jury_measurement() -> dict[str, Any] | None:
    """Return the optional local artifact only when it matches release evidence."""
    try:
        evidence = load_benchmark_evidence(verify_local_files=True)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    kp_path = Path(evidence["local_paths"]["package"])
    if not evidence["local_files_verified"]:
        return None
    source = evidence["source"]
    package = evidence["package"]
    content = evidence["content"]
    return {
        "file": source["file"],
        "original_bytes": source["bytes"],
        "compressed_bytes": package["bytes"],
        "saved_bytes": evidence["saved_bytes"],
        "saved_percent": evidence["saved_percent"],
        "sha256": source["sha256"][:16],
        "kp_path": str(kp_path.resolve()),
        "facts": {
            "mode": "prepared semantic video demo",
            "duration": f"{float(source['duration_seconds']):.1f} s",
            "transcript segments": content["transcript_segments"],
            "unique frames": content["representative_frames"],
            "source SHA-256": source["sha256"],
        },
    }


@st.cache_data
def storage_report(package_path: str) -> dict:
    """Build a compact demo artifact and return presentation-ready metrics."""
    package = Path(package_path)
    kp_path = package.parent / "rec_mock.kp"
    report = pack(package, kp_path)
    source = json.loads(package.read_text(encoding="utf-8"))["source"]
    source_file = package.parent / str(source.get("file", ""))
    source_available = source_file.is_file()
    if source_available:
        original = source_file.stat().st_size
        basis = "actual source recording"
    else:
        # A mock package may contain a representative source size in metadata
        # without containing the original video. Never present that metadata
        # as a measured 1 GB recording.
        original = package.stat().st_size + sum(
            path.stat().st_size
            for path in (package.parent / "frames").glob("*")
            if path.is_file()
        )
        basis = "files present in the demo package (source video not included)"
    compact = report.packed_bytes
    saved, saved_percent = measured_savings(original, compact)
    return {
        "original_bytes": original,
        "compact_bytes": compact,
        "saved_bytes": saved,
        "saved_percent": saved_percent,
        "codec": report.codec,
        "components": report.component_bytes,
        "basis": basis,
        "source_available": source_available,
    }


package_path = Path(ensure_demo_index())
try:
    storage = storage_report(str(package_path))
except Exception as error:
    storage = None
    st.warning(f"Storage metrics unavailable: {error}")


def format_bytes(value: int | float) -> str:
    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def format_percent(value: float, *, output_bytes: int | None = None) -> str:
    """Format a percentage without rounding a non-empty output to 100.00%."""
    if output_bytes and 99.995 <= value < 100:
        return ">99.99%"
    return f"{value:.2f}%"


def savings_label(saved_bytes: int) -> str:
    """Describe a signed storage change without hiding growth."""
    return "Saved" if saved_bytes >= 0 else "Size increase"


def clear_session_uploads() -> None:
    """Remove generated session artifacts and their cached measurements."""
    temporary_root = Path(tempfile.gettempdir()).resolve()
    generated_roots: set[Path] = set()
    for measurement in st.session_state.get("upload_measurements", {}).values():
        for field in ("search_db", "kp_path"):
            value = measurement.get(field)
            if not value:
                continue
            candidate_root = Path(value).resolve().parent
            if (
                candidate_root.is_relative_to(temporary_root)
                and candidate_root.name.startswith(
                    ("uploaded-recording-", "uploaded-presentation-", "uploaded-document-")
                )
            ):
                generated_roots.add(candidate_root)
    for root in generated_roots:
        shutil.rmtree(root, ignore_errors=True)
    st.session_state.pop("upload_measurements", None)
    st.session_state.pop("latest_measurements", None)


def inspect_uploaded_file(name: str, data: bytes) -> dict[str, Any]:
    """Return measured compression and content metadata for one uploaded file."""
    artifact = build_exact_artifact(data)
    suffix = Path(name).suffix.lower()
    facts: dict[str, Any] = {"type": mimetypes.guess_type(name)[0] or "unknown"}
    if suffix == ".pdf":
        try:
            import pymupdf
            document = pymupdf.open(stream=data, filetype="pdf")
            facts["pages"] = len(document)
            facts["text characters"] = sum(len(page.get_text()) for page in document)
            document.close()
        except Exception:
            facts["pages"] = "unavailable"
    elif suffix == ".pptx":
        try:
            from pptx import Presentation
            presentation = Presentation(io.BytesIO(data))
            facts["slides"] = len(presentation.slides)
            facts["text characters"] = sum(
                len(shape.text)
                for slide in presentation.slides
                for shape in slide.shapes
                if hasattr(shape, "text")
            )
        except Exception:
            facts["slides"] = "unavailable"
    elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as image:
                facts["dimensions"] = f"{image.width} × {image.height}"
                facts["mode"] = image.mode
        except Exception:
            facts["dimensions"] = "unavailable"
    elif suffix in {".txt", ".md", ".json", ".csv"}:
        try:
            facts["UTF-8 characters"] = len(data.decode("utf-8"))
        except UnicodeDecodeError:
            facts["UTF-8 characters"] = "not UTF-8"
    elif suffix in VIDEO_SUFFIXES and shutil.which("ffprobe"):
        with tempfile.NamedTemporaryFile(suffix=suffix) as temporary:
            temporary.write(data)
            temporary.flush()
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", temporary.name],
                    check=True, capture_output=True, text=True, timeout=20,
                )
                facts["duration"] = f"{float(result.stdout.strip()):.1f} s"
            except (subprocess.SubprocessError, ValueError):
                facts["duration"] = "unavailable"
    facts.update(
        {
            "mode": "exact lossless file compression",
            "fidelity": artifact.fidelity,
            "integrity verified": True,
            "source SHA-256": artifact.source_sha256,
            "package SHA-256": artifact.package_sha256,
            "original file reconstruction": True,
        }
    )
    return {
        "file": name,
        "original_bytes": len(data),
        "compressed_bytes": artifact.package_bytes,
        "saved_bytes": artifact.saved_bytes,
        "saved_percent": artifact.saved_percent,
        "codec": f"Exact KP/{artifact.codec}",
        "sha256": hashlib.sha256(data).hexdigest()[:16],
        "kp_bytes": artifact.payload,
        "candidate_bytes": {},
        "component_kind": "exact",
        "components": {
            **artifact.component_bytes,
            "final": artifact.package_bytes,
        },
        "facts": facts,
    }


def compress_uploaded_video(name: str, data: bytes) -> dict[str, Any]:
    """Run and retain the real video-to-KP pipeline for one uploaded video."""
    source_hash = hashlib.sha256(data).hexdigest()
    try:
        evidence = load_benchmark_evidence(verify_local_files=True)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        evidence = None
    evidence_source = evidence["source"] if evidence else None
    if (
        evidence
        and evidence["local_files_verified"]
        and len(data) == evidence_source["bytes"]
        and source_hash == evidence_source["sha256"]
    ):
        package_json = Path(evidence["local_paths"]["metadata"])
        kp_path = Path(evidence["local_paths"]["package"])
        package = json.loads(package_json.read_text(encoding="utf-8"))
        return {
            "file": name,
            "original_bytes": len(data),
            "compressed_bytes": evidence["package"]["bytes"],
            "saved_bytes": evidence["saved_bytes"],
            "saved_percent": evidence["saved_percent"],
            "codec": f"KP v2/{evidence['package']['codec']}",
            "sha256": source_hash[:16],
            "kp_path": str(kp_path.resolve()),
            "component_kind": "video",
            "facts": {
                "mode": "semantic video compression · verified prepared artifact",
                "segments": len(package.get("segments", [])),
                "unique frames": len(package.get("frames", [])),
                "searchable": True,
                "transcript": "UTF-8 text",
                "source SHA-256": source_hash,
                "package SHA-256": evidence["package"]["sha256"],
                "prepared artifact reused": True,
                "speaker diarization": False,
            },
        }

    suffix = Path(name).suffix.lower()
    root = Path(tempfile.mkdtemp(prefix="uploaded-recording-"))
    try:
        source = root / f"source{suffix}"
        package_dir = root / "package"
        kp_path = root / "recording.kp"
        source.write_bytes(data)
        package_json = build_package(source, package_dir, transcribe_audio=True)
        report = pack(package_json, kp_path)
        search_db = root / "index.db"
        index_package(package_json, db_path=search_db)
        package = json.loads(package_json.read_text(encoding="utf-8"))
        compressed = kp_path.stat().st_size
        return {
            "file": name,
            "original_bytes": len(data),
            "compressed_bytes": compressed,
            "saved_bytes": measured_savings(len(data), compressed)[0],
            "saved_percent": measured_savings(len(data), compressed)[1],
            "codec": f"KP v2/{report.codec}",
            "sha256": hashlib.sha256(data).hexdigest()[:16],
            "search_db": str(search_db),
            "kp_path": str(kp_path),
            "component_kind": "video",
            "components": {
                **report.component_bytes,
                "container_header": 4,
                "final": compressed,
            },
            "facts": {
                "mode": "semantic video compression",
                "segments": len(package.get("segments", [])),
                "unique frames": len(package.get("frames", [])),
                "searchable": True,
                "transcript": "UTF-8 text",
                "component accounting": (
                    "Components are uncompressed archive inputs; whole-archive compression "
                    "means they do not add up to the final KP bytes."
                ),
            },
        }
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def compress_uploaded_pptx(name: str, data: bytes, *, include_media: bool) -> dict[str, Any]:
    """Create a verified semantic slide graph and retain its downloadable bytes."""
    result = package_pptx_semantic(data, include_media=include_media)
    graph = read_semantic_pptx_graph(result.package)
    package_root = Path(tempfile.mkdtemp(prefix="uploaded-presentation-"))
    recording_id = f"pptx_{result.source_sha256[:16]}"
    package_json = package_root / "package.json"
    frames = []
    segments = []
    slide_hashes: dict[str, list[int]] = {}
    for slide in graph["slides"]:
        slide_number = int(slide["slide"])
        visible_text = "\n".join(value for value in slide["text"] if value.strip())
        notes = "\n".join(value for value in slide["notes"] if value.strip())
        frame_id = f"slide-{slide_number}"
        content_hash = str(slide["content_sha256"])
        slide_hashes.setdefault(content_hash, []).append(slide_number)
        frames.append(
            {
                "id": frame_id,
                "t": float(slide_number - 1),
                "file": f"frames/{frame_id}.webp",
                "phash": None,
                "ocr_text": visible_text,
                "slide_ref": {
                    "doc_id": recording_id,
                    "slide_no": slide_number,
                    "slide_hash": content_hash,
                },
            }
        )
        segments.append(
            {
                "start": float(slide_number - 1),
                "end": float(slide_number),
                "speaker": None,
                "text": notes,
                "frame_id": frame_id,
            }
        )
    search_package = {
        "id": recording_id,
        "source": {
            "file": name,
            "sha256": result.source_sha256,
            "duration_s": float(result.slide_count),
            "size_bytes": len(data),
        },
        "segments": segments,
        "frames": frames,
    }
    package_json.write_text(
        json.dumps(search_package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    search_db = package_root / "index.db"
    index_package(package_json, db_path=search_db)
    internal_duplicates = sum(len(slides) - 1 for slides in slide_hashes.values())
    return {
        "file": name,
        "original_bytes": result.original_bytes,
        "compressed_bytes": result.packed_bytes,
        "saved_bytes": result.saved_bytes,
        "saved_percent": result.saved_percent,
        "codec": f"KP semantic PPTX/{result.codec}",
        "sha256": result.source_sha256[:16],
        "kp_bytes": result.package,
        "ascii_bytes": result.ascii_package,
        "search_db": str(search_db),
        "slide_hashes": slide_hashes,
        "candidate_bytes": result.candidate_bytes,
        "components": {
            "graph": result.graph_bytes,
            "source_media": result.source_media_bytes,
            "optimized_media": result.optimized_media_bytes,
            "final": result.packed_bytes,
            "container_header": 5,
        },
        "component_kind": "pptx",
        "facts": {
            "mode": "semantic presentation compression",
            "fidelity": result.fidelity,
            "slides": result.slide_count,
            "text characters": result.text_characters,
            "unique media assets": result.asset_count,
            "exact duplicates removed": result.duplicate_assets,
            "duplicate slides in this presentation": internal_duplicates,
            "searchable in this session": True,
            "integrity verified": True,
            "under 100 KB target": result.packed_bytes <= 100 * 1024,
            "source SHA-256": result.source_sha256,
            "package SHA-256": result.package_sha256,
            "editable PowerPoint reconstruction": False,
            "ASCII export overhead": (
                f"{(len(result.ascii_package) / result.packed_bytes - 1) * 100:.2f}%"
            ),
        },
    }


def compress_uploaded_pdf(name: str, data: bytes) -> dict[str, Any]:
    """Create a verified, searchable knowledge package from a PDF."""
    result = package_pdf_semantic(data)
    graph = read_semantic_pdf_graph(result.package)
    package_root = Path(tempfile.mkdtemp(prefix="uploaded-document-"))
    recording_id = f"pdf_{result.source_sha256[:16]}"
    package_json = package_root / "package.json"
    frames = []
    page_hashes: dict[str, list[int]] = {}
    for page in graph["pages"]:
        page_number = int(page["page"])
        frame_id = f"page-{page_number}"
        content_hash = str(page["text_sha256"])
        searchable_text = page["text"]
        if page.get("ocr_text"):
            searchable_text += "\n" + page["ocr_text"]
        page_hashes.setdefault(content_hash, []).append(page_number)
        frames.append(
            {
                "id": frame_id,
                "t": float(page_number - 1),
                "file": f"frames/{frame_id}.webp",
                "phash": None,
                "ocr_text": searchable_text,
                "slide_ref": {
                    "doc_id": recording_id,
                    "slide_no": page_number,
                    "slide_hash": content_hash,
                },
            }
        )
    search_package = {
        "id": recording_id,
        "source": {
            "file": name,
            "sha256": result.source_sha256,
            "duration_s": float(result.page_count),
            "size_bytes": len(data),
        },
        "segments": [],
        "frames": frames,
    }
    package_json.write_text(
        json.dumps(search_package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    search_db = package_root / "index.db"
    index_package(package_json, db_path=search_db)
    duplicate_pages = sum(len(pages) - 1 for pages in page_hashes.values())
    return {
        "file": name,
        "original_bytes": result.original_bytes,
        "compressed_bytes": result.packed_bytes,
        "saved_bytes": result.saved_bytes,
        "saved_percent": result.saved_percent,
        "codec": f"KP semantic PDF/{result.codec}",
        "sha256": result.source_sha256[:16],
        "kp_bytes": result.package,
        "search_db": str(search_db),
        "slide_hashes": page_hashes,
        "unit_label": "page",
        "candidate_bytes": result.candidate_bytes,
        "components": {
            "graph": result.graph_bytes,
            "source_media": result.indexed_asset_bytes,
            "optimized_media": 0,
            "final": result.packed_bytes,
            "container_header": 6,
        },
        "component_kind": "pdf",
        "facts": {
            "mode": "semantic PDF knowledge compression",
            "fidelity": graph["fidelity"],
            "pages": result.page_count,
            "text characters": result.text_characters,
            "OCR-enhanced sparse pages": result.ocr_page_count,
            "indexed image identities": result.asset_count,
            "embedded image bytes referenced by hash": result.indexed_asset_bytes,
            "duplicate embedded image occurrences": result.duplicate_assets,
            "duplicate text pages": duplicate_pages,
            "searchable in this session": True,
            "integrity verified": True,
            "under 100 KB target": result.packed_bytes <= 100 * 1024,
            "source SHA-256": result.source_sha256,
            "package SHA-256": result.package_sha256,
            "original PDF reconstruction": False,
        },
    }


st.title("Ericsson Knowledge Compression", icon=":material/database:")
st.caption(
    "A deployable compression and search layer for recordings and documents — with a Streamlit client for the demo."
)
st.markdown(
    ":green-badge[Measured outputs] :blue-badge[REST/OpenAPI ready] "
    ":gray-badge[SHA-256 verified]"
)

with st.container(border=True):
    st.markdown("#### From source file to reusable knowledge")
    flow = st.columns(4)
    for column, title, detail in zip(
        flow,
        ("01 · Ingest", "02 · Distill", "03 · Package", "04 · Activate"),
        (
            "Video and documents",
            "Text, timing and unique visuals",
            "Verified compact .kp",
            "Search, storage and AI",
        ),
    ):
        with column:
            st.markdown(f"**{title}**")
            st.caption(detail)

upload_tab, search_tab, impact_tab, coverage_tab, story_tab = st.tabs(
    [
        "Measure your files",
        "Search the knowledge",
        "Storage calculator",
        "Challenge coverage",
        "How to pitch it",
    ]
)

with search_tab:
    st.info("Demo index ready · try: **storage**, **duplicate files**, or **winner**")
    q = st.text_input("Search for a topic", placeholder="e.g. duplicate files", key="search_query")
    if q:
        results = uploaded_search_results(q)
        st.caption(f"{len(results)} hits · text and visual context returned together")
        for r in results:
            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                fr = r["frame"]
                with c1:
                    frame_path = Path(fr["file"]).resolve() if fr and fr.get("file") else None
                    if frame_path and frame_path.is_file():
                        try:
                            st.image(
                                load_search_frame(
                                    str(frame_path), frame_path.stat().st_mtime_ns
                                ),
                                width="stretch",
                                alt="Frame returned with the search result",
                            )
                        except OSError:
                            st.caption("The frame could not be read from storage.")
                    else:
                        st.caption("Reference frame · render from source registry")
                with c2:
                    mm, ss = divmod(int(r["start"]), 60)
                    result_title = r.get("source_file") or r["rec_id"]
                    st.markdown(
                        f"**{result_title}** · {mm:02d}:{ss:02d} · "
                        f"{r['speaker'] or '-'} · _{r['kind']}_"
                    )
                    st.markdown(r["snippet"].replace("[", "**").replace("]", "**"))
                    if fr and fr.get("doc_id"):
                        st.caption(f"Slide {fr['slide_no']} in {fr['doc_id']}")

with upload_tab:
    st.subheader("Measure real files", icon=":material/compress:")
    st.caption(
        "Upload, choose the fidelity policy and compress. Every displayed byte and percentage is measured from the uploaded data."
    )
    prepared_demo = prepared_jury_measurement()
    benchmark_evidence = load_benchmark_evidence()
    if prepared_demo:
        with st.container(border=True):
            st.markdown("#### Jury-safe real-video demo")
            st.caption(
                "The same 88.7 MB recording is already processed, so the live demo does not depend on a long upload or transcription run."
            )
            prepared_columns = st.columns(4)
            prepared_columns[0].metric(
                "Original video", format_bytes(prepared_demo["original_bytes"])
            )
            prepared_columns[1].metric(
                "Knowledge package", format_bytes(prepared_demo["compressed_bytes"])
            )
            prepared_columns[2].metric(
                "Storage saved", format_bytes(prepared_demo["saved_bytes"])
            )
            prepared_columns[3].metric(
                "Reduction",
                format_percent(
                    prepared_demo["saved_percent"],
                    output_bytes=prepared_demo["compressed_bytes"],
                ),
            )
            st.caption(
                "The package was re-hashed and its source metadata matches the evidence manifest. The original video is not distributed. Search for **winner** to show transcript and visual context."
            )
            st.download_button(
                "Download prepared .kp package",
                data=Path(prepared_demo["kp_path"]).read_bytes(),
                file_name="Jury-and-prizes.kp",
                mime="application/vnd.ericsson.knowledge-package",
                icon=":material/download:",
                key="download_prepared_jury_package",
            )
    else:
        st.info(
            "The optional real-video artifact is not bundled in a clean checkout. "
            "The app remains fully demonstrable with deterministic mock search; the result slide is labelled local benchmark evidence.",
            title="Clean-checkout demo mode",
            icon=":material/cloud_done:",
        )
    if st.session_state.get("upload_measurements"):
        st.button(
            "Clear processed session files",
            icon=":material/delete_sweep:",
            on_click=clear_session_uploads,
            key="clear_uploads",
        )
    uploads = st.file_uploader(
        "Upload recordings, PDFs, presentations, images or text files",
        type=[
            "mp4", "mov", "m4v", "mkv", "webm", "avi", "pdf", "pptx",
            "png", "jpg", "jpeg", "webp", "txt", "md", "json", "csv", "zip",
        ],
        accept_multiple_files=True,
        help=(
            "Documents are processed in memory. Videos use an isolated temporary workspace. "
            "Session artifacts are not added to the repository."
        ),
        max_upload_size=200,
        key="file_uploads_v2",
    )
    st.caption(
        "Demo upload limit: 200 MB per file. The production API streams video up to 10 GiB without loading the complete source into memory."
    )
    if uploads:
        unique_uploads = []
        seen_uploads: set[tuple[str, str]] = set()
        duplicate_uploads = 0
        for upload in uploads:
            identity = (
                upload.name,
                hashlib.sha256(upload.getbuffer()).hexdigest(),
            )
            if identity in seen_uploads:
                duplicate_uploads += 1
                continue
            seen_uploads.add(identity)
            unique_uploads.append(upload)
        uploads = unique_uploads
        if duplicate_uploads:
            st.info(
                f"Ignored {duplicate_uploads} repeated selection(s) of the same file.",
                title="Duplicate upload selection",
                icon=":material/content_copy:",
            )
        video_uploads = [
            upload for upload in uploads
            if Path(upload.name).suffix.lower() in VIDEO_SUFFIXES
        ]
        pptx_uploads = [upload for upload in uploads if Path(upload.name).suffix.lower() == ".pptx"]
        pdf_uploads = [upload for upload in uploads if Path(upload.name).suffix.lower() == ".pdf"]
        semantic_video = True
        presentation_mode = "Knowledge + lossless visuals"
        pdf_mode = "Searchable knowledge (maximum reduction)"
        offer_ascii = False
        if video_uploads:
            semantic_video = st.checkbox(
                "Run semantic video compression (transcript + keyframes + KP package)",
                value=True,
                help="This produces the actual challenge output. It can take several minutes for a long video.",
                key="semantic_video_mode",
            )
            if semantic_video:
                st.warning(
                    "Semantic video mode keeps transcript timing and representative keyframes; "
                    "original audio and discarded motion cannot be reconstructed. Automatic speaker diarization is not implemented.",
                    title="Semantic video changes the artifact",
                    icon=":material/movie_edit:",
                )
        if pptx_uploads:
            presentation_mode = st.segmented_control(
                "PowerPoint quality policy",
                ["Knowledge + lossless visuals", "Maximum reduction", "Exact PowerPoint file"],
                default="Knowledge + lossless visuals",
                key="presentation_quality_policy",
                help=(
                    "Lossless visuals keeps exact text, geometry, notes, relationships, and pixel-identical media. "
                    "Maximum reduction keeps the knowledge graph without media. Exact PowerPoint preserves every file byte."
                ),
            )
            offer_ascii = st.checkbox(
                "Offer ASCII/Base85 export too",
                value=False,
                disabled=presentation_mode == "Exact PowerPoint file",
                help="ASCII is export-only and about 25% larger than the selected binary KP package.",
                key="ascii_export",
            )
            if presentation_mode != "Exact PowerPoint file":
                media_statement = (
                    "Pixel-identical embedded media is included."
                    if presentation_mode == "Knowledge + lossless visuals"
                    else "Embedded media pixels are omitted for maximum reduction."
                )
                st.warning(
                    "Semantic PowerPoint mode keeps text, notes, shape geometry and relationships. "
                    f"{media_statement} The editable original PowerPoint cannot be reconstructed.",
                    title="Semantic PowerPoint changes the artifact",
                    icon=":material/slideshow:",
                )
        if pdf_uploads:
            pdf_mode = st.segmented_control(
                "PDF quality policy",
                ["Searchable knowledge (maximum reduction)", "Exact PDF file"],
                default="Searchable knowledge (maximum reduction)",
                key="pdf_quality_policy",
                help=(
                    "Searchable knowledge keeps extracted text, page order and geometry, links, source identity, "
                    "and hashes for embedded images. Exact PDF preserves every original byte but saves much less space."
                ),
            )
            if pdf_mode == "Searchable knowledge (maximum reduction)":
                st.warning(
                    "This mode preserves the searchable knowledge layer, not the original page rendering or image pixels.",
                    title="Maximum reduction changes the artifact",
                    icon=":material/compress:",
                )
        elif not video_uploads and not pptx_uploads:
            st.info(
                "This file type uses exact lossless byte compression. Upload a PDF, PowerPoint or video to use a semantic knowledge mode.",
                title="Exact mode for this file type",
                icon=":material/info:",
            )
        run_compression = st.button(
            "Compress uploaded files",
            type="primary",
            icon=":material/compress:",
            width="stretch",
            key="compress_uploads",
        )
        measurements = []
        upload_cache = st.session_state.setdefault("upload_measurements", {})
        for upload in uploads:
            data = upload.getvalue()
            content_hash = hashlib.sha256(data).hexdigest()
            is_video = Path(upload.name).suffix.lower() in VIDEO_SUFFIXES
            is_pptx = Path(upload.name).suffix.lower() == ".pptx"
            is_pdf = Path(upload.name).suffix.lower() == ".pdf"
            cache_mode = (
                "semantic-video" if is_video and semantic_video
                else str(presentation_mode) if is_pptx
                else str(pdf_mode) if is_pdf
                else "lossless-bytes"
            )
            upload_key = f"{content_hash}:{cache_mode}"
            if is_video and semantic_video:
                if upload_key in upload_cache:
                    measurements.append(upload_cache[upload_key])
                    continue
                if not run_compression:
                    st.info("Click **Compress uploaded files** to run the real video distillation pipeline.")
                    continue
                with st.status(f"Distilling {upload.name}…", expanded=False) as status:
                    try:
                        measurement = compress_uploaded_video(upload.name, data)
                        status.update(label=f"Finished {upload.name}", state="complete")
                    except Exception as error:
                        status.update(label=f"Could not distill {upload.name}", state="error")
                        st.error(str(error))
                        measurement = inspect_uploaded_file(upload.name, data)
                        measurement["facts"]["mode"] = "lossless byte compression fallback"
                upload_cache[upload_key] = measurement
                measurements.append(measurement)
            elif is_pptx and presentation_mode != "Exact PowerPoint file":
                if upload_key in upload_cache:
                    measurements.append(upload_cache[upload_key])
                    continue
                if not run_compression:
                    st.info(
                        "Click **Compress uploaded files** to build the verified slide graph and run the codec tournament."
                    )
                    continue
                with st.status(f"Optimizing {upload.name}…", expanded=False) as status:
                    try:
                        upload_cache[upload_key] = compress_uploaded_pptx(
                            upload.name,
                            data,
                            include_media=presentation_mode == "Knowledge + lossless visuals",
                        )
                        status.update(label=f"Finished {upload.name}", state="complete")
                    except Exception as error:
                        status.update(label=f"Could not optimize {upload.name}", state="error")
                        st.error(str(error))
                        upload_cache[upload_key] = inspect_uploaded_file(upload.name, data)
                        upload_cache[upload_key]["facts"]["mode"] = "lossless byte compression fallback"
                measurements.append(upload_cache[upload_key])
            elif is_pdf and pdf_mode != "Exact PDF file":
                if upload_key in upload_cache:
                    measurements.append(upload_cache[upload_key])
                    continue
                if not run_compression:
                    st.info(
                        "Click **Compress uploaded files** to extract the searchable PDF knowledge graph and run the codec tournament."
                    )
                    continue
                with st.status(f"Extracting knowledge from {upload.name}…", expanded=False) as status:
                    try:
                        upload_cache[upload_key] = compress_uploaded_pdf(upload.name, data)
                        status.update(label=f"Finished {upload.name}", state="complete")
                    except Exception as error:
                        status.update(label=f"Could not extract {upload.name}", state="error")
                        st.error(str(error))
                        upload_cache[upload_key] = inspect_uploaded_file(upload.name, data)
                        upload_cache[upload_key]["facts"]["mode"] = "lossless byte compression fallback"
                measurements.append(upload_cache[upload_key])
            else:
                if upload_key in upload_cache:
                    measurements.append(upload_cache[upload_key])
                    continue
                if not run_compression:
                    st.info(
                        "Click **Compress uploaded files** to build and verify the byte-for-byte reversible package."
                    )
                    continue
                with st.status(f"Compressing {upload.name}…", expanded=False) as status:
                    try:
                        upload_cache[upload_key] = inspect_uploaded_file(upload.name, data)
                        status.update(label=f"Finished {upload.name}", state="complete")
                    except Exception as error:
                        status.update(label=f"Could not compress {upload.name}", state="error")
                        st.error(str(error))
                        continue
                measurements.append(upload_cache[upload_key])
        if measurements:
            st.session_state["latest_measurements"] = measurements
            total_original = sum(item["original_bytes"] for item in measurements)
            total_compressed = sum(item["compressed_bytes"] for item in measurements)
            total_saved, total_saved_percent = measured_savings(total_original, total_compressed)
            st.success(f"Measured {len(measurements)} file(s) using actual uploaded data.")
            metrics = st.columns(4)
            metrics[0].metric("Original", format_bytes(total_original), border=True)
            metrics[1].metric("Compressed", format_bytes(total_compressed), border=True)
            metrics[2].metric(savings_label(total_saved), format_bytes(abs(total_saved)), border=True)
            metrics[3].metric(
                "Reduction" if total_saved >= 0 else "Increase",
                format_percent(abs(total_saved_percent), output_bytes=total_compressed),
                border=True,
            )
            slide_occurrences: dict[str, list[str]] = {}
            for item in measurements:
                unit = item.get("unit_label", "slide")
                for slide_hash, slide_numbers in item.get("slide_hashes", {}).items():
                    slide_occurrences.setdefault(slide_hash, []).extend(
                        f"{item['file']} · {unit} {number}" for number in slide_numbers
                    )
            duplicate_slides = [
                {"Copies": len(locations), "Locations": " · ".join(locations)}
                for locations in slide_occurrences.values()
                if len(locations) > 1
            ]
            if duplicate_slides:
                st.info(
                    f"Found {sum(row['Copies'] - 1 for row in duplicate_slides)} duplicate page or slide copies.",
                    title="Page/slide-level deduplication opportunity",
                    icon=":material/content_copy:",
                )
                st.dataframe(
                    duplicate_slides,
                    hide_index=True,
                    width="stretch",
                    alt="Duplicate slides and their source locations",
                )
            st.dataframe(
                [
                    {
                        "File": item["file"],
                        "Original": format_bytes(item["original_bytes"]),
                        "Compressed": format_bytes(item["compressed_bytes"]),
                        "Storage change": (
                            f"Saved {format_bytes(item['saved_bytes'])}"
                            if item["saved_bytes"] >= 0
                            else f"Increased {format_bytes(abs(item['saved_bytes']))}"
                        ),
                        "Change": (
                            f"{format_percent(item['saved_percent'], output_bytes=item['compressed_bytes'])} reduction"
                            if item["saved_bytes"] >= 0
                            else f"{format_percent(abs(item['saved_percent']))} increase"
                        ),
                        "Codec": item["codec"],
                    }
                    for item in measurements
                ],
                width="stretch",
                hide_index=True,
                alt="Compression results for uploaded files",
            )
            for item_index, item in enumerate(measurements):
                element_suffix = f"{item['sha256']}_{item_index}"
                with st.expander(f"{item['file']} · SHA-256 {item['sha256']}"):
                    st.json(item["facts"])
                    if item.get("components"):
                        components = item["components"]
                        component_kind = item.get("component_kind")
                        if component_kind in {"pdf", "pptx"}:
                            if component_kind == "pdf":
                                breakdown = [
                                    {"Component": "Original file", "Bytes": item["original_bytes"]},
                                    {"Component": "Page knowledge graph", "Bytes": components["graph"]},
                                    {"Component": "Images referenced by hash", "Bytes": components["source_media"]},
                                    {"Component": "Image pixels stored", "Bytes": components["optimized_media"]},
                                    {"Component": "Container header", "Bytes": components["container_header"]},
                                    {"Component": "Final KP package", "Bytes": components["final"]},
                                ]
                            else:
                                breakdown = [
                                    {"Component": "Original file", "Bytes": item["original_bytes"]},
                                    {"Component": "Slide graph", "Bytes": components["graph"]},
                                    {"Component": "Original embedded media", "Bytes": components["source_media"]},
                                    {"Component": "Verified optimized media", "Bytes": components["optimized_media"]},
                                    {"Component": "Container header", "Bytes": components["container_header"]},
                                    {"Component": "Final KP package", "Bytes": components["final"]},
                                ]
                        elif component_kind == "video":
                            breakdown = [
                                {"Component": "Original video", "Bytes": item["original_bytes"]},
                                {"Component": "Transcript and manifest", "Bytes": components.get("text", 0)},
                                {"Component": "Unique frames", "Bytes": components.get("frames", 0)},
                                {"Component": "Slide references", "Bytes": components.get("references", 0)},
                                {"Component": "Deduplicated bytes", "Bytes": components.get("dedup_removed", 0)},
                                {"Component": "Container header", "Bytes": components.get("container_header", 0)},
                                {"Component": "Final KP output", "Bytes": item["compressed_bytes"]},
                            ]
                        else:
                            breakdown = [
                                {"Component": "Original file", "Bytes": item["original_bytes"]},
                                {"Component": "Compressed payload", "Bytes": components.get("compressed_payload", 0)},
                                {"Component": "Integrity header", "Bytes": components.get("container_header", 0)},
                                {"Component": "Final exact package", "Bytes": components.get("final", item["compressed_bytes"])},
                            ]
                        inner_components = {
                            row["Component"]: row["Bytes"]
                            for row in breakdown[1:-1]
                        }
                        largest_component = max(
                            inner_components, key=inner_components.get, default="none"
                        )
                        st.caption(
                            f"Largest reported component: **{largest_component}**. "
                            "Semantic component inputs are measured before whole-package compression and are not additive to final bytes."
                        )
                        st.bar_chart(
                            breakdown,
                            x="Component",
                            y="Bytes",
                            horizontal=True,
                            alt="Bytes used by each compression component",
                        )
                        st.dataframe(
                            breakdown,
                            hide_index=True,
                            width="stretch",
                            alt="Compression component sizes in bytes",
                            column_config={
                                "Bytes": st.column_config.NumberColumn(format="localized")
                            },
                        )
                    if item.get("candidate_bytes"):
                        st.markdown("**Codec tournament**")
                        st.dataframe(
                            [
                                {
                                    "Codec": codec,
                                    "Bytes": size,
                                    "Selected": codec in item["codec"],
                                }
                                for codec, size in sorted(
                                    item["candidate_bytes"].items(), key=lambda candidate: candidate[1]
                                )
                            ],
                            hide_index=True,
                            width="stretch",
                            alt="Compared codec output sizes",
                        )
                    kp_path = item.get("kp_path")
                    if kp_path and Path(kp_path).is_file():
                        st.download_button(
                            "Download compact .kp package",
                            data=Path(kp_path).read_bytes(),
                            file_name=f"{Path(item['file']).stem}.kp",
                            mime="application/octet-stream",
                            key=f"download_{element_suffix}",
                            icon=":material/download:",
                        )
                    kp_bytes = item.get("kp_bytes")
                    if kp_bytes:
                        st.download_button(
                            "Download verified .kp package",
                            data=kp_bytes,
                            file_name=f"{Path(item['file']).stem}.kp",
                            mime="application/vnd.ericsson.knowledge-package",
                            key=f"download_package_{element_suffix}",
                            icon=":material/download:",
                            width="stretch",
                        )
                        if offer_ascii and item.get("ascii_bytes"):
                            st.download_button(
                                "Download ASCII/Base85 export (larger)",
                                data=item["ascii_bytes"],
                                file_name=f"{Path(item['file']).stem}.kp.txt",
                                mime="text/plain",
                                key=f"download_ascii_{element_suffix}",
                                icon=":material/code:",
                                width="stretch",
                            )
            st.caption(
                "Semantic video, PDF and presentation results are knowledge packages. Exact-file mode and other file types use lossless byte compression."
            )

with impact_tab:
    st.subheader("A storage decision in seconds", icon=":material/query_stats:")
    if storage:
        st.markdown(
            "#### Measured recording baseline" if storage["source_available"]
            else "#### Included technical fixture (no source video)"
        )
        st.caption(f"Measured from {storage['basis']}.")
        if not storage["source_available"]:
            st.caption(
                "The demo has no source video. These fixture byte sizes validate packing only; "
                "the mock source-size metadata is not a measured video compression result."
            )
        baseline_metrics = st.columns(4)
        baseline_metrics[0].metric(
            "Source input" if storage["source_available"] else "Fixture input",
            format_bytes(storage["original_bytes"]), border=True
        )
        baseline_metrics[1].metric(
            "Compact package" if storage["source_available"] else "Fixture package",
            format_bytes(storage["compact_bytes"]), border=True
        )
        baseline_metrics[2].metric(
            savings_label(storage["saved_bytes"]),
            format_bytes(abs(storage["saved_bytes"])),
            border=True,
        )
        baseline_metrics[3].metric(
            "Reduction" if storage["saved_bytes"] >= 0 else "Increase",
            format_percent(
                abs(storage["saved_percent"]), output_bytes=storage["compact_bytes"]
            ),
            border=True,
        )
        with st.expander("Inspect baseline package"):
            components = storage["components"]
            st.markdown(
                f"**Codec:** {storage['codec']}  \n"
                f"**Text and manifest:** {format_bytes(components.get('text', 0))}  \n"
                f"**Unique frames:** {format_bytes(components.get('frames', 0))}  \n"
                f"**Slide references:** {format_bytes(components.get('references', 0))}"
            )
    measured = st.session_state.get("latest_measurements", [])
    measured_videos = [
        item for item in measured
        if item.get("facts", {}).get("mode") == "semantic video compression"
    ]
    if measured:
        measured_original = sum(item["original_bytes"] for item in measured)
        measured_compact = sum(item["compressed_bytes"] for item in measured)
        measured_saved, measured_saved_percent = measured_savings(measured_original, measured_compact)
        st.success("Latest calculation uses the files measured in this session.")
        measured_cols = st.columns(4)
        measured_cols[0].metric("Measured original", format_bytes(measured_original))
        measured_cols[1].metric("Measured compact", format_bytes(measured_compact))
        measured_cols[2].metric(
            f"Measured {savings_label(measured_saved).lower()}", format_bytes(abs(measured_saved))
        )
        measured_cols[3].metric(
            "Measured reduction" if measured_saved >= 0 else "Measured increase",
            format_percent(abs(measured_saved_percent), output_bytes=measured_compact),
        )
        st.caption("This is an exact result for the uploaded bytes, not an estimate.")
    hours = st.number_input(
        "Original recording volume (hours)", min_value=1.0, value=2000.0, step=100.0
    )
    average_gb_per_hour = st.number_input(
        "Average original GB per hour", min_value=0.1, value=0.5, step=0.1
    )
    original = hours * average_gb_per_hour * 1024**3
    if measured_videos:
        scenario_original = sum(item["original_bytes"] for item in measured_videos)
        scenario_compact = sum(item["compressed_bytes"] for item in measured_videos)
        ratio = scenario_compact / max(scenario_original, 1)
        scenario_basis = "latest semantic video measurements"
    else:
        scenario_options = ["Local benchmark evidence", "Planning assumption"]
        scenario_mode = st.segmented_control(
            "Scenario basis",
            scenario_options,
            default=scenario_options[0],
            key="storage_scenario_basis",
            help=(
                "Use the recorded ratio from the local jury benchmark, or enter an explicit "
                "planning assumption for another workload."
            ),
        )
        if scenario_mode == "Local benchmark evidence":
            ratio = benchmark_evidence["package"]["bytes"] / benchmark_evidence["source"]["bytes"]
            scenario_basis = (
                "verified local Jury and prizes.mp4 benchmark evidence: "
                f"{format_percent(benchmark_evidence['saved_percent'])} reduction; source not distributed"
            )
        else:
            retained_percent = st.number_input(
                "Planning assumption: retained share after semantic compression (%)",
                min_value=0.01,
                max_value=100.0,
                value=5.0,
                step=0.5,
                help=(
                    "This is an explicit planning assumption, not a measured result. "
                    "Benchmark representative Ericsson recordings before production planning."
                ),
            )
            ratio = retained_percent / 100
            scenario_basis = "planning assumption entered above"
    compact = original * ratio
    a, b, c = st.columns(3)
    a.metric("Before", format_bytes(original), border=True)
    b.metric("After", format_bytes(compact), border=True)
    scenario_saved = original - compact
    c.metric(
        "Released capacity" if scenario_saved >= 0 else "Additional capacity",
        format_bytes(abs(scenario_saved)),
        border=True,
    )
    st.caption(
        f"Scenario basis: {scenario_basis}. This estimate is kept separate from measured uploaded-file results."
    )

with coverage_tab:
    st.subheader("Challenge coverage", icon=":material/fact_check:")
    st.caption(
        "Mapped directly from Challenge_Ericsson.docx. Completed means implemented and locally verified; partial means the core exists with a stated limitation."
    )
    st.dataframe(
        [
            {"Challenge need": "Reduce recording storage", "Status": ["Complete"], "Evidence": "Transcript + keyframes + KP package"},
            {"Challenge need": "Make content searchable", "Status": ["Complete"], "Evidence": "FTS search across demo, uploaded videos, PDFs and presentations"},
            {"Challenge need": "Produce AI-ready content", "Status": ["Complete"], "Evidence": "UTF-8 transcript, semantic graphs and versioned REST output"},
            {"Challenge need": "Connect a production AI consumer", "Status": ["Partial"], "Evidence": "Open package/API contract exists; Ericsson model and retrieval integration remain"},
            {"Challenge need": "Link text to visual context", "Status": ["Complete"], "Evidence": "Frame IDs, timestamps and slide references"},
            {"Challenge need": "Differentiate speakers", "Status": ["Partial"], "Evidence": "Speaker field is supported; automatic diarization is not implemented"},
            {"Challenge need": "Find exact duplicate files", "Status": ["Complete"], "Evidence": "SHA-256 grouping and measured duplicate-byte savings"},
            {"Challenge need": "Identify duplicate slides and assets", "Status": ["Complete"], "Evidence": "Content hashes plus cross-upload duplicate report"},
            {"Challenge need": "Preserve meaningful visuals", "Status": ["Complete"], "Evidence": "Pixel-verified media or source-slide reference"},
            {"Challenge need": "Safe offboarding deletion decision", "Status": ["Partial"], "Evidence": "Exact copies and continued access are verified; deletion, approval and remote-provider adapters remain"},
            {"Challenge need": "Recreate the original video", "Status": ["Partial"], "Evidence": "Knowledge timeline is retained; discarded motion and audio cannot be recreated"},
            {"Challenge need": "Connect SharePoint, OneDrive and Ericsson Play", "Status": ["Partial"], "Evidence": "REST/OpenAPI integration is ready; product-specific connector and Ericsson authentication remain"},
        ],
        hide_index=True,
        width="stretch",
        alt="Ericsson challenge requirements and implementation status",
        column_config={
            "Status": st.column_config.MultiselectColumn(
                options=["Complete", "Partial", "Future work"], color="auto"
            )
        },
    )
    st.info(
        "The challenge explicitly allows replacing video with text and keyframes. Semantic mode therefore preserves the information timeline, not a reversible copy of discarded motion or audio.",
        title="Quality boundary",
        icon=":material/policy:",
    )
    st.warning(
        "Offboarding produces auditable evidence and deliberately does not delete files. "
        "A production connector must enforce retention policy, approval and a final recheck immediately before deletion.",
        title="Safe deletion boundary",
        icon=":material/admin_panel_settings:",
    )

    st.markdown("#### Final-pitch checklist")
    st.dataframe(
        [
            {
                "Pitch requirement": "1 · Use cases addressed",
                "What we present": "Video distillation, enterprise search, duplicate detection and offboarding evidence",
                "Demo proof": "Upload/package metrics, winner search, duplicate hashes and challenge coverage",
            },
            {
                "Pitch requirement": "2 · Technical solution",
                "What we present": "Ingest → transcript/keyframes → deduplicate → verified KP → REST/search",
                "Demo proof": "Measured components, SHA-256 integrity and deployable API boundary",
            },
            {
                "Pitch requirement": "3 · Scenario savings",
                "What we present": (
                    f"{benchmark_evidence['saved_percent']:.2f}% local benchmark evidence "
                    f"on {benchmark_evidence['source']['file']}, then scaled transparently"
                ),
                "Demo proof": (
                    f"{benchmark_evidence['source']['bytes']:,} B → "
                    f"{benchmark_evidence['package']['bytes']:,} B plus the storage calculator"
                ),
            },
            {
                "Pitch requirement": "4 · Future-proof data strategy",
                "What we present": "Content-addressed packages, open semantic data, versioned APIs and source registry",
                "Demo proof": "Portable .kp, UTF-8/JSON graphs, REST/OpenAPI and object-storage output",
            },
            {
                "Pitch requirement": "5 · Further work and unresolved problems",
                "What we present": "Connectors/auth, diarization, quality policy, scale benchmarks and governed deletion",
                "Demo proof": "Partial rows are visible instead of being presented as finished",
            },
        ],
        hide_index=True,
        width="stretch",
        alt="Final pitch requirements mapped to implementation and demo evidence",
    )

    st.markdown("#### Future-proof data strategy")
    strategy_columns = st.columns(4)
    for column, title, detail in zip(
        strategy_columns,
        (
            "Content-addressed",
            "Open knowledge layer",
            "Replaceable adapters",
            "Evidence-first governance",
        ),
        (
            "SHA-256 identifies source and package bytes, enabling deduplication and integrity checks.",
            "UTF-8 text, timestamps, references and semantic JSON remain usable by future search and AI tools.",
            "A versioned REST/Python boundary separates the core from Play, SharePoint, OneDrive and model vendors.",
            "Retention, access and duplicate evidence are recorded before any external deletion workflow acts.",
        ),
    ):
        with column:
            with st.container(border=True, height="stretch"):
                st.markdown(f"**{title}**")
                st.caption(detail)

    st.markdown("#### Jury evidence map")
    st.caption(
        "Each row answers what the jury is asked to write down. Show the evidence; do not rely on the claim alone."
    )
    st.dataframe(
        [
            {
                "Criterion": "Problem understanding · 15%",
                "Evidence to show": "Storage owners face heavy copies; knowledge workers cannot find answers; offboarding teams need safe deletion evidence",
                "Honest boundary": "The brief and prototype files support the scope; Ericsson-wide prevalence is not yet measured",
            },
            {
                "Criterion": "Feasibility · 15%",
                "Evidence to show": "Versioned API, streamed video path and a four-week read-only pilot plan",
                "Honest boundary": "Ericsson authentication, connectors and operational ownership remain",
            },
            {
                "Criterion": "Technical quality · 5%",
                "Evidence to show": "Verified package/hash evidence, search returns frames, API and release tests pass",
                "Honest boundary": "Semantic mode cannot reconstruct discarded motion or audio",
            },
            {
                "Criterion": "User value · 20%",
                "Evidence to show": "Less storage, direct topic search instead of replaying video, evidence before offboarding deletion",
                "Honest boundary": "Search relevance and workflow time savings need user validation in a pilot",
            },
            {
                "Criterion": "Innovation · 10%",
                "Evidence to show": "One pipeline combines semantic distillation, deduplication, search/AI activation and deletion evidence",
                "Honest boundary": "The codecs and extraction tools are standard; the adapted combination is the contribution",
            },
            {
                "Criterion": "Presentation and demo · 25%",
                "Evidence to show": "Prepared real-video result, winner search with images and a verified static backup",
                "Honest boundary": "Keep the live path to two actions and finish within three minutes",
            },
            {
                "Criterion": "Partner relevance · 10%",
                "Evidence to show": "Video-to-text/keyframes, duplicates, AI-ready search and offboarding map directly to the brief",
                "Honest boundary": "Product-specific Ericsson adapters are the next integration step",
            },
        ],
        hide_index=True,
        width="stretch",
        alt="Jury criteria mapped to evidence and remaining limitations",
    )

    built_column, reused_column = st.columns(2)
    with built_column:
        with st.container(border=True, height="stretch"):
            st.markdown("**Built by the team**")
            st.caption(
                "Knowledge-package pipeline, fidelity policies, search/index integration, "
                "duplicate and offboarding evidence flows, REST adapter and Streamlit demo."
            )
    with reused_column:
        with st.container(border=True, height="stretch"):
            st.markdown("**Reused foundations**")
            st.caption(
                "Standard compression codecs and established tools for media, transcription, "
                "document rendering and parsing. The value is how they are combined for this brief."
            )

    st.info(
        "Run a four-week, read-only pilot on 100 representative files. Measure storage reduction, "
        "search relevance, fidelity acceptance, processing cost and offboarding evidence quality. "
        "Use a data owner, one platform/integration engineer and a security or records reviewer. "
        "Do not automate deletion during the pilot.",
        title="Concrete next step",
        icon=":material/science:",
    )
    st.markdown("#### Implementation path")
    st.caption("The dashboard is one client. The compression and search contract is deployable independently.")
    implementation = st.columns(4)
    for column, title, detail in zip(
        implementation,
        ("Ericsson source", "Integration API", "Knowledge package", "Existing consumers"),
        (
            "Play · SharePoint · offboarding",
            "Python library or REST/OpenAPI",
            "Immutable .kp + SHA-256 metadata",
            "Object storage · search · AI",
        ),
    ):
        with column:
            st.markdown(f"**{title}**")
            st.caption(detail)
    st.success(
        "Production boundary implemented: documents are processed in memory, large videos are streamed through an isolated temporary workspace, and the API returns a portable package plus integrity and storage metrics. Streamlit is not required in production.",
        icon=":material/integration_instructions:",
    )

with story_tab:
    st.subheader("Final pitch structure · three minutes", icon=":material/record_voice_over:")
    st.markdown(
        f"""
        **0:00–0:30 · Use cases and problem**
        Valuable recordings and documents are expensive to keep but costly to lose. We address
        video distillation, searchable knowledge, duplicate detection and safer offboarding decisions.

        **0:30–1:15 · Technical solution**
        We preserve transcript, timing, unique visual context and source references; remove duplicate
        information; then create a verified `.kp` package for object storage, search and AI through a
        versioned Python and REST/OpenAPI boundary.

        **1:15–2:00 · Measured result and demo**
        Local benchmark evidence records `{benchmark_evidence['source']['file']}` from
        {benchmark_evidence['source']['bytes']:,} bytes to {benchmark_evidence['package']['bytes']:,}
        bytes — **{benchmark_evidence['saved_percent']:.2f}% less**; the source is not distributed
        in the repository.
        Search for `winner` to return the transcript together with its visual context, then scale the
        measured ratio in the storage calculator.

        **2:00–2:35 · Future-proof data strategy**
        Content hashes prevent needless copies, open text and semantic graphs remain AI-consumable,
        and replaceable connectors keep the core independent of storage platform and model vendor.

        **2:35–3:00 · Honest next steps**
        Ericsson authentication and product connectors, speaker diarization, representative-scale
        benchmarks, quality-policy calibration and governed deletion remain. The proposed next step is
        a limited Ericsson pilot with agreed fidelity, retention and cost targets.
        """
    )
