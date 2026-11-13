"""Content-based slide comparisons that do not assume matching positions."""

from difflib import SequenceMatcher

from .visuals import calibration, hamming


def rendered_slides(registry, doc_id: str) -> list[dict]:
    result = registry.slides(doc_id)
    rendered = {row["slide_no"]: dict(row) for row in registry.connection.execute(
        "SELECT * FROM rendered_slides WHERE doc_id=?", (doc_id,)
    )}
    for slide in result:
        image = rendered.get(slide["slide_no"], {})
        slide["image_sha256"] = image.get("image_sha256")
        slide["render_profile"] = image.get("profile_id")
    return result


def compare_versions(registry, left_doc_id: str, right_doc_id: str, *,
                     calibration_id: str | None = None, text_similarity: float = 0.85) -> dict:
    """Return mutually unique content matches, ambiguous candidates, and unmatched slides.

    Text similarity is candidate evidence, never a family-link or deletion decision.
    Only compatible, calibrated image hashes can contribute visual candidates.
    """
    if not 0 < text_similarity <= 1:
        raise ValueError("Text similarity must be greater than zero and at most one")
    policy = calibration(registry, calibration_id)
    left, right = rendered_slides(registry, left_doc_id), rendered_slides(registry, right_doc_id)
    candidates = []
    for first in left:
        for second in right:
            nonempty = bool(first["text"] and first["text"].strip()
                            and second["text"] and second["text"].strip())
            same_text = nonempty and first["text_hash"] == second["text_hash"]
            ratio = SequenceMatcher(None, first["text"], second["text"], autojunk=False).ratio() if nonempty else 0
            compatible = bool(first["render_profile"] and
                              first["render_profile"] == second["render_profile"])
            same_image = bool(compatible and first["phash"] and second["phash"]
                              and first["image_sha256"] == second["image_sha256"])
            distance = None
            if (policy and first["phash"] and second["phash"]
                    and first["phash_profile"] == second["phash_profile"] == policy["profile_id"]):
                distance = hamming(first["phash"], second["phash"])
            near_image = distance is not None and distance <= policy["max_distance"]
            if not (same_text or same_image or near_image or ratio >= text_similarity):
                continue
            rank = 4 if same_image else 3 if same_text else 2 if ratio >= text_similarity else 1
            visual_changed = compatible and first["image_sha256"] != second["image_sha256"]
            status = "changed" if (not same_text and not same_image) or visual_changed else (
                "unchanged" if same_image else "text_match"
            )
            candidates.append({
                "left_slide_no": first["slide_no"], "right_slide_no": second["slide_no"],
                "status": status, "moved": first["slide_no"] != second["slide_no"],
                "same_nonempty_text": bool(same_text), "same_rendered_image": same_image,
                "visual_change": bool(visual_changed), "visual_comparable": compatible,
                "text_similarity": ratio, "phash_distance": distance, "rank": rank,
                "evidence": "rendered_image" if same_image else "exact_text" if same_text else
                            "similar_text" if ratio >= text_similarity else "similar_image",
            })
    # Retain ties rather than assigning repeated content to arbitrary positions.
    best_left, best_right = {}, {}
    for candidate in candidates:
        l, r, rank = candidate["left_slide_no"], candidate["right_slide_no"], candidate["rank"]
        best_left[l] = max(best_left.get(l, 0), rank)
        best_right[r] = max(best_right.get(r, 0), rank)
    top = [c for c in candidates if c["rank"] == best_left[c["left_slide_no"]]
           and c["rank"] == best_right[c["right_slide_no"]]]
    counts_left = {s["slide_no"]: sum(c["left_slide_no"] == s["slide_no"] for c in top) for s in left}
    counts_right = {s["slide_no"]: sum(c["right_slide_no"] == s["slide_no"] for c in top) for s in right}
    matches, ambiguous = [], []
    for candidate in top:
        entry = dict(candidate)
        entry.pop("rank")
        if counts_left[entry["left_slide_no"]] == counts_right[entry["right_slide_no"]] == 1:
            matches.append(entry)
        else:
            ambiguous.append(entry)
    return {
        "left_doc_id": left_doc_id, "right_doc_id": right_doc_id,
        "matches": matches, "ambiguous": ambiguous,
        "removed": [s["slide_no"] for s in left if not any(c["left_slide_no"] == s["slide_no"] for c in top)],
        "inserted": [s["slide_no"] for s in right if not any(c["right_slide_no"] == s["slide_no"] for c in top)],
        "calibration_id": calibration_id, "text_similarity_threshold": text_similarity,
        "limitations": ["Similarity is candidate evidence, not proof of a revision relationship.",
                        "Text-only matches do not establish visual equality.",
                        "Low-information slides are not matched by empty text or a uniform image.",
                        "Slides without sufficient similarity appear as removed/inserted."],
    }


def shared_slides(registry) -> list[dict]:
    """Group exact nonempty text shared by different file versions, in any position."""
    groups = {}
    for row in registry.connection.execute(
        "SELECT doc_id,slide_no,text,text_hash FROM slides WHERE text IS NOT NULL AND text!='' "
        "ORDER BY text_hash,doc_id,slide_no"
    ):
        if row["text"].strip():
            groups.setdefault(row["text_hash"], []).append(
                {"doc_id": row["doc_id"], "slide_no": row["slide_no"]}
            )
    return [{"text_hash": digest, "slides": slides, "visual_equality": "not_established"}
            for digest, slides in groups.items() if len({s["doc_id"] for s in slides}) > 1]
