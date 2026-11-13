
import json
from pathlib import Path

from .pack import pack
from .report import create_storage_report


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


def benchmark_packages(samples_root: str | Path = "data/sample", output_file: str | Path = "docs/savings.md") -> str:
    """Pack every recording package below *samples_root* and write Markdown results."""
    rows: list[dict] = []
    for package_json in sorted(Path(samples_root).rglob("package.json")):
        output = package_json.parent / (package_json.stem + ".kp")
        report = pack(package_json, output)
        rows.append({"package": str(package_json), "report": report})
    lines = [
        "# Compact package benchmark",
        "",
        "The benchmark measures the deterministic KP v2 archive. Generated `.kp` files remain under `data/` and are ignored by Git.",
        "",
        "| Package | Original video bytes | Packed bytes | Savings | Codec | Largest component |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        report = row["report"]
        original = report.original_video_bytes
        savings = (1 - report.packed_bytes / original) * 100 if original else 0
        lines.append(f"| `{row['package']}` | {original:,} | {report.packed_bytes:,} | {savings:.2f}% | {report.codec} | {report.largest_component} |".replace(",", " "))
        lines.append("")
        lines.append("| Step | Bytes |")
        lines.append("|---|---:|")
        for name, value in report.component_bytes.items():
            lines.append(f"| {name} | {value} |")
        lines.append("")
    markdown = "\n".join(lines) + ("\n" if rows else "")
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return markdown


if __name__ == "__main__":
    benchmark_packages()
