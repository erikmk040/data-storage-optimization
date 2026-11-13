# Document and slide data contract

Approved Role B contract. This specifies data semantics; the document/slide
registry and its integration are not implemented by this documentation change.
The existing recording package fields remain unchanged.

## Document versions and families

| Field | JSON type | Required | Meaning |
| --- | --- | --- | --- |
| `document_id` | string | Yes | Stable, opaque ID for a document family across revisions. |
| `doc_id` | string | Yes | `sha256:<lowercase file SHA-256>`; identifies an exact file version. |
| `sha256` | string | Yes | SHA-256 of the complete source file, as 64 lowercase hexadecimal characters. |
| `size_bytes` | integer | Yes | Source file size in bytes, at least zero. |
| `revision` | string or null | No | Source revision label; not an identity or unique key. |
| `document_number` | string or null | No | Document number supplied by the source. |
| `author` | string or null | No | Author stated in source metadata. |
| `document_date` | string or null | No | Source document date as `YYYY-MM-DD`, not ingestion time. |

Identical bytes share one `doc_id`, regardless of filename or location. Any byte
change creates a new version, including a metadata-only edit. `doc_id` must equal
`"sha256:" + sha256`.

A newly seen unique file starts in its own document family. Link versions into
one family only after explicit confirmation or reliable source metadata. Record
the supporting confirmation or metadata as implementation provenance. Similar
names, text, or images alone do not authorize a family link. Revision labels do
not imply ordering or prove that one version supersedes another.

## Stored copies

| Field | JSON type | Required | Meaning |
| --- | --- | --- | --- |
| `copy_id` | string | Yes | Opaque ID for one stored copy, distinct from other copies of identical bytes. |
| `doc_id` | string | Yes | Exact file version observed at this location. |
| `filename` | string | Yes | Filename of this copy, including extension. |
| `location_uri` | string | Yes | Storage address, such as a local file URI or stable provider URI. |
| `owner_id` | string or null | No | Responsible user or team, when known. |

Missing optional metadata may be omitted or represented as null. It must not be
invented. Copy records describe observations, not guarantees that a file still
exists. A location containing changed bytes must no longer be treated as a
verified copy of the old `doc_id`.

## Slides

The composite key `(doc_id, slide_no)` identifies one slide in one exact file
version. PDF pages map directly to `slide_no`; PPTX slides follow presentation
order. Both start at 1. Preserve empty pages/slides and never renumber after
filtering. Position alone does not identify the same slide across revisions.

| Field | JSON type | Required | Meaning |
| --- | --- | --- | --- |
| `doc_id` | string | Yes | Exact source file version. |
| `slide_no` | integer | Yes | Source position, at least 1. |
| `text` | string or null | Yes | Exact extracted text; empty string means successful extraction with no text, null means unavailable or failed. |
| `text_hash` | string or null | Yes | SHA-256 of `text.encode("utf-8")`, as 64 lowercase hex characters; null exactly when text is null. |
| `phash` | string or null | Yes | 64-bit perceptual image hash, encoded as 16 lowercase hex characters; null if unavailable. |
| `phash_profile` | string or null | Yes | Reference to the rendering/hashing profile; required when phash is present, otherwise null. |

Do not normalize case, Unicode, whitespace, or line endings before computing
`text_hash`. Empty text has the SHA-256 of the empty UTF-8 byte sequence. Equal
empty text cannot establish a slide match on its own. Equal nonempty text is
evidence of text equality, not visual equality or whole-file identity.

`phash_profile` makes the approved compatibility rule explicit. Its profile
definition must record rendering engine/version, dimensions or resolution,
background/color handling, preprocessing, and hashing algorithm/version/settings.
Compare only profiles known to be compatible. Use Hamming distance for compatible
64-bit hashes. Calibrate the similarity threshold with demo files during
implementation; this contract does not prescribe an untested threshold. A similar
image hash is candidate-match evidence, not proof of identical files.

## Recording references (existing field names preserved)

An existing frame may omit `slide_ref` or set it to null when there is no resolved
match. A populated reference uses these fields:

| Field | JSON type | Required in reference | Meaning |
| --- | --- | --- | --- |
| `doc_id` | string | Yes | Exact registered file version, not a document family ID. |
| `slide_no` | integer | Yes | Source slide number within that version. |
| `slide_hash` | string or null | Yes | Referenced slide's `text_hash` when available, otherwise null. |

Resolve by `(doc_id, slide_no)`. If a non-null `slide_hash` disagrees with the
registered text hash, report an inconsistent reference; do not silently redirect
to another version. Never resolve to the latest revision implicitly. A hash of
empty text is allowed as a consistency value, but is not sufficient match evidence.

Recording `source`, `segments`, `frames`, frame timestamps, and existing frame
`phash` fields retain their current names and meanings. A frame phash must also
have known compatible profile provenance before comparison with a slide phash;
this document adds no field to the recording package.

## Offboarding evidence only

The registry produces evidence reports, never deletion instructions or automatic
deletion. A remaining copy must be read and verified by whole-file SHA-256,
match the source copy, and remain accessible to the team after offboarding.
Ownership or a matching filename alone is insufficient.

Each successful remaining-copy evidence entry contains:

| Field | JSON type | Required | Meaning |
| --- | --- | --- | --- |
| `source_copy_id` | string | Yes | Copy being assessed. |
| `remaining_copy_id` | string | Yes | Distinct copy intended to remain. |
| `verified_sha256` | string | Yes | Whole-file SHA-256 read and verified for both copies. |
| `verified_at` | string | Yes | UTC verification time, RFC 3339 with `Z`. |
| `verified_by` | string | Yes | Person or service performing verification. |
| `survives_offboarding` | boolean | Yes | True only after verifying continued team access. |
| `access_evidence` | string | Yes | Explanation or evidence reference supporting continued team access. |

Only entries with verified byte equality and confirmed continued access establish
a verified remaining copy. If either check fails or is unknown, report that no
verified remaining copy has been established. A revised version or similar slide
does not qualify. Recheck evidence before acting: it describes the recorded time,
not permanent future availability. Retention, permissions, and deletion approval
remain separate team decisions.

## Example

The file digests below are illustrative synthetic values. Revision B is linked
to the same family only because the team explicitly confirmed the relationship.
The slide text hash is the actual SHA-256 of UTF-8 `hello`. The collection wrapper
is illustrative and does not change the recording package envelope.

```json
{
  "document_versions": [
    {
      "document_id": "family-7",
      "doc_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "size_bytes": 12000,
      "revision": "A"
    },
    {
      "document_id": "family-7",
      "doc_id": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "size_bytes": 12500,
      "revision": "B"
    }
  ],
  "copies": [
    {
      "copy_id": "copy-1",
      "doc_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "filename": "slides.pdf",
      "location_uri": "file:///users/alex/slides.pdf",
      "owner_id": "alex"
    },
    {
      "copy_id": "copy-2",
      "doc_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "filename": "slides.pdf",
      "location_uri": "sharepoint://team/slides.pdf",
      "owner_id": "team"
    },
    {
      "copy_id": "copy-3",
      "doc_id": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "filename": "slides-revB.pdf",
      "location_uri": "sharepoint://team/slides-revB.pdf",
      "owner_id": "team"
    }
  ],
  "slides": [
    {
      "doc_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "slide_no": 1,
      "text": "hello",
      "text_hash": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
      "phash": null,
      "phash_profile": null
    }
  ],
  "recording": {
    "id": "rec-1",
    "source": {
      "file": "meeting.mp4",
      "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "duration_s": 30,
      "size_bytes": 1000000
    },
    "segments": [],
    "frames": [
      {
        "id": "f-1",
        "t": 5,
        "file": "frames/f-1.webp",
        "phash": null,
        "ocr_text": "hello",
        "slide_ref": {
          "doc_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "slide_no": 1,
          "slide_hash": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        }
      }
    ]
  },
  "offboarding_evidence": [
    {
      "source_copy_id": "copy-1",
      "remaining_copy_id": "copy-2",
      "verified_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "verified_at": "2026-11-13T16:00:00Z",
      "verified_by": "registry-service",
      "survives_offboarding": true,
      "access_evidence": "Team-controlled location and continued team access confirmed."
    }
  ]
}
```

## Compatibility and integration work

Checked against `src/search/index.py`, `src/search/db.py`, and
`src/search/make_mock.py` on origin/main at `c36cd7f`:

- The reader already accepts absent/null `slide_ref`, reads its existing three
  field names, and stores null `slide_hash` in nullable columns. No recording
  field rename is needed.
- It currently stores references without validating them. Integration must add
  document/slide lookup, validation of version IDs and slide numbers, and hash
  consistency checks. Unknown references must be reported as unresolved rather
  than accepted as verified matches.
- The recording SQLite index has no document, copy, family, or slide tables.
  The registry and its integration remain implementation work.
- Mock values such as `DOC-123`, `h1`, and `mock1` are placeholders, not valid
  contract IDs/hashes. Integration fixtures must register real target slides and
  compute hashes, or omit unresolved references. Existing code is unchanged here.
- Frame hashes have no profile provenance today. Establish compatible rendering
  and hashing provenance before implementing frame-to-slide matching; do not
  infer compatibility from a 16-character hash alone.
- The PDF extractor returns `page_number` and `text`. A registry adapter maps
  `page_number` directly to `slide_no` and computes `text_hash`; its standalone
  CLI does not need a breaking output change. PPTX adapters must retain source
  slide order and empty slides in the same way.
- Extraction provenance should identify extractor/version/settings so changes in
  extraction can be diagnosed. Do not silently treat results produced under
  different extraction rules as a changed source file.

Rendering/hash profile values, similarity thresholds, storage layout, and
verification freshness policy remain implementation/integration choices; they
do not change the approved identity and evidence rules above.
