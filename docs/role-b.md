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

## Tests

```bash
.venv/bin/python -m pytest -q
```

The registry tests cover both formats, duplicate copies, persistence, reimports,
revision confirmation, changed source locations, metadata, exact text hashes,
and rollback after invalid input, concurrent source changes, and SQL failures.
