import json
import subprocess
import sys
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

from src.documents.file_hash import hash_file
from src.documents.pptx_revision_demo import compare_presentations, extract_slides


def make_deck(path, texts):
    presentation = Presentation()
    for text in texts:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        if text:
            slide.shapes.add_textbox(0, 0, Inches(6), Inches(2)).text = text
    presentation.save(path)


def run_cli(left, right):
    return subprocess.run(
        [sys.executable, "-m", "src.documents.pptx_revision_demo", str(left), str(right)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True,
    )


def test_revision_cli_and_empty_slides(tmp_path):
    left, right = tmp_path / "first.pptx", tmp_path / "second.pptx"
    make_deck(left, ["Agenda", "Original text", ""])
    make_deck(right, ["Agenda", "Edited text", "", "Extra slide"])
    result = run_cli(left, right)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["identical_bytes"] is False
    assert report["left"]["sha256"] == hash_file(left)
    assert report["right"]["sha256"] == hash_file(right)
    assert report["left"]["slide_count"] == 3
    assert report["right"]["slide_count"] == 4
    assert report["slides"] == [
        {"slide_no": 1, "status": "matches", "left_text": "Agenda",
         "right_text": "Agenda", "neither_has_text": False},
        {"slide_no": 2, "status": "differs", "left_text": "Original text",
         "right_text": "Edited text", "neither_has_text": False},
        {"slide_no": 3, "status": "matches", "left_text": "",
         "right_text": "", "neither_has_text": True},
        {"slide_no": 4, "status": "only_right", "left_text": None,
         "right_text": "Extra slide", "neither_has_text": False},
    ]
    assert report["comparison"] == "corresponding_positions"
    assert any("shift" in item for item in report["limitations"])
    assert any("visual equality" in item for item in report["limitations"])
    assert compare_presentations(right, left)["slides"][-1]["status"] == "only_left"
    copy = tmp_path / "copy.pptx"
    copy.write_bytes(left.read_bytes())
    assert compare_presentations(left, copy)["identical_bytes"] is True


def test_group_and_table_text_order(tmp_path):
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text = "Grouped"
    table = slide.shapes.add_table(1, 2, 0, Inches(2), Inches(4), Inches(1)).table
    table.cell(0, 0).text = "Cell one"
    table.cell(0, 1).text = "Cell two"
    path = tmp_path / "shapes.pptx"
    presentation.save(path)
    assert extract_slides(path) == [
        {"slide_no": 1, "text": "Grouped\nCell one\nCell two"}
    ]


def test_invalid_input_cli(tmp_path):
    missing = tmp_path / "missing.pptx"
    invalid = tmp_path / "invalid.pptx"
    invalid.write_bytes(b"not a presentation")
    for path in (missing, invalid):
        result = run_cli(path, path)
        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr.startswith("Error:")
