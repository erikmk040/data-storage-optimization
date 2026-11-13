# Role B: local document pipeline

The approved contract is in PR #6 (`docs/schema.md`). This implementation builds
on the PPTX extractor in PR #5. Merge those reviews before the implementation PRs.
The document database is separate from Role C's recording search index.

## Setup and ingestion

Use Python 3.11 or newer and an isolated environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pymupdf python-pptx imagehash Pillow pytest
```

These are existing project dependencies. The full application dependency list
remains in `requirements.txt`; the command above installs just the document/test
subset. Generated data belongs under ignored `data/` or a temporary directory.

One command imports either format, preserving source order and empty slides:

```bash
.venv/bin/python -m src.documents --db data/documents.db ingest /path/to/file.pdf --owner alex
.venv/bin/python -m src.documents --db data/documents.db ingest /path/to/file.pptx --owner team
```

The JSON result returns `doc_id`, `document_id`, `copy_id`, and slide count.
Optional flags: `--revision`, `--document-number`, `--author`, `--document-date`.
Dates use `YYYY-MM-DD`. Inspect a version with `show DOC_ID`.

Each import snapshots the source and verifies its whole-file hash again before
committing. Failure rolls back that import's records. Each canonical local file
URI has one copy ID; reimports update the observation rather than duplicate it.
Identical bytes at distinct paths share one version and retain separate copy IDs.
Symlink aliases resolve to the same location. Historical versions remain when
the bytes at a location change. The registry verifies local file URIs only;
remote-storage verification requires a future provider adapter, not a local cache.

New unique versions start in their own family. To explicitly confirm revisions:

```bash
.venv/bin/python -m src.documents --db data/documents.db link-revisions NEW_DOC_ID ORIGINAL_DOC_ID \
  --confirmed-by team --reason 'Source owner confirmed revisions A and B'
```

The actor, evidence, time, and original/target families are recorded. Similar
filenames or slides never automatically link families. Extraction provenance is
stored; a changed extractor/profile cannot silently overwrite existing text.
Slide text hashes are SHA-256 of exact extracted UTF-8 text, including whitespace.
Empty text has a hash; missing text is null. Empty text alone is not match evidence.

## Rendering, hashes, calibration, and slide comparison

PDF rendering uses PyMuPDF directly. PPTX rendering uses headless LibreOffice
(`libreoffice`/`soffice` on PATH, or the standard macOS application path), in a
temporary directory with an isolated LibreOffice user profile. Install LibreOffice
separately to render PPTX slides. Hidden slides are included; a rendered page-count
mismatch aborts the import. The default `--render auto` permits text-only PPTX
imports with an explicit warning when LibreOffice is absent. Use `--render required`
to require image hashes, or `--render none` for text only.
For an isolated portable installation set `ROLE_B_SOFFICE` to the absolute path of
its `soffice` executable. No system installation is required. On macOS, even
headless LibreOffice needs permission to register with the operating system;
restricted sandboxes can block it. A failed renderer never creates partial imports.

An alternative is `ingest deck.pptx --rendered-pdf /path/to/export.pdf
--render-evidence 'Exported from this exact deck, including hidden slides, in source order'`.
This is an explicit caller attestation; a matching page count cannot prove that an
arbitrary PDF belongs to a PPTX. The PDF hash, source hash, converter or attestation,
and rendering profile are recorded. No approximate text-only slide rendering is used.

Profile definitions and their SHA-256 IDs are stored in `phash_profiles`; list them
with `profiles`. Rendering scales the longest page dimension to 1280 pixels, uses
RGB on white, and normalizes the full uncropped image onto a 1280x960 white canvas
with preserved aspect ratio. EXIF orientation and transparency are handled.
ImageHash pHash uses 8x8 bits and high-frequency factor 4. Renderer, Pillow,
ImageHash, NumPy, and SciPy versions are recorded. Only identical profile IDs are
compatible. Uniform images (grayscale standard deviation below 1.0) have null
pHash and cannot independently establish a match. A separate SHA-256 of canonical
RGB pixels detects visual-only changes, including color edits invisible to pHash.
This is rendering evidence, not source-file identity.

Visual similarity has **no default unmeasured threshold**. Calibrate on labeled
positive and negative demo captures first. A pairs JSON file is an array such as:

```json
[
  {"left": "slide.png", "right": "compressed.jpg", "same_slide": true},
  {"left": "slide.png", "right": "other.png", "same_slide": false}
]
```

Paths are relative to that JSON file. Run:

```bash
.venv/bin/python -m src.documents --db data/documents.db calibrate PROFILE_ID /path/to/pairs.json
.venv/bin/python -m src.documents --db data/documents.db compare ORIGINAL_DOC_ID REVISED_DOC_ID --calibration CALIBRATION_ID
.venv/bin/python -m src.documents --db data/documents.db shared
```

The threshold is the largest positive Hamming distance, accepted only when strictly
below every negative distance. Calibration stores image byte hashes, labels,
distances, time, and profile. Overlapping labels fail without saving a threshold.
Demo calibration is evidence for those captures only; recalibrate for real capture
conditions, compression, and layouts. Cropped or perspective-distorted frames are
not supported by the full-slide profile.

Comparison considers all slide positions, ranks exact rendered images, exact
nonempty text, similar text, and calibrated similar images, and accepts only
mutually unique best candidates. Ties are reported under `ambiguous`. Reordered
slides retain their original positions in the report. Matched changed slides,
inserted/removed positions, visual-only changes, and uncertainty are explicit.
Text similarity defaults to 0.85 (`--text-similarity` can change it); it is candidate
evidence, never automatic family linking. Changes with insufficient evidence are
reported as inserted/removed. Empty text alone never matches. Without calibration,
only exact rendered images and text evidence can match; visual similarity is off.

## Tests

```bash
.venv/bin/python -m pytest -q
```

The registry tests cover both formats, duplicate copies, persistence, reimports,
revision confirmation, changed source locations, metadata, exact text hashes,
and rollback after invalid input, concurrent source changes, and SQL failures.
Visual tests cover calibration, reordered slides, ambiguous repeated content,
insertions/removals, text and visual-only edits, incompatible profiles, uniform
images, attested PPTX rendering, and conversion failure. The LibreOffice adapter
unit test uses a controlled converter; it does not assert native LibreOffice runs.
The separate native test runs when LibreOffice is available and covers PPTX
rendering and retention of a hidden empty slide; otherwise that test is skipped.
