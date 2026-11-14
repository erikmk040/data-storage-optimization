"""Compact, searchable knowledge packages for PDF uploads.

The semantic package preserves extracted text, page order and geometry, links,
source identity, and hashes/metadata for embedded images. It intentionally does
not preserve the original PDF rendering or embedded image pixels; users who
need byte-perfect recovery must select exact-PDF mode in the app.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import lzma
import shutil
from dataclasses import dataclass
from typing import Any

import pymupdf


PACKAGE_MAGIC = b"KPDF1"
CODEC_MARKERS = {"brotli": b"B", "xz": b"X", "zstd": b"Z", "gzip": b"G"}
MAX_PDF_PAGES = 10_000
MAX_EXTRACTED_TEXT_BYTES = 64 * 1024 * 1024
MAX_OCR_PAGES = 200


@dataclass(frozen=True)
class SemanticPdfResult:
    package: bytes
    codec: str
    original_bytes: int
    graph_bytes: int
    page_count: int
    text_characters: int
    ocr_page_count: int
    asset_count: int
    indexed_asset_bytes: int
    duplicate_assets: int
    candidate_bytes: dict[str, int]
    source_sha256: str
    package_sha256: str

    @property
    def packed_bytes(self) -> int:
        return len(self.package)

    @property
    def saved_bytes(self) -> int:
        return self.original_bytes - self.packed_bytes

    @property
    def saved_percent(self) -> float:
        return self.saved_bytes / self.original_bytes * 100 if self.original_bytes else 0.0


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _codec_family(codec: str) -> str:
    return codec.split("-", 1)[0]


def _decompress(family: str, payload: bytes) -> bytes:
    if family == "gzip":
        return gzip.decompress(payload)
    if family == "xz":
        return lzma.decompress(payload)
    if family == "brotli":
        import brotli

        return brotli.decompress(payload)
    if family == "zstd":
        import zstandard as zstd

        return zstd.ZstdDecompressor().decompress(payload, max_output_size=MAX_EXTRACTED_TEXT_BYTES)
    raise ValueError(f"Unsupported semantic PDF codec: {family}")


def _ocr_page(page: pymupdf.Page) -> str:
    """Return optional OCR text for sparse pages without making OCR mandatory."""
    if not shutil.which("tesseract"):
        return ""
    try:
        import pytesseract
        from PIL import Image

        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(1.5, 1.5), colorspace=pymupdf.csRGB, alpha=False
        )
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        return pytesseract.image_to_string(image).strip()
    except Exception:
        return ""


def read_semantic_pdf_graph(package: bytes) -> dict[str, Any]:
    """Decode and validate a semantic PDF graph."""
    if not package.startswith(PACKAGE_MAGIC) or len(package) <= len(PACKAGE_MAGIC):
        raise ValueError("Invalid semantic PDF package")
    marker = package[len(PACKAGE_MAGIC):len(PACKAGE_MAGIC) + 1]
    family = next((name for name, value in CODEC_MARKERS.items() if value == marker), None)
    if family is None:
        raise ValueError("Unknown semantic PDF codec")
    raw = _decompress(family, package[len(PACKAGE_MAGIC) + 1:])
    if len(raw) > MAX_EXTRACTED_TEXT_BYTES:
        raise ValueError("Expanded semantic PDF graph exceeds the safety limit")
    graph = json.loads(raw.decode("utf-8"))
    if graph.get("format") != "kp-semantic-pdf-v1":
        raise ValueError("Unsupported semantic PDF graph version")
    expected = graph.get("graph_sha256")
    unsigned = dict(graph)
    unsigned.pop("graph_sha256", None)
    canonical = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if expected != _sha256(canonical):
        raise ValueError("Semantic PDF graph integrity check failed")
    return graph


def package_pdf_semantic(data: bytes) -> SemanticPdfResult:
    """Extract and compress the searchable knowledge layer of a PDF."""
    source_sha256 = _sha256(data)
    pages: list[dict[str, Any]] = []
    assets: dict[str, dict[str, Any]] = {}
    asset_occurrences = 0
    text_characters = 0
    ocr_page_count = 0
    ocr_attempts = 0

    with pymupdf.open(stream=data, filetype="pdf") as document:
        if not document.is_pdf:
            raise ValueError("Uploaded content is not a PDF document")
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported")
        if len(document) > MAX_PDF_PAGES:
            raise ValueError(f"PDF exceeds the {MAX_PDF_PAGES:,}-page safety limit")

        metadata = {
            key: str(value)
            for key, value in (document.metadata or {}).items()
            if value and key in {"title", "author", "subject", "keywords", "creator", "producer"}
        }
        for number, page in enumerate(document, start=1):
            text = page.get_text("text", sort=True)
            ocr_text = ""
            if len(text.strip()) < 100 and ocr_attempts < MAX_OCR_PAGES:
                ocr_attempts += 1
                candidate = _ocr_page(page)
                if len(candidate) >= 5 and (
                    not text.strip() or len(candidate) > len(text.strip()) + 50
                ):
                    ocr_text = candidate
                    ocr_page_count += 1
            searchable_text = text + (("\n" + ocr_text) if ocr_text else "")
            text_characters += len(searchable_text)
            if text_characters * 4 > MAX_EXTRACTED_TEXT_BYTES:
                raise ValueError("Extracted PDF text exceeds the safety limit")

            image_hashes: list[str] = []
            for image_info in page.get_images(full=True):
                xref = int(image_info[0])
                try:
                    extracted = document.extract_image(xref)
                    image_bytes = extracted["image"]
                except (KeyError, RuntimeError, ValueError):
                    continue
                image_hash = _sha256(image_bytes)
                image_hashes.append(image_hash)
                asset_occurrences += 1
                if image_hash not in assets:
                    assets[image_hash] = {
                        "sha256": image_hash,
                        "source_bytes": len(image_bytes),
                        "width": int(extracted.get("width", 0)),
                        "height": int(extracted.get("height", 0)),
                        "extension": str(extracted.get("ext", "bin")),
                    }

            links = []
            for link in page.get_links():
                target = link.get("uri")
                target_page = link.get("page")
                if target:
                    links.append({"uri": str(target)})
                elif isinstance(target_page, int) and target_page >= 0:
                    links.append({"page": target_page + 1})

            pages.append(
                {
                    "page": number,
                    "width": round(float(page.rect.width), 2),
                    "height": round(float(page.rect.height), 2),
                    "rotation": int(page.rotation),
                    "text": text,
                    "ocr_text": ocr_text,
                    "text_sha256": _sha256(searchable_text.encode("utf-8")),
                    "image_sha256s": image_hashes,
                    "links": links,
                }
            )

    graph: dict[str, Any] = {
        "format": "kp-semantic-pdf-v1",
        "fidelity": "searchable stored text plus OCR enrichment; original rendering and image pixels omitted",
        "source": {"sha256": source_sha256, "bytes": len(data)},
        "metadata": metadata,
        "pages": pages,
        "assets": [assets[key] for key in sorted(assets)],
    }
    canonical = json.dumps(
        graph, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    graph["graph_sha256"] = _sha256(canonical)
    raw = json.dumps(
        graph, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    candidates = _compress_candidates(raw)
    codec, payload = min(candidates.items(), key=lambda item: len(item[1]))
    family = _codec_family(codec)
    package = PACKAGE_MAGIC + CODEC_MARKERS[family] + payload

    verified = read_semantic_pdf_graph(package)
    if verified["source"]["sha256"] != source_sha256:
        raise ValueError("Semantic PDF source identity check failed")

    return SemanticPdfResult(
        package=package,
        codec=codec,
        original_bytes=len(data),
        graph_bytes=len(raw),
        page_count=len(pages),
        text_characters=text_characters,
        ocr_page_count=ocr_page_count,
        asset_count=len(assets),
        indexed_asset_bytes=sum(asset["source_bytes"] for asset in assets.values()),
        duplicate_assets=max(asset_occurrences - len(assets), 0),
        candidate_bytes={name: len(value) + len(PACKAGE_MAGIC) + 1 for name, value in candidates.items()},
        source_sha256=source_sha256,
        package_sha256=_sha256(package),
    )
