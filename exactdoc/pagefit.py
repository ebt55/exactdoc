"""Page-fit planner for the standard profile (LibreOffice and Word).

Every source page ends in a hard page break, so a page whose content renders a
line or two taller than its box spills, the break then fires on the spill, and
every later page sits one place late: word recall -- words on the right page --
collapses from there. Measured on the checkpoint's raw renders (ckpt-raw,
LibreOffice 24.2 in the canonical container, 2,092 single-column pages of the
90 convertible documents, `docs/evidence/pagefit-2026-10-06.json`), the page
model below against what LibreOffice did with each page:

    predicted spare (pt)   pages   spilled
    < -20                    145     60%
    -20 .. 0                  50     28%
    0 .. 5                    51     10%
    5 .. 10                   15      7%
    10 .. 15                  34      6%
    15 .. 20                  47      2%
    20 .. 30                 162      2%
    30 and more             1588      3%

and the rendered page height less the modelled one, on pages that kept to
their page and end in text: median -0.2pt, p75 +0.7, p90 +13.7. The model is
exact to a point on most pages; what it misses is a paragraph wrapping one
line longer than predicted, one body line (12-14pt in these documents). The
spills it cannot see at all (the 3% past 30pt) are tables whose rows grow and
pages the writer does not end with a break; no gap plan can reach those.
(Tables are their source box plus `table_growth`; the first cut, source box
only, read 17% / 12% / 3% for the 0-15pt buckets, its spills hiding in
tables whose rows wrapped.)

So the rule is the one the Google Docs planner (WP19, `docxout._gdocs_page_plan`)
proved live, with LibreOffice/Word line metrics: model the page as the
standard profile writes it, and only where it would be set with less than a
body line plus PAGEFIT_SAFETY_PT to spare, take what that needs from the
page's own gaps -- gently first, then to the refine loop's floors, from the
foot of the page up so the fewest lines move. A page that fits is written
exactly as before; a page that cannot be made to fit by its gaps is left as
the source spaced it (spending its spacing would not save it).

The two defences this generalises stay as they were: `_absorb_page_spill`
still answers every page the planner leaves alone (a booklet, a page before a
blank source page, a page the model cannot add up), and `_guard_page_tail`
still keeps the closing element a line clear of the foot afterwards.
"""
import dataclasses
import math
from typing import Optional

from .layout import ColBreak, FigureEl, ImageEl, Para, RuleEl, TableEl

# OFF until it is proven on the gate and in the product and Word lanes. On
# the raw sweep (canonical, both corpora, against ckpt-raw) it takes y18 156
# -> 144 pages and y33 62 -> 60, both page-exact (criterion 5 in LibreOffice
# 11 -> 13 of 21), y03 51 -> 47 and y64 44 -> 40, page-exact 59 -> 62, the 16
# gated documents byte-identical -- but y59 (CMS notice, 6 pages rendered as
# 18, not promised) regresses dy_p50 30.07 -> 46.35 when its first page, 178pt
# over, is paid back into its box. Word, on: product DOCX 15 -> 16 of 21
# (y18 154 -> 144) but y64 40 -> 41. With it off the writer is byte-identical
# to the code before the planner. `docs/evidence/pagefit-2026-10-06.json`.
PAGEFIT_ENABLED = True
# A page the model puts more than this many body lines past its box is paid
# only by a plan that keeps every gap at least PAGEFIT_GENTLE_GAP_SCALE of
# itself; one that would have to go to the refine floors is left as spaced.
# A claim that large is the guess the model is least sure of, and to the
# floors a wrong one costs the most placement. Measured over every page the
# uncapped planner paid (240 pages of the 90 documents, raw lane, Carlito
# image, the off and on renders read per source page with refine._measure;
# docs/evidence/pagefit-2026-10-10.json "pages"): of the 11 pages claimed
# more than 8 lines over whose plan needed the floors, 8 fitted in the render
# unpaid (the claim was wrong) and paying them only moved their lines --
# y59 p1, 11.1 lines (178pt) claimed, fitted all the same, and its plan cut
# one 233pt gap to 70pt (dy_p50 31.97 -> 48.15); of the pages the gentle
# tier could pay, every one past 8 lines was a real spill and was saved --
# y21 p6, 10.9 lines, which a flat cap of 10 left spilling (y21 dy_p50
# 51.96 -> 65.32 with it, 40.90 without). Under 10 lines the floors stay
# open: y02 p66 (7.4 lines) and p70, y03 p33 were real spills only the
# floors could pay. The old image's cap measurements
# (docs/evidence/pagefit-2026-10-06.json "cap": 3, 5 and 8 lost y18, y33 and
# y03 pages) keep the threshold at 10.
PAGEFIT_MAX_OVER_LINES = 10
# Sizes are half-points, gaps tenths and the exact line a tenth of a point: a
# plan that lands exactly on its target can still be a point out. The value
# the Google Docs planner (GDOCS_PAGE_SAFETY_PT) and the refine loop
# (refine.FIT_SAFETY_PT) aim with.
PAGEFIT_SAFETY_PT = 2.0
# The first tier of the reclaim leaves every gap at least this share of its
# source size; only a page that still needs room goes on to the refine floors
# (docxout.SPILL_MIN_GAP_SCALE / SPILL_GAP_FLOOR_PT). The Google Docs
# planner's GDOCS_GENTLE_GAP_SCALE, measured live there on placement.
PAGEFIT_GENTLE_GAP_SCALE = 0.6


def _segments(p: Para):
    """The paragraph's runs split at its forced line breaks ("\\n"), or None
    when it has none. `predict_lines` reads a soft break as a space, so a
    line-locked or verbatim paragraph would be re-flowed as one."""
    if not any("\n" in (r.text or "") for r in p.runs):
        return None
    segs, cur = [], []
    for r in p.runs:
        parts = (r.text or "").split("\n")
        for j, part in enumerate(parts):
            if part or r.is_tab:
                cur.append(dataclasses.replace(r, text=part))
            if j < len(parts) - 1:
                segs.append(cur)
                cur = []
    segs.append(cur)
    return segs


def _source_lines(p: Para) -> int:
    """The lines the source set `p` in: its measured count, and at least one
    per forced line (a code cell's listing arrives with no count)."""
    forced = sum((r.text or "").count("\n") for r in p.runs) + 1
    return max(1, p.src_lines or 0, forced)


def para_lines(p: Para, avail: float, metrics) -> int:
    """How many lines the renderer sets `p` in at `avail` points.

    The ladder's greedy first fit (`ladder.predict_lines`), per forced line,
    where the font has a width table; the source's own count where it has
    not. `predict_lines` measures one space between words whatever the text
    holds, so a preformatted line padded with runs of spaces (y22's verbatim
    blocks, LaTeX side-by-side code) is predicted narrower than it is set:
    measured on y22 p48, such lines wrapped and moved the page 59pt. There
    the source count is a floor."""
    from .docxout import predict_lines_for
    src = _source_lines(p)
    if metrics is None:
        return src
    segs = _segments(p)
    if segs is None:
        n = predict_lines_for(p, avail, metrics)
        if n is None:
            return src
    else:
        n = 0
        for seg in segs:
            if not any(r.text for r in seg if not r.is_tab):
                n += 1
                continue
            k = predict_lines_for(dataclasses.replace(p, runs=seg), avail,
                                  metrics)
            if k is None:
                return src
            n += k
    if "  " in p.text:
        n = max(n, src)
    return n


# A cell line the source filled to within this much of the cell's edge may
# wrap or not: the writer encodes the source's letter-spacing in twentieths of
# a point per character (w:spacing) and its width correction in whole percent
# (w:w), so a 45-character label with typed leaders lands within about a
# point of where the source set it, either side. Measured on y64 p22 (BLS
# release, canonical LibreOffice): of 17 leader rows predicted to fit by under
# 2pt, 9 wrapped, and the table's notes went over by the two-line NOTE alone.
# `table_growth` counts such a line as wrapping: a row grows by at most a line
# it may not take, and a page the planner then pays for is moved by at most
# that line -- against a whole page lost to the one it did take.
CELL_EDGE_PT = 2.0


def table_growth(t: TableEl, content_w: float, metrics) -> float:
    """How much taller than its source box the standard profile's table
    renders, from cell paragraphs that wrap to more lines than the source.

    A text row is content-driven in the writer (`write_table`: the cell's
    pads plus its exact-leading paragraphs), so a cell paragraph that wraps
    once more in its written column grows the row by a line, unless another
    cell of the row is taller still. Measured on y64 (BLS release, p19-p20):
    category labels with typed leaders ("Agriculture and related
    industries....") wrapped in seven rows and pushed the table's notes onto
    a page of their own; the page model, which took the table's source box,
    said 12pt to spare (and see CELL_EDGE_PT). Each row's growth is counted,
    never its shrinkage: a
    row predicted shorter may still be held by another cell or a pinned
    height, and the planner errs toward a page at risk.

    The written column widths are `_fit_col_widths`'s, which can widen a
    column past the source's; a cell's text width is its span less its own
    side pads and the indents the writer keeps (`_depadded`)."""
    from .docxout import (_fit_col_widths, _line_height,
                          _span_into_blank_neighbours)
    import copy
    if metrics is None or not t.rows or not t.col_widths:
        return 0.0
    try:
        tt = _span_into_blank_neighbours(copy.copy(t))
        widths = _fit_col_widths(tt, content_w)
    except Exception:              # a table the writer would not fit: no claim
        return 0.0
    grow = 0.0
    for ri, row in enumerate(tt.rows):
        pred_row = src_row = 0.0
        for ci, cell in enumerate(row):
            if cell is None or getattr(cell, "row_span", 1) > 1:
                continue
            span = max(1, getattr(cell, "col_span", 1) or 1)
            pad = cell.pad if len(cell.pad) >= 4 else (0.0, 0.0, 0.0, 0.0)
            cw = sum(widths[ci:ci + span]) - pad[1] - pad[3]
            pred = src = pad[0] + pad[2]
            for p in cell.paras:
                if not isinstance(p, Para):
                    continue
                avail = cw - max(0.0, p.left_indent - pad[1]) -                     max(0.0, p.right_indent - pad[3])
                lead = _line_height(p)
                k = _source_lines(p)
                n = k
                if avail > CELL_EDGE_PT + 1.0:
                    # a line set within CELL_EDGE_PT of its cell's edge may
                    # wrap: counted as wrapping
                    n = para_lines(p, avail - CELL_EDGE_PT, metrics)
                rest = (p.space_before or 0.0) + (p.space_after or 0.0)
                pred += rest + n * lead
                src += rest + k * lead
            pred_row = max(pred_row, pred)
            src_row = max(src_row, src)
        # the row as the source measured it, where inference kept it: a code
        # block's one cell carries its listing as forced lines with no
        # per-line count (c7: ten lines, src_lines 0), and its row height is
        # the truth the content is compared with
        rh = tt.row_heights[ri] if ri < len(tt.row_heights) else None
        grow += max(0.0, pred_row - max(src_row, rh or 0.0))
    return grow


def _payable(el) -> bool:
    """A gap the writer can apply a plan to: a paragraph's, a flowing rule's,
    an inline picture's (`_write_docx` writes those from a copy). A table's
    gap is its spacer paragraph, which takes no plan."""
    return isinstance(el, (Para, RuleEl, FigureEl, ImageEl)) and \
        getattr(el, "frame", None) is None


def page_model(pg, content_w: float, lay, notes_h: float, plan: dict,
               metrics, drop_first_gap: bool = False):
    """-> (used_pt, [(element, gap_now, source_gap)]) for one source page as
    the standard profile writes it, under the gap overrides in `plan`; None
    where the page is not additive (columns, a column break, a page-locked
    element, a block with no box).

    Paragraphs are their predicted line count (`para_lines`) at the exact
    line the writer emits (a tenth of a point); a rule is write_rule's exact
    2pt line; a picture its height; a table its source box. `notes_h`: the
    page's real footnote area, whose `role="footnote"` paragraphs leave the
    body. `drop_first_gap`: the page seam is a carrier paragraph, and
    LibreOffice drops the gap of the element after it (B23, see
    `_write_docx`) -- room the page has, and no gap to pay."""
    from .docxout import _line_height
    used = 0.0
    gaps = []
    first = True
    for ch in pg.chunks:
        if ch.n_cols > 1:
            return None
        used += max(0.0, ch.pre_gap)
        for el in ch.elements:
            if isinstance(el, ColBreak) or \
                    getattr(el, "frame", None) is not None:
                return None
            if notes_h > 0 and getattr(el, "role", "") == "footnote":
                continue
            src_gap = getattr(el, "space_before", 0.0) or 0.0
            gap = plan.get(id(el), src_gap)
            if first and drop_first_gap:
                gap = 0.0
            elif _payable(el):
                gaps.append((el, gap, src_gap))
            first = False
            gap = round(max(0.0, gap), 1)
            after = getattr(el, "space_after", 0.0) or 0.0
            if isinstance(el, Para):
                n = para_lines(el, content_w - el.left_indent - el.right_indent,
                               metrics)
                lead = _line_height(el)
                if el.leading and el.leading > 1:
                    lead = round(lead, 1)          # _apply_leading's exact line
                used += gap + n * lead + round(max(0.0, after), 1)
            elif isinstance(el, RuleEl):
                used += gap + 2.0
            elif isinstance(el, (FigureEl, ImageEl)):
                used += gap + el.height
            elif isinstance(el, TableEl):
                if el.bbox is None:
                    return None
                used += gap + (el.bbox[3] - el.bbox[1]) + after + \
                    table_growth(el, content_w, metrics)
            else:
                bb = getattr(el, "bbox", None) or getattr(el, "clip", None)
                if bb is None:
                    return None
                used += gap + (bb[3] - bb[1]) + after
    return used, gaps


def fit_page(pg, content_w: float, lay, notes_h: float, body_line: float,
             plan: dict, output_profile: str = "standard",
             drop_first_gap: bool = False, report: Optional[dict] = None) -> dict:
    """The gap plan `{id(element): space_before}` for one standard-profile
    page: `plan` (the caller's, `_absorb_page_spill`'s) unchanged when the page
    fits with a body line plus PAGEFIT_SAFETY_PT to spare or cannot be made to,
    else a plan of the page's own gaps that leaves it that room (module
    docstring). Nothing is mutated: the refine loop writes the same layout
    once per round, and a gap reduced in place would compound.

    `report`, when given, receives `at_risk` and `short` (the points of the
    budget the gaps could not pay)."""
    from .docxout import (SPILL_GAP_FLOOR_PT, SPILL_MIN_GAP_SCALE,
                          _body_capacity, _text_metrics)
    if report is not None:
        report.update(at_risk=False, short=0.0)
    if getattr(pg, "continuation_only", False) or not pg.chunks:
        return plan
    got = page_model(pg, content_w, lay, notes_h, {},
                     _text_metrics(output_profile), drop_first_gap)
    if got is None:
        return plan
    used, gaps = got
    capacity = _body_capacity(lay) - notes_h
    need = used - capacity + max(0.0, body_line) + PAGEFIT_SAFETY_PT
    if need <= 0.05:
        return plan
    if report is not None:
        report["at_risk"] = True
    tiers = []
    for scale in (PAGEFIT_GENTLE_GAP_SCALE, SPILL_MIN_GAP_SCALE):
        tiers.append([max(0.0, gap - max(SPILL_GAP_FLOOR_PT, src * scale))
                      for _el, gap, src in gaps])
    total = sum(tiers[-1])
    over = used - capacity
    if report is not None:
        report["short"] = max(0.0, need - total)
    if over > 0 and total < over + PAGEFIT_SAFETY_PT:
        return plan            # cannot be saved by its spacing: as shipped
    if PAGEFIT_MAX_OVER_LINES is not None and \
            over > PAGEFIT_MAX_OVER_LINES * max(0.0, body_line) and \
            sum(tiers[0]) < need - 0.05:
        # a claim this large is paid only by a plan that keeps every gap at
        # least PAGEFIT_GENTLE_GAP_SCALE of itself; to the floors it is the
        # guess the model is least sure of (PAGEFIT_MAX_OVER_LINES)
        return plan
    pay = min(need, total)
    take = [0.0] * len(gaps)
    # From the foot of the page up, each tier in turn: a gap taken low on the
    # page moves only the lines under it, so the fewest words leave their
    # source position (the WP19 probe measured the proportional reclaim
    # moving every line below the first gap it touched).
    for row in tiers:
        for k in range(len(gaps) - 1, -1, -1):
            if pay <= 0.05:
                break
            t = min(max(0.0, row[k] - take[k]), pay)
            take[k] += t
            pay -= t
    out = {}
    for (el, gap, _src), t in zip(gaps, take):
        if t > 0.05:
            # tenths of a point, rounded down: the page never pays less
            out[id(el)] = max(0.0, math.floor((gap - t) * 10 + 1e-6) / 10)
    return out


def plan_page(pg, content_w: float, lay, notes_h: float, body_line: float,
              plan: dict, output_profile: str = "standard",
              drop_first_gap: bool = False, memo: Optional[dict] = None) -> dict:
    """`fit_page` as the writer asks it. Open-loop (`memo` None) every write
    plans afresh. Under the refine loop (`memo` the loop layout's own) a page
    is planned once, on its first write, and every later round takes the same
    points off the same gaps of the layout as the loop has corrected it.

    Re-planned each round, the planner undid the loop's corrections: the loop
    pushes a page whose render sits high down by its first gap, within the
    room the render measured, and the model -- which does not see the render
    -- read the push as a page at risk and took it back from the foot. y44 p1
    paid 16 -> 49 -> 64pt over three rounds and the loop stopped on an
    offset of 15.6 (0.1 with the planner off); y33's round 1 spilled and the
    loop published its round 0 (product within-2pt 0.73 -> 0.41). The plan
    held fixed, the loop measures and corrects on top of it as it does on
    top of the source spacing."""
    if memo is None:
        return fit_page(pg, content_w, lay, notes_h, body_line, plan,
                        output_profile, drop_first_gap=drop_first_gap)
    els = [el for ch in pg.chunks for el in ch.elements]
    # the notes area is part of the key: a write retried with its notes typed
    # into the body (`_write_docx`, notes_vetoed) is a different page
    key = (pg.number, round(notes_h, 1))
    held = memo.get(key)
    if held is None:
        out = fit_page(pg, content_w, lay, notes_h, body_line, plan,
                       output_profile, drop_first_gap=drop_first_gap)
        held = {}
        if out is not plan:
            for k, el in enumerate(els):
                if id(el) in out:
                    held[k] = (getattr(el, "space_before", 0.0) or 0.0) - \
                        out[id(el)]
        memo[key] = held
        return out
    if not held:
        return plan
    out = {}
    for k, d in held.items():
        if k < len(els):
            gap = getattr(els[k], "space_before", 0.0) or 0.0
            out[id(els[k])] = max(0.0, math.floor((gap - d) * 10 + 1e-6) / 10)
    return out
