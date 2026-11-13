import re
from .db import connect

def _fts_query(q: str) -> str:
    tokens = re.findall(r"\w+", q, flags=re.UNICODE)
    if not tokens:
        return ""
    parts = [f'"{t}"' for t in tokens[:-1]] + [f'"{tokens[-1]}"*']  # prefix on last word
    return " ".join(parts)

def _frame_for(con, rec_id, frame_id, t):
    if frame_id:
        row = con.execute("SELECT * FROM frames WHERE rec_id=? AND id=?", (rec_id, frame_id)).fetchone()
        if row:
            return row
    return con.execute(
        "SELECT * FROM frames WHERE rec_id=? AND t<=? ORDER BY t DESC LIMIT 1", (rec_id, t)).fetchone()

def search(q: str, limit: int = 10) -> list[dict]:
    fq = _fts_query(q)
    if not fq:
        return []
    con = connect()
    out = []

    # 1) hits in speech
    rows = con.execute("""
        SELECT s.*, snippet(segments_fts, 0, '[', ']', '…', 12) AS snip, bm25(segments_fts) AS score
        FROM segments_fts JOIN segments s
          ON s.rec_id = segments_fts.rec_id AND s.idx = segments_fts.idx
        WHERE segments_fts MATCH ? ORDER BY score LIMIT ?""", (fq, limit)).fetchall()
    for r in rows:
        fr = _frame_for(con, r["rec_id"], r["frame_id"], r["start_s"])
        out.append({"kind": "speech", "rec_id": r["rec_id"], "start": r["start_s"],
                    "end": r["end_s"], "speaker": r["speaker"], "text": r["text"],
                    "snippet": r["snip"], "frame": dict(fr) if fr else None, "score": r["score"]})

    # 2) hits in slide text (OCR)
    rows = con.execute("""
        SELECT f.*, snippet(frames_fts, 0, '[', ']', '…', 12) AS snip, bm25(frames_fts) AS score
        FROM frames_fts JOIN frames f
          ON f.rec_id = frames_fts.rec_id AND f.id = frames_fts.frame_id
        WHERE frames_fts MATCH ? ORDER BY score LIMIT ?""", (fq, limit)).fetchall()
    for r in rows:
        seg = con.execute("""SELECT * FROM segments WHERE rec_id=? AND start_s>=? 
                             ORDER BY start_s LIMIT 1""", (r["rec_id"], r["t"])).fetchone()
        out.append({"kind": "slide", "rec_id": r["rec_id"], "start": r["t"],
                    "end": seg["end_s"] if seg else r["t"], "speaker": seg["speaker"] if seg else None,
                    "text": seg["text"] if seg else "", "snippet": r["snip"],
                    "frame": dict(r), "score": r["score"]})

    return sorted(out, key=lambda x: x["score"])[:limit]