"""Compare slide text: python -m src.documents.pptx_revision_demo LEFT RIGHT.

Slides are compared at corresponding positions, not aligned by content.
"""

import argparse
import json
from itertools import zip_longest
from pathlib import Path
from zipfile import BadZipFile

from pptx import Presentation
from pptx.exc import PythonPptxError

from .file_hash import hash_file


LIMITATIONS = [
    "Inserted or reordered slides can shift the positional comparison.",
    "Equal extracted text does not establish visual equality.",
    "Text follows shape order, including groups and table cells; no OCR, "
    "speaker notes, chart labels, or visual reading-order inference is used.",
]


def _shape_texts(shapes):
    """Yield text in shape order, descending into groups and tables."""
    for shape in shapes:
        if shape.has_text_frame:
            yield shape.text_frame.text
        elif shape.has_table:
            for row in shape.table.rows:
                for cell in row.cells:
                    if not cell.is_spanned:
                        yield cell.text
        elif hasattr(shape, "shapes"):
            yield from _shape_texts(shape.shapes)


def extract_slides(path: str | Path) -> list[dict]:
    """Extract slide text in presentation order, retaining empty slides."""
    presentation = Presentation(str(path))
    return [
        {
            "slide_no": number,
            "text": "\n".join(text for text in _shape_texts(slide.shapes) if text),
        }
        for number, slide in enumerate(presentation.slides, start=1)
    ]


def compare_presentations(left: str | Path, right: str | Path) -> dict:
    """Report exact text equality at each position and source byte equality."""
    left_slides, right_slides = extract_slides(left), extract_slides(right)
    left_hash, right_hash = hash_file(left), hash_file(right)
    comparisons = []
    for number, (first, second) in enumerate(
        zip_longest(left_slides, right_slides), start=1
    ):
        left_text = first["text"] if first is not None else None
        right_text = second["text"] if second is not None else None
        if first is None:
            status = "only_right"
        elif second is None:
            status = "only_left"
        else:
            status = "matches" if left_text == right_text else "differs"
        comparisons.append({
            "slide_no": number,
            "status": status,
            "left_text": left_text,
            "right_text": right_text,
            "neither_has_text": first is not None and second is not None
            and not left_text.strip() and not right_text.strip(),
        })
    return {
        "left": {"file": str(left), "sha256": left_hash, "slide_count": len(left_slides)},
        "right": {"file": str(right), "sha256": right_hash, "slide_count": len(right_slides)},
        "identical_bytes": left_hash == right_hash,
        "comparison": "corresponding_positions",
        "limitations": LIMITATIONS,
        "slides": comparisons,
    }


def main(argv: list[str] | None = None) -> int:
    """Write a standalone JSON comparison report to stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path, help="first local PPTX path")
    parser.add_argument("right", type=Path, help="second local PPTX path")
    args = parser.parse_args(argv)
    try:
        report = compare_presentations(args.left, args.right)
    except (OSError, ValueError, KeyError, BadZipFile, PythonPptxError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
