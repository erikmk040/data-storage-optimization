
from pathlib import Path

from src.documents.file_hash import find_duplicate_groups, hash_file


def calculate_file_hash(file_path: str | Path) -> str:
    """Compatibility wrapper around the shared file hash implementation."""
    return hash_file(file_path)


def find_duplicates(directory: str | Path) -> dict[str, list[str]]:
    """Find files with identical SHA-256 hashes."""
    directory = Path(directory)

    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    files_by_hash = find_duplicate_groups(
        file_path for file_path in sorted(directory.rglob("*")) if file_path.is_file()
    )
    return {file_hash: [str(path) for path in paths]
            for file_hash, paths in files_by_hash.items()}


def calculate_duplicate_savings(
    duplicates: dict[str, list[str]]
) -> dict:
    """Calculate potential storage savings from duplicate files."""
    total_saved_bytes = 0
    duplicate_groups = []

    for file_paths in duplicates.values():
        if len(file_paths) < 2:
            continue

        files = [Path(file_path) for file_path in file_paths]
        file_sizes = [file.stat().st_size for file in files]

        saved_bytes = sum(file_sizes) - max(file_sizes)
        total_saved_bytes += saved_bytes

        duplicate_groups.append({
            "files": [str(file) for file in files],
            "saved_bytes": saved_bytes
        })

    return {
        "duplicate_groups": duplicate_groups,
        "total_saved_bytes": total_saved_bytes
    }


from src.savings.duplicate_savings import calculate_duplicate_savings


def test_calculate_duplicate_savings(tmp_path):
    file_one = tmp_path / "presentation_a.txt"
    file_two = tmp_path / "presentation_b.txt"

    file_one.write_text("Same content")
    file_two.write_text("Same content")

    duplicates = {
        "same_hash": [str(file_one), str(file_two)]
    }

    result = calculate_duplicate_savings(duplicates)

    assert result["total_saved_bytes"] == file_one.stat().st_size
    assert len(result["duplicate_groups"]) == 1


