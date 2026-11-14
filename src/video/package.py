"""Build a compact, searchable recording package from a local video file."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SHOWINFO_TIME = re.compile(r"pts_time:(?P<time>[-+]?\d+(?:\.\d+)?)")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of *path* without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Required command is not installed: {command[0]}. "
            "Install ffmpeg and make sure it is on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout).strip()
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{details}") from exc


def probe_video(video_path: Path) -> dict[str, Any]:
    """Read duration and size information using ffprobe."""
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(video_path),
        ]
    )
    format_data = json.loads(result.stdout).get("format", {})
    return {
        "duration_s": float(format_data["duration"]),
        "size_bytes": int(format_data.get("size", video_path.stat().st_size)),
    }


def has_audio_stream(video_path: Path) -> bool:
    """Return whether the input contains at least one audio stream."""
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "json",
            str(video_path),
        ]
    )
    return bool(json.loads(result.stdout).get("streams"))


def _frame_times(output: str) -> list[float]:
    return [float(match.group("time")) for match in SHOWINFO_TIME.finditer(output)]


def extract_keyframes(
    video_path: Path,
    output_dir: Path,
    scene_threshold: float = 0.35,
    fallback_interval_s: int = 30,
) -> list[dict[str, Any]]:
    """Extract scene changes plus periodic context frames.

    Scene detection alone is insufficient for long recordings with a static
    camera view: many transcript segments would otherwise point to one frame.
    Periodic frames provide time coverage, while perceptual-hash deduplication
    prevents identical frames from inflating the package.
    """
    if fallback_interval_s <= 0:
        raise ValueError("fallback_interval_s must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_frame in output_dir.glob("f_*.jpg"):
        old_frame.unlink()

    with tempfile.TemporaryDirectory(prefix="recording-frames-") as directory:
        temporary = Path(directory)
        scene_dir = temporary / "scene"
        periodic_dir = temporary / "periodic"
        scene_dir.mkdir()
        periodic_dir.mkdir()

        scene_result = _run([
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", f"select='eq(n,0)+gt(scene,{scene_threshold})',showinfo",
            "-fps_mode", "vfr", "-q:v", "5", str(scene_dir / "s_%05d.jpg"),
        ])
        periodic_result = _run([
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", f"fps=1/{fallback_interval_s},showinfo",
            "-fps_mode", "vfr", "-q:v", "5", str(periodic_dir / "p_%05d.jpg"),
        ])

        def candidates(directory: Path, stderr: str, prefix: str) -> list[tuple[float, Path, int]]:
            paths = sorted(directory.glob(f"{prefix}_*.jpg"))
            times = _frame_times(stderr)
            if len(times) != len(paths):
                times = [index * fallback_interval_s for index in range(len(paths))]
            return [(time, path, 0 if prefix == "s" else 1) for path, time in zip(paths, times)]

        all_candidates = candidates(scene_dir, scene_result.stderr, "s")
        all_candidates += candidates(periodic_dir, periodic_result.stderr, "p")
        all_candidates.sort(key=lambda item: (item[0], item[2]))

        # Keep scene frames in preference to periodic frames at the same time,
        # and remove visually identical frames before copying to the package.
        kept: list[tuple[float, Path]] = []
        hashes = []
        try:
            import imagehash
            from PIL import Image
        except ImportError:
            imagehash = None

        for time, path, _priority in all_candidates:
            current_hash = None
            if imagehash is not None:
                with Image.open(path) as image:
                    current_hash = imagehash.phash(image)
            if current_hash is not None and any(int(current_hash - previous) <= 2 for previous in hashes):
                continue
            if current_hash is not None:
                hashes.append(current_hash)
            kept.append((time, path))

        for index, (_time, path) in enumerate(kept, 1):
            shutil.copyfile(path, output_dir / f"f_{index:05d}.jpg")

    return [
        {
            "id": f"f_{index:03d}",
            "t": round(time, 3),
            "file": f"frames/f_{index:05d}.jpg",
            "phash": None,
            "ocr_text": "",
        }
        for index, (time, _path) in enumerate(kept, 1)
    ]


def transcribe(video_path: Path, model_name: str = "base") -> list[dict[str, Any]]:
    """Transcribe speech with faster-whisper using timestamped segments."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is required for transcription. "
            "Install it with: python -m pip install faster-whisper"
        ) from exc

    model = WhisperModel(model_name)
    segments, _info = model.transcribe(str(video_path), vad_filter=True)
    return [
        {
            "start": float(segment.start),
            "end": float(segment.end),
            "speaker": None,
            "text": segment.text.strip(),
        }
        for segment in segments
    ]


def _frame_for_time(frames: list[dict[str, Any]], time: float) -> str | None:
    if not frames:
        return None
    return min(
        frames,
        key=lambda frame: (abs(frame["t"] - time), frame["t"] > time),
    )["id"]


def build_package(
    video_path: Path,
    output_dir: Path,
    model_name: str = "base",
    transcribe_audio: bool = True,
) -> Path:
    """Create ``package.json`` and frame assets for one recording."""
    video_path = video_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = probe_video(video_path)
    frames = extract_keyframes(video_path, output_dir / "frames")
    if transcribe_audio and has_audio_stream(video_path):
        raw_segments = transcribe(video_path, model_name)
    else:
        raw_segments = []
        if transcribe_audio:
            print("warning: input has no audio stream; skipping transcription")
    segments = [
        {**segment, "frame_id": _frame_for_time(frames, segment["start"])}
        for segment in raw_segments
    ]
    package = {
        "id": f"rec_{video_path.stem}",
        "source": {
            "file": video_path.name,
            "sha256": sha256_file(video_path),
            **metadata,
        },
        "segments": segments,
        "frames": frames,
    }
    package_path = output_dir / "package.json"
    package_path.write_text(json.dumps(package, indent=2), encoding="utf-8")
    return package_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="base")
    parser.add_argument(
        "--skip-transcription",
        action="store_true",
        help="Extract metadata and frames without loading faster-whisper.",
    )
    args = parser.parse_args()
    package_path = build_package(
        args.video,
        args.output,
        model_name=args.model,
        transcribe_audio=not args.skip_transcription,
    )
    print(f"wrote {package_path}")


if __name__ == "__main__":
    main()
