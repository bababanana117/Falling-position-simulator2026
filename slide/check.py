#!/usr/bin/env python
"""Render main.pdf to preview/pNN.png and flag what the eye might miss.

Two sources of trouble, two checks.

The log catches overfull boxes, missing glyphs, font substitutions and
undefined citation keys. Beamer writes no per-frame marker to the log, so a
log line is reported with its input line, not a page.

The PDF itself is where overflow shows: a beamer frame is not a fixed-height
box, so content that runs past the bottom produces at most an overfull vbox
and often nothing at all. The geometry pass therefore asks pymupdf for text
and drawings with a clip much larger than the page, and reports anything
whose box crosses the page edge or sits in the footline band. A fallback
font in the PDF (Latin Modern, DejaVu) means a CJK glyph reached a Latin-only
context or a font load failed silently.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pymupdf

OVERFULL = re.compile(r"^Overfull \\([hv])box \(([\d.]+)pt too (wide|high)\)(.*)")
MISSING = re.compile(r"^Missing character: There is no (.+?) \(U\+([0-9A-Fa-f]+)\) in font (.+)")
FONTWARN = re.compile(
    r"LaTeX Font Warning: Font shape .* undefined|fontspec.*not found|luaotfload.*not found"
)
UNDEFSRC = re.compile(r"undefined source key '([^']+)'")
LINEREF = re.compile(r"(?:at|on input) line (\d+)")
FALLBACK = ("LMRoman", "LatinModern", "lmroman", "DejaVu", "NotoSans", "LMSans", "LMMono")
ALLOWED_MATH = ("FiraMath", "LMMathSymbols", "LMMathItalic", "LMMathExtension")


def parse_log(path: Path) -> list[tuple[str, str, str]]:
    """(kind, where, what) for every log line worth acting on."""
    issues = []
    for line in path.read_text(errors="replace").splitlines():
        where = f"line {m.group(1)}" if (m := LINEREF.search(line)) else "log"
        if m := OVERFULL.match(line):
            # A box a few points too wide protrudes invisibly into the margin;
            # a box too high runs into the footline, so that threshold stays low.
            if float(m.group(2)) >= (4.0 if m.group(1) == "h" else 1.0):
                issues.append(("overfull", where, f"{m.group(1)}box {m.group(2)}pt too {m.group(3)}"))
        elif m := MISSING.match(line):
            issues.append(("missing-glyph", where, f"{m.group(1)} U+{m.group(2)} in {m.group(3)}"))
        elif FONTWARN.search(line):
            issues.append(("font", where, line.strip()))
        elif m := UNDEFSRC.search(line):
            issues.append(("undefined-src", where, m.group(1)))
    return issues


def check_pages(doc, out: Path, dpi: int = 110, foot_pt: float = 17.0) -> list[tuple[str, str, str]]:
    """Render each page; flag text or graphics outside the safe area."""
    out.mkdir(parents=True, exist_ok=True)
    issues = []
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_MEDIABOX_CLIP
    for i, page in enumerate(doc, 1):
        page.get_pixmap(dpi=dpi).save(out / f"p{i:02d}.png")
        w, h = page.rect.width, page.rect.height
        where = f"p{i:02d}"
        # get_text clips to the page rect unless told otherwise; look well past it.
        wide = pymupdf.Rect(-w, -h, 2 * w, 3 * h)
        for b in page.get_text("dict", flags=flags, clip=wide)["blocks"]:
            x0, y0, x1, y1 = b["bbox"]
            if x1 > w + 0.5 or y1 > h + 0.5 or x0 < -0.5 or y0 < -0.5:
                snippet = ""
                if b["type"] == 0:
                    snippet = "".join(s["text"] for ln in b["lines"] for s in ln["spans"])[:30]
                issues.append(("off-page", where, f"y1={y1:.0f} > {h:.0f}  {snippet!r}"))
                continue
            if b["type"] == 0 and y1 > h - foot_pt:
                size = max(s["size"] for ln in b["lines"] for s in ln["spans"])
                if size > 9.5:
                    issues.append(("into-footline", where, f"{size:.1f}pt text at y1={y1:.1f}"))
        for img in page.get_image_info():
            x0, y0, x1, y1 = img["bbox"]
            if x1 > w + 0.5 or y1 > h + 0.5:
                issues.append(("image-off-page", where, str(img["bbox"])))
        # Vector graphics (card frames, TikZ, included PDFs) past the page edge.
        # A path under a clip (a coastline polygon inside its axes, say) is
        # judged by the part that can show: its rect cut to the clip's scissor.
        low = []
        clips: dict[int, pymupdf.Rect] = {}   # nesting level -> scissor rect
        for dr in page.get_drawings(extended=True):
            lvl = dr.get("level", 0)
            if dr.get("type") == "clip":
                for k in [k for k in clips if k >= lvl]:
                    del clips[k]
                if dr.get("scissor") is not None:
                    clips[lvl] = dr["scissor"]
                continue
            if "rect" not in dr:
                continue
            r = pymupdf.Rect(dr["rect"])
            for k, sc in clips.items():
                if k < lvl:
                    r = r & sc
            if r.is_empty:
                continue
            if h + 0.5 < r.y1 < 3 * h:
                low.append(r.y1)
        if low:
            issues.append(("drawing-off-page", where, f"{len(low)} paths, lowest y1={max(low):.0f} > {h:.0f}"))
        for f in page.get_fonts():
            name = f[3]
            if any(k in name for k in FALLBACK) and not any(k in name for k in ALLOWED_MATH):
                issues.append(("fallback-font", where, name))
    return issues


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="?", default="main.pdf")
    ap.add_argument("--log", default="main.log")
    ap.add_argument("--out", default="preview")
    ap.add_argument("--dpi", type=int, default=110)
    a = ap.parse_args()
    doc = pymupdf.open(a.pdf)
    issues = parse_log(Path(a.log)) + check_pages(doc, Path(a.out), a.dpi)
    print(f"{doc.page_count} pages -> {a.out}/pNN.png")
    for kind, where, what in issues:
        print(f"  {where:9s} {kind:16s} {what}")
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
