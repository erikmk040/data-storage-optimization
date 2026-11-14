import json
from pathlib import Path
from PIL import Image, ImageDraw

def make(base=Path("data/sample/rec_mock")):
    (base / "frames").mkdir(parents=True, exist_ok=True)
    slides = [("Agenda", 0.0), ("Storage costs", 30.0), ("Duplicate detection", 75.0), ("Winner", 105.0)]
    frames = []
    for i, (title, t) in enumerate(slides, 1):
        img = Image.new("RGB", (960, 540), (30, 50, 120))
        ImageDraw.Draw(img).text((40, 40), f"Slide {i}: {title}", fill="white")
        img.save(base / "frames" / f"f_{i:03d}.webp")
        frames.append({"id": f"f_{i:03d}", "t": t, "file": f"frames/f_{i:03d}.webp",
                       "phash": f"mock{i}", "ocr_text": title,
                       "slide_ref": {"doc_id": "DOC-123", "slide_no": i, "slide_hash": f"h{i}"}})
    segs = [
        {"start": 2, "end": 10, "speaker": "SPEAKER_01", "text": "Welcome everyone, today we talk about storage."},
        {"start": 31, "end": 40, "speaker": "SPEAKER_01", "text": "As you see here, storage costs grow every year."},
        {"start": 76, "end": 90, "speaker": "SPEAKER_02", "text": "Duplicate files are created when people download and re-upload documents."},
        {"start": 106, "end": 114, "speaker": "SPEAKER_02", "text": "The winner is announced after the technical category review."},
    ]
    pkg = {"id": "rec_mock", "source": {"file": "mock.mp4", "sha256": "x", "duration_s": 120, "size_bytes": 10**9},
           "segments": segs, "frames": frames}
    (base / "package.json").write_text(json.dumps(pkg, indent=2))
    print("wrote", base / "package.json")

if __name__ == "__main__":
    make()
