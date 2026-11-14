import json

import pytest
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


def test_identical_frames_are_referenced(tmp_path):
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


def test_roundtrip_preserves_complete_hash_references(tmp_path):
    document_id = "sha256:" + "a" * 64
    slide_hash = "b" * 64
    source_hash = "c" * 64
    package = {
        "id": "rec_hashes",
        "source": {"file": "meeting.mp4", "sha256": source_hash, "duration_s": 1, "size_bytes": 100},
        "segments": [],
        "frames": [{
            "id": "slide-1", "t": 0, "file": "unused",
            "slide_ref": {"doc_id": document_id, "slide_no": 1, "slide_hash": slide_hash},
        }],
    }
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    kp = tmp_path / "hashes.kp"
    pack(package_path, kp)
    output = unpack(kp, tmp_path / "unpacked")
    restored = json.loads(output.read_text(encoding="utf-8"))

    assert restored["source"]["sha256"] == source_hash
    assert restored["frames"][0]["slide_ref"] == package["frames"][0]["slide_ref"]


def test_frame_dedup_requires_identical_pixels_and_preserves_ocr(tmp_path):
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    first = Image.new("RGB", (24, 16), (20, 80, 140))
    changed = first.copy()
    changed.putpixel((0, 0), (21, 80, 140))
    first.save(frame_dir / "one.png")
    changed.save(frame_dir / "two.png")
    first.save(frame_dir / "three.png")
    package = {
        "id": "rec_pixels",
        "source": {"file": "meeting.mp4", "sha256": "d" * 64, "duration_s": 3, "size_bytes": 100},
        "segments": [],
        "frames": [
            {"id": "one", "t": 0, "file": "frames/one.png", "ocr_text": "first text"},
            {"id": "two", "t": 1, "file": "frames/two.png", "ocr_text": "changed image text"},
            {"id": "three", "t": 2, "file": "frames/three.png", "ocr_text": "same image, other text"},
        ],
    }
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    kp = tmp_path / "pixels.kp"
    report = pack(package_path, kp)
    output = unpack(kp, tmp_path / "unpacked")
    restored = json.loads(output.read_text(encoding="utf-8"))
    frames = restored["frames"]

    assert report.dedup_bytes > 0
    assert frames[0]["file"] != frames[1]["file"]
    assert frames[0]["file"] == frames[2]["file"]
    assert [frame["ocr_text"] for frame in frames] == [
        "first text", "changed image text", "same image, other text",
    ]
    with Image.open(tmp_path / "unpacked" / frames[0]["file"]) as first_image:
        first_pixels = first_image.convert("RGBA").tobytes()
    with Image.open(tmp_path / "unpacked" / frames[1]["file"]) as changed_image:
        changed_pixels = changed_image.convert("RGBA").tobytes()
    assert first_pixels != changed_pixels


def test_embedded_zstd_dictionary_decodes_without_sidecar(tmp_path):
    import pytest
    zstd = pytest.importorskip("zstandard")

    from src.savings.pack import MAGIC, _decode

    dictionary_bytes = b"a useful transcript dictionary with repeated recording words"
    dictionary = zstd.ZstdCompressionDict(dictionary_bytes)
    raw = b"repeated recording words in a transcript " * 20
    compressed = zstd.ZstdCompressor(dict_data=dictionary).compress(raw)
    payload = b"KPD1" + len(dictionary_bytes).to_bytes(4, "big") + dictionary_bytes + compressed
    kp = tmp_path / "embedded-dictionary.kp"
    kp.write_bytes(MAGIC + b"Y" + payload)

    codec, decoded = _decode(kp)
    assert codec == "zstd-dict"
    assert decoded == raw


def test_empty_and_missing_speakers_roundtrip_distinctly(tmp_path):
    package = {
        "id": "rec_speakers",
        "source": {"file": "meeting.mp4", "sha256": "e" * 64, "duration_s": 2, "size_bytes": 100},
        "segments": [
            {"start": 0, "end": 1, "speaker": "", "text": "empty label"},
            {"start": 1, "end": 2, "speaker": None, "text": "no label"},
        ],
        "frames": [],
    }
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    kp = tmp_path / "speakers.kp"
    pack(package_path, kp)
    output = unpack(kp, tmp_path / "unpacked")
    restored = json.loads(output.read_text(encoding="utf-8"))

    assert [segment["speaker"] for segment in restored["segments"]] == ["", None]


def test_pack_rejects_unsafe_or_duplicate_frame_ids(tmp_path):
    package = {
        "id": "rec_bad_ids",
        "source": {"file": "meeting.mp4", "sha256": "f" * 64, "duration_s": 1, "size_bytes": 1},
        "segments": [],
        "frames": [{"id": "../escape", "t": 0, "file": "unused", "slide_ref": {"doc_id": "DOC", "slide_no": 1}}],
    }
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe frame id"):
        pack(package_path, tmp_path / "unsafe.kp")

    package["frames"] = [
        {"id": "same", "t": 0, "file": "unused", "slide_ref": {"doc_id": "DOC", "slide_no": 1}},
        {"id": "same", "t": 1, "file": "unused", "slide_ref": {"doc_id": "DOC", "slide_no": 2}},
    ]
    package_path.write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate frame id"):
        pack(package_path, tmp_path / "duplicate.kp")
