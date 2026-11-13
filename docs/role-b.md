# Role B: local document pipeline

The approved contract is in PR #6 (`docs/schema.md`). This implementation builds
on the PPTX extractor in PR #5. Merge those reviews before the implementation PRs.
The document database is separate from Role C's recording search index.

## Setup and ingestion

Use Python 3.11 or newer and an isolated environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: pymupdf python-pptx imagehash Pillow pytest
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
compatible. Uniform images (unpadded source grayscale standard deviation below 1.0) have null
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

## Offboarding evidence

```bash
.venv/bin/python -m src.documents --db data/documents.db offboarding SOURCE_COPY_ID --verified-by reviewer
.venv/bin/python -m src.documents --db data/documents.db offboarding SOURCE_COPY_ID \
  --verified-by reviewer --access-confirmations /path/to/continued-access.json
```

The optional confirmations file maps a remaining `copy_id` to a nonempty evidence
string, for example `{"copy-123": "Team folder and permissions confirmed after account removal"}`.
This is an explicit attestation of continued access, not an automatic ACL check.
Without it a byte-identical readable file is only an unconfirmed candidate. A copy
still owned by the departing owner cannot qualify. `--remaining-copy COPY_ID`
restricts verification to one candidate; otherwise all registered copies of the
exact version are considered.

Both whole files are re-read, with modification checks; a source changed since
import, inaccessible remaining copy, revised version, or same-inode alias cannot
produce successful evidence. A source changed during candidate verification is
reported as unverified. No files are deleted, moved, or rewritten. Reports include
UTC times, verifier, observed status, confirmed evidence, and limitations, and are
persisted as JSON in the local registry's `offboarding_reports` table. Re-run to
get fresh evidence before any separately authorized storage action.

## Video adapter and Role C handoff

```bash
.venv/bin/python -m src.documents --db data/documents.db match-recording /path/to/package.json \
  --calibration CALIBRATION_ID \
  --capture-evidence 'Full uncropped slide captures compatible with these calibration images' \
  --output data/linked/package.json
```

The adapter recomputes image hashes from keyframe files using the current calibrated
profile; existing package `phash` strings are not treated as provenance. It first
prefers exact canonical pixels, then calibrated perceptual candidates. It assigns
a reference only for a single candidate. Shared content across revisions, repeated
slides, incompatible profiles, missing images, low-information frames, and uncertain
matches remain unresolved. The optional `--doc-id` restricts candidates to an exact
version only when the caller already has reliable version context.

References use only `doc_id`, `slide_no`, and `slide_hash` (the registered exact
text hash, or null when text is unavailable). Existing references are checked by
`resolve_slide_ref` against the exact composite key; stale/inconsistent references
are cleared in the new output and reported for review, never silently redirected.
Valid prior references are retained. Matching evidence and ambiguity are returned
outside the recording envelope; field names and the recording contract are unchanged.

`--output` exclusively creates a NEW package and rebases frame asset paths relative
to its new location. It never overwrites the input or any existing output. Original
source metadata, segments, frame timestamps, and other package fields are preserved.
The report remains on stdout and can be retained separately.

Role C owns the caller. No `src/search` or `app` files change: hand off the new
package to the existing `src.search.index.index_package(Path(...))` interface.
Its returned frame columns contain the exact version/slide/hash. The integration
test invokes that unmodified reader and query function in a separate process,
indexes twice, checks the returned revision reference, and verifies asset paths.
Do not index the adapter's outer report envelope as a recording package.

## Reproducible end-to-end demo

On macOS, install LibreOffice if needed (`brew install --cask libreoffice`), or
set `ROLE_B_SOFFICE=/absolute/path/to/LibreOffice.app/Contents/MacOS/soffice` for an
isolated portable installation. On Linux, use a headless LibreOffice installation
on PATH. Run from the repository root after Python setup above:

```bash
.venv/bin/python -m src.documents.demo --native-pptx
.venv/bin/python -m pytest -q
```

The native demo generates PDF revisions and two real PPTX decks, renders the PPTX
decks through LibreOffice, and exercises duplicate copies, idempotent reimports,
explicit family links, text hashes, measured image calibration, moved/inserted/
removed slides, text and visual-only edits, repeated-content ambiguity, offboarding
with/without continued-access evidence, a temporarily inaccessible synthetic copy,
and frames resolving to the correct revision or remaining ambiguous. It feeds the
result into Role C's actual index/re-index/search caller and checks its references.
No source video or Ericsson data is needed. The demo's synthetic video metadata is
illustrative; it does not claim to transcode a video.

All artifacts and both SQLite databases are temporary by default and removed after
the assertions. To inspect them, supply `--directory data/role-b-demo-NEW` (must not
exist); `summary.json` contains results, IDs, and the actual calibration distances.
Without `--native-pptx`, the same demo uses explicit, paired synthetic PDF sidecar
attestations rather than claiming native PPTX rendering. The native integration
tests run only when LibreOffice is available, and otherwise report skips.

## Review dependencies

Keep #5 (PPTX) and #6 (contract) open for independent review. Merge both before
the registry implementation. Implementation PRs are stacked in order: registry
(`docs/document-registry`, based on #5), slide comparison (`docs/slide-matching`),
offboarding (`docs/offboarding-evidence`), then video/demo
(`docs/frame-slide-integration`). Retarget each dependent PR to main after its
base is merged, and do not merge a dependent implementation before the contract.
No shared-contract or Role C caller edits are needed for these implementations.

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
Offboarding tests cover verified/unconfirmed access, unreadable/missing copies,
stale or concurrently changing bytes, hard links, and persistence of evidence.
Video tests cover exact revision resolution, ambiguity, invalid prior references,
missing frames, incompatible runtimes, uniform widescreen images, nullable hashes,
non-overwriting output, and rebased paths. Two full demo tests exercise Role C's
actual reader: one with paired synthetic sidecars, one with native LibreOffice.

Verified implementation run: Python 3.14, PyMuPDF 1.28.2, python-pptx 1.0.2,
ImageHash 4.3.2, Pillow 13.0.0, and native LibreOffice 26.8.3 on macOS. All 38 tests
passed with no skips and five upstream PyMuPDF/SWIG deprecation warnings. The native
demo CLI also passed separately. Its measured positive distance was 0 bits and
negative distance 34 bits; that conservative threshold applies to the synthetic
captures only. The CLI workflow test exercises import, inspection, shared text,
calibration, revision comparison/linking, offboarding, and recording output.
