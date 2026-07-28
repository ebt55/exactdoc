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


def predict_lines(p: Para, avail: float) -> Optional[int]:
    """Greedy first-fit, the way Word breaks. None if not predictable."""
    import fitz
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
                words.append((w, fn, r.size))
    if not words:
        return 1
    cache = {}

    def wid(t, fn, sz):
        key = (t, fn, sz)
        if key not in cache:
            try:
                cache[key] = fitz.get_text_length(t, fontname=fn, fontsize=sz)
            except Exception:
                cache[key] = len(t) * sz * 0.5
        return cache[key]

    n, cur, first = 1, 0.0, True
    room0 = avail - max(0.0, p.first_indent)
    for w, fn, sz in words:
        ww = wid(w, fn, sz)
        room = room0 if n == 1 else avail
        if first:
            cur = ww
            first = False
            continue
        add = wid(" ", fn, sz) + ww
        if cur + add > room + SLACK_PT:
            n += 1
            cur = ww
        else:
            cur += add
    return n


def _seg_width(seg_runs, cache) -> float:
    import fitz
    w = 0.0
    for r in seg_runs:
        if r.is_tab or not r.text:
            continue
        fam = map_font(r.font, mono=r.mono, serif=r.serif)
        fn = _b14(fam, r.bold, r.italic)
        if fn is None:
            return -1.0
        key = (r.text, fn, r.size)
        if key not in cache:
            try:
                cache[key] = fitz.get_text_length(r.text, fontname=fn, fontsize=r.size)
            except Exception:
                return -1.0
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


def _lock(p: Para, avail: float) -> bool:
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
        w = _seg_width(seg, cache)
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


def apply_ladder(lay: DocLayout, enabled: bool = True) -> dict:
    """Decide flow vs line-locked for every paragraph. Returns a report."""
    rep = {"flow": 0, "line-locked": 0, "unpredictable": 0, "short": 0,
           "lock_failed": 0}
    if not enabled:
        return rep

    def visit(p: Para, avail: float):
        if p.src_lines < MIN_LINES or not p.runs:
            rep["short"] += 1
            return
        if not _predictable(p):
            rep["unpredictable"] += 1
            return
        pred = predict_lines(p, avail)
        if pred is None:
            rep["unpredictable"] += 1
            return
        if pred == p.src_lines:
            rep["flow"] += 1
            return
        if _lock(p, avail):
            rep["line-locked"] += 1
        else:
            rep["lock_failed"] += 1

    for pg in lay.pages:
        for ch in pg.chunks:
            width = lay.content_w
            if ch.n_cols > 1:
                width = (lay.content_w - ch.col_gap * (ch.n_cols - 1)) / ch.n_cols
            for el in ch.elements:
                if isinstance(el, Para):
                    visit(el, max(20.0, width - el.left_indent - el.right_indent))
                elif isinstance(el, TableEl):
                    for ri, row in enumerate(el.rows):
                        for ci, cell in enumerate(row):
                            if cell is None:
                                continue
                            cw = el.col_widths[ci] if ci < len(el.col_widths) else 100.0
                            for cp in cell.paras:
                                visit(cp, max(20.0, cw - 8.0))
    return rep


def summarise(rep: dict) -> str:
    total = sum(rep.values()) or 1
    locked = rep.get("line-locked", 0)
    return ("%d paragraphs: %d flow, %d line-locked (%.0f%%), "
            "%d single-line, %d unpredictable font, %d lock failed"
            % (total, rep.get("flow", 0), locked, 100.0 * locked / total,
               rep.get("short", 0), rep.get("unpredictable", 0),
               rep.get("lock_failed", 0)))
