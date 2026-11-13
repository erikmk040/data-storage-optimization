
import hashlib
from pathlib import Path


def calculate_file_hash(file_path: str | Path) -> str:
    """Calculate the SHA-256 hash of a file."""
    file_path = Path(file_path)

    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    sha256 = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def find_duplicates(directory: str | Path) -> dict[str, list[str]]:
    """Find files with identical SHA-256 hashes."""
    directory = Path(directory)

    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    files_by_hash = {}

    for file_path in sorted(directory.rglob("*")):
        if not file_path.is_file():
            continue

        file_hash = calculate_file_hash(file_path)

        files_by_hash.setdefault(file_hash, []).append(str(file_path))

    return {
        file_hash: file_paths
        for file_hash, file_paths in files_by_hash.items()
        if len(file_paths) > 1
    }


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


