"""Regression coverage for the app/search/upload behaviors combined in PR #15."""

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _app(monkeypatch, directory):
    streamlit = pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(directory)
    streamlit.cache_resource.clear()
    streamlit.cache_data.clear()
    source = (ROOT / "app/streamlit_app.py").read_text(encoding="utf-8")
    # Capture the actual app's storage report for assertions without adding a
    # testing hook or changing the production UI. Each app runs in a temp cwd.
    script = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n" + source
    script += '\nst.session_state["_tested_storage"] = storage\n'
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception, [error.message for error in app.exception]
    return app


def test_fresh_app_demo_search_reindex_and_honest_fixture_statistics(tmp_path, monkeypatch):
    app = _app(monkeypatch, tmp_path)
    report = app.session_state["_tested_storage"]
    package_path = tmp_path / "data/sample/rec_mock/package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    expected_input = package_path.stat().st_size + sum(
        path.stat().st_size for path in (package_path.parent / "frames").iterdir() if path.is_file()
    )
    assert report["source_available"] is False
    assert report["original_bytes"] == expected_input
    assert report["original_bytes"] != package["source"]["size_bytes"]
    assert report["saved_bytes"] == expected_input - report["compact_bytes"]
    assert any("mock source-size metadata is not a measured video" in caption.value for caption in app.caption)

    from src.search.index import index_package
    from src.search.query import search

    before = search("storage")
    assert before
    assert all(Path(result["frame"]["file"]).is_file() for result in before if result["frame"])
    index_package(package_path)
    index_package(package_path)
    assert search("storage") == before
    with sqlite3.connect(tmp_path / "data/index.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == len(package["segments"])
        assert connection.execute("SELECT COUNT(*) FROM frames_fts").fetchone()[0] == len(package["frames"])
    app.text_input(key="search_query").set_value("storage").run()
    assert not app.exception
    assert any(f"{len(before)} hits" in caption.value for caption in app.caption)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="Native FFmpeg and FFprobe are required for the video upload smoke test")
def test_real_mp4_upload_compression_roundtrip_and_session_index(tmp_path, monkeypatch):
    # Actual encoded video, with no audio: exercise upload/build/pack/search
    # without pretending to test speech transcription or downloading a model.
    video = tmp_path / "input.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=320x240:rate=8", "-t", "2", "-an", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-threads", "1", str(video),
    ], check=True, capture_output=True, timeout=60)
    payload = video.read_bytes()
    app = _app(monkeypatch, tmp_path)
    if not hasattr(app.file_uploader[0], "set_value"):
        pytest.skip("This Streamlit version lacks file uploader testing support")
    app.file_uploader[0].set_value(("uploaded.mp4", payload, "video/mp4")).run()
    assert not app.exception
    app.button(key="compress_uploads").click().run()
    assert not app.exception, [error.message for error in app.exception]
    measurements = list(app.session_state["upload_measurements"].values())
    assert len(measurements) == 1
    measurement = measurements[0]
    assert measurement["facts"]["mode"] == "semantic video compression"
    assert measurement["facts"]["unique frames"] > 0
    packed = Path(measurement["kp_path"])
    assert measurement["original_bytes"] == len(payload)
    assert measurement["compressed_bytes"] == packed.stat().st_size
    assert measurement["saved_bytes"] == len(payload) - packed.stat().st_size
    assert measurement["saved_percent"] == pytest.approx(measurement["saved_bytes"] / len(payload) * 100)

    from src.savings.pack import unpack
    from src.search.index import index_package
    from src.search.query import search

    restored_path = unpack(packed, tmp_path / "unpacked-upload")
    restored = json.loads(restored_path.read_text(encoding="utf-8"))
    assert restored["source"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert restored["source"]["size_bytes"] == len(payload)
    assert restored["frames"]
    assert all((restored_path.parent / frame["file"]).is_file() for frame in restored["frames"])
    database = Path(measurement["search_db"])
    package_path = packed.parent / "package/package.json"
    index_package(package_path, db_path=database)
    index_package(package_path, db_path=database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == len(restored["frames"])
    assert search("storage")  # The session's upload must not replace the demo index.
    app.run()
    assert not app.exception
    assert len(app.session_state["upload_measurements"]) == 1
    assert packed.is_file() and video.read_bytes() == payload
    app.button(key="clear_uploads").click().run()
    assert not app.exception
    assert not packed.exists()
    assert video.read_bytes() == payload
