import sqlite3
from pathlib import Path

DB_PATH = Path("data/index.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings(
  id TEXT PRIMARY KEY, file TEXT, sha256 TEXT, duration_s REAL, size_bytes INTEGER);

CREATE TABLE IF NOT EXISTS segments(
  rec_id TEXT, idx INTEGER, start_s REAL, end_s REAL,
  speaker TEXT, text TEXT, frame_id TEXT,
  PRIMARY KEY(rec_id, idx));

CREATE TABLE IF NOT EXISTS frames(
  rec_id TEXT, id TEXT, t REAL, file TEXT, phash TEXT, ocr_text TEXT,
  doc_id TEXT, slide_no INTEGER, slide_hash TEXT,
  PRIMARY KEY(rec_id, id));

CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
  text, rec_id UNINDEXED, idx UNINDEXED,
  tokenize='unicode61 remove_diacritics 2');

CREATE VIRTUAL TABLE IF NOT EXISTS frames_fts USING fts5(
  ocr_text, rec_id UNINDEXED, frame_id UNINDEXED,
  tokenize='unicode61 remove_diacritics 2');
"""

def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con