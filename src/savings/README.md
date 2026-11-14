# KP v2 compact recording packages

`python -m src.savings.pack <package.json> <out.kp>` creates one deterministic
KP v2 archive. The packer preserves transcript text as UTF-8, rounds only
timestamps, stores slide-registry matches as references, and verifies encoded
images before accepting them. A lossy image is accepted only after OCR and SSIM
checks; otherwise lossless WebP is used.

## What is not preserved

- The original video container, motion between key frames, and its audio waveform
  are not part of a recording package.
- Speaker diarization is not invented when the input speaker is null.
- A slide reference does not contain a local slide image; the referenced registry
  document is required to render it.
- The optional `--voice` flag records the intent in the manifest, but cannot
  create voice samples unless voice data is present in the input package.

The 100 KB target is measurable for mock/reference-heavy packages, not a
mathematical guarantee for arbitrary recordings. Lossless preservation can
require more space when unique frames contain high-entropy visual data.
