import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.documents.file_hash import find_duplicates, hash_file


class FileHashTests(unittest.TestCase):
    def test_duplicate_files_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second, third = [
                Path(directory) / name for name in ("first.bin", "second.bin", "third.bin")
            ]
            data = b"identical\x00bytes\xff" * 100
            first.write_bytes(data)
            second.write_bytes(data)
            third.write_bytes(b"different bytes")

            # Small chunks force multiple reads, including a partial final chunk.
            self.assertEqual(hash_file(first, chunk_size=7), hashlib.sha256(data).hexdigest())
            self.assertEqual(find_duplicates([first, second, third]), [[first, second]])
            self.assertEqual(find_duplicates([first, first]), [])
            self.assertEqual(find_duplicates([first, third]), [])

            result = subprocess.run(
                [sys.executable, "-m", "src.documents.file_hash", str(first), str(second), str(third)],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(
                result.stdout, f"Duplicate group 1:\n  {first}\n  {second}\n"
            )

    def test_empty_file_and_invalid_chunk_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.bin"
            path.touch()
            self.assertEqual(hash_file(path), hashlib.sha256(b"").hexdigest())
            for size in (0, -1):
                with self.assertRaises(ValueError):
                    hash_file(path, chunk_size=size)


if __name__ == "__main__":
    unittest.main()
