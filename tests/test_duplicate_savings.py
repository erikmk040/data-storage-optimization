
from src.savings.duplicate_savings import (
    find_duplicates,
    calculate_duplicate_savings,
)


def test_find_duplicates(tmp_path):
    test_directory = tmp_path / "files"
    test_directory.mkdir()

    file_one = test_directory / "presentation_a.txt"
    file_two = test_directory / "presentation_b.txt"
    file_three = test_directory / "notes.txt"

    file_one.write_text("Same presentation content")
    file_two.write_text("Same presentation content")
    file_three.write_text("Different content")

    duplicates = find_duplicates(test_directory)

    assert len(duplicates) == 1

    duplicate_files = list(duplicates.values())[0]

    assert str(file_one) in duplicate_files
    assert str(file_two) in duplicate_files
    assert str(file_three) not in duplicate_files


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
