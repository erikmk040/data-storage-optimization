import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
from src.search.query import search

st.set_page_config(page_title="Recording search", layout="wide")
st.title("Search recordings")

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