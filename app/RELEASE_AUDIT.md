# Final release audit

Audit date: 2026-11-14  
Branch: `fix/cloud-demo-search`  
Scope: Ericsson Data Storage Optimization hackathon prototype

This audit distinguishes implemented behavior from demo evidence and production
readiness. Files outside Role C ownership (`app/*`, `src/search/*`) are reviewed
but not modified here; their fixes must be handled by the responsible role.

## Challenge requirement matrix

| # | Challenge requirement | Current implementation | Evidence in code, tests or demo | Missing evidence | Risk | Recommended fix | Responsible file | Final status |
|---:|---|---|---|---|---|---|---|---|
| 1 | Storage reduction | Exact codec selection and semantic PDF, PPTX and video packages report signed byte changes. | `app/integration.py`, semantic packagers, KP v2 packer, measured jury-video artifact locally. | No tracked, reproducible real-file benchmark is available in a clean checkout. | Hard-coded or local-only results can be mistaken for shipped evidence. | Add a tracked benchmark evidence manifest and a deterministic release benchmark; label unavailable local evidence explicitly. | `app/*`; `docs/savings.md` requires Role A/B follow-up | Partial |
| 2 | Video-to-transcript conversion | `faster-whisper` produces timestamped transcript segments when audio exists. | `src/video/package.py`; local jury-video package. | No small tracked video fixture or integration test exercises transcription in CI. | Model/runtime availability and transcript quality are unproven in a clean release. | Keep transcription opt-in in tests; add a frame-only video integration test and document transcription as an external model dependency. | `src/video/*` (other role), tests under `app/tests/*` for adapter behavior | Partial |
| 3 | Keyframes | Video frames are sampled and scene-filtered; KP stores unique frames or references. | `src/video/package.py`, `src/savings/pack.py`, compact-package tests and generated-video release test. | Transcription still depends on an external model. | Model availability can affect the audio path, while frame-only packaging is verified. | Keep generated frame-only coverage and validate Whisper in the pilot environment. | `app/tests/test_video_search_chain.py`; `src/video/*` follow-up | Complete for frame-only path; partial for transcription |
| 4 | Speaker handling | Segment schema and package encoding support speaker labels. Actual transcription writes `speaker=None`. | `src/video/package.py`, KP speaker index. | No diarization implementation. | UI or pitch could imply speaker identification that does not exist. | State “speaker labels supported; automatic diarization not implemented” everywhere. | `app/streamlit_app.py`, presentation | Partial |
| 5 | Timestamp-to-frame linking | Transcript segments receive the nearest frame ID and search returns that frame. | `_frame_for_time` in `src/video/package.py`; generated video → KP → index → query test. | Real transcription alignment quality needs representative recordings. | Algorithmic linkage is verified, but corpus quality is not yet calibrated. | Evaluate alignment on representative pilot recordings. | `app/tests/test_video_search_chain.py` | Complete for integration path |
| 6 | Slide references | Verified document-registry references are supported and resolved; unresolved matches remain images. | `src/documents/video_matching.py`, slide-matching tests. | Mock search uses self-generated `DOC-123`, not a verified registry ID. | Mock references may be presented as an Ericsson source of truth. | Mark mock references as demo-only; never call them registry-verified. | `src/search/make_mock.py`, `app/streamlit_app.py` | Partial |
| 7 | Search | SQLite FTS searches transcripts and OCR text; uploaded semantic packages receive session indexes; API searches PDF/PPTX packages. | `src/search/*`, Streamlit search, `/v1/search`. | API search does not support KP2 video packages; no committed API/search tests. | “Search API supports all packages” would be false. | Add tests and report supported package kinds explicitly; add KP2 API search in a later cross-role change. | `app/api.py`, `app/tests/*`, `src/savings/*` follow-up | Partial |
| 8 | AI-ready output | UTF-8 transcript/semantic graphs, hashes and a versioned REST contract are available. | `app/integration.py`, `app/api.py`, PDF/PPTX graph readers. | No production AI/RAG connector or evaluation. Video KP is not searched by `/v1/search`. | “AI integrated” would be unsupported. | Use “AI-ready”; expose explicit searchable/AI-ready metadata and supported kinds. | `app/api.py`, `app/integration.py` | Partial |
| 9 | Exact file deduplication | SHA-256 groups byte-identical files. | `src/documents/file_hash.py`, duplicate-savings and registry tests. | No remote-provider adapter. | Cross-system duplicate claims exceed local evidence. | State local/adapter-ready scope; add SharePoint/OneDrive providers in a pilot. | `src/documents/*` (other role) | Complete for local files |
| 10 | Slide-level deduplication | Exact semantic slide hashes, embedded-media hashes and calibrated visual comparison exist. | `app/pptx_semantic.py`, `src/documents/revisions.py`, slide tests. | Cross-system calibration requires representative documents. | False positives/negatives if thresholds are generalized. | Keep exact hashes authoritative; calibrate perceptual matching per corpus. | `src/documents/*` (other role) | Complete for exact matches; partial for perceptual matches |
| 11 | Revision comparison | PDF/PPTX revisions are compared with text and calibrated visual evidence. | `src/documents/revisions.py`, revision and slide tests. | No production UI/API workflow. | Capability may be invisible in the demo. | Present as implemented library evidence, not a finished end-user workflow. | `src/documents/*`; future `app/*` adapter | Partial |
| 12 | Offboarding evidence | Source and candidate copies are re-read, hashed and checked for continued-access evidence. | `src/documents/offboarding.py`, offboarding tests. | Remote access confirmation is manual/provider-dependent. | Current accessibility can be confused with post-offboarding survival. | Preserve explicit attestation and recheck immediately before external action. | `src/documents/*` (other role) | Complete for local evidence workflow |
| 13 | Safe deletion policy | Reports never authorize or perform deletion; explicit verification and access evidence are required. | Offboarding limitations and tests prove files remain unchanged. | No external approval/retention integration. | Automatic deletion would be unsafe. | Keep deletion outside the prototype; require policy, authorization and final recheck. | `src/documents/*`, production connector | Complete as a safety boundary |
| 14 | REST/API integration | Versioned FastAPI endpoints cover health, capabilities, exact, PDF, PPTX, video ingest and PDF/PPTX search. | API contract tests cover health, limits, invalid input, exact restore, semantic package search, hashes and signed headers. | Direct search inside a KP2 video package is not implemented; KP2 must be indexed first. | A consumer could assume all package kinds work with one endpoint. | Capabilities now state supported direct-search kinds; add KP2 direct search in a cross-role follow-up. | `app/api.py`, `app/tests/test_api.py` | Complete for documented contract; partial for direct KP2 search |
| 15 | Scenario-based savings | Streamlit separates uploaded measurements, validated local benchmark evidence and planning assumptions. | Storage calculator, tracked evidence manifest, clean-checkout AppTest and agent-API run. | The real video source is intentionally not distributed. | A reviewer cannot independently rerun that video benchmark from a clean clone. | Keep the evidence label and SHA-256; rerun on representative Ericsson data during the pilot. | `app/streamlit_app.py`, `app/assets/benchmark_evidence.json` | Complete for evidence separation |
| 16 | Future Ericsson deployment path | Python core and REST adapter are independent of Streamlit; architecture names Play, SharePoint, OneDrive, object storage, search and AI. | `app/integration.py`, `app/api.py`, presentation. | Authentication, provider adapters, governance and production operations are not implemented. | “Ready to deploy at Ericsson” would be unsupported. | Present a read-only pilot path with named owners, gates and no deletion. | `app/*`, future provider modules | Partial |
| 17 | Limitations and unresolved problems | UI and presentation state semantic fidelity boundaries, missing connectors, diarization and deletion limits. | Challenge coverage and pitch sections. | Tracked benchmark documentation still contains misleading mock totals. | Contradictory repository evidence weakens trust. | Remove mock metadata from real totals or label it explicitly; add release claims list. | `docs/savings.md` (other role), `app/RELEASE_AUDIT.md` | Partial |

## Critical correctness audit

- **Misleading tracked benchmark:** `docs/savings.md` currently reports the mock
  metadata value `1,000,000,000` bytes against a tiny generated package and rounds
  the result to `100.00%`. This is not a real-file benchmark. Role C cannot edit
  that file; the responsible role must remove it from real totals or label it
  “metadata-only mock, not measured source bytes.”
- **Ignored demo data:** `data/sample/jury_prizes/*` is ignored. The app currently
  hides the prepared-video card when those files are absent, which is safe, but
  the presentation's video result is local benchmark evidence rather than a
  clean-checkout artifact.
- **Ignored presentation binaries:** `.pptx` and `.pdf` are ignored. The tracked
  deck builder and speaker script are reproducible, but the generated files are
  not part of a clean checkout.
- **Signed savings:** application-level calculations preserve negative savings.
  UI labels show “size increase” instead of clamping to zero.
- **Exact restoration:** exact packages restore bytes and verify the original
  SHA-256 before being returned.
- **Semantic fidelity:** PDF omits original rendering and image pixels; video
  omits discarded motion/audio; PPTX distinguishes semantic structure, optional
  pixel-identical embedded media and exact-file mode.
- **ASCII/Base85:** offered only as a larger export and never entered in codec
  selection.
- **Speaker diarization:** not implemented. Real video segments have no automatic
  speaker identity.
- **Slide references:** only `sha256:<64 hex>` registry IDs are verified. Mock
  `DOC-123` references are illustrative only.
- **Automatic deletion:** not implemented by design.

## Release-gate result

Completed in Role C scope:

1. `62 passed` in the complete test suite, including native LibreOffice tests outside the macOS sandbox.
2. API tests prove exact restoration, semantic PDF/PPTX search, hashes, invalid-input handling, limits and signed metrics.
3. Streamlit AppTest proves clean start, mock search with images, exact upload, session clearing and uploaded-PDF search.
4. A generated video proves video → keyframes/package → KP → index → query with visual context.
5. A clean-checkout copy starts without ignored data; its agent-API status is `ready`, `winner` returns two images, and the console is clean.
6. Presentation metrics are derived from a validated evidence manifest; fixed test-count claims were removed.
7. The reusable release benchmark measures semantic and exact document modes without writing artifacts.

Remaining blockers outside Role C ownership:

1. `docs/savings.md` still mixes a metadata-only 1 GB mock with real-file totals and rounds it to `100.00%`. It must be corrected by its owning role before external submission.
2. Automatic speaker diarization is not implemented.
3. Direct KP2 video search through `POST /v1/search` is not implemented; the existing index path works.
4. Ericsson authentication, provider connectors, retention integration and governed external deletion remain pilot work.
5. The local jury-video source and package are ignored, so the tracked hash evidence is recorded but not independently verifiable or reproducible from a clean clone.

## Safe claim registry

Safe to claim:

- Exact mode restores byte-for-byte and verifies SHA-256.
- Semantic PDF/PPTX/video modes can produce much smaller searchable knowledge packages, with explicit fidelity loss.
- The local jury-video benchmark measured 88,654,139 → 1,202,334 bytes (98.64% reduction); the source is not distributed.
- Search, duplicate evidence, revision comparison and safe offboarding evidence work in the demonstrated local scope.
- Streamlit is a demo client; Python and REST adapters provide the deployment boundary.

Do not claim:

- Lossless or visually identical reconstruction from semantic mode.
- 100% savings, or that 1 GB can generally become 50–100 KB.
- Automatic speaker identification.
- A production Ericsson deployment, completed product connectors or production AI integration.
- Automatic deletion, or that local copy verification alone makes offboarding deletion safe.
- That direct `/v1/search` currently accepts KP2 video packages.

## Jury score estimate

| Criterion | Weight | Estimated score | Weighted points | Reason the score is not higher |
|---|---:|---:|---:|---|
| Problem understanding | 15% | 4/5 | 12 | Scope follows the brief, but Ericsson-wide prevalence and user evidence are not measured. |
| Feasibility | 15% | 4/5 | 12 | Read-only pilot and API boundary are credible; authentication and provider dependencies remain. |
| Technical quality | 5% | 4/5 | 4 | Core paths and 62 tests pass; transcription quality and direct KP2 API search remain. |
| User value | 20% | 4/5 | 16 | Storage and retrieval improvements are demonstrated; workflow/time value needs user validation. |
| Innovation | 10% | 4/5 | 8 | The adapted combination is distinctive; individual codecs and extractors are established tools. |
| Presentation and demo | 25% | 4/5 | 20 | The three-minute story and backup are clear; live local video evidence is optional rather than bundled. |
| Partner relevance | 10% | 5/5 | 10 | Storage, search/AI activation, duplicates and safe offboarding map directly to the brief. |
| **Estimated total** | **100%** |  | **82/100** | A strong weekend prototype with clearly stated production gaps. |

