"""Run measured PDF/PPTX release benchmarks without writing generated artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from app.evidence import load_benchmark_evidence
from app.integration import (
    KnowledgeArtifact,
    build_exact_artifact,
    build_pdf_artifact,
    build_pptx_artifact,
)


def _row(file: Path, mode: str, artifact: KnowledgeArtifact) -> dict[str, object]:
    return {
        "file": file.name,
        "mode": mode,
        **artifact.metadata(),
    }


def benchmark_document(
    file: Path,
    builders: list[tuple[str, Callable[[bytes], KnowledgeArtifact]]],
) -> list[dict[str, object]]:
    data = file.read_bytes()
    return [_row(file, mode, builder(data)) for mode, builder in builders]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure semantic and exact knowledge-package modes."
    )
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--pptx", type=Path)
    parser.add_argument("--exact-file", type=Path, action="append", default=[])
    parser.add_argument("--include-local-video-evidence", action="store_true")
    args = parser.parse_args()
    if not args.pdf and not args.pptx and not args.exact_file and not args.include_local_video_evidence:
        parser.error(
            "provide --pdf, --pptx, --exact-file, or --include-local-video-evidence"
        )

    results: list[dict[str, object]] = []
    if args.pdf:
        results.extend(
            benchmark_document(
                args.pdf,
                [("semantic", build_pdf_artifact), ("exact", build_exact_artifact)],
            )
        )
    if args.pptx:
        results.extend(
            benchmark_document(
                args.pptx,
                [
                    ("semantic_with_media", build_pptx_artifact),
                    (
                        "semantic_graph_only",
                        lambda data: build_pptx_artifact(data, include_media=False),
                    ),
                    ("exact", build_exact_artifact),
                ],
            )
        )
    for exact_file in args.exact_file:
        results.extend(
            benchmark_document(exact_file, [("exact", build_exact_artifact)])
        )
    if args.include_local_video_evidence:
        evidence = load_benchmark_evidence(verify_local_files=True)
        results.append(
            {
                "file": evidence["source"]["file"],
                "mode": "semantic_video_local_evidence",
                "original_bytes": evidence["source"]["bytes"],
                "package_bytes": evidence["package"]["bytes"],
                "saved_bytes": evidence["saved_bytes"],
                "saved_percent": evidence["saved_percent"],
                "source_sha256": evidence["source"]["sha256"],
                "package_sha256": evidence["package"]["sha256"],
                "local_files_verified": evidence["local_files_verified"],
                "reversible": False,
                "searchable": True,
                "ai_ready": True,
                "limitations": evidence["fidelity"]["not_preserved"],
            }
        )
    print(json.dumps({"results": results}, indent=2))


if __name__ == "__main__":
    main()
