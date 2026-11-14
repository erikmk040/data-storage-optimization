"""Find exact duplicate files by hashing their bytes with SHA-256.

Usage: python -m src.documents.file_hash FILE [FILE ...]
"""

import argparse
import hashlib
from pathlib import Path
from typing import Iterable


CHUNK_SIZE = 1024 * 1024


def hash_file(path: str | Path, chunk_size: int = CHUNK_SIZE) -> str:
    """Return a file's SHA-256 digest without loading it all into memory."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicate_groups(paths: Iterable[str | Path]) -> dict[str, list[Path]]:
    """Group distinct paths by SHA-256 digest, preserving input order.

    Repeated paths (including relative/absolute aliases) count once. File
    access errors propagate to the caller.
    """
    groups: dict[str, list[Path]] = {}
    seen: set[Path] = set()
    for path in paths:
        path = Path(path)
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        groups.setdefault(hash_file(path), []).append(path)
    return {digest: group for digest, group in groups.items() if len(group) > 1}


def find_duplicates(paths: Iterable[str | Path]) -> list[list[Path]]:
    """Return groups of distinct file paths with identical SHA-256 digests."""
    return list(find_duplicate_groups(paths).values())


def main(argv: list[str] | None = None) -> int:
    """Report duplicate groups for the supplied file paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="files to compare")
    args = parser.parse_args(argv)
    try:
        groups = find_duplicates(args.files)
    except OSError as error:
        parser.exit(1, f"Error: {error}\n")
    if not groups:
        print("No duplicate files found.")
    for index, group in enumerate(groups, start=1):
        print(f"Duplicate group {index}:")
        for path in group:
            print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
