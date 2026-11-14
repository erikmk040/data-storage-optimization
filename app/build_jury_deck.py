"""Build a human, story-led three-minute Ericsson jury presentation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from app.evidence import load_benchmark_evidence
from app.integration import build_exact_artifact


OUT = Path(__file__).parent / "assets" / "Ericsson_Knowledge_Compression_3min.pptx"

PAPER = RGBColor(247, 244, 237)
INK = RGBColor(20, 38, 61)
BLUE = RGBColor(0, 130, 240)
CYAN = RGBColor(0, 169, 224)
GREEN = RGBColor(22, 163, 74)
YELLOW = RGBColor(234, 179, 8)
CORAL = RGBColor(225, 95, 80)
WHITE = RGBColor(255, 255, 255)
MUTED = RGBColor(91, 108, 127)
LINE = RGBColor(207, 211, 211)
SOFT_BLUE = RGBColor(226, 239, 250)
SOFT_GREEN = RGBColor(226, 242, 231)
SOFT_YELLOW = RGBColor(250, 241, 207)
SOFT_CORAL = RGBColor(249, 229, 224)


def rect(slide, x, y, w, h, fill, *, line=None, rounded=True):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = line or fill
    return shape


def text(
    slide, value, x, y, w, h, *, size=20, color=INK, bold=False,
    align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP, margin=0.03,
):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(margin)
    frame.margin_top = frame.margin_bottom = Inches(margin)
    frame.vertical_anchor = valign
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    paragraph.space_after = Pt(0)
    run = paragraph.add_run()
    run.text = value
    run.font.name = "Arial"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return box


def rich(slide, parts, x, y, w, h, *, size=20, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(0.03)
    frame.margin_top = frame.margin_bottom = Inches(0.03)
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    for value, color, bold in parts:
        run = paragraph.add_run()
        run.text = value
        run.font.name = "Arial"
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
    return box


def arrow(slide, x, y, w=0.45, color=CYAN):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(0.25)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.color.rgb = color


def blank(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = PAPER
    return slide


def heading(slide, title, label, number, timing):
    text(slide, label.upper(), 0.65, 0.32, 7.4, 0.26, size=10, color=BLUE, bold=True)
    text(slide, title, 0.65, 0.68, 11.9, 0.65, size=29, bold=True)
    text(slide, f"{number}/6  ·  {timing}", 11.35, 0.36, 1.25, 0.22, size=9, color=MUTED, align=PP_ALIGN.RIGHT)


def footer(slide, message="Ericsson Knowledge Compression · jury demo"):
    text(slide, message, 0.65, 7.19, 8.0, 0.17, size=8, color=MUTED)
    rect(slide, 11.94, 7.21, 0.7, 0.05, BLUE, rounded=False)


def notes(slide, value):
    slide.notes_slide.notes_text_frame.text = value


def build() -> Path:
    evidence = load_benchmark_evidence(verify_local_files=True)
    source = evidence["source"]
    package = evidence["package"]
    content = evidence["content"]
    source_mb = f"{source['bytes'] / 1_000_000:.1f} MB"
    package_mb = f"{package['bytes'] / 1_000_000:.2f} MB"
    reduction = f"{evidence['saved_percent']:.2f}%"
    verification = (
        "Package re-hashed; source metadata matched"
        if evidence["local_files_verified"]
        else "Evidence manifest verified; source is not distributed"
    )
    exact_control_path = Path(__file__).resolve().parents[1] / "Challenge_Ericsson.docx"
    exact_control = build_exact_artifact(exact_control_path.read_bytes())
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    slide = blank(prs)
    text(slide, "ERICSSON DATA STORAGE CHALLENGE", 0.7, 0.48, 6.5, 0.3, size=10, color=BLUE, bold=True)
    text(slide, "When storage is full,\nuseful knowledge disappears.", 0.7, 1.0, 7.4, 1.25, size=35, bold=True)
    rect(slide, 0.72, 2.65, 7.0, 1.55, WHITE, line=LINE)
    text(slide, "“Highly informative content is often deleted\ndue to a lack of storage capacity.”", 1.02, 2.97, 6.35, 0.76, size=21, bold=True)
    text(slide, "— Ericsson challenge brief", 1.05, 3.78, 3.0, 0.22, size=10, color=MUTED)
    story = [
        ("STORAGE OWNERS", "Heavy copies grow", SOFT_BLUE, BLUE),
        ("KNOWLEDGE WORKERS", "Answers stay hidden", SOFT_YELLOW, YELLOW),
        ("OFFBOARDING TEAMS", "Deletion feels unsafe", SOFT_CORAL, CORAL),
        ("AI / DATA TEAMS", "Useful data stays inactive", SOFT_GREEN, GREEN),
    ]
    for index, (top, bottom, fill, color) in enumerate(story):
        y = 1.05 + index * 1.08
        rect(slide, 8.45, y, 4.15, 0.84, fill, line=fill)
        text(slide, top, 8.76, y + 0.11, 3.45, 0.22, size=9, color=MUTED, bold=True)
        text(slide, bottom, 8.76, y + 0.39, 3.45, 0.27, size=15, color=color, bold=True)
    text(slide, "We asked a simple question:", 0.75, 5.13, 3.4, 0.3, size=15, color=MUTED)
    text(slide, "Can we keep what matters without keeping every byte?", 0.75, 5.52, 10.7, 0.55, size=28, color=BLUE, bold=True)
    footer(slide)
    notes(slide, "0:00–0:30\nThe brief creates a real tension for four users. Storage owners see large files and copies grow. Knowledge workers cannot find one answer without replaying content. Offboarding teams cannot safely delete a file unless another accessible copy is proven. AI and data teams cannot activate information that remains trapped in media. The causes are full-fidelity media, duplication and information that is not indexed. Can we keep what matters without keeping every byte?")

    slide = blank(prs)
    heading(slide, "We tried it on a real file. This is what happened.", "Our measured proof", 2, "0:30–1:00")
    rect(slide, 0.7, 1.55, 7.7, 4.9, WHITE, line=LINE)
    text(slide, "REAL VIDEO · JURY AND PRIZES.MP4", 1.02, 1.86, 3.7, 0.26, size=10, color=BLUE, bold=True)
    text(slide, source_mb, 1.02, 2.32, 2.55, 0.62, size=37, bold=True)
    text(slide, f"{source['bytes']:,} source bytes", 1.05, 2.94, 2.35, 0.23, size=11, color=MUTED)
    arrow(slide, 3.75, 2.52, 0.72)
    text(slide, package_mb, 4.72, 2.32, 2.8, 0.62, size=37, color=GREEN, bold=True)
    text(slide, "searchable knowledge package", 4.75, 2.94, 2.8, 0.23, size=11, color=MUTED)
    text(slide, reduction, 1.02, 3.68, 3.25, 0.72, size=48, color=GREEN, bold=True)
    text(slide, "less storage", 1.07, 4.42, 2.5, 0.3, size=16, bold=True)
    rect(slide, 4.64, 3.66, 3.15, 1.18, SOFT_GREEN, line=SOFT_GREEN)
    text(slide, "Still searchable", 4.94, 3.9, 2.55, 0.3, size=18, color=GREEN, bold=True)
    text(slide, f"{content['transcript_segments']} transcript segments · {content['representative_frames']} frames", 4.94, 4.28, 2.55, 0.23, size=11, color=MUTED)
    text(slide, f"Local video evidence · {verification}.", 1.03, 5.34, 6.8, 0.26, size=11, color=MUTED)
    text(slide, f"Clean-clone exact control: Challenge_Ericsson.docx · {exact_control.original_bytes:,} → {exact_control.package_bytes:,} B · {exact_control.saved_percent:.2f}% · reversible", 1.03, 5.68, 6.95, 0.44, size=10, color=MUTED)
    rect(slide, 8.72, 1.55, 3.92, 4.9, SOFT_YELLOW, line=SOFT_YELLOW)
    text(slide, "What this number means", 9.03, 1.9, 3.25, 0.35, size=17, bold=True)
    text(slide, "We kept", 9.03, 2.55, 1.25, 0.26, size=11, color=GREEN, bold=True)
    text(slide, "Transcript, timing and\nrepresentative visuals", 9.03, 2.85, 3.1, 0.78, size=17, bold=True)
    text(slide, "We did not keep", 9.03, 3.93, 1.65, 0.26, size=11, color=CORAL, bold=True)
    text(slide, "Original audio and discarded motion", 9.03, 4.25, 3.1, 0.55, size=17, bold=True)
    text(slide, "Need every byte? Exact mode is reversible, but cannot deliver this semantic reduction.", 9.03, 5.2, 3.1, 0.72, size=12, color=MUTED)
    footer(slide)
    notes(slide, f"0:30–1:00\nWe tested the idea on a real six-minute video. The {source['bytes']:,}-byte source became a {package['bytes']:,}-byte knowledge package: {reduction} less storage. It still contains {content['transcript_segments']} searchable transcript segments and {content['representative_frames']} representative frames. This is local benchmark evidence; the source is not distributed in the repository. As a clean-clone control, exact mode reduces the tracked challenge document from {exact_control.original_bytes:,} to {exact_control.package_bytes:,} bytes, or {exact_control.saved_percent:.2f} percent, and restores it byte-for-byte. Semantic mode does not preserve original audio or every motion frame.")

    slide = blank(prs)
    heading(slide, "Behind the number is a simple idea", "What we built", 3, "1:00–1:30")
    text(slide, "Not every byte has the same value.", 0.7, 1.44, 7.5, 0.42, size=20, color=MUTED)
    stages = [
        ("1", "Read", "Video, PDF or\nPowerPoint", SOFT_BLUE, BLUE),
        ("2", "Keep", "Words, timing and\nuseful visuals", SOFT_GREEN, GREEN),
        ("3", "Avoid copies", "Hashes point to one\nsource of truth", SOFT_YELLOW, YELLOW),
        ("4", "Make useful", "One small package\nfor search and AI", SOFT_BLUE, BLUE),
    ]
    for index, (number, title, detail, fill, color) in enumerate(stages):
        x = 0.7 + index * 3.12
        rect(slide, x, 2.13, 2.62, 3.15, WHITE, line=LINE)
        rect(slide, x + 0.24, 2.39, 0.48, 0.48, fill, line=fill)
        text(slide, number, x + 0.24, 2.44, 0.48, 0.26, size=13, color=color, bold=True, align=PP_ALIGN.CENTER)
        text(slide, title, x + 0.24, 3.13, 2.1, 0.4, size=20, bold=True)
        text(slide, detail, x + 0.24, 3.83, 2.15, 0.75, size=15, color=MUTED)
        if index < 3:
            arrow(slide, x + 2.68, 3.48, 0.33)
    rect(slide, 0.7, 5.5, 12.0, 0.95, INK, line=INK)
    text(slide, "Our contribution: storage reduction + searchable, AI-ready evidence", 1.03, 5.68, 11.3, 0.28, size=16, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    text(slide, "Built: KP pipeline, dedup/search, API and demo  ·  Reused: standard codecs, FFmpeg, Whisper and LibreOffice", 1.03, 6.08, 11.3, 0.18, size=8, color=LINE, align=PP_ALIGN.CENTER)
    footer(slide)
    notes(slide, "1:00–1:30\nNot every byte has the same value. We preserve words, timing and useful visuals, avoid duplicate information and create one package for search and AI. Our innovation is not an exotic codec. It is the combination of semantic reduction, content identity, activation and deletion evidence. We built the package pipeline, policies, search, API and demo; we reused established codecs and extraction tools.")

    slide = blank(prs)
    heading(slide, "The website is the demo — this is the product", "How it fits Ericsson", 4, "1:30–1:55")
    text(slide, "Ericsson systems", 0.78, 1.55, 2.4, 0.3, size=13, color=MUTED, bold=True)
    text(slide, "Our service", 5.04, 1.55, 2.4, 0.3, size=13, color=MUTED, bold=True)
    text(slide, "What Ericsson already uses", 9.05, 1.55, 3.1, 0.3, size=13, color=MUTED, bold=True)
    groups = [
        (0.7, 2.0, 2.7, ["Ericsson Play", "SharePoint / OneDrive", "Offboarding flow"], SOFT_BLUE, BLUE),
        (4.45, 2.0, 3.25, ["Distill + deduplicate", "REST / OpenAPI", "Evidence + search"], SOFT_GREEN, GREEN),
        (8.72, 2.0, 3.9, ["Object storage", "Enterprise search", "AI / RAG consumers"], SOFT_YELLOW, YELLOW),
    ]
    for x, y, w, items, fill, color in groups:
        rect(slide, x, y, w, 3.35, WHITE, line=LINE)
        for row, item in enumerate(items):
            rect(slide, x + 0.25, y + 0.42 + row * 0.85, w - 0.5, 0.56, fill, line=fill)
            text(slide, item, x + 0.45, y + 0.56 + row * 0.85, w - 0.9, 0.26, size=14, color=color, bold=True)
    arrow(slide, 3.58, 3.48, 0.58)
    arrow(slide, 7.88, 3.48, 0.58)
    rich(slide, [("Demo today: ", BLUE, True), ("Streamlit", INK, True), ("   Production path: ", MUTED, False), ("API beside existing systems", INK, True)], 0.75, 5.75, 8.9, 0.35, size=15)
    text(slide, "Still needed: Ericsson authentication, governance and product connectors", 7.4, 6.2, 5.11, 0.4, size=12, color=CORAL, bold=True, align=PP_ALIGN.RIGHT)
    footer(slide)
    notes(slide, "1:30–1:55\nThe website is only the demo client. The product is the Python core and versioned REST API behind it. It can sit between Ericsson Play, SharePoint, OneDrive or offboarding and existing storage, search and AI systems. The API and streamed video path work today. Ericsson authentication, product connectors and governed deletion approval come next; the prototype never deletes automatically.")

    slide = blank(prs)
    heading(slide, "Let us show it", "Live demo", 5, "1:55–2:30")
    text(slide, "One file. Four things to watch.", 0.7, 1.4, 7.2, 0.4, size=20, color=MUTED)
    demo_steps = [
        ("1", "Open", "Demo or evidence slide"),
        ("2", "Verify", f"{source_mb} → {package_mb}"),
        ("3", "Check", f"{reduction} less storage"),
        ("4", "Search", '“winner” + frames'),
    ]
    for index, (number, title, detail) in enumerate(demo_steps):
        x = 0.7 + index * 2.55
        rect(slide, x, 2.08, 2.12, 2.55, WHITE, line=LINE)
        fill = SOFT_BLUE if index < 2 else SOFT_GREEN
        color = BLUE if index < 2 else GREEN
        rect(slide, x + 0.22, 2.32, 0.48, 0.48, fill, line=fill)
        text(slide, number, x + 0.22, 2.37, 0.48, 0.26, size=13, color=color, bold=True, align=PP_ALIGN.CENTER)
        text(slide, title, x + 0.22, 3.04, 1.65, 0.4, size=20, bold=True)
        text(slide, detail, x + 0.22, 3.68, 1.65, 0.45, size=13, color=MUTED)
        if index < 3:
            arrow(slide, x + 2.16, 3.12, 0.3)
    button = rect(slide, 10.95, 2.08, 1.72, 2.55, BLUE, line=BLUE)
    label = text(slide, "OPEN\nDEMO", 11.13, 2.85, 1.36, 0.76, size=20, color=WHITE, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    for shape in (button, label):
        shape.click_action.hyperlink.address = "http://localhost:8511"
    rect(slide, 0.7, 5.12, 11.98, 0.92, SOFT_YELLOW, line=SOFT_YELLOW)
    text(slide, "If the live demo fails", 1.0, 5.34, 2.1, 0.28, size=12, color=YELLOW, bold=True)
    text(slide, f"Evidence backup: {source_mb} → {package_mb} · {reduction} less · search returns visual context", 3.0, 5.3, 8.9, 0.35, size=14, bold=True)
    text(slide, "Automated release tests cover API metadata, exact restoration and semantic search.", 0.73, 6.42, 11.3, 0.35, size=14, color=MUTED)
    footer(slide)
    notes(slide, f"1:55–2:30 — LIVE DEMO\nIf the local prepared artifact is available, show the verified result: {source_mb} to {package_mb}, or {reduction} less. Otherwise say clearly that the clean demo uses deterministic mock search and show this evidence slide. Search for winner and show transcript plus visual context. Do not transcribe on stage.")

    slide = blank(prs)
    heading(slide, "What we know — and what we still need to prove", "A credible next step", 6, "2:30–3:00")
    rect(slide, 0.7, 1.55, 5.82, 4.5, WHITE, line=LINE)
    text(slide, "We know", 1.03, 1.9, 2.3, 0.4, size=23, color=GREEN, bold=True)
    known = [
        f"{reduction} local video benchmark",
        "Search returns transcript + frames",
        "API and automated release tests pass",
    ]
    for index, item in enumerate(known):
        y = 2.65 + index * 0.85
        rect(slide, 1.04, y, 0.38, 0.38, SOFT_GREEN, line=SOFT_GREEN)
        text(slide, "✓", 1.04, y + 0.02, 0.38, 0.22, size=12, color=GREEN, bold=True, align=PP_ALIGN.CENTER)
        text(slide, item, 1.62, y - 0.01, 4.35, 0.45, size=15, bold=True)
    rect(slide, 6.82, 1.55, 5.82, 4.5, WHITE, line=LINE)
    text(slide, "We need to prove", 7.15, 1.9, 3.3, 0.4, size=23, color=CORAL, bold=True)
    open_items = [
        "Fidelity on representative Ericsson data",
        "Authentication and product connectors",
        "Governed deletion and operations at scale",
    ]
    for index, item in enumerate(open_items):
        y = 2.65 + index * 0.85
        rect(slide, 7.16, y, 0.38, 0.38, SOFT_CORAL, line=SOFT_CORAL)
        text(slide, "?", 7.16, y + 0.02, 0.38, 0.22, size=12, color=CORAL, bold=True, align=PP_ALIGN.CENTER)
        text(slide, item, 7.74, y - 0.01, 4.35, 0.45, size=15, bold=True)
    text(slide, "Pilot team: data owner + platform/integration engineer + security or records reviewer", 0.76, 6.12, 11.8, 0.24, size=11, color=MUTED, align=PP_ALIGN.CENTER)
    rect(slide, 0.7, 6.42, 11.94, 0.58, INK, line=INK)
    text(slide, "Next: 4-week read-only pilot · 100 files · measure savings, relevance, fidelity and cost", 1.0, 6.56, 11.3, 0.3, size=17, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    footer(slide, "Ericsson Knowledge Compression · thank you")
    notes(slide, "2:30–3:00\nWe know the measured reduction, search path and deployable API work. The biggest risk is choosing a fidelity policy users trust on representative Ericsson data. Our next step is a four-week, read-only pilot on 100 files with a data owner, integration engineer and security or records reviewer. We measure savings, search relevance, fidelity acceptance and processing cost. No automated deletion during the pilot. Thank you.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    print(build())
