import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
from src.search.db import connect
from src.search.index import index_package
from src.search.make_mock import make
from src.search.query import search

st.set_page_config(page_title="Recording search", layout="wide")
st.title("Search recordings")


@st.cache_resource
def ensure_demo_index() -> str:
    """Create a small portable demo index when running on a fresh host."""
    package_path = Path("data/sample/rec_mock/package.json")
    if not package_path.is_file():
        make(package_path.parent)
    with connect() as connection:
        exists = connection.execute(
            "SELECT 1 FROM recordings WHERE id=?", ("rec_mock",)
        ).fetchone()
    if exists is None:
        index_package(package_path)
    return str(package_path)


ensure_demo_index()
st.caption("Demo index ready · try: storage, duplicate files, or winner")

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
