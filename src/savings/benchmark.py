
import json
from pathlib import Path

from src.savings.report import create_storage_report


def benchmark_files(
    test_cases: list[dict],
    output_file: str | Path
) -> dict:
    """Benchmark multiple original files and knowledge packages."""

    results = []

    for test_case in test_cases:
        report = create_storage_report(
            test_case["original_file"],
            test_case["package_directory"]
        )

        report["name"] = test_case["name"]
        results.append(report)

    total_original = sum(
        result["original_size_bytes"] for result in results
    )

    total_optimized = sum(
        result["optimized_size_bytes"] for result in results
    )

    total_saved = total_original - total_optimized

    total_savings = (
        total_saved / total_original * 100
        if total_original > 0 else 0
    )

    benchmark = {
        "total_files": len(results),
        "total_original_bytes": total_original,
        "total_optimized_bytes": total_optimized,
        "total_saved_bytes": total_saved,
        "total_savings_percent": round(total_savings, 2),
        "results": results
    }

    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_file.write_text(
        json.dumps(benchmark, indent=4),
        encoding="utf-8"
    )

    return benchmark
