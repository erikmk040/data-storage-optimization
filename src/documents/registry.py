"""Local document registry implementing the approved Role B contract in PR #6."""

import hashlib
import json
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from shutil import copyfileobj
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import pptx
import pymupdf

from .file_hash import hash_file
from .pdf_extraction import extract_pages
from .pptx_revision_demo import extract_slides


SCHEMA = """
CREATE TABLE IF NOT EXISTS registry_meta(version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS document_families(document_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS document_versions(
    doc_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES document_families(document_id),
    sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    size_bytes INTEGER NOT NULL CHECK(size_bytes>=0),
    revision TEXT, document_number TEXT, author TEXT, document_date TEXT,
    extraction_profile TEXT NOT NULL,
    CHECK(doc_id='sha256:' || sha256)
);
CREATE TABLE IF NOT EXISTS stored_copies(
    copy_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES document_versions(doc_id),
    filename TEXT NOT NULL, location_uri TEXT NOT NULL UNIQUE, owner_id TEXT,
    observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS slides(
    doc_id TEXT NOT NULL REFERENCES document_versions(doc_id),
    slide_no INTEGER NOT NULL CHECK(slide_no>=1),
    text TEXT, text_hash TEXT, phash TEXT, phash_profile TEXT,
    PRIMARY KEY(doc_id, slide_no),
    CHECK((text IS NULL)=(text_hash IS NULL)),
    CHECK(text_hash IS NULL OR (length(text_hash)=64 AND text_hash NOT GLOB '*[^0-9a-f]*')),
    CHECK((phash IS NULL)=(phash_profile IS NULL)),
    CHECK(phash IS NULL OR (length(phash)=16 AND phash NOT GLOB '*[^0-9a-f]*'))
);
CREATE INDEX IF NOT EXISTS slides_text_hash ON slides(text_hash);
CREATE INDEX IF NOT EXISTS copies_doc_id ON stored_copies(doc_id);
CREATE TABLE IF NOT EXISTS family_links(
    id TEXT PRIMARY KEY, source_document_id TEXT NOT NULL, target_document_id TEXT NOT NULL,
    confirmed_by TEXT NOT NULL, reason TEXT NOT NULL, confirmed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS phash_profiles(
    profile_id TEXT PRIMARY KEY, definition TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rendered_slides(
    doc_id TEXT NOT NULL, slide_no INTEGER NOT NULL,
    image_sha256 TEXT NOT NULL, profile_id TEXT NOT NULL REFERENCES phash_profiles(profile_id),
    PRIMARY KEY(doc_id, slide_no),
    FOREIGN KEY(doc_id, slide_no) REFERENCES slides(doc_id, slide_no)
);
CREATE TABLE IF NOT EXISTS rendering_observations(
    doc_id TEXT PRIMARY KEY REFERENCES document_versions(doc_id),
    profile_id TEXT NOT NULL REFERENCES phash_profiles(profile_id), provenance TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS visual_calibrations(
    calibration_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES phash_profiles(profile_id),
    max_distance INTEGER NOT NULL CHECK(max_distance>=0 AND max_distance<=64), evidence TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def text_hash(text: str | None) -> str | None:
    """Hash exact UTF-8 text, retaining the difference between empty and null."""
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def local_path(location_uri: str) -> Path:
    """Accept local file URIs only; cached files cannot verify remote copies."""
    uri = urlsplit(location_uri)
    if uri.scheme != "file" or uri.netloc not in ("", "localhost") or uri.query or uri.fragment:
        raise ValueError("Only local file URIs can be verified by this local registry")
    return Path(unquote(uri.path))


class Registry:
    """One connection; use as a context manager to close it deterministically."""

    def __init__(self, path: str | Path = "data/documents.db"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(SCHEMA)
        versions = self.connection.execute("SELECT version FROM registry_meta").fetchall()
        if not versions:
            self.connection.execute("INSERT INTO registry_meta VALUES (1)")
            self.connection.commit()
        elif len(versions) != 1 or versions[0][0] != 1:
            self.connection.close()
            raise ValueError("Unsupported document registry schema version")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    def document(self, doc_id: str) -> dict:
        row = self.connection.execute(
            "SELECT * FROM document_versions WHERE doc_id=?", (doc_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown document version: {doc_id}")
        result = dict(row)
        result["extraction_profile"] = json.loads(result["extraction_profile"])
        return result

    def slides(self, doc_id: str) -> list[dict]:
        self.document(doc_id)
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM slides WHERE doc_id=? ORDER BY slide_no", (doc_id,)
        )]

    def copies(self, doc_id: str | None = None) -> list[dict]:
        query = "SELECT * FROM stored_copies"
        args = ()
        if doc_id is not None:
            query += " WHERE doc_id=?"
            args = (doc_id,)
        return [dict(row) for row in self.connection.execute(query + " ORDER BY location_uri", args)]

    def copy(self, copy_id: str) -> dict:
        row = self.connection.execute(
            "SELECT * FROM stored_copies WHERE copy_id=?", (copy_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown stored copy: {copy_id}")
        return dict(row)

    def ingest(self, path: str | Path, *, owner_id: str | None = None,
               metadata: dict | None = None, render: str = "auto",
               rendered_pdf: str | Path | None = None, render_evidence: str | None = None) -> dict:
        """Import one stable snapshot atomically; preserve IDs on reimport.

        Distinct canonical locations get distinct copy IDs. A changed file at the
        same location updates that copy's current version, retaining older versions.
        """
        path = Path(path).resolve(strict=True)
        metadata = dict(metadata or {})
        allowed = {"revision", "document_number", "author", "document_date"}
        if set(metadata) - allowed:
            raise ValueError("Unknown document metadata fields")
        if any(value is not None and not isinstance(value, str) for value in metadata.values()):
            raise ValueError("Document metadata must be strings or null")
        if metadata.get("document_date") is not None:
            date.fromisoformat(metadata["document_date"])
        if path.suffix.lower() not in (".pdf", ".pptx"):
            raise ValueError("Expected a local PDF or PPTX file")
        with tempfile.TemporaryDirectory(prefix="document-import-") as directory:
            snapshot = Path(directory) / ("source" + path.suffix.lower())
            with path.open("rb") as source, snapshot.open("wb") as target:
                copyfileobj(source, target)
            digest = hash_file(snapshot)
            if path.suffix.lower() == ".pdf":
                pages = extract_pages(snapshot)
                slides = [{"slide_no": p["page_number"], "text": p["text"]} for p in pages]
                profile = {"extractor": "pymupdf", "version": pymupdf.__version__,
                           "mode": "get_text(text)", "normalization": "none"}
            else:
                slides = extract_slides(snapshot)
                profile = {"extractor": "python-pptx", "version": pptx.__version__,
                           "mode": "shape/group/table order v1", "normalization": "none"}
            from .visuals import render_source

            visual = render_source(snapshot, len(slides), mode=render,
                                   rendered_pdf=Path(rendered_pdf) if rendered_pdf else None,
                                   render_evidence=render_evidence)
            if hash_file(path) != digest:
                raise ValueError("Source changed during import; no records were imported")
            return self._store(path, digest, snapshot.stat().st_size, slides, profile,
                               owner_id, metadata, visual)

    def _store(self, path, digest, size, slides, profile, owner_id, metadata, visual):
        doc_id = "sha256:" + digest
        profile_json = json.dumps(profile, sort_keys=True)
        with self.connection:
            existing = self.connection.execute(
                "SELECT * FROM document_versions WHERE doc_id=?", (doc_id,)
            ).fetchone()
            if existing is None:
                document_id = "family-" + uuid4().hex
                self.connection.execute("INSERT INTO document_families VALUES (?)", (document_id,))
                self.connection.execute(
                    "INSERT INTO document_versions VALUES (?,?,?,?,?,?,?,?,?)",
                    (doc_id, document_id, digest, size, metadata.get("revision"),
                     metadata.get("document_number"), metadata.get("author"),
                     metadata.get("document_date"), profile_json),
                )
                self.connection.executemany(
                    "INSERT INTO slides(doc_id,slide_no,text,text_hash) VALUES (?,?,?,?)",
                    [(doc_id, s["slide_no"], s["text"], text_hash(s["text"])) for s in slides],
                )
            else:
                prior = [(s["slide_no"], s["text"]) for s in self.slides(doc_id)]
                if existing["extraction_profile"] != profile_json or prior != [
                    (s["slide_no"], s["text"]) for s in slides
                ]:
                    raise ValueError("Extraction provenance changed; explicit migration required")
                for key, value in metadata.items():
                    if value is not None and existing[key] not in (None, value):
                        raise ValueError(f"Conflicting {key} for the same exact file version")
                    if value is not None:
                        self.connection.execute(
                            f"UPDATE document_versions SET {key}=? WHERE doc_id=?", (value, doc_id)
                        )
            if visual["slides"]:
                self.connection.execute(
                    "INSERT OR IGNORE INTO phash_profiles VALUES (?,?)",
                    (visual["profile_id"], json.dumps(visual["definition"], sort_keys=True)),
                )
                for number, fingerprint in enumerate(visual["slides"], start=1):
                    self.connection.execute(
                        "UPDATE slides SET phash=?,phash_profile=? WHERE doc_id=? AND slide_no=?",
                        (fingerprint["phash"], visual["profile_id"] if fingerprint["phash"] else None,
                         doc_id, number),
                    )
                    self.connection.execute(
                        "INSERT OR REPLACE INTO rendered_slides VALUES (?,?,?,?)",
                        (doc_id, number, fingerprint["image_sha256"], visual["profile_id"]),
                    )
                self.connection.execute(
                    "INSERT OR REPLACE INTO rendering_observations VALUES (?,?,?)",
                    (doc_id, visual["profile_id"], json.dumps(visual["provenance"], sort_keys=True)),
                )
            uri = path.as_uri()
            previous_copy = self.connection.execute(
                "SELECT copy_id FROM stored_copies WHERE location_uri=?", (uri,)
            ).fetchone()
            copy_id = previous_copy[0] if previous_copy else "copy-" + uuid4().hex
            self.connection.execute(
                """INSERT INTO stored_copies VALUES (?,?,?,?,?,?)
                ON CONFLICT(location_uri) DO UPDATE SET doc_id=excluded.doc_id,
                filename=excluded.filename, owner_id=COALESCE(excluded.owner_id,stored_copies.owner_id),
                observed_at=excluded.observed_at""",
                (copy_id, doc_id, path.name, uri, owner_id, utc_now()),
            )
        return {"document": self.document(doc_id), "copy": self.copy(copy_id),
                "slide_count": len(slides), "warnings": visual["warnings"]}

    def link_revisions(self, doc_id: str, target_doc_id: str, *, confirmed_by: str, reason: str):
        """Explicitly link families, retaining who confirmed the relationship and why."""
        if not confirmed_by.strip() or not reason.strip():
            raise ValueError("Revision linking requires explicit confirmation and evidence")
        source, target = self.document(doc_id), self.document(target_doc_id)
        with self.connection:
            if source["document_id"] != target["document_id"]:
                self.connection.execute(
                    "INSERT INTO family_links VALUES (?,?,?,?,?,?)",
                    (uuid4().hex, source["document_id"], target["document_id"],
                     confirmed_by, reason, utc_now()),
                )
                self.connection.execute(
                    "UPDATE document_versions SET document_id=? WHERE document_id=?",
                    (target["document_id"], source["document_id"]),
                )
        return self.document(doc_id)
