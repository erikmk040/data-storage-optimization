import json
import random
import subprocess
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from src.documents.registry import Registry
from src.documents.revisions import compare_versions, shared_slides
from src.documents.visuals import (
    calibrate, canonical_image, image_file_fingerprint, profile_definition,
    profile_identity, libreoffice_executable,
)
from test_document_registry import make_pptx


def deck(path, slides):
    """Draw distinctive layouts; source text and visible graphics vary independently."""
    with pymupdf.open() as document:
        for text, seed, tint in slides:
            page = document.new_page(width=640, height=480)
            rng = random.Random(seed)
            if seed is not None:
                for _ in range(12):
                    x, y = rng.randrange(10, 500), rng.randrange(90, 350)
                    page.draw_rect(pymupdf.Rect(x, y, x + 90, y + 50),
                                   fill=tint, color=tint)
            if text:
                page.insert_text((35, 45), text, fontsize=16)
        document.save(path)


def save_page(pdf, number, path):
    with pymupdf.open(pdf) as document:
        page = document[number - 1]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csRGB, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        image.save(path)


def calibration_images(tmp_path, pdf):
    first, compressed, negative = [tmp_path / name for name in ("first.png", "compressed.jpg", "negative.png")]
    save_page(pdf, 1, first)
    with Image.open(first) as image:
        image.resize((640, 480)).save(compressed, quality=85)
    save_page(pdf, 2, negative)
    return [{"left": str(first), "right": str(compressed), "same_slide": True},
            {"left": str(first), "right": str(negative), "same_slide": False}]


def test_reordered_changed_inserted_removed_ambiguous_and_visual_edits(tmp_path):
    first, revised = tmp_path / "a.pdf", tmp_path / "b.pdf"
    blue, red = (0.1, 0.2, 0.8), (0.8, 0.1, 0.1)
    deck(first, [("Overview", 1, blue), ("Storage costs are increasing", 2, blue),
                 ("Color only", 3, blue), ("Removed", 4, blue),
                 ("Repeated", 5, blue), ("Repeated", 5, blue), ("", None, blue)])
    deck(revised, [("Storage costs are increasing!", 2, blue), ("Overview", 1, blue),
                   ("Color only", 3, red), ("Inserted unrelated material", 8, blue),
                   ("Repeated", 5, blue), ("", None, blue)])
    with Registry(tmp_path / "db.sqlite") as registry:
        left, right = registry.ingest(first)["document"], registry.ingest(revised)["document"]
        assert left["document_id"] != right["document_id"]
        slides = registry.slides(left["doc_id"])
        assert slides[0]["phash"] is not None
        assert len(slides[0]["phash"]) == 16
        assert slides[-1]["phash"] is None  # Uniform image cannot establish a match.
        profile = slides[0]["phash_profile"]
        policy = calibrate(registry, profile, calibration_images(tmp_path, first))
        assert policy["max_distance"] < policy["min_negative_distance"]
        report = compare_versions(registry, left["doc_id"], right["doc_id"],
                                  calibration_id=policy["calibration_id"])
        moved = next(item for item in report["matches"] if item["left_slide_no"] == 1)
        assert moved["right_slide_no"] == 2 and moved["moved"]
        edited = next(item for item in report["matches"] if item["left_slide_no"] == 2)
        assert edited["right_slide_no"] == 1 and edited["status"] == "changed"
        visual = next(item for item in report["matches"] if item["left_slide_no"] == 3)
        assert visual["same_nonempty_text"] and visual["visual_change"]
        assert visual["status"] == "changed"
        assert {4, 7}.issubset(report["removed"])
        assert {4, 6}.issubset(report["inserted"])
        assert {item["left_slide_no"] for item in report["ambiguous"]} == {5, 6}
        assert shared_slides(registry)
        before = registry.connection.execute("SELECT COUNT(*) FROM visual_calibrations").fetchone()[0]
        pairs = calibration_images(tmp_path, first)
        pairs[1]["right"] = pairs[1]["left"]
        with pytest.raises(ValueError, match="separable"):
            calibrate(registry, profile, pairs)
        assert registry.connection.execute("SELECT COUNT(*) FROM visual_calibrations").fetchone()[0] == before


def test_incompatible_profiles_and_no_empty_text_matches(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    deck(a, [("", 1, (0, 0, 0)), ("", None, (0, 0, 0))])
    deck(b, [("", 1, (0, 0, 0)), ("", None, (0, 0, 0))])
    with Registry(tmp_path / "db.sqlite") as registry:
        left, right = registry.ingest(a)["document"], registry.ingest(b)["document"]
        definition = profile_definition()
        definition["renderer_version"] = "incompatible"
        incompatible = profile_identity(definition)
        registry.connection.execute("INSERT INTO phash_profiles VALUES (?,?)",
                                    (incompatible, json.dumps(definition)))
        registry.connection.execute("UPDATE rendered_slides SET profile_id=? WHERE doc_id=?",
                                    (incompatible, right["doc_id"]))
        registry.connection.execute("UPDATE slides SET phash_profile=? WHERE doc_id=? AND phash IS NOT NULL",
                                    (incompatible, right["doc_id"]))
        registry.connection.commit()
        report = compare_versions(registry, left["doc_id"], right["doc_id"])
        assert report["matches"] == []
        assert report["ambiguous"] == []
        assert shared_slides(registry) == []


def test_pptx_attested_rendering_is_atomic_and_missing_converter(tmp_path, monkeypatch):
    import src.documents.visuals as module

    pptx, pdf = tmp_path / "deck.pptx", tmp_path / "rendered.pdf"
    make_pptx(pptx, ["Title", ""])
    deck(pdf, [("Title", 1, (0.1, 0.2, 0.8)), ("", None, (0, 0, 0))])
    monkeypatch.setattr(module, "libreoffice_executable", lambda: None)
    with Registry(tmp_path / "db.sqlite") as registry:
        with pytest.raises(ValueError, match="requires LibreOffice"):
            registry.ingest(pptx, render="required")
        assert registry.copies() == []
        result = registry.ingest(pptx)
        assert result["warnings"]
        assert registry.slides(result["document"]["doc_id"])[0]["phash"] is None
        with pytest.raises(ValueError, match="render-evidence"):
            registry.ingest(pptx, rendered_pdf=pdf)
        result = registry.ingest(pptx, rendered_pdf=pdf, render_evidence="Synthetic deck generated with this PDF")
        assert registry.slides(result["document"]["doc_id"])[0]["phash"] is not None
        wrong = tmp_path / "wrong.pdf"
        deck(wrong, [("Wrong count", 1, (0, 0, 0))])
        with pytest.raises(ValueError, match="page count"):
            registry.ingest(pptx, rendered_pdf=wrong, render_evidence="Test")
        assert len(registry.copies()) == 1


def test_render_storage_failure_rolls_back_all_import_records(tmp_path):
    path = tmp_path / "source.pdf"
    deck(path, [("Render", 1, (0, 0, 0))])
    with Registry(tmp_path / "db.sqlite") as registry:
        registry.connection.execute(
            "CREATE TRIGGER fail_render BEFORE INSERT ON rendering_observations "
            "BEGIN SELECT RAISE(ABORT,'render storage failure'); END"
        )
        with pytest.raises(Exception, match="render storage failure"):
            registry.ingest(path)
        for table in ("document_families", "document_versions", "slides", "stored_copies",
                      "phash_profiles", "rendered_slides", "rendering_observations"):
            assert registry.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_libreoffice_conversion_uses_isolated_profile_and_provenance(tmp_path, monkeypatch):
    import src.documents.visuals as module

    path = tmp_path / "deck.pptx"
    make_pptx(path, ["Slide"])
    monkeypatch.setattr(module, "libreoffice_executable", lambda: "test-soffice")

    def convert(command, **kwargs):
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "LibreOffice test-version", "")
        assert any("UserInstallation=file:" in item for item in command)
        assert "ExportHiddenSlides" in command[command.index("--convert-to") + 1]
        directory = command[command.index("--outdir") + 1]
        deck(Path(directory) / "source.pdf", [("Slide", 1, (0, 0, 0))])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", convert)
    with Registry(tmp_path / "db.sqlite") as registry:
        result = registry.ingest(path, render="required")
        provenance = json.loads(registry.connection.execute(
            "SELECT provenance FROM rendering_observations"
        ).fetchone()[0])
        assert provenance["converter_version"] == "LibreOffice test-version"
        assert registry.slides(result["document"]["doc_id"])[0]["phash"]


@pytest.mark.skipif(libreoffice_executable() is None, reason="Native LibreOffice is not installed")
def test_native_libreoffice_pptx_rendering_including_hidden_empty_slide(tmp_path):
    from pptx import Presentation

    path = tmp_path / "native.pptx"
    make_pptx(path, ["Native rendered slide", ""])
    presentation = Presentation(path)
    presentation.slides[1]._element.set("show", "0")
    presentation.save(path)
    with Registry(tmp_path / "db.sqlite") as registry:
        result = registry.ingest(path, render="required")
        slides = registry.slides(result["document"]["doc_id"])
        assert len(slides) == 2
        assert slides[0]["phash"] is not None
        assert slides[1]["text"] == ""
        provenance = json.loads(registry.connection.execute(
            "SELECT provenance FROM rendering_observations"
        ).fetchone()[0])
        assert provenance["conversion"] == "LibreOffice"
        assert provenance["converter_version"]
