# Compact package benchmark

The benchmark measures the deterministic KP v2 archive. Generated `.kp` files remain under `data/` and are ignored by Git.

| Package | Original video bytes | Packed bytes | Savings | Codec | Largest component |
|---|---:|---:|---:|---|---|
| `data/sample/jury_prizes/package.json` | 88 654 139 | 1 202 334 | 98.64% | brotli | frames |

| Step | Bytes |
|---|---:|
| text | 3652 |
| frames | 1219918 |
| references | 0 |
| dedup_removed | 0 |

| `data/sample/rec_mock/package.json` | 1 000 000 000 | 331 | 100.00% | brotli | text |

| Step | Bytes |
|---|---:|
| text | 350 |
| frames | 0 |
| references | 71 |
| dedup_removed | 0 |

| `data/sample/video_c5925/package.json` | 22 882 674 | 5 623 575 | 75.42% | zstd | frames |

| Step | Bytes |
|---|---:|
| text | 166 |
| frames | 5625540 |
| references | 0 |
| dedup_removed | 0 |

