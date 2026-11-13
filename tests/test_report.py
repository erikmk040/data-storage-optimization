
from src.savings.report import create_storage_report, save_report
from src.savings.report import create_duplicate_report

def test_create_storage_report(tmp_path):
    original_file = tmp_path / "meeting.mp4"
    original_file.write_bytes(b"x" * 1000)

    package_directory = tmp_path / "knowledge_package"
    package_directory.mkdir()

    (package_directory / "transcript.txt").write_bytes(b"x" * 200)
    (package_directory / "metadata.json").write_bytes(b"x" * 100)

    report = create_storage_report(
        original_file,
        package_directory
    )

    assert report["original_size_bytes"] == 1000
    assert report["optimized_size_bytes"] == 300
    assert report["saved_bytes"] == 700
    assert report["savings_percent"] == 70.0


def test_save_report(tmp_path):
    report = {"savings_percent": 70.0}
    output_file = tmp_path / "reports" / "result.json"

    save_report(report, output_file)

    assert output_file.exists()

def test_create_duplicate_report(tmp_path):
    file_one = tmp_path / "presentation_a.txt"
    file_two = tmp_path / "presentation_b.txt"
    file_three = tmp_path / "notes.txt"

    file_one.write_text("Same presentation")
    file_two.write_text("Same presentation")
    file_three.write_text("Different content")

    report = create_duplicate_report(tmp_path)

    assert report["total_duplicate_groups"] == 1
    assert report["potential_saved_bytes"] == file_one.stat().st_size
    assert report["automatic_deletion"] is False
