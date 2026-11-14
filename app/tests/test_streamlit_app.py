"""User-visible smoke tests for the Streamlit jury demo."""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf
import pytest
from pptx import Presentation
from streamlit.testing.v1 import AppTest


APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")


def _app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=30).run()


def _pdf_bytes() -> bytes:
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Uploaded aurora knowledge")
        return document.tobytes(garbage=4, deflate=True)


def _pptx_bytes() -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "Semantic presentation proof"
    output = io.BytesIO()
    presentation.save(output)
    return output.getvalue()


def test_clean_start_and_mock_search_show_visual_context() -> None:
    app = _app()
    assert not app.exception
    assert len(app.file_uploader) == 1
    assert [tab.label for tab in app.tabs] == [
        "Measure your files",
        "Search the knowledge",
        "Storage calculator",
        "Challenge coverage",
        "How to pitch it",
    ]
    app.text_input[0].set_value("winner").run()
    assert not app.exception
    assert any("winner" in item.value.casefold() for item in app.markdown)
    assert len(app.image) > 0


def test_exact_upload_reports_measured_result_and_can_clear_session() -> None:
    app = _app()
    payload = b"release proof\n" * 100
    app.file_uploader[0].upload("proof.txt", payload, "text/plain").upload(
        "proof.txt", payload, "text/plain"
    ).upload(
        "same-content-different-name.txt", payload, "text/plain"
    ).run()
    app.button(key="compress_uploads").click().run()
    assert not app.exception
    latest = app.session_state["latest_measurements"]
    assert len(latest) == 2
    assert any("repeated selection" in item.value for item in app.info)
    for measurement in latest:
        assert measurement["facts"]["original file reconstruction"] is True
        assert measurement["saved_bytes"] == (
            measurement["original_bytes"] - measurement["compressed_bytes"]
        )
    app.run()
    app.button(key="clear_uploads").click().run()
    with pytest.raises(KeyError):
        app.session_state["latest_measurements"]


def test_semantic_pdf_warning_package_and_uploaded_search() -> None:
    app = _app()
    app.file_uploader[0].upload("knowledge.pdf", _pdf_bytes(), "application/pdf").run()
    assert any("original page rendering" in item.value for item in app.warning)
    app.button(key="compress_uploads").click().run()
    assert not app.exception
    latest = app.session_state["latest_measurements"]
    assert latest[0]["facts"]["mode"] == "semantic PDF knowledge compression"
    assert latest[0]["saved_bytes"] == (
        latest[0]["original_bytes"] - latest[0]["compressed_bytes"]
    )
    app.text_input[0].set_value("aurora").run()
    assert not app.exception
    assert any("aurora" in item.value.casefold() for item in app.markdown)


def test_semantic_pptx_and_video_modes_show_fidelity_warnings() -> None:
    app = _app()
    app.file_uploader[0].set_value(
        [
            ("knowledge.pptx", _pptx_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
            ("recording.mp4", b"demo-only-video-placeholder", "video/mp4"),
        ]
    ).run()
    warnings = " ".join(item.value for item in app.warning)
    assert "editable original PowerPoint cannot be reconstructed" in warnings
    assert "original audio and discarded motion cannot be reconstructed" in warnings
    assert "speaker diarization is not implemented" in warnings


def test_calculator_uses_latest_semantic_video_measurement() -> None:
    app = AppTest.from_file(APP, default_timeout=30)
    app.session_state["latest_measurements"] = [
        {
            "file": "measured.mp4",
            "original_bytes": 1000,
            "compressed_bytes": 100,
            "saved_bytes": 900,
            "saved_percent": 90.0,
            "facts": {"mode": "semantic video compression"},
        }
    ]
    app.run()
    assert not app.exception
    assert any(
        "latest semantic video measurements" in item.value
        for item in app.caption
    )

