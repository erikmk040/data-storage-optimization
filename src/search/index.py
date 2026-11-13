import json
from pathlib import Path

from .db import connect

def index_package(package_json: Path) -> str:
    """Index one recording package and return its recording id.

    Re-indexing the same package is safe: all rows belonging to the recording
    are removed before the package is inserted again.
    """
    pkg = json.loads(package_json.read_text(encoding="utf-8"))
    base = package_json.parent
    rid, src = pkg["id"], pkg["source"]
    con = connect()
    with con:
        # re-index safely
        for t in ("segments", "frames", "recordings"):
            col = "id" if t == "recordings" else "rec_id"
            con.execute(f"DELETE FROM {t} WHERE {col}=?", (rid,))
        con.execute("DELETE FROM segments_fts WHERE rec_id=?", (rid,))
        con.execute("DELETE FROM frames_fts WHERE rec_id=?", (rid,))

        con.execute("INSERT INTO recordings VALUES (?,?,?,?,?)",
            (rid, src["file"], src.get("sha256"), src.get("duration_s"), src.get("size_bytes")))

        for i, s in enumerate(pkg["segments"]):
            con.execute("INSERT INTO segments VALUES (?,?,?,?,?,?,?)",
                (rid, i, s["start"], s["end"], s.get("speaker"), s["text"], s.get("frame_id")))
            con.execute("INSERT INTO segments_fts(text, rec_id, idx) VALUES (?,?,?)",
                (s["text"], rid, i))

        for f in pkg["frames"]:
            ref = f.get("slide_ref") or {}
            con.execute("INSERT INTO frames VALUES (?,?,?,?,?,?,?,?,?)",
                (rid, f["id"], f["t"], str(base / f["file"]), f.get("phash"),
                 f.get("ocr_text", ""), ref.get("doc_id"), ref.get("slide_no"), ref.get("slide_hash")))
            con.execute("INSERT INTO frames_fts(ocr_text, rec_id, frame_id) VALUES (?,?,?)",
                (f.get("ocr_text", ""), rid, f["id"]))
    return rid
