"""Closed-loop layout correction: write, render, measure, correct, rewrite.

The converter is otherwise open-loop -- it predicts how Word will lay the
document out and hopes. Two errors survive that prediction and neither is
recoverable by better prediction alone:

  * **Overflow.** Every source page ends in an explicit page break, so the
    reconstruction has zero slack: if a page's content comes out even 1pt too
    tall it spills, and one spilled line costs a whole extra page. Measured on
    real input this is the single most common remaining failure.

  * **Per-page offset.** Whole pages land a few points high or low while being
    internally near-perfect. On the WeasyPrint sample, fitting a per-page
    affine trend to word drift dropped mean |dy| from 4.01pt to 0.93pt -- 77%
    of the vertical error was a constant offset, not a layout mistake.

Both are trivial to *measure* from a render and awkward to predict. So measure
them. `verify.py` already rendered and diffed; it just never fed the answer
back. This module closes that loop.

LibreOffice is optional: without it `refine()` degrades to a single ordinary
write, so conversion never depends on it being installed.
"""
import copy
import os
import re
import tempfile
from typing import List, Optional

from .layout import DocLayout, Para, TableEl, FigureEl, ImageEl, RuleEl

# Space that may be reclaimed from a page that overflowed. Leading and content
# heights are load-bearing; the gaps between elements are the slack.
MIN_GAP_SCALE = 0.30     # never crush a gap below 30% of its measured value
OFFSET_DEADBAND = 0.4    # pt; do not chase noise
# Cap on a single correction step. This was 40pt on the theory that anything
# larger had to be a structural bug rather than an offset -- which turned out
# to be wrong, and self-serving: Google Docs offsets measure ~41pt, so the
# guard silently refused to correct the exact case the loop exists for. The
# loop is iterative and keeps the best round, so a generous cap is safe.
MAX_OFFSET_FIX = 200.0


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t or "")[:60]


def _page_elements(pl):
    for ch in pl.chunks:
        for el in ch.elements:
            yield el


def _gap_of(el):
    return getattr(el, "space_before", 0.0) or 0.0


def _set_gap(el, v):
    if hasattr(el, "space_before"):
        el.space_before = max(0.0, v)


def _rendered_pages_text(pdf_path):
    import fitz
    doc = fitz.open(pdf_path)
    out = []
    for p in doc:
        lines = []
        for b in p.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for ln in b["lines"]:
                t = "".join(s["text"] for s in ln["spans"])
                if t.strip():
                    lines.append((_norm(t), ln["bbox"][1], ln["bbox"][3]))
        out.append(lines)
    doc.close()
    return out


def _source_pages_text(src_pdf):
    return _rendered_pages_text(src_pdf)


def _map_pages(src_pages, out_pages):
    """Which rendered page does each source page's content begin on?

    Returns [rendered_index or None] per source page. Matching is by first
    distinctive line text, which survives re-wrap better than position.
    """
    where = {}
    for ri, lines in enumerate(out_pages):
        for t, _, _ in lines:
            if len(t) >= 12:
                where.setdefault(t, ri)
    mapping = []
    for lines in src_pages:
        found = None
        for t, _, _ in lines:
            if len(t) >= 12 and t in where:
                found = where[t]
                break
        mapping.append(found)
    return mapping


def _measure(src_pdf, rendered_pdf):
    src = _source_pages_text(src_pdf)
    out = _rendered_pages_text(rendered_pdf)
    mapping = _map_pages(src, out)
    spill = []          # per source page: rendered pages consumed beyond one
    offset = []         # per source page: median dy of matched lines
    for i, lines in enumerate(src):
        ri = mapping[i]
        nxt = None
        for j in range(i + 1, len(mapping)):
            if mapping[j] is not None:
                nxt = mapping[j]
                break
        if ri is None:
            spill.append(0)
            offset.append(0.0)
            continue
        end = nxt if nxt is not None else len(out)
        spill.append(max(0, (end - ri) - 1))
        pos = {}
        for t, y0, _ in out[ri]:
            pos.setdefault(t, y0)
        ds = [pos[t] - y0 for t, y0, _ in lines if t in pos and len(t) >= 12]
        ds.sort()
        offset.append(ds[len(ds) // 2] if ds else 0.0)
    return {"spill": spill, "offset": offset, "out_pages": len(out),
            "src_pages": len(src)}


def _apply(lay: DocLayout, m) -> bool:
    """Fold the measurement back into the layout. True if anything changed."""
    changed = False
    for idx, pl in enumerate(lay.pages):
        if idx >= len(m["spill"]):
            break
        els = list(_page_elements(pl))
        if not els:
            continue

        # 1. overflow -- reclaim slack from the gaps on this page
        if m["spill"][idx] > 0:
            gaps = [(_gap_of(e), e) for e in els]
            total = sum(g for g, _ in gaps)
            if total > 1.0:
                # one spilled page means at least one line did not fit; take
                # back a proportional slice and let the next round re-measure
                want = min(total * 0.5, total - total * MIN_GAP_SCALE)
                scale = max(MIN_GAP_SCALE, (total - want) / total)
                for g, e in gaps:
                    if g > 0:
                        _set_gap(e, g * scale)
                changed = True

        # 2. constant per-page offset
        off = m["offset"][idx]
        if abs(off) > OFFSET_DEADBAND and abs(off) <= MAX_OFFSET_FIX \
                and m["spill"][idx] == 0:
            if off < 0:
                # content sits too high: push it down, the first gap absorbs it
                _set_gap(els[0], _gap_of(els[0]) - off)
                changed = True
            else:
                # Content sits too low, so `off` points must be *removed*. The
                # first gap is often already 0 and w:before cannot be negative
                # (ST_TwipsMeasure is unsigned), so a first-gap-only correction
                # silently does nothing -- which is exactly how the Google Docs
                # offset survived every round untouched. Reclaim from every gap
                # on the page instead, nearest first.
                remaining = off
                for e in els:
                    if remaining <= 0.05:
                        break
                    g = _gap_of(e)
                    take = min(g, remaining)
                    if take > 0:
                        _set_gap(e, g - take)
                        remaining -= take
                        changed = True
    return changed


def refine(lay: DocLayout, src_pdf: str, out_path: str, dpi: int = 240,
           rounds: int = 2, verbose: bool = False, render=None) -> str:
    """Write `lay`, then correct it against real renders. Returns out_path.

    `render(docx_path, tmp_dir) -> pdf_path | None` selects the oracle. It
    defaults to LibreOffice, but nothing in this loop is LibreOffice-specific:
    pass the Google Docs round-trip instead and the same machinery corrects for
    Docs. That matters, because the two renderers disagree substantially --
    Docs adds a one-off gap after the first heading plus roughly 3pt at every
    paragraph boundary, so a layout tuned against LibreOffice is NOT tuned for
    the renderer this project actually targets.
    """
    from .docxout import write_docx
    from .verify import docx_to_pdf, SOFFICE

    if render is None:
        if SOFFICE is None:
            return write_docx(copy.deepcopy(lay), out_path, dpi=dpi)
        render = docx_to_pdf
    if rounds <= 0:
        return write_docx(copy.deepcopy(lay), out_path, dpi=dpi)

    best_path, best_score = None, None
    with tempfile.TemporaryDirectory() as td:
        for rnd in range(rounds + 1):
            write_docx(copy.deepcopy(lay), out_path, dpi=dpi)
            rendered = render(out_path, td)
            if rendered is None:
                return out_path
            m = _measure(src_pdf, rendered)
            score = (abs(m["out_pages"] - m["src_pages"]),
                     sum(m["spill"]),
                     sum(abs(o) for o in m["offset"]))
            if verbose:
                print("  refine round %d: pages %d/%d spill=%d |offset|=%.1f"
                      % (rnd, m["out_pages"], m["src_pages"], sum(m["spill"]),
                         score[2]))
            if best_score is None or score < best_score:
                best_score = score
                best_path = out_path + ".best"
                try:
                    import shutil
                    shutil.copy(out_path, best_path)
                except OSError:
                    best_path = None
            if score[0] == 0 and score[1] == 0 and score[2] < 1.0:
                break
            if rnd == rounds or not _apply(lay, m):
                break
        # keep the best round, not merely the last
        if best_path and os.path.exists(best_path):
            try:
                os.replace(best_path, out_path)
            except OSError:
                pass
    return out_path
