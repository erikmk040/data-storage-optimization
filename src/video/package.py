"""Build a compact, searchable recording package from a local video file."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
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


def _frame_times(output: str) -> list[float]:
    return [float(match.group("time")) for match in SHOWINFO_TIME.finditer(output)]


def extract_keyframes(
    video_path: Path,
    output_dir: Path,
    scene_threshold: float = 0.35,
    fallback_interval_s: int = 30,
) -> list[dict[str, Any]]:
    """Extract scene-change frames and return contract-compatible frame records.

    If a video has no detectable scene changes, a regular fallback interval keeps
    the package useful for recordings with a mostly static screen.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    # Some Homebrew FFmpeg builds do not include the WebP encoder. JPEG is
    # widely available and remains compatible with the recording contract.
    pattern = output_dir / "f_%05d.jpg"
    result = _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"select='eq(n,0)+gt(scene,{scene_threshold})',showinfo",
            "-fps_mode",
            "vfr",
            "-q:v",
            "5",
            str(pattern),
        ]
    )
    times = _frame_times(result.stderr)
    frame_paths = sorted(output_dir.glob("f_*.jpg"))

    if not frame_paths:
        result = _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vf",
                f"fps=1/{fallback_interval_s}",
                "-q:v",
                "5",
                str(pattern),
            ]
        )
        del result
        frame_paths = sorted(output_dir.glob("f_*.jpg"))
        times = [index * fallback_interval_s for index in range(len(frame_paths))]

    if len(times) != len(frame_paths):
        # ffmpeg versions can omit showinfo lines; preserve the frames with a
        # deterministic approximation rather than producing invalid records.
        interval = fallback_interval_s
        times = [index * interval for index in range(len(frame_paths))]

    return [
        {
            "id": f"f_{index:03d}",
            "t": round(time, 3),
            "file": f"frames/{path.name}",
            "phash": None,
            "ocr_text": "",
        }
        for index, (path, time) in enumerate(zip(frame_paths, times), 1)
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
    candidates = [frame for frame in frames if frame["t"] <= time]
    if not candidates:
        return frames[0]["id"] if frames else None
    return max(candidates, key=lambda frame: frame["t"])["id"]


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
    raw_segments = transcribe(video_path, model_name) if transcribe_audio else []
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
