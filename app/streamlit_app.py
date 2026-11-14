import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
from src.search.index import index_package
from src.search.make_mock import make
from src.search.query import search
from src.savings.pack import pack

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


st.set_page_config(page_title="Ericsson Knowledge Compression", page_icon="⚡", layout="wide")
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

search_tab, impact_tab, story_tab = st.tabs(["Search the knowledge", "Storage calculator", "How to pitch it"])

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

q = st.text_input("Search for a topic", placeholder="e.g. duplicate files")
if q:
    results = search(q)
    st.caption(f"{len(results)} hits")
    for r in results:
        c1, c2 = st.columns([1, 2])
        fr = r["frame"]
        with c1:
            if fr and Path(fr["file"]).exists():
                st.image(fr["file"])
            else:
                st.info("No frame")
        with c2:
            mm, ss = divmod(int(r["start"]), 60)
            st.markdown(f"**{r['rec_id']}** · {mm:02d}:{ss:02d} · {r['speaker'] or '-'} · _{r['kind']}_")
            st.write(r["snippet"].replace("[", "**").replace("]", "**"))
            if fr and fr.get("doc_id"):
                st.caption(f"Slide {fr['slide_no']} in {fr['doc_id']}")
        st.divider()
