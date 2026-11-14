"""Release-contract tests for the deployable FastAPI adapter."""

from __future__ import annotations

import hashlib
import io

import pymupdf
from fastapi.testclient import TestClient
from pptx import Presentation

import app.integration as integration
from app.api import app


client = TestClient(app)


def _pdf_bytes(text: str = "Winner evidence is searchable") -> bytes:
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), text)
        return document.tobytes(garbage=4, deflate=True)


def _pptx_bytes(text: str = "Winner evidence is searchable") -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = text
    output = io.BytesIO()
    presentation.save(output)
    return output.getvalue()


def _assert_package_headers(response, source: bytes, *, reversible: bool) -> None:
    assert response.status_code == 200
    assert response.headers["x-kp-source-sha256"] == hashlib.sha256(source).hexdigest()
    assert response.headers["x-kp-package-sha256"] == hashlib.sha256(response.content).hexdigest()
    assert int(response.headers["x-kp-original-bytes"]) == len(source)
    assert int(response.headers["x-kp-package-bytes"]) == len(response.content)
    assert int(response.headers["x-kp-saved-bytes"]) == len(source) - len(response.content)
    assert response.headers["x-kp-reversible"] == str(reversible).lower()
    assert response.headers["x-kp-searchable"] == str(not reversible).lower()
    assert response.headers["x-kp-ai-ready"] == str(not reversible).lower()
    assert response.headers["x-kp-fidelity"]
    assert response.headers["x-kp-largest-component"]
    for header in (
        "x-kp-transcript-bytes",
        "x-kp-graph-manifest-bytes",
        "x-kp-reference-bytes",
        "x-kp-unique-visual-bytes",
        "x-kp-deduplicated-bytes",
        "x-kp-archive-header-overhead",
    ):
        assert int(response.headers[header]) >= 0


def test_health_and_capabilities_are_explicit() -> None:
    assert client.get("/health").json()["status"] == "ok"
    capabilities = client.get("/v1/capabilities")
    assert capabilities.status_code == 200
    assert set(capabilities.json()["formats"]) == {"exact", "pdf", "pptx", "video"}
    assert "does_not_preserve" in capabilities.json()["formats"]["video"]


def test_exact_api_round_trip_and_signed_headers() -> None:
    source = (b"Ericsson release evidence\n" * 128) + bytes(range(64))
    packaged = client.post(
        "/v1/packages/exact",
        content=source,
        headers={"content-type": "application/octet-stream"},
    )
    _assert_package_headers(packaged, source, reversible=True)
    restored = client.post(
        "/v1/restore/exact",
        content=packaged.content,
        headers={"content-type": "application/vnd.ericsson.knowledge-package"},
    )
    assert restored.status_code == 200
    assert restored.content == source
    assert restored.headers["x-kp-restored-sha256"] == hashlib.sha256(source).hexdigest()


def test_pdf_package_is_searchable_and_reports_semantic_fidelity() -> None:
    source = _pdf_bytes()
    packaged = client.post(
        "/v1/packages/pdf", content=source, headers={"content-type": "application/pdf"}
    )
    _assert_package_headers(packaged, source, reversible=False)
    searched = client.post(
        "/v1/search?q=winner",
        content=packaged.content,
        headers={"content-type": "application/vnd.ericsson.knowledge-package"},
    )
    assert searched.status_code == 200
    assert searched.json()["kind"] == "pdf"
    assert searched.json()["total_hits"] == 1


def test_pptx_package_is_searchable_and_reports_semantic_fidelity() -> None:
    source = _pptx_bytes()
    packaged = client.post(
        "/v1/packages/pptx?include_media=false",
        content=source,
        headers={
            "content-type": "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        },
    )
    _assert_package_headers(packaged, source, reversible=False)
    searched = client.post(
        "/v1/search?q=winner",
        content=packaged.content,
        headers={"content-type": "application/vnd.ericsson.knowledge-package"},
    )
    assert searched.status_code == 200
    assert searched.json()["kind"] == "pptx"
    assert searched.json()["total_hits"] == 1


def test_invalid_empty_and_unsupported_packages_are_rejected() -> None:
    empty = client.post(
        "/v1/packages/exact",
        content=b"",
        headers={"content-type": "application/octet-stream"},
    )
    assert empty.status_code == 422
    invalid_search = client.post(
        "/v1/search?q=winner",
        content=b"not-a-package",
        headers={"content-type": "application/vnd.ericsson.knowledge-package"},
    )
    assert invalid_search.status_code == 422


def test_document_size_limit_is_enforced(monkeypatch) -> None:
    monkeypatch.setattr(integration, "MAX_INPUT_BYTES", 8)
    response = client.post(
        "/v1/packages/exact",
        content=b"123456789",
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 422
    assert "limit" in response.json()["detail"].lower()

