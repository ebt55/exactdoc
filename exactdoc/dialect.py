"""Producer-dialect normalisation: PDF IR -> canonical IR.

The same visual element is emitted very differently by different PDF
generators. A list bullet, for example:

    ReportLab   a text character, same block as the item, gap >= 4pt
    WeasyPrint  a text character, separate block, butted flush (gap 0)
    Chromium    not text at all -- a filled bezier circle (a vector path)
    pdfTeX      a text character from a math font

`infer.py` reconstructs semantics from geometry. If the geometry it sees
depends on the producer, its thresholds silently encode "how ReportLab draws
things" instead of "what a bullet is". This module removes that coupling by
rewriting producer-specific idioms into one canonical form *before* inference
runs.

Everything here keys off **evidence observed in the page**, never off the
`/Producer` metadata string. Producer strings are absent (fpdf2 writes none),
rewritten by post-processors (Ghostscript, pdftk), and differ across versions
of the same engine. A metadata switch also fails catastrophically on the first
unknown producer, which is exactly the failure mode this module exists to
prevent. The detected fingerprint is recorded on `ir.meta` for diagnostics and
CI, and is deliberately not consulted for decisions.
"""
from typing import List, Optional

from .model import DocIR, PageIR, TextBlock, Line, Span, DrawCmd, bbox_overlap

# --- tunables, all in PDF points ------------------------------------------
BULLET_MAX = 9.0          # a list marker glyph is never larger than this
BULLET_ASPECT = 2.0       # max |w - h| for a marker glyph
BULLET_GAP = 46.0         # max distance from marker to the text it labels
BULLET_VTOL = 1.0         # vertical overlap tolerance, in marker heights
BACKDROP_COVER = 0.60     # page-area fraction that makes a fill a backdrop
BACKDROP_LUMA = 245       # min channel value for "invisible" light backdrop


def _luma_ok(hexcol: Optional[str]) -> bool:
    if not hexcol or len(hexcol) != 7:
        return False
    try:
        r, g, b = (int(hexcol[1:3], 16), int(hexcol[3:5], 16), int(hexcol[5:7], 16))
    except ValueError:
        return False
    return min(r, g, b) >= BACKDROP_LUMA


def _is_backdrop(d: DrawCmd, pw: float, ph: float) -> bool:
    """A page-covering light fill: painted by Chromium (and others) as the
    page background. Invisible on paper, but it touches every other drawing,
    so cluster union-find merges the whole page into one region."""
    if d.shape != "rect" or not d.fill:
        return False
    x0, y0, x1, y1 = d.bbox
    if (x1 - x0) * (y1 - y0) < BACKDROP_COVER * pw * ph:
        return False
    return _luma_ok(d.fill)


def _is_marker_glyph(d: DrawCmd) -> bool:
    """Small, solid, roughly square: the shape of a drawn bullet."""
    if not d.fill:
        return False
    x0, y0, x1, y1 = d.bbox
    w, h = x1 - x0, y1 - y0
    if not (0.4 < w <= BULLET_MAX and 0.4 < h <= BULLET_MAX):
        return False
    return abs(w - h) <= BULLET_ASPECT


def _labels_a_line(d: DrawCmd, lines: List[Line]) -> bool:
    """True if this glyph sits just left of a text line it plausibly labels."""
    x0, y0, x1, y1 = d.bbox
    cy, h = (y0 + y1) / 2, max(1.0, y1 - y0)
    for ln in lines:
        lb = ln.bbox
        if lb[0] < x1 - 0.5:                       # text must start to the right
            continue
        if lb[0] - x1 > BULLET_GAP:
            continue
        if lb[1] - BULLET_VTOL * h <= cy <= lb[3] + BULLET_VTOL * h:
            return True
    return False


def _drop_backdrops(page: PageIR) -> int:
    keep = [d for d in page.drawings if not _is_backdrop(d, page.width, page.height)]
    n = len(page.drawings) - len(keep)
    page.drawings = keep
    return n


def _markers_to_text(page: PageIR) -> int:
    """Rewrite drawn bullet glyphs as one-span text blocks.

    This is deliberately a *translation*, not a special case: it converts the
    Chromium idiom into the separate-marker-box idiom that infer.py already
    reconstructs for WeasyPrint, so list handling has a single code path.
    """
    lines = [l for b in page.blocks for l in b.lines if l.horizontal]
    if not lines:
        return 0
    cand = [d for d in page.drawings if _is_marker_glyph(d)]
    if not cand:
        return 0
    hits = [d for d in cand if _labels_a_line(d, lines)]
    # A real list has repetition. A single small square is more likely to be a
    # decorative dot, so require corroboration before rewriting anything.
    if len(hits) < 2:
        return 0
    hitset = {id(d) for d in hits}
    page.drawings = [d for d in page.drawings if id(d) not in hitset]
    for d in hits:
        x0, y0, x1, y1 = d.bbox
        cy = (y0 + y1) / 2
        size, near = 10.0, None
        for ln in lines:
            lb = ln.bbox
            if lb[0] >= x1 - 0.5 and lb[0] - x1 <= BULLET_GAP and \
                    lb[1] - (y1 - y0) <= cy <= lb[3] + (y1 - y0):
                if near is None or lb[0] < near.bbox[0]:
                    near = ln
        if near is not None and near.spans:
            size = near.spans[0].size
        bb = (x0, cy - size * 0.72, x0 + size * 0.5, cy + size * 0.22)
        sp = Span(text="•", font="Arial", size=size,
                  color=d.fill or "#000000", bold=False, italic=False,
                  mono=False, serif=False, superscript=False,
                  bbox=bb, origin=(x0, cy + size * 0.22))
        page.blocks.append(TextBlock(lines=[Line(spans=[sp], bbox=bb)], bbox=bb))
    page.blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    return len(hits)


def _split_rotated(page: PageIR) -> int:
    """Move non-horizontal text out of the flow.

    LaTeX/arXiv stamps a rotated identifier down the left margin. Emitted as a
    normal paragraph it becomes a full-width horizontal line that pushes the
    whole page down. Word has no editable rotated-text construct that Google
    Docs imports, so the honest options are 'drop from flow' or 'rasterise';
    we take it out of the flow and record it for the writer.
    """
    moved = 0
    for b in page.blocks:
        rot = [l for l in b.lines if not l.horizontal]
        if not rot:
            continue
        b.lines = [l for l in b.lines if l.horizontal]
        moved += len(rot)
        page.rotated.extend(rot)
    page.blocks = [b for b in page.blocks if b.lines]
    return moved


def fingerprint(ir: DocIR) -> dict:
    """Observable dialect traits. Diagnostics and CI only -- never a switch."""
    fp = {"producer": (ir.meta or {}).get("producer", "") or "",
          "creator": (ir.meta or {}).get("creator", "") or ""}
    n_curve = n_rect = n_backdrop = n_marker = n_rot = 0
    for p in ir.pages:
        for d in p.drawings:
            if d.shape in ("curve", "complex"):
                n_curve += 1
            if d.shape == "rect":
                n_rect += 1
            if _is_backdrop(d, p.width, p.height):
                n_backdrop += 1
            if _is_marker_glyph(d):
                n_marker += 1
        for b in p.blocks:
            for l in b.lines:
                if not l.horizontal:
                    n_rot += 1
    fp.update({"curves": n_curve, "rects": n_rect, "backdrops": n_backdrop,
               "vector_markers": n_marker, "rotated_lines": n_rot,
               "pages": len(ir.pages)})
    return fp


def normalize(ir: DocIR) -> DocIR:
    """Rewrite producer idioms into canonical form. Mutates and returns `ir`."""
    stats = {"backdrops": 0, "vector_markers": 0, "rotated": 0}
    for p in ir.pages:
        if not hasattr(p, "rotated"):
            p.rotated = []
        stats["backdrops"] += _drop_backdrops(p)
        stats["rotated"] += _split_rotated(p)
        stats["vector_markers"] += _markers_to_text(p)
    ir.meta = dict(ir.meta or {})
    ir.meta["_dialect"] = fingerprint(ir)
    ir.meta["_normalized"] = stats
    return ir
