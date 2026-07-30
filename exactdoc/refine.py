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


# Which vertical anchor the offset is measured from. Both are available from
# `Backend.page_lines`; this is a measured choice, and the measurement contradicts
# the physics.
#
# A baseline is the physically correct anchor -- it is a number in the content
# stream, so it cancels cleanly when a source y is subtracted from a rendered y
# over two documents set in different fonts, where a line-box TOP carries a
# per-font metric convention that does not. The writer's own vertical model is
# baseline-anchored (THEORY 3.1). And measured on the canonical corpus, switching
# to it took the incumbent's mean within-2pt from **0.511 to 0.478**.
#
# The reason is the same one that reverted the line-box escalation in STATUS D2:
# `_apply` below feeds the offset into the `space_before` chain, and that chain is
# calibrated against a box-top origin. Moving the anchor alone desynchronises the
# correction from the thing it corrects -- it fixed 04_exec_brief (0.22 -> 0.44)
# and broke 05_memo (0.64 -> 0.48) and r1_reportlab_report (0.60 -> 0.32). Origin,
# `_para_box` and the spacing chain have to move together, which is a project and
# not a patch.
ANCHOR_TOP, ANCHOR_BASELINE = 1, 2
ANCHOR = ANCHOR_TOP


def _pages_text(pdf_path, backend, anchor=ANCHOR):
    """[(normalised text, anchor_y, y_bottom), ...] per page, via the backend.

    This read the rendered PDF through `fitz` directly, which put PyMuPDF on the
    default runtime path of a stage that has nothing to do with parsing: the loop
    measures a document *it just wrote*, and what it needs is text lines with a
    vertical anchor, which is now `Backend.page_lines`.
    """
    return [[(_norm(ln[0]), ln[anchor], ln[3]) for ln in page]
            for page in backend.page_lines(pdf_path)]


def _map_pages(src_pages, out_pages):
    """Which rendered page does each source page's content begin on?

    Returns [rendered_index or None] per source page.

    Matching on the FIRST distinctive line alone mis-maps any page whose
    opening line's text repeats elsewhere -- TOC entries repeating as headings,
    running "References" heads, "Figure N" captions. That exact failure class
    contaminated two diagnostic scripts before it was caught here. So: each of
    the page's first few distinctive lines votes for every rendered page it
    appears on, and the winner is chosen under a monotonicity constraint
    (rendered index never decreases across source pages -- pages cannot render
    out of order).
    """
    idx = {}
    for ri, lines in enumerate(out_pages):
        for t, _, _ in lines:
            if len(t) >= 12:
                idx.setdefault(t, []).append(ri)
    mapping = []
    prev = 0
    for lines in src_pages:
        votes = {}
        used = 0
        for t, _, _ in lines:
            if len(t) < 12 or t not in idx:
                continue
            for ri in idx[t]:
                votes[ri] = votes.get(ri, 0) + 1
            used += 1
            if used >= 5:
                break
        if not votes:
            mapping.append(None)
            continue
        fwd = {ri: v for ri, v in votes.items() if ri >= prev}
        pool = fwd or votes            # fall back if monotonicity finds nothing
        best = min(pool, key=lambda ri: (-pool[ri], ri))
        mapping.append(best)
        prev = best
    return mapping


def _measure(src_pdf, rendered_pdf, backend):
    src = _pages_text(src_pdf, backend)
    out = _pages_text(rendered_pdf, backend)
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
        # Offsets use only lines whose text is UNIQUE on both sides of the
        # comparison. A duplicated string ("1. Motivation" in a TOC and again
        # as a heading) would pair the heading with the TOC entry's y and feed
        # the corrector a garbage offset -- the same defect as first-line page
        # mapping, one level down.
        from collections import Counter
        sc = Counter(t for t, _, _ in lines)
        oc = Counter(t for t, _, _ in out[ri])
        pos = {t: y0 for t, y0, _ in out[ri] if oc[t] == 1}
        ds = [pos[t] - y0 for t, y0, _ in lines
              if len(t) >= 12 and sc[t] == 1 and t in pos]
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

        # 1. overflow -- reclaim slack from the gaps on this page.
        # Take from the LARGEST gaps first rather than scaling everything
        # uniformly: a 40pt section break and a 4pt paragraph gap are not
        # equally elastic -- the eye notices the section break shrinking long
        # before it notices the paragraph gap, and large gaps carry
        # proportionally more slack and less rhythm. Every gap keeps an
        # absolute floor, not just a percentage of itself.
        if m["spill"][idx] > 0:
            gaps = sorted(((_gap_of(e), e) for e in els),
                          key=lambda t: -t[0])
            total = sum(g for g, _ in gaps)
            if total > 1.0:
                want = total * 0.5      # re-measured next round; iterate, don't guess
                for g, e in gaps:
                    if want <= 0.05:
                        break
                    floor = max(2.0, g * MIN_GAP_SCALE)
                    take = min(max(0.0, g - floor), want)
                    if take > 0:
                        _set_gap(e, g - take)
                        want -= take
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
           rounds: int = 2, verbose: bool = False, render=None,
           output_profile: str = "standard", backend=None) -> str:
    """Write `lay`, then correct it against real renders. Returns out_path.

    `render(docx_path, tmp_dir) -> pdf_path | None` selects the oracle. It
    defaults to LibreOffice, but nothing in this loop is LibreOffice-specific:
    pass the Google Docs round-trip instead and the same machinery corrects for
    Docs. That matters, because the two renderers disagree substantially --
    Docs adds a one-off gap after the first heading plus roughly 3pt at every
    paragraph boundary, so a layout tuned against LibreOffice is NOT tuned for
    the renderer this project actually targets.

    `backend` reads both the source and the rendered PDF. It is the same backend
    the parse used, passed down rather than re-chosen, so the loop cannot end up
    measuring one parser's line grouping against another's and correcting the
    layout for the difference.
    """
    from .backend import get_backend
    from .docxout import write_docx
    from .verify import docx_to_pdf, SOFFICE

    if backend is None:
        backend = get_backend()
    if render is None:
        if SOFFICE is None:
            # Refinement was requested and there is nothing to refine against.
            # This used to return an unrefined DOCX -- a different product under
            # the same exit code, and the specific mechanism by which a published
            # fidelity number came to describe a profile no surface had run.
            from .errors import OracleUnavailableError
            raise OracleUnavailableError(
                "refinement was requested but LibreOffice was not found, so "
                "there is no renderer to correct against. Install it, choose "
                "another oracle, or set refine_rounds=0 to convert open-loop "
                "deliberately.")
        render = docx_to_pdf
    if rounds <= 0:
        return write_docx(lay, out_path, dpi=dpi,
                          output_profile=output_profile, backend=backend)

    best_path, best_score = None, None
    with tempfile.TemporaryDirectory() as td:
        for rnd in range(rounds + 1):
            # write_docx is pure: `lay` survives the round unmodified.
            write_docx(lay, out_path, dpi=dpi, output_profile=output_profile,
                       backend=backend)
            rendered = render(out_path, td)
            if rendered is None:
                return out_path
            m = _measure(src_pdf, rendered, backend)
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
