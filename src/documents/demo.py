"""Reproducible synthetic Role B demo: python -m src.documents.demo --native-pptx.

All generated decks, frames, reports, and databases live in a temporary directory
unless --directory is supplied. No Ericsson files or real videos are required.
"""

import argparse
import contextlib
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Pt

from .offboarding import offboarding_report
from .registry import Registry
from .revisions import compare_versions, shared_slides
from .video_matching import match_recording, write_matched_package
from .visuals import calibrate, image_file_fingerprint


def _rectangles(seed):
    rng = random.Random(seed)
    return [(rng.randrange(10, 500), rng.randrange(90, 350), 90, 50) for _ in range(12)]


def make_pdf(path: Path, slides: list[tuple]) -> None:
    with pymupdf.open() as document:
        for text, seed, color in slides:
            page = document.new_page(width=640, height=480)
            if seed is not None:
                for x, y, w, h in _rectangles(seed):
                    page.draw_rect(pymupdf.Rect(x, y, x + w, y + h), fill=color, color=color)
            if text:
                page.insert_text((35, 45), text, fontsize=16)
        document.save(path)


def make_pptx(path: Path, slides: list[tuple]) -> None:
    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = Pt(640), Pt(480)
    for text, seed, color in slides:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        if seed is not None:
            for x, y, w, h in _rectangles(seed):
                shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(x), Pt(y), Pt(w), Pt(h))
                shape.fill.solid()
                shape.fill.fore_color.rgb = RGBColor(*(round(component * 255) for component in color))
                shape.line.fill.background()
        if text:
            box = slide.shapes.add_textbox(Pt(30), Pt(20), Pt(580), Pt(60))
            box.text = text
            box.text_frame.paragraphs[0].font.size = Pt(16)
    presentation.save(path)


def save_page(pdf: Path, number: int, destination: Path) -> None:
    with pymupdf.open(pdf) as document:
        page = document[number - 1]
        scale = 1280 / max(page.rect.width, page.rect.height)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale),
                                 colorspace=pymupdf.csRGB, alpha=False)
        Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples).save(destination)


def reader_smoke(package: Path, directory: Path) -> list[dict]:
    """Run Role C's actual unmodified caller with its database under the demo directory."""
    code = """import json, sys
from pathlib import Path
from src.search.index import index_package
from src.search.query import search
index_package(Path(sys.argv[1]))
index_package(Path(sys.argv[1]))
print(json.dumps(search('revision')))
"""
    environment = os.environ.copy()
    root = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = root + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-c", code, str(package.resolve())],
                            cwd=directory, env=environment, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def run_demo(directory: Path, *, native_pptx: bool = False) -> dict:
    """Exercise all Role B outcomes with assertions on synthetic end-to-end behavior."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    blue, red = (0.1, 0.2, 0.8), (0.8, 0.1, 0.1)
    original, duplicate, revised = [directory / name for name in ("original.pdf", "copy.pdf", "revision.pdf")]
    original_slides = [("Overview", 1, blue), ("Storage costs are increasing", 2, blue),
                       ("Color only", 3, blue), ("Removed", 4, blue),
                       ("Repeated", 5, blue), ("Repeated", 5, blue), ("", None, blue)]
    revised_slides = [("Storage costs are increasing!", 2, blue), ("Overview", 1, blue),
                      ("Color only", 3, red), ("Inserted unrelated material", 8, blue),
                      ("Repeated", 5, blue), ("", None, blue)]
    make_pdf(original, original_slides)
    duplicate.write_bytes(original.read_bytes())
    make_pdf(revised, revised_slides)
    with Registry(directory / "documents.db") as registry:
        first = registry.ingest(original, owner_id="leaving", metadata={"revision": "A"})
        second = registry.ingest(duplicate, owner_id="team")
        repeated = registry.ingest(original)
        changed = registry.ingest(revised, owner_id="team", metadata={"revision": "B"})
        old_id, new_id = first["document"]["doc_id"], changed["document"]["doc_id"]
        assert old_id == second["document"]["doc_id"]
        assert first["copy"]["copy_id"] != second["copy"]["copy_id"]
        assert repeated["copy"]["copy_id"] == first["copy"]["copy_id"]
        assert first["document"]["document_id"] != changed["document"]["document_id"]
        registry.link_revisions(new_id, old_id, confirmed_by="synthetic-demo",
                                 reason="Demo generator explicitly created revision B from A")
        profile = registry.slides(old_id)[0]["phash_profile"]
        positive, compressed, negative = [directory / name for name in ("positive.png", "compressed.jpg", "negative.png")]
        save_page(original, 1, positive)
        save_page(original, 2, negative)
        with Image.open(positive) as image:
            image.resize((640, 480)).save(compressed, quality=85)
        pairs = [{"left": str(positive), "right": str(compressed), "same_slide": True},
                 {"left": str(positive), "right": str(negative), "same_slide": False}]
        (directory / "calibration-pairs.json").write_text(json.dumps(pairs, indent=2))
        policy = calibrate(registry, profile, pairs)
        comparison = compare_versions(registry, old_id, new_id, calibration_id=policy["calibration_id"])
        assert any(m["moved"] and m["left_slide_no"] == 1 for m in comparison["matches"])
        assert any(m["status"] == "changed" and m["left_slide_no"] == 2 for m in comparison["matches"])
        assert any(m["visual_change"] and m["same_nonempty_text"] for m in comparison["matches"])
        assert 4 in comparison["removed"] and 4 in comparison["inserted"]
        assert comparison["ambiguous"]
        assert 7 in comparison["removed"] and 6 in comparison["inserted"]
        assert shared_slides(registry)

        # Exercise PPTX import too. The default pairs synthetic PDF/PPTX source
        # generation explicitly; --native-pptx requires actual LibreOffice export.
        pptx_results = []
        for label, slides in (("pptx-original", [("PPTX agenda", 21, blue), ("", None, blue)]),
                              ("pptx-revised", [("PPTX agenda updated", 21, blue), ("", None, blue),
                                                 ("PPTX extra", 22, blue)])):
            path = directory / (label + ".pptx")
            make_pptx(path, slides)
            options = {"render": "required"}
            if not native_pptx:
                sidecar = directory / (label + ".pdf")
                make_pdf(sidecar, slides)
                options.update(rendered_pdf=sidecar, render_evidence="Paired synthetic rendering generated from identical demo inputs")
            result = registry.ingest(path, **options)
            pptx_slides = registry.slides(result["document"]["doc_id"])
            assert [s["slide_no"] for s in pptx_slides] == list(range(1, len(slides) + 1))
            assert pptx_slides[1]["text"] == "" and pptx_slides[0]["phash"] is not None
            pptx_results.append(result["document"]["doc_id"])

        unconfirmed = offboarding_report(registry, first["copy"]["copy_id"], verified_by="synthetic-demo")
        assert unconfirmed["status"] == "no_verified_remaining_copy"
        confirmations = {second["copy"]["copy_id"]: "Synthetic team-owned folder remains accessible"}
        verified = offboarding_report(registry, first["copy"]["copy_id"], verified_by="synthetic-demo",
                                      access_confirmations=confirmations)
        assert verified["status"] == "verified_remaining_copy"
        offline_path = directory / "temporarily-offline.pdf"
        duplicate.rename(offline_path)
        try:
            inaccessible = offboarding_report(registry, first["copy"]["copy_id"], verified_by="synthetic-demo",
                                              access_confirmations=confirmations)
            assert inaccessible["status"] == "no_verified_remaining_copy"
        finally:
            offline_path.rename(duplicate)

        revision_frame, ambiguous_frame = directory / "revision-frame.png", directory / "ambiguous-frame.png"
        save_page(revised, 3, revision_frame)
        save_page(original, 5, ambiguous_frame)
        package = {"id": "role-b-demo", "source": {"file": "synthetic.mp4",
                    "sha256": hashlib.sha256(b"").hexdigest(), "size_bytes": 0, "duration_s": 30},
                   "segments": [{"start": 0, "end": 10, "speaker": "DEMO", "text": "Revision demo",
                                 "frame_id": "revision-frame"}],
                   "frames": [{"id": "revision-frame", "t": 0, "file": revision_frame.name,
                               "phash": image_file_fingerprint(revision_frame)["phash"], "ocr_text": "revision capture"},
                              {"id": "ambiguous-frame", "t": 10, "file": ambiguous_frame.name,
                               "phash": image_file_fingerprint(ambiguous_frame)["phash"], "ocr_text": "repeated"}]}
        package_path = directory / "package.json"
        original_payload = json.dumps(package, indent=2)
        package_path.write_text(original_payload)
        matching = match_recording(registry, package_path, calibration_id=policy["calibration_id"],
                                    capture_evidence="Full uncropped synthetic slides rendered with the registered profile")
        reference = matching["package"]["frames"][0]["slide_ref"]
        assert reference["doc_id"] == new_id and reference["slide_no"] == 3
        assert matching["report"]["frames"][1]["status"] == "ambiguous"
        assert matching["package"]["frames"][1]["slide_ref"] is None
        output = directory / "linked" / "package.json"
        write_matched_package(matching, package_path, output)
        assert package_path.read_text() == original_payload
        hits = reader_smoke(output, directory)
        assert any(hit["frame"] and hit["frame"]["doc_id"] == new_id
                   and hit["frame"]["slide_hash"] == reference["slide_hash"] for hit in hits)
        for hit in hits:
            if hit["frame"]:
                assert Path(hit["frame"]["file"]).is_file()
        summary = {
            "duplicate_copy_ids": [first["copy"]["copy_id"], second["copy"]["copy_id"]],
            "original_doc_id": old_id, "revised_doc_id": new_id,
            "reimport_idempotent": True, "calibration": policy, "comparison": comparison,
            "pptx_versions": pptx_results,
            "pptx_rendering": "native LibreOffice" if native_pptx else "attested synthetic companion PDF",
            "offboarding_verified": verified["status"], "inaccessible_copy": inaccessible["status"],
            "unconfirmed_copy": unconfirmed["status"], "video_reference": reference,
            "video_ambiguous": matching["report"]["frames"][1]["status"],
            "role_c_reader_hits": len(hits), "all_checks_passed": True,
        }
        (directory / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, help="retain synthetic artifacts in a NEW directory")
    parser.add_argument("--native-pptx", action="store_true", help="require native LibreOffice conversion")
    args = parser.parse_args(argv)
    context = tempfile.TemporaryDirectory(prefix="role-b-demo-") if args.directory is None else contextlib.nullcontext(None)
    try:
        with context as directory:
            destination = args.directory or Path(directory) / "demo"
            summary = run_demo(destination, native_pptx=args.native_pptx)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
