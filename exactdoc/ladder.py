"""Quality ladder: choose, per paragraph, how much editability to spend.

Word re-flows text with a greedy first-fit line breaker. Some producers do not:
TeX runs Knuth-Plass, a global optimiser that also *shrinks* inter-word glue, so
a TeX line can legitimately carry more words than the same text at natural
spacing ever fits. Word cannot reproduce that line, breaks earlier, and the
paragraph gains a line. Multiply by a few hundred paragraphs and a 15-page
paper renders as 19.

No amount of tuning fixes that for every paragraph, because the two line
breakers are not the same algorithm. So instead of pretending, spend
editability only where it is actually needed, one paragraph at a time:

    flow         Word's own wrapping reproduces the source line count.
                 Fully editable. Always preferred.
    line-locked  Source line breaks are pinned with soft breaks. The line
                 count -- and therefore the pagination -- is exact; editing
                 the text no longer re-flows that paragraph cleanly.

The choice is reported per conversion rather than applied silently, because a
document that is 60% line-locked is a materially different artifact from one
that is 2% line-locked, and the user is entitled to know which they received.

Prediction uses base-14 metrics, which are exact for the metric-compatible
families the writer maps onto (Helvetica->Arial, Times->Times New Roman,
Courier->Courier New). Paragraphs whose font has no such equivalent are left
in flow: a prediction we cannot trust is not a reason to spend editability.

STATUS: built, measured, and OFF by default (convert(ladder=False)).

It was built to fix LaTeX page inflation and does not, because inflation there
is not caused by re-wrap. Measured on four LaTeX papers it was neutral at best
and cost three pages on one. The actual cause, found afterwards by reading the
element list instead of the metrics: inline math sub/superscripts arrive as
separate text blocks at their own baselines, and each becomes its own
single-line paragraph -- eight paragraphs for two source lines on one measured
page. Every fragment then consumes a full line, math-heavy pages overflow, and
because each source page ends in a hard break, one overflow costs a whole page.

That belongs in _merge_row_lines (fold small vertically-offset fragments into
the adjacent baseline row as super/subscript runs), not here. The ladder stays
because the machinery is sound and the trade it encodes is real -- but it will
not be switched on until it is measured to help something.

An early version pinned line breaks WITHOUT checking each line still fits.
That is strictly worse than doing nothing: Word honours the soft break and
then wraps the overflow too, so a 15-page paper went from 24 rendered pages to
27. Locked lines are now compressed with negative tracking to make them fit,
and refused outright past MAX_TRACK.
"""
from typing import List, Optional

from .layout import DocLayout, Para, Run, TableEl
from .fonts import map_font

# Base-14 metric equivalents. Anything absent is "not predictable" -- see below.
_B14 = {
    "arial": ("helv", "hebo", "heit", "hebi"),
    "carlito": ("helv", "hebo", "heit", "hebi"),
    "times new roman": ("tiro", "tibo", "tiit", "tibi"),
    "courier new": ("cour", "cobo", "cour", "cobo"),
}
MIN_LINES = 2          # single-line paragraphs have no wrap to preserve
SLACK_PT = 0.5         # tolerance when fitting, in points
MAX_TRACK = 0.28       # pt/char; beyond this compression is visible as mangling


def _b14(family: str, bold: bool, italic: bool) -> Optional[str]:
    ent = _B14.get((family or "").lower())
    if ent is None:
        return None
    return ent[3] if (bold and italic) else ent[1] if bold else ent[2] if italic else ent[0]


def _predictable(p: Para) -> bool:
    for r in p.runs:
        if r.text and not r.is_tab:
            fam = map_font(r.font, mono=r.mono, serif=r.serif)
            if _b14(fam, r.bold, r.italic) is None:
                return False
    return True


def _measurable(ch: str) -> bool:
    """Is this character one the base-14 metrics can actually measure?

    `_predictable` checks the FAMILY maps to a base-14 name. It never checked
    that the CHARACTERS are in that font's repertoire, and base-14 faces are
    WinAnsi. Measured with `fitz.get_text_length` at 11pt: Latin resolves glyph
    by glyph ("aaaaaaaaaa" 48.84pt vs "mmmmmmmmmm" 85.58pt), while Cyrillic and
    Greek return the SAME width for narrow and wide letters -- 13.75pt either
    way, a constant fallback. Per character: Latin 4.95pt, Cyrillic 1.47pt,
    Greek 1.64pt, CJK 1.10pt. The metrics are not approximating those scripts,
    they are not seeing them.
    """
    try:
        ch.encode("cp1252")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


# Scripts written without spaces. A renderer breaking these picks its own point
# anywhere in the run, so it cannot reproduce the source's break by luck --
# which is the one case where pinning text the metrics cannot measure still pays.
_CONTINUA = ((0x3040, 0x30FF),    # Hiragana + Katakana
             (0x3400, 0x4DBF),    # CJK ext A
             (0x4E00, 0x9FFF),    # CJK unified
             (0xAC00, 0xD7AF),    # Hangul syllables
             (0xF900, 0xFAFF))    # CJK compatibility

# A stray unmeasurable glyph -- a Wingdings bullet in a private-use codepoint --
# is not a script change. l1_word_native's list paragraph carries two U+F0B7
# among ~200 Latin characters; vetoing on one character cost it word_recall
# 1.0 -> 0.9931 for nothing. x06's Cyrillic body is 71% of its paragraph.
UNMEASURED_MAX_FRAC = 0.05


def _continuum_frac(text: str) -> float:
    n = tot = 0
    for ch in text:
        if ch.isspace():
            continue
        tot += 1
        o = ord(ch)
        if any(lo <= o <= hi for lo, hi in _CONTINUA):
            n += 1
    return n / max(1, tot)


def _lockable_text(text: str) -> bool:
    """May a lock be placed on this text at all?

    Two different reasons a lock survives, and one it does not.

    **Measured text.** Every character is in the base-14 repertoire, so
    `predict_lines` and `_seg_width` mean what they say. This is c1_whitepaper's
    cover band and l1_word_native's headings.

    **A script continuum.** CJK, Kana and Hangul are written without spaces, so
    the renderer breaks them wherever its own measurement lands and has no way
    to reproduce the source's break. The metrics cannot see these glyphs either
    -- c4_i18n's CJK measures 1.10pt per character against Latin's 4.95 -- but
    the error is UNIFORM across the run, so a width fraction still maps onto the
    right character and the cut lands where the source broke. Measured: locking
    c4_i18n moved within2pt 0.1966 -> 0.5043.

    **Unmeasured text that wraps at spaces.** Cyrillic, Greek and Vietnamese
    tone marks are outside WinAnsi, so the metrics are blind to them -- but they
    break at spaces exactly like Latin, so the renderer already reproduces the
    source's wrap on its own. There is nothing for a lock to restore and a great
    deal for it to disturb: x06_lo_euro_scripts went dy_p50 1.5 -> 13.0 and
    within2pt 0.6165 -> 0.2184. Refused.
    """
    if _continuum_frac(text) >= 0.5:
        return True
    tot = unmeasured = 0
    for ch in text:
        if ch.isspace():
            continue
        tot += 1
        if not _measurable(ch):
            unmeasured += 1
    return (unmeasured / max(1, tot)) <= UNMEASURED_MAX_FRAC


def predict_lines(p: Para, avail: float, metrics=None) -> Optional[int]:
    """Greedy first-fit, the way Word breaks. None if not predictable.

    This is the one caller in the tree that genuinely needs to *shape* text: it
    predicts a re-wrap, so by definition there is no source line to measure and
    `Para.src_widths` cannot answer. `metrics` is a real capability requirement
    and `NullMetrics` still makes every paragraph unpredictable -- the same
    answer a non-base-14 font has always produced, and which turns the ladder
    into a no-op.

    **That is no longer what a default install gets.** The default shaper is
    `metrics.Base14Metrics`, which needs no extra, so this predicts on every
    installation rather than only where PyMuPDF happened to be present. The
    passage here used to say the ladder does nothing without the `[mupdf]` extra
    and that nothing shipped changed because the ladder was off by default; both
    halves stopped being true -- the first at 2026-08-06, the second at c9d36df
    when the default was turned on.

    Note the default argument below is still `NullMetrics`, deliberately: a
    caller who passes no metrics has expressed no capability, and this function
    must not silently reach for a shaper on their behalf. `convert` and
    `docxout` pass one explicitly.
    """
    if metrics is None:
        from .metrics import NullMetrics
        metrics = NullMetrics()
    words = []
    for r in p.runs:
        if r.is_tab or not r.text:
            continue
        fam = map_font(r.font, mono=r.mono, serif=r.serif)
        fn = _b14(fam, r.bold, r.italic)
        if fn is None:
            return None
        for w in r.text.replace("\n", " ").split(" "):
            if w:
                words.append((w, fam, r.size, r.bold, r.italic))
    if not words:
        return 1
    cache = {}
    unmeasurable = []

    def wid(t, fam, sz, bold, italic):
        key = (t, fam, sz, bold, italic)
        if key not in cache:
            w = metrics.text_width(t, fam, sz, bold=bold, italic=italic)
            if w is None:
                unmeasurable.append(key)
                w = 0.0
            cache[key] = w
        return cache[key]

    n, cur, first = 1, 0.0, True
    room0 = avail - max(0.0, p.first_indent)
    for w, fam, sz, bold, italic in words:
        ww = wid(w, fam, sz, bold, italic)
        room = room0 if n == 1 else avail
        if first:
            cur = ww
            first = False
            continue
        add = wid(" ", fam, sz, bold, italic) + ww
        if cur + add > room + SLACK_PT:
            n += 1
            cur = ww
        else:
            cur += add
    # An unmeasurable word made every width beyond it meaningless, so the count
    # is not a prediction. Say "unpredictable" rather than return a number
    # computed partly from zeros -- the caller's whole contract is that it acts
    # only on a prediction it trusts.
    if unmeasurable:
        return None
    return n


def _seg_width(seg_runs, cache, metrics) -> float:
    """Width of one locked line's runs. -1.0 when unmeasurable."""
    w = 0.0
    for r in seg_runs:
        if r.is_tab or not r.text:
            continue
        fam = map_font(r.font, mono=r.mono, serif=r.serif)
        if _b14(fam, r.bold, r.italic) is None:
            return -1.0
        key = (r.text, fam, r.size, r.bold, r.italic)
        if key not in cache:
            got = metrics.text_width(r.text, fam, r.size, bold=r.bold,
                                     italic=r.italic)
            if got is None:
                return -1.0
            cache[key] = got
        w += cache[key]
    return w


def _slice_runs(runs: List[Run], a: int, b: int) -> List[Run]:
    """Copy the runs covering text offsets [a, b)."""
    out, pos = [], 0
    for r in runs:
        if r.is_tab:
            continue
        n = len(r.text)
        s, e = max(a, pos), min(b, pos + n)
        if s < e:
            c = Run(text=r.text[s - pos:e - pos], font=r.font, size=r.size,
                    color=r.color, bold=r.bold, italic=r.italic, mono=r.mono,
                    serif=r.serif, link=r.link, underline=r.underline,
                    superscript=r.superscript, field=r.field)
            out.append(c)
        pos += n
    return out


def _lock(p: Para, avail: float, metrics) -> bool:
    """Pin the source line breaks -- and make each pinned line actually fit.

    A soft break alone is not enough. TeX fits a line by *shrinking* inter-word
    glue, so at natural spacing that same text is wider than the column; Word
    honours the soft break and then wraps the overflow as well, producing MORE
    lines than doing nothing. (Measured: locking without fitting took a 15-page
    paper from 24 rendered pages to 27.)

    So each locked line is measured, and any line that would overflow is
    compressed with negative character tracking -- reproducing, crudely but
    effectively, the glue shrink TeX applied. Lines needing more compression
    than MAX_TRACK are refused: past that, text starts to look mangled, and a
    correct-looking extra line beats a cramped one.
    """
    if p.src_lines < MIN_LINES:
        return False
    widths = p.src_widths or []
    if len(widths) != p.src_lines or sum(widths) <= 0:
        return False
    text = "".join(r.text for r in p.runs if not r.is_tab)
    if "\n" in text or len(text) < 8:
        return False

    cum, targets, run_w = 0.0, [], sum(widths)
    for w in widths[:-1]:
        cum += w
        targets.append(cum / run_w * len(text))
    cuts = []
    for t in targets:
        lo = int(max(1, min(len(text) - 1, t)))
        best = None
        for d in range(0, 24):
            for j in (lo - d, lo + d):
                if 0 < j < len(text) and text[j] == " ":
                    best = j
                    break
            if best is not None:
                break
        if best is None or (cuts and best <= cuts[-1]):
            return False
        cuts.append(best)
    if len(cuts) != p.src_lines - 1:
        return False

    bounds = [0] + [c + 1 for c in cuts] + [len(text)]   # skip the space itself
    cache, segments = {}, []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        seg = _slice_runs(p.runs, a, b)
        if not seg:
            return False
        w = _seg_width(seg, cache, metrics)
        if w < 0:
            return False
        room = avail - (max(0.0, p.first_indent) if i == 0 else 0.0)
        nch = sum(len(r.text) for r in seg)
        track = 0.0
        if w > room - SLACK_PT and nch > 1:
            track = -(w - room + SLACK_PT) / (nch - 1)
            if -track > MAX_TRACK:
                return False
        segments.append((seg, track))

    new_runs = []
    for i, (seg, track) in enumerate(segments):
        for r in seg:
            r.char_spacing = round(track, 3)
        if i < len(segments) - 1 and seg:
            seg[-1].text += "\n"
        new_runs.extend(seg)
    if not new_runs:
        return False
    p.runs = new_runs
    p.line_breaks = True
    p.fidelity = "line-locked"
    return True


def _leading_of(p: Para) -> float:
    if p.leading and p.leading > 0.5:
        return p.leading
    size = max((r.size for r in p.runs if r.text), default=10.0)
    return max(4.0, size * 1.16)


def _el_height(el, width, metrics) -> float:
    """Flow height an element is predicted to occupy, in points.

    Deliberately a rough model: it exists to answer "does this page have room
    for another line?", not to place anything. Where a prediction is unavailable
    the source's own line count is used, which is the honest fallback.
    """
    if isinstance(el, Para):
        n = None
        if el.runs and _predictable(el):
            n = predict_lines(el, max(20.0, width), metrics)
        if n is None:
            n = max(1, el.src_lines or 1)
        return (el.space_before or 0.0) + n * _leading_of(el) + (el.space_after or 0.0)
    if isinstance(el, TableEl):
        if el.bbox:
            h = el.bbox[3] - el.bbox[1]
        else:
            h = sum(rh or 12.0 for rh in el.row_heights) or 12.0
        return (el.space_before or 0.0) + h + (el.space_after or 0.0)
    h = getattr(el, "height", None)
    if h is None:
        h = getattr(el, "thickness", 0.0) or 0.0
    return (getattr(el, "space_before", 0.0) or 0.0) + h \
        + (getattr(el, "space_after", 0.0) or 0.0)


# How empty a page must be before a flow lock may spend height on it.
#
# The height model below is deliberately rough -- it uses predicted line counts,
# which are exactly the quantity in doubt -- so an absolute "does it fit?" test
# is not trustworthy near a full page. Measured page slack as a fraction of
# capacity, against whether locking that page helped:
#
#     l1_word_native  p1   59%   3 locks, dy_p50 26.69 -> 2.71      helped
#     c4_i18n         p1   43%   2 locks, within2pt 0.1966 -> 0.5043 helped
#     x11 p2               22%   2 locks, dy_p50 46.6 -> 57.85       hurt
#     x10             p1   14%   2 locks, pages 2/2 -> 2/3           hurt
#     x11 p1                2%   3 locks                             hurt
#
# A quarter of a US-Letter text column is about thirteen lines of headroom. The
# rule is not "will it fit" but "is there room to be wrong about whether it
# fits", which is the honest question when the model's own inputs are the
# suspect quantity. It is applied to the height REMAINING AFTER the lock, so a
# page full of candidates stops accepting them while it is still a quarter
# empty rather than filling itself one lock at a time.
PAGE_SLACK_FRAC = 0.25


def _page_capacity(lay: DocLayout, page_index: int) -> float:
    cap = lay.page_h - lay.margin_t - lay.margin_b
    if page_index == 0 and lay.cover_band is not None and lay.cover_band.bbox:
        cap = lay.page_h - lay.cover_band.bbox[3] - lay.margin_b
    return max(1.0, cap)


def apply_ladder(lay: DocLayout, enabled: bool = True, metrics=None) -> dict:
    """Decide flow vs line-locked for every paragraph. Returns a report.

    `metrics` must be able to shape text (see `predict_lines`). Without it every
    paragraph counts as unpredictable and the ladder changes nothing, which the
    report says in the clear -- `text_metrics` names what was used.

    Two things a lock is not allowed to do, both learned from the expansion
    corpus after the default was turned on (docs/evidence/ladder-gating-
    2026-08-05.json):

    * **Cut blind.** The metrics are keyed on the font FAMILY and are simply
      absent for characters outside its WinAnsi repertoire, so a prediction can
      exist and be meaningless. See `_lockable_text`.
    * **Spend page height the page has not got.** Locking pins the source's line
      count, and where the renderer would have used fewer lines that is taller.
      In a table cell the row height is declared by the source and restoring it
      is the entire point (c1_whitepaper's cover band). In free flow it can push
      a page over: x10_chrome_tables_plain went 2/2 -> 2/3 and its word recall
      0.9963 -> 0.8657 even though the same locks improved its dy_p50 17.2 ->
      1.65. So flow locks that ADD lines are taken only while the page they sit
      on is predicted to have room, in document order.
    """
    rep = {"flow": 0, "line-locked": 0, "unpredictable": 0, "short": 0,
           "lock_failed": 0, "unmeasured_script": 0, "no_page_room": 0}
    if metrics is None:
        from .metrics import NullMetrics
        metrics = NullMetrics()
    rep["text_metrics"] = getattr(metrics, "name", "?")
    if not enabled:
        return rep

    def visit(p: Para, avail: float, slack: Optional[list]):
        """`slack` is [remaining_pt, capacity_pt], or None for a table cell.

        None means "this height is declared by the source, not spent by me" --
        restoring a cell's own row height is what the lock is FOR, so a full
        page must not veto it.
        """
        if p.src_lines < MIN_LINES or not p.runs:
            rep["short"] += 1
            return
        if not _predictable(p):
            rep["unpredictable"] += 1
            return
        text = "".join(r.text for r in p.runs if not r.is_tab)
        if not _lockable_text(text):
            rep["unmeasured_script"] += 1
            return
        pred = predict_lines(p, avail, metrics)
        if pred is None:
            rep["unpredictable"] += 1
            return
        if pred == p.src_lines:
            rep["flow"] += 1
            return
        cost = (p.src_lines - pred) * _leading_of(p)
        # A lock that REMOVES lines can never overflow a page, so it is never
        # asked. One that adds them must leave the page still a quarter empty
        # AFTERWARDS -- checking only the height before means a page with many
        # candidates accepts them one at a time until it is full.
        if slack is not None and cost > 0 and \
                (slack[0] - cost) < PAGE_SLACK_FRAC * slack[1]:
            rep["no_page_room"] += 1
            return
        if _lock(p, avail, metrics):
            rep["line-locked"] += 1
            if slack is not None and cost > 0:
                slack[0] -= cost
        else:
            rep["lock_failed"] += 1

    for pi, pg in enumerate(lay.pages):
        used = 0.0
        for ch in pg.chunks:
            width = lay.content_w
            if ch.n_cols > 1:
                width = (lay.content_w - ch.col_gap * (ch.n_cols - 1)) / ch.n_cols
            used += ch.pre_gap or 0.0
            for el in ch.elements:
                used += _el_height(el, width, metrics) / max(1, ch.n_cols)
        cap = _page_capacity(lay, pi)
        slack = [cap - used, cap]          # [remaining height, page capacity]
        for ch in pg.chunks:
            width = lay.content_w
            if ch.n_cols > 1:
                width = (lay.content_w - ch.col_gap * (ch.n_cols - 1)) / ch.n_cols
            for el in ch.elements:
                if isinstance(el, Para):
                    visit(el, max(20.0, width - el.left_indent - el.right_indent),
                          slack)
                elif isinstance(el, TableEl):
                    for ri, row in enumerate(el.rows):
                        for ci, cell in enumerate(row):
                            if cell is None:
                                continue
                            cw = el.col_widths[ci] if ci < len(el.col_widths) else 100.0
                            for cp in cell.paras:
                                # A cell's height is declared by the source; the
                                # lock restores it rather than inventing it.
                                visit(cp, max(20.0, cw - 8.0), None)
    return rep


def summarise(rep: dict) -> str:
    total = sum(v for v in rep.values() if isinstance(v, int)) or 1
    locked = rep.get("line-locked", 0)
    metrics = rep.get("text_metrics", "?")
    # "none" no longer means "this install lacks an extra" -- the default shaper
    # needs none. It now means someone asked for it, so the message says that
    # rather than blaming a missing package the reader has not got.
    note = ("  [text metrics: none -- measurement is switched off, so every "
            "paragraph is unpredictable]"
            if metrics == "none" else "  [text metrics: %s]" % metrics)
    # Every refusal reason is named. They are counted in `total` either way, and
    # a summary that folds 1,745 page-room refusals into an unexplained
    # denominator reads as "the ladder did almost nothing" when in fact it
    # declined to do something specific, for a stated reason.
    return ("%d paragraphs: %d flow, %d line-locked (%.0f%%), "
            "%d single-line, %d unpredictable font, %d lock failed, "
            "%d unmeasured script, %d no page room%s"
            % (total, rep.get("flow", 0), locked, 100.0 * locked / total,
               rep.get("short", 0), rep.get("unpredictable", 0),
               rep.get("lock_failed", 0), rep.get("unmeasured_script", 0),
               rep.get("no_page_room", 0), note))
