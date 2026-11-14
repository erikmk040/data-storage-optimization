import json

from PIL import Image

from src.savings.pack import pack, unpack


def _package(tmp_path):
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    image = Image.new("RGB", (24, 16), (20, 80, 140))
    image.save(frame_dir / "f_001.png")
    package = {
        "id": "rec_compact",
        "source": {"file": "meeting.mp4", "sha256": "a" * 64, "duration_s": 12, "size_bytes": 250000},
        "segments": [
            {"start": 1.01, "end": 2.06, "speaker": "A", "text": "Unicode åäö | stays exact", "frame_id": "f_001"},
        ],
        "frames": [{"id": "f_001", "t": 1.01, "file": "frames/f_001.png", "ocr_text": "plain"}],
    }
    path = tmp_path / "package.json"
    path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    return path, package


def test_text_and_image_roundtrip(tmp_path):
    package_path, original = _package(tmp_path)
    kp = tmp_path / "recording.kp"
    report = pack(package_path, kp)
    output = tmp_path / "unpacked"
    unpack(kp, output)
    restored = json.loads((output / "package.json").read_text(encoding="utf-8"))

    assert report.packed_bytes > 0
    assert report.packed_bytes < 100_000
    assert restored["segments"][0]["text"] == original["segments"][0]["text"]
    assert abs(restored["segments"][0]["start"] - 1.0) <= 0.1
    assert abs(restored["segments"][0]["end"] - 2.1) <= 0.1
    with Image.open(tmp_path / "frames/f_001.png") as before, Image.open(output / "frames/f_001.webp") as after:
        assert before.convert("RGBA").tobytes() == after.convert("RGBA").tobytes()


def test_ascii_roundtrip(tmp_path):
    package_path, _ = _package(tmp_path)
    kp = tmp_path / "recording-ascii.kp"
    pack(package_path, kp, ascii_armor=True)
    output = tmp_path / "unpacked-ascii"
    unpack(kp, output)
    assert (output / "package.json").is_file()


def test_slide_references_do_not_store_images(tmp_path):
    package = {
        "id": "rec_slide",
        "source": {"file": "meeting.mp4", "sha256": "b" * 64, "duration_s": 1, "size_bytes": 1000},
        "segments": [],
        "frames": [{"id": "slide-1", "t": 0, "file": "frames/missing.webp", "ocr_text": "Title", "slide_ref": {"doc_id": "DOC-1", "slide_no": 2, "slide_hash": "c" * 32}}],
    }
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    kp = tmp_path / "slide.kp"
    report = pack(package_path, kp)
    assert report.frame_bytes == 0
    output = tmp_path / "slide-out"
    unpack(kp, output)
    restored = json.loads((output / "package.json").read_text())
    assert restored["frames"][0]["slide_ref"]["doc_id"] == "DOC-1"


def test_unpacked_package_can_be_indexed_and_searched(tmp_path, monkeypatch):
    package_path, _ = _package(tmp_path)
    kp = tmp_path / "recording.kp"
    pack(package_path, kp)
    output = tmp_path / "indexed"
    unpack(kp, output)

    import src.search.index as index_module
    import src.search.query as query_module
    import src.search.db as db

    index_package = index_module.index_package
    search = query_module.search
    connect = lambda: db.connect(tmp_path / "index.db")
    monkeypatch.setattr(index_module, "connect", connect)
    monkeypatch.setattr(query_module, "connect", connect)
    index_package(output / "package.json")
    results = search("Unicode")
    assert results
    assert results[0]["text"] == "Unicode åäö | stays exact"


def test_near_duplicate_frames_are_referenced(tmp_path):
    package_path, package = _package(tmp_path)
    from PIL import Image

    Image.open(tmp_path / "frames/f_001.png").save(tmp_path / "frames/f_002.png")
    package["frames"].append({"id": "f_002", "t": 2, "file": "frames/f_002.png", "ocr_text": "plain"})
    package_path.write_text(json.dumps(package), encoding="utf-8")
    kp = tmp_path / "dedup.kp"
    report = pack(package_path, kp)
    assert report.dedup_bytes > 0
    output = tmp_path / "dedup-out"
    unpack(kp, output)
    restored = json.loads((output / "package.json").read_text())
    assert restored["frames"][1]["file"] == restored["frames"][0]["file"]
