import json
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

from src.documents.pdf_extraction import extract_pages


def test_page_order_numbering_blank_pages_and_cli(tmp_path):
    path = tmp_path / "synthetic.pdf"
    texts = ["", "Second page", "", "Fourth page", ""]
    with pymupdf.open() as document:
        for text in texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        document.save(path)

    expected = [
        {"page_number": number, "text": text + "\n" if text else ""}
        for number, text in enumerate(texts, start=1)
    ]
    assert extract_pages(path) == expected
    result = subprocess.run(
        [sys.executable, "-m", "src.documents.pdf_extraction", str(path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == expected
    assert result.stderr == ""


def test_missing_pdf_reports_cli_error(tmp_path):
    path = tmp_path / "missing.pdf"
    with pytest.raises(pymupdf.FileNotFoundError):
        extract_pages(path)
    result = subprocess.run(
        [sys.executable, "-m", "src.documents.pdf_extraction", str(path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("Error:")
