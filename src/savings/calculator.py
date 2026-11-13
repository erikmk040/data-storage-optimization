from pathlib import Path


def calculate_directory_size(directory: str | Path) -> int:
    """Calculate the total size of all files in a directory."""

    directory = Path(directory)

    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    return sum(
        file.stat().st_size
        for file in directory.rglob("*")
        if file.is_file()
    )


def calculate_savings(
    original_size: int,
    optimized_size: int
) -> dict:
    """Calculate storage savings and return a benchmark report."""

    if original_size <= 0:
        raise ValueError("Original size must be greater than zero")

    if optimized_size < 0:
        raise ValueError("Optimized size cannot be negative")

    saved_bytes = original_size - optimized_size

    savings_percent = (saved_bytes / original_size) * 100

    return {
        "original_size_bytes": original_size,
        "optimized_size_bytes": optimized_size,
        "saved_bytes": saved_bytes,
        "savings_percent": round(savings_percent, 2)
    }
