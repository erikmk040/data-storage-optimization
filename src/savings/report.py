
import json
from pathlib import Path
from src.savings.duplicate_savings import (
    find_duplicates,
    calculate_duplicate_savings
)

from src.savings.calculator import (
    calculate_directory_size,
    calculate_savings
)


def create_storage_report(
    original_file: str | Path,
    package_directory: str | Path
) -> dict:
    """Compare original file size with the complete knowledge package."""

    original_file = Path(original_file)
    package_directory = Path(package_directory)

    if not original_file.is_file():
        raise FileNotFoundError("Original file not found")

    original_size = original_file.stat().st_size
    package_size = calculate_directory_size(package_directory)

    report = calculate_savings(original_size, package_size)

    report["original_file"] = original_file.name
    report["package_directory"] = str(package_directory)

    return report


def save_report(report: dict, output_file: str | Path) -> None:
    """Save storage benchmark as JSON."""

    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_file.write_text(
        json.dumps(report, indent=4),
        encoding="utf-8"
    )


def create_duplicate_report(directory: str | Path) -> dict:
    """Create a report of duplicate files and potential storage savings."""

    directory = Path(directory)

    duplicates = find_duplicates(directory)
    savings = calculate_duplicate_savings(duplicates)

    return {
        "directory": str(directory),
        "duplicate_groups": savings["duplicate_groups"],
        "total_duplicate_groups": len(savings["duplicate_groups"]),
        "potential_saved_bytes": savings["total_saved_bytes"],
        "automatic_deletion": False
    }
