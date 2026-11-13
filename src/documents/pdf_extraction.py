"""Extract PDF pages as JSON: python -m src.documents.pdf_extraction FILE.pdf.

This standalone output awaits the shared contract in docs/schema.md.
Text extraction uses the PDF's stored text order; it does not perform OCR.
"""

import argparse
import json
from pathlib import Path
from typing import TypedDict

import pymupdf


class PageText(TypedDict):
    page_number: int
    text: str


def extract_pages(path: str | Path) -> list[PageText]:
    """Return every PDF page in document order, including blank pages."""
    with pymupdf.open(path) as document:
        if not document.is_pdf:
            raise ValueError("Input must be a PDF document")
        return [
            {"page_number": number, "text": page.get_text("text")}
            for number, page in enumerate(document, start=1)
        ]


def main(argv: list[str] | None = None) -> int:
    """Write a JSON array of page numbers and extracted text to stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="local PDF path")
    args = parser.parse_args(argv)
    try:
        pages = extract_pages(args.pdf)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(json.dumps(pages, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
