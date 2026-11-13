import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest
from pptx import Presentation
from pptx.util import Inches

from src.documents.registry import Registry, text_hash


@pytest.fixture(autouse=True)
def text_registry_without_native_converter(monkeypatch):
    monkeypatch.setattr("src.documents.visuals.libreoffice_executable", lambda: None)


def make_pdf(path, texts):
    with pymupdf.open() as document:
        for text in texts:
            page = document.new_page()
            if text:
                page.insert_text((50, 60), text)
        document.save(path)


def make_pptx(path, texts):
    presentation = Presentation()
    for text in texts:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        if text:
            slide.shapes.add_textbox(0, 0, Inches(6), Inches(2)).text = text
    presentation.save(path)


@pytest.mark.parametrize("kind,make", [("pdf", make_pdf), ("pptx", make_pptx)])
def test_import_duplicate_copies_reimport_and_revisions(tmp_path, kind, make):
    first, copy, revision = [tmp_path / (name + "." + kind) for name in ("a", "b", "rev")]
    make(first, ["First", "", "Third"])
    copy.write_bytes(first.read_bytes())
    make(revision, ["Third", "First edited", ""])
    db = tmp_path / "registry.db"
    with Registry(db) as registry:
        result = registry.ingest(first, owner_id="leaving", metadata={
            "revision": "A", "document_number": "DOC-1", "author": "Author",
            "document_date": "2026-11-13",
        })
        repeated = registry.ingest(first)
        assert result["copy"]["copy_id"] == repeated["copy"]["copy_id"]
        assert repeated["copy"]["owner_id"] == "leaving"
        second = registry.ingest(copy, owner_id="team")
        doc_id = result["document"]["doc_id"]
        assert doc_id == "sha256:" + hashlib.sha256(first.read_bytes()).hexdigest()
        assert second["document"]["doc_id"] == doc_id
        assert result["copy"]["copy_id"] != second["copy"]["copy_id"]
        assert len(registry.copies(doc_id)) == 2
        slides = registry.slides(doc_id)
        assert [slide["slide_no"] for slide in slides] == [1, 2, 3]
        assert slides[1]["text"] == ""
        assert slides[1]["text_hash"] == hashlib.sha256(b"").hexdigest()
        assert slides[0]["text_hash"] == text_hash(slides[0]["text"])
        assert text_hash(None) is None
        changed = registry.ingest(revision, metadata={"revision": "B"})
        assert changed["document"]["document_id"] != result["document"]["document_id"]
        with pytest.raises(ValueError, match="confirmation"):
            registry.link_revisions(changed["document"]["doc_id"], doc_id,
                                    confirmed_by="", reason="same name")
        linked = registry.link_revisions(changed["document"]["doc_id"], doc_id,
                                         confirmed_by="team", reason="Confirmed revisions A and B")
        assert linked["document_id"] == result["document"]["document_id"]
        first.write_bytes(revision.read_bytes())
        updated = registry.ingest(first)
        assert updated["copy"]["copy_id"] == result["copy"]["copy_id"]
        assert updated["copy"]["doc_id"] == changed["document"]["doc_id"]
    with Registry(db) as reopened:
        assert len(reopened.copies()) == 3
        assert reopened.document(doc_id)["author"] == "Author"


def test_failed_import_rolls_back_and_cli(tmp_path):
    path = tmp_path / "source.pdf"
    make_pdf(path, ["Hello"])
    db = tmp_path / "registry.db"
    with Registry(db) as registry:
        registry.connection.execute(
            "CREATE TRIGGER fail_slide BEFORE INSERT ON slides BEGIN SELECT RAISE(ABORT,'test failure'); END"
        )
        with pytest.raises(Exception, match="test failure"):
            registry.ingest(path)
        for table in ("document_families", "document_versions", "slides", "stored_copies"):
            assert registry.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        registry.connection.execute("DROP TRIGGER fail_slide")
        invalid = tmp_path / "invalid.pptx"
        invalid.write_bytes(b"broken")
        with pytest.raises(Exception):
            registry.ingest(invalid)
        assert registry.copies() == []
    result = subprocess.run(
        [sys.executable, "-m", "src.documents", "--db", str(db), "ingest", str(path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout)["slide_count"] == 1


def test_source_change_and_metadata_conflict_leave_no_partial_updates(tmp_path, monkeypatch):
    import src.documents.registry as module

    path = tmp_path / "source.pdf"
    make_pdf(path, ["One"])
    with Registry(tmp_path / "db.sqlite") as registry:
        initial = registry.ingest(path, metadata={"author": "One"})
        with pytest.raises(ValueError, match="Conflicting"):
            registry.ingest(path, metadata={"revision": "A", "author": "Two"})
        assert registry.document(initial["document"]["doc_id"])["revision"] is None
        make_pdf(tmp_path / "other.pdf", ["Other"])
        original = module.extract_pages

        def change_source(snapshot):
            path.write_bytes((tmp_path / "other.pdf").read_bytes())
            return original(snapshot)

        monkeypatch.setattr(module, "extract_pages", change_source)
        with pytest.raises(ValueError, match="Source changed"):
            registry.ingest(path)
        assert registry.copy(initial["copy"]["copy_id"])["doc_id"] == initial["document"]["doc_id"]
