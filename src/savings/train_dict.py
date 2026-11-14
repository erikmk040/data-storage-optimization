"""Train an optional zstandard dictionary from sample transcripts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def train(output: str | Path, samples_root: str | Path = "data/sample", size: int = 8192) -> Path:
    import zstandard as zstd

    samples = []
    for package_path in sorted(Path(samples_root).rglob("package.json")):
        package = json.loads(package_path.read_text(encoding="utf-8"))
        samples.extend(str(segment.get("text", "")).encode("utf-8") for segment in package.get("segments", []))
    if not samples:
        raise ValueError("No transcript samples found")
    dictionary = zstd.train_dictionary(size, samples)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(dictionary.as_bytes())
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a zstandard transcript dictionary.")
    parser.add_argument("--output", default="data/dict/transcript.zdict")
    parser.add_argument("--samples-root", default="data/sample")
    parser.add_argument("--size", type=int, default=8192)
    args = parser.parse_args()
    print(train(args.output, args.samples_root, args.size))


if __name__ == "__main__":
    main()
