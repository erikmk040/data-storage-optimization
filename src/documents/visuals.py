"""Versioned full-slide rendering, perceptual hashes, and measured calibration."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from importlib.metadata import version
from pathlib import Path

import imagehash
import pymupdf
from PIL import Image, ImageOps, ImageStat

from .file_hash import hash_file
from .registry import utc_now


def profile_definition() -> dict:
    """Only identical profile IDs are compatible in this first implementation."""
    return {
        "renderer": "pymupdf", "renderer_version": pymupdf.__version__,
        "render_max_dimension": 1280, "colorspace": "RGB", "background": "white",
        "preprocessing": "EXIF transpose; contain on white 1280x960 canvas; LANCZOS; v1",
        "hash": "imagehash.phash", "hash_size": 8, "highfreq_factor": 4,
        "imagehash_version": version("imagehash"), "pillow_version": version("Pillow"),
        "numpy_version": version("numpy"), "scipy_version": version("scipy"),
        "low_information": "unpadded source grayscale standard deviation < 1.0 is excluded",
    }


def profile_identity(definition: dict) -> str:
    return "profile:" + hashlib.sha256(
        json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _opaque_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGBA")
    white = Image.new("RGBA", image.size, "white")
    white.alpha_composite(image)
    return white.convert("RGB")


def canonical_image(image: Image.Image) -> Image.Image:
    scaled = ImageOps.contain(_opaque_image(image), (1280, 960), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (1280, 960), "white")
    canvas.paste(scaled, ((1280 - scaled.width) // 2, (960 - scaled.height) // 2))
    return canvas


def image_fingerprint(image: Image.Image) -> dict:
    opaque = _opaque_image(image)
    canvas = canonical_image(opaque)
    informative = ImageStat.Stat(opaque.convert("L")).stddev[0] >= 1.0
    return {
        "phash": str(imagehash.phash(canvas, hash_size=8, highfreq_factor=4)) if informative else None,
        "image_sha256": hashlib.sha256(canvas.tobytes()).hexdigest(),
    }


def image_file_fingerprint(path: str | Path) -> dict:
    with Image.open(path) as image:
        return image_fingerprint(image)


def hamming(first: str, second: str) -> int:
    if any(len(value) != 16 or any(c not in "0123456789abcdef" for c in value)
           for value in (first, second)):
        raise ValueError("Expected two lowercase 64-bit perceptual hashes")
    return (int(first, 16) ^ int(second, 16)).bit_count()


def render_pdf(path: Path) -> list[dict]:
    with pymupdf.open(path) as document:
        if not document.is_pdf:
            raise ValueError("Rendering source must be a PDF")
        result = []
        for page in document:
            scale = 1280 / max(page.rect.width, page.rect.height)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale),
                                     colorspace=pymupdf.csRGB, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            result.append(image_fingerprint(image))
        return result


def libreoffice_executable() -> str | None:
    configured = os.environ.get("ROLE_B_SOFFICE")
    if configured:
        if not Path(configured).is_file():
            raise ValueError("ROLE_B_SOFFICE does not identify an executable file")
        return configured
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    return executable or (str(mac) if mac.is_file() else None)


def render_source(snapshot: Path, slide_count: int, *, mode: str = "auto",
                  rendered_pdf: Path | None = None, render_evidence: str | None = None) -> dict:
    """Render PDFs directly and PPTX through isolated LibreOffice or an attested PDF.

    Auto mode permits text-only PPTX import if LibreOffice is not installed.
    Explicit/required rendering failures abort the entire import.
    """
    if mode not in ("auto", "required", "none"):
        raise ValueError("Render mode must be auto, required, or none")
    if mode == "none":
        if rendered_pdf is not None:
            raise ValueError("Cannot supply rendered PDF with rendering disabled")
        return {"slides": [], "warnings": ["Image rendering explicitly disabled"]}
    definition = profile_definition()
    profile = profile_identity(definition)
    warnings = []
    with tempfile.TemporaryDirectory(prefix="slide-render-") as directory:
        directory = Path(directory)
        provenance = {"source_sha256": hash_file(snapshot)}
        if snapshot.suffix == ".pdf":
            if rendered_pdf is not None:
                raise ValueError("A rendered PDF sidecar is only valid for PPTX inputs")
            pdf = snapshot
            provenance["conversion"] = "none"
        elif rendered_pdf is not None:
            if not render_evidence or not render_evidence.strip():
                raise ValueError("A rendered PPTX sidecar requires --render-evidence confirming source/order")
            pdf = directory / "attested.pdf"
            shutil.copyfile(rendered_pdf, pdf)
            provenance.update(conversion="attested PDF sidecar", render_evidence=render_evidence)
        else:
            executable = libreoffice_executable()
            if executable is None:
                if mode == "required":
                    raise ValueError("PPTX rendering requires LibreOffice or an attested --rendered-pdf")
                warnings.append("LibreOffice unavailable: PPTX text imported; image hashes not computed in this import")
                return {"slides": [], "warnings": warnings}
            result = subprocess.run(
                [executable, "--headless", "-env:UserInstallation=" + (directory / "profile").as_uri(),
                 "--convert-to", 'pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}',
                 "--outdir", str(directory), str(snapshot)],
                capture_output=True, text=True, timeout=90, check=False,
            )
            pdf = directory / (snapshot.stem + ".pdf")
            if result.returncode != 0 or not pdf.is_file():
                raise ValueError("LibreOffice conversion failed: " + result.stderr.strip())
            renderer_version = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=10, check=True
            ).stdout.strip()
            provenance.update(conversion="LibreOffice", converter_version=renderer_version)
        slides = render_pdf(pdf)
        if len(slides) != slide_count:
            raise ValueError("Rendered page count does not match source slides; import aborted")
        provenance["rendered_pdf_sha256"] = hash_file(pdf)
    return {"slides": slides, "profile_id": profile, "definition": definition,
            "provenance": provenance, "warnings": warnings}


def calibrate(registry, profile_id: str, pairs: list[dict]) -> dict:
    """Choose a measured threshold only when labeled positives/negatives separate."""
    profile = registry.connection.execute(
        "SELECT definition FROM phash_profiles WHERE profile_id=?", (profile_id,)
    ).fetchone()
    if profile is None or json.loads(profile[0]) != profile_definition():
        raise ValueError("Calibration requires the current registered rendering/hashing profile")
    if not isinstance(pairs, list) or any(not isinstance(pair, dict) for pair in pairs):
        raise ValueError("Calibration input must be a JSON array of labeled image pairs")
    measurements = []
    for pair in pairs:
        if type(pair.get("same_slide")) is not bool:
            raise ValueError("Calibration pairs require boolean same_slide labels")
        left, right = Path(pair["left"]), Path(pair["right"])
        first, second = image_file_fingerprint(left), image_file_fingerprint(right)
        if first["phash"] is None or second["phash"] is None:
            raise ValueError("Low-information images cannot calibrate slide matching")
        measurements.append({
            "left_sha256": hash_file(left), "right_sha256": hash_file(right),
            "same_slide": pair["same_slide"], "distance": hamming(first["phash"], second["phash"]),
        })
    positives = [m["distance"] for m in measurements if m["same_slide"]]
    negatives = [m["distance"] for m in measurements if not m["same_slide"]]
    if not positives or not negatives or max(positives) >= min(negatives):
        raise ValueError("Calibration needs separable positive and negative examples; no threshold saved")
    evidence = {"profile_id": profile_id, "max_distance": max(positives),
                "min_negative_distance": min(negatives), "measurements": measurements}
    calibration_id = "calibration:" + hashlib.sha256(
        json.dumps(evidence, sort_keys=True).encode()
    ).hexdigest()
    evidence.update(calibration_id=calibration_id, calibrated_at=utc_now())
    with registry.connection:
        registry.connection.execute(
            "INSERT OR IGNORE INTO visual_calibrations VALUES (?,?,?,?)",
            (calibration_id, profile_id, max(positives), json.dumps(evidence, sort_keys=True)),
        )
    return evidence


def calibration(registry, calibration_id: str | None) -> dict | None:
    if calibration_id is None:
        return None
    row = registry.connection.execute(
        "SELECT evidence FROM visual_calibrations WHERE calibration_id=?", (calibration_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Unknown visual calibration")
    return json.loads(row[0])
