"""Validated release evidence shared by the demo and presentation builder."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


EVIDENCE_PATH = Path(__file__).parent / "assets" / "benchmark_evidence.json"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def load_benchmark_evidence(*, verify_local_files: bool = False) -> dict[str, Any]:
    """Load evidence and reject internally inconsistent or stale measurements."""
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    source = evidence["source"]
    package = evidence["package"]
    original = int(source["bytes"])
    compact = int(package["bytes"])
    if original <= 0 or compact <= 0:
        raise ValueError("Benchmark byte counts must be positive")
    if not SHA256_PATTERN.fullmatch(str(source["sha256"])):
        raise ValueError("Benchmark source SHA-256 is invalid")
    if not SHA256_PATTERN.fullmatch(str(package["sha256"])):
        raise ValueError("Benchmark package SHA-256 is invalid")

    evidence["saved_bytes"] = original - compact
    evidence["saved_percent"] = (original - compact) / original * 100
    evidence["local_files_verified"] = False

    if verify_local_files:
        metadata_path = Path(evidence["local_paths"]["metadata"])
        package_path = Path(evidence["local_paths"]["package"])
        if metadata_path.is_file() and package_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            measured_source = metadata["source"]
            if int(measured_source["size_bytes"]) != original:
                raise ValueError("Local source size does not match benchmark evidence")
            if str(measured_source["sha256"]) != source["sha256"]:
                raise ValueError("Local source hash does not match benchmark evidence")
            payload = package_path.read_bytes()
            if len(payload) != compact:
                raise ValueError("Local package size does not match benchmark evidence")
            if hashlib.sha256(payload).hexdigest() != package["sha256"]:
                raise ValueError("Local package hash does not match benchmark evidence")
            evidence["local_files_verified"] = True
    return evidence
