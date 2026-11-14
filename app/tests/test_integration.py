"""Framework-independent integration tests for release-critical behavior."""

from __future__ import annotations

import hashlib
import io

import pymupdf
from pptx import Presentation

from app.integration import (
    build_exact_artifact,
    build_pdf_artifact,
    build_pptx_artifact,
    restore_exact_artifact,
    search_knowledge_package,
)
from app.evidence import load_benchmark_evidence
from app.release_benchmark import benchmark_document


def _pdf_bytes() -> bytes:
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Reusable winner knowledge")
        return document.tobytes(garbage=4, deflate=True)


def _pptx_bytes() -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "Reusable winner knowledge"
    output = io.BytesIO()
    presentation.save(output)
    return output.getvalue()


def test_exact_artifact_restores_identical_sha256() -> None:
    source = (b"round trip proof\n" * 64) + bytes(range(128))
    artifact = build_exact_artifact(source)
    restored = restore_exact_artifact(artifact.payload)
    assert restored == source
    assert hashlib.sha256(restored).hexdigest() == artifact.source_sha256
    assert artifact.metadata()["reversible"] is True
    assert artifact.saved_bytes == len(source) - len(artifact.payload)


def test_pdf_artifact_has_search_and_honest_limitations() -> None:
    artifact = build_pdf_artifact(_pdf_bytes())
    result = search_knowledge_package(artifact.payload, "winner")
    assert result["total_hits"] == 1
    assert artifact.searchable and artifact.ai_ready and not artifact.reversible
    assert "semantic_graph_uncompressed" in artifact.component_bytes
    assert any("rendering" in item for item in artifact.limitations)


def test_pptx_artifact_has_search_and_honest_limitations() -> None:
    artifact = build_pptx_artifact(_pptx_bytes(), include_media=False)
    result = search_knowledge_package(artifact.payload, "winner")
    assert result["total_hits"] == 1
    assert artifact.searchable and artifact.ai_ready and not artifact.reversible
    assert artifact.component_bytes["embedded_media_uncompressed"] == 0
    assert any("cannot be reconstructed" in item for item in artifact.limitations)


def test_ascii_export_is_not_a_codec_candidate() -> None:
    artifact = build_pptx_artifact(_pptx_bytes())
    assert "base" not in artifact.codec.casefold()
    assert "ascii" not in artifact.codec.casefold()


def test_benchmark_evidence_uses_signed_byte_math() -> None:
    evidence = load_benchmark_evidence()
    expected = evidence["source"]["bytes"] - evidence["package"]["bytes"]
    assert evidence["saved_bytes"] == expected
    assert evidence["saved_percent"] == expected / evidence["source"]["bytes"] * 100
    assert evidence["status"] == "verified local benchmark evidence"
    assert "not distributed" in evidence["distribution"]


def test_release_benchmark_reports_actual_artifact_bytes(tmp_path) -> None:
    source = tmp_path / "release.pdf"
    source.write_bytes(_pdf_bytes())
    rows = benchmark_document(
        source,
        [("semantic", build_pdf_artifact), ("exact", build_exact_artifact)],
    )
    assert [row["mode"] for row in rows] == ["semantic", "exact"]
    for row in rows:
        assert row["original_bytes"] == source.stat().st_size
        assert row["saved_bytes"] == row["original_bytes"] - row["package_bytes"]

