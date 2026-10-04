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

Three properties the loop must have, each of which it once lacked:

  * **It converges.** The page mapper used to vote with each source page's first
    five distinctive lines, and repeated furniture fooled it: RFC 9110 reported
    `spill=312..329` for 194 source pages and the loop corrected the wrong pages
    -- 228 rendered pages became 340. Pages are now mapped by a monotone
    alignment anchored on every line that is unique in both documents, and
    a page with no unique line is placed by an ordinary diff inside the
    window those anchors fix (`_align`).
    And an overflowing page on which the gaps are already spent now has two
    more levers, cheapest-invisible first: <=3% line pitch, then table cell
    padding (`_apply`). What each lever spent is recorded.

  * **It is cheap.** The source PDF was re-read every round, every round started
    LibreOffice against a fresh profile, every figure was re-rasterised, and a
    round that improved nothing was followed by another. None of that changes
    the answer; all of it is gone (see `refine`).

  * **Its failure cannot cost the user the document.** A LibreOffice that is
    installed but crashes, hangs or writes nothing used to fail the whole
    conversion with no DOCX, although the open-loop DOCX had already been
    written. The best candidate produced so far is now published and the
    failure is raised as `OracleDegradedWarning` -- see `refine` for why that,
    and not silence or an error, is the contract.

Requesting refinement with no oracle installed at all is still an error
(`OracleUnavailableError`): that is a property of the installation, knowable
before any work, and silently converting open-loop on such a machine would make
the shipping profile mean the raw one there for every document.
"""
import os
import re
import shutil
import time
import warnings
from collections import Counter
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

# The two levers after the gaps. Both are spent only on a page that still
# overflows, only up to the overflow the render measured, and only once the
# gap step of that round has not covered it.
#
# Line pitch: 3% is the compression the design audit names as invisible
# (finding 5, "leading <=3%"): on 12pt leading it is 0.36pt a line, under the
# 0.5pt at which a reader starts to see a page run tight, and below the
# writer's own 0.1pt leading quantum times four. Cumulative over all rounds,
# measured from the inferred leading, never compounded.
MAX_LEADING_SQUEEZE = 0.03
# Table cell padding: top and bottom pads, at most halved. A pad is spacing,
# not text -- the gdocs profile already cuts the bottom pad first for the same
# reason (`docxout`, round-4 lever [C]) -- but a cell whose text touches its
# rules reads as broken, so half of the inferred pad always stays.
MAX_PAD_SQUEEZE = 0.50
# Added to a page's measured overflow, so the correction aims for a page that
# fits with a little room rather than one that fits exactly and spills again
# on the next renderer rounding (design audit C.2: "capacity - 2pt").
FIT_SAFETY_PT = 2.0
# A line shorter than this (whitespace removed) is not used as an alignment
# anchor. Page numbers, "1.2", single words in tables: short strings are
# unique by accident -- a source "41" and the render's "41" can be different
# pages' numbers -- while the alignment has thousands of real lines to use.
ANCHOR_MIN_CHARS = 8
# Bound on the gap-filling diff between two unique anchors (source lines x
# rendered lines in the window). The largest window measured on the raw
# renders of y01, y02, y17, y21 and y26 is 354 x 174 lines (RFC 9110's table
# of contents); 4M cells is some 65 times that and keeps a pathological
# window from costing more than the render did.
FILL_MAX_CELLS = 4_000_000


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


def _align(src_pages, out_pages):
    """Monotone line alignment: [(src_page, src_line, out_page, out_line)].

    Anchors are the lines whose text occurs exactly once in the source AND
    exactly once in the render. A running head, a repeated footer, a TOC entry
    that recurs as a heading: none of them can anchor, because none of them
    says where *one* piece of content went. The anchors are then cut to their
    longest chain that increases on both sides (patience-sorting LIS), which is
    what "pages cannot render out of order" means at line granularity. A stray
    coincidental match costs one anchor, not a page.

    This replaces voting with each page's first five distinctive lines, which
    the furniture of a long document defeats: on RFC 9110 every page opens
    with the same running head, the vote went to whichever rendered page
    happened to carry the most of the next few lines, and the loop reported
    312 spilled pages for 194 source pages and corrected the wrong ones.
    """
    def flat(pages):
        seq = []
        for pi, lines in enumerate(pages):
            for li, (t, _, _) in enumerate(lines):
                seq.append((t, pi, li))
        return seq

    s_seq, o_seq = flat(src_pages), flat(out_pages)
    sc = Counter(t for t, _, _ in s_seq)
    oc = Counter(t for t, _, _ in o_seq)
    o_pos = {t: k for k, (t, _, _) in enumerate(o_seq)
             if oc[t] == 1 and len(t) >= ANCHOR_MIN_CHARS}
    pairs = [(k, o_pos[t]) for k, (t, _, _) in enumerate(s_seq)
             if sc[t] == 1 and t in o_pos]
    # longest strictly increasing subsequence of the render positions, in
    # source order (both coordinates are then increasing)
    import bisect
    tails, tails_idx, prev = [], [], [-1] * len(pairs)
    for n, (_, ok) in enumerate(pairs):
        j = bisect.bisect_left(tails, ok)
        if j == len(tails):
            tails.append(ok)
            tails_idx.append(n)
        else:
            tails[j] = ok
            tails_idx[j] = n
        prev[n] = tails_idx[j - 1] if j > 0 else -1
    chain = []
    n = tails_idx[-1] if tails_idx else -1
    while n >= 0:
        chain.append(pairs[n])
        n = prev[n]
    chain.reverse()
    # Then fill between consecutive anchors with an ordinary sequence diff,
    # which may use repeated lines because it only ever pairs them inside the
    # window the unique anchors already fixed. A page whose every line repeats
    # elsewhere -- "This page intentionally left blank", a running-head-only
    # page -- otherwise has no anchor at all, and the pages around it cannot be
    # told apart: y02's cover spilled onto a second page and the loop never
    # saw it (its blank verso was unanchored), so it left every later page one
    # index late; y26 rendered 215 pages for 214 while measuring no spill.
    import difflib
    bounds = [(-1, -1)] + chain + [(len(s_seq), len(o_seq))]
    fill = []
    for (s0, o0), (s1, o1) in zip(bounds, bounds[1:]):
        ns, no = s1 - s0 - 1, o1 - o0 - 1
        if ns <= 0 or no <= 0 or ns * no > FILL_MAX_CELLS:
            continue
        a = [s_seq[k][0] for k in range(s0 + 1, s1)]
        b = [o_seq[k][0] for k in range(o0 + 1, o1)]
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for blk in sm.get_matching_blocks():
            for d in range(blk.size):
                if len(a[blk.a + d]) >= ANCHOR_MIN_CHARS:
                    fill.append((s0 + 1 + blk.a + d, o0 + 1 + blk.b + d))
    # ...but only for pages with no unique anchor of their own. Inside a
    # window a repeated line can still pair with the wrong copy -- a page's
    # running head with the one on the previous page's spill page -- and a
    # page that already has unique anchors would then appear to start a page
    # early: allowed everywhere, the fill took y18 from 147 rendered pages to
    # 163 and multiplied y17's measured offsets fourfold.
    anchored = {s_seq[sk][1] for sk, _ in chain}
    fill = [(sk, ok) for sk, ok in fill if s_seq[sk][1] not in anchored]
    if fill:
        chain = sorted(chain + fill)
    return [(s_seq[sk][1], s_seq[sk][2], o_seq[ok][1], o_seq[ok][2])
            for sk, ok in chain]


def _map_pages(src_pages, out_pages, anchors=None):
    """Which rendered page does each source page's content begin on?

    Returns [rendered_index or None] per source page: the rendered page of the
    page's first alignment anchor (`_align`), so the answer is monotone by
    construction. None means nothing on the page could be anchored -- a
    figure-only page, say -- and the page itself is neither corrected nor
    blamed (`_measure` charges any surplus to the page before it).
    """
    if anchors is None:
        anchors = _align(src_pages, out_pages)
    mapping = [None] * len(src_pages)
    for sp, _, op, _ in anchors:
        if mapping[sp] is None:
            mapping[sp] = op
    return mapping


def _body_bottom(lines, top, bottom):
    """Lowest line bottom inside the body band [top, bottom], or None.

    The band excludes header and footer parts, which a renderer draws in the
    margins on every page and which say nothing about whether the body fits.
    """
    ys = [yb for _, y0, yb in lines if y0 >= top - 1.0 and yb <= bottom + 1.0]
    return max(ys) if ys else None


def _measure(src_pdf, rendered_pdf, backend, src_cache=None, geom=None):
    """Spill, offset and overflow per source page, from one render.

    `src_cache` holds the source's page lines between rounds: the source never
    changes, and re-reading it each round was a full text extraction of the
    input per round -- 8.3s of y01's 87s, 14.6s of y17's 200s, every round.

    `geom` is `(page_h, body_top, body_bottom)` of the written document. With
    it, each spilled page also gets `need`: how many points must leave the page
    for it to fit, read off the render -- the height of the content that ran
    onto the following page(s), less the room it left behind at the foot of
    the page it started on, plus FIT_SAFETY_PT. None where the render shows no
    text to measure the overflow by.
    """
    if src_cache is not None and "lines" in src_cache:
        src = src_cache["lines"]
    else:
        src = _pages_text(src_pdf, backend)
        if src_cache is not None:
            src_cache["lines"] = src
    out = _pages_text(rendered_pdf, backend)
    anchors = _align(src, out)
    mapping = _map_pages(src, out, anchors)
    last_anchor = {}
    for sp_, _, op, _ in anchors:
        last_anchor[sp_] = op
    spill = []          # per source page: rendered pages consumed beyond one
    offset = []         # per source page: median dy of matched lines
    need = []           # per source page: pt to remove to fit, or None
    room = []           # per unspilled source page: pt free at its foot
    for i, lines in enumerate(src):
        ri = mapping[i]
        nxt, nxt_i = None, len(src)
        for j in range(i + 1, len(mapping)):
            if mapping[j] is not None:
                nxt, nxt_i = mapping[j], j
                break
        if ri is None:
            spill.append(0)
            offset.append(0.0)
            need.append(None)
            room.append(None)
            continue
        end = nxt if nxt is not None else len(out)
        if nxt_i == i + 1:
            # Every source page ends in a hard break, so the next page's start
            # bounds this one exactly.
            sp = max(0, (end - ri) - 1)
            own = True
        else:
            # Unanchored source pages follow -- nothing on them matched, even
            # inside the window the anchors fix (a figure-only page, a
            # two-column index whose entries interleave differently). The
            # rendered pages up to the next anchor are shared with them, and
            # charging all of them to this page is how RFC 9110's page 1 came
            # to "spill" over its own nine-page TOC under the old mapper. Only
            # the SURPLUS -- rendered pages beyond one per source page in the
            # run -- is a spill, and this page is the one the loop can act on,
            # so it carries it; without that, y26 rendered 215 pages for 214
            # while measuring none. Whether the surplus is this page's own
            # overflow is known only if its own anchors reach the spill page,
            # and the overflow is measured (`need`) only then.
            spare = (end - ri) - (nxt_i - i)
            sp = max(0, spare)
            own = last_anchor.get(i, ri) - ri >= sp
        spill.append(sp)
        # Offsets use only lines whose text is UNIQUE on both sides of the
        # comparison. A duplicated string ("1. Motivation" in a TOC and again
        # as a heading) would pair the heading with the TOC entry's y and feed
        # the corrector a garbage offset -- the same defect as first-line page
        # mapping, one level down.
        sc = Counter(t for t, _, _ in lines)
        oc = Counter(t for t, _, _ in out[ri])
        pos = {t: y0 for t, y0, _ in out[ri] if oc[t] == 1}
        ds = [pos[t] - y0 for t, y0, _ in lines
              if len(t) >= 12 and sc[t] == 1 and t in pos]
        ds.sort()
        offset.append(ds[len(ds) // 2] if ds else 0.0)
        nd = rm = None
        if geom is not None and ri + sp < len(out):
            _, top, bottom = geom
            first = _body_bottom(out[ri], top, bottom)
            if sp > 0 and own:
                tail = _body_bottom(out[ri + sp], top, bottom)
                if tail is not None:
                    left_behind = (bottom - first) if first is not None else 0.0
                    over = (sp - 1) * (bottom - top) + (tail - top)
                    nd = max(0.0, over - max(0.0, left_behind)) + FIT_SAFETY_PT
            elif sp == 0 and first is not None:
                rm = max(0.0, bottom - first)
        need.append(nd)
        room.append(rm)
    return {"spill": spill, "offset": offset, "need": need, "room": room,
            "out_pages": len(out), "src_pages": len(src),
            "anchors": len(anchors)}


# The lowest a footer is moved when the render shows the body needs the room:
# a quarter inch, the common minimum printable margin. Measured on the NIST
# class (y01, y02, y08, y09), whose re-wrapped body overruns the source's body
# box by up to ~50pt a page: with every footer at its source distance (35-52pt)
# those overruns spill -- y01 rendered 119 pages against 107 before footers
# were emitted -- and with the footers at 18pt the same document rendered 105.
FOOTER_FLOOR_PT = 18.0
# ...and only when that frees at least a line of body text. The EUR-Lex AI Act
# (y18) prints its footer 19.2pt up: lowering it 1.2pt bought no line and
# perturbed the loop off the 144/144 fixed point it otherwise reaches (145
# pages, word recall 0.99 -> 0.46). A 12pt line is the common body leading of
# the documents measured.
FOOTER_MIN_GAIN_PT = 12.0


def _lower_footers(lay: DocLayout) -> bool:
    """Spend the footer's own distance as correction currency, once.

    A footer at its source distance bounds the body exactly where the source
    did, which is right whenever the body fits -- and only then: a page whose
    re-wrapped text runs a few points past the source's body box spills a
    whole page. Before running footers were emitted at all, that overrun
    silently used the space the footer now occupies. When the render shows
    spills, the footers move down to FOOTER_FLOOR_PT and the bottom margin
    follows them; a document that renders without spilling never gets here,
    so its footers stay exactly where the source put them.
    """
    from .infer import _hf_extent
    changed = False
    parts = [lay.footer_default, lay.footer_even, lay.footer_first]
    for s in lay.hf_sections:          # running-head sections' own footers
        if s.parts:
            parts += [s.parts.get(k) for k in ("footer", "footer_even",
                                                "footer_first")]
    parts = [p for p in parts if p is not None]
    for part in parts:
        if part.distance - FOOTER_FLOOR_PT < FOOTER_MIN_GAIN_PT:
            continue
        old_top = part.distance + _hf_extent(part)
        part.distance = FOOTER_FLOOR_PT
        if lay.margin_b <= old_top + 0.5:
            # the body was bounded by this footer: follow it down
            lay.margin_b = round(min(lay.margin_b, max(
                14.0, FOOTER_FLOOR_PT + _hf_extent(part))), 1)
        changed = True
    return changed


def _paras_of(el):
    """Exact-leading paragraphs an element contributes to its page's height,
    with their line counts: (para, lines, row_key). `row_key` groups table cell
    paragraphs by row, since a row is only as tall as its tallest cell."""
    if isinstance(el, Para):
        if el.leading and el.leading > 1.0:
            yield el, max(1, el.src_lines or 1), None
    elif isinstance(el, TableEl):
        for ri, row in enumerate(el.rows):
            for cell in row:
                if not cell:
                    continue
                for p in cell.paras:
                    if p.leading and p.leading > 1.0:
                        yield p, max(1, p.src_lines or 1), (id(el), ri, id(cell))


def _leading_base(els, state):
    """Points of line pitch on the page, at the inferred (unsqueezed) leading.

    Table rows count once, at their tallest cell."""
    lead0 = state["lead0"]
    total, rows = 0.0, {}
    for el in els:
        for p, n, key in _paras_of(el):
            h = n * lead0.setdefault(id(p), p.leading)
            if key is None:
                total += h
            else:
                row = key[:2]
                cells = rows.setdefault(row, {})
                cells[key[2]] = cells.get(key[2], 0.0) + h
    total += sum(max(c.values()) for c in rows.values())
    return total


def _squeeze_leading(idx, els, want, state):
    """Compress this page's line pitch by up to MAX_LEADING_SQUEEZE in total.
    Returns the points it expects to save."""
    base = _leading_base(els, state)
    if base <= 1.0 or want <= 0.0:
        return 0.0
    done = state["lead_frac"].get(idx, 0.0)
    add = min(MAX_LEADING_SQUEEZE - done, want / base)
    if add <= 1e-4:
        return 0.0
    frac = done + add
    state["lead_frac"][idx] = frac
    lead0 = state["lead0"]
    for el in els:
        for p, _, _ in _paras_of(el):
            p.leading = lead0[id(p)] * (1.0 - frac)
    return add * base


def _squeeze_padding(idx, els, want, state):
    """Trim the top/bottom pads of this page's table cells, at most
    MAX_PAD_SQUEEZE of each. Returns the points it expects to save."""
    pad0 = state["pad0"]
    tables = [el for el in els if isinstance(el, TableEl)]
    base = 0.0
    for t in tables:
        for row in t.rows:
            per_row = 0.0
            for cell in row:
                if cell and len(cell.pad) >= 4:
                    p0 = pad0.setdefault(id(cell), tuple(cell.pad))
                    per_row = max(per_row, p0[0] + p0[2])
            base += per_row
    if base <= 0.5 or want <= 0.0:
        return 0.0
    done = state["pad_frac"].get(idx, 0.0)
    add = min(MAX_PAD_SQUEEZE - done, want / base)
    if add <= 1e-4:
        return 0.0
    frac = done + add
    state["pad_frac"][idx] = frac
    for t in tables:
        for row in t.rows:
            for cell in row:
                if cell and id(cell) in pad0:
                    p0 = pad0[id(cell)]
                    cell.pad = (p0[0] * (1.0 - frac), p0[1],
                                p0[2] * (1.0 - frac), p0[3]) + tuple(p0[4:])
    return add * base


def new_state():
    """Per-loop memory of what `_apply` has spent: the inferred leading and
    pads it squeezes from (so rounds never compound a squeeze), and the
    ledger the result reports."""
    return {"lead0": {}, "pad0": {}, "lead_frac": {}, "pad_frac": {},
            "ledger": {"gap_pt": 0.0, "gap_pages": set(),
                       "leading_pt": 0.0, "leading_pages": set(),
                       "padding_pt": 0.0, "padding_pages": set()}}


def ledger_summary(state):
    led = state["ledger"]
    return {"gap_pt": round(led["gap_pt"], 1),
            "gap_pages": len(led["gap_pages"]),
            "leading_pt": round(led["leading_pt"], 1),
            "leading_pages": len(led["leading_pages"]),
            "padding_pt": round(led["padding_pt"], 1),
            "padding_pages": len(led["padding_pages"])}


def _apply(lay: DocLayout, m, state=None) -> bool:
    """Fold the measurement back into the layout. True if anything changed."""
    if state is None:
        state = new_state()
    led = state["ledger"]
    needs = m.get("need") or []
    changed = False
    if any(m["spill"]):
        changed = _lower_footers(lay)
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
            taken = 0.0
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
                        taken += take
                        changed = True
            if taken > 0:
                led["gap_pt"] += taken
                led["gap_pages"].add(idx)
            # 1b. A dense page has no gap slack: y01's pages are set solid,
            # and the gaps alone took it from 107 rendered pages to 96 against
            # 80 and no further. When the render says more must go than the
            # gaps gave this round, spend the next-cheapest levers, in order,
            # and no more than the measured overflow.
            nd = needs[idx] if idx < len(needs) else None
            if nd is not None and nd > taken + 0.05:
                rest = nd - taken
                got = _squeeze_leading(idx, els, rest, state)
                if got > 0:
                    led["leading_pt"] += got
                    led["leading_pages"].add(idx)
                    rest -= got
                    changed = True
                if rest > 0.05:
                    got = _squeeze_padding(idx, els, rest, state)
                    if got > 0:
                        led["padding_pt"] += got
                        led["padding_pages"].add(idx)
                        changed = True

        # 2. constant per-page offset
        off = m["offset"][idx]
        if abs(off) > OFFSET_DEADBAND and abs(off) <= MAX_OFFSET_FIX \
                and m["spill"][idx] == 0:
            if off < 0:
                # Content sits too high: push it down, the first gap absorbs
                # it -- but never further than the render shows free at the
                # foot of the page. A push past that room is a spill
                # manufactured by the corrector: the next round sees it,
                # crushes the gaps back, and the loop oscillates instead of
                # converging.
                push = -off
                rooms = m.get("room") or []
                rm = rooms[idx] if idx < len(rooms) else None
                if rm is not None:
                    push = min(push, max(0.0, rm - FIT_SAFETY_PT))
                if push > OFFSET_DEADBAND:
                    _set_gap(els[0], _gap_of(els[0]) + push)
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


def _geom(lay):
    """(page_h, body_top, body_bottom) of the written document, or None.

    The body band is where the writer's own capacity model puts it
    (`docxout._body_capacity`): a header or footer taller than its margin
    pushes the body in, and its lines must not be read as body content."""
    try:
        from .docxout import _hf_height
        hd = lay.header_default.distance if lay.header_default else 0.0
        fd = lay.footer_default.distance if lay.footer_default else 0.0
        top = max(float(lay.margin_t), hd + _hf_height(lay.header_default))
        bottom = float(lay.page_h) - max(float(lay.margin_b),
                                         fd + _hf_height(lay.footer_default))
        return (float(lay.page_h), top, bottom)
    except (AttributeError, TypeError, ValueError):
        return None


def _freeze_seams(lay):
    try:
        from .docxout import _stack_fits
        for pg in lay.pages:
            if getattr(pg, "top_gap_fits", None) is None:
                pg.top_gap_fits = _stack_fits(pg, lay)
    except (AttributeError, TypeError):
        pass                    # not a layout this loop can reason about


def _score(m):
    return (abs(m["out_pages"] - m["src_pages"]), sum(m["spill"]),
            sum(abs(o) for o in m["offset"]))


def refine(lay: DocLayout, src_pdf: str, out_path: str, dpi: int = 240,
           rounds: int = 2, verbose: bool = False, render=None,
           output_profile: str = "standard", backend=None,
           image_report=None, report=None) -> str:
    """Write `lay`, then correct it against real renders. Returns out_path.

    `render(docx_path, tmp_dir) -> pdf_path | None` selects the oracle. It
    defaults to LibreOffice, but nothing in this loop is LibreOffice-specific:
    pass the Google Docs round-trip instead and the same machinery corrects for
    Docs. That matters, because the two renderers disagree substantially --
    Docs adds a one-off gap after the first heading plus roughly 3pt at every
    paragraph boundary, so a layout tuned against LibreOffice is NOT tuned for
    the renderer this project actually targets. A renderer with a `close()`
    is closed when the loop ends; one with `last_failure` explains a None.

    `backend` reads both the source and the rendered PDF. It is the same backend
    the parse used, passed down rather than re-chosen, so the loop cannot end up
    measuring one parser's line grouping against another's and correcting the
    layout for the difference.

    `report`, when given, is cleared and filled with what the loop did: each
    round's measurement and timings, which round was published, why the loop
    stopped, the levers it spent, and any oracle failure. Content-free.

    **Cost.** Measured on y01 (80 pages) in the canonical container, the loop
    was 87s against ~10s open-loop: 58s reading text back out of PDFs (the
    unchanged source re-read every round), 13s of writes, 8s of LibreOffice.
    The source is now read once, figures are rasterised once, the LibreOffice
    profile is kept for the loop (the cold start is the cost on Windows), and
    the loop stops at the first round that improves nothing -- a further round
    corrects from a layout already measured to be no better.

    **An oracle failure degrades; it does not fail.** If the renderer returns
    nothing, raises an `OracleError` other than `OracleCleanupError`, or
    renders something that cannot be read, the loop stops and publishes the
    best candidate measured so far -- or, if the failure came in round 0, the
    round-0 write, which is byte-for-byte the open-loop DOCX. It then raises
    `OracleDegradedWarning`, *before* publishing. By default Python prints it
    and the conversion succeeds; a caller who would rather have no file than an
    unrefined one escalates it (`warnings.simplefilter("error",
    OracleDegradedWarning)`) and gets the old behaviour exactly: an exception,
    and the destination untouched. The gate does that, so a crashed oracle can
    never be measured as the shipping product. A cleanup failure stays an
    error -- the document is still in somebody else's storage -- and so does a
    writer failure, which is not the oracle's.
    """
    from .backend import get_backend
    from .docxout import write_docx
    from .errors import (OracleCleanupError, OracleDegradedWarning,
                         OracleError, OutputWriteError)
    from .io import Workspace, publish
    from .verify import SOFFICE

    rep = report if report is not None else {}
    rep.clear()
    rep.update({"rounds": [], "published_round": None, "stopped": None,
                "oracle_failure": None, "levers": None,
                "levers_tried": None})
    if backend is None:
        backend = get_backend()
    if render is None and SOFFICE is None:
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
    if rounds <= 0:
        publish(lambda tmp: write_docx(lay, tmp, dpi=dpi,
                                       output_profile=output_profile,
                                       backend=backend,
                                       image_report=image_report), out_path)
        return out_path
    if render is None:
        from .targets import LibreOfficeRenderer
        render = LibreOfficeRenderer()

    state = new_state()
    src_cache = {}
    clip_cache = {}
    geom = _geom(lay)
    # Opt the pages whose stack fits their box into the page-top-gap-keeping
    # seam (B23; `PageLayout.top_gap_fits`). Under the loop the kept gap is a
    # lever it can correct; open-loop it is not, which is why only the loop
    # sets it. Decided once, on the layout as inferred: decided per round, a
    # page the loop had just squeezed started honouring a gap it had been
    # dropping, moved down by that gap and spilled again -- y18 rendered 191
    # pages after round 1 that way against 174 with the decision held, and
    # finished on 153 against 147.
    _freeze_seams(lay)
    best_path, best_score = None, None
    first_candidate = None
    failure = None
    # Render-feedback candidates are deliberately private.  In particular, do
    # not use ``<out_path>.best``: that predictable public-side artifact races
    # with another conversion and survives a failed run looking deliverable.
    # The final candidate alone is copied through ``publish`` once all renderer
    # work has finished, so failures in a round cannot touch ``out_path``.
    with Workspace() as workspace:
        td = workspace.path
        try:
            for rnd in range(rounds + 1):
                row = {"round": rnd}
                # what this round's candidate carries, for the report
                spent = ledger_summary(state)
                # write_docx is pure: `lay` survives the round unmodified.
                candidate = workspace.file("candidate-%d.docx" % rnd)
                # Each round rewrites the same layout, so the image tally is
                # per-write rather than cumulative: `write_docx` clears it first.
                t0 = time.monotonic()
                write_docx(lay, candidate, dpi=dpi,
                           output_profile=output_profile, backend=backend,
                           image_report=image_report, clip_cache=clip_cache)
                row["write_ms"] = int((time.monotonic() - t0) * 1000)
                if first_candidate is None:
                    first_candidate = candidate
                t0 = time.monotonic()
                try:
                    rendered = render(candidate, td)
                except OracleCleanupError:
                    raise
                except OracleError as e:
                    rendered, why = None, "%s: %s" % (type(e).__name__,
                                                      e.message)
                else:
                    why = getattr(render, "last_failure", None) or \
                        "the render oracle produced no output"
                row["render_ms"] = int((time.monotonic() - t0) * 1000)
                if rendered is None:
                    failure = {"round": rnd, "reason": why}
                    rep["rounds"].append(row)
                    break
                t0 = time.monotonic()
                try:
                    # the body box of the document THIS round wrote: the
                    # footer lever (`_lower_footers`) moves its bottom
                    geom = _geom(lay)
                    m = _measure(src_pdf, rendered, backend,
                                 src_cache=src_cache, geom=geom)
                except Exception as e:
                    # The render exists but cannot be read back. That is the
                    # self-check failing, not the conversion.
                    failure = {"round": rnd,
                               "reason": "the rendered PDF could not be "
                                         "measured (%s)" % type(e).__name__}
                    rep["rounds"].append(row)
                    break
                row["measure_ms"] = int((time.monotonic() - t0) * 1000)
                score = _score(m)
                need_total = sum(n for n in (m.get("need") or ())
                                 if n is not None)
                row.update(out_pages=m["out_pages"], src_pages=m["src_pages"],
                           spill=sum(m["spill"]),
                           offset=round(score[2], 1),
                           need=round(need_total, 1))
                rep["rounds"].append(row)
                if verbose:
                    print("  refine round %d: pages %d/%d spill=%d "
                          "|offset|=%.1f need=%.1f  (write %.1fs, render "
                          "%.1fs, measure %.1fs)"
                          % (rnd, m["out_pages"], m["src_pages"],
                             sum(m["spill"]), score[2], need_total,
                             row["write_ms"] / 1000.0,
                             row["render_ms"] / 1000.0,
                             row["measure_ms"] / 1000.0))
                if best_score is None or score < best_score:
                    best_score = score
                    best_path = workspace.file("best.docx")
                    shutil.copyfile(candidate, best_path)
                    rep["published_round"] = rnd
                    rep["levers"] = spent
                elif rnd > 0 and (score[1] == 0 or score[:2] > best_score[:2]):
                    # A round that made nothing better, and that the next round
                    # cannot be expected to fix: nothing spills, so all that is
                    # left to move is offsets, and they have stopped improving
                    # (an oscillation); or pages and spills got worse than the
                    # best, so the corrections are diverging. Either way the
                    # next round would correct from a layout already measured
                    # to be no better, at the price of another write and render.
                    #
                    # A round that still spills and is merely no better goes
                    # on: the gap step takes half of what is left each round,
                    # so a stalled spill can still close -- x11 sat at 3 pages
                    # for two rounds and fitted its 2 on the third.
                    rep["stopped"] = "no-improvement"
                    break
                if score[0] == 0 and score[1] == 0 and score[2] < 1.0:
                    rep["stopped"] = "converged"
                    break
                if rnd == rounds:
                    rep["stopped"] = "max-rounds"
                    break
                if not _apply(lay, m, state):
                    rep["stopped"] = "nothing-to-correct"
                    break
        finally:
            # A session-holding renderer (LibreOffice's private profile) is
            # released whatever happened above.
            close = getattr(render, "close", None)
            if callable(close):
                close()
        # `levers` is what the published candidate carries; `levers_tried`
        # includes rounds that were measured and not kept.
        rep["levers_tried"] = ledger_summary(state)
        if rep["levers"] is None:
            rep["levers"] = ledger_summary(new_state())
        if failure is not None:
            rep["stopped"] = "oracle-failed"
            rep["oracle_failure"] = failure
            source = best_path or first_candidate
            measured = best_path is not None
            if not measured:
                rep["published_round"] = None
            if verbose:
                print("  refine: oracle failed in round %d (%s)"
                      % (failure["round"], failure["reason"]))
            # Raised before publishing: escalated to an error, it leaves the
            # destination exactly as it was.
            warnings.warn(OracleDegradedWarning(
                "the render oracle failed in refine round %d (%s); published "
                "%s instead" % (
                    failure["round"], failure["reason"],
                    ("the best measured round (%d)" % rep["published_round"])
                    if measured else "the unrefined open-loop DOCX"),
                round_index=failure["round"], reason=failure["reason"],
                published_round=rep["published_round"]), stacklevel=2)
        else:
            source = best_path
        # keep the best round, not merely the last
        if not source or not os.path.exists(source):
            raise OutputWriteError(
                "refinement did not produce a final DOCX; %s is unchanged"
                % os.path.basename(out_path))
        if verbose and failure is None:
            lv = rep["levers"]
            print("  refine: kept round %s of %d (%s); spent gaps %.1fpt/%d "
                  "pages, leading %.1fpt/%d pages, padding %.1fpt/%d pages"
                  % (rep["published_round"], len(rep["rounds"]),
                     rep["stopped"], lv["gap_pt"], lv["gap_pages"],
                     lv["leading_pt"], lv["leading_pages"],
                     lv["padding_pt"], lv["padding_pages"]))
        publish(lambda tmp, src=source: shutil.copyfile(src, tmp), out_path)
    return out_path
