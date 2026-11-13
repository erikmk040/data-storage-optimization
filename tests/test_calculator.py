import pytest

from src.savings.calculator import (
    calculate_savings,
    calculate_directory_size
)


def test_calculate_savings():
    result = calculate_savings(1_000_000, 200_000)
    assert result["saved_bytes"] == 800_000
    assert result["savings_percent"] == 80.0


def test_no_savings():
    result = calculate_savings(1000, 1000)
    assert result["savings_percent"] == 0.0


def test_negative_savings():
    result = calculate_savings(1000, 1200)
    assert result["savings_percent"] == -20.0


def test_invalid_original_size():
    with pytest.raises(ValueError):
        calculate_savings(0, 100)


def test_negative_optimized_size():
    with pytest.raises(ValueError):
        calculate_savings(1000, -100)


def test_calculate_directory_size(tmp_path):
    (tmp_path / "text.txt").write_text("Hello")
    (tmp_path / "image.txt").write_text("World")

    result = calculate_directory_size(tmp_path)
    assert result == 10