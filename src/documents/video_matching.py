"""Role B adapter for existing recording packages; Role C's caller stays unchanged."""

import copy
import json
import os
import re
from pathlib import Path

from .visuals import (
    calibration, hamming, image_file_fingerprint, profile_definition, profile_identity,
)


def resolve_slide_ref(registry, reference: dict | None) -> dict:
    """Resolve the exact version/position and check the existing slide_hash field."""
    if reference is None:
        return {"status": "unresolved", "reason": "No slide reference"}
    if not isinstance(reference, dict) or set(reference) != {"doc_id", "slide_no", "slide_hash"}:
        return {"status": "invalid", "reason": "Expected doc_id, slide_no, and slide_hash"}
    if (not isinstance(reference["doc_id"], str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", reference["doc_id"]) is None
            or type(reference["slide_no"]) is not int or reference["slide_no"] < 1):
        return {"status": "invalid", "reason": "Invalid exact version ID or source slide number"}
    row = registry.connection.execute(
        "SELECT * FROM slides WHERE doc_id=? AND slide_no=?",
        (reference["doc_id"], reference["slide_no"]),
    ).fetchone()
    if row is None:
        return {"status": "unresolved", "reason": "Unknown version/slide; no latest-revision fallback"}
    if reference["slide_hash"] != row["text_hash"]:
        return {"status": "inconsistent", "reason": "slide_hash must carry registered text_hash or null when unavailable"}
    return {"status": "resolved", "slide": dict(row)}


def match_recording(registry, package_path: str | Path, *, calibration_id: str,
                    capture_evidence: str, doc_id: str | None = None) -> dict:
    """Bind only uniquely supported frames; return a copy of the original package.

    Capture evidence attests full, uncropped slides compatible with the calibration
    images. Stored frame phash strings have unknown provenance and are not trusted;
    hashes are recomputed from image files using the calibrated profile.
    """
    if not isinstance(capture_evidence, str) or not capture_evidence.strip():
        raise ValueError("Matching requires full-slide capture/profile compatibility evidence")
    policy = calibration(registry, calibration_id)
    if policy is None or policy["profile_id"] != profile_identity(profile_definition()):
        raise ValueError("Visual calibration is incompatible with the current image pipeline")
    if doc_id is not None:
        registry.document(doc_id)
    path = Path(package_path).resolve(strict=True)
    package = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(package, dict) or not isinstance(package.get("frames"), list):
        raise ValueError("Recording package must contain a frames array")
    output = copy.deepcopy(package)
    query = """SELECT s.*,r.image_sha256 FROM slides s JOIN rendered_slides r
               USING(doc_id,slide_no) WHERE s.phash_profile=? AND r.profile_id=?"""
    parameters = [policy["profile_id"], policy["profile_id"]]
    if doc_id is not None:
        query += " AND s.doc_id=?"
        parameters.append(doc_id)
    slides = [dict(row) for row in registry.connection.execute(query + " ORDER BY s.doc_id,s.slide_no", parameters)]
    reports = []
    frame_ids = set()
    for frame in output["frames"]:
        if not isinstance(frame, dict) or not isinstance(frame.get("id"), str):
            raise ValueError("Every frame must be an object with a string id")
        if frame["id"] in frame_ids:
            raise ValueError("Frame IDs must be unique within a recording")
        frame_ids.add(frame["id"])
        report = {"frame_id": frame["id"], "status": "unresolved", "candidates": []}
        reports.append(report)
        if frame.get("slide_ref") is not None:
            resolution = resolve_slide_ref(registry, frame["slide_ref"])
            report["reference_check"] = resolution
            if resolution["status"] == "resolved":
                report["status"] = "resolved_existing"
            else:
                frame["slide_ref"] = None
            # Invalid prior references require caller review, not silent remapping.
            continue
        frame["slide_ref"] = None
        try:
            if not isinstance(frame.get("file"), str):
                raise ValueError("Frame file must be a local image path")
            fingerprint = image_file_fingerprint(path.parent / frame["file"])
        except (OSError, ValueError) as error:
            report["reason"] = str(error)
            continue
        if fingerprint["phash"] is None:
            report["reason"] = "Low-information frame cannot establish a slide match"
            continue
        exact, nearby = [], []
        for slide in slides:
            distance = hamming(fingerprint["phash"], slide["phash"])
            candidate = {
                "doc_id": slide["doc_id"], "slide_no": slide["slide_no"],
                "slide_hash": slide["text_hash"], "phash_distance": distance,
                "same_rendered_pixels": fingerprint["image_sha256"] == slide["image_sha256"],
            }
            if candidate["same_rendered_pixels"]:
                exact.append(candidate)
            elif distance <= policy["max_distance"]:
                nearby.append(candidate)
        candidates = exact if exact else nearby
        report["candidates"] = candidates
        if len(candidates) == 1:
            selected = candidates[0]
            frame["slide_ref"] = {key: selected[key] for key in ("doc_id", "slide_no", "slide_hash")}
            report["status"] = "resolved_exact_pixels" if exact else "resolved_calibrated_visual"
            if resolve_slide_ref(registry, frame["slide_ref"])["status"] != "resolved":
                frame["slide_ref"] = None
                report.update(status="unresolved", reason="Registry changed during matching; re-run verification")
        elif candidates:
            report.update(status="ambiguous", reason="Multiple registered slides support this frame")
        else:
            report["reason"] = "No compatible registered slide meets the calibrated threshold"
    return {
        "package": output,
        "report": {"profile_id": policy["profile_id"], "calibration_id": calibration_id,
                   "capture_evidence": capture_evidence, "restricted_doc_id": doc_id, "frames": reports,
                   "limitations": ["Visual matching is calibrated candidate evidence, not whole-file equality.",
                                   "Cropped, overlaid, or perspective-distorted frames need another profile.",
                                   "Ambiguous and invalid prior references remain unresolved."]},
    }


def write_matched_package(result: dict, source: Path, destination: Path) -> None:
    """Write a new package, rebasing frame paths for Role C's package-relative reader."""
    package = copy.deepcopy(result["package"])
    source, destination = source.resolve(), destination.resolve()
    for frame in package["frames"]:
        if isinstance(frame.get("file"), str):
            frame["file"] = os.path.relpath(source.parent / frame["file"], destination.parent)
    payload = json.dumps(package, ensure_ascii=False, indent=2)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects the input and all existing local files.
    with destination.open("x", encoding="utf-8") as output:
        output.write(payload + "\n")
