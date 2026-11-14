"""Generated-video smoke test for package, KP, index and search integration."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from src.savings.pack import pack
from src.search.index import index_package
from src.search.query import search
from src.video.package import build_package


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_generated_video_package_to_kp_to_index_to_search(tmp_path) -> None:
    source = tmp_path / "generated.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=1:duration=31",
            "-vf",
            "format=yuvj420p",
            "-color_range",
            "pc",
            "-y",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    package_path = build_package(
        source,
        tmp_path / "package",
        transcribe_audio=False,
    )
    package = json.loads(package_path.read_text(encoding="utf-8"))
    assert package["frames"]
    package["segments"] = [
        {
            "start": 0.0,
            "end": 1.0,
            "speaker": None,
            "text": "Generated aurora search proof",
            "frame_id": package["frames"][0]["id"],
        }
    ]
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")

    output = tmp_path / "generated.kp"
    report = pack(package_path, output)
    assert output.is_file()
    assert report.packed_bytes == output.stat().st_size

    database = tmp_path / "search.db"
    index_package(package_path, db_path=database)
    hits = search("aurora", db_path=database)
    assert hits
    assert hits[0]["frame"]["id"] == package["frames"][0]["id"]
    assert hits[0]["source_file"] == source.name

