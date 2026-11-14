"""Semantic, lossless-visual PowerPoint packaging for the Streamlit app.

The package preserves slide text, shape geometry, notes, relationships, and
every embedded media asset. It intentionally omits PowerPoint's editing
machinery, embedded fonts, themes, and animation XML. Raster replacements are
accepted only when they decode to exactly the same pixels as their source.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import lzma
import shutil
import struct
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image
from pptx import Presentation


PACKAGE_MAGIC = b"KPS1"
RAW_MAGIC = b"KPR1"
CODEC_MARKERS = {"brotli": b"B", "xz": b"X", "zstd": b"Z", "gzip": b"G"}
MAX_EXPANDED_PPTX_BYTES = 512 * 1024 * 1024
MAX_PPTX_ENTRIES = 10_000


@dataclass(frozen=True)
class SemanticPptxResult:
    package: bytes
    ascii_package: bytes
    codec: str
    original_bytes: int
    packed_bytes: int
    graph_bytes: int
    source_media_bytes: int
    optimized_media_bytes: int
    asset_count: int
    duplicate_assets: int
    slide_count: int
    text_characters: int
    candidate_bytes: dict[str, int]
    source_sha256: str
    package_sha256: str
    fidelity: str

    @property
    def saved_bytes(self) -> int:
        return self.original_bytes - self.packed_bytes

    @property
    def saved_percent(self) -> float:
        return self.saved_bytes / self.original_bytes * 100 if self.original_bytes else 0.0


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_archive(archive: zipfile.ZipFile, input_bytes: int) -> None:
    """Reject encrypted or pathologically expanded upload archives."""
    entries = archive.infolist()
    expanded_bytes = sum(entry.file_size for entry in entries)
    if len(entries) > MAX_PPTX_ENTRIES:
        raise ValueError("PowerPoint package contains too many internal files")
    if expanded_bytes > MAX_EXPANDED_PPTX_BYTES:
        raise ValueError("Expanded PowerPoint package exceeds the 512 MiB safety limit")
    if input_bytes and expanded_bytes > max(64 * 1024 * 1024, input_bytes * 100):
        raise ValueError("PowerPoint package has an unsafe expansion ratio")
    if any(entry.flag_bits & 0x1 for entry in entries):
        raise ValueError("Encrypted PowerPoint packages are not supported")


def _pixel_fingerprint(data: bytes) -> tuple[tuple[int, int], bytes]:
    with Image.open(io.BytesIO(data)) as image:
        rgba = image.convert("RGBA")
        return rgba.size, hashlib.sha256(rgba.tobytes()).digest()


def _pixel_identical(left: bytes, right: bytes) -> bool:
    try:
        return _pixel_fingerprint(left) == _pixel_fingerprint(right)
    except Exception:
        return False


def _lossless_raster_candidate(data: bytes, suffix: str) -> tuple[bytes, str]:
    """Return the smallest candidate that renders to exactly the same pixels."""
    candidates: list[tuple[bytes, str]] = [(data, suffix.lstrip(".") or "bin")]
    try:
        with Image.open(io.BytesIO(data)) as image:
            webp = io.BytesIO()
            image.save(webp, format="WEBP", lossless=True, method=6, exact=True)
            encoded = webp.getvalue()
            if _pixel_identical(data, encoded):
                candidates.append((encoded, "webp"))
    except Exception:
        pass

    if suffix.lower() in {".jpg", ".jpeg"} and shutil.which("jpegtran"):
        try:
            result = subprocess.run(
                ["jpegtran", "-copy", "all", "-optimize", "-progressive"],
                input=data,
                capture_output=True,
                check=True,
                timeout=30,
            )
            if result.stdout and _pixel_identical(data, result.stdout):
                candidates.append((result.stdout, "jpg"))
        except (OSError, subprocess.SubprocessError):
            pass
    return min(candidates, key=lambda item: len(item[0]))


def _walk_shapes(shapes: Iterable[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for shape in shapes:
        record: dict[str, Any] = {
            "type": str(shape.shape_type),
            "name": str(shape.name),
            "x": int(shape.left),
            "y": int(shape.top),
            "w": int(shape.width),
            "h": int(shape.height),
        }
        text = getattr(shape, "text", "")
        if text:
            record["text"] = text
        if getattr(shape, "has_table", False):
            record["table"] = [
                [cell.text for cell in row.cells]
                for row in shape.table.rows
            ]
        try:
            blob = shape.image.blob
            record["media_sha256"] = _sha256(blob)
        except (AttributeError, ValueError):
            pass
        if hasattr(shape, "shapes"):
            record["children"] = _walk_shapes(shape.shapes)
        records.append(record)
    return records


def _slide_xml_text(archive: zipfile.ZipFile, slide_number: int) -> list[str]:
    from xml.etree import ElementTree

    name = f"ppt/slides/slide{slide_number}.xml"
    root = ElementTree.fromstring(archive.read(name))
    return [element.text or "" for element in root.iter() if element.tag.endswith("}t")]


def _notes_xml_text(archive: zipfile.ZipFile, slide_number: int) -> list[str]:
    from xml.etree import ElementTree

    name = f"ppt/notesSlides/notesSlide{slide_number}.xml"
    try:
        root = ElementTree.fromstring(archive.read(name))
    except KeyError:
        return []
    return [element.text or "" for element in root.iter() if element.tag.endswith("}t")]


def _relationship_graph(archive: zipfile.ZipFile, slide_number: int) -> list[dict[str, str]]:
    from xml.etree import ElementTree

    name = f"ppt/slides/_rels/slide{slide_number}.xml.rels"
    try:
        root = ElementTree.fromstring(archive.read(name))
    except KeyError:
        return []
    return [
        {
            "id": element.attrib.get("Id", ""),
            "type": element.attrib.get("Type", "").rsplit("/", 1)[-1],
            "target": element.attrib.get("Target", ""),
            "mode": element.attrib.get("TargetMode", "Internal"),
        }
        for element in root
    ]


def _encode_records(records: dict[str, bytes]) -> bytes:
    output = bytearray(RAW_MAGIC)
    output.extend(struct.pack(">I", len(records)))
    for name, data in sorted(records.items()):
        encoded_name = name.encode("utf-8")
        output.extend(struct.pack(">HQ", len(encoded_name), len(data)))
        output.extend(encoded_name)
        output.extend(data)
    return bytes(output)


def _decode_records(raw: bytes) -> dict[str, bytes]:
    if not raw.startswith(RAW_MAGIC):
        raise ValueError("Invalid semantic PowerPoint record stream")
    offset = len(RAW_MAGIC)
    count = struct.unpack_from(">I", raw, offset)[0]
    offset += 4
    records: dict[str, bytes] = {}
    for _ in range(count):
        name_length, data_length = struct.unpack_from(">HQ", raw, offset)
        offset += 10
        name = raw[offset:offset + name_length].decode("utf-8")
        offset += name_length
        records[name] = raw[offset:offset + data_length]
        offset += data_length
    if offset != len(raw):
        raise ValueError("Trailing bytes in semantic PowerPoint record stream")
    return records


def _compress_candidates(raw: bytes) -> dict[str, bytes]:
    candidates = {
        "gzip-9": gzip.compress(raw, compresslevel=9, mtime=0),
        "xz-9e": lzma.compress(raw, format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME),
    }
    try:
        import brotli

        candidates["brotli-11"] = brotli.compress(raw, quality=11, lgwin=24)
    except ImportError:
        pass
    try:
        import zstandard as zstd

        candidates["zstd-22"] = zstd.ZstdCompressor(level=22).compress(raw)
    except (ImportError, ValueError):
        pass
    return candidates


def _decompress(codec: str, payload: bytes) -> bytes:
    if codec.startswith("gzip"):
        return gzip.decompress(payload)
    if codec.startswith("xz"):
        return lzma.decompress(payload)
    if codec.startswith("brotli"):
        import brotli

        return brotli.decompress(payload)
    if codec.startswith("zstd"):
        import zstandard as zstd

        return zstd.ZstdDecompressor().decompress(payload)
    raise ValueError(f"Unsupported semantic PowerPoint codec: {codec}")


def _codec_family(codec: str) -> str:
    return codec.split("-", 1)[0]


def verify_semantic_pptx(package: bytes) -> dict[str, Any]:
    """Decode a package and verify every record against its manifest hash."""
    records = _package_records(package)
    manifest = json.loads(records["manifest.json"].decode("utf-8"))
    for record in manifest["records"]:
        data = records[record["name"]]
        if len(data) != record["bytes"] or _sha256(data) != record["sha256"]:
            raise ValueError(f"Integrity check failed for {record['name']}")
    return manifest


def _package_records(package: bytes) -> dict[str, bytes]:
    if not package.startswith(PACKAGE_MAGIC) or len(package) < 6:
        raise ValueError("Invalid semantic PowerPoint package")
    marker = package[4:5]
    codec = next((name for name, value in CODEC_MARKERS.items() if value == marker), None)
    if codec is None:
        raise ValueError("Unknown semantic PowerPoint codec")
    raw = _decompress(codec, package[5:])
    return _decode_records(raw)


def read_semantic_pptx_graph(package: bytes) -> dict[str, Any]:
    """Return a verified semantic graph for indexing and AI consumption."""
    verify_semantic_pptx(package)
    return json.loads(_package_records(package)["graph.json"].decode("utf-8"))


def package_pptx_semantic(data: bytes, *, include_media: bool = True) -> SemanticPptxResult:
    """Create the smallest verified semantic package from one PPTX byte string."""
    presentation = Presentation(io.BytesIO(data))
    archive = zipfile.ZipFile(io.BytesIO(data))
    _validate_archive(archive, len(data))
    source_sha256 = _sha256(data)
    assets: dict[str, tuple[bytes, str, int]] = {}
    asset_paths: dict[str, list[str]] = {}
    duplicate_assets = 0

    for info in archive.infolist():
        if not info.filename.startswith("ppt/media/"):
            continue
        source = archive.read(info.filename)
        source_hash = _sha256(source)
        if source_hash in assets:
            duplicate_assets += 1
            asset_paths[source_hash].append(info.filename)
            continue
        suffix = Path(info.filename).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            optimized, extension = _lossless_raster_candidate(source, suffix)
        else:
            optimized, extension = source, suffix.lstrip(".") or "bin"
        assets[source_hash] = (optimized, extension, len(source))
        asset_paths[source_hash] = [info.filename]

    slides: list[dict[str, Any]] = []
    text_characters = 0
    for index, slide in enumerate(presentation.slides, 1):
        text_runs = _slide_xml_text(archive, index)
        notes = _notes_xml_text(archive, index)
        text_characters += sum(len(value) for value in text_runs + notes)
        slide_record = {
            "slide": index,
            "text": text_runs,
            "notes": notes,
            "shapes": _walk_shapes(slide.shapes),
            "relationships": _relationship_graph(archive, index),
            "source_xml_sha256": _sha256(archive.read(f"ppt/slides/slide{index}.xml")),
        }
        semantic_content = json.dumps(
            {
                "text": slide_record["text"],
                "notes": slide_record["notes"],
                "shapes": slide_record["shapes"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        slide_record["content_sha256"] = _sha256(semantic_content)
        slides.append(slide_record)
    archive.close()

    graph = {
        "format": "kp-semantic-pptx-v1",
        "fidelity": "knowledge + pixel-identical embedded media" if include_media else "text knowledge only",
        "source": {"sha256": source_sha256, "bytes": len(data)},
        "canvas": {"width": int(presentation.slide_width), "height": int(presentation.slide_height)},
        "media": [
            {
                "source_paths": asset_paths[source_hash],
                "source_sha256": source_hash,
                "record": f"assets/{source_hash}.{extension}" if include_media else None,
                "source_bytes": source_size,
                "stored_bytes": len(asset) if include_media else 0,
            }
            for source_hash, (asset, extension, source_size) in sorted(assets.items())
        ],
        "slides": slides,
    }
    graph_bytes = json.dumps(graph, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    records: dict[str, bytes] = {"graph.json": graph_bytes}
    if include_media:
        for source_hash, (asset, extension, _source_size) in assets.items():
            records[f"assets/{source_hash}.{extension}"] = asset

    manifest_records = [
        {"name": name, "bytes": len(value), "sha256": _sha256(value)}
        for name, value in sorted(records.items())
    ]
    manifest = {
        "format": "kp-semantic-pptx-v1",
        "fidelity": graph["fidelity"],
        "source_sha256": source_sha256,
        "slide_count": len(slides),
        "text_characters": text_characters,
        "records": manifest_records,
    }
    records["manifest.json"] = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    raw = _encode_records(records)
    candidates = _compress_candidates(raw)
    codec, payload = min(candidates.items(), key=lambda item: len(item[1]))
    family = _codec_family(codec)
    package = PACKAGE_MAGIC + CODEC_MARKERS[family] + payload
    verified = verify_semantic_pptx(package)
    if verified["source_sha256"] != source_sha256:
        raise ValueError("Semantic package source identity check failed")

    return SemanticPptxResult(
        package=package,
        ascii_package=base64.b85encode(package),
        codec=codec,
        original_bytes=len(data),
        packed_bytes=len(package),
        graph_bytes=len(graph_bytes),
        source_media_bytes=sum(source_size for _asset, _extension, source_size in assets.values()),
        optimized_media_bytes=sum(len(asset) for asset, _extension, _source_size in assets.values()) if include_media else 0,
        asset_count=len(assets) if include_media else 0,
        duplicate_assets=duplicate_assets,
        slide_count=len(slides),
        text_characters=text_characters,
        candidate_bytes={name: len(value) + 5 for name, value in candidates.items()},
        source_sha256=source_sha256,
        package_sha256=_sha256(package),
        fidelity=graph["fidelity"],
    )
