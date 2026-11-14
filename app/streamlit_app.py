import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gzip
import hashlib
import io
import lzma
import mimetypes
import shutil
import subprocess
import tempfile
from typing import Any

import streamlit as st
from src.search.index import index_package
from src.search.make_mock import make
from src.search.query import search
from src.savings.pack import pack
from src.video.package import build_package

st.set_page_config(page_title="Ericsson Knowledge Compression", page_icon="⚡", layout="wide")

@st.cache_resource
def ensure_demo_index() -> str:
    """Create a small portable demo index when running on a fresh host."""
    package_path = Path("data/sample/rec_mock/package.json")
    # Rebuild the tiny demo deterministically so a persistent cloud volume
    # cannot keep an older package or stale FTS rows after an app update.
    make(package_path.parent)
    index_package(package_path)
    return str(package_path)


@st.cache_data
def storage_report(package_path: str) -> dict:
    """Build a compact demo artifact and return presentation-ready metrics."""
    package = Path(package_path)
    kp_path = package.parent / "rec_mock.kp"
    report = pack(package, kp_path)
    source = __import__("json").loads(package.read_text(encoding="utf-8"))["source"]
    original = int(source.get("size_bytes") or 0)
    compact = report.packed_bytes
    saved = max(original - compact, 0)
    return {
        "original_bytes": original,
        "compact_bytes": compact,
        "saved_bytes": saved,
        "saved_percent": (saved / original * 100) if original else 0,
        "codec": report.codec,
        "components": report.component_bytes,
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


def compress_uploaded_bytes(data: bytes) -> tuple[str, bytes]:
    """Choose the smallest lossless byte compression for one upload."""
    candidates: dict[str, bytes] = {
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
        candidates["zstd-19"] = zstd.ZstdCompressor(level=19).compress(data)
    except ImportError:
        pass
    return min(candidates.items(), key=lambda item: len(item[1]))


def inspect_uploaded_file(name: str, data: bytes) -> dict[str, Any]:
    """Return measured compression and content metadata for one uploaded file."""
    codec, compressed = compress_uploaded_bytes(data)
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
    elif suffix in {".mp4", ".mov", ".mkv", ".avi"} and shutil.which("ffprobe"):
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
    return {
        "file": name,
        "original_bytes": len(data),
        "compressed_bytes": len(compressed),
        "saved_bytes": max(len(data) - len(compressed), 0),
        "saved_percent": max((1 - len(compressed) / len(data)) * 100, 0) if data else 0,
        "codec": codec,
        "sha256": hashlib.sha256(data).hexdigest()[:16],
        "facts": facts,
    }


def compress_uploaded_video(name: str, data: bytes) -> dict[str, Any]:
    """Run the real video-to-KP pipeline for one uploaded video."""
    suffix = Path(name).suffix.lower()
    with tempfile.TemporaryDirectory(prefix="uploaded-recording-") as directory:
        root = Path(directory)
        source = root / f"source{suffix}"
        package_dir = root / "package"
        kp_path = root / "recording.kp"
        source.write_bytes(data)
        package_json = build_package(source, package_dir, transcribe_audio=True)
        report = pack(package_json, kp_path)
        package = __import__("json").loads(package_json.read_text(encoding="utf-8"))
        compressed = kp_path.stat().st_size
        return {
            "file": name,
            "original_bytes": len(data),
            "compressed_bytes": compressed,
            "saved_bytes": max(len(data) - compressed, 0),
            "saved_percent": max((1 - compressed / len(data)) * 100, 0) if data else 0,
            "codec": f"KP v2/{report.codec}",
            "sha256": hashlib.sha256(data).hexdigest()[:16],
            "facts": {
                "mode": "semantic video compression",
                "segments": len(package.get("segments", [])),
                "unique frames": len(package.get("frames", [])),
                "transcript": "UTF-8 text",
            },
        }


st.title("Ericsson Knowledge Compression")
st.caption("Turn heavy recordings into compact, searchable knowledge packages.")

if storage:
    st.subheader("Storage impact")
    metric_columns = st.columns(4)
    metric_columns[0].metric("Original recording", format_bytes(storage["original_bytes"]))
    metric_columns[1].metric("Compact package", format_bytes(storage["compact_bytes"]))
    metric_columns[2].metric("Storage saved", format_bytes(storage["saved_bytes"]))
    metric_columns[3].metric("Reduction", f"{storage['saved_percent']:.2f}%")
    st.progress(min(storage["saved_percent"] / 100, 1.0), text="Information retained · storage removed")

    impact_left, impact_right = st.columns([1, 1])
    with impact_left:
        st.markdown("#### Scale the impact")
        recordings = st.number_input("Number of recordings", min_value=1, value=1000, step=100)
        original_total = storage["original_bytes"] * recordings
        compact_total = storage["compact_bytes"] * recordings
        st.metric("Estimated storage after compression", format_bytes(compact_total), f"-{format_bytes(original_total - compact_total)}")
    with impact_right:
        st.markdown("#### What makes the package small?")
        components = storage["components"]
        st.write(f"**Codec:** {storage['codec']}")
        st.write(f"**Text and manifest:** {format_bytes(components.get('text', 0))}")
        st.write(f"**Unique frames:** {format_bytes(components.get('frames', 0))}")
        st.write(f"**Slide references:** {format_bytes(components.get('references', 0))}")

    st.divider()

with st.container(border=True):
    st.markdown("#### From video to reusable knowledge")
    flow = st.columns(5)
    for column, title, detail in zip(
        flow,
        ("01 · Capture", "02 · Distill", "03 · Deduplicate", "04 · Compress", "05 · Activate"),
        ("Video and documents", "Transcript + keyframes", "Hashes + references", "One compact .kp", "Search + AI"),
    ):
        with column:
            st.markdown(f"**{title}**")
            st.caption(detail)

search_tab, upload_tab, impact_tab, story_tab = st.tabs(["Search the knowledge", "Measure your files", "Storage calculator", "How to pitch it"])

with search_tab:
    st.info("Demo index ready · try: **storage**, **duplicate files**, or **winner**")
    q = st.text_input("Search for a topic", placeholder="e.g. duplicate files", key="search_query")
    if q:
        results = search(q)
        st.caption(f"{len(results)} hits · text and visual context returned together")
        for r in results:
            c1, c2 = st.columns([1, 2])
            fr = r["frame"]
            with c1:
                if fr and Path(fr["file"]).exists():
                    st.image(fr["file"], use_container_width=True)
                else:
                    st.info("Reference frame · render from source registry")
            with c2:
                mm, ss = divmod(int(r["start"]), 60)
                st.markdown(f"**{r['rec_id']}** · {mm:02d}:{ss:02d} · {r['speaker'] or '-'} · _{r['kind']}_")
                st.write(r["snippet"].replace("[", "**").replace("]", "**"))
                if fr and fr.get("doc_id"):
                    st.caption(f"Slide {fr['slide_no']} in {fr['doc_id']}")
            st.divider()

with upload_tab:
    st.subheader("Measure real files")
    st.write("Drag one or more files here. Every number below is calculated from the uploaded bytes.")
    uploads = st.file_uploader(
        "Upload recordings, PDFs, presentations, images or text files",
        type=["mp4", "mov", "mkv", "avi", "pdf", "pptx", "png", "jpg", "jpeg", "webp", "txt", "md", "json", "csv", "zip"],
        accept_multiple_files=True,
        help="Files are processed in memory for this session and are not added to the repository.",
    )
    if uploads:
        video_uploads = [upload for upload in uploads if Path(upload.name).suffix.lower() in {".mp4", ".mov", ".mkv", ".avi"}]
        semantic_video = st.checkbox(
            "Run semantic video compression (transcript + keyframes + KP package)",
            value=True,
            disabled=not video_uploads,
            help="This produces the actual challenge output. It can take several minutes for a long video.",
        )
        run_semantic = st.button("Analyze uploaded files", type="primary")
        measurements = []
        for upload in uploads:
            data = upload.getvalue()
            is_video = Path(upload.name).suffix.lower() in {".mp4", ".mov", ".mkv", ".avi"}
            if is_video and semantic_video:
                if not run_semantic:
                    st.info("Click **Analyze uploaded files** to run the real video distillation pipeline.")
                    break
                with st.status(f"Distilling {upload.name}…", expanded=False) as status:
                    try:
                        measurement = compress_uploaded_video(upload.name, data)
                        status.update(label=f"Finished {upload.name}", state="complete")
                    except Exception as error:
                        status.update(label=f"Could not distill {upload.name}", state="error")
                        st.error(str(error))
                        measurement = inspect_uploaded_file(upload.name, data)
                        measurement["facts"]["mode"] = "lossless byte compression fallback"
                measurements.append(measurement)
            else:
                measurements.append(inspect_uploaded_file(upload.name, data))
        if not measurements:
            st.stop()
        total_original = sum(item["original_bytes"] for item in measurements)
        total_compressed = sum(item["compressed_bytes"] for item in measurements)
        total_saved = max(total_original - total_compressed, 0)
        st.success(f"Measured {len(measurements)} file(s) using actual uploaded data.")
        metrics = st.columns(4)
        metrics[0].metric("Original", format_bytes(total_original))
        metrics[1].metric("Compressed", format_bytes(total_compressed))
        metrics[2].metric("Saved", format_bytes(total_saved))
        metrics[3].metric("Reduction", f"{total_saved / total_original * 100:.2f}%" if total_original else "0.00%")
        st.dataframe(
            [
                {
                    "File": item["file"],
                    "Original": format_bytes(item["original_bytes"]),
                    "Compressed": format_bytes(item["compressed_bytes"]),
                    "Saved": format_bytes(item["saved_bytes"]),
                    "Reduction": f"{item['saved_percent']:.2f}%",
                    "Codec": item["codec"],
                }
                for item in measurements
            ],
            use_container_width=True,
            hide_index=True,
        )
        for item in measurements:
            with st.expander(f"{item['file']} · SHA-256 {item['sha256']}"):
                st.json(item["facts"])
        st.caption("The measured compression is lossless byte compression. Recording packages additionally preserve searchable transcript and visual references through the KP pipeline.")

with impact_tab:
    st.subheader("A storage decision in seconds")
    if storage:
        hours = st.number_input("Original recording volume (hours)", min_value=1.0, value=2000.0, step=100.0)
        average_gb_per_hour = st.number_input("Average original GB per hour", min_value=0.1, value=0.5, step=0.1)
        original = hours * average_gb_per_hour * 1024**3
        ratio = storage["compact_bytes"] / max(storage["original_bytes"], 1)
        compact = original * ratio
        a, b, c = st.columns(3)
        a.metric("Before", format_bytes(original))
        b.metric("After", format_bytes(compact))
        c.metric("Released capacity", format_bytes(original - compact))
        st.caption("The ratio is measured from the running demo package; replace it with production benchmark data for planning.")

with story_tab:
    st.subheader("The pitch in one minute")
    st.markdown(
        """
        **The problem:** valuable recordings are deleted because video is expensive to store.

        **Our solution:** preserve the information that matters — transcript, timing, unique visual
        context and links to a single source of truth — then compress it into one searchable package.

        **The differentiator:** this is not only compression. It is a knowledge activation layer:
        every saved byte remains discoverable, explainable and usable by future AI systems.

        **The scale story:** deduplication, registry references and codec selection make the same
        pipeline work for one recording or an enterprise library.
        """
    )
