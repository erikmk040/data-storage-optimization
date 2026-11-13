"""Generate auditable remaining-copy evidence without deleting any source file."""

import json
from pathlib import Path
from uuid import uuid4

from .file_hash import hash_file
from .registry import local_path, utc_now


def _verified_digest(path: Path) -> str:
    before = path.stat()
    digest = hash_file(path)
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise ValueError("File changed while being verified")
    return digest


def offboarding_report(registry, source_copy_id: str, *, verified_by: str,
                       access_confirmations: dict[str, str] | None = None,
                       remaining_copy_id: str | None = None) -> dict:
    """Re-read both files; survival requires explicit evidence of continued team access.

    A successful read proves accessibility now, not continued access after an
    account is removed. That separate claim must be explicitly confirmed.
    """
    if not isinstance(verified_by, str) or not verified_by.strip():
        raise ValueError("Offboarding verification requires an identified verifier")
    confirmations = {} if access_confirmations is None else access_confirmations
    if not isinstance(confirmations, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) or not value.strip()
        for key, value in confirmations.items()
    ):
        raise ValueError("Access confirmations must map copy IDs to nonempty evidence strings")
    source = registry.copy(source_copy_id)
    candidates = ([registry.copy(remaining_copy_id)] if remaining_copy_id else
                  [copy for copy in registry.copies(source["doc_id"]) if copy["copy_id"] != source_copy_id])
    report = {
        "report_id": "offboarding-" + uuid4().hex, "source_copy_id": source_copy_id,
        "verified_by": verified_by, "verified_at": utc_now(),
        "status": "no_verified_remaining_copy", "candidates": [], "evidence": [],
        "limitations": ["Evidence describes this verification time only; recheck before taking action.",
                        "Continued team access is explicitly attested, not inferred from an owner ID.",
                        "This report neither authorizes nor performs deletion."],
    }
    expected = registry.document(source["doc_id"])["sha256"]
    try:
        source_path = local_path(source["location_uri"])
        source_digest = _verified_digest(source_path)
        if source_digest != expected:
            raise ValueError("Source bytes no longer match the registered file version")
    except (OSError, ValueError) as error:
        report["source_error"] = str(error)
        report["status"] = "source_unverified"
        return _record_report(registry, report)
    for candidate in candidates:
        result = {"remaining_copy_id": candidate["copy_id"], "status": "unverified",
                  "hashes_verified": False, "survives_offboarding": False}
        report["candidates"].append(result)
        if candidate["copy_id"] == source_copy_id or candidate["doc_id"] != source["doc_id"]:
            result.update(status="not_a_distinct_copy_of_this_version")
            continue
        try:
            remaining_path = local_path(candidate["location_uri"])
            if source_path.samefile(remaining_path):
                result.update(status="same_physical_file")
                continue
            remaining_digest = _verified_digest(remaining_path)
            # Detect changes to the source during remaining-copy verification too.
            if _verified_digest(source_path) != source_digest:
                raise ValueError("Source changed during remaining-copy verification")
            if remaining_digest != expected:
                result.update(status="bytes_differ", observed_sha256=remaining_digest)
                continue
            result["hashes_verified"] = True
        except (OSError, ValueError) as error:
            result.update(status="inaccessible_or_changed", reason=str(error))
            continue
        access_evidence = confirmations.get(candidate["copy_id"])
        if (not access_evidence or (source["owner_id"] is not None
                                  and candidate["owner_id"] == source["owner_id"])):
            result.update(status="candidate_access_unconfirmed")
            continue
        evidence = {
            "source_copy_id": source_copy_id, "remaining_copy_id": candidate["copy_id"],
            "verified_sha256": expected, "verified_at": utc_now(), "verified_by": verified_by,
            "survives_offboarding": True, "access_evidence": access_evidence,
        }
        result.update(status="verified_remaining_copy", survives_offboarding=True)
        report["evidence"].append(evidence)
    if report["evidence"]:
        report["status"] = "verified_remaining_copy"
    return _record_report(registry, report)


def _record_report(registry, report: dict) -> dict:
    with registry.connection:
        registry.connection.execute(
            "CREATE TABLE IF NOT EXISTS offboarding_reports(report_id TEXT PRIMARY KEY, report TEXT NOT NULL)"
        )
        registry.connection.execute(
            "INSERT INTO offboarding_reports VALUES (?,?)",
            (report["report_id"], json.dumps(report, sort_keys=True)),
        )
    return report
