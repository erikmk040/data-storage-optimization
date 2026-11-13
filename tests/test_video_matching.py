import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from src.documents.demo import run_demo
from src.documents.registry import Registry
from src.documents.video_matching import match_recording, resolve_slide_ref, write_matched_package
from src.documents.visuals import calibrate, image_fingerprint, libreoffice_executable
from test_slide_matching import calibration_images, deck, save_page


def test_exact_revision_ambiguity_invalid_reference_and_unavailable_frame(tmp_path):
    blue, red = (0.1, 0.2, 0.8), (0.8, 0.1, 0.1)
    old, revised = tmp_path / "old.pdf", tmp_path / "revised.pdf"
    deck(old, [("Overview", 1, blue), ("Other", 2, blue), ("Color", 3, blue),
               ("Repeated", 5, blue), ("Repeated", 5, blue)])
    deck(revised, [("Overview", 1, blue), ("Other", 2, blue), ("Color", 3, red)])
    save_page(revised, 3, tmp_path / "revision.png")
    save_page(old, 4, tmp_path / "repeated.png")
    Image.new("RGB", (1600, 900), "black").save(tmp_path / "blank.png")
    assert image_fingerprint(Image.new("RGB", (1600, 900), "black"))["phash"] is None
    with Registry(tmp_path / "db.sqlite") as registry:
        first, second = registry.ingest(old), registry.ingest(revised)
        old_id, new_id = first["document"]["doc_id"], second["document"]["doc_id"]
        profile = registry.slides(old_id)[0]["phash_profile"]
        policy = calibrate(registry, profile, calibration_images(tmp_path, old))
        valid_ref = {"doc_id": new_id, "slide_no": 3,
                     "slide_hash": registry.slides(new_id)[2]["text_hash"]}
        invalid_ref = {**valid_ref, "slide_hash": "0" * 64}
        package = {"id": "recording", "extra": "preserved", "frames": [
            {"id": "revision", "file": "revision.png", "phash": "untrusted stored hash"},
            {"id": "ambiguous", "file": "repeated.png"},
            {"id": "missing", "file": "missing.png"},
            {"id": "invalid-prior", "file": "revision.png", "slide_ref": invalid_ref},
            {"id": "valid-prior", "file": "revision.png", "slide_ref": valid_ref},
            {"id": "blank", "file": "blank.png"},
        ]}
        path = tmp_path / "package.json"
        original = json.dumps(package)
        path.write_text(original)
        result = match_recording(registry, path, calibration_id=policy["calibration_id"],
                                 capture_evidence="Full-slide synthetic captures with the registered profile")
        assert result["package"]["extra"] == "preserved"
        assert result["package"]["frames"][0]["slide_ref"] == valid_ref
        assert result["report"]["frames"][0]["status"] == "resolved_exact_pixels"
        assert result["report"]["frames"][1]["status"] == "ambiguous"
        assert result["package"]["frames"][1]["slide_ref"] is None
        assert result["package"]["frames"][2]["slide_ref"] is None
        assert result["report"]["frames"][3]["reference_check"]["status"] == "inconsistent"
        assert result["package"]["frames"][3]["slide_ref"] is None
        assert result["package"]["frames"][4]["slide_ref"] == valid_ref
        assert result["package"]["frames"][5]["slide_ref"] is None
        assert resolve_slide_ref(registry, {**valid_ref, "slide_no": 100})["status"] == "unresolved"
        assert resolve_slide_ref(registry, {**valid_ref, "slide_no": True})["status"] == "invalid"
        assert resolve_slide_ref(registry, {**valid_ref, "doc_id": "family-id"})["status"] == "invalid"
        output = tmp_path / "linked" / "package.json"
        write_matched_package(result, path, output)
        output_package = json.loads(output.read_text())
        assert (output.parent / output_package["frames"][0]["file"]).resolve() == tmp_path / "revision.png"
        with pytest.raises(FileExistsError):
            write_matched_package(result, path, path)
        assert path.read_text() == original
        # A nullable text hash is allowed only when the registered text is unavailable.
        registry.connection.execute("UPDATE slides SET text=NULL,text_hash=NULL WHERE doc_id=? AND slide_no=3", (new_id,))
        assert resolve_slide_ref(registry, {**valid_ref, "slide_hash": None})["status"] == "resolved"


def test_runtime_profile_mismatch_rejected(tmp_path, monkeypatch):
    import src.documents.video_matching as module

    path = tmp_path / "source.pdf"
    deck(path, [("First", 1, (0, 0, 0)), ("Second", 2, (0, 0, 0))])
    with Registry(tmp_path / "db.sqlite") as registry:
        result = registry.ingest(path)
        profile = registry.slides(result["document"]["doc_id"])[0]["phash_profile"]
        policy = calibrate(registry, profile, calibration_images(tmp_path, path))
        monkeypatch.setattr(module, "profile_definition", lambda: {"different": "runtime"})
        with pytest.raises(ValueError, match="incompatible"):
            match_recording(registry, tmp_path / "unused.json", calibration_id=policy["calibration_id"],
                             capture_evidence="Full slide")


def test_reproducible_end_to_end_demo_and_actual_role_c_reader(tmp_path):
    result = run_demo(tmp_path / "demo")
    assert result["all_checks_passed"]
    assert result["video_reference"]["doc_id"] == result["revised_doc_id"]
    assert result["role_c_reader_hits"] > 0
    assert result["inaccessible_copy"] == "no_verified_remaining_copy"


def test_document_cli_workflow(tmp_path):
    directory = tmp_path / "cli-demo"
    summary = run_demo(directory)
    base = [sys.executable, "-m", "src.documents", "--db", str(directory / "documents.db")]

    def command(*args):
        result = subprocess.run(base + list(args), cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    imported = command("ingest", str(directory / "original.pdf"))
    assert imported["document"]["doc_id"] == summary["original_doc_id"]
    assert command("profiles")
    assert command("shared")
    assert command("show", summary["original_doc_id"])["slides"]
    policy = command("calibrate", summary["calibration"]["profile_id"],
                     str(directory / "calibration-pairs.json"))
    assert command("compare", summary["original_doc_id"], summary["revised_doc_id"],
                   "--calibration", policy["calibration_id"])["ambiguous"]
    command("link-revisions", summary["revised_doc_id"], summary["original_doc_id"],
            "--confirmed-by", "cli-test", "--reason", "Explicit synthetic revisions")
    confirmations = directory / "access.json"
    confirmations.write_text(json.dumps({summary["duplicate_copy_ids"][1]: "Team access verified"}))
    assert command("offboarding", summary["duplicate_copy_ids"][0], "--verified-by", "cli-test",
                   "--access-confirmations", str(confirmations))["status"] == "verified_remaining_copy"
    result = command("match-recording", str(directory / "package.json"), "--calibration", policy["calibration_id"],
                     "--capture-evidence", "Full synthetic slide captures", "--output", str(directory / "cli-linked.json"))
    assert result["package"]["frames"][0]["slide_ref"]["doc_id"] == summary["revised_doc_id"]


@pytest.mark.skipif(libreoffice_executable() is None, reason="Native LibreOffice is not installed")
def test_end_to_end_demo_with_native_pptx_rendering(tmp_path):
    result = run_demo(tmp_path / "native-demo", native_pptx=True)
    assert result["all_checks_passed"]
    assert result["pptx_rendering"] == "native LibreOffice"
