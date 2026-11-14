"""Compact, loss-aware recording package format (KP v2).

The container is deliberately deterministic: a small manifest and two UTF-8
indexes are stored in a tar archive and then compressed with the smallest
available codec.  Original media is never silently discarded: an image is
stored losslessly unless a separately verified lossy candidate is smaller.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import lzma
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops


MAGIC = b"KP2"
CODECS = {b"X": "xz", b"B": "brotli", b"Z": "zstd", b"Y": "zstd-dict", b"P": "ppmd", b"7": "7z"}
CODEC_IDS = {value: key for key, value in CODECS.items()}


def _field(value: str) -> str:
    """Escape one text field without changing its UTF-8 content."""
    return value.replace("\\", "\\\\").replace("|", "\\p").replace("\n", "\\n").replace("\r", "\\r")


def _unfield(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "\\" or index + 1 >= len(value):
            result.append(value[index])
            index += 1
            continue
        escaped = value[index + 1]
        result.append({"p": "|", "n": "\n", "r": "\r", "\\": "\\"}.get(escaped, escaped))
        index += 2
    return "".join(result)


def _round(value: float, resolution: float) -> float:
    return round(value / resolution) * resolution


def _short_hash(value: str | None) -> str:
    return (value or "").lower()[:32]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_pixels_equal(left: Image.Image, right: Image.Image) -> bool:
    if left.mode != right.mode or left.size != right.size:
        return False
    return ImageChops.difference(left, right).getbbox() is None


def _lossless_webp(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        image.save(target, format="WEBP", lossless=True, method=6)
    with Image.open(source) as original, Image.open(target) as encoded:
        if not _image_pixels_equal(original.convert("RGBA"), encoded.convert("RGBA")):
            raise ValueError(f"Lossless WebP verification failed for {source}")


def _verified_lossy(source: Path, lossless: Path, ocr_text: str) -> Path:
    """Return a smaller verified candidate, otherwise the lossless image.

    Lossy output is optional and conservative.  OCR and SSIM are imported only
    when installed; failure to verify means the lossless candidate wins.
    """
    try:
        import pytesseract
        from skimage.metrics import structural_similarity
    except ImportError:
        return lossless
    candidate = lossless.with_name(lossless.stem + ".lossy.webp")
    try:
        with Image.open(source) as original:
            original_rgb = original.convert("RGB")
            source_ocr = pytesseract.image_to_string(original_rgb).strip()
            declared_ocr = ocr_text.strip()
            if declared_ocr and source_ocr != declared_ocr:
                return lossless
            original_array = __import__("numpy").asarray(original_rgb)
            # Try progressively smaller WebP candidates. The first accepted
            # candidate is always verified against the original pixels.
            for quality in (90, 85, 80, 75, 70):
                original.save(candidate, format="WEBP", quality=quality, method=6)
                with Image.open(candidate) as encoded:
                    encoded_rgb = encoded.convert("RGB")
                    score = structural_similarity(
                        original_array,
                        __import__("numpy").asarray(encoded_rgb),
                        channel_axis=2,
                    )
                    candidate_ocr = pytesseract.image_to_string(encoded_rgb).strip()
                if score > 0.99 and candidate_ocr == source_ocr and candidate.stat().st_size < lossless.stat().st_size:
                    lossless.unlink(missing_ok=True)
                    candidate.rename(lossless)
                    return lossless
    except Exception:
        pass
    candidate.unlink(missing_ok=True)
    return lossless


def _phash(path: Path):
    try:
        import imagehash
        with Image.open(path) as image:
            return imagehash.phash(image)
    except (ImportError, OSError):
        return None


def _distance(left, right) -> int | None:
    if left is None or right is None:
        return None
    return int(left - right)


@dataclass
class PackReport:
    """Measured sizes and decisions made while producing one KP archive."""

    original_video_bytes: int
    text_bytes: int
    frame_bytes: int
    reference_bytes: int
    dedup_bytes: int
    codec: str
    packed_bytes: int
    component_bytes: dict[str, int] = field(default_factory=dict)
    output: str | None = None

    @property
    def largest_component(self) -> str:
        return max(self.component_bytes, key=self.component_bytes.get, default="none")

    def to_dict(self) -> dict:
        return {
            "original_video_bytes": self.original_video_bytes,
            "text_bytes": self.text_bytes,
            "frame_bytes": self.frame_bytes,
            "reference_bytes": self.reference_bytes,
            "dedup_bytes": self.dedup_bytes,
            "codec": self.codec,
            "packed_bytes": self.packed_bytes,
            "largest_component": self.largest_component,
            "component_bytes": dict(self.component_bytes),
            "output": self.output,
        }


def _speakers(segments: list[dict]) -> tuple[list[str], dict[str, int]]:
    names = sorted({str(s["speaker"]) for s in segments if s.get("speaker") is not None})
    return names, {name: index for index, name in enumerate(names)}


def _make_text_indexes(package: dict, resolution: float) -> tuple[str, str, dict[str, int]]:
    segments = package.get("segments", [])
    speakers, speaker_ids = _speakers(segments)
    t_lines = ["spk:" + "|".join(_field(speaker) for speaker in speakers)]
    previous = 0.0
    for segment in segments:
        start = _round(float(segment["start"]), resolution)
        end = _round(float(segment["end"]), resolution)
        frame_id = segment.get("frame_id", "")
        t_lines.append("|".join((
            f"{int(round((start - previous) / resolution))}",
            f"{int(round((end - start) / resolution))}",
            str(speaker_ids.get(str(segment.get("speaker")), -1)),
            _field(str(frame_id)) if frame_id else "",
            _field(str(segment.get("text", ""))),
        )))
        previous = start

    frame_ids = {str(frame["id"]): index for index, frame in enumerate(package.get("frames", []), 1)}
    return "\n".join(t_lines) + "\n", "", frame_ids


def _build_archive(package_json: Path, work: Path, resolution: float, voice: bool) -> tuple[dict, dict[str, int]]:
    package = json.loads(package_json.read_text(encoding="utf-8"))
    rec_id = str(package["id"])
    source = package.get("source", {})
    frames_dir = work / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    speakers, speaker_ids = _speakers(package.get("segments", []))
    previous = 0.0
    text_lines = ["spk:" + "|".join(_field(speaker) for speaker in speakers)]
    frame_id_to_index = {str(frame["id"]): index for index, frame in enumerate(package.get("frames", []), 1)}
    for segment in package.get("segments", []):
        start = _round(float(segment["start"]), resolution)
        end = _round(float(segment["end"]), resolution)
        text_lines.append("|".join((
            str(int(round((start - previous) / resolution))),
            str(int(round((end - start) / resolution))),
            str(speaker_ids.get(str(segment.get("speaker")), -1)),
            str(frame_id_to_index.get(str(segment.get("frame_id")), "")),
            _field(str(segment.get("text", ""))),
        )))
        previous = start

    frame_lines: list[str] = []
    phashes: list[tuple[str, object]] = []
    raw_frame_bytes = 0
    unique_frame_bytes = 0
    reference_bytes = 0
    dedup_bytes = 0
    frame_records: list[tuple[dict, Path | None, str]] = []
    for frame in package.get("frames", []):
        frame_id = str(frame["id"])
        timestamp = _round(float(frame.get("t", 0)), resolution)
        slide = frame.get("slide_ref") or {}
        if slide.get("doc_id") is not None and slide.get("slide_no") is not None:
            line = f"S|{_field(frame_id)}|{timestamp:g}|{_field(str(slide['doc_id']))}|{int(slide['slide_no'])}|{_short_hash(slide.get('slide_hash'))}"
            frame_lines.append(line)
            reference_bytes += len((line + "\n").encode())
            frame_records.append((frame, None, "S"))
            continue
        source_frame = package_json.parent / str(frame.get("file", ""))
        if not source_frame.is_file():
            raise FileNotFoundError(f"Frame file not found: {source_frame}")
        raw_frame_bytes += source_frame.stat().st_size
        phash = _phash(source_frame)
        duplicate = next(((existing_id, existing_hash) for existing_id, existing_hash in phashes if _distance(phash, existing_hash) is not None and _distance(phash, existing_hash) <= 2), None)
        if duplicate:
            line = f"D|{_field(frame_id)}|{timestamp:g}|{_field(duplicate[0])}"
            frame_lines.append(line)
            dedup_bytes += source_frame.stat().st_size
            frame_records.append((frame, None, "D"))
            continue
        target = frames_dir / f"{frame_id}.webp"
        _lossless_webp(source_frame, target)
        _verified_lossy(source_frame, target, str(frame.get("ocr_text", "")))
        phashes.append((frame_id, phash))
        unique_frame_bytes += target.stat().st_size
        line = f"I|{_field(frame_id)}|{timestamp:g}|{_field(str(frame.get('ocr_text', '')))}"
        frame_lines.append(line)
        frame_records.append((frame, target, "I"))

    manifest = {
        "version": 2,
        "rec_id": rec_id,
        "source_file": str(source.get("file", "")),
        "sha256": _short_hash(source.get("sha256")),
        "duration_s": source.get("duration_s"),
        "size_bytes": source.get("size_bytes"),
        "time_resolution": resolution,
        "voice": bool(voice),
    }
    (work / "m.txt").write_text("".join(f"{key}={value}\n" for key, value in manifest.items()), encoding="utf-8")
    (work / "t.txt").write_text("\n".join(text_lines) + "\n", encoding="utf-8")
    (work / "f.txt").write_text("\n".join(frame_lines) + ("\n" if frame_lines else ""), encoding="utf-8")
    if voice:
        (work / "voice").mkdir(exist_ok=True)
        (work / "voice" / "README.txt").write_text("Voice preservation is opt-in and not present in this package.\n", encoding="utf-8")
    component_bytes = {
        "text": (work / "m.txt").stat().st_size + (work / "t.txt").stat().st_size,
        "frames": unique_frame_bytes,
        "references": reference_bytes,
        "dedup_removed": dedup_bytes,
    }
    return {"manifest": manifest, "frame_records": frame_records, "speakers": speakers}, component_bytes | {"raw_frames": raw_frame_bytes}


def _tar_bytes(work: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path in sorted(work.rglob("*")):
            if not path.is_file():
                continue
            info = tarfile.TarInfo(path.relative_to(work).as_posix())
            data = path.read_bytes()
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _compress_candidates(data: bytes) -> dict[str, bytes]:
    candidates = {"xz": lzma.compress(data, format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME)}
    try:
        import brotli
        candidates["brotli"] = brotli.compress(data, quality=11, lgwin=24)
    except ImportError:
        pass
    try:
        import zstandard as zstd
        try:
            compressor = zstd.ZstdCompressor(
                level=19, long_distance_matcher=True, window_log=27
            )
        except TypeError:
            # zstandard 0.25 exposes long-distance matching through lower-level
            # compression parameters, while older releases accepted these
            # keywords directly. Level 19 remains the portable equivalent.
            compressor = zstd.ZstdCompressor(level=19)
        candidates["zstd"] = compressor.compress(data)
        dictionary_path = Path("data/dict/transcript.zdict")
        if dictionary_path.is_file():
            try:
                dictionary = zstd.ZstdCompressionDict(dictionary_path.read_bytes())
                candidates["zstd-dict"] = zstd.ZstdCompressor(level=19, dict_data=dictionary).compress(data)
            except (OSError, ValueError):
                pass
    except (ImportError, ValueError):
        pass
    try:
        import py7zr
        with tempfile.TemporaryDirectory(prefix="kp7z-") as directory:
            archive_path = Path(directory) / "archive.7z"
            source = Path(directory) / "payload"
            source.write_bytes(data)
            with py7zr.SevenZipFile(archive_path, "w", filters=[{"id": py7zr.FILTER_COPY}]) as archive:
                archive.write(source, arcname="payload")
            candidates["7z"] = archive_path.read_bytes()
        with tempfile.TemporaryDirectory(prefix="kpppmd-") as directory:
            archive_path = Path(directory) / "archive.7z"
            source = Path(directory) / "payload"
            source.write_bytes(data)
            filters = [{"id": py7zr.FILTER_PPMD, "order": 6, "mem": 24}]
            with py7zr.SevenZipFile(archive_path, "w", filters=filters) as archive:
                archive.write(source, arcname="payload")
            candidates["ppmd"] = archive_path.read_bytes()
    except (ImportError, OSError, TypeError, AttributeError, ValueError):
        pass
    return candidates


def pack(package_json: str | Path, out: str | Path, ascii_armor: bool = False, voice: bool = False, time_res: float = 0.1) -> PackReport:
    """Pack a recording package into a KP v2 file."""
    package_json = Path(package_json)
    out = Path(out)
    if time_res <= 0:
        raise ValueError("time_res must be positive")
    with tempfile.TemporaryDirectory(prefix="kp2-") as directory:
        work = Path(directory)
        _metadata, components = _build_archive(package_json, work, time_res, voice)
        raw = _tar_bytes(work)
        candidates = _compress_candidates(raw)
        codec, payload = min(candidates.items(), key=lambda item: len(item[1]))
        encoded = MAGIC + CODEC_IDS[codec] + payload
        if ascii_armor:
            encoded = MAGIC + b"A" + base64.b85encode(encoded)
            codec_label = f"ascii+{codec}"
        else:
            codec_label = codec
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(encoded)
    component_bytes = {key: value for key, value in components.items() if key != "raw_frames"}
    return PackReport(
        original_video_bytes=int(json.loads(package_json.read_text(encoding="utf-8"))["source"].get("size_bytes") or 0),
        text_bytes=component_bytes["text"],
        frame_bytes=component_bytes["frames"],
        reference_bytes=component_bytes["references"],
        dedup_bytes=component_bytes["dedup_removed"],
        codec=codec_label,
        packed_bytes=out.stat().st_size,
        component_bytes=component_bytes,
        output=str(out),
    )


def _decode(path: Path) -> tuple[str, bytes]:
    encoded = path.read_bytes()
    if encoded[:3] != MAGIC:
        raise ValueError("Not a KP v2 file")
    marker, payload = encoded[3:4], encoded[4:]
    if marker == b"A":
        decoded = base64.b85decode(payload)
        if decoded[:3] != MAGIC:
            raise ValueError("Invalid ASCII KP header")
        marker, payload = decoded[3:4], decoded[4:]
    codec = CODECS.get(marker)
    if codec is None:
        raise ValueError(f"Unknown KP codec marker: {marker!r}")
    if codec == "xz":
        raw = lzma.decompress(payload)
    elif codec == "brotli":
        import brotli
        raw = brotli.decompress(payload)
    elif codec in ("zstd", "zstd-dict"):
        import zstandard as zstd
        if codec == "zstd-dict":
            dictionary_path = Path("data/dict/transcript.zdict")
            if not dictionary_path.is_file():
                raise FileNotFoundError("The zstandard dictionary required by this KP file is missing")
            dictionary = zstd.ZstdCompressionDict(dictionary_path.read_bytes())
            raw = zstd.ZstdDecompressor(dict_data=dictionary).decompress(payload)
        else:
            raw = zstd.ZstdDecompressor().decompress(payload)
    else:
        import py7zr
        with tempfile.TemporaryDirectory(prefix="kp7z-unpack-") as directory:
            archive_path = Path(directory) / "archive.7z"
            archive_path.write_bytes(payload)
            with py7zr.SevenZipFile(archive_path, "r") as archive:
                archive.extractall(directory)
            raw = (Path(directory) / "payload").read_bytes()
    return codec, raw


def _parse_manifest(path: Path) -> dict[str, str]:
    return dict(line.rstrip("\n").split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)


def unpack(kp_path: str | Path, out_dir: str | Path) -> Path:
    """Unpack and reconstruct a search-compatible recording package."""
    kp_path, out_dir = Path(kp_path), Path(out_dir)
    with tempfile.TemporaryDirectory(prefix="kp2-unpack-") as directory:
        codec, raw = _decode(kp_path)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            archive.extractall(directory)
        root = Path(directory)
        manifest = _parse_manifest(root / "m.txt")
        output = out_dir
        output.mkdir(parents=True, exist_ok=True)
        frames = output / "frames"
        frames.mkdir(exist_ok=True)
        extracted_frames = []
        frame_by_index: dict[int, dict] = {}
        for index, line in enumerate((root / "f.txt").read_text(encoding="utf-8").splitlines(), 1):
            parts = line.split("|")
            kind, frame_id, timestamp = parts[0], _unfield(parts[1]), float(parts[2])
            record = {"id": frame_id, "t": timestamp, "phash": None, "ocr_text": ""}
            if kind == "S":
                record["file"] = f"frames/{frame_id}.ref"
                record["slide_ref"] = {"doc_id": _unfield(parts[3]), "slide_no": int(parts[4]), "slide_hash": parts[5] or None}
            elif kind == "D":
                target_index = next(i for i, item in frame_by_index.items() if item["id"] == _unfield(parts[3]))
                record["file"] = frame_by_index[target_index]["file"]
            elif kind == "I":
                record["ocr_text"] = _unfield("|".join(parts[3:]))
                source = root / "frames" / f"{frame_id}.webp"
                target = frames / source.name
                shutil.copyfile(source, target)
                record["file"] = f"frames/{target.name}"
            else:
                raise ValueError(f"Unknown frame type {kind!r}")
            frame_by_index[index] = record
            extracted_frames.append(record)
        segments = []
        previous = 0.0
        time_res = float(manifest.get("time_resolution", "0.1"))
        text_lines = (root / "t.txt").read_text(encoding="utf-8").splitlines()
        speakers = [_unfield(value) for value in text_lines[0][4:].split("|") if value]
        for line in text_lines[1:]:
            delta, duration, speaker_index, frame_index, text = line.split("|", 4)
            start = previous + int(delta) * time_res
            end = start + int(duration) * time_res
            segment = {"start": round(start, 6), "end": round(end, 6), "speaker": speakers[int(speaker_index)] if int(speaker_index) >= 0 else None, "text": _unfield(text)}
            if frame_index:
                segment["frame_id"] = frame_by_index[int(frame_index)]["id"]
            segments.append(segment)
            previous = start
        package = {"id": manifest["rec_id"], "source": {"file": manifest.get("source_file", ""), "sha256": manifest.get("sha256", ""), "duration_s": float(manifest.get("duration_s", 0)), "size_bytes": int(manifest.get("size_bytes", 0))}, "segments": segments, "frames": extracted_frames}
        (output / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output / "package.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Pack a recording package into a compact KP v2 archive.")
    parser.add_argument("package_json")
    parser.add_argument("out")
    parser.add_argument("--ascii", action="store_true", dest="ascii_armor")
    parser.add_argument("--voice", action="store_true")
    parser.add_argument("--time-res", type=float, default=0.1)
    args = parser.parse_args()
    report = pack(args.package_json, args.out, args.ascii_armor, args.voice, args.time_res)
    print(json.dumps(report.to_dict(), indent=2))


if __name__ == "__main__":
    main()
