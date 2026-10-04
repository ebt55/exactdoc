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
# A drawn bullet is ink at the scale of the text it labels. Measured over both
# corpora, every genuine drawn marker is 2.67-3.0pt at 0.27-0.29em (c1, c6,
# x09 -- Chromium discs), while the squares Word/PDFMaker paints where table
# borders meet are 0.48pt and 1.5pt (y01, y02, y08, y09, y11: 0.04-0.15em) and
# Chromium's dotted TOC leaders are 0.75pt (x11: 0.07em). Both floors sit in
# the empty gap between those populations.
MARKER_MIN_PT = 2.0
MARKER_MIN_EM = 0.25
# Within this distance a rule's end (or its run) touches a candidate marker.
# Word draws the joint square flush against the segments it joins: measured
# gaps are exactly 0.0pt on every joint in y01/y02, so the tolerance only has
# to absorb float noise and the parser's 0.1pt rounding.
JOINT_TOL = 0.6
# A fill whose every channel is within this of the background is not ink. Word
# writes paragraph shading as exactly #ffffff; 2 levels absorbs colour-space
# rounding. Kept far below BACKDROP_LUMA on purpose: GitHub-style code panels
# are #f6f8fa and the gated corpus has visible tints down to #f8fafc (01) and
# #f2f5f8 (c1, c3, r1), all of which must stay boxes.
BACKGROUND_TOL = 2
# Drawings at or below this alpha leave no visible mark. The same cut-off the
# leftover-drawing pass in infer.py already applies.
TRANSPARENT_MAX = 0.05
# em. A producer splitting one visual line leaves fragments almost touching --
# a maths script boundary is ~0.1-0.3em, an inter-word space ~0.25em. Anything
# wider is a real gap, and on a two-column page it may be the gutter: joining
# across it fuses two columns into one enormous line that then re-wraps into
# many. Measured on a two-column paper, 1.6em cost five extra pages.
MAX_FRAGMENT_GAP = 0.55

# These are intentionally pairs, not a general PUA decoder.  A PUA value has
# no portable meaning on its own; it is only safe to translate where a known
# symbol face assigns it to a conventional list marker.
_SYMBOL_LIST_MARKERS = {("opensymbol", "\uf0b7"): "\u2022"}


# TeX Computer Modern fonts carry glyphs the Unicode standard has no single
# codepoint for: the pieces of tall delimiters (a big brace is drawn as
# top/middle/bottom/extender fragments), oldstyle digits, the dotless j.
# With no /ToUnicode to consult, BOTH parsers synthesise Adobe's PUA
# assignments for them (F8EB=parenlefttp, F8F1=bracelefttp, ...), and the
# DOCX then carries Private Use characters that render as garbage boxes.
# Ground truth -- every PUA value joined to its glyph name through the
# embedded CFF charsets of the corpus's own documents (PyMuPDF texttrace
# GIDs against the font's charset) -- not a table copied from memory:
#
#   CMEX10  F8E6 arrowvertex; F8EB-ED parenleft tp/ex/bt; F8EE-F0
#           bracketleft tp/ex/bt; F8F1-F3 braceleft tp/mid/bt;
#           F8F4 braceex; F8F6-F8 parenright; F8FA-FB bracketright tp/ex/bt
#           (F8F9 unobserved but bracketrighttp by the same joins);
#           F8FC/F8FD/F8FE braceright tp/mid/bt (mid by symmetry);
#   CMMI10  F6BE dotlessj; F731-34 oneoldstyle..fouroldstyle
#           (F735-39 five..nine by the same published slots).
#
# A piece becomes its base character: three "(" fragments in a column are
# how a tall parenthesis reads in running text, which is exactly what an
# editor's user types there. Scoped to the CM families by font name so a
# PUA value in any other face keeps its producer's meaning.
_TEX_PUA_TO_UNICODE = {
    0xF8E6: "|",
    0xF8EB: "(", 0xF8EC: "(", 0xF8ED: "(",
    0xF8EE: "[", 0xF8EF: "[", 0xF8F0: "[",
    0xF8F1: "{", 0xF8F2: "{", 0xF8F3: "{",
    0xF8F4: "|",
    0xF8F6: ")", 0xF8F7: ")", 0xF8F8: ")",
    0xF8F9: "]", 0xF8FA: "]", 0xF8FB: "]",
    0xF8FC: "}", 0xF8FD: "}", 0xF8FE: "}",
    0xF6BE: "\u0237",
    0xF731: "1", 0xF732: "2", 0xF733: "3", 0xF734: "4", 0xF735: "5",
    0xF736: "6", 0xF737: "7", 0xF738: "8", 0xF739: "9",
}


def _tex_pua_to_text(page: PageIR) -> int:
    """Rewrite TeX PUA characters to the Unicode they read as."""
    n = 0
    for b in page.blocks:
        for ln in b.lines:
            for s in ln.spans:
                if not s.font.startswith("CM"):
                    continue
                if not any(0xE000 <= ord(c) <= 0xF8FF for c in s.text):
                    continue
                out = []
                changed = False
                for c in s.text:
                    u = _TEX_PUA_TO_UNICODE.get(ord(c))
                    if u is not None:
                        out.append(u)
                        changed = True
                    else:
                        out.append(c)
                if changed:
                    s.text = "".join(out)
                    n += 1
    return n


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


def _is_hollow_marker(d: DrawCmd) -> bool:
    """A stroked, unfilled small CURVE: the `circle` list-style marker.

    Chromium draws a second-level bullet (`list-style: circle`) as an outlined
    bezier circle -- fill None, a 0.75pt stroke, 4.9pt across on x09 -- so the
    solid-only test below never saw it, the drawing fell through as a stray
    ornament, and every second-level item of x09's nested list lost its marker.
    Restricted to curves on purpose: a stroked small RECTANGLE before a label is
    a form's checkbox, and calling that a bullet would be a lie about content.
    """
    if d.fill or not d.stroke or d.shape not in ("curve", "complex"):
        return False
    x0, y0, x1, y1 = d.bbox
    w, h = x1 - x0, y1 - y0
    if not (1.5 < w <= BULLET_MAX and 1.5 < h <= BULLET_MAX):
        return False
    return abs(w - h) <= 0.25 * max(w, h)


def _is_marker_glyph(d: DrawCmd) -> bool:
    """Small, solid, roughly square: the shape of a drawn bullet."""
    if not d.fill:
        return _is_hollow_marker(d)
    x0, y0, x1, y1 = d.bbox
    w, h = x1 - x0, y1 - y0
    if not (0.4 < w <= BULLET_MAX and 0.4 < h <= BULLET_MAX):
        return False
    return abs(w - h) <= BULLET_ASPECT


def _labelled_line(bbox, lines: List[Line]) -> Optional[Line]:
    """The leftmost text line this glyph plausibly labels, or None.

    Takes a bbox rather than a DrawCmd because the same geometric question is
    asked of two different kinds of evidence: a drawn marker glyph, and a
    position where a glyph was drawn that could not be decoded.
    """
    x0, y0, x1, y1 = bbox
    cy, h = (y0 + y1) / 2, max(1.0, y1 - y0)
    best = None
    for ln in lines:
        lb = ln.bbox
        if lb[0] < x1 - 0.5:                       # text must start to the right
            continue
        if lb[0] - x1 > BULLET_GAP:
            continue
        if lb[1] - BULLET_VTOL * h <= cy <= lb[3] + BULLET_VTOL * h:
            if best is None or lb[0] < best.bbox[0]:
                best = ln
    return best


def _bullet_block(x0: float, baseline: float, size: float,
                  color: Optional[str], char: str = "•") -> TextBlock:
    """The canonical form both marker recoveries produce: a one-span block."""
    bb = (x0, baseline - size * 0.94, x0 + size * 0.5, baseline)
    sp = Span(text=char, font="Arial", size=size,
              color=color or "#000000", bold=False, italic=False,
              mono=False, serif=False, superscript=False,
              bbox=bb, origin=(x0, baseline))
    return TextBlock(lines=[Line(spans=[sp], bbox=bb)], bbox=bb)


def _drop_backdrops(page: PageIR) -> int:
    keep = [d for d in page.drawings if not _is_backdrop(d, page.width, page.height)]
    n = len(page.drawings) - len(keep)
    page.drawings = keep
    return n


# A drawing must reach at least this far onto the paper to be ink.
OFFPAGE_TOL = 0.5


def _drop_offpage(page: PageIR) -> int:
    """Drop drawings that lie wholly outside the page box.

    They are invisible by construction, and Chromium emits them: it paints a
    layer once and clips it per page, so the contents dot leaders of
    x11_chrome_toc_headings page 1 are ALSO in page 2's content stream, at
    y = -453 .. -335. Kept, they became seven "figures" with negative heights
    at the top of page 2, and they set its top margin to 10pt.
    """
    w, h = page.width, page.height
    keep = [d for d in page.drawings
            if d.bbox[2] > OFFPAGE_TOL and d.bbox[3] > OFFPAGE_TOL
            and d.bbox[0] < w - OFFPAGE_TOL and d.bbox[1] < h - OFFPAGE_TOL]
    n = len(page.drawings) - len(keep)
    page.drawings = keep
    return n


# --- visibility -------------------------------------------------------------
# Inference treats every path as evidence of structure: a filled rectangle
# around text becomes a box, a small square beside text becomes a bullet. That
# is only sound for ink a reader can see. The helpers below decide visibility
# from the page itself -- colour, alpha, and what the shape sits on -- so the
# structural passes never have to.

PAGE_BACKGROUND = "#ffffff"
RULE_THICK = 2.5     # the parser's own hline/vline cut-off (parse_pdfium)


def _rgb(hexcol: Optional[str]):
    if not hexcol or len(hexcol) != 7 or hexcol[0] != "#":
        return None
    try:
        return (int(hexcol[1:3], 16), int(hexcol[3:5], 16), int(hexcol[5:7], 16))
    except ValueError:
        return None


def _same_colour(a: Optional[str], b: Optional[str]) -> bool:
    """Indistinguishable on paper: every channel within BACKGROUND_TOL."""
    ra, rb = _rgb(a), _rgb(b)
    if ra is None or rb is None:
        return False
    return all(abs(x - y) <= BACKGROUND_TOL for x, y in zip(ra, rb))


def _paints_nothing(d: DrawCmd) -> bool:
    """A path that leaves no mark: no paint at all, or (near-)zero alpha.

    Measured: y01/y02/y08/y09/y11 carry 45 such paths each on one page (alpha
    0, no fill and no stroke colour), y03 859 glyph-outline strokes at alpha
    0.03-0.04 laid over the filled glyphs. infer's leftover pass already
    ignores them, but margins, furniture, column edges and marker detection
    all read the raw list. `fillstroke` is exempt: its recorded opacity is the
    fill's, and the stroke may still be opaque.
    """
    if d.fill is None and d.stroke is None:
        return True
    return d.kind in ("fill", "stroke") and d.opacity <= TRANSPARENT_MAX


def _drop_transparent(page: PageIR) -> int:
    keep = [d for d in page.drawings if not _paints_nothing(d)]
    n = len(page.drawings) - len(keep)
    page.drawings = keep
    return n


def _ink_against(e: DrawCmd, colour: str) -> bool:
    """Does drawing `e` put down paint distinguishable from `colour`?"""
    if _paints_nothing(e):
        return False
    paints = []
    if e.kind in ("fill", "fillstroke") and e.fill:
        paints.append(e.fill)
    if e.kind in ("stroke", "fillstroke") and e.stroke:
        paints.append(e.stroke)
    return any(not _same_colour(c, colour) for c in paints)


def _touching(a, b, pad: float) -> bool:
    return not (a[2] < b[0] - pad or b[2] < a[0] - pad or
                a[3] < b[1] - pad or b[3] < a[1] - pad)


def _is_background_fill(d: DrawCmd) -> bool:
    """An unstroked AREA fill in the page's own colour.

    Rules and joints (either side within the parser's rule thickness) are not
    candidates: a table drawn with white borders is still a table -- y09 p54
    has a 112-segment #ffffff grid whose geometry is the only evidence of its
    rows and columns -- and dropping its corner squares would break its grid.
    """
    if d.kind != "fill" or d.shape != "rect":
        return False
    x0, y0, x1, y1 = d.bbox
    if (x1 - x0) <= RULE_THICK or (y1 - y0) <= RULE_THICK:
        return False
    return _same_colour(d.fill, PAGE_BACKGROUND)


def _drop_invisible_fills(page: PageIR) -> int:
    """Remove page-coloured fills that knock out nothing and frame nothing.

    Word exports paint paragraph shading as one #ffffff rectangle per LINE.
    Each one used to reach infer's leftover pass as a 'box' and become its own
    single-cell table, so a 7-line paragraph came out as 7 stacked tables, each
    line re-wrapping inside its cell (y01 p21; 111 such boxes on y01, which
    was the largest single driver of its page inflation). White on white is
    not a box: a box needs a visible edge or a fill that differs from what it
    is painted on.

    So a background-coloured area fill survives only when it is VISIBLE BY
    CONTRAST with something it touches: any drawing whose paint differs from
    its colour, before or after it in z-order (a white card knocked out of a
    tinted band, white zebra rows between tinted ones and their rules -- 01,
    03, r1 -- a white panel under chart artwork -- y03), or an image it
    overlaps without wholly containing it. An image wholly inside the fill is
    drawn on top of it -- underneath, it would be invisible -- and is no
    evidence; y01's section numbers are such images inside the heading
    shading. Z-order is deliberately not consulted for drawings: keeping a
    fill that merely sits under dark ink costs nothing, dropping a knockout
    would lose a visible shape.

    Runs before `_drop_backdrops`, so a light page backdrop of a different
    colour still counts as the thing a white card stands out against.
    """
    cand = [d for d in page.drawings if _is_background_fill(d)]
    if not cand:
        return 0
    drop = set()
    for d in cand:
        bb = d.bbox
        if any(e is not d and _touching(e.bbox, bb, 1.0) and _ink_against(e, d.fill)
               for e in page.drawings):
            continue
        if any(_touching(im.bbox, bb, 1.0) and not (
                im.bbox[0] >= bb[0] - 0.5 and im.bbox[1] >= bb[1] - 0.5 and
                im.bbox[2] <= bb[2] + 0.5 and im.bbox[3] <= bb[3] + 0.5)
               for im in page.images):
            continue
        drop.add(id(d))
    if drop:
        page.drawings = [d for d in page.drawings if id(d) not in drop]
    return len(drop)


def _abuts_rule(d: DrawCmd, drawings: List[DrawCmd]) -> bool:
    """True if a horizontal or vertical rule ends at, or runs through, `d`.

    Word/PDFMaker draws a table's borders as separate filled segments and
    paints a small square at every point where they meet (y01 p1: 0.48pt
    squares at each inner junction, 1.5pt at the outer corners), flush with
    the segments on either side. A list marker never touches a rule: it sits
    in the text's own x-height band, a gap away from anything drawn.
    """
    x0, y0, x1, y1 = d.bbox
    t = JOINT_TOL
    for e in drawings:
        if e is d:
            continue
        ex0, ey0, ex1, ey1 = e.bbox
        if e.shape == "hline":
            if ey1 < y0 - t or ey0 > y1 + t:
                continue
            if abs(ex0 - x1) <= t or abs(ex1 - x0) <= t or \
                    (ex0 <= x0 + t and ex1 >= x1 - t):
                return True
        elif e.shape == "vline":
            if ex1 < x0 - t or ex0 > x1 + t:
                continue
            if abs(ey0 - y1) <= t or abs(ey1 - y0) <= t or \
                    (ey0 <= y0 + t and ey1 >= y1 - t):
                return True
    return False


def _marker_at_text_scale(d: DrawCmd, line: Line) -> bool:
    """Is this glyph big enough, against its line's text, to be a marker?"""
    em = _line_text_size(line)
    if em <= 0:
        return False             # nothing measurable to compare with
    x0, y0, x1, y1 = d.bbox
    return max(x1 - x0, y1 - y0) >= max(MARKER_MIN_PT, MARKER_MIN_EM * em)


# --- drawn dot leaders --------------------------------------------------------
# A contents line in HTML is "title <span class=dots> page", and the dots are a
# CSS `border-bottom: dotted` -- which Chromium paints as hundreds of tiny
# filled squares. On x11_chrome_toc_headings: 0.75pt squares at a 1.5pt pitch,
# 271-292 of them per entry. Left as drawings they were rasterised as seven
# 5pt-tall pictures, the 29 squares nearest each page number were promoted to
# BULLETS by `_markers_to_text` (each sits within 46pt left of the number), and
# those bullet blocks then read as a right-hand column, which split the page
# into two columns and reordered the whole report.
#
# A leader is unmistakable geometry: many identical marks on one line at one
# pitch, BETWEEN two pieces of text on that line's baseline. It is rewritten
# into the canonical form every other producer already uses -- a run of "."
# characters on the label's baseline -- so `infer` has one leader idiom to
# recognise, not two.
MARKER_ALIGN_TOL = 1.0     # pt; markers of one list share their left edge
LEADER_MARK_MAX = 2.5      # pt; a leader dot, not a bullet (x09's are 3-5pt)
LEADER_MIN_MARKS = 8       # a short dotted rule is decoration, not a leader
LEADER_MIN_SPAN = 24.0     # pt
LEADER_PITCH_MAX = 6.0     # pt between dot origins; dotted leaders are dense
LEADER_PITCH_TOL = 0.35    # fraction of the pitch the spacing may wander
LEADER_Y_TOL = 0.4         # pt; the marks of one leader share a centre line


def _leader_runs(page: PageIR):
    """[(marks, (x0, y0, x1, y1))] for regular horizontal runs of tiny marks."""
    marks = [d for d in page.drawings
             if (d.fill or d.stroke)
             and 0.2 < d.bbox[2] - d.bbox[0] <= LEADER_MARK_MAX
             and 0.2 < d.bbox[3] - d.bbox[1] <= LEADER_MARK_MAX]
    if len(marks) < LEADER_MIN_MARKS:
        return []
    marks.sort(key=lambda d: (round((d.bbox[1] + d.bbox[3]) / 2, 1), d.bbox[0]))
    rows, cur = [], [marks[0]]
    for d in marks[1:]:
        cy = (d.bbox[1] + d.bbox[3]) / 2
        py = (cur[-1].bbox[1] + cur[-1].bbox[3]) / 2
        if abs(cy - py) <= LEADER_Y_TOL:
            cur.append(d)
        else:
            rows.append(cur)
            cur = [d]
    rows.append(cur)
    out = []
    for row in rows:
        row.sort(key=lambda d: d.bbox[0])
        # split the row into runs of steady pitch
        run = [row[0]]
        for d in row[1:] + [None]:
            if d is not None:
                step = d.bbox[0] - run[-1].bbox[0]
                pitch = (run[-1].bbox[0] - run[0].bbox[0]) / (len(run) - 1) \
                    if len(run) >= 2 else step
                if 0 < step <= LEADER_PITCH_MAX and \
                        abs(step - pitch) <= LEADER_PITCH_TOL * max(pitch, 0.5):
                    run.append(d)
                    continue
            if len(run) >= LEADER_MIN_MARKS and \
                    run[-1].bbox[2] - run[0].bbox[0] >= LEADER_MIN_SPAN:
                out.append((run, (run[0].bbox[0],
                                  min(m.bbox[1] for m in run),
                                  run[-1].bbox[2],
                                  max(m.bbox[3] for m in run))))
            if d is not None:
                run = [d]
    return out


def _drawn_leaders_to_text(page: PageIR) -> int:
    """Rewrite drawn dot leaders between a label and its page number as text."""
    lines = [l for b in page.blocks for l in b.lines if l.horizontal and l.spans]
    if not lines:
        return 0
    done = 0
    drop = set()
    for marks, (x0, y0, x1, y1) in _leader_runs(page):
        cy = (y0 + y1) / 2
        left = right = None
        for ln in lines:
            size = max(s.size for s in ln.spans)
            # the run sits on the line: between its x-height and just under
            # its baseline (x11's border is lifted 2pt above the baseline)
            if not (ln.baseline - 0.6 * size <= cy <= ln.baseline + 1.0):
                continue
            if ln.bbox[2] <= x0 + 1.0 and x0 - ln.bbox[2] <= 3.0 * size:
                if left is None or ln.bbox[2] > left.bbox[2]:
                    left = ln
            elif ln.bbox[0] >= x1 - 1.0 and ln.bbox[0] - x1 <= 3.0 * size:
                if right is None or ln.bbox[0] < right.bbox[0]:
                    right = ln
        if left is None or right is None:
            continue                     # dots with nothing to lead: decoration
        ref = left.spans[-1]
        dot_w = 0.25 * ref.size          # a "." in Times; only a fallback width
        n = max(LEADER_MIN_MARKS // 2, int((x1 - x0) / dot_w))
        base = left.baseline
        bb = (x0, base - 0.94 * ref.size, x1, base + 0.21 * ref.size)
        sp = Span(text="." * n, font=ref.font, size=ref.size,
                  color=marks[0].fill or marks[0].stroke or ref.color,
                  bold=False, italic=False, mono=False, serif=ref.serif,
                  superscript=False, bbox=bb, origin=(x0, base))
        page.blocks.append(TextBlock(lines=[Line(spans=[sp], bbox=bb)], bbox=bb))
        drop.update(id(m) for m in marks)
        done += 1
    if done:
        page.drawings = [d for d in page.drawings if id(d) not in drop]
        page.blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    return done


def _marker_hits(page: PageIR, lines=None) -> List[DrawCmd]:
    """Drawn marker glyphs on this page that sit in front of a text line."""
    if lines is None:
        lines = [l for b in page.blocks for l in b.lines if l.horizontal]
    if not lines:
        return []
    # Shape and position are not enough: Word's table-border joints are filled
    # squares just left of cell text too, and y02 came out with 1,286 "•" for
    # its 24 real bullets, most of them inside table cells. A marker must also
    # be ink at its text's scale and must not be part of a rule.
    hits, hollow = [], []
    for d in page.drawings:
        if not _is_marker_glyph(d):
            continue
        near = _labelled_line(d.bbox, lines)
        if near is None or not _marker_at_text_scale(d, near):
            continue
        if _abuts_rule(d, page.drawings):
            continue
        if _flush_with_column_end(d, lines):
            continue
        if d.fill:
            hits.append(d)
        else:
            hollow.append((d, near))
    # An outlined circle is also a chart's scatter marker: y38 (eLife) has
    # 120 of them on one figure page, each "labelling" a tick label within
    # 46pt. A list's circle sits just ahead of its item (x09: 7pt, 1.4 marker
    # widths) and is the ONLY mark in front of that item; a scatter point is
    # neither.
    owners = {}
    for d, near in hollow:
        owners[id(near)] = owners.get(id(near), 0) + 1
    for d, near in hollow:
        w = d.bbox[2] - d.bbox[0]
        if owners[id(near)] == 1 and near.bbox[0] - d.bbox[2] <= 2.5 * w \
                and len(near.text.strip()) >= 4:     # an item, not a tick label
            hits.append(d)
    return hits


# IEEEtran's end-of-proof square is set flush with its column's right edge,
# and the other column's text starts 7pt past it -- "in front of a line" as
# far as position goes. y41's squares end where 19-28 lines of their page end;
# the bullets of x09, x07-x10 and y02 where at most one does.
END_MARK_FLUSH_LINES = 3


def _flush_with_column_end(d: DrawCmd, lines) -> bool:
    """Does the mark end where a text column's lines end (a tombstone)?"""
    return sum(1 for l in lines
               if abs(l.bbox[2] - d.bbox[2]) <= MARKER_ALIGN_TOL)         >= END_MARK_FLUSH_LINES


def _aligned(hits: List[DrawCmd]) -> List[DrawCmd]:
    """Marks that share their left edge with another: a list's marker column."""
    return [d for d in hits
            if any(e is not d and abs(e.bbox[0] - d.bbox[0]) <= MARKER_ALIGN_TOL
                   for e in hits)]


def _marker_sig(d: DrawCmd):
    """What makes two drawn marks the same marker: shape, size, ink.

    Sizes in half-point buckets: x09's circles measure 4.9 x 4.9 on page 1
    and 4.9 x 4.8 on page 2 -- the same glyph, rounded differently.
    """
    return (d.shape, round((d.bbox[2] - d.bbox[0]) * 2) / 2,
            round((d.bbox[3] - d.bbox[1]) * 2) / 2, d.fill, d.stroke)


def _corroborated_markers(ir: DocIR) -> set:
    """Marker signatures that some page shows as a LIST.

    Two hits are not enough on their own: IEEEtran's end-of-proof square
    (y41) lands just left of the other column's text twice on some pages, and
    corroborating it from there turned every lone proof square into a
    bullet. A list's markers share a left edge; proof squares never do.
    """
    sigs = set()
    for p in ir.pages:
        aligned = _aligned(_marker_hits(p))
        if len(aligned) >= 2:
            sigs.update(_marker_sig(d) for d in aligned)
    return sigs


def _markers_to_text(page: PageIR, corroborated=frozenset()) -> int:
    """Rewrite drawn bullet glyphs as one-span text blocks.

    This is deliberately a *translation*, not a special case: it converts the
    Chromium idiom into the separate-marker-box idiom that infer.py already
    reconstructs for WeasyPrint, so list handling has a single code path.
    """
    lines = [l for b in page.blocks for l in b.lines if l.horizontal]
    if not lines:
        return 0
    hits = _marker_hits(page, lines)
    # Outlined circles must form a marker column on the page, or be
    # corroborated by one elsewhere (see `_marker_hits` for why circles are
    # held to more than solid marks).
    hollow = [d for d in hits if not d.fill]
    if hollow:
        column = _aligned(hollow)
        keep = {id(d) for d in column} | {
            id(d) for d in hollow if _marker_sig(d) in corroborated}
        hits = [d for d in hits if d.fill or id(d) in keep]
    # A real list has repetition. A single small square is more likely to be a
    # decorative dot, so require corroboration before rewriting anything --
    # from this page, or from the same mark labelling lines elsewhere in the
    # document: a list that breaks across pages can leave one item behind
    # (x09 page 2 holds the last sub-item of a list begun on page 1).
    if len(hits) < 2:
        hits = [d for d in hits if _marker_sig(d) in corroborated]
        if not hits:
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
        hollow = not d.fill
        page.blocks.append(_bullet_block(x0, cy + size * 0.22, size,
                                         d.stroke if hollow else d.fill,
                                         char="◦" if hollow else "•"))
    page.blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    return len(hits)


# A marker set far smaller than the text it labels is not a marker. Measured
# across the expansion corpus, the two populations do not overlap and do not
# come close to it: every mark x03 promotes is 11.0pt against 11.0pt body text
# (ratio 1.0), while all 345 on y01 and all 623 on y03 report 1.0pt against
# ~10pt body (ratio 0.1). Those are PDF's default text size on an object whose
# font size was never set -- a positioning artifact, not ink anybody sees.
# The threshold sits in the empty middle of that gap.
UNDECODED_MIN_SIZE_RATIO = 0.5

# What a line already starting with a marker looks like. Narrower than
# infer.BULLET_CHARS on purpose: '-' and '*' start ordinary prose and code.
_MARKER_HEADS = set("•◦▪‣·○●♦")


def _line_text_size(ln: Line) -> float:
    """The size of the visible text on a line, 0.0 when there is none."""
    return max((s.size for s in ln.spans if s.text.strip()), default=0.0)


def _starts_with_marker(ln: Line) -> bool:
    head = ln.text.strip()[:1]
    return bool(head) and head in _MARKER_HEADS


def _undecoded_markers_to_text(page: PageIR) -> int:
    """Rewrite undecodable glyphs that sit in a list-marker slot as bullets.

    A glyph PDFium could not decode leaves nothing in `page.blocks` to
    normalise -- the text page does not report it at all -- so the only
    evidence is the position `parse_pdfium` recorded in `page.undecoded`.
    Position alone turned out to be far too weak a test, and the corpus said so
    loudly: on its first form this promoted 345 marks on y01 and 623 on y03,
    against 12 on x03, and sampling every one of them showed essentially none
    were list markers. y03 is the AES specification; its promotions were the
    column gaps of the S-box tables ('63 7c 77 7b f2...'), the operators of
    displayed equations ('= ({02} . s0,c)+({03} . s1,c)...') and matrix
    brackets. y01's were table-of-contents leaders between a section number and
    its title, and label/value separators whose 'item' was an existing bullet.

    So a mark has to bring the evidence a real list marker leaves, and three
    tests carry it. **Nothing may end to its left on its own baseline**: a
    marker's line starts after it, whereas a symbol inside running text has
    text on both sides -- that alone was 85% of the false promotions on both
    documents. **It must be ink at the item's own scale** (see
    UNDECODED_MIN_SIZE_RATIO); the remainder were 1pt artifacts. And **its host
    must be item text rather than another marker**, because a bullet in front
    of a bullet is not a list, it is a duplicate.

    What survives still has to repeat: at least two marks on the page must
    agree, the same corroboration `_markers_to_text` demands of a drawn one.
    Everything else stays dropped, deliberately -- producers emit empty text
    objects for trailing whitespace too, and x03 carries one at x=147.4 just
    past the end of 'binding constraint.' with bounds identical to a bullet's.

    Measured after: x03 unchanged at 12, y01 0, y03 0, y06 68 -> 7,
    c7_code 16 -> 0, x11_chrome_toc_headings 2 -> 0.
    """
    marks = getattr(page, "undecoded", None)
    if not marks:
        return 0
    lines = [l for b in page.blocks for l in b.lines if l.horizontal]
    if not lines:
        return 0
    hits = []
    for m in marks:
        x, y = m.origin
        near = _labelled_line((x, y, x, y), lines)
        if near is None:
            continue
        # A list puts ONE marker in front of an item. Several marks strung
        # along a single baseline are spacing, and on a monospace listing they
        # are unmistakable: c7_code reports 202 marks, in runs 5.1pt apart --
        # exactly one character advance at its 11.3pt Courier -- which is the
        # listing's own indentation. Only the leading mark of such a run has
        # nothing to its left, so the left-text test above passes it and 16
        # bullets used to land inside the code. x11_chrome_toc_headings is the
        # same story with 492. Every one of x03's twelve is alone on its
        # baseline, because that is what a list looks like.
        if sum(1 for o in marks
               if abs(o.origin[1] - y) <= BULLET_VTOL) > 1:
            continue
        # Text to the left on this baseline: the mark is inside a line, not in
        # front of one. "To the left" includes a line that SPANS the mark: an
        # undecoded glyph between "2." and "Method" is the space inside one
        # line, and it is no less inside it for that line ending further
        # right. (x11's contents entries promoted exactly that space to a
        # bullet once their leaders became text 43pt away.)
        if any(ln.bbox[0] <= x + 0.5 and
               ln.bbox[1] - BULLET_VTOL <= y <= ln.bbox[3] + BULLET_VTOL
               for ln in lines):
            continue
        host_size = _line_text_size(near)
        # An unmeasurable host is not a licence to promote: absent evidence is
        # not evidence.
        if host_size <= 0 or m.size < UNDECODED_MIN_SIZE_RATIO * host_size:
            continue
        if _starts_with_marker(near):
            continue
        hits.append((m, near))
    if len(hits) < 2:
        return 0
    for m, near in hits:
        size = m.size
        if size <= 0.4 and near.spans:
            size = near.spans[0].size
        page.blocks.append(_bullet_block(m.origin[0], m.origin[1],
                                         size or 10.0, m.color))
    page.blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    page.undecoded = [m for m in marks
                      if all(m is not h for h, _ in hits)]
    return len(hits)


def _symbol_list_marker_candidates(page: PageIR):
    """Find known PUA bullets that have the geometry of an inline marker.

    The font/codepoint pair supplies the semantic evidence; being the first
    ink on a horizontal row, immediately followed by body text, and having a
    small glyph box supplies the layout evidence.  Both are needed: symbol
    fonts also contain decorative glyphs, and PUA text in an ordinary font is
    not portable enough to guess at.
    """
    out = []
    for block in page.blocks:
        for line in block.lines:
            if not line.horizontal or not line.spans:
                continue
            first = next((i for i, span in enumerate(line.spans)
                          if span.text.strip()), None)
            if first is None:
                continue
            marker = line.spans[first]
            key = ("".join(marker.font.lower().split()), marker.text.strip())
            bullet = _SYMBOL_LIST_MARKERS.get(key)
            if bullet is None:
                continue
            body = next((span for span in line.spans[first + 1:]
                         if span.text.strip()), None)
            if body is None or body.bbox[0] < marker.bbox[2] - 0.5:
                continue
            mw, mh = marker.bbox[2] - marker.bbox[0], marker.bbox[3] - marker.bbox[1]
            # A genuine marker is no wider than roughly one em and no taller
            # than its adjacent body run.  This admits OpenSymbol's 11pt
            # bullet while rejecting display-size symbol artwork.
            if mw <= 0.4 or mw > max(2.0, 1.05 * body.size) or \
                    mh <= 0.4 or mh > 1.5 * body.size or \
                    marker.size > 1.2 * body.size:
                continue
            if body.bbox[0] - marker.bbox[2] > BULLET_GAP:
                continue
            out.append((line, marker, body, bullet))
    return out


def _normalize_symbol_list_markers(page: PageIR) -> int:
    """Canonicalise corroborated leading symbol-font PUA list markers."""
    candidates = _symbol_list_marker_candidates(page)
    if len(candidates) < 2:
        return 0

    # A list repeats both its marker edge and its item-text edge.  Requiring a
    # two-row cluster prevents unrelated symbol glyphs elsewhere on the page
    # from gaining list semantics merely because they share a font/codepoint.
    accepted = set()
    for _, marker, body, bullet in candidates:
        x_tol = max(2.0, 0.25 * body.size)
        group = [(ln, m, b, canon) for ln, m, b, canon in candidates
                 if canon == bullet and abs(m.bbox[0] - marker.bbox[0]) <= x_tol
                 and abs(b.bbox[0] - body.bbox[0]) <= x_tol]
        if len(group) >= 2:
            accepted.update(id(m) for _, m, _, _ in group)

    changed = 0
    for _, marker, body, bullet in candidates:
        if id(marker) not in accepted:
            continue
        # Keep any source separator in this span: infer's marker splitter uses
        # it when the text box is flush.  Arial is safe in Google Docs and the
        # following body span remains untouched.
        suffix = marker.text[len(marker.text.rstrip()):]
        marker.text = bullet + suffix
        marker.font = "Arial"
        marker.serif = False
        changed += 1
    return changed


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


def _line_size(ln: Line) -> float:
    return max((s.size for s in ln.spans), default=10.0)


def _coalesce_row_fragments(page: PageIR) -> int:
    """Rejoin one visual line that a producer split across several blocks.

    pdfTeX emits inline maths as separate text blocks: the run before the
    script, the script itself, the run after. They share a baseline but sit in
    different blocks, and inference rebuilds its paragraph flow from blocks --
    so each fragment became its own single-line paragraph. One measured page
    turned two source lines into eight paragraphs; every fragment then consumed
    a full line, the page overflowed, and since each source page ends in a hard
    break the overflow cost a whole page. That was the bulk of LaTeX page
    inflation, and none of it was re-wrap.

    Fragments are joined only when they share a baseline AND are horizontally
    close. The proximity test is what keeps two-column layouts intact: those
    also share baselines across the gutter, but are an inch apart.
    """
    flat = [(bi, ln) for bi, b in enumerate(page.blocks) for ln in b.lines
            if ln.horizontal and ln.spans]
    rows = {}
    for bi, ln in flat:
        sz = _line_size(ln)
        key = None
        for base in rows:
            if abs(ln.baseline - base) <= max(1.2, 0.18 * sz):
                key = base
                break
        rows.setdefault(key if key is not None else round(ln.baseline, 2),
                        []).append((bi, ln))

    # Absorb raised/lowered scripts. A subscript sits on its own baseline by
    # definition, so baseline grouping alone leaves it stranded as its own
    # paragraph -- which is most of what is left of the maths problem.
    for base in sorted(rows, key=lambda b: -len(rows[b])):
        host = rows.get(base)
        if not host:
            continue
        hsz = max(_line_size(l) for _, l in host)
        hx0 = min(l.bbox[0] for _, l in host)
        hx1 = max(l.bbox[2] for _, l in host)
        for other in [b for b in list(rows) if b != base]:
            grp = rows.get(other)
            if not grp:
                continue
            if any(_line_size(l) >= 0.92 * hsz for _, l in grp):
                continue                       # full-size: a real line
            # scripts are short. A wide fragment at a nearby baseline is a
            # genuine line of small type (a caption, a footnote), not a script.
            if any((l.bbox[2] - l.bbox[0]) > 0.25 * max(1.0, hx1 - hx0)
                   for _, l in grp):
                continue
            if abs(other - base) > 0.75 * hsz:
                continue                       # outside the em box
            if any(l.bbox[0] < hx0 - 2.0 or l.bbox[0] > hx1 + 0.6 * hsz
                   for _, l in grp):
                continue                       # not adjacent horizontally
            for _, l in grp:
                if l.baseline < base - 0.12 * hsz:
                    for s in l.spans:
                        s.superscript = True
            host.extend(grp)
            del rows[other]

    joined = 0
    for base, items in rows.items():
        if len({bi for bi, _ in items}) < 2:
            continue                       # already one block: nothing to do
        items.sort(key=lambda t: t[1].bbox[0])
        # split into horizontally-contiguous groups
        groups, cur = [], [items[0]]
        for prev, nxt in zip(items, items[1:]):
            gap = nxt[1].bbox[0] - prev[1].bbox[2]
            if gap > MAX_FRAGMENT_GAP * _line_size(prev[1]):
                groups.append(cur)
                cur = [nxt]
            else:
                cur.append(nxt)
        groups.append(cur)
        for grp in groups:
            if len({bi for bi, _ in grp}) < 2:
                continue
            host_bi = grp[0][0]
            spans, bb = [], None
            for k, (bi, ln) in enumerate(grp):
                if k and spans and not spans[-1].text.endswith(" "):
                    gap = ln.bbox[0] - grp[k - 1][1].bbox[2]
                    if gap > 0.22 * _line_size(ln):
                        spans[-1].text += " "
                spans.extend(ln.spans)
                bb = (ln.bbox if bb is None else
                      (min(bb[0], ln.bbox[0]), min(bb[1], ln.bbox[1]),
                       max(bb[2], ln.bbox[2]), max(bb[3], ln.bbox[3])))
            merged = Line(spans=spans, bbox=bb, dir=grp[0][1].dir)
            drop = {id(ln) for _, ln in grp}
            for bi, b in enumerate(page.blocks):
                b.lines = [l for l in b.lines if id(l) not in drop]
            page.blocks[host_bi].lines.append(merged)
            page.blocks[host_bi].lines.sort(key=lambda l: (round(l.baseline, 1),
                                                          l.bbox[0]))
            joined += len(grp) - 1

    page.blocks = [b for b in page.blocks if b.lines]
    for b in page.blocks:
        bb = None
        for l in b.lines:
            bb = (l.bbox if bb is None else
                  (min(bb[0], l.bbox[0]), min(bb[1], l.bbox[1]),
                   max(bb[2], l.bbox[2]), max(bb[3], l.bbox[3])))
        b.bbox = bb
    page.blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    return joined


def _ruled_bands(page: PageIR):
    """Y-bands that look like tables, from the ruling lines.

    Whether two lines sharing a baseline belong together -- cells of one row,
    or unrelated text that merely lines up -- cannot be decided from the text
    alone. Measured over the corpus, the same-baseline gaps inside a table and
    the coincidental ones have identical distributions (median 4.7em for both),
    so no width threshold separates them, and five attempts at one oscillated
    between 3 and 4 regressions instead of converging.

    The ruling lines settle it, and a parser does not have them. This does: a
    band spanned by two or more horizontal rules that overlap in x is a table,
    and inside such a band same-baseline lines are cells and may be joined.
    """
    raw_rules = [d for d in page.drawings
                 if d.shape == "hline" and (d.bbox[2] - d.bbox[0]) > 24]
    if len(raw_rules) < 2:
        return []
    # Merge rules that share a y FIRST. A table's borders are drawn per cell,
    # so several sit side by side on one line; sorted by y, consecutive ones
    # then have zero horizontal overlap and every band breaks at the first
    # pair. One measured page had 70 rules and produced no bands at all.
    raw_rules.sort(key=lambda d: (round(d.bbox[1], 1), d.bbox[0]))
    rules = []
    for d in raw_rules:
        if rules and abs(d.bbox[1] - rules[-1][1]) <= 2.0:
            r = rules[-1]
            rules[-1] = (min(r[0], d.bbox[0]), r[1], max(r[2], d.bbox[2]), r[3])
        else:
            rules.append((d.bbox[0], d.bbox[1], d.bbox[2], d.bbox[3]))
    if len(rules) < 2:
        return []

    bands, cur = [], [rules[0]]
    for prev, r in zip(rules, rules[1:]):
        ox = min(prev[2], r[2]) - max(prev[0], r[0])
        w = max(1.0, min(prev[2] - prev[0], r[2] - r[0]))
        if ox > 0.5 * w and (r[1] - prev[3]) < 220:
            cur.append(r)
        else:
            bands.append(cur)
            cur = [r]
    bands.append(cur)
    out = []
    for grp in bands:
        if len(grp) < 2:
            continue
        out.append((min(d[0] for d in grp) - 6, min(d[1] for d in grp) - 4,
                    max(d[2] for d in grp) + 6, max(d[3] for d in grp) + 4))
    return out


def _join_ruled_rows(page: PageIR) -> int:
    """Inside a ruled band, join blocks whose lines share a baseline."""
    bands = _ruled_bands(page)
    if not bands:
        return 0

    def in_band(ln):
        cx = (ln.bbox[0] + ln.bbox[2]) / 2
        cy = (ln.bbox[1] + ln.bbox[3]) / 2
        for b in bands:
            if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
                return b
        return None

    rows = {}
    for bi, b in enumerate(page.blocks):
        for ln in b.lines:
            if not ln.horizontal or not ln.spans:
                continue
            band = in_band(ln)
            if band is None:
                continue
            key = (id(band) if False else band, round(ln.baseline, 0))
            rows.setdefault(key, []).append((bi, ln))

    joined = 0
    for _, items in rows.items():
        if len({bi for bi, _ in items}) < 2:
            continue
        items.sort(key=lambda t: t[1].bbox[0])
        host = items[0][0]
        drop = {id(ln) for _, ln in items[1:]}
        for b in page.blocks:
            b.lines = [l for l in b.lines if id(l) not in drop]
        for _, ln in items[1:]:
            page.blocks[host].lines.append(ln)
        page.blocks[host].lines.sort(key=lambda l: (round(l.baseline, 1), l.bbox[0]))
        joined += len(items) - 1

    page.blocks = [b for b in page.blocks if b.lines]
    for b in page.blocks:
        bb = None
        for l in b.lines:
            bb = (l.bbox if bb is None else
                  (min(bb[0], l.bbox[0]), min(bb[1], l.bbox[1]),
                   max(bb[2], l.bbox[2]), max(bb[3], l.bbox[3])))
        b.bbox = bb
    page.blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    return joined


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
    stats = {"backdrops": 0, "vector_markers": 0, "symbol_markers": 0,
             "undecoded_markers": 0, "rotated": 0, "row_joins": 0,
             "ruled_rows": 0, "tex_pua": 0, "transparent": 0,
             "invisible_fills": 0, "offpage": 0, "leaders": 0}
    for p in ir.pages:
        if not hasattr(p, "rotated"):
            p.rotated = []
        stats["tex_pua"] += _tex_pua_to_text(p)
        # Visibility first: everything after this reads drawings as evidence.
        stats["transparent"] += _drop_transparent(p)
        stats["invisible_fills"] += _drop_invisible_fills(p)
        stats["backdrops"] += _drop_backdrops(p)
        stats["offpage"] += _drop_offpage(p)
        stats["rotated"] += _split_rotated(p)
        # Before the marker pass: leader dots are small and square, and the
        # ones nearest the page number sit exactly where a bullet would.
        stats["leaders"] += _drawn_leaders_to_text(p)
    # The marker pass needs the whole document in view: a page with ONE item
    # of a list is corroborated by the pages that show the list.
    corroborated = _corroborated_markers(ir)
    for p in ir.pages:
        stats["vector_markers"] += _markers_to_text(p, corroborated)
        stats["undecoded_markers"] += _undecoded_markers_to_text(p)
        stats["symbol_markers"] += _normalize_symbol_list_markers(p)
        stats["row_joins"] += _coalesce_row_fragments(p)
        stats["ruled_rows"] += _join_ruled_rows(p)
    ir.meta = dict(ir.meta or {})
    ir.meta["_dialect"] = fingerprint(ir)
    ir.meta["_normalized"] = stats
    return ir
