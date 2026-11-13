
import json

from src.savings.benchmark import benchmark_files


def test_benchmark_multiple_files(tmp_path):
    original_one = tmp_path / "video1.mp4"
    original_two = tmp_path / "video2.mp4"

    original_one.write_bytes(b"x" * 1000)
    original_two.write_bytes(b"x" * 2000)

    package_one = tmp_path / "package1"
    package_two = tmp_path / "package2"

    package_one.mkdir()
    package_two.mkdir()

    (package_one / "transcript.txt").write_bytes(b"x" * 200)
    (package_two / "transcript.txt").write_bytes(b"x" * 500)

    output_file = tmp_path / "reports" / "benchmark.json"

    test_cases = [
        {
            "name": "Video 1",
            "original_file": original_one,
            "package_directory": package_one
        },
        {
            "name": "Video 2",
            "original_file": original_two,
            "package_directory": package_two
        }
    ]

    result = benchmark_files(test_cases, output_file)

    assert result["total_files"] == 2
    assert result["total_original_bytes"] == 3000
    assert result["total_optimized_bytes"] == 700
    assert result["total_saved_bytes"] == 2300
    assert result["total_savings_percent"] == 76.67

    assert output_file.exists()

    saved_report = json.loads(output_file.read_text())

    assert saved_report["total_files"] == 2
