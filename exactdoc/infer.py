"""Structure inference: PageIR -> DocLayout (semantic, writer-ready)."""
import copy
import math
import re
from collections import Counter, defaultdict
from dataclasses import replace
from statistics import median
from typing import List, Optional, Tuple, Dict, Any

from .model import (DocIR, PageIR, TextBlock, Line, Span, DrawCmd, ImageObj,
                    BBox, bbox_union, bbox_overlap, bbox_area, contains,
                    ink_extent)
from .layout import (Run, Para, Cell, TableEl, FigureEl, ImageEl, RuleEl,
                     ColBreak, Chunk, PageLayout, HFPart, HFSection, DocLayout,
                     page_sequences, FloatEl)
from .furniture import (DECIMAL, num_tokens, page_number_model, is_page_number,
                        furniture_text, printed_parity, numbering_sections)
from . import hyphen
from .lists import assign_lists
from .notes import bind_page_notes, find_page_notes, number_footnotes

BULLET_CHARS = set("•◦▪‣·-–—*➤►○●♦")
# A single Hebrew or Arabic letter is an ordinal too: y49's contents and
# y47's sub-lists number items `א.` `ב.` / `أ.` `ب.` as Latin lists use `a.`.
NUM_RE = re.compile(r"^\(?(\d{1,3}|[a-zA-Zא-תء-ي]|"
                    r"[ivxlIVXL]{1,5})[\.\)\:]$")
SECTION_NUM_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){1,4}\.?$")   # "2.5", "2.5.1."

# --- figure-detection budget ----------------------------------------------
# A figure region is rasterised, so anything it swallows stops being editable
# text. These caps make that trade explicit and bounded.
GLYPH_MAX = 9.0            # pt; shapes this small are glyphs, not artwork
RULE_THICK = 2.5           # pt; thinner than this is a rule, not a shape
MAX_FIG_GROWTH = 4.0       # a figure may not exceed 4x its seed area
MAX_FIG_PAGE_FRAC = 0.55   # ...nor 55% of the page
MAX_FIG_TEXT_FRAC = 0.35   # ...nor swallow more than 35% of a page's text

# --- multi-column grids ----------------------------------------------------
# A column grid is recognised from its GUTTERS: vertical bands that almost no
# text line crosses. Block geometry cannot be used for this -- the parser
# merges adjacent columns into a single block often enough (y06 p6 has one
# 57-line block spanning columns 2 and 3) that a block-based test misses the
# structure entirely, while line left-edges cluster on the grid exactly.
# --- cover-band accent stripes ---------------------------------------------
# A cover block is often two fills: the block itself and a thin full-width rule
# flush against its edge. The thin one is an accent stripe and is carried as a
# border on the band cell; the thick one is the band. Both bounds below refuse
# a SECOND SUBSTANTIAL fill, which is a second band rather than a stripe.
#
# The absolute bound is not a taste call: OOXML stores border width in eighths
# of a point with a maximum of 96, so a stripe thicker than 12pt cannot be
# expressed as a border at all. The relative bound is the shape argument -- a
# rule against a block is a small fraction of it. Measured over the corpus, the
# only two accent stripes are 4.0pt (2.4% of its band, 01_whitepaper) and 8.0pt
# (6.2%, 04_exec_brief), so 8pt is a real accent and the threshold has to admit
# it.
ACCENT_MAX_PT = 12.0
ACCENT_MAX_FRAC = 0.25

MIN_GUTTER_W = 8.0          # pt; narrower than this is word spacing
GRID_WIDTH_TOL = 0.12       # columns must be within 12% of the same width
MIN_COL_LINES = 6           # ...and each must actually carry text
# A full-width heading crosses a real gutter, so this was never a test for
# absolute emptiness -- it has always let a fraction of baselines through. The
# question is only how large that fraction may be, and it is bounded from above
# by tables rather than by headings.
#
# Swept 0.02..0.15 over the corpus with a fresh parse per value. No gated
# fixture fires a >=3 column grid at any of them, and neither IRS form
# (y14_irs_fw9, y07_irs_f1040) does either -- so forms are not the binding
# constraint. A numeric table is: at 0.04 and above, y03_nist_fips197 p41 reads
# as a three-column grid, and it is an AES byte table whose line starts sit at
# 184/245/303/362/421 on a pitch of 59. Measured end to end, that costs y03 a
# page (+21 -> +22).
#
# 0.03 is therefore the widest value that makes no document worse. It still
# moves the PDFium arm, which is what the tolerance is for: y13 goes 2 -> 6
# pages. Going further would take y13 to 19 against PyMuPDF's 20, and the
# reason not to is that it gets there by calling a table a grid.
GUTTER_CROSS_FRAC = 0.03
# The widest line the column-grid occupancy scan reads (fraction of the
# content width). The same 0.62 bar the flow's own narrow-block test uses:
# a line this wide cannot live in one column of a >=3-column grid.
COL_SCAN_W_FRAC = 0.62
MIN_GRID_BAND_PT = 80.0    # a document's text column is never narrower
COL_SPAN_FRAC = 1.5         # wider than 1.5 columns is genuinely page-spanning
COL_SINGLE_BLOCK_FRAC = 0.5  # one block this tall is a column on its own
# The two-column test asks for a left cluster, a right cluster and enough text
# in each; it never asked that the white between them be a GUTTER. A page of
# short left-hand labels and right-hand fields -- headings and contents titles
# on the left, page numbers against the margin -- passes every one of those
# tests, and x11_chrome_toc_headings did: a single-column report was split at
# x=502 with a 238pt "gutter", its headings poured into column one, its body
# paragraphs into a tail below, and the page rendered as two. Measured over
# both corpora, every genuine two-column chunk has a gutter of at most 0.234 of
# the content width (y22_lshort's two-column index; papers and booklets sit at
# 0.03-0.10); x11's was 0.485. 0.30 sits between them.
MAX_GUTTER_FRAC = 0.30
# ...and only when the page's PROSE says so: text that crosses the split lying
# between the "columns'" own items, as x11's body paragraphs lay between its
# headings. A wide white gap flanked by a table's stub and last columns, with
# the table itself across it, is a mis-read table (y37 p15-17, y35 p14), and
# laying those pages out as one column stacked every label above its figure:
# +4 pages on y37.


def _prose_between(wide_items, col_items) -> bool:
    """Does split-crossing TEXT lie inside the vertical span of the columns?"""
    if not col_items:
        return False
    lo = min(t[1][1] for t in col_items)
    hi = max(t[1][3] for t in col_items)
    return any(kind == "blk" and lo < (bb[1] + bb[3]) / 2 < hi
               for kind, bb, _o in wide_items)


# --- two-column pages, read from the gutter ---------------------------------
# The block-cluster test above finds a two-column page from where its BLOCKS
# start, and takes the split from the most populous right-hand cluster. On a
# page of display maths neither survives: equation numbers flush at a single
# column's right margin are a right-hand "cluster" of many blocks (y43 p3, a
# one-column NeurIPS page, was laid out as a 14pt-wide second column holding
# "(7)".."(14)" with every prose line in a tail below), and on a genuine
# two-column page the fragments of a display can outnumber the right column's
# own blocks (y41 p2's split landed 52pt inside the LEFT column, every line of
# both columns then sat in the wrong flow with page-absolute indents, and the
# page rendered one character per line). The gutter is the evidence that does
# not move: a vertical band of white that the column-sized lines never cross,
# the same reading `column_grid` makes for three columns and more.
#
# A two-column page leaves both columns at roughly half the content width;
# measured over the corpus, the narrowest genuine column is 0.46 of it (the
# journal and arXiv classes sit at 0.47-0.49). A sidebar beside one wide column
# (PLOS, Frontiers title pages: 0.24-0.32) is not this shape, and neither is a
# right-margin column of equation numbers (0.04).
TWO_COL_MIN_BAND_FRAC = 0.38
# Each column must actually be set in lines that fill it. The crossing test
# below does the real work against a one-column page; this keeps a white band
# under a scatter of short fragments from passing for a gutter.
TWO_COL_FULL_LINE_FRAC = 0.75
TWO_COL_MIN_FULL_LINES = 6
# Of the lines lying within the columns' vertical extent, the share allowed to
# cross the gutter. On a two-column page those are the spanning floats and
# their captions; on a one-column page they are its prose. Measured: the
# journal pages cross at 0.00-0.08, y43's one-column maths pages at 0.55-0.80.
TWO_COL_MAX_CROSS_FRAC = 0.25
# A white band beside a few lines of text is an inset, not a gutter: the
# shorter column must run at least this share of the body's height, unless the
# block-cluster detector reads two columns too (it accepts a short right
# column of several blocks -- an article's last page). y39 p1's right column,
# one 250pt block under the abstract, is 0.33; tests/test_column_grid's 88pt
# inset is 0.11.
TWO_COL_MIN_EXTENT_FRAC = 0.2
# A SIDEBAR beside a main column is a column too, of its own width: Frontiers'
# title page (y40 p1) sets its editor/review/citation metadata in a 0.2-wide
# column beside the 0.67-wide title, abstract and introduction. Read with the
# half-width bar above it fell to the block clusters, which split it at the
# wrong place, sent the main column's lines to a page-wide tail and set both
# halves at the average width -- three rendered pages, and the next page's
# left column landed 270pt to the right. A narrow side down to this share of
# the measure is accepted (an equation-number column is 0.04)...
TWO_COL_SIDE_MIN_FRAC = 0.15
# ...when it runs on its own baselines. A glossary's terms and a form's labels
# are narrow left columns too, but each sits on the baseline of the text it
# labels: that is a row structure, and the row and table readings own it. A
# sidebar set in its own type keeps its own grid (y40 p1: 6.4/9pt against the
# main column's 12pt). Of the narrow column's lines, at most this share may
# share a baseline with the wide column's.
TWO_COL_SIDE_MAX_SHARED = 0.5
# Columns this much apart in width (of the wider) are written at their own
# widths (Chunk.col_widths); closer than that, equal columns as before -- the
# journal classes differ by 0-3%, a sidebar by 60-70%.
TWO_COL_UNEQUAL_FRAC = 0.10


def _two_column_gutter(lines, content_l: float, content_r: float):
    """(left x, right x, shorter column's height) of a two-column page's
    gutter, or None.

    `lines` are the page's flow lines. The occupancy scan reads only lines
    that fit a column (wider than COL_SCAN_W_FRAC is page-spanning by
    construction) and tolerates GUTTER_CROSS_FRAC of them through the band,
    exactly as `column_grid` does. A band qualifies when it leaves two columns
    of TWO_COL_MIN_BAND_FRAC or more, each holding TWO_COL_MIN_FULL_LINES lines
    that fill it, and when no more than TWO_COL_MAX_CROSS_FRAC of all the lines
    in the columns' vertical extent run across it.
    """
    w = content_r - content_l
    n = int(round(w))
    if n < 120:
        return None
    boxes = [l.bbox for l in lines if l.horizontal and l.text.strip()]
    scan = [b for b in boxes if (b[2] - b[0]) <= COL_SCAN_W_FRAC * w]
    if len(scan) < 2 * TWO_COL_MIN_FULL_LINES:
        return None
    occ = [0] * n
    for b in scan:
        a0 = max(0, int(b[0] - content_l))
        a1 = min(n, int(math.ceil(b[2] - content_l)))
        for i in range(a0, a1):
            occ[i] += 1
    tol = max(1, int(GUTTER_CROSS_FRAC * len(scan)))
    best = None
    i = 0
    while i < n:
        if occ[i] > tol:
            i += 1
            continue
        j = i
        while j < n and occ[j] <= tol:
            j += 1
        gl, gr = content_l + i, content_l + j
        narrow = min(gl - content_l, content_r - gr)
        wide = max(gl - content_l, content_r - gr)
        if i > 0 and j < n and (j - i) >= MIN_GUTTER_W and \
                wide >= TWO_COL_MIN_BAND_FRAC * w and \
                narrow >= TWO_COL_SIDE_MIN_FRAC * w:
            # the widest qualifying band is the gutter; a second one would be
            # a three-column grid, which column_grid owns
            if best is None or (j - i) > (best[1] - best[0]):
                best = (gl, gr)
        i = j
    if best is None:
        return None
    gl, gr = best
    lw, rw = gl - content_l, content_r - gr
    left = [b for b in boxes if b[2] <= gl + 2.0]
    right = [b for b in boxes if b[0] >= gr - 2.0]
    full_l = [b for b in left if b[2] - b[0] >= TWO_COL_FULL_LINE_FRAC * lw]
    full_r = [b for b in right if b[2] - b[0] >= TWO_COL_FULL_LINE_FRAC * rw]
    if len(full_l) < TWO_COL_MIN_FULL_LINES or \
            len(full_r) < TWO_COL_MIN_FULL_LINES:
        return None
    y0 = min(b[1] for b in left + right)
    y1 = max(b[3] for b in left + right)
    inside = [b for b in boxes if y0 <= (b[1] + b[3]) / 2.0 <= y1]
    crossing = [b for b in inside if b[0] < gl and b[2] > gr]
    if len(crossing) > TWO_COL_MAX_CROSS_FRAC * max(1, len(inside)):
        return None
    if min(lw, rw) < TWO_COL_MIN_BAND_FRAC * w:
        side, other = (left, right) if lw < rw else (right, left)
        bases = [b[3] for b in other]
        shared = sum(1 for b in side if any(abs(b[3] - y) <= 1.0 for y in bases))
        if shared > TWO_COL_SIDE_MAX_SHARED * max(1, len(side)):
            return None
    short =min(max(b[3] for b in left) - min(b[1] for b in left),
                max(b[3] for b in right) - min(b[1] for b in right))
    return gl, gr, short

# --- side-margin page furniture -------------------------------------------
# Clearance a shape must keep from the body column before it is called margin
# furniture. Margins are inferred, so a shape that merely grazes the column
# edge may be ordinary content sitting against a slightly mis-inferred margin;
# the constructs this rule exists for clear the column by tens of points.
MARGIN_BAND_CLEARANCE = 2.0

# --- running headers and footers --------------------------------------------
# The historical furniture bands, in points from the paper edge. A line inside
# them is furniture on text repetition alone (>= 60% of pages), as it always
# was; every gated document's furniture sits inside them.
TOPZ, BOTZ = 62.0, 64.0
# How far from the edge furniture is SEARCHED for beyond those bands, as a
# fraction of the page height. Measured: the RFC footer row sits 0.137 H above
# the bottom of A4 (y17, y27), a LaTeX book's running head 0.126 H below the
# top (y22), the Supreme Court slip opinion's 0.157 H (y19) -- the deepest
# found. Lines out here qualify only with page-number evidence in their row
# and only in an unbroken chain of furniture rows from the edge.
FURN_EXT_FRAC = 0.2
# Verso/recto running heads are recognised per parity only on documents long
# enough that 60% of one parity's pages is still evidence: 10 pages give 4-5
# pages per class, and the per-class bar is never below 3 pages.
PARITY_MIN_PAGES = 10
# A varying running HEAD found by geometry alone (detect_hf) stands clear of
# the body below it by at least a line of its own type: median clearance over
# its pages (_furniture_clearance) >= GEO_CLEAR_LINES x its size, a line at the
# usual 120% leading. Census of every head signature the geometry pass
# qualified, over both corpora (2026-10-10): the running heads clear by 19.8pt
# (y24's chapter head, 11pt: 1.8 lines), 38.7 (y34's slide titles, 24pt) and
# 40.0 (y26's folios); what it ate besides is body text touching the line
# below -- y64's table titles 1.4pt, y17's and y27's first RFC lines 0.2,
# y55's paragraph lines 9.9 and 10.3 (11pt: 0.78 lines), y54's 8.1 and below.
# FEET are not held to it, though the same census splits them as cleanly
# (y23's folios 40.5, y02's chapter foot 48.7 against y18's last EUR-Lex line
# 0.7, y14's form line -0.4, y47's notes 4.1): written back, those last lines
# are pages the render does not make room for -- y18 raw 156 -> 174 pages
# (144 in the source), product placement dy_p50 2.8 -> 4.5pt; y47 raw 86 -> 93.
GEO_CLEAR_LINES = 1.2
# A drawing covering this much of the sheet is a background, not a margin.
PAGE_COVER_FRAC = 0.9

# --- quote bars -------------------------------------------------------------
# A quote bar sits against the text it marks and is as tall as that text. Both
# limits are in ems of the marked text (median line size). Measured over both
# corpora: the genuine bars leave 14.0pt / 1.08em (04_exec_brief) and 11.9pt /
# 1.08em (x11) before their text and overhang it by at most 8.1pt / 0.62em;
# y09's page-height margin rule (x=41, y 72-720, beside every body page) leaves
# 28.5-29.7pt / 2.4-2.5em and was wrapping 56 of 59 pages in a quote table.
QUOTE_MAX_GAP_EM = 2.0
QUOTE_MAX_OVERHANG_EM = 1.5
# A lone vline running at least this share of the page's height is the side of
# a frame or a box down the page, drawn behind the text rather than stacked in
# the flow as a picture (the stray-shape branch of `_infer_body`). RFC 9110's
# collected-ABNF box sides run 0.66-0.75 of the page. Shorter bars keep the old
# path: an accent bar beside a heading (y48's, 0.27 of its page) is placed with
# the heading by the flow, and floated it moved the median word 15pt.
VLINE_FLOAT_MIN_FRAC = 0.5

# --- grid tables: merged cells and per-edge borders ------------------------
# Every producer in the corpus that rules a table draws its borders PER CELL
# SIDE: Word/PDFMaker one 0.5pt filled bar per side with a joint square where
# four meet, LibreOffice and ReportLab one stroke per side. So on a lattice
# segment the drawn ink covers either nearly all of it (Word: the side less a
# 0.5pt joint, ~97% of a 14pt row) or nothing (the inside of a merged cell).
# 0.45 sits between those and below a dashed border's ~50%, and far above an
# underline or tick that happens to cross a boundary (a few percent).
GRID_EDGE_COVER = 0.45
# A segment lies on a lattice line within this distance. The lattice itself
# clusters line positions at 2.0pt, and the widest single border measured in
# the corpus (FIPS 180's 2.2pt white bar) puts its own centre ~1.1pt off the
# cluster mean of the hairlines beside it.
GRID_EDGE_TOL = 2.5
GRID_MIN_BOTTOM_PAD = 0.5   # pt; see build_grid_table
GRID_MIN_TEXT_FRAC = 0.2    # cells with text, below which a barred lattice is a chart
GRID_CENTER_PAD = 5.4       # pt: Word's default left/right cell margin (0.075in)
# An unshaded row between two shaded bands of one tiled table is one text row:
# c3_tables' are 21.8pt between 22.4pt zebra rows. 2.5 rows admits a wrapped
# white row and refuses a paragraph-sized gap between two separate tables.
TILE_BAND_GAP = 2.5
# Rules (booktabs) tables whose cells the parser kept on one line: the line
# splitter's own threshold (parse_pdfium.LINE_SPLIT_EM) separates them, and a
# gap between columns narrower than 3pt is not a gutter anyone set.
# A headed table's body rows follow at its own pitch: x10's at exactly the
# header's 22.5pt. Two header heights admits a wrapped row and stops at the
# paragraph after the table.
HEADED_ROW_GAP = 2.0
RULES_CELL_GAP_EM = 1.10
RULES_MIN_GUTTER = 3.0
SPACE_EM = 0.28             # a word space in a proportional face, in em
# An hline wider than 0.6 of the column is still an underline when it runs
# under (nearly) the whole of one span -- see the underline pre-pass.
UNDERLINE_SPAN_SHARE = 0.9


def _thin(d: DrawCmd) -> bool:
    x0, y0, x1, y1 = d.bbox
    return min(x1 - x0, y1 - y0) <= RULE_THICK


def _mode(vals, nd=1):
    if not vals:
        return 0.0
    c = Counter(round(v, nd) for v in vals)
    return c.most_common(1)[0][0]


def _cluster(vals: List[float], tol: float) -> List[float]:
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(c) / len(c) for c in out]


def _margin_cluster(vals: List[float], left=True) -> Optional[float]:
    if not vals:
        return None
    cl = _cluster(vals, 2.5)
    n = len(vals)
    good = []
    for c in cl:
        cnt = sum(1 for v in vals if abs(v - c) <= 2.5)
        if cnt >= max(3, 0.08 * n):
            good.append(c)
    if not good:
        return None
    return (min(good) if left else max(good))


def _margin_by_mass(vals: List[float], left=True) -> Optional[float]:
    """Margin estimate that survives a dense ladder of indents.

    `_cluster` chains -- a value joins the previous cluster when it is within
    tol of the PREVIOUS VALUE, not of the cluster's centre. A document with
    many indent levels therefore collapses into a few very wide clusters whose
    means sit between the real edges and match almost nothing, so
    `_margin_cluster`'s 8%-membership test rejects every one of them and it
    returns None.

    That is a measurement failure, not evidence that the page has no margin,
    and the caller's fallback was the constant 72.0 -- an assumption that the
    document uses 1in margins. On the IRS 1040 instructions (14,050 left edges
    collapsing into 3 clusters) the true margin is 42.0, so the constant put
    the content edge 30pt to the right of the text and the column detector,
    which requires the first column to start at the content edge, could never
    fire.

    This counts exact edges instead of clustering them: the leftmost x that
    carries real mass. Used ONLY where `_margin_cluster` finds nothing, so it
    cannot move a document that already has an answer.
    """
    if not vals:
        return None
    counts = Counter(round(v) for v in vals)
    need = max(3.0, 0.02 * len(vals))
    mass = [x for x, c in counts.items() if c >= need]
    if not mass:
        return None
    return float(min(mass) if left else max(mass))


# How far inside the lines it was measured from a right-edge estimate may sit
# before it stops being a measurement and becomes a mis-cluster.
#
# `_margin_cluster` takes the RIGHTMOST cluster carrying 8% of the mass. On a
# ragged-right document the true flush edge legitimately sits a little inside
# the widest lines, because not every line reaches it. But when the flush edge
# itself is thinner than 8% -- which is what a densely fragmented parse does to
# a multi-column page, by turning long lines into many short ones -- the
# rightmost cluster that DOES qualify can be an interior band of line ends, and
# the estimate lands far inside the text it is supposed to bound.
#
# Measured over the expansion corpus, both arms, as (p90 of the wide-line right
# edges) minus (the estimate). The two populations are cleanly separated:
#
#     ragged-right, correct     0.4 .. 22.7pt   (y01, y03, y08, y09, y11,
#                                                y13, y17, and all 16 gated
#                                                documents, which sit at 0.0)
#     mis-clustered             95.8pt          y07_irs_f1040_form  [pdfium]
#                              184.2pt          y06_irs_1040_instr. [pdfium]
#
# 60.0 is the midpoint of that gap: 37pt of margin above the worst correct
# case and 36pt below the worst failure. Both parsers see the same line
# geometry on y06 -- 747 wide lines against 340, p50 527.0 against 504.7, max
# 571.1 against 572.6 -- and PyMuPDF's estimator happens to return None and
# take the mirror-the-left-margin fallback, landing on the correct 42.0, while
# PDFium's returns 385.8 and puts the content edge 184pt inside its own text.
# The reference arm fails SAFE here only by accident; this makes it deliberate
# on both.
#
# p90 rather than max, because max is a single line: y02's reference arm has a
# wide-line max of 613.2 on a 612pt page, which is an outlier, not an edge.
MARGIN_MISCLUSTER_PT = 60.0

# --- cover-band seeding -----------------------------------------------------
# How far below the paper edge a full-width fill may start and still seed the
# cover-band group (`_hf.top_bands`). This was 2.5pt, and 2.5 is not a measured
# number -- it is "flush, allowing for rounding". A cover band that a producer
# insets by a few points is still a cover band, and treating it as ordinary body
# content costs BOTH of the treatments `docxout.has_cover` gates: the zero side
# margin that makes it bleed, and the Google Docs vertical compensation.
#
# It cost exactly that on c1_whitepaper, whose band starts at 7.16 and was
# therefore not recognised. Measured in Google's own export from live pass 6
# (docs/evidence/c1-live-attribution-2026-08-06.json): its band landed 54.52pt
# right of source, overflowing a 612pt page to 660.60, and 17.38pt low against
# the +14.55 that both RECOGNISED bands measured in the same export.
#
# The two populations this has to separate, measured over all 45 committed
# fixtures with no y0 cap:
#
#   must seed (real cover bands)          y0 = 0.00, 0.00, 7.16
#   must NOT seed (nearest other fill)    y0 = 130.0   (04_exec_brief's 8pt
#                                         accent stripe; 01's 4pt one is at
#                                         170.0)
#
# 36.0 sits in that gap with margin in both directions: 5.0x above the worst
# real inset, 3.6x below the nearest fill that must not seed. It is also half an
# inch -- the narrowest top margin in common use -- so a full-width fill
# starting above it cannot be inside the text area of an ordinary page, which is
# the property that actually distinguishes a bleed from a body block.
#
# The accent stripes never seed in practice regardless: `cands` is sorted by y0,
# so a band at 0.00 always claims the group first and the stripe continues it
# through the 3.0pt adjacency rule. The bound is there for the document that has
# a full-width fill part-way down page 1 and no band above it.
COVER_BAND_SEED_PT = 36.0


def _right_edge_misclustered(wide_x1: List[float], mr: Optional[float]) -> bool:
    """Does this right-edge estimate sit too far inside its own evidence?

    True means "not a measurement" -- the caller drops it and takes the
    fallback, which mirrors the left margin and errs WIDE. Erring wide costs a
    little under-wrapping; erring narrow re-wraps every paragraph in the
    document and is what took y06 to 599 pages from 126.
    """
    if mr is None or not wide_x1:
        return False
    ordered = sorted(wide_x1)
    p90 = ordered[int(0.9 * (len(ordered) - 1))]
    return (p90 - mr) > MARGIN_MISCLUSTER_PT


def _two_column_right_edge(body_lines, margin_l: float,
                           page_w: float) -> Optional[float]:
    """Right content edge from verified two-column geometry.

    On two-column pages an inset full-width element (e.g. an abstract)
    can supply the only lines wide enough for the wide-line right-margin
    estimate, pulling the inferred content edge inside the true right
    column.  When the page shows genuine two-column evidence -- a
    repeated x0 cluster at margin_l, a second repeated x0 cluster in the
    middle band, a gutter (left-column lines ending before the second
    column starts), and a repeated flush right edge among the second
    column's lines -- that flush edge is the content right edge.
    Purely geometric: no backend or fixture conditionals."""
    approx_w = page_w - 2 * margin_l
    if approx_w <= 0:
        return None
    left_lines = [l for _, l in body_lines if abs(l.bbox[0] - margin_l) <= 2.5]
    if len(left_lines) < 3:
        return None
    lo = margin_l + 0.35 * approx_w
    hi = 0.7 * page_w
    mid_x0 = [l.bbox[0] for _, l in body_lines if lo <= l.bbox[0] < hi]
    col2 = _margin_cluster(mid_x0, left=True)
    if col2 is None:
        return None
    col2_lines = [l for _, l in body_lines if abs(l.bbox[0] - col2) <= 2.5]
    if len(col2_lines) < 3:
        return None
    # gutter: enough left-column lines must end before column 2 starts
    if sum(1 for l in left_lines if l.bbox[2] < col2 - 6.0) < 3:
        return None
    edge = _margin_cluster([l.bbox[2] for l in col2_lines], left=False)
    if edge is None or edge - col2 < 0.15 * approx_w:
        return None
    if page_w - edge < 14.0:
        return None
    return float(edge)


RULE_EDGE_TEXT_TOL = 2.0   # pt; a line ending this close to a rule edge reaches it

# --- the wrap edge ------------------------------------------------------------
# A line that WRAPPED -- followed in its paragraph by a continuation line at the
# same left edge -- ends where its last word fitted, so the column it was set in
# is at least that wide. That is a hard lower bound on the content edge, and
# the cluster estimate can sit well inside it: `_margin_cluster` takes the
# rightmost cluster holding 8% of the wide lines, and a ragged-right document
# does not put 8% of its lines at any one x. Measured: x05_lo_quotes_notes
# estimated its edge at 529.0 while one of its wrapped lines ends at 547.2 (the
# LibreOffice text area ends at 546.9); x02_lo_report_toc at 535.1 with wrapped
# lines ending at 541.1. Every one of those paragraphs re-wrapped a line longer
# in the render, and each lost line moved the rest of its page by ~14.5pt.
#
# Any edge between the widest wrapped line and the true one reproduces every
# source wrap (each line still fits, and each next word still did not fit in
# the true column, so it cannot fit in a narrower one). So the widener takes
# the widest wrapped line (its 98th percentile -- see `_wrapped_right_edge`),
# prefers the mirrored left margin when that lies just beyond it (word
# processors set symmetric margins), and acts only when it disagrees with the
# estimate by more than the protrusion a justified TeX or Typst line shows (y13
# and y20 reach 2.2pt past their estimates by hanging punctuation). Gated
# fixtures: the widest wrapped line sits 0.0-0.8pt from the estimate on all
# sixteen, so none moves. Expansion movers, all toward the measured text: x02,
# x05, the NIST pair y01/y09, whose ragged Word bodies estimated 519pt against
# wrapped lines at 540 (the 1in mirror), and y21 (502.8 -> 509.7, where its
# wrapped lines' 95th percentile already sits at 508.5).
WRAP_EDGE_MIN_GAIN = 2.5   # pt
WRAP_EDGE_MIRROR_PT = 8.0  # how far past the widest line a mirrored edge may sit
WRAP_EDGE_MIN_LINES = 3    # wrapped lines needed before the bound is used
WRAP_EDGE_QUANTILE = 0.98  # see _wrapped_right_edge


def _wrapped_right_edge(ir: DocIR, hf: dict, page_w: float) -> Optional[float]:
    """The right end of the widest line that wrapped onto a continuation."""
    ends = []
    for p in ir.pages:
        ct = hf["consumed_text"][p.number]
        # Only a page set in ONE wide column says anything about its width.
        # On a multi-column page the few wide "lines" are the parser's
        # cross-column merges ("safety. EPA determines whether acute In
        # making its tolerance", y61's three-column Federal Register), they
        # end at the outer column's edge, and widening to them reflowed that
        # document from 8 pages to 10. A page whose lines are mostly narrow
        # is such a page.
        widths = sorted(l.bbox[2] - l.bbox[0]
                        for bi, b in enumerate(p.blocks) for l in b.lines
                        if (bi, id(l)) not in ct and l.horizontal and l.spans
                        and l.text.strip().count(" ") >= 3)
        if not widths or widths[len(widths) // 2] < 0.45 * page_w:
            continue
        for bi, b in enumerate(p.blocks):
            ls = [l for l in b.lines
                  if (bi, id(l)) not in ct and l.horizontal and l.spans]
            for l1, l2 in zip(ls, ls[1:]):
                if (l1.bbox[2] - l1.bbox[0]) < 0.45 * page_w:
                    continue
                if l1.bbox[2] > page_w - 14.0:
                    continue                     # into the paper edge
                s1, s2 = _line_size(l1), _line_size(l2)
                step = l2.baseline - l1.baseline
                if abs(s1 - s2) > 0.5 or not (0.5 * s1 < step <= 2.5 * s1):
                    continue                     # not the same paragraph
                # a continuation starts where l1 did (or left of an indented
                # first line), never further right: that is a nested item
                if l2.bbox[0] > l1.bbox[0] + 1.0 or l2.bbox[0] < l1.bbox[0] - 40:
                    continue
                # a single unbreakable token may overflow its column
                if l1.text.strip().count(" ") < 3:
                    continue
                # verbatim lines do not wrap; consecutive code lines only
                # look like a paragraph (RFC listings, y23's mono tables)
                if sum(len(s.text) for s in l1.spans if s.mono) > \
                        0.5 * len(l1.text):
                    continue
                ends.append(l1.bbox[2])
    if len(ends) < WRAP_EDGE_MIN_LINES:
        return None
    # The widest line, short of the rare one that is not a wrap at all: TeX
    # sets an overfull line PAST its column when no break fits (y25 has one
    # 74pt out; y22 one 7pt out), and a cover page may set its own measure
    # (y02's withdrawal notice). The 98th percentile ignores those, and on a
    # short document -- under 50 wrapped lines -- it is the widest line.
    ends.sort()
    return ends[max(0, int(math.ceil(WRAP_EDGE_QUANTILE * len(ends))) - 1)]


def _field_row_ends(pages_lines, margin_l: float, page_w: float) -> List[float]:
    """Right ends of label/field rows: two fragments on one baseline, the
    label starting at the left margin, the field short and set in a different
    style after a real gap -- a résumé's role and date. Used only as evidence
    that text reaches a rule edge (`_rule_right_edge`); the right content
    edge is not known yet, so the field's width is judged against the
    mirrored-margin estimate of the content width."""
    width = page_w - 2 * margin_l
    if width <= 0:
        return []
    out = []
    for lines in pages_lines:
        ls = sorted((l for l in lines if l.horizontal and l.spans),
                    key=lambda l: (round(l.baseline, 1), l.bbox[0]))
        rows = []
        for ln in ls:
            if rows and abs(ln.baseline - rows[-1][0].baseline) <= _ROW_BASELINE_TOL:
                rows[-1].append(ln)
            else:
                rows.append([ln])
        for row in rows:
            if len(row) != 2:
                continue
            left, right = row
            if left.bbox[0] > margin_l + _ROW_LEFT_TOL \
                    or right.bbox[0] - left.bbox[2] < _ROW_MIN_GAP \
                    or right.bbox[2] - right.bbox[0] > _ROW_MAX_RIGHT * width \
                    or left.bbox[2] - left.bbox[0] < _ROW_MIN_LEFT * width \
                    or not _row_contrast(left, right):
                continue
            out.append(right.bbox[2])
    return out


def _rule_right_edge(ir: DocIR, hf: dict, page_w: float,
                     wide_x1: List[float],
                     row_x1: Optional[List[float]] = None,
                     body_boxes=()) -> Optional[float]:
    """Right content edge from the document's own full-width rules.

    The wide-line right-margin estimate reads where wide TEXT lines end. A
    ragged-right document keeps its flush edge below that estimator's 8%
    membership floor -- not every line reaches the edge, that is what
    ragged means -- so the rightmost qualifying cluster is an interior band
    of line ends and the content edge lands inside the text it bounds.

    Measured on a real 32-page ragged-right report (Chrome print-to-PDF,
    Georgia body): the text cluster returned 519.7 on a 595pt page while
    every one of the document's 32 full-width horizontal rules ends at
    exactly 539.25 -- the designer's own column edge, unanimous, drawn 32
    times. The hand-measured cost of trusting the text cluster there was
    ~19.5pt of lost column width, which re-wrapped every paragraph in the
    document and nearly doubled its page count in Google Docs.

    A rule qualifies only when it is thin (a rule, not a shape) and at
    least as wide as the wide-line standard (0.45 of the page), and the
    candidate edge must carry repeated rule mass -- `_margin_cluster`'s
    max(3, 8%) floor -- so one stray stroke cannot move the column. Edges
    within 14pt of the paper edge are rejected outright: a rule that
    bleeds is page furniture, not a column boundary.

    The edge must also EXIST IN THE TEXT: no further than 5pt beyond the
    p90 of the wide-line right ends. A true column edge is one text
    reaches -- the ragged top decile lands 3.75pt short of B13's 539.25 --
    while a decorative rule overshoots a correctly-measured column by
    design: 01_whitepaper_market's text cluster and p90 both sit at 552.0
    and six of its rules run to 558.0, a 6pt overshoot that moved a gated
    margin when this guard did not exist. The caller only ever widens
    content with the answer, never narrows it.

    `body_boxes` -- (page, bbox) of every body line -- lets text other than
    wide lines vouch for the edge: right-aligned fields that reach it, inside
    the prose band of their page, on more than one page (see below).
    """
    x1s: List[float] = []
    for p in ir.pages:
        cd = hf["consumed_draw"].get(p.number, ())
        for di, d in enumerate(p.drawings):
            if di in cd:
                continue
            x0, y0, x1, y1 = d.bbox
            if (y1 - y0) <= RULE_THICK and (x1 - x0) >= 0.45 * page_w:
                x1s.append(x1)
    if not x1s:
        return None
    edge = _margin_cluster(x1s, left=False)
    if edge is None or page_w - edge < 14.0:
        return None
    if wide_x1:
        ordered = sorted(wide_x1)
        p90 = ordered[int(0.9 * (len(ordered) - 1))]
        # Text also reaches an edge through right-aligned FIELDS: a résumé's
        # dates end at its rules (x17: rules at 552.75, four dates at 552.3)
        # while its ragged prose stops ~23pt short (p90 529.9), so the prose
        # test alone kept a 486pt column for 509pt of text -- every date's
        # tab stop and every centred line was measured against the wrong
        # edge. Two label/field rows ending at the rule edge are the text
        # existing there. 01_whitepaper's overshooting rules have none.
        #
        # Failing label/field rows, body lines of ANY width reaching the
        # edge are the same evidence -- provided they recur through the
        # document as body text. Not furniture: an RFC's "Page N" footer
        # ends at its header rule's edge on every page, 10pt past the prose,
        # so a hit must sit within the vertical band its page's prose
        # occupies. Not one page's oddity: three cover-page lines of
        # EUR-Lex's Official Journal masthead end at its rule edge and
        # nothing else does.
        fields = sum(1 for x in (row_x1 or ()) if abs(x - edge) <= 1.5)
        if edge > p90 + 5.0 and fields < 2:
            band = {}
            for pg, bb in body_boxes:
                if (bb[2] - bb[0]) >= 0.45 * page_w:
                    lo, hi = band.get(pg, (bb[1], bb[3]))
                    band[pg] = (min(lo, bb[1]), max(hi, bb[3]))
            hits = [pg for pg, bb in body_boxes
                    if edge - RULE_EDGE_TEXT_TOL <= bb[2] <= edge + 1.0
                    and pg in band
                    and band[pg][0] <= (bb[1] + bb[3]) / 2 <= band[pg][1]]
            if len(hits) < 2 or len(set(hits)) < min(2, len(ir.pages)):
                return None
    return float(edge)


# ------------------------------------------------------------------ runs/paras
def _soft_join(runs: List[Run], next_text: str, dehyphenate: bool = True):
    """Append a joiner between wrapped lines: space normally, dehyphenate
    when the previous line ends with a hyphenated word break.

    `dehyphenate` is the caller's geometry verdict on that hyphen: a hyphen
    only marks a word break when its line reached the wrap edge, because
    hyphenation is how a justified line buys its last few points. A
    ragged-right line that stops short of the edge carries a *real* hyphen
    ("co-author" split across lines), and the join must keep it, not eat it.
    Unconditional dehyphenation deleted 37 real hyphens and spaced 4 more on
    a 32-page ragged-right report (defect catalogue #10, live-verified in
    Google Docs: every drawn hyphen in it is real text, none a break).

    Inside a conversion the geometry verdict is only the last resort: the
    document's own vocabulary decides first (exactdoc.hyphen). Geometry alone
    kept 464 breaks mid-word on a ragged-right booklet (`re-turn`) and deleted
    real hyphens in a justified paper (`singlecorpus`).
    """
    if not runs:
        return
    last = runs[-1].text
    nxt = next_text.lstrip()[:1]
    if last.endswith("-") and len(last) >= 2 and last[-2].isalpha() \
            and nxt.islower():
        ev = hyphen.current()
        pair = hyphen.split_pair(last, next_text) if ev is not None else None
        if pair is not None:
            dehyphenate = ev.is_break(pair[0], pair[1], at_edge=dehyphenate)
        if dehyphenate:
            runs[-1].text = last[:-1]
    elif not last.endswith((" ", "-")):
        runs[-1].text += " "


# Two runs whose measured letter-spacing differs by less than this are one run:
# every source line measures its own value (x07's body lines 0.24-0.34pt, the
# spread of Chromium's pixel rounding), and splitting a paragraph's runs at each
# line would fragment it for a difference the writer's 1/20pt unit barely holds.
TRACK_MERGE_PT = 0.1


def _closed_up(s: Span) -> Optional[str]:
    """`O V E R V I E W` -> `OVERVIEW`, when the document spells the word.

    A word set in spaced capitals arrives with a space in every gap, because
    each gap is wider than a space (WDR: 0.42em). The parser marks such a run;
    whether it is ONE word or a row of letters (an alphabet bar, a key) is a
    question of vocabulary, so it is answered here, where the document's own
    word list exists. Unattested strings keep their spaces.
    """
    if not getattr(s, "spaced_letters", False):
        return None
    word = re.sub(r"\s+", "", s.text)
    ev = hyphen.current()
    if ev is None or not word.isalpha() or not ev.words[word.lower()]:
        return None
    lead = s.text[:len(s.text) - len(s.text.lstrip())]
    trail = s.text[len(s.text.rstrip()):]
    return lead + word + (" " if trail else "")


def runs_from_spans(spans: List[Span]) -> List[Run]:
    runs: List[Run] = []
    for s in spans:
        # justified text extracts stretched word gaps as doubled spaces;
        # collapse them (except in monospace) so re-wrap matches the source
        txt = s.text if s.mono else re.sub(r" {2,}", " ", s.text)
        tracking = getattr(s, "tracking", 0.0)
        closed = _closed_up(s)
        if closed is not None:
            txt = closed
        elif getattr(s, "spaced_letters", False):
            tracking = 0.0              # the spaces stay, and carry the width
        r = Run(text=txt, font=s.font, size=s.size, color=s.color,
                bold=s.bold, italic=s.italic, mono=s.mono, serif=s.serif,
                link=s.link, dest=getattr(s, "dest", None),
                underline=bool(getattr(s, "_ul", False)),
                superscript=s.superscript, tracking=tracking)
        if runs:
            p = runs[-1]
            if (p.font == r.font and abs(p.size - r.size) < 0.05 and p.color == r.color
                    and p.bold == r.bold and p.italic == r.italic and p.link == r.link
                    and p.dest == r.dest
                    and p.underline == r.underline and p.superscript == r.superscript
                    and abs(p.tracking - r.tracking) < TRACK_MERGE_PT):
                if p.tracking != r.tracking:
                    n_p, n_r = len(p.text), len(r.text)
                    p.tracking = round((p.tracking * n_p + r.tracking * n_r)
                                       / max(1, n_p + n_r), 3)
                if not p.mono and p.text.endswith(" ") and r.text.startswith(" "):
                    p.text += r.text.lstrip(" ")
                else:
                    p.text += r.text
                continue
            if not r.mono and runs[-1].text.endswith(" ") and r.text.startswith(" "):
                r.text = r.text.lstrip(" ") or r.text
        runs.append(r)
    return runs


def _line_size(ln: Line) -> float:
    return max((s.size for s in ln.spans), default=10.0)


# Line-level form of parse_pdfium's collision rule: text runs of two lines that
# cover each other horizontally are two lines, whatever their baselines say.
# Without it a heading overprinting a running footer 0.75pt away (x07) became
# one row, and a booklet index's 8pt entries 9.5pt above a large index letter
# were absorbed as "superscripts" of the line beside it (y13: `Kidnapped 13,
# 18` + raised `age 18 3, 4`). A script sits beside the glyph it modifies.
OVERPRINT_FRAC = 0.5
SCRIPT_MAX_EM = 1.5     # wider than this (about three glyphs) is not a script


def _overprinted(a: Line, b: Line, sized: bool = False) -> bool:
    """Do two lines' inked spans cover each other by more than half the
    narrower span? With `sized`, only lines whose type differs by >15% count:
    a same-size overlap is a producer drawing one line twice."""
    if sized:
        sa, sb = _line_size(a), _line_size(b)
        if abs(sa - sb) <= 0.15 * max(sa, sb):
            return False
    for s in a.spans:
        if not s.text.strip():
            continue
        s0, s1 = ink_extent(s)
        for t in b.spans:
            if not t.text.strip():
                continue
            t0, t1 = ink_extent(t)
            ov = min(s1, t1) - max(s0, t0)
            w = min(s1 - s0, t1 - t0)
            if w > 0.5 and ov > OVERPRINT_FRAC * w:
                return True
    return False


def _merge_row_lines(lines: List[Line]) -> List[Line]:
    """Merge Line fragments that share a baseline into single visual rows.

    PDF producers split lines at link/style boundaries; alignment analysis
    needs whole visual rows.

    Grouping is by BASELINE, not by bbox top. Tops disagree whenever glyph
    heights disagree -- a fragment reading "R^{d x d}" is far taller than one
    reading "i" even though both sit on the same baseline -- so top-grouping
    silently split every line of inline maths into separate rows, and each
    fragment then became its own single-line paragraph. One measured pdfTeX
    page turned two source lines into eight paragraphs; each consumed a full
    line, the page overflowed, and since every source page ends in a hard
    break the overflow cost a whole page. That was the bulk of LaTeX page
    inflation.

    A second pass then absorbs true super/subscripts: smaller fragments whose
    baseline is shifted but which still sit inside the host row's em box.
    """
    rows: List[List[Line]] = []
    for ln in sorted(lines, key=lambda l: (round(l.baseline, 1), l.bbox[0])):
        placed = False
        for row in rows:
            tol = max(1.2, 0.18 * _line_size(row[0]))
            if abs(ln.baseline - row[0].baseline) < tol and \
                    not any(_overprinted(ln, o, sized=True) for o in row):
                row.append(ln)
                placed = True
                break
        if not placed:
            rows.append([ln])

    # absorb raised/lowered script fragments into the row they belong to
    rows.sort(key=lambda r: min(l.baseline for l in r))
    merged = True
    while merged:
        merged = False
        for i, frag in enumerate(rows):
            if len(frag) != 1:
                continue
            f = frag[0]
            fsz = _line_size(f)
            for j, host in enumerate(rows):
                if i == j or not host:
                    continue
                hsz = max(_line_size(l) for l in host)
                if fsz >= 0.92 * hsz:
                    continue                      # same size: a real line
                hb = host[0].baseline
                if abs(f.baseline - hb) > 0.75 * hsz:
                    continue                      # outside the em box
                hx0 = min(l.bbox[0] for l in host)
                hx1 = max(l.bbox[2] for l in host)
                if f.bbox[0] < hx0 - 2.0 or f.bbox[0] > hx1 + 0.5 * hsz:
                    continue                      # not adjacent horizontally
                # A script is a glyph or three; a host span's box can contain
                # one legitimately (the span runs on past it), so only a
                # fragment longer than that is tested for overprinting.
                if (f.bbox[2] - f.bbox[0]) > SCRIPT_MAX_EM * fsz and \
                        any(_overprinted(f, h) for h in host):
                    continue                      # a line over the host's text
                for s in f.spans:
                    if f.baseline < hb - 0.12 * hsz:
                        s.superscript = True
                host.append(f)
                rows.pop(i)
                merged = True
                break
            if merged:
                break

    out = []
    for row in rows:
        # A right-to-left row reads from its rightmost fragment (see
        # _rtl_lines); its pieces join in that order, the gap measured from
        # each piece's left end to the next one's right end.
        rtl = len(row) > 1 and _rtl_lines(row)
        if rtl:
            row.sort(key=lambda l: -l.bbox[2])
        else:
            row.sort(key=lambda l: l.bbox[0])
        if len(row) == 1:
            out.append(row[0])
            continue
        spans = []
        for i, ln in enumerate(row):
            if i > 0 and spans:
                gap = (row[i - 1].bbox[0] - ln.bbox[2]) if rtl else \
                    (ln.bbox[0] - row[i - 1].bbox[2])
                if gap > 0.25 * (spans[-1].size or 10) and \
                        not spans[-1].text.endswith(" "):
                    spans[-1].text += " "
            spans.extend(ln.spans)
        bb = None
        for ln in row:
            bb = bbox_union(bb, ln.bbox)
        out.append(Line(spans=spans, bbox=bb, dir=row[0].dir, rtl=rtl))
    out.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
    return out


def _marker_split_idx(spans) -> Optional[int]:
    """Index k such that spans[:k+1] form a list marker followed by item text.

    Separation counts if there is a real gap OR the marker span carries its
    own trailing space (WeasyPrint markers sit flush against the text box).
    """
    for j in range(min(3, len(spans) - 1)):
        prefix = "".join(s.text for s in spans[:j + 1])
        sep = (spans[j + 1].bbox[0] - spans[j].bbox[2] >= 2.0) or \
            prefix.endswith(" ")
        m = prefix.strip()
        if sep and m and (m in BULLET_CHARS or NUM_RE.match(m)):
            return j
        if len(m) > 4:
            return None
    return None


def _is_marker_text(t: str) -> bool:
    """Is this whole line nothing but a list marker?

    `_marker_split_idx` cannot answer it: that one wants a marker AND its item
    text inside one line, and a producer is equally free to draw the bullet as a
    line fragment of its own beside the text. Measured on y11_nist_sp80053r5,
    where every `•` arrives that way.
    """
    m = t.strip()
    return bool(m) and (m in BULLET_CHARS or bool(NUM_RE.match(m)))


def _line_starts_with_marker(ln: Line) -> bool:
    if len(ln.spans) < 2:
        return False
    return _marker_split_idx(ln.spans) is not None


# ------------------------------------------------------------ typed list markers
# A marker TYPED as text -- "• Rebuilt the ingestion path…", "1. Install…" --
# arrives in the same span as its item text, so `_marker_split_idx`, which only
# looks for a marker at a span boundary, never sees it. Measured: x17/x18's
# résumé bullets (CSS `text-indent:-11.5pt` with a literal "• ") fused three
# items into one paragraph ("…partition loss. • Introduced…" on one rendered
# line), and y17_rfc9110 p40's four "• control data…" items -- one block each,
# glued back together by `_merge_flow_paras` -- became one justified paragraph.
#
# A token at the start of a line is weak evidence on its own: a wrapped line can
# begin "– as expected –", "10. In this", "* note". So a typed marker opens an
# item only with LIST evidence from the same flow (`_inline_list_starts`):
#   glyph bullets   a second line opening with the same glyph at the same x, or
#                   a hanging indent under this one (its continuation indented
#                   by the marker's width);
#   dashes, "*"     a second line with the same marker at the same x;
#   1. a) (iv)      a neighbour in sequence -- n-1 or n+1, same punctuation,
#                   same x. "5. Section heading" alone is not a list; a
#                   numbered heading run "4." "5." is a sequence, and splitting
#                   there changes nothing because a heading already ends a
#                   paragraph.
# Monospaced lines never qualify: "- key: value" and " * comment" in a code
# block are code, and splitting would break the verbatim block apart.
_INLINE_GLYPHS = frozenset("•◦▪‣●○■□➤►♦❖➢✓✔∙⁃")
_INLINE_DASHES = frozenset("-–—*·")
_INLINE_ORD_RE = re.compile(r"(\(?)(\d{1,3}|[ivx]{1,5}|[a-zA-Zא-ת"
                            r"ء-ي])([.)])(?=\s+\S)")
_INLINE_X_TOL = 2.0     # same list column: markers of one list share their x
_INLINE_HANG_MAX = 40.0  # a hang wider than this is a new column, not a marker's width
# Letter ordinals of right-to-left lists: Hebrew in alphabet order (final forms
# are not ordinals), Arabic in abjad order (أ ب ج د ه و ز ح ط ي ...), which is
# how Arabic sub-lists count.
_HEB_ORD = "אבגדהוזחטיכלמנסעפצקרשת"
_ABJAD_ORD = "أبجدهوزحطيكلمنسعفصقرشتثخذضظغ"


def _start_x(ln: Line) -> float:
    """Where a line STARTS, signed so that larger means further along its
    reading direction: the left edge of a Latin line, the negated right edge
    of a right-to-left one."""
    return -ln.bbox[2] if getattr(ln, "rtl", False) else ln.bbox[0]


def _roman_value(tok: str) -> int:
    vals = [{"i": 1, "v": 5, "x": 10}[c] for c in tok]
    return sum(-v if i + 1 < len(vals) and vals[i + 1] > v else v
               for i, v in enumerate(vals))


def _inline_marker(text: str):
    """(style, values) when `text` opens with a typed list marker and item text.

    `style` groups markers that belong to one list; `values` is the set of
    ordinals a numbered marker may stand for ("i" is both the ninth letter and
    roman one), None for bullets.
    """
    t = text.lstrip()
    if len(t) < 3:
        return None
    c = t[0]
    if c in _INLINE_GLYPHS or c in _INLINE_DASHES:
        if t[1] in (" ", "\t", "\u00a0") and t[2:].strip():
            return (("glyph" if c in _INLINE_GLYPHS else "dash", c), None)
        return None
    m = _INLINE_ORD_RE.match(t)
    if not m:
        return None
    op, tok, cl = m.groups()
    if op and cl != ")":
        return None                     # "(1." is not a marker
    if tok.isdigit():
        return (("num", op, cl), {int(tok)})
    if tok in _HEB_ORD or tok in _ABJAD_ORD:
        order = _HEB_ORD if tok in _HEB_ORD else _ABJAD_ORD
        return (("rtl-letter", op, cl), {order.index(tok) + 1})
    if not tok.isascii():
        return None
    if tok.isupper():
        # "A." opens initials ("J. Smith") and outline headings; only the
        # parenthesised forms are unambiguous enough to take.
        if cl != ")":
            return None
        return (("ALPHA", op, cl), {ord(tok) - 64})
    vals = set()
    if len(tok) == 1:
        vals.add(ord(tok) - 96)
    if set(tok) <= set("ivx"):
        vals.add(_roman_value(tok))
    return (("alpha", op, cl), vals)


def _line_key(ln: Line):
    return (round(ln.bbox[0], 1), round(ln.baseline, 1))


def _inline_list_starts(blocks) -> set:
    """Keys (`_line_key`) of lines that open a list item with a typed marker.

    `blocks` is a sequence of line lists in reading order; the hang test looks
    at the line that follows a candidate inside its own block.
    """
    cands = []
    for lines in blocks:
        rows = sorted((l for l in lines if l.spans and l.horizontal),
                      key=lambda l: (l.bbox[1], l.bbox[0]))
        for i, ln in enumerate(rows):
            if all(s.mono for s in ln.spans if s.text.strip()):
                continue
            m = _inline_marker(ln.text)
            if m is None:
                continue
            hang = False
            if i + 1 < len(rows):
                nx = rows[i + 1]
                sz = _line_size(ln)
                if 1.5 < _start_x(nx) - _start_x(ln) <= _INLINE_HANG_MAX \
                        and 0 < nx.baseline - ln.baseline <= 2.2 * sz \
                        and _inline_marker(nx.text) is None:
                    hang = True
            cands.append((ln, m[0], m[1], hang))
    out = set()
    for ln, style, vals, hang in cands:
        peers = [c for c in cands if c[1] == style and c[0] is not ln
                 and abs(_start_x(c[0]) - _start_x(ln)) <= _INLINE_X_TOL]
        if style[0] == "glyph":
            ok = bool(peers) or hang
        elif style[0] == "dash":
            ok = bool(peers)
        else:
            ok = any(abs(v - w) == 1 for c in peers for v in vals for w in c[2])
        if ok:
            out.add(_line_key(ln))
    return out


def _line_tracked(ln: Line) -> Optional[bool]:
    """Is this whole line letter-spaced? None when it is neither cleanly.

    Measured by the parser, never guessed here. A line that mixes tracked and
    untracked runs answers None rather than picking a side, because a run-in
    heading followed by body text on the SAME line is one line and splitting
    around it would be a lie about the source.
    """
    tot = sum(len(s.text.strip()) for s in ln.spans)
    if not tot:
        return None
    n = sum(len(s.text.strip()) for s in ln.spans if getattr(s, "tracked", False))
    if n >= 0.8 * tot:
        return True
    if n <= 0.2 * tot:
        return False
    return None


_RTL_TEXT = re.compile("[֐-ࣿיִ-﷿ﹰ-﻿]")


# ---------------------------------------------------------- right-to-left lines
# A Hebrew or Arabic paragraph is the mirror image of a Latin one: it starts on
# the right, its ragged last line is flush RIGHT, its first-line indent and its
# list hang are measured from the right edge. Every geometric test below was
# written for the Latin shape, and measured on the tranche-4 RTL documents
# (y47-y50) that was much of their page inflation: a justified Hebrew
# paragraph's ragged-left last line failed `left_flush`, the full-width lines
# passed the centring test, and y49 p2's first paragraph came out CENTRED; a
# right-flush paragraph got a left indent the width of its last line's gap.
#
# The parser already hands over RTL lines in logical order (Line.rtl), so the
# first span is the rightmost. Mirroring the geometry about the column's axis
# makes such a paragraph exactly the Latin shape the tests expect -- logical
# span order then runs left to right too -- and the answer comes back in
# START/END terms, which is what OOXML's w:jc and w:ind mean in a w:bidi
# paragraph (left = start, right = end; probed in the pinned LibreOffice: a
# bidi paragraph with jc=left sets flush right, ind left=1in pulls the right
# edge in by 1in, firstLine indents the right end of the first line).
def _rtl_lines(lines) -> bool:
    """Do these lines read right to left? Majority by text, ties to RTL."""
    n_r = n_l = 0
    for ln in lines:
        n = len(ln.text.strip())
        if getattr(ln, "rtl", False):
            n_r += n
        else:
            n_l += n
    return n_r > 0 and n_r >= n_l


def _mirror_box(b, axis: float):
    return (axis - b[2], b[1], axis - b[0], b[3])


def _mirror_line(ln: Line, axis: float) -> Line:
    """A copy of `ln` reflected about x = axis / 2 (spans copied, text shared)."""
    spans = []
    for s in ln.spans:
        m = replace(s, bbox=_mirror_box(s.bbox, axis),
                    origin=(axis - s.origin[0], s.origin[1]))
        for k in ("_note_mark", "_ul"):          # inference's own span marks
            if hasattr(s, k):
                setattr(m, k, getattr(s, k))
        spans.append(m)
    return Line(spans=spans, bbox=_mirror_box(ln.bbox, axis), dir=ln.dir,
                rtl=getattr(ln, "rtl", False))


def _opens_note(ln: Line) -> bool:
    """Does the line open with a glued footnote number (`_merge_list_markers`)?"""
    inked = [s for s in ln.spans if s.text.strip()]
    if getattr(ln, "rtl", False):
        first = max(inked, key=lambda s: s.bbox[2], default=None)
    else:
        first = min(inked, key=lambda s: s.bbox[0], default=None)
    return first is not None and getattr(first, "_note_mark", False)


def _first_word_w(ln: Line) -> float:
    """Width of a line's first word, apportioned from its span by characters."""
    s = next((s for s in ln.spans if s.text.strip()), None)
    if s is None:
        return 0.0
    t = s.text.lstrip()
    word = t.split()[0] if t.split() else t
    return (s.bbox[2] - s.bbox[0]) * len(word) / max(1, len(s.text))


# Lines of one text column start at its left edge or within a list hang of it
# (_INLINE_HANG_MAX). A box whose lines start further apart holds columns of
# its own -- y59's mock-up notice page, two columns inside one frame -- and
# there the widest line says nothing about where any one line could have
# continued: read against it, every left-column line "broke by hand" and the
# mock-up became one paragraph per line, three pages longer.
def _text_column_edge(lines) -> Optional[float]:
    """The right edge forced breaks are read against, or None when lines
    are not one text column (see above)."""
    xs = [ln.bbox[0] for ln in lines if ln.text.strip()]
    if not xs:
        return None
    if max(xs) - min(xs) > _INLINE_HANG_MAX:
        fr = _flush_right_edge(lines)
        if fr is not None:
            return fr
        # no line has room to spare against -inf, so only the heading rule
        # of _forced_break can fire: y46's ragged-left column keeps its bold
        # entry titles apart from the text under them
        return float("-inf")
    return max(ln.bbox[2] for ln in lines)


# A flush-left column may set a line flush RIGHT: a court caption's
# "Plaintiff," and "Defendant." against the caption's rule (y63, ending 0.1pt
# apart at 315.6/315.7 while the parties' own lines start at 75.6). Such a
# line is not a column of its own (y59's) and not a wrapped line either: it is
# a paragraph of one line. Read as -inf the caption's six lines ran together
# as one paragraph that re-wrapped across the column (y63 5 -> 6 pages,
# character recall 1.000 -> 0.937 once WP15 had cleared its line numbers).
FLUSH_RIGHT_TOL = 2.0


def _flush_right_edge(lines) -> Optional[float]:
    """For a flush-left column whose only lines off its left edge are set
    flush right: the flush-left lines' own right edge, which the flush-right
    lines reach past (`_forced_break` sets each on its own). Else None."""
    lines = [ln for ln in lines if ln.text.strip()]
    if len(lines) < 2:
        return None
    x0 = min(ln.bbox[0] for ln in lines)
    flush = [ln for ln in lines if ln.bbox[0] - x0 <= _INLINE_HANG_MAX]
    off = [ln for ln in lines if ln.bbox[0] - x0 > _INLINE_HANG_MAX]
    if not off or len(flush) < SBS_FLUSH_SHARE * len(lines):
        return None
    right = max(ln.bbox[2] for ln in lines)
    edge = max(ln.bbox[2] for ln in flush)
    if right - edge <= FLUSH_RIGHT_TOL or             any(right - ln.bbox[2] > FLUSH_RIGHT_TOL for ln in off):
        return None
    return edge


def _forced_break(prev: Line, ln: Line, col_r: float) -> bool:
    """Did the source END `prev` rather than wrap it?

    A wrapping line breaks only when the next word does not fit, so a line
    that stops short of its column with room for the next line's first word
    was broken by hand -- a heading over its text, the lines of an address or
    a contact list. y58's 'Retirement Benefits' (12pt bold, 142pt of a 252pt
    panel) and the paragraph under it read as one paragraph and wrapped as
    one. Hyphenated ends are wraps whatever their room. Used only where a
    panel or a layout column is read (`forced=True`), whose right edge is its
    own measured text edge."""
    if prev.text.rstrip().endswith(("-", "­")):
        return False
    # A line reaching past the column's own text edge is set flush right, a
    # paragraph of its own (_flush_right_edge); elsewhere no line can.
    if math.isfinite(col_r) and (prev.bbox[2] > col_r + 1.0 or
                                 ln.bbox[2] > col_r + 1.0):
        return True
    # A wholly bold line over a line with no bold is a heading over its
    # text: the sidebar fixture's 'CONTACT' over 'jordan@example.com', whose
    # 83pt address would not have fitted the 63pt left on the heading's line.
    # (Flow-wide, a bold delta splits labels and table cells -- see the
    # tracking note in _split_lines_to_paras -- which is why this, too, is
    # read only inside a panel or a layout column.)
    pb = [s.bold for s in prev.spans if s.text.strip()]
    nb = [s.bold for s in ln.spans if s.text.strip()]
    if pb and nb and all(pb) and not any(nb):
        return True
    size = max((s.size for s in ln.spans if s.text.strip()), default=10.0)
    room = col_r - prev.bbox[2]
    return room > _first_word_w(ln) + FORCED_BREAK_SPACE_EM * size


# A line pitch at least this many times the type size is double-ish spacing
# (Word's "double" at 12pt is 27.6pt = 2.3em; y63 sets 14.04pt type at
# 24.1pt = 1.72em). Single spacing runs 1.15-1.25em.
DOUBLE_SPACED_PITCH = 1.6
# The fewest lines whose median pitch says how a block is spaced.
DOUBLE_SPACED_MIN_LINES = 3


def _author_break(a: Line, b: Line, right: float, pitch: float,
                  n_lines: int = DOUBLE_SPACED_MIN_LINES) -> bool:
    """Did the author end the paragraph at `a`? The next line's first word
    would have fitted on it.

    A paragraph is a line run that the line breaker filled: it moves a word
    down only when the word does not fit. Where `a` plus the space plus `b`'s
    first word stays inside the block's right edge, the break was the
    author's. It is the only paragraph evidence in text set with no space
    between paragraphs -- double-spaced pleadings mark a new paragraph by the
    short line before its indent alone, and on y63_court_pleading_word365
    (24.1pt pitch throughout) every page was otherwise one paragraph with its
    headings and sub-paragraphs fused into it. `right` is the furthest line end
    in the block, which can only sit inside the true column edge, so the test
    errs towards joining. Only where the pitch leaves no room for paragraph
    spacing to say it (DOUBLE_SPACED_PITCH): a single-spaced document states
    its paragraphs in its gaps, and the fit test, whose word width is an
    estimate, has no business second-guessing those. `pitch` is the block's
    TIGHTEST baseline step, so every line of it must be double-spaced: a
    heading's space below it is not double spacing (y39's "3 Extending
    ensemble Kalman filters" over 12pt-pitch text, recall 0.735 -> 0.711 when
    the median was asked), and a block of fewer than DOUBLE_SPACED_MIN_LINES
    has no pitch worth the name (x02's two-line cover block).
    """
    size = max((s.size for s in a.spans if s.text.strip()), default=0.0)
    if size <= 0 or pitch < DOUBLE_SPACED_PITCH * size or \
            n_lines < DOUBLE_SPACED_MIN_LINES:
        return False
    if b.baseline - a.baseline < 0.5 * size:
        return False                    # the same row: a marker and its text
    if _RTL_TEXT.search(a.text) or _RTL_TEXT.search(b.text):
        # A right-to-left line ends short on its LEFT; the fit test measures
        # from the right end, so it says nothing about one.
        return False
    at = a.text.rstrip()
    if not any(ch.isalpha() for ch in at) or \
            not any(ch.isalpha() for ch in b.text):
        # Not prose: a chart's axis labels ("54" over "52", y47) are a
        # stack of short lines no line breaker filled.
        return False
    if not at or at.endswith(("-", "­")):
        return False                    # a hyphenated word runs on
    words = b.text.split()
    if not words:
        return False
    bt = b.text.strip()
    first_w = (b.bbox[2] - b.bbox[0]) * len(words[0]) / max(1, len(bt))
    return a.bbox[2] + SPACE_EM * size + first_w < right - 1.0




# A justified paragraph's lines all reach both column edges except its last,
# so a short line between two full ones is a paragraph END even with no extra
# leading after it. Word sets Hebrew and Arabic at 1.5 lines with no space
# between paragraphs (y49, y50), and there that short line is the only
# boundary there is: y49 p2's five paragraphs read as one. A line is "full"
# within FULL_EDGE_PT of both edges; "short" when its end stops more than
# SHORT_END_EM of its own size from the end edge (y49's last lines stop 60-410pt
# short at 12pt; its justified lines within 0.4pt). Right-to-left groups only
# for now: their bogus list markers had been doing this job by accident (see
# dialect._labelled_line), and the Latin rule's effect on the gated corpus is
# unmeasured.
FULL_EDGE_PT = 3.0
SHORT_END_EM = 2.0


def _short_line_ends_para(prev: Line, ln: Line, nxt: Line,
                          col_l: float, col_r: float) -> bool:
    """`ln`, between a full line and a line starting at the start edge, ends
    its paragraph (right-to-left lines; see FULL_EDGE_PT)."""
    def full(x):
        return abs(x.bbox[0] - col_l) <= FULL_EDGE_PT and \
            abs(x.bbox[2] - col_r) <= FULL_EDGE_PT
    sz = _line_size(ln)
    return (full(prev) and abs(ln.bbox[2] - col_r) <= FULL_EDGE_PT
            and ln.bbox[0] - col_l > SHORT_END_EM * sz
            and abs(nxt.bbox[2] - col_r) <= FULL_EDGE_PT)


def _split_lines_to_paras(lines: List[Line],
                          list_starts: Optional[set] = None,
                          col_l: Optional[float] = None,
                          col_r: Optional[float] = None,
                          forced: Optional[float] = None) -> List[List[Line]]:
    """Group a flat list of lines into paragraphs on large baseline gaps,
    dominant-size jumps, letter-spacing changes, or list-marker starts.

    `list_starts` holds the `_line_key`s of lines that open a list item with a
    typed marker, decided over the whole flow by `_inline_list_starts`.
    With the column edges, a right-to-left group also ends at a short line
    between full ones (_short_line_ends_para). `forced`, when given, also
    splits where the source broke a line by hand short of that text edge
    (`_forced_break`)."""
    lines = _merge_row_lines(lines)
    list_starts = list_starts or set()
    if len(lines) <= 1:
        return [lines] if lines else []
    deltas = [b.bbox[1] - a.bbox[1] for a, b in zip(lines, lines[1:])]
    pos = [d for d in deltas if d > 0.5]
    lead = sorted(pos)[len(pos) // 2] if pos else 12.0
    # A median of ALL the gaps cannot bound a group whose every gap is
    # huge. Measured on lshort's index: its last three entries arrived
    # from three different columns, 352pt apart; the median went 352 with
    # them, the "1.55x the median" split could never fire, and the group
    # became one paragraph whose 352pt exact leading rendered ONE LINE PER
    # PAGE. A real line pitch never exceeds ~2.2x its font size (double
    # spacing is 2.0); cap the threshold's idea of a pitch there, and a
    # group whose every gap is enormous splits like any other.
    dom = max((s.size for ln in lines for s in ln.spans
               if s.text.strip()), default=10.0)
    lead = min(lead, 2.2 * dom)

    def dom_size(ln):
        best, n = 10.0, 0
        for s in ln.spans:
            if len(s.text) > n:
                best, n = s.size, len(s.text)
        return best

    right = max(l.bbox[2] for l in lines)
    # The block's tightest pitch: double-spaced text is double-spaced on
    # EVERY line (_author_break).
    pitch = min(pos) if pos else 0.0
    groups, cur = [], [lines[0]]
    for i, ln in enumerate(lines[1:]):
        sz_prev = dom_size(cur[-1])
        sz_new = dom_size(ln)
        size_jump = max(sz_prev, sz_new) > 1.3 * max(0.1, min(sz_prev, sz_new))
        # A section heading set in letter-spaced caps at the BODY'S OWN SIZE is
        # invisible to every test above it: measured on a resume whose headings
        # are Georgia-Bold 9.49pt over 9.49pt body, the size ratio is 1.000
        # against a 1.3 threshold, the baseline step is an ordinary leading, and
        # there is no marker -- so `SUMMARY` and `TECHNICAL SKILLS` were grouped
        # with the paragraphs beneath them and emitted as one run of text.
        #
        # The boundary is letter-spacing rather than bold or caps, and that is a
        # measured choice, not a preference. Censused over all 48 documents:
        # a bold delta would newly split 584 pairs on y11_nist_sp80053r5, 235 on
        # y06_irs_1040_instructions and 96 on y02, because bold labels, bold
        # table cells and bold run-in headings are everywhere in those; a caps
        # delta would newly split a citation inside 02_research_paper, which is
        # a GATED fixture. Tracking newly splits 2 pairs in 1 document of 48,
        # and both are the welded headings. See parse_pdfium._drop_tracking_spaces
        # for how the measurement is made and what it refuses to call tracking.
        track_prev, track_new = _line_tracked(cur[-1]), _line_tracked(ln)
        track_jump = (track_prev is not None and track_new is not None
                      and track_prev != track_new)
        short_end = (col_l is not None and len(cur) >= 2
                     and getattr(cur[-1], "rtl", False)
                     and getattr(ln, "rtl", False)
                     and _short_line_ends_para(cur[-2], cur[-1], ln,
                                               col_l, col_r))
        if deltas[i] > max(lead * 1.55, lead + 4.0) or size_jump or track_jump \
                or _line_starts_with_marker(ln) or _line_key(ln) in list_starts \
                or _opens_note(ln) or short_end or \
                (forced is not None and _forced_break(cur[-1], ln, forced)) or \
                _author_break(cur[-1], ln, right, pitch, len(lines)):
            groups.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    groups.append(cur)
    return groups


def para_from_lines(lines: List[Line], col_l: float, col_r: float,
                    list_start: bool = False) -> Para:
    """`list_start`: the first line opens a list item with a TYPED marker
    (see `_inline_list_starts`). The marker stays text, as the source typed
    it; what the item needs is its hanging indent, read off its own
    continuation lines."""
    lines = _merge_row_lines(lines)
    bbox = None
    for ln in lines:
        bbox = bbox_union(bbox, ln.bbox)
    # The paragraph reads right to left when most of its text does, or when
    # its FIRST line does -- the paragraph-level rule of UAX #9 (P2: the first
    # strong character), seen from the page. y47's notes open `١٦ انظر:` and
    # continue with two lines of English citation: by letters they are Latin,
    # by their first line (and by the page) they are Arabic, right-aligned,
    # mark on the right.
    first = next((ln for ln in lines if ln.text.strip()), None)
    rtl = _rtl_lines(lines) or bool(first is not None and getattr(first, "rtl", False))
    if any(getattr(ln, "rtl", False) != rtl for ln in lines):
        # A line read at the other direction than its paragraph renders in
        # is re-read at the paragraph's (parse_pdfium.relogical_spans): y50's
        # `.(Basiri, et al., 2014)` closing a Persian paragraph.
        from .parse_pdfium import relogical_spans
        lines = [ln if getattr(ln, "rtl", False) == rtl else
                 Line(spans=relogical_spans(ln.spans, getattr(ln, "rtl", False),
                                            rtl),
                      bbox=ln.bbox, dir=ln.dir, rtl=rtl)
                 for ln in lines]
    if rtl:
        # Measured in the mirror image from here on; see _rtl_lines. The
        # column is symmetric about its own axis, so col_l/col_r stand, and
        # every indent and alignment below comes out in start/end terms.
        lines = [_mirror_line(ln, col_l + col_r) for ln in lines]
    p = Para(bbox=bbox)
    p.rtl = rtl
    p._vis_lines = len(lines)
    p._list_item = bool(list_start)
    if list_start:
        m = _inline_marker(lines[0].text)
        p._list_style = m[0] if m else None
    p._tracked = all(_line_tracked(ln) is True for ln in lines)
    # The line's size, not a glued note number's (`_merge_list_markers`): a
    # 6pt number opening y50's 9pt notes made them 7.5pt-exact paragraphs.
    first_sz = next((s.size for s in lines[0].spans
                     if getattr(s, "_note_mark", None) is None),
                    lines[0].spans[0].size if lines[0].spans else 10.0)
    p._b1 = lines[0].baseline
    p._size1 = first_sz
    if len(lines) >= 2:
        base = [ln.baseline for ln in lines]
        diffs = [b2 - b1 for b1, b2 in zip(base, base[1:]) if b2 > b1]
        p.leading = round(sorted(diffs)[len(diffs) // 2], 2) if diffs else 0.0
    else:
        # exact single-line height: a hair above natural so nothing clips
        p.leading = round(max(first_sz * 1.16, 4.0), 2)
    xs0 = [ln.bbox[0] for ln in lines]
    xs1 = [ln.bbox[2] for ln in lines]
    # A typed-marker item hangs: "• Rebuilt…" starts at the marker and its
    # continuation lines start under the item text (x17: 44.5 then 56.0, a
    # CSS text-indent of -11.5pt). Measured as the continuation lines' common
    # x; the alignment tests below then judge the item by where its TEXT
    # lines start, so a justified item is still justified.
    hang_x = None
    if list_start and len(lines) >= 2:
        cont = min(xs0[1:])
        if 1.5 < cont - xs0[0] <= _INLINE_HANG_MAX and \
                all(abs(x - cont) < 1.5 for x in xs0[1:]):
            hang_x = cont
            xs0 = [cont] + xs0[1:]
    ccx = (col_l + col_r) / 2
    if len(lines) >= 2:
        left_flush = all(abs(x - xs0[0]) < 1.5 for x in xs0)
        # a paragraph may justify against an inset right edge (e.g. an
        # indented abstract); detect the consistent edge and pin it with a
        # right indent so the wrap width matches exactly
        edge = max(xs1[:-1]) if len(xs1) > 1 else xs1[0]
        right_flush = all(abs(x - edge) < 3.0 for x in xs1[:-1])
        centered = all(abs((a + b) / 2 - ccx) < 2.5 for a, b in zip(xs0, xs1))
        if centered and not (left_flush and abs(xs0[0] - col_l) < 2):
            p.align = "center"
        elif left_flush and right_flush and len(lines) >= 3:
            p.align = "justify"
            if col_r - edge > 4.0:
                p.right_indent = round(col_r - edge, 1)
        elif left_flush and right_flush and abs(edge - col_r) < 3.0:
            p.align = "justify"
        elif all(abs(x - col_r) < 2.5 for x in xs1) and xs0[0] - col_l > 6:
            p.align = "right"
        else:
            p.align = "left"
    else:
        x0, x1 = xs0[0], xs1[0]
        if abs((x0 + x1) / 2 - ccx) < 2.5 and x0 - col_l > 8 and col_r - x1 > 8:
            p.align = "center"
        elif col_r - x1 < 2.5 and x0 - col_l > 10 and \
                not getattr(lines[0], "_main_col", False):
            p.align = "right"
    minx = min(xs0)
    p.left_indent = max(0.0, round(minx - col_l, 1))
    if p.align in ("left", "justify"):
        fi = round(lines[0].bbox[0] - minx, 1)
        if abs(fi) > 1.0:
            p.first_indent = fi
    if p.align == "center":
        p.left_indent = 0.0
    if hang_x is not None and p.align != "center":
        p.left_indent = max(0.0, round(hang_x - col_l, 1))
        p.first_indent = round(lines[0].bbox[0] - hang_x, 1)
    p.runs = []
    p.src_lines = len(lines)
    p.src_widths = [round(ln.bbox[2] - ln.bbox[0], 1) for ln in lines]
    # A block whose every glyph is monospace is verbatim matter: code, ASCII
    # diagrams, fixed-pitch tables. Its line breaks are semantic, not wraps,
    # and re-flowing them as prose is wrong in every renderer. Defect
    # catalogue #2, live-verified in Google Docs: a multi-line code block
    # emitted as one run-per-line paragraph with space joiners collapsed
    # onto one wrapped line. Keep each source line, separated by breaks the
    # writer renders as w:br, exactly like the shaded code-cell path and the
    # ladder's line-locked encoding.
    mono_block = len(lines) >= 2 and all(
        s.mono for ln in lines for s in ln.spans if s.text.strip())
    if mono_block:
        p.line_breaks = True
        # Equal-length lines are routine in monospace -- two 22-character
        # lines end at the same x by construction -- and the justify test
        # above reads that as a right edge to pin. On the Bash manual (y26)
        # `if test-commands; then` / `  consequent-commands;` gave a 219.6pt
        # right indent that left the block exactly its widest line, and the
        # third line wrapped and spilled the page; FIPS 197's S-box rows, the
        # pandoc manual's templates and lshort's logs did the same. Lines
        # ended by w:br have no wrap to pin, and a justified line before a
        # break is stretched to the margin in Word.
        if p.align == "justify":
            p.align = "left"
        p.right_indent = 0.0
    for i, ln in enumerate(lines):
        row = runs_from_spans(ln.spans)
        if mono_block and i < len(lines) - 1 and row:
            row[-1].text += "\n"
        p.runs.extend(row)
        if not mono_block and i < len(lines) - 1:
            # Dehyphenate only where hyphenation happens: a justified
            # paragraph buying its last few points at the wrap edge. A
            # ragged-right line carries real text hyphens regardless of
            # how close to the edge it stops -- measured on a 32-page
            # ragged-right report where even the widest hyphen line ends
            # 3.75pt short of the column and every drawn hyphen is text.
            _soft_join(p.runs, lines[i + 1].text,
                       dehyphenate=(p.align == "justify"
                                    and ln.bbox[2]
                                    >= col_r - p.right_indent - 3.0))
    # ``right_flush`` deliberately ignores the final source line: that is how
    # a normal justified paragraph has a ragged last line.  A short metadata
    # block can look the same to that heuristic, except its final row is wider
    # than the inferred inset.  Serialising that as one justified paragraph
    # gives it an impossible wrap width (the memo's Date row then wraps in
    # Google Docs).  Record its source rows only when the geometry proves the
    # inset cannot contain the longest row.  Ordinary narrow justified prose
    # still has a longest source row that fits its inferred width and remains
    # reflowable.
    inferred_w = col_r - col_l - p.left_indent - p.right_indent
    if p.align == "justify" and p.right_indent > 0.05 and len(lines) >= 2 and \
            p.src_widths and max(p.src_widths) > inferred_w + 1.0:
        # This is deliberately not a global layout mutation: standard DOCX
        # preserves its long-standing flowing paragraph, while the Google Docs
        # writer consumes these rows as soft breaks at a usable width.
        p.gdocs_rows = [runs_from_spans(ln.spans) for ln in lines]
    # bullet / numbered list detection
    spans0 = lines[0].spans
    if len(spans0) >= 2:
        k = _marker_split_idx(spans0)
        if k is not None:
            text_x = spans0[k + 1].bbox[0]
            p.left_indent = max(0.0, round(text_x - col_l, 1))
            p.first_indent = round(spans0[0].bbox[0] - text_x, 1)
            p.tab_stops = [(p.left_indent, "left")]
            mruns = runs_from_spans(spans0[:k + 1])
            for mr in mruns:
                mr.text = mr.text.rstrip(" ")
            runs = [m for m in mruns if m.text]
            runs.append(Run(text="\t", font=spans0[0].font, size=spans0[0].size,
                            color=spans0[0].color, is_tab=True))
            runs += runs_from_spans(spans0[k + 1:])
            for j in range(1, len(lines)):
                _soft_join(runs, lines[j].text,
                           dehyphenate=(p.align == "justify"
                                        and lines[j - 1].bbox[2]
                                        >= col_r - p.right_indent - 3.0))
                runs.extend(runs_from_spans(lines[j].spans))
            p.runs = runs
            # its one tab is the marker's separator, not a tabbed row
            # (`_mergeable` lets the item's continuation join it)
            p._marker_tab = True
    if getattr(lines[0], "_gutter", None) is not None and p.align != "center":
        _gutter_para(p, lines, col_l)
    _keep_room(p, col_l, col_r)
    return p


# Which paragraphs the guard repairs. A SHORT one-line paragraph -- a label,
# a date, a page number, no wider than SHORT_LINE_FRAC of the column -- that
# overhangs by more than OVERHANG_TOL wraps where the source did not (RFC
# 9110's full-length `Page N`: 17pt of room for 27pt, on every page). Anything
# else is repaired only when STARVED -- left less than half its widest line,
# so it re-wraps into at least twice its lines (one character per line at the
# extreme). A few points of overhang on running text is something else: the
# inferred margin disagreeing with the text's edge, which moving the text does
# not settle -- pulling WDR's 87 column-2 paragraphs in by 5.7pt each (206pt of
# room for 212pt lines) cost that document 2 pages under the refine loop, and
# pulling four 330pt cross-column lines of the Federal Register's 3-column
# page in by 9pt cost it one.
OVERHANG_TOL = 3.0
STARVED_FRAC = 0.5
SHORT_LINE_FRAC = 1.0 / 3.0
# Room a short right-aligned line keeps beyond its own width, as a share of
# it: the substitute faces the font table maps run up to ~10% wider than the
# source's (Fontin's substitute on y44).
RIGHT_LINE_SLACK = 0.10
# A forced break leaves room for the next line's first word plus this much
# (in em of that line): a word space (SPACE_EM) and the same again for
# justification and the character-apportioned word width. The breaks it is
# for leave far more -- y58's panel headings leave 100pt for a 20pt word.
FORCED_BREAK_SPACE_EM = 1.0


def _keep_room(p: Para, col_l: float, col_r: float) -> None:
    """Never leave a paragraph less room than its own widest source line.

    The indent is the line's distance from the column's left edge, and the
    column's right edge is inferred from the BODY text. A line set further
    right than that -- a running footer's `Page 5` at x 512-539 on RFC 9110,
    whose body column ends at 506; EUR-Lex's masthead `L series` -- then has
    an indent wider than the column (446pt in a 440pt column): Word and
    LibreOffice wrap it one character per line, 30 times in 30 pages of the
    RFC. The paragraph's extent is known, so when it is starved (see
    STARVED_FRAC) the indent is pulled left until the widest line fits; it
    cannot go past the column's own left edge. A
    right-aligned line keeps its alignment, which is what places it; the
    indent only ever bounded its wrap.
    """
    if not p.bbox or p.align == "center":
        return
    width = p.bbox[2] - p.bbox[0]
    room = (col_r - col_l) - p.right_indent
    if width > room:
        return              # wider than the column: no indent makes it fit
    start = p.left_indent + min(0.0, p.first_indent)
    if p.align == "right" and (p.src_lines or 1) <= 1 and start > 0 and \
            width <= SHORT_LINE_FRAC * room and \
            p.bbox[2] <= col_r - p.right_indent + OVERHANG_TOL:
        # A SHORT line set flush against the right edge -- a date, a page
        # label -- is placed by its alignment; its indent only bounds the
        # wrap, so it can be given room for a substitute face a little wider
        # than the source's and nothing moves. y44's 'Last updated in Mar
        # 2026' fitted its indent exactly and wrapped in Fontin's substitute.
        # Short only: given to every flush-right line it moved y40's
        # misread right-aligned body lines and cost that paper 3 pages.
        fit = room - width * (1.0 + RIGHT_LINE_SLACK)
        if fit < start:
            p.left_indent = round(max(0.0, p.left_indent - (start - fit)), 1)
        return
    over = start + width - room
    if start <= 0 or over <= OVERHANG_TOL:
        return
    short = (p.src_lines or 1) <= 1 and width <= SHORT_LINE_FRAC * room
    if not short and room - start >= STARVED_FRAC * width:
        return
    p.left_indent = round(max(0.0, -p.first_indent, p.left_indent - over), 1)


def paras_from_line_list(lines: List[Line], col_l: float, col_r: float,
                         list_starts: Optional[set] = None,
                         forced: Optional[float] = None) -> List[Para]:
    out = []
    ccx = (col_l + col_r) / 2
    list_starts = list_starts or set()
    prev_last = None
    for grp in _split_lines_to_paras(lines, list_starts, col_l, col_r,
                                     forced=forced):
        if not grp:
            continue
        # centered short lines with strongly varying widths are separate
        # paragraphs (title/author blocks), not one wrapped paragraph
        if len(grp) >= 2:
            centered = all(abs((l.bbox[0] + l.bbox[2]) / 2 - ccx) < 3.5 and
                           l.bbox[0] - col_l > 8 for l in grp)
            if centered:
                ws = [l.bbox[2] - l.bbox[0] for l in grp[:-1]]
                if ws and (max(ws) - min(ws)) > 0.3 * max(ws):
                    for l in grp:
                        out.append(para_from_lines(
                            [l], col_l, col_r, list_start=_line_key(l) in list_starts))
                    prev_last = grp[-1]
                    continue
        p = para_from_lines(grp, col_l, col_r,
                            list_start=_line_key(grp[0]) in list_starts)
        p._note = _opens_note(grp[0])
        # a paragraph the source opened by hand stays one: the flow merge
        # (_merge_flow_paras) must not weld it back to the one before it
        p._forced = bool(forced is not None and prev_last is not None
                         and _forced_break(prev_last, grp[0], forced))
        prev_last = grp[-1]
        out.append(p)
    return out


# ------------------------------------------------------------------ HF detect
def _norm_text(t: str) -> str:
    return re.sub(r"\d+", "#", t.strip())


def _no_furniture() -> dict:
    """detect_hf's result for a document read as having no furniture."""
    return {
        "consumed_text": defaultdict(set), "consumed_draw": defaultdict(set),
        "band_first": None, "band_def": None, "rep_lines": defaultdict(list),
        "rep_draws": defaultdict(list), "line_roles": {},
        "page_numbers": {}, "num_sections": [], "parity": {},
        # varying furniture: consumed from the body, not part of the modal
        # signature; `infer` states it per running-head section
        "var_lines": defaultdict(list),
        # pleading paper's line-number gutter, per page (_line_number_gutters)
        "gutter": {},
    }


def _furniture_clearance(ir: DocIR, res: dict, qualified) -> dict:
    """id(line) -> the white between a running-furniture candidate and the
    body it frames, in points: for a head, from its bottom to the top of the
    first line below it; for a foot, from the bottom of the last line above it
    to its top. `qualified` is the geometry pass's [(sig, [(page, block index,
    line), ...])]; a page with nothing on the body side measures infinity.

    The candidates stack: a line on the body side that is itself a candidate
    (a running head's second row) is not the body, and the stack is measured
    from its innermost row. Lines the text-signature pass already consumed are
    furniture, not body, and are skipped the same way.

    Real varying running heads stand clear of the body below them, and a
    table's title does not -- the census behind GEO_CLEAR_LINES, which
    detect_hf applies to heads; feet are measured the same way and recorded
    there, not held to it."""
    cands = defaultdict(list)        # page -> [(zone, line)]
    for sig, occs in qualified:
        for pg, bi, ln in occs:
            cands[pg].append((sig[0], ln))
    out = {}
    for p in ir.pages:
        mine = cands.get(p.number)
        if not mine:
            continue
        ct = res["consumed_text"][p.number]
        ids = {id(ln) for _, ln in mine}
        body = [ln.bbox for bi, blk in enumerate(p.blocks) for ln in blk.lines
                if ln.text.strip() and id(ln) not in ids
                and (bi, id(ln)) not in ct]
        for zone in ("top", "bot"):
            # (near, far) extents measured from the zone's paper edge, so a
            # foot reads exactly as a head does
            def depth(bb, foot=(zone == "bot"), h=p.height):
                return (h - bb[3], h - bb[1]) if foot else (bb[1], bb[3])
            rows = [(depth(ln.bbox), ln) for z, ln in mine if z == zone]
            lines = [depth(bb) for bb in body]
            for (near, far), ln in rows:
                inward = [b for b in lines if (b[0] + b[1]) / 2 > far]
                if not inward:
                    out[id(ln)] = float("inf")
                    continue
                first = min(inward)
                mid = (first[0] + first[1]) / 2
                inner = max([far] + [r[1] for r, _ in rows
                                     if r[0] >= near and (r[0] + r[1]) / 2 < mid])
                out[id(ln)] = first[0] - inner
    return out


def detect_hf(ir: DocIR):
    n = len(ir.pages)
    H = ir.pages[0].height if ir.pages else 792
    W = ir.pages[0].width if ir.pages else 612
    res = _no_furniture()
    if n == 0:
        return res

    def top_bands(p: PageIR):
        cands = []
        for i, d in enumerate(p.drawings):
            x0, y0, x1, y1 = d.bbox
            if d.fill and (x1 - x0) >= 0.95 * p.width and (y1 - y0) >= 2.5 and y0 <= 220:
                cands.append((i, d))
        cands.sort(key=lambda t: t[1].bbox[1])
        grp, last_y1 = [], None
        for i, d in cands:
            if last_y1 is None:
                if d.bbox[1] <= COVER_BAND_SEED_PT:
                    grp.append((i, d))
                    last_y1 = d.bbox[3]
            elif d.bbox[1] - last_y1 <= 3.0:
                grp.append((i, d))
                last_y1 = max(last_y1, d.bbox[3])
        return grp

    b1 = top_bands(ir.pages[0])
    b1_h = max((d.bbox[3] for _, d in b1), default=0)
    later = [top_bands(p) for p in ir.pages[1:]]
    later_h = [max((d.bbox[3] for _, d in g), default=0) for g in later]
    strip_h = _mode([h for h in later_h if h > 0]) if any(later_h) else 0
    have_strip = n >= 2 and sum(
        1 for h in later_h if h > 0 and abs(h - strip_h) < 3) >= max(1, int(0.6 * (n - 1)))

    if b1 and b1_h > 45:
        res["band_first"] = b1
        for i, _ in b1:
            res["consumed_draw"][1].add(i)
    elif b1 and have_strip and abs(b1_h - strip_h) < 3:
        res["band_def"] = b1  # same strip everywhere
    if have_strip:
        if res["band_def"] is None:
            res["band_def"] = later[0] or None
        for pi, g in enumerate(later, start=2):
            for i, _ in g:
                res["consumed_draw"][pi].add(i)
        if b1 and b1_h <= 45 and abs(b1_h - strip_h) < 3:
            for i, _ in b1:
                res["consumed_draw"][1].add(i)

    band1_bb = None
    if res["band_first"]:
        for _, d in res["band_first"]:
            band1_bb = bbox_union(band1_bb, d.bbox)

    # -- candidates. The legacy bands (TOPZ/BOTZ) qualify on repetition alone,
    # exactly as before. The extended band (FURN_EXT_FRAC of the page) is
    # searched only on documents of 3+ pages, and what is found there must
    # earn it: see the extended pass below.
    cands = []          # (page, block index, line, side, in_legacy_band)
    for p in ir.pages:
        band_h = b1_h if (p.number == 1 and res["band_first"]) else \
            (strip_h if have_strip else 0)
        ext = FURN_EXT_FRAC * p.height
        for bi, blk in enumerate(p.blocks):
            for ln in blk.lines:
                y0, y1 = ln.bbox[1], ln.bbox[3]
                zone, legacy = None, True
                if y1 <= max(TOPZ, band_h + 2) and p.number != 1:
                    zone = "top"
                elif p.number == 1 and y1 <= TOPZ and not res["band_first"]:
                    zone = "top"
                elif y0 >= p.height - BOTZ:
                    zone = "bot"
                elif n >= 3 and y1 <= ext and not (
                        p.number == 1 and res["band_first"]):
                    zone, legacy = "top", False
                elif n >= 3 and y0 >= p.height - ext:
                    zone, legacy = "bot", False
                if zone:
                    cands.append((p.number, bi, ln, zone, legacy))

    # -- printed page numbers, judged across pages before anything is consumed:
    # the roman-numeral half of the signature normalisation needs to know which
    # "vii" is a page number and which "I" is a pronoun.
    labels = (ir.meta or {}).get("page_labels") if hasattr(ir, "meta") else None
    pn0 = page_number_model(
        ((pg, fmt, v, legacy) for pg, bi, ln, zone, legacy in cands
         for _, _, fmt, v in num_tokens(ln.text)), labels)
    parity0 = printed_parity(pn0, n)

    # rows of candidate lines per (page, side), ordered from the paper edge in
    rows = {}
    by_side = defaultdict(list)
    for pg, bi, ln, zone, legacy in cands:
        by_side[(pg, zone)].append((bi, ln, legacy))
    for key, items in by_side.items():
        items.sort(key=lambda t: (t[1].bbox[1], t[1].bbox[0]))
        grp: List[list] = []
        for it in items:
            if grp and abs(it[1].bbox[1] - grp[-1][0][1].bbox[1]) < 3.5:
                grp[-1].append(it)
            else:
                grp.append([it])
        if key[1] == "bot":
            grp.reverse()
        rows[key] = grp

    def row_has_page_number(pg, zone, ln):
        for row in rows.get((pg, zone), ()):
            if any(x[1] is ln for x in row):
                return any(is_page_number(pn0, pg, fmt, v)
                           for x in row for _, _, fmt, v in num_tokens(x[1].text))
        return False

    sigs = defaultdict(list)
    for pg, bi, ln, zone, legacy in cands:
        sig = (zone, round(ln.bbox[1] / 3),
               furniture_text(ln.text, pn0, pg)[:40])
        sigs[sig].append((pg, bi, ln, legacy))
    need = max(2, int(round(0.6 * n)))
    later_pages = list(range(2, n + 1))
    sig_lines = []            # (sig, page, line) consumed by text signature
    ext_ok = {}               # (page, id(line)) -> sig: extended-band lines that qualify
    for sig, occ in sigs.items():
        pages = {o[0] for o in occ}
        strip_case = sig[0] == "top" and (res["band_first"] is not None or have_strip)
        need_here = max(2, int(round(0.6 * (n - 1)))) if strip_case else need
        ok_pages = pages if len(pages) >= need_here else None
        if ok_pages is None and n >= PARITY_MIN_PAGES:
            # verso/recto running heads: each text holds on its own parity
            # only, so neither reaches 60% of ALL pages (audit finding 3d).
            for par in (0, 1):
                cls = [pg for pg in later_pages if parity0[pg] == par]
                on = {pg for pg in pages if parity0[pg] == par}
                if len(on) >= max(3, int(round(0.6 * len(cls)))) and \
                        len(on) >= 0.9 * len(pages):
                    ok_pages = on
        if not ok_pages:
            continue
        ext_occ = [o for o in occ if not o[3] and o[0] in ok_pages]
        if ext_occ:
            # Beyond the legacy band repetition alone is not furniture -- a
            # table header repeated at the top of every page repeats too.
            # What body text does not do is carry the page's own number.
            with_pn = sum(1 for pg, bi, ln, _ in ext_occ
                          if row_has_page_number(pg, sig[0], ln))
            if with_pn >= max(2, 0.6 * len(ok_pages)):
                for pg, bi, ln, _ in ext_occ:
                    ext_ok[(pg, id(ln))] = sig
        for pg, bi, ln, legacy in occ:
            if legacy and pg in ok_pages:
                res["rep_lines"][pg].append((sig[0], bi, ln))
                res["consumed_text"][pg].add((bi, id(ln)))
                sig_lines.append((sig, pg, ln))

    # VARYING running furniture. The text-signature pass above consumes a
    # line only when its full signature -- position AND text -- repeats on
    # >= 60% of pages, so furniture whose text varies per chapter never
    # reaches the bar and lands in the body flow, one stray line per source
    # page. Measured: the pandoc manual's top line is the chapter name
    # ("Pandoc's Markdown" x25, "Options" x11, ...) and the bash manual's is
    # the page number, roman then arabic (212 of 214 pages). What holds for
    # both -- and cannot hold for real content, which starts below the
    # furniture zone -- is the GEOMETRY: exactly one line at the same
    # position and size on >= 60% of pages. Those lines are consumed
    # WITHOUT emission: the representative-page machinery above cannot
    # express varying text, so furniture that cannot be stated correctly is
    # dropped rather than stated wrongly. (Their folios still vote in the
    # page-number model at the end of this function.)
    if n >= 3:
        geo = defaultdict(list)
        for p in ir.pages:
            if p.number == 1:
                continue
            band_h = strip_h if have_strip else 0
            for bi, blk in enumerate(p.blocks):
                for ln in blk.lines:
                    y0, y1 = ln.bbox[1], ln.bbox[3]
                    if (bi, id(ln)) in res["consumed_text"][p.number]:
                        continue
                    if y1 <= max(TOPZ, band_h + 2):
                        zone = "top"
                    elif y0 >= p.height - BOTZ:
                        zone = "bot"
                    else:
                        continue
                    size = max((s.size for s in ln.spans
                                if s.text.strip()), default=0.0)
                    geo[(zone, round(ln.bbox[1] / 3), round(size))].append(
                        (p.number, bi, ln))
        geo_need = max(2, int(round(0.6 * (n - 1))))
        qualified = []
        for sig, occ in geo.items():
            per_page = defaultdict(list)
            for pg, bi, ln in occ:
                per_page[pg].append((bi, ln))
            single = [pg for pg, v in per_page.items() if len(v) == 1]
            if len(single) < geo_need:
                continue
            qualified.append((sig, [(pg,) + tuple(per_page[pg][0])
                                    for pg in single]))
        # ...and furniture stands clear of the body it frames. A table's
        # title set at one place and size on every table page holds the
        # geometry too: y64_bls_release_xpp's "HOUSEHOLD DATA" over
        # "Table A-n. ..." on 31 of its 38 later pages, 1.4pt above the
        # table, both consumed and neither written. So does the first line
        # of a page set on a fixed grid (an RFC's, y17: 0.2pt above the
        # next). See GEO_CLEAR_LINES for the census.
        clear = _furniture_clearance(ir, res, qualified)
        for sig, occs in qualified:
            if sig[0] == "top" and median(
                    clear[id(ln)] for _, _, ln in occs) < \
                    GEO_CLEAR_LINES * sig[2]:
                continue
            for pg, bi, ln in occs:
                res["consumed_text"][pg].add((bi, id(ln)))
                res["var_lines"][pg].append((sig[0], bi, ln))

    # EXTENDED-band furniture (audit B2). The fixed 62/64pt bands left the RFC
    # footer "Fielding, et al.  Standards Track  [Page 40]" -- 105pt above the
    # bottom of A4 -- in the body on all 194 pages of RFC 9110, as a tabbed
    # paragraph that wrapped to three lines, and the Supreme Court's running
    # head (114pt down) in the body of all 114 pages of the slip opinion. Their
    # zone is derived from the evidence instead: a row qualifies when its text
    # repeats like furniture AND the row carries the page's own number, and
    # only as part of an unbroken chain of furniture rows from the paper edge,
    # so the first row of body text below a header stops the walk. A row that
    # qualifies is consumed whole: the rest of it (a chapter title beside the
    # page number, as LaTeX books set it) is varying furniture, dropped for the
    # same reason the geometry pass above drops it.
    if ext_ok:
        for (pg, zone) in sorted(rows):
            ct = res["consumed_text"][pg]
            for row in rows[(pg, zone)]:
                if all(x[2] for x in row):
                    if all((x[0], id(x[1])) in ct for x in row):
                        continue        # a legacy furniture row: walk on
                    break
                hits = [x for x in row if (pg, id(x[1])) in ext_ok]
                if not hits:
                    break
                for bi, ln, _ in row:
                    if (bi, id(ln)) in ct:
                        continue
                    ct.add((bi, id(ln)))
                    sig = ext_ok.get((pg, id(ln)))
                    if sig is not None:
                        res["rep_lines"][pg].append((zone, bi, ln))
                        sig_lines.append((sig, pg, ln))
                    else:
                        res["var_lines"][pg].append((zone, bi, ln))

    if n >= 3:
        _varying_folio_lines(ir, res, cands, row_has_page_number, parity0)

    _furniture_leftovers(ir, res, TOPZ, BOTZ)
    _line_number_gutters(ir, res)
    # A thin rule running the page's whole height is page furniture: pleading
    # paper's margin rules (y63: x 64.8, 68.4 and 581.2, y 0 to 792 on every
    # page). Left in, each one met the body's own rules and closed a lattice:
    # the left rule, the caption's bracket and an underline 133pt lower made
    # a "grid table" of the text between them.
    for p in ir.pages:
        for di, d in enumerate(p.drawings):
            if d.shape in ("vline", "line") and \
                    (d.bbox[3] - d.bbox[1]) >= PAGE_RULE_FRAC * p.height and \
                    (d.bbox[2] - d.bbox[0]) <= 2.0:
                res["consumed_draw"][p.number].add(di)

    # page-1 band text
    if band1_bb is not None:
        for bi, blk in enumerate(ir.pages[0].blocks):
            for ln in blk.lines:
                if contains(band1_bb, ln.bbox, pad=3):
                    res["rep_lines"][1].append(("band1", bi, ln))
                    res["consumed_text"][1].add((bi, id(ln)))
    # strip band text on later pages (inside strip bbox)
    if have_strip:
        for pi, g in enumerate(later, start=2):
            bb = None
            for _, d in g:
                bb = bbox_union(bb, d.bbox)
            if bb is None:
                continue
            for bi, blk in enumerate(ir.pages[pi - 1].blocks):
                for ln in blk.lines:
                    if contains(bb, ln.bbox, pad=3) and \
                            (bi, id(ln)) not in res["consumed_text"][pi]:
                        res["rep_lines"][pi].append(("top", bi, ln))
                        res["consumed_text"][pi].add((bi, id(ln)))

    # repeating zone drawings
    dsigs = defaultdict(list)
    for p in ir.pages:
        runs = _rule_runs(p.drawings)
        for di, d in enumerate(p.drawings):
            if di in res["consumed_draw"][p.number]:
                continue
            y0, y1 = d.bbox[1], d.bbox[3]
            zone = "top" if y1 <= TOPZ else ("bot" if y0 >= p.height - BOTZ else None)
            if zone and d.shape in ("hline", "vline", "rect", "line"):
                # a rule drawn as abutting segments is signed as the whole rule
                x0 = runs[di][0] if di in runs else d.bbox[0]
                sig = (zone, round(y0 / 3), round(x0 / 5), d.shape, d.fill, d.stroke)
                dsigs[sig].append((p.number, di, d))
    for sig, occ in dsigs.items():
        if len({o[0] for o in occ}) >= need:
            for pg, di, d in occ:
                res["rep_draws"][pg].append((sig[0], di, d))
                res["consumed_draw"][pg].add(di)
    # NOTE: mirrored even/odd furniture RULES (the EU Official Journal's
    # header rule is split into parity-mirrored segments, x 42/298 vs
    # 84/412, so the exact signature above never reaches 60% per variant)
    # were consumed here by a geometry-keyed pass, twice, and both forms
    # measured WORSE on the AI Act: emitted into the header part the
    # header's measured height grew and 147 pages became 157; consumed
    # without emission the open-loop render went to 274 and the refinement
    # loop, which had been spending the rule paragraphs' seam spacing as
    # its correction currency, could no longer converge below 156. The
    # stray rule-paragraphs at each seam are also a faithful rendering of
    # the source's own per-page furniture rules. Measured a third time by
    # WP22 (2026-10-05), with the recitals fixed and WP19's Docs planner in:
    # the head rule (3.5pt past TOPZ) taken into the header took y18's raw
    # LibreOffice render 157 -> 153 pages (its 1pt seam carriers stopped
    # firing after full pages), but grew margin_t 62.8 -> 67.1 and took the
    # gdocs DOCX, rendered by LibreOffice, 144 -> 165. Left alone again. The
    # FOOT rule, which lies inside BOTZ, is a different case: its halves are
    # signed as one rule (`_rule_runs`) and go to the footer. Reverted; the +2% class
    # is bounded and recorded as such.

    # -- page numbers as the FURNITURE states them. Only tokens on lines that
    # were consumed as furniture vote here (including varying furniture that
    # is not emitted -- NIST SP 800-88 prints its roman folios 25pt higher than
    # its arabic ones), so a coincidence elsewhere in a candidate band can
    # neither open a numbering section nor become a field.
    pn = page_number_model(
        ((pg, fmt, v, legacy) for pg, bi, ln, zone, legacy in cands
         if (bi, id(ln)) in res["consumed_text"][pg]
         for _, _, fmt, v in num_tokens(ln.text)), labels)
    by_sig = defaultdict(list)
    for sig, pg, ln in sig_lines:
        by_sig[sig].append((pg, ln))
    for sig, occ in by_sig.items():
        per_page = {}
        for pg, ln in occ:
            per_page.setdefault(pg, num_tokens(ln.text))
        lens = {len(v) for v in per_page.values()}
        uniform = len(lens) == 1 and lens != {0}
        numpages = set()
        if uniform:
            for idx in range(next(iter(lens))):
                vals = {per_page[pg][idx][2:] for pg in per_page}
                if vals == {(DECIMAL, n)}:
                    numpages.add(idx)   # context-checked later
        for pg, ln in occ:
            roles = []
            for idx, (_, _, fmt, v) in enumerate(num_tokens(ln.text)):
                if uniform and idx in numpages:
                    roles.append("NUMPAGES?")
                elif is_page_number(pn, pg, fmt, v):
                    roles.append("PAGE")
                else:
                    roles.append("LIT")
            if uniform or "PAGE" in roles:
                res["line_roles"][id(ln)] = roles
    for pg, items in res["var_lines"].items():
        for _, _, ln in items:
            roles = ["PAGE" if is_page_number(pn, pg, fmt, v) else "LIT"
                     for _, _, fmt, v in num_tokens(ln.text)]
            if "PAGE" in roles:
                res["line_roles"][id(ln)] = roles
    res["page_numbers"] = pn
    res["num_sections"] = numbering_sections(pn, n)
    res["parity"] = printed_parity(pn, n)
    return res


def _varying_folio_lines(ir: DocIR, res: dict, cands, row_has_page_number,
                         parity) -> None:
    """VARYING running furniture outside the legacy zones: a line of the
    extended band that carries the page's own number, alone at one place and
    size on 60% of the pages -- or on 60% of one parity's pages, when the
    other parity's furniture there is already consumed.

    The geometry pass in `detect_hf` reads only TOPZ/BOTZ, and the extended
    pass only text that repeats. A recto foot that names the current section
    -- "Parts of the main Writer window | 5", "Creating a new document | 15"
    -- does neither: y36_lo_writer_guide (LibreOffice, A4) sets it at y 772,
    70pt above the paper's edge, beside versos whose "6 | Chapter 1
    Introducing Writer" the extended pass takes. Left in the body, the recto
    foot closed every odd page as a paragraph the page had no room for. Its
    folio is the evidence body text cannot give; the line is consumed as
    varying furniture, which `_running_head_sections` states per section.
    """
    n = len(ir.pages)
    ct = res["consumed_text"]
    geo = defaultdict(list)
    for pg, bi, ln, zone, legacy in cands:
        if legacy or pg == 1 or (bi, id(ln)) in ct[pg] or not ln.text.strip():
            continue
        if not row_has_page_number(pg, zone, ln):
            continue
        size = max((s.size for s in ln.spans if s.text.strip()), default=0.0)
        geo[(zone, round(ln.bbox[1] / 3), round(size))].append((pg, bi, ln))
    need = max(2, int(round(0.6 * (n - 1))))
    later = range(2, n + 1)
    for sig, occ in geo.items():
        per_page = defaultdict(list)
        for pg, bi, ln in occ:
            per_page[pg].append((bi, ln))
        single = [pg for pg, v in per_page.items() if len(v) == 1]
        ok = len(single) >= need
        if not ok and n >= PARITY_MIN_PAGES:
            for par in (0, 1):
                cls = [pg for pg in later if parity.get(pg, pg % 2) == par]
                on = [pg for pg in single if parity.get(pg, pg % 2) == par]
                if len(on) >= max(3, int(round(0.6 * len(cls)))) and \
                        len(on) >= 0.9 * len(single):
                    ok = True
        if not ok:
            continue
        for pg in single:
            bi, ln = per_page[pg][0]
            ct[pg].add((bi, id(ln)))
            res["var_lines"][pg].append((sig[0], bi, ln))


# Two hline segments are one rule when they share a y within RULE_RUN_Y_TOL and
# the next starts within RULE_RUN_GAP of where the last ended (pt). The EU
# Official Journal draws its foot rule as two abutting segments split under the
# folio, at x 98.5 on versos and 496.7 on rectos (y18: 41.8-98.5 + 98.5-553.4
# against 41.8-496.7 + 496.7-553.4, all at y 806.2).
RULE_RUN_Y_TOL = 0.6
RULE_RUN_GAP = 1.0


def _rule_runs(drawings) -> Dict[int, Tuple[float, float]]:
    """{drawing index: (x0, x1) of the whole rule} for hlines drawn as two or
    more abutting collinear segments of one colour.

    The zone-drawing signature keys a rule on where it starts; signed per
    segment, a parity-mirrored split gives the second segment a different
    start on versos and rectos, so neither variant repeats on 60% of pages and
    that half of the rule stayed in the body -- below the body box (the box
    ends at 804.6 on y18), so wherever the text filled its page that 2pt
    paragraph went over the foot and took a page of its own (y18: 60 of 226
    pages blank). Signed as the whole rule, both halves are the same furniture
    on every page."""
    hl = sorted(((i, d) for i, d in enumerate(drawings) if d.shape == "hline"),
                key=lambda t: (round(t[1].bbox[1], 1), t[1].bbox[0]))
    out = {}
    used = set()
    for k, (i, d) in enumerate(hl):
        if i in used:
            continue
        run, x1 = [i], d.bbox[2]
        for j, e in hl[k + 1:]:
            if j in used or abs(e.bbox[1] - d.bbox[1]) > RULE_RUN_Y_TOL or \
                    (e.fill, e.stroke) != (d.fill, d.stroke):
                continue
            if e.bbox[0] <= x1 + RULE_RUN_GAP and e.bbox[2] > x1:
                run.append(j)
                x1 = e.bbox[2]
        if len(run) > 1:
            used.update(run)
            for j in run:
                out[j] = (d.bbox[0], x1)
    return out


# The band, from either edge, in which `_furniture_leftovers` looks.
FURNITURE_BAND_PT = 100.0


def _furniture_leftovers(ir: DocIR, res: dict, topz: float, botz: float) -> None:
    """What the running-furniture passes above leave behind them: the rules
    their running lines are set against, and the front matter's folios.

    The rule: y36_lo_writer_guide (LibreOffice, A4) sets each running foot
    1.4pt under a column-wide hline, 70pt above the paper's edge and so
    outside BOTZ; the foot itself is furniture (the extended band, by parity),
    but its rule stayed in the flow and closed every page on a ruled line the
    body had no room for -- 25 pages rendered 38. A thin hline outside the
    legacy zones touching a running line consumed outside them goes with it,
    into the part when the part's page carries it (`build_hf_part` draws it as
    the paragraph's border). Inside the legacy zones nothing changes: the
    mirrored-rule NOTE at the end of `detect_hf` records why.
    """
    if len(ir.pages) < 3:
        return
    _front_matter_folios(ir, res)
    for p in ir.pages:
        ct = res["consumed_text"][p.number]
        running = []
        for bi, blk in enumerate(p.blocks):
            for ln in blk.lines:
                if (bi, id(ln)) not in ct:
                    continue
                if ln.bbox[3] > topz and ln.bbox[1] < p.height - botz:
                    running.append(ln)
        if not running:
            continue
        for di, d in enumerate(p.drawings):
            if d.shape != "hline" or di in res["consumed_draw"][p.number]:
                continue
            if d.bbox[3] <= topz or d.bbox[1] >= p.height - botz:
                continue
            for ln in running:
                if min(abs(d.bbox[1] - ln.bbox[3]), abs(ln.bbox[1] - d.bbox[3]))                         <= RUNNING_RULE_GAP_PT and d.bbox[0] < ln.bbox[2] and                         d.bbox[2] > ln.bbox[0]:
                    zone = "top" if ln.bbox[1] < p.height / 2 else "bot"
                    res["consumed_draw"][p.number].add(di)
                    res["rep_draws"][p.number].append((zone, di, d))
                    break
    _repeated_running_rules(ir, res, topz, botz)


def _repeated_running_rules(ir: DocIR, res: dict, topz: float,
                            botz: float) -> None:
    """A rule drawn at one place on most pages, with a running line beyond it
    and nothing of the body between them, is that line's rule -- however far
    from it the author set it.

    RUNNING_RULE_GAP_PT reads a single page, so it has to be tight. Repetition
    is the stronger evidence, and with it the gap can be whatever the part can
    still draw (HF_RULE_REACH_PT). Measured on y17_rfc9110 (A4): the foot rule
    at y 713.6-714.3, x 56.2-539.0, on all 194 pages, its foot 9.2pt below.
    Left in the body it was a 2pt paragraph behind a 66pt gap closing every
    page, and wherever Google Docs set a page a few points longer than the
    source (p18's last line at 646 against 634.7), that paragraph went over
    and took a page of its own: 272 pages for 194, 77 of them carrying nothing
    but the rule. Its head rule, 9.0pt under the head, was always the part's
    (it lies inside TOPZ); this states the foot the same way.

    Inside the legacy zones nothing changes (the mirrored-rule NOTE at the
    end of `detect_hf`).
    """
    n = len(ir.pages)
    need = max(3, int(round(0.6 * n)))
    sigs = defaultdict(list)
    for p in ir.pages:
        for di, d in enumerate(p.drawings):
            if d.shape != "hline" or di in res["consumed_draw"][p.number]:
                continue
            if d.bbox[3] <= topz or d.bbox[1] >= p.height - botz:
                continue
            # the same geometry: the y and both ends, 3pt / 5pt buckets as the
            # zone-drawing signature in `detect_hf` buckets them
            sig = (round(d.bbox[1] / 3), round(d.bbox[0] / 5),
                   round(d.bbox[2] / 5), d.fill, d.stroke)
            sigs[sig].append((p, di, d))
    for occ in sigs.values():
        if len({p.number for p, _, _ in occ}) < need:
            continue
        for p, di, d in occ:
            zone = _rule_beside_running_line(p, d, res["consumed_text"][p.number],
                                             topz, botz)
            if zone is not None:
                res["consumed_draw"][p.number].add(di)
                res["rep_draws"][p.number].append((zone, di, d))


def _rule_beside_running_line(p: PageIR, d: DrawCmd, ct, topz: float,
                              botz: float) -> Optional[str]:
    """"top"/"bot" when a running line consumed outside the legacy zones lies
    within HF_RULE_REACH_PT of the rule `d`, across its extent, with no body
    line between them; else None.

    Outside the legacy zones, as `_furniture_leftovers` reads them: a foot
    inside BOTZ is set close under its rule and close over the body, and
    there the rule is the body's room as much as the foot's. Measured on
    y28_doe_oig_word365 (Letter): the foot at 731.4, its rule at 727.4 and
    footnotes down to 720.1 on 16 pages; taken into the footer as a border,
    the part grew 4pt into the body and LibreOffice set 23 pages for 21
    (22 before). The EU Official Journal's head rule, 3.5pt under a head
    inside TOPZ, is the case the NOTE at the end of `detect_hf` records.
    """
    lines = [(bi, ln) for bi, blk in enumerate(p.blocks) for ln in blk.lines
             if ln.text.strip()]
    x0, y0, x1, y1 = d.bbox
    for bi, ln in lines:
        if (bi, id(ln)) not in ct or not (x0 < ln.bbox[2] and x1 > ln.bbox[0]):
            continue
        if ln.bbox[3] <= topz or ln.bbox[1] >= p.height - botz:
            continue
        if ln.bbox[1] >= y1:
            lo, hi = y1, ln.bbox[1]           # a foot below its rule
        elif ln.bbox[3] <= y0:
            lo, hi = ln.bbox[3], y0           # a head above its rule
        else:
            continue
        if hi - lo > HF_RULE_REACH_PT:
            continue
        if any((bj, id(m)) not in ct and m.bbox[1] < hi and m.bbox[3] > lo
               and m.bbox[0] < x1 and m.bbox[2] > x0 for bj, m in lines):
            continue
        return "top" if ln.bbox[1] < p.height / 2 else "bot"
    return None


_BARE_FOLIO = re.compile(r"^(\d{1,4}|[ivxlcdm]{1,7}|[IVXLCDM]{1,7})$")


def _front_matter_folios(ir: DocIR, res: dict) -> None:
    """The folios the other passes leave behind: a front matter's roman
    numbers, set where the body's arabic ones are.

    The body's folios are consumed by the passes above, and a front
    matter's few roman ones reach no bar of their own. Measured on
    y30_nz_guideline_word365: "ii", "iii" at y 805, where every arabic folio
    sits; left in the flow, the folio went over its page, made a page of its
    own, and every later page sat one place late (word recall 0.98 -> 0.38).
    A bare number (arabic or roman) at a place whose other occupants, one per
    page on most pages, are already furniture, is furniture too.
    """
    n = len(ir.pages)
    need = max(3, int(round(0.6 * n)))
    geo = defaultdict(list)
    for p in ir.pages:
        ct = res["consumed_text"][p.number]
        for bi, blk in enumerate(p.blocks):
            for ln in blk.lines:
                if not ln.text.strip():
                    continue
                y0, y1 = ln.bbox[1], ln.bbox[3]
                if y1 <= FURNITURE_BAND_PT:
                    zone = "top"
                elif y0 >= p.height - FURNITURE_BAND_PT:
                    zone = "bot"
                else:
                    continue
                size = max((s.size for s in ln.spans if s.text.strip()), default=0)
                geo[(zone, round(y0 / 3), round(size))].append(
                    (p.number, bi, ln, (bi, id(ln)) in ct))
    for occ in geo.values():
        per_page = Counter(o[0] for o in occ)
        single = [o for o in occ if per_page[o[0]] == 1]
        if len(single) < need or \
                sum(1 for o in single if o[3]) < 0.5 * len(single):
            continue
        for pg, bi, ln, done in single:
            if not done and _BARE_FOLIO.match(ln.text.strip()):
                res["consumed_text"][pg].add((bi, id(ln)))


# A rule within this distance of a running line belongs to it (y36: 1.4pt).
RUNNING_RULE_GAP_PT = 6.0
# How far from a furniture row `build_hf_part` still sets a rule as that row's
# border (w:pBdr/@w:space itself stops at 31pt). A furniture rule farther out
# than this would be consumed and never drawn, so no pass takes one.
HF_RULE_REACH_PT = 18.0


# A line-number gutter (pleading paper, bills; parse_pdfium splits each number
# off the line it numbers): bare integers sharing a right edge, counting up by
# one down the page. Measured on y63_court_pleading_word365: 1-28 at a 24.1pt
# pitch, right edge 57.8, on all five pages, left of a 72pt body margin. In the
# body flow they were 28 one-word paragraphs a page and the margin cluster's
# competition; they are page furniture, and the header carries them where the
# profile can position a frame (see build_gutter_part).
GUTTER_MIN_ROWS = 8          # parse_pdfium.LINE_NUMBER_MIN_ROWS
GUTTER_X_TOL = 1.0           # pt, shared right edge
GUTTER_RUN_SHARE = 0.8       # adjacent rows counting up by exactly one
GUTTER_CLEAR_PT = 3.0        # parse_pdfium.LINE_NUMBER_CLEAR_PT


def _page_number_gutter(p: PageIR):
    """[(block index, line, value)] of `p`'s line-number gutter, or []."""
    cands = []
    for bi, blk in enumerate(p.blocks):
        for ln in blk.lines:
            t = ln.text.strip()
            if 1 <= len(t) <= 3 and t.isdigit() and ln.horizontal:
                cands.append((bi, ln, int(t)))
    if len(cands) < GUTTER_MIN_ROWS:
        return []
    cands.sort(key=lambda c: c[1].bbox[2])
    best, cur = [], [cands[0]]
    for c in cands[1:]:
        if c[1].bbox[2] - cur[-1][1].bbox[2] <= GUTTER_X_TOL:
            cur.append(c)
        else:
            best = max(best, cur, key=len)
            cur = [c]
    best = max(best, cur, key=len)
    if len(best) < GUTTER_MIN_ROWS:
        return []
    best.sort(key=lambda c: c[1].baseline)
    seq = [v for _, _, v in best]
    if sum(1 for a, b in zip(seq, seq[1:]) if b == a + 1) < \
            GUTTER_RUN_SHARE * (len(seq) - 1):
        return []
    # A gutter numbers the page: it starts again at 1, and it stands in the
    # margin, clear of every other line on the page. A table's index column
    # counts up too -- but on from the page before (c3_tables: 1-9, 10-38,
    # 39-46) and beside the paragraphs above the table.
    if seq[0] != 1:
        return []
    x1 = max(c[1].bbox[2] for c in best)
    ids = {id(c[1]) for c in best}
    if any(ln.bbox[0] < x1 + GUTTER_CLEAR_PT
           for blk in p.blocks for ln in blk.lines if id(ln) not in ids):
        return []
    return best


# Two pages' gutters are the same gutter when every number sits within this
# of the other's (pt) -- pleading paper prints one, identical, on every page.
GUTTER_SAME_PT = 1.5


def _header_gutter(lay: DocLayout, gutter: dict, n_pages: int) -> None:
    """Put a page-locked line-number gutter back as header furniture.

    The gutter left the body (`_line_number_gutters`); where every page
    carries the same one -- pleading paper's 1-28, at the same places -- it is
    one framed paragraph in the header (w:framePr at its page position, one
    line per number at the gutter's own pitch), which is how a word processor's
    pleading template draws it: on every page, outside the text. Measured in
    LibreOffice 24 (probe frametest4): drawn on every page within 1.8pt of
    the source's numbers, the body unmoved. A gutter that differs between
    pages stays consumed and unprinted, as before.
    """
    if not gutter or len(gutter) < max(1, int(round(0.6 * n_pages))):
        return
    seqs = list(gutter.values())
    ref = seqs[0]
    for other in seqs[1:]:
        if len(other) != len(ref) or any(
                a[1] != b[1] or abs(a[0].baseline - b[0].baseline) > GUTTER_SAME_PT
                for a, b in zip(ref, other)):
            return
    lines = [ln for ln, _v in ref]
    bases = [ln.baseline for ln in lines]
    pitches = [b - a for a, b in zip(bases, bases[1:])]
    if not pitches:
        return
    pitch = round(median(pitches), 2)
    if max(abs(p - pitch) for p in pitches) > GUTTER_SAME_PT:
        return                  # numbers off the one grid: not drawable as lines
    first = lines[0].spans[0]
    size = first.size
    runs = []
    for i, ln in enumerate(lines):
        if i:
            runs.append(Run(text="\n", font=first.font, size=size,
                            color=first.color))
        runs.extend(runs_from_spans(ln.spans))
    x0 = min(ln.bbox[0] for ln in lines)
    x1 = max(ln.bbox[2] for ln in lines)
    para = Para(runs=runs, align="right", leading=pitch, line_breaks=True,
                src_lines=len(lines))
    para._vis_lines = len(lines)
    para._b1, para._size1 = bases[0], size
    top, _h = _para_box(para)
    # the frame's width is the numbers' own, plus a digit of slack on the left
    para.frame = (round(x0 - 0.6 * size, 1), round(top, 1),
                  round(x1 - x0 + 0.6 * size, 1))
    tail = Para(runs=[Run(text="", font=first.font, size=1.0,
                          color=first.color)], leading=1.0)

    def carry(part):
        if part is None:
            part = HFPart(elements=[], distance=min(36.0, round(top, 1)))
        # A frame is drawn on the page of the paragraph after it: the tail.
        part.elements.extend([copy.deepcopy(para), copy.deepcopy(tail)])
        return part

    # Every header a page can show carries it: the default, the verso's, the
    # first page's, and those of the running-head sections.
    lay.header_default = carry(lay.header_default)
    if lay.even_odd:
        lay.header_even = carry(lay.header_even)
    if lay.different_first:
        lay.header_first = carry(lay.header_first)
    for sec in lay.hf_sections or ():
        if sec.parts:
            for key in ("header", "header_even", "header_first"):
                if key in sec.parts:
                    sec.parts[key] = carry(sec.parts[key])


def _line_number_gutters(ir: DocIR, res: dict) -> None:
    """Consume every page's line-number gutter as furniture (res['gutter'])."""
    res["gutter"] = {}
    for p in ir.pages:
        g = _page_number_gutter(p)
        if not g:
            continue
        res["gutter"][p.number] = [(ln, v) for _, ln, v in g]
        for bi, ln, _ in g:
            res["consumed_text"][p.number].add((bi, id(ln)))


def _pagefields(runs: List[Run], roles_for_line: Optional[List[str]],
                context: List[str]) -> List[Run]:
    if not roles_for_line:
        return runs
    out = []
    ri = [0]

    def next_role():
        r = roles_for_line[ri[0]] if ri[0] < len(roles_for_line) else "LIT"
        ri[0] += 1
        return r

    for r in runs:
        if r.is_tab or r.field:
            out.append(r)
            context.append(r.text)
            continue
        # Split at exactly the tokens `detect_hf` assigned roles to -- digit
        # groups and roman-numeral words, in order -- so the role list stays
        # index-aligned. For purely arabic text this is the old \d+ split.
        parts, pos = [], 0
        for s, e, _, _ in num_tokens(r.text):
            parts += [(r.text[pos:s], False), (r.text[s:e], True)]
            pos = e
        parts.append((r.text[pos:], False))
        for part, is_num in parts:
            if part == "":
                continue
            # Every property survives the split (tracking included). This used
            # to rebuild the run from a hand-picked subset that left out
            # `serif`, so a split Century Schoolbook head lost its serif
            # mapping and came out in the sans fallback (the Supreme Court's
            # running head, y19).
            nr = replace(r, text=part)
            if is_num:
                role = next_role()
                if role == "PAGE":
                    nr.field, nr.text = "PAGE", ""
                elif role == "NUMPAGES?":
                    prev = "".join(context)[-8:].strip().lower()
                    if prev.endswith(("/", "of", "de", "von", "sur")):
                        nr.field, nr.text = "NUMPAGES", ""
            out.append(nr)
            context.append(part)
    return out


def _group_lines_by_row(lines: List[Line]) -> List[List[Line]]:
    rows = []
    for ln in sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])):
        if rows and abs(ln.bbox[1] - rows[-1][0].bbox[1]) < 3.5:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    for r in rows:
        r.sort(key=lambda l: l.bbox[0])
    return rows


# A furniture line joins a neighbouring row, rather than stacking as a row of
# its own, when it shares at least this fraction of the shorter line's height
# with that row and sits beside it rather than under it. Measured on the NZ
# medicinal-cannabis guideline (y30): its folio (805.0-816.0) is centred
# between two left-hand footer lines (801.3-809.4, 811.2-819.2), overlapping
# each by 54% and 60%; stacked as three paragraphs the footer was 31.5pt tall
# against the source's 18pt, and every page lost the 13pt difference.
HF_ROW_OVERLAP = 0.5


def _group_hf_rows(lines: List[Line]) -> List[List[Line]]:
    """`_group_lines_by_row`, plus: a line that sits BESIDE a row (sharing
    HF_ROW_OVERLAP of its height, and no x-range with the row's lines) is
    part of that row -- one paragraph with a tab, as the source sets it --
    not a paragraph stacked under it."""
    rows = _group_lines_by_row(lines)
    if len(rows) < 2:
        return rows

    def vov(a, b):
        ov = min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1])
        return ov / max(1e-6, min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1]))

    def beside(ln, row):
        return all(ln.bbox[2] <= o.bbox[0] or ln.bbox[0] >= o.bbox[2]
                   for o in row)

    out: List[List[Line]] = []
    for row in rows:
        if len(row) == 1 and out:
            ln = row[0]
            host = next((r for r in out if beside(ln, r) and
                         max(vov(ln, o) for o in r) >= HF_ROW_OVERLAP), None)
            if host is not None:
                host.append(ln)
                host.sort(key=lambda l: l.bbox[0])
                continue
        out.append(list(row))
    return out


def _hf_row_para(row: List[Line], margin_l: float, content_w: float,
                 line_roles: Dict[int, List[str]]) -> Para:
    p = Para()
    bbox = None
    for ln in row:
        bbox = bbox_union(bbox, ln.bbox)
    p.bbox = bbox
    p._vis_lines = 1
    if row and row[0].spans:
        p._b1 = row[0].baseline
        p._size1 = row[0].spans[0].size
        p.leading = round(max(p._size1 * 1.16, 4.0), 2)
    center_x = margin_l + content_w / 2
    right_edge = margin_l + content_w
    context: List[str] = []

    def seg_runs(ln):
        return _pagefields(runs_from_spans(ln.spans), line_roles.get(id(ln)), context)

    if len(row) == 1:
        bb, ln = row[0].bbox, row[0]
        cx = (bb[0] + bb[2]) / 2
        p.runs = seg_runs(ln)
        if abs(cx - center_x) < 8 and bb[0] - margin_l > 8:
            p.align = "center"
        elif right_edge - bb[2] < 6 and bb[0] - margin_l > 10:
            p.align = "right"
        else:
            p.left_indent = max(0.0, round(bb[0] - margin_l, 1))
        return p
    runs: List[Run] = []
    tabs = []
    for i, ln in enumerate(row):
        bb = ln.bbox
        rr = seg_runs(ln)
        cx = (bb[0] + bb[2]) / 2
        if i == 0:
            if bb[0] - margin_l >= 6:
                p.left_indent = round(bb[0] - margin_l, 1)
            runs += rr
            continue
        if abs(cx - center_x) < 8:
            tabs.append((content_w / 2, "center"))
        elif right_edge - bb[2] < 8:
            tabs.append((content_w, "right"))
        else:
            tabs.append((round(bb[0] - margin_l, 1), "left"))
        runs.append(Run(text="\t", font=rr[0].font if rr else "Helvetica",
                        size=rr[0].size if rr else 9, color=rr[0].color if rr else "#000000",
                        is_tab=True))
        runs += rr
    p.runs = runs
    p.tab_stops = tabs
    return p


def build_band_table(band, band_lines: List[Line], margin_l, content_w,
                     line_roles) -> TableEl:
    band_bb = None
    for _, d in band:
        band_bb = bbox_union(band_bb, d.bbox)
    main = max((d for _, d in band), key=lambda d: bbox_area(d.bbox))
    accents = [d for _, d in band if d is not main]
    cell = Cell(shading=main.fill, borders={})
    binner = sorted(band_lines, key=lambda l: l.bbox[1])
    pad_left = max(0.0, round(min((l.bbox[0] for l in binner), default=margin_l)
                              - margin_l, 1))
    for rowlines in _group_lines_by_row(binner):
        pp = _hf_row_para(rowlines, margin_l + pad_left, content_w - pad_left, line_roles)
        cell.paras.append(pp)
    if not cell.paras:
        cell.paras = [Para(runs=[Run(text="", font="Helvetica", size=2,
                                     color="#000000")], leading=2.0)]
    cursor = _space_paras(cell.paras, band_bb[1])
    pad_bot = max(0.0, round(band_bb[3] - cursor, 1))
    cell.pad = (0.0, pad_left, pad_bot, 0.0)
    main_h = max(1e-6, main.bbox[3] - main.bbox[1])
    for a in accents:
        ah = a.bbox[3] - a.bbox[1]
        if ah > ACCENT_MAX_PT or ah > ACCENT_MAX_FRAC * main_h:
            continue          # a second substantial fill is a band, not a stripe
        if a.bbox[1] >= main.bbox[3] - 1:
            cell.borders["bottom"] = (max(1.0, ah), a.fill or "#000000")
        elif a.bbox[3] <= main.bbox[1] + 1:
            cell.borders["top"] = (max(1.0, ah), a.fill or "#000000")
    return TableEl(rows=[[cell]], col_widths=[content_w],
                   row_heights=[band_bb[3] - band_bb[1]], role="band", bbox=band_bb)


def _role_text(ln: Line, roles: Optional[List[str]]) -> str:
    """A furniture line's text as its part will state it: a page-number field
    is '{P}', any other digit group '#', every other word literal."""
    out, pos = [], 0
    text = ln.text.strip()
    for i, (s, e, fmt, _) in enumerate(num_tokens(text)):
        role = roles[i] if roles and i < len(roles) else "LIT"
        if role == "PAGE":
            rep = "{P}"
        elif fmt == DECIMAL:
            rep = "#"
        else:
            continue
        out += [text[pos:s], rep]
        pos = e
    out.append(text[pos:])
    return "".join(out)


def _hf_anchor(bb: BBox, page_w: float) -> str:
    """Where a furniture line hangs: left, centre, right, or full width. Part of
    the part signature because verso/recto heads often differ ONLY in which side
    the folio sits on."""
    cx = (bb[0] + bb[2]) / 2
    if bb[2] - bb[0] > 0.6 * page_w:
        return "W"
    if abs(cx - page_w / 2) < 15:
        return "C"
    return "L" if cx < page_w / 2 else "R"


def _part_has_page_field(part: Optional[HFPart]) -> bool:
    if part is None:
        return False
    paras = []
    for el in part.elements:
        if isinstance(el, Para):
            paras.append(el)
        elif isinstance(el, TableEl):
            paras += [p for row in el.rows for c in row if c for p in c.paras]
    return any(r.field == "PAGE" for p in paras for r in p.runs)


def _hf_extent(part: Optional[HFPart]) -> float:
    """How far a header or footer part reaches from its anchor, in points."""
    if part is None:
        return 0.0
    h = 0.0
    for el in part.elements:
        if getattr(el, "frame", None) is not None:
            continue            # page-locked (a pleading gutter): no extent
        if isinstance(el, Para):
            lead = el.leading if (el.leading and el.leading > 1) else \
                max((r.size for r in el.runs if r.text), default=10.0) * 1.15
            h += (el.space_before or 0.0) + max(1, el.src_lines or 1) * lead \
                + (el.space_after or 0.0)
            for b in (getattr(el, "border_top", None),
                      getattr(el, "border_bottom", None)):
                if b:
                    h += b[0] + b[2]
            continue
        bb = getattr(el, "bbox", None) or getattr(el, "_bbox", None)
        if bb:
            h += (bb[3] - bb[1]) + (getattr(el, "space_before", 0.0) or 0.0)
    return h


# The lowest a footer is placed: a quarter inch, the common minimum printable
# margin (also the refine loop's floor, refine.FOOTER_FLOOR_PT).
FOOTER_FLOOR_PT = 18.0
# A footer is moved only when that frees at least a line of body: 12pt, the
# common body leading of the documents measured. A smaller move buys nothing
# and only perturbs the page (EUR-Lex: 1.2pt cost the refine loop its 144/144).
FOOTER_MIN_GAIN_PT = 12.0
# The reserve below the lowest body line that `_measure_margins` keeps.
BODY_FOOT_RESERVE_PT = 16.0


def _fit_footers_below_body(ir: DocIR, hf, lay: DocLayout, rh) -> None:
    """Keep the footers, but never let one shrink the body box below what the
    source body uses.

    A DOCX section has ONE body box for all its pages, and a footer bounds it
    from below. The margin model already measures that box from the lowest
    body line on any page (`_measure_margins`); a footer placed at its source
    distance can sit higher than that, and then every page loses the
    difference. Before running footers were written the body had that room,
    and the documents whose re-wrapped text needs it -- the Word-export class
    -- spilled once the footer took it: on the merged tree y01 89 -> 96 pages,
    y03 63 -> 71, y08 67 -> 72, y36 42 -> 47. Measured with each footer moved
    down just far enough to sit below the box (never under FOOTER_FLOOR_PT,
    never by less than FOOTER_MIN_GAIN_PT), over 19 documents: 1528 -> 1493
    pages and word recall 0.3025 -> 0.3221 -- y01 92, y03 66 (recall 0.262 ->
    0.404), y08 68, y36 42, y28 33 -> 28 -- and no document worse. A footer
    whose source position already clears the box (every gated document, the
    RFCs at 105pt) is not touched.
    """
    feet = [lay.footer_default, lay.footer_even]
    for _, parts, _ in rh:
        feet += [parts.get("footer"), parts.get("footer_even")]
    feet = list({id(p): p for p in feet if p is not None}.values())
    if not feet:
        return
    room = None
    for p in ir.pages:
        ct = hf["consumed_text"][p.number]
        bots = [l.bbox[3] for bi, b in enumerate(p.blocks) for l in b.lines
                if (bi, id(l)) not in ct]
        if bots:
            r = p.height - max(bots) - BODY_FOOT_RESERVE_PT
            room = r if room is None else min(room, r)
    if room is None:
        return
    for part in feet:
        target = room - _hf_extent(part)
        if part.distance - target >= FOOTER_MIN_GAIN_PT:
            part.distance = max(FOOTER_FLOOR_PT, round(target, 1))


def _running_head_sections(ir: DocIR, hf, lay: DocLayout, zs, roles):
    """[(start_page, parts, title_pg)] -- one entry per change of running head.

    Varying furniture (a chapter title in the head, a section title in the
    recto head) is consumed from the body by `detect_hf` because no single
    header part can state it: the bash manual's "Chapter 3: Basic Shell
    Features" vanished from 212 pages, the pandoc manual's chapter names from
    138. A Word author states such heads the only way DOCX can -- a section
    per chapter, each with its own header -- and that is what this plans: the
    pages are walked in order, and wherever the varying text on a side (per
    parity, under evenAndOddHeaders) changes, a section starts. It starts on
    the first page after the last one that carried varying furniture, so a
    chapter opener that prints no running head belongs to its own chapter and
    gets a first-page part of its own (w:titlePg).

    Each section's parts are built from its own representative pages, fixed
    and varying furniture together. Returns [] when there is nothing to vary,
    or when the "head" changes so often (more than one section per two pages)
    that it is not a running head at all.
    """
    vl = hf.get("var_lines") or {}
    n = len(ir.pages)
    if not any(vl.get(pg) for pg in range(2, n + 1)):
        return []
    parity = hf.get("parity") or {}
    zones = ("top", "bot")

    def cls_of(pg):
        return parity.get(pg, pg % 2) if lay.even_odd else 1

    def var_sig(pg, zone):
        items = sorted((l for z, _, l in vl.get(pg, ()) if z == zone),
                       key=lambda l: (round(l.bbox[1] / 3), l.bbox[0]))
        return tuple((_role_text(l, roles.get(id(l))),
                      _hf_anchor(l.bbox, lay.page_w)) for l in items)

    def says_something(sig):
        # a varying line that is only a folio (a chapter opener printing its
        # number where the head would be) states no running head: it opens
        # the chapter rather than starting a section of its own
        return any(re.sub(r"\{P\}|#", "", t).strip() for t, _ in sig)

    sigs = {pg: {z: (s if says_something(s) else ())
                 for z in zones for s in (var_sig(pg, z),)}
            for pg in range(2, n + 1)}
    # Boundaries: a page whose varying text differs from the running state,
    # and the first page that states a running head at all when pages before
    # it print none (front matter ahead of chapter 1). A section begins on the
    # first silent page after the last page that stated a head -- the chapter
    # opener -- but never before the numbering section the head belongs to:
    # the bash manual's chapter 1 opens on the page its arabic count starts.
    num_starts = [s for s, _, _ in hf.get("num_sections") or []]
    state, bounds, prev_furn, seen = {}, [], 1, False
    for pg in range(2, n + 1):
        changed = False
        for z in zones:
            s = sigs[pg][z]
            if not s:
                continue
            key = (z, cls_of(pg))
            if state.get(key) is not None and state[key] != s:
                changed = True
            state[key] = s
        stated = any(sigs[pg].values())
        first = stated and not seen and pg > 2
        if changed or first:
            floor = max([s for s in num_starts if s <= pg], default=1) \
                if first else 0
            start = max(prev_furn + 1, floor,
                        (bounds[-1] + 1) if bounds else 2)
            if 2 < start <= pg:     # page 2 belongs to section 1 anyway
                bounds.append(start)
        if stated:
            prev_furn, seen = pg, True
    if not bounds or len(bounds) + 1 > max(2, n // 2):
        return []

    def full_part(pg, zone):
        a, b = zs(pg, zone)
        a = a + [(z, bi, l) for (z, bi, l) in vl.get(pg, ()) if z == zone]
        return build_hf_part(a, b, ir.pages[pg - 1], lay.margin_l, lay.margin_r,
                             roles, band=hf["band_def"] if zone == "top" else None)

    defaults = {("top", 1): lay.header_default, ("bot", 1): lay.footer_default,
                ("top", 0): lay.header_even or lay.header_default,
                ("bot", 0): lay.footer_even or lay.footer_default}
    out, rep = [], {}
    edges = [2] + bounds + [n + 1]
    for i in range(len(edges) - 1):
        s, e = edges[i], edges[i + 1]
        for pg in range(s, e):
            for z in zones:
                if sigs[pg][z]:
                    rep.setdefault((z, cls_of(pg), i), pg)
        parts = {}
        for z, name in (("top", "header"), ("bot", "footer")):
            for c, suffix in ((1, ""), (0, "_even")):
                if suffix and not lay.even_odd:
                    continue
                # this section's own page, else the last one before it
                pg = rep.get((z, c, i))
                if pg is None:
                    pg = next((rep[(z, c, j)] for j in range(i - 1, -1, -1)
                               if (z, c, j) in rep), None)
                part = full_part(pg, z) if pg is not None else defaults[(z, c)]
                parts[name + suffix] = part
        first_furn = next((pg for pg in range(s, e) if any(sigs[pg].values())), s)
        title_pg = i > 0 and first_furn > s
        if title_pg:
            parts["header_first"] = full_part(s, "top")
            parts["footer_first"] = full_part(s, "bot")
        out.append((1 if i == 0 else s, parts, title_pg))
    return out


def build_hf_part(zone_items, zone_draws, page: PageIR, margin_l, margin_r,
                  line_roles, band=None) -> Optional[HFPart]:
    if not zone_items and not zone_draws and not band:
        return None
    W = page.width
    content_w = W - margin_l - margin_r
    part = HFPart(elements=[])

    band_bb = None
    if band:
        for _, d in band:
            band_bb = bbox_union(band_bb, d.bbox)

    if band_bb is not None:
        blines = [ln for (_, _, ln) in zone_items if ln.bbox[3] <= band_bb[3] + 2]
        part.elements.append(build_band_table(band, blines, margin_l, content_w,
                                              line_roles))
        part.distance = 0.0
        rest = [(z, b, l) for (z, b, l) in zone_items if l.bbox[3] > band_bb[3] + 2]
    else:
        rest = list(zone_items)

    rules = [d for (_, _, d) in zone_draws if d.shape in ("hline", "line")]
    text_paras = []
    for rowlines in _group_hf_rows([ln for (_, _, ln) in rest]):
        pp = _hf_row_para(rowlines, margin_l, content_w, line_roles)
        y0 = min(l.bbox[1] for l in rowlines)
        y1 = max(l.bbox[3] for l in rowlines)
        for rl in rules:
            ry = (rl.bbox[1] + rl.bbox[3]) / 2
            th = max(0.5, rl.width or (rl.bbox[3] - rl.bbox[1]))
            colr = rl.stroke or rl.fill or "#000000"
            if 0 < y0 - ry < HF_RULE_REACH_PT:
                pp.border_top = (th, colr, round(y0 - ry, 1))
            elif 0 < ry - y1 < HF_RULE_REACH_PT:
                pp.border_bottom = (th, colr, round(ry - y1, 1))
        text_paras.append((y0, y1, pp))
    text_paras.sort(key=lambda t: t[0])
    cursor = None
    for y0, y1, pp in text_paras:
        if cursor is not None:
            pp.space_before = max(0.0, round(y0 - cursor, 1))
        cursor = y1
        part.elements.append(pp)

    if not part.elements:
        return None
    if band_bb is None:
        ys0 = [t[0] for t in text_paras]
        ys1 = [t[1] for t in text_paras]
        if ys0:
            if min(ys0) < page.height / 2:
                part.distance = round(min(ys0), 1)
            else:
                part.distance = round(page.height - max(ys1), 1)
    return part


# ------------------------------------------------------------------ clustering
class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _expand(b: BBox, d: float) -> BBox:
    return (b[0] - d, b[1] - d, b[2] + d, b[3] + d)


def _touches(a: BBox, b: BBox, d: float = 6.0) -> bool:
    ea = _expand(a, d)
    return not (ea[2] < b[0] or b[2] < ea[0] or ea[3] < b[1] or b[3] < ea[1])


# Past this many drawings a page's clusters are found by a sweep over the
# boxes sorted by left edge instead of testing every pair (a page of y06's
# ruled tables holds ~400: 76,000 pairs).
_CLUSTER_SWEEP_MIN = 48


def _clusters(draws):
    n = len(draws)
    uf = _UF(n)
    boxes = [d[1].bbox for d in draws]
    if n >= _CLUSTER_SWEEP_MIN and all(
            math.isfinite(v) and abs(v) < 1e9 for b in boxes for v in b):
        # The same pairs are united: every pair the sweep skips has its left
        # box end more than 7pt (6pt reach + 1pt of slack against rounding)
        # before the right one starts, which _touches answers False for either
        # way round; every pair it tests is tested by _touches itself, lower
        # index first, as the double loop does. Components, and so the groups
        # below and their order, are those of the double loop.
        order = sorted(range(n), key=lambda k: boxes[k][0])
        for a, i in enumerate(order):
            reach = boxes[i][2] + 7.0
            for b in range(a + 1, n):
                j = order[b]
                if boxes[j][0] > reach:
                    break
                lo, hi = (i, j) if i < j else (j, i)
                if _touches(boxes[lo], boxes[hi]):
                    uf.union(lo, hi)
    else:
        for i in range(n):
            for j in range(i + 1, n):
                if _touches(boxes[i], boxes[j]):
                    uf.union(i, j)
    groups = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(draws[i])
    return list(groups.values())


def _edges_of(d: DrawCmd):
    x0, y0, x1, y1 = d.bbox
    hs, vs = [], []
    if d.shape == "hline":
        hs.append(((y0 + y1) / 2, x0, x1, d))
    elif d.shape == "vline":
        vs.append((((x0 + x1) / 2), y0, y1, d))
    elif d.shape == "rect" and d.kind in ("stroke", "fillstroke"):
        hs += [(y0, x0, x1, d), (y1, x0, x1, d)]
        vs += [(x0, y0, y1, d), (x1, y0, y1, d)]
    return hs, vs


def _is_glyphlike(d: DrawCmd) -> bool:
    """Tiny solid shape: a drawn bullet, tick or dingbat, not artwork.

    dialect.normalize() converts the ones that label a text line into real
    markers; the survivors are ornaments and must not be able to promote a
    whole cluster to 'figure'."""
    x0, y0, x1, y1 = d.bbox
    return (x1 - x0) <= GLYPH_MAX and (y1 - y0) <= GLYPH_MAX


def in_side_margin(bb: BBox, margin_l: float, margin_r: float,
                   page_w: float) -> bool:
    """Does this geometry lie wholly in a left/right margin band?

    DOCX body flow is a single vertical stream: every block element in it
    consumes its own height from the content area. A PDF has no such
    constraint, and producers use the side margins for furniture -- rotated
    citation strips, change bars, tabs, marginal icons -- which occupy zero
    body height because they are not in the body column at all.

    Emitting such a shape as a flow element therefore invents height the source
    never spent. It is not a small error: a 432pt sidebar strip repeated on
    every page of an 80-page NIST publication injected ~45 pages of height and
    pushed each source page onto two output pages, which is why word_recall
    collapsed to 0.13 while nearly every word was still present somewhere.

    Only the horizontal bands are treated this way. The top and bottom bands
    are running headers and footers, which `detect_hf` already recognises with
    a repetition test, and the vertical extent of an inferred body area is much
    less reliable than its column edges.
    """
    return (bb[2] <= margin_l - MARGIN_BAND_CLEARANCE or
            bb[0] >= page_w - margin_r + MARGIN_BAND_CLEARANCE)


def _frame_edge(bar: BBox, drawings, reach_x: float, tol: float = 1.0) -> bool:
    """Do horizontal rules leave BOTH ends of this vertical bar toward the text?

    That is the left side of a drawn frame, not a quote bar: Word exports draw
    a bordered box as four separate segments, and the NIST covers' title frame
    (y01/y02/y08: x=65, 42.8pt tall) has hlines starting flush at the bar's
    top and bottom ends and running across the title -- it was promoted to a
    quote table holding the title.
    """
    x1 = bar[2]

    def meets(y):
        for e in drawings:
            if e.shape != "hline":
                continue
            ex0, ey0, ex1, ey1 = e.bbox
            if ey0 - tol <= y <= ey1 + tol and ex0 <= x1 + tol and ex1 >= reach_x:
                return True
        return False

    return meets(bar[1]) and meets(bar[3])


def _is_quote_bar(bar: BBox, lines: List[Line], drawings) -> bool:
    """Is this tall vertical rule the bar of the quote formed by `lines`?

    The caller has already found text to the bar's right inside the bar's own
    vertical span. A quote bar also has to sit close to that text, must not run
    far above or below it, and must not be one side of a frame. See
    QUOTE_MAX_GAP_EM for the measurements.
    """
    sizes = sorted(max((s.size for s in l.spans if s.text.strip()), default=0.0)
                   for l in lines)
    sizes = [s for s in sizes if s > 0]
    if not sizes:
        return False
    em = sizes[len(sizes) // 2]
    minx = min(l.bbox[0] for l in lines)
    if minx - bar[2] > QUOTE_MAX_GAP_EM * em:
        return False
    top = min(l.bbox[1] for l in lines)
    bot = max(l.bbox[3] for l in lines)
    slack = QUOTE_MAX_OVERHANG_EM * em
    if bar[1] < top - slack or bar[3] > bot + slack:
        return False
    return not _frame_edge(bar, drawings, minx)


def _has_bars(fills) -> bool:
    """Three or more filled rectangles on one baseline at differing heights:
    the shape test `_classify_cluster` uses for a bar chart."""
    bars = [f for f in fills if not _is_glyphlike(f)]
    if len(bars) < 3:
        return False
    for b in _cluster([f.bbox[3] for f in bars], 2.5):
        grp = [f for f in bars if abs(f.bbox[3] - b) <= 2.5]
        if len(grp) >= 3:
            hts = [f.bbox[3] - f.bbox[1] for f in grp]
            if max(hts) > 1.3 * max(1e-6, min(hts)):
                return True
    return False


def _blank_picture_frame(d: DrawCmd, images) -> bool:
    """A white, unstroked rectangle behind a picture: a word processor's
    picture frame, which draws nothing on a white page. As a one-cell box it
    held the caption and the picture went after it, so the frame's height was
    paid twice: y36 p11, Figure 6 inside a 282pt white frame -- the box, then
    the 269pt picture below it. Left alone, picture and caption flow as the
    page shows them."""
    if d.stroke or (d.fill or "").lower() != "#ffffff":
        return False
    return any(bbox_overlap(im.bbox, d.bbox) >= 0.9 * max(1e-6, bbox_area(im.bbox))
               for im in images)


# An icon on a shaded box -- a callout's tick, a tip's bulb -- covers a sliver of
# the box it sits in. LibreOffice Writer's Note/Tip headings (y36: a 473x26pt
# band, a 19.5pt icon at its left end, 3% of its area) are a band holding a
# word, and read as artwork the cluster went to a figure that grew over the
# heading and paragraph above it and the note's first lines below: 105pt of
# text rasterised on page 5, and the rest of the note set 82pt lower. A curve
# wholly inside a filled rectangle of its own cluster, covering no more than
# ICON_FILL_FRAC of it, is that box's ornament, as a glyph-sized one already is.
ICON_FILL_FRAC = 0.1


def _icon_on_fill(d: DrawCmd, ds) -> bool:
    """...and so is the artwork inside it taken TOGETHER: a drawing set in a
    framed box is many small pieces (lshort's arrows, y22 p106: each vector a
    sliver of its frame, all of them the whole frame) and stays a figure.
    Only on a band that is the cluster's one fill: among several (y59's
    mock-up notice page, tiles standing for a page's panels) the curves are
    the picture's, and read as ornaments they left tables of empty cells."""
    fills = [f for f in ds if f.fill and f.shape == "rect" and not _is_glyphlike(f)]
    if len(fills) != 1:
        return False
    for f in fills:
        if f is d or not f.fill or f.shape != "rect" or not contains(f.bbox, d.bbox, 0.5):
            continue
        art = None
        for e in ds:
            if e is not f and e.shape in ("curve", "complex", "line") and \
                    not _is_glyphlike(e) and contains(f.bbox, e.bbox, 0.5):
                art = bbox_union(art, e.bbox)
        if art is not None and bbox_area(art) <= ICON_FILL_FRAC * bbox_area(f.bbox):
            return True
    return False


def _classify_cluster(cl) -> str:
    ds = [d for _, d in cl]
    art = [d for d in ds if d.shape in ("curve", "complex", "line")
           and not _is_glyphlike(d) and not _icon_on_fill(d, ds)]
    # A rule is a rule at any length; on its own it is never a figure.
    if art and not all(d.shape == "line" and _thin(d) for d in art):
        return "figure"
    # Lattice evidence is tested BEFORE the bar-chart shape test below, and
    # outranks it. The bar test asks whether three or more filled rectangles
    # share a bottom edge with differing heights -- true of a bar chart, and
    # equally true of a table row whose merged cells have different heights.
    # When it won, a whole bordered table was classified 'figure'; the figure
    # budget then refused to rasterise that much text, and the fallback broke
    # the table into one single-cell box per rectangle. NIST SP 800-171 p94 is
    # one table 686pt tall and became 55 stacked boxes totalling 2947pt, plus
    # 1294pt of figures over the same region.
    #
    # A lattice of long edges at many distinct rows AND columns is much
    # stronger evidence than a shared baseline: a bar chart has one baseline
    # and no interior horizontal rules. Measured over all 45 fixtures, no
    # cluster that the bar test claims on a gated fixture has a lattice --
    # including c5_graphics, which is the chart fixture.
    hs, vs = [], []
    for d in ds:
        h, v = _edges_of(d)
        hs += h
        vs += v
    hys = _cluster([h[0] for h in hs if h[2] - h[1] > 40], 2.0)
    vxs = _cluster([v[0] for v in vs if v[2] - v[1] > 6], 2.0)
    if len(hys) >= 2 and len(vxs) >= 2 and (len(hys) >= 3 or len(vxs) >= 3):
        return "grid"
    fills = [d for d in ds if d.fill and d.shape == "rect"]
    # A glyph-sized square is not a bar. Word/PDFMaker paints one at every
    # border junction, flush with the rules it joins; a shaded heading box
    # has four, two of them sharing the fill's bottom edge. While dialect
    # promoted the joints to bullets they left the drawing list; once they
    # stayed (as the border ink they are), those three bottoms called the box
    # a bar chart and rasterised the heading with the paragraph under it --
    # measured on y08 without this guard: all 12 chapter headings.
    bars = [f for f in fills if not _is_glyphlike(f)]
    if len(bars) >= 3:
        bots = _cluster([f.bbox[3] for f in bars], 2.5)
        for b in bots:
            grp = [f for f in bars if abs(f.bbox[3] - b) <= 2.5]
            if len(grp) >= 3:
                hts = [f.bbox[3] - f.bbox[1] for f in grp]
                if max(hts) > 1.3 * max(1e-6, min(hts)):
                    return "figure"
    if len(fills) >= 2:
        y0s = _cluster([f.bbox[1] for f in fills], 3.0)
        y1s = _cluster([f.bbox[3] for f in fills], 3.0)
        if len(y0s) == 1 and len(y1s) == 1:
            xs = sorted(fills, key=lambda f: f.bbox[0])
            if all(xs[i + 1].bbox[0] - xs[i].bbox[2] <= 4 for i in range(len(xs) - 1)) \
                    and all(f.bbox[2] - f.bbox[0] >= 40 for f in xs):
                return "cards"
        x0s = _cluster([f.bbox[0] for f in fills], 3.0)
        x1s = _cluster([f.bbox[2] for f in fills], 3.0)
        if len(x0s) == 1 and len(x1s) == 1:
            return "stripes"
    if len(fills) == 1 and not (_is_glyphlike(fills[0]) and len(ds) > 1):
        # ...but not when that one "box" is the joint square where the
        # cluster's rules meet: Word paints a 0.5pt square at the corner of a
        # pleading caption's bracket (y63: an hline and a vline meeting at
        # 319.0, 480.8), and as the box it took the text BELOW the bracket
        # into a 254pt-wide cell.
        return "boxlike"
    # "lots of primitives" only implies artwork when the primitives are
    # substantial. Four hairline rules are a ruled table, not a chart.
    substantial = [d for d in ds if not _is_glyphlike(d) and not _thin(d)]
    if len(substantial) >= 4:
        return "figure"
    return "loose"


# ------------------------------------------------------------------ tables
def _all_lines(blocks: List[TextBlock]):
    for b in blocks:
        for ln in b.lines:
            yield ln


def _take_lines_in(blocks, rect: BBox, consumed: set, mode="center") -> List[Line]:
    out = []
    for ln in _all_lines(blocks):
        if id(ln) in consumed:
            continue
        lb = ln.bbox
        if mode == "center":
            cx, cy = (lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2
            ok = rect[0] - 1 <= cx <= rect[2] + 1 and rect[1] - 1 <= cy <= rect[3] + 1
        else:
            ok = bbox_overlap(lb, rect) > 0.55 * max(1e-6, bbox_area(lb))
        if ok:
            out.append(ln)
            consumed.add(id(ln))
    return out


def _space_paras(paras: List[Para], top: float):
    """Assign baseline-anchored space_before within a container."""
    cursor = top
    for p in paras:
        t, h = _para_box(p)
        p.space_before = max(0.0, round(t - cursor, 1))
        p.space_after = 0.0
        cursor = t + h
    return cursor


def _cell_from_lines(lines: List[Line], rect: BBox, pad_extra=(2.0, 2.0)) -> Cell:
    cell = Cell(borders={})
    if lines:
        minx = min(l.bbox[0] for l in lines)
        cell.paras = paras_from_line_list(lines, rect[0], rect[2] - 2)
        t0 = _para_box(cell.paras[0])[0] if cell.paras else rect[1]
        pad_top = max(0.0, round(t0 - rect[1], 1))
        end = _space_paras(cell.paras, rect[1] + pad_top)
        pad_bot = max(pad_extra[0], round(rect[3] - end, 1))
        cell.pad = (pad_top, round(max(0, minx - rect[0]), 1),
                    pad_bot, pad_extra[1])
        for p in cell.paras:
            p.left_indent = max(0.0, round((p.bbox[0] if p.bbox else minx) - rect[0]
                                           - cell.pad[1], 1)) \
                if p.align in ("left", "justify") else p.left_indent
    return cell


def _striped_row_tiles(draws: List[Tuple[int, DrawCmd]]):
    """Return full-width filled row candidates without claiming any content.

    A regular table often paints only alternating rows.  Its fill is therefore
    represented as several adjacent rectangles, not one large rectangle.  This
    collector is intentionally stricter than the old ``stripes`` cluster: all
    tiles in a row must share top/bottom edges and be contiguous.
    """
    by_y = defaultdict(list)
    for di, d in draws:
        if not (d.fill and d.shape == "rect"):
            continue
        if d.bbox[2] - d.bbox[0] < 12 or d.bbox[3] - d.bbox[1] < 8:
            continue
        by_y[(round(d.bbox[1] * 2), round(d.bbox[3] * 2))].append((di, d))
    out = []
    for group in by_y.values():
        group.sort(key=lambda item: item[1].bbox[0])
        # A row may be emitted as two adjacent rectangles due to a merged
        # producer path, but it must still form a contiguous tiled band.
        runs, run = [], [group[0]]
        for item in group[1:]:
            if item[1].bbox[0] - run[-1][1].bbox[2] <= 1.25:
                run.append(item)
            else:
                runs.append(run)
                run = [item]
        runs.append(run)
        for run in runs:
            if len(run) < 2:
                continue
            x0, x1 = run[0][1].bbox[0], run[-1][1].bbox[2]
            if x1 - x0 < 80:
                continue
            bounds = [x0] + [d.bbox[2] for _, d in run]
            out.append((run, bounds))
    return out


def _regular_striped_table_segment(draws: List[Tuple[int, DrawCmd]], blocks,
                                   consumed: set) -> Optional[Tuple[TableEl, set]]:
    """Recognise a conservative, row-regular striped table on one page.

    This is intentionally a *segment* detector.  It validates all geometry
    and text ownership using a probe set before it consumes lines/drawings, so
    cards, callouts, mixed dashboard regions, and wrapped cells retain the
    established inference path.
    """
    tile_rows = _striped_row_tiles(draws)
    if len(tile_rows) < 3:
        return None

    # Find a repeated column signature among the painted row bands.  Rounded
    # half-point coordinates survive both PyMuPDF and PDFium extraction.
    signatures = defaultdict(list)
    for run, bounds in tile_rows:
        sig = tuple(round(v / 2.0) * 2.0 for v in bounds)
        if len(sig) >= 3:
            signatures[sig].append((run, bounds))
    ranked = sorted(signatures.values(), key=len, reverse=True)
    if not ranked or len(ranked[0]) < 3:
        return None
    rows = ranked[0]
    sample_bounds = rows[0][1]
    n_cols = len(sample_bounds) - 1
    if n_cols < 2 or n_cols > 8:
        return None
    x0, x1 = sample_bounds[0], sample_bounds[-1]
    if any(abs(a - b) > 2.0 for _, bounds in rows for a, b in zip(bounds, sample_bounds)):
        return None

    # Boundaries are supplied by the alternating fill rectangles and by the
    # horizontal rules on unfilled rows.  A usable rule must tile the same
    # width, not merely cross one card.
    y_boundaries = []
    for run, _ in rows:
        y_boundaries.extend((run[0][1].bbox[1], run[0][1].bbox[3]))
    hgroups = defaultdict(list)
    for di, d in draws:
        if d.shape != "hline" or d.bbox[2] - d.bbox[0] < 12:
            continue
        cy = (d.bbox[1] + d.bbox[3]) / 2
        hgroups[round(cy * 2)].append((di, d))
    boundary_draws_by_y = {}
    for group in hgroups.values():
        group.sort(key=lambda item: item[1].bbox[0])
        cursor = x0
        used = []
        for item in group:
            d = item[1]
            if d.bbox[2] < cursor - 1.5 or d.bbox[0] > x1 + 1.5:
                continue
            if d.bbox[0] > cursor + 1.5:
                break
            cursor = max(cursor, d.bbox[2])
            used.append(item[0])
        if cursor >= x1 - 1.5:
            y = sum((d.bbox[1] + d.bbox[3]) / 2 for di, d in group
                    if di in used) / max(1, len(used))
            y_boundaries.append(y)
            boundary_draws_by_y[y] = set(used)
    ys = _cluster(y_boundaries, 1.5)
    if len(ys) < 4:
        return None
    # Split unrelated regions at gaps larger than a regular row plus a small
    # tolerance.  Choose the largest valid run, never bridge dashboard bands.
    intervals = [b - a for a, b in zip(ys, ys[1:])]
    pitches = [v for v in intervals if 10.0 <= v <= 40.0]
    if len(pitches) < 3:
        return None
    pitch = median(pitches)
    runs, current = [], [ys[0]]
    for a, b in zip(ys, ys[1:]):
        if abs((b - a) - pitch) <= 2.25:
            current.append(b)
        else:
            if len(current) >= 4:
                runs.append(current)
            current = [b]
    if len(current) >= 4:
        runs.append(current)
    if not runs:
        return None
    row_ys = max(runs, key=len)
    if len(row_ys) - 1 < 3:
        return None

    # At least three alternating bands must lie within this exact regular run;
    # this prevents a short striped note above an unrelated table from winning.
    full_fills = 0
    draw_ids = set()
    for y, ids in boundary_draws_by_y.items():
        if any(abs(y - ry) <= 1.5 for ry in row_ys):
            draw_ids.update(ids)
    for run, bounds in rows:
        top, bot = run[0][1].bbox[1], run[0][1].bbox[3]
        if any(abs(top - row_ys[i]) <= 1.5 and abs(bot - row_ys[i + 1]) <= 1.5
               for i in range(len(row_ys) - 1)):
            full_fills += 1
            draw_ids.update(di for di, _ in run)
    if full_fills < 3:
        return None

    probe = set(consumed)
    cell_lines = defaultdict(list)
    all_candidate = []
    for ln in _all_lines(blocks):
        if id(ln) in probe or not ln.horizontal:
            continue
        cx, cy = (ln.bbox[0] + ln.bbox[2]) / 2, (ln.bbox[1] + ln.bbox[3]) / 2
        if not (x0 - 1 <= cx <= x1 + 1 and row_ys[0] - 1 <= cy <= row_ys[-1] + 1):
            continue
        ri = next((i for i in range(len(row_ys) - 1)
                   if row_ys[i] - 1 <= cy <= row_ys[i + 1] + 1), None)
        ci = next((j for j in range(n_cols)
                   if sample_bounds[j] - 1 <= cx <= sample_bounds[j + 1] + 1), None)
        if ri is None or ci is None:
            return None                    # text straddles/escapes a cell
        cell_lines[(ri, ci)].append(ln)
        all_candidate.append(ln)
    expected = (len(row_ys) - 1) * n_cols
    occupied = sum(1 for vals in cell_lines.values() if len(vals) == 1)
    if occupied < 0.80 * expected or len(all_candidate) != occupied:
        return None                        # missing or wrapped/multiline cells
    if any(sum(1 for ci in range(n_cols) if (ri, ci) in cell_lines) < n_cols
           for ri in range(len(row_ys) - 1)):
        return None

    tbl = TableEl(role="striped-table", bbox=(x0, row_ys[0], x1, row_ys[-1]))
    tbl.col_widths = [sample_bounds[i + 1] - sample_bounds[i] for i in range(n_cols)]
    tbl.row_heights = [row_ys[i + 1] - row_ys[i] for i in range(len(row_ys) - 1)]
    # The rule actually drawn at each row boundary (audit B24): this used to
    # be one 0.5pt #d8dee5 for every table, which is c3_tables' own colour.
    hsegs, _ = _draw_segments([d for _, d in draws if d.shape == "hline"])

    def rule_at(y):
        cov, style = _seg_cover(hsegs, y, x0, x1)
        if cov < GRID_EDGE_COVER or style is None:
            return None
        return (max(0.25, min(style[0], 12.0)), style[1])
    for ri, (top, bot) in enumerate(zip(row_ys, row_ys[1:])):
        row = []
        for ci in range(n_cols):
            rect = (sample_bounds[ci], top, sample_bounds[ci + 1], bot)
            ln = cell_lines[(ri, ci)][0]
            cell = _cell_from_lines([ln], rect, pad_extra=(1.5, 1.5))
            # Preserve the source's row band and each horizontal rule.  There
            # are no vertical strokes in this ordinary striped-table dialect.
            fill = next((d.fill for _, d in draws if d.fill and d.shape == "rect" and
                         bbox_overlap(d.bbox, rect) > 0.85 * bbox_area(rect)), None)
            if fill:
                cell.shading = fill
            cell.borders = {k: v for k, v in (("top", rule_at(top)), ("bottom", rule_at(bot)))
                            if v}
            row.append(cell)
        tbl.rows.append(row)
    # All probes succeeded.  This is the sole point at which this detector is
    # allowed to claim text; failures above leave the normal flow untouched.
    consumed.update(id(ln) for ln in all_candidate)
    return tbl, draw_ids


def _row_signature(row: List[Optional[Cell]]):
    """Text/style evidence used only for repeated source table headers."""
    return tuple((_norm_text(" ".join(p.text for p in c.paras)),
                  tuple((round(r.size, 1), r.bold, r.italic)
                        for p in c.paras for r in p.runs))
                 if c else ("", ()) for c in row)


def _coalesce_striped_table_segments(lay: DocLayout):
    """Merge only adjacent continuation-only striped-table page segments."""
    leader = None
    header = None
    previous = None
    previous_is_final = False
    for pi, page in enumerate(lay.pages):
        elements = [el for chunk in page.chunks for el in chunk.elements]
        segments = [el for el in elements if isinstance(el, TableEl) and
                    el.role == "striped-table"]
        if len(segments) != 1:
            leader = header = previous = None
            previous_is_final = False
            continue
        segment = segments[0]
        if leader is None:
            leader, header, previous = segment, segment.rows[0] if segment.rows else None, segment
            previous_is_final = bool(elements and elements[-1] is segment)
            continue
        # A continuation page must contain *only* this verified table.  This
        # is what makes dropping its explicit source-page break safe.
        # PDF body baselines routinely stop 8--14pt above the nominal bottom
        # margin; use the conventional 72pt reserve as a floor rather than
        # requiring the last painted rule to touch it.
        if len(elements) != 1 or len(segment.col_widths) != len(leader.col_widths) or \
                any(abs(a - b) > 2.0 for a, b in zip(segment.col_widths, leader.col_widths)) or \
                previous is None or previous.bbox is None or segment.bbox is None or \
                not previous_is_final or \
                abs(previous.bbox[0] - segment.bbox[0]) > 2.0 or \
                abs(previous.bbox[2] - segment.bbox[2]) > 2.0 or \
                previous.bbox[3] < lay.page_h - max(72.0, lay.margin_b) - 8.0 or \
                segment.bbox[1] > lay.margin_t + 12.0:
            leader, header, previous = segment, segment.rows[0] if segment.rows else None, segment
            previous_is_final = bool(elements and elements[-1] is segment)
            continue
        if header and segment.rows and _row_signature(segment.rows[0]) == _row_signature(header):
            segment.rows.pop(0)
            if segment.row_heights:
                segment.row_heights.pop(0)
            leader.repeat_header_rows = max(leader.repeat_header_rows, 1)
        leader.rows.extend(segment.rows)
        leader.row_heights.extend(segment.row_heights)
        for chunk in page.chunks:
            chunk.elements = [el for el in chunk.elements if el is not segment]
        page.continuation_only = True
        previous = segment
        previous_is_final = True


def _split_span_at_boundaries(s: Span, col_xs: List[float]) -> List[Span]:
    """Split a single span that straddles drawn column boundaries.

    The parser's cell-join has a second, harder form: cells joined with NO
    span boundary at all -- one text run, "base L0" measured 40pt wide over
    a 28.5pt drawn column. Spans cannot help, but character advances can.
    For monospace the advance is a known constant, so the boundary's
    character position is arithmetic; for proportional text the span's own
    width is divided evenly across its characters, an estimate good to a
    couple of characters on prose.

    Both forms split ONLY at a space within three characters of the
    computed boundary: the gap the parser joined across was a space, so a
    space is where cells end, and a wrong estimate can at worst move a
    whole word one cell over -- never cut a word in half. A boundary with
    no space near it is a word crossing columns (a hyphenated token in a
    spanning cell), and cutting it would corrupt text.
    """
    from .fonts import family_metrics
    bounds = [x for x in col_xs[1:-1] if s.bbox[0] + 2.0 < x < s.bbox[2] - 2.0]
    if not bounds or not s.text:
        return [s]
    fam = family_metrics(s.font)
    if fam is not None and fam[1] == "mono" and s.size > 0:
        adv = fam[0] * s.size
    else:
        adv = (s.bbox[2] - s.bbox[0]) / len(s.text)
    if adv <= 0:
        return [s]
    cuts = []
    x = s.bbox[0]
    for i, ch in enumerate(s.text):
        nxt = x + adv
        for b in bounds:
            if x <= b <= nxt:
                # the space nearest the boundary, within 3 chars either way
                lo, hi = max(0, i - 3), min(len(s.text), i + 4)
                cand = [j for j in range(lo, hi) if s.text[j] == " "]
                if cand:
                    j = min(cand, key=lambda k: abs(k - i))
                    cuts.append(j + 1)   # split AFTER the space
                bounds.remove(b)
                break
        x = nxt
    if not cuts:
        return [s]
    cuts = sorted(set(cuts))
    out = []
    start = 0
    for j in cuts + [len(s.text)]:
        if j <= start:
            continue
        text = s.text[start:j]
        x0 = s.bbox[0] + start * adv
        x1 = s.bbox[0] + j * adv
        out.append(Span(text=text, font=s.font, size=s.size, color=s.color,
                        bold=s.bold, italic=s.italic, mono=s.mono,
                        serif=s.serif, superscript=s.superscript,
                        bbox=(x0, s.bbox[1], x1, s.bbox[3]),
                        origin=(x0, s.origin[1]),
                        tracking=getattr(s, "tracking", 0.0)))
        start = j
    return out


def _fragments_by_column(ln: Line, col_xs: List[float]) -> List[Line]:
    """Split a line whose spans straddle table column boundaries.

    The parser glues adjacent table cells into one Line whenever their gap
    is under its own join threshold -- measured on a real report, "1 " and
    "v0_cand_z4js_s7" arrived as one line, and a three-cell group header as
    another -- so assigning whole lines by centre deposited two cells' text
    into one cell and left its neighbour empty (the hand campaign on that
    report measured 27 of 59 rows partitioned correctly; defect catalogue
    #6). Spans keep their own bboxes, so each span belongs to the column
    band its centre falls in, and contiguous same-band spans stay one
    fragment. A line whose spans all share a band returns ITSELF, so every
    table that already partitions correctly is byte-for-byte unchanged.
    """
    bands: List[List] = []
    for s in ln.spans:
        if s.text == "":
            continue
        for piece in _split_span_at_boundaries(s, col_xs):
            cx = (piece.bbox[0] + piece.bbox[2]) / 2
            ci = next((j for j in range(len(col_xs) - 1)
                       if col_xs[j] - 1 <= cx <= col_xs[j + 1] + 1), -1)
            if bands and bands[-1][0] == ci:
                bands[-1][1].append(piece)
            else:
                bands.append((ci, [piece]))
    if len(bands) <= 1:
        return [ln]
    out = []
    for _ci, spans in bands:
        out.append(Line(
            spans=list(spans),
            bbox=(min(s.bbox[0] for s in spans), min(s.bbox[1] for s in spans),
                  max(s.bbox[2] for s in spans), max(s.bbox[3] for s in spans)),
            dir=ln.dir))
    return out


def _draw_segments(ds) -> Tuple[list, list]:
    """Drawn boundary ink: ([(y, x0, x1, thick, colour)], [(x, y0, y1, ...)]).

    The painted thickness is the rule's own: a filled bar's short side (Word
    and PDFMaker draw every border as a 0.48-0.5pt filled rectangle and the
    DrawCmd's `width` is then a default, not a measurement), a stroked line's
    stroke width (XPP, ReportLab, LibreOffice), a stroked rectangle's sides.
    """
    hs, vs = [], []
    for d in ds:
        x0, y0, x1, y1 = d.bbox
        stroked = d.kind in ("stroke", "fillstroke") and bool(d.stroke)
        col = (d.stroke if stroked else d.fill) or "#000000"
        if d.shape == "hline":
            th = max(d.width or 0.0, y1 - y0) if stroked else (y1 - y0)
            hs.append(((y0 + y1) / 2, x0, x1, th, col))
        elif d.shape == "vline":
            th = max(d.width or 0.0, x1 - x0) if stroked else (x1 - x0)
            vs.append(((x0 + x1) / 2, y0, y1, th, col))
        elif d.shape == "rect" and stroked:
            th = d.width or 0.5
            hs += [(y0, x0, x1, th, d.stroke), (y1, x0, x1, th, d.stroke)]
            vs += [(x0, y0, y1, th, d.stroke), (x1, y0, y1, th, d.stroke)]
    return hs, vs


def _seg_cover(segs, pos: float, a: float, b: float):
    """How much of the lattice segment [a, b] on line `pos` is drawn.

    -> (covered fraction, (thickness, colour) of the dominant ink or None).
    Dominance is by INK -- length times thickness -- because a boundary is
    sometimes several parallel strokes: FIPS 180's grey table separates its
    cells with a 2.2pt white bar between two 0.1pt grey hairlines, and the
    bar is the line a reader sees.
    """
    if b - a <= 1e-6:
        return 0.0, None
    ivs = []
    ink = defaultdict(float)
    for p, s0, s1, th, col in segs:
        if abs(p - pos) > GRID_EDGE_TOL:
            continue
        lo, hi = max(a, s0), min(b, s1)
        if hi - lo <= 0:
            continue
        ivs.append((lo, hi))
        ink[(round(max(th, 0.1), 2), col)] += (hi - lo) * max(th, 0.25)
    if not ivs:
        return 0.0, None
    ivs.sort()
    tot, (lo0, hi0) = 0.0, ivs[0]
    for lo, hi in ivs[1:]:
        if lo > hi0:
            tot += hi0 - lo0
            lo0, hi0 = lo, hi
        else:
            hi0 = max(hi0, hi)
    tot += hi0 - lo0
    style = max(ink.items(), key=lambda kv: kv[1])[0]
    return tot / (b - a), style


def _cell_tiles(fills):
    """Fill rectangles that are cell backgrounds, not decoration inside one.

    Word paints a shaded cell twice: the cell, and each paragraph's shading
    inset ~5pt inside it in the same colour (y02 p75: cell 90.2-239.4,
    paragraph 95.4-234.2, both #c6d9f1). The inner one paints nothing a
    reader can see and its edges are not cell boundaries.
    """
    out = []
    for f in fills:
        nested = any(g is not f and g.fill == f.fill
                     and bbox_area(g.bbox) > bbox_area(f.bbox) + 1.0
                     and contains(g.bbox, f.bbox, 0.6) for g in fills)
        if not nested:
            out.append(f)
    return out


def _extend_by_tiles(xs: List[float], ys: List[float], tiles, has_text=None):
    """Grow a lattice outward over cells drawn only as fills.

    A shaded table separated by rules BETWEEN its cells has no rule on its
    outer edge: FIPS 180's Figure 1 is grey cells with white gridlines, so
    the lattice from drawn lines held only the three middle columns and the
    middle rows; the Algorithm and Digest columns and the header row fell
    out of the table as loose 'SHA-1 160' paragraphs (defect catalogue #13).
    A fill whose inner edge sits ON the lattice's outer line and which
    extends outward is a cell of the same table; its outer edge is the
    table's edge. Only outward, and only from a tile sharing the line --
    a page band that merely contains the table shares neither edge -- and
    only a tile holding text: an empty fill beside a table is a panel, not
    a column (y65's form has white boxes flush with its label table).
    """
    t = GRID_EDGE_TOL
    ys = list(ys)
    xs = list(xs)
    if has_text is not None:
        tiles = [f for f in tiles if has_text(f.bbox)]
    # rows first (tiles over the lattice's columns), then columns over the
    # grown rows, so a corner cell of an outer row and column is reached
    top = [f.bbox[1] for f in tiles if abs(f.bbox[3] - ys[0]) <= t
           and f.bbox[1] < ys[0] - 4 and f.bbox[2] > xs[0] + t
           and f.bbox[0] < xs[-1] - t]
    bot = [f.bbox[3] for f in tiles if abs(f.bbox[1] - ys[-1]) <= t
           and f.bbox[3] > ys[-1] + 4 and f.bbox[2] > xs[0] + t
           and f.bbox[0] < xs[-1] - t]
    if top:
        ys.insert(0, min(top))
    if bot:
        ys.append(max(bot))
    left = [f.bbox[0] for f in tiles if abs(f.bbox[2] - xs[0]) <= t
            and f.bbox[0] < xs[0] - 4 and f.bbox[3] > ys[0] + t
            and f.bbox[1] < ys[-1] - t]
    right = [f.bbox[2] for f in tiles if abs(f.bbox[0] - xs[-1]) <= t
             and f.bbox[2] > xs[-1] + 4 and f.bbox[3] > ys[0] + t
             and f.bbox[1] < ys[-1] - t]
    if left:
        xs.insert(0, min(left))
    if right:
        xs.append(max(right))
    return xs, ys


def _tile_edge(tiles, vertical: bool, pos: float, a: float, b: float) -> bool:
    """Does a cell-background tile END on this lattice segment?

    The author's cell structure is also in the fills: two shaded cells with
    no rule between them are still two cells when each is its own rectangle
    (and a cell shaded differently from its neighbour is visibly separate).
    """
    t = GRID_EDGE_TOL
    for f in tiles:
        x0, y0, x1, y1 = f.bbox
        if vertical:
            if (abs(x0 - pos) <= t or abs(x1 - pos) <= t) and \
                    min(b, y1) - max(a, y0) >= GRID_EDGE_COVER * (b - a):
                return True
        else:
            if (abs(y0 - pos) <= t or abs(y1 - pos) <= t) and \
                    min(b, x1) - max(a, x0) >= GRID_EDGE_COVER * (b - a):
                return True
    return False


def _grid_regions(n_rows: int, n_cols: int, vdrawn, hdrawn):
    """Rectangular merged regions from the boundaries that exist.

    vdrawn[i][j]: the boundary LEFT of column j in row i exists (j >= 1).
    hdrawn[i][j]: the boundary ABOVE row i in column j exists (i >= 1).
    -> {(r0, c0): (r1, c1)} covering every lattice cell exactly once.

    Horizontal runs first, row by row; then a run continues downward only
    while the row below holds a run with the same columns and no boundary
    separates them along its whole width. Every region is a rectangle by
    construction, which is what gridSpan/vMerge can express; a merge shape
    that is not (an L) stays as its rectangles rather than being forced.
    """
    runs = []                     # per row: list of (c0, c1)
    for i in range(n_rows):
        row, c0 = [], 0
        for j in range(1, n_cols):
            if vdrawn[i][j]:
                row.append((c0, j - 1))
                c0 = j
        row.append((c0, n_cols - 1))
        runs.append(row)
    regions = {}
    open_ = {}                    # (c0, c1) -> r0 of the region still growing
    for i in range(n_rows):
        nxt = {}
        for c0, c1 in runs[i]:
            r0 = open_.get((c0, c1))
            if r0 is not None and not any(hdrawn[i][j] for j in range(c0, c1 + 1)):
                nxt[(c0, c1)] = r0
            else:
                if r0 is not None:
                    regions[(r0, c0)] = (i - 1, c1)
                nxt[(c0, c1)] = i
        for key, r0 in open_.items():
            if key not in nxt or nxt[key] != r0:
                if (r0, key[0]) not in regions:
                    regions[(r0, key[0])] = (i - 1, key[1])
        open_ = nxt
    for (c0, c1), r0 in open_.items():
        regions[(r0, c0)] = (n_rows - 1, c1)
    return regions


def _center_cell(cell: Cell, lines: List[Line], rect: BBox) -> None:
    """A cell whose text is centred: symmetric pads, and its own line breaks.

    `_cell_from_lines` measures the left pad from the cell edge to the
    text, which for centred text is half the slack; with the default 2pt
    right pad the paragraph then centres in a box shifted right by the
    difference -- NIST SP 800-171's 'SECURITY REQUIREMENTS' header sat ~10pt
    right of centre, and a merged header's text area lost a quarter of
    its width and hyphenated ('Relevant Secu-rity'). Both sides take the
    smaller gap, capped at Word's default cell margin (0.075in): the centre
    is the source's and the wrap width is the cell less the margins Word
    itself gave it.

    A centred header is also set line by line ('NIST SP 800-53' / 'Relevant
    Security Controls'): where a line plus the next line's first word would
    have fitted, the break was the author's, and the paragraph keeps it.
    """
    if not cell.paras or not lines or \
            not all(p.align == "center" for p in cell.paras):
        return
    x0 = min(l.bbox[0] for l in lines)
    x1 = max(l.bbox[2] for l in lines)
    side = round(max(0.0, min(x0 - rect[0], rect[2] - x1, GRID_CENTER_PAD)), 1)
    cell.pad = (cell.pad[0], side, cell.pad[2], side)
    inner = (rect[2] - rect[0]) - 2 * side
    for p in list(cell.paras):
        p.left_indent = p.right_indent = p.first_indent = 0.0
        if p.bbox is None or (p.src_lines or 0) < 2 or p.line_breaks:
            continue
        pl = _merge_row_lines([l for l in lines if contains(p.bbox, l.bbox, 0.5)])
        if len(pl) < 2:
            continue
        forced = False
        for a, b in zip(pl, pl[1:]):
            words = b.text.split()
            if not words:
                continue
            bw = b.bbox[2] - b.bbox[0]
            first_w = bw * len(words[0]) / max(1, len(b.text.strip()))
            size = max((s.size for s in a.spans), default=10.0)
            if (a.bbox[2] - a.bbox[0]) + SPACE_EM * size + first_w < inner - 1.0:
                forced = True
                break
        if not forced:
            continue
        _split_lines(cell, p, pl)


def _para_lines(p: Para, lines: List[Line]) -> List[Line]:
    """The cell lines a paragraph was built from (by its box), row-merged."""
    if p.bbox is None:
        return []
    return _merge_row_lines([l for l in lines if contains(p.bbox, l.bbox, 0.5)])


def _split_lines(cell: Cell, p: Para, pl: List[Line]) -> None:
    """Replace a cell paragraph by one paragraph per source line.

    The author's line breaks are kept as paragraph ends rather than soft
    breaks inside one paragraph: same positions under the exact line rule
    (each paragraph one leading tall, no space between), and every value or
    header line stays separately editable.
    """
    out = []
    for i, ln in enumerate(pl):
        q = copy.copy(p)
        q.runs = runs_from_spans(ln.spans)
        if q.runs:
            q.runs[-1].text = q.runs[-1].text.rstrip(" ")
        q.bbox = ln.bbox
        q.space_before = p.space_before if i == 0 else 0.0
        q.space_after = 0.0
        q.src_lines = 1
        q.src_widths = [round(ln.bbox[2] - ln.bbox[0], 1)]
        q._vis_lines = 1
        q.line_breaks = False
        q.first_indent = 0.0
        if q.align == "justify":
            q.align = "left"
        q.right_indent = 0.0
        out.append(q)
    k = cell.paras.index(p)
    cell.paras[k:k + 1] = out


def _fit_grid_cells(cells) -> None:
    """Values in narrow ruled columns keep their own lines and their edge.

    `cells` is [(cell, lines, rect)] for one lattice column. A column of
    figures is set flush right in the source, so its cells' line ends
    agree while their starts wander with the digit count; and a stack of
    figures in one cell ('1,205' / '1,211' / ...) is one value per line,
    not prose. Read as left-aligned justified paragraphs with the left gap
    as a pad, IRS's EIC tables left 15.3pt of a 29.5pt column for '1,205',
    which Arial sets in 16.3 -- every figure broke mid-token in the render
    ('1,20' / '5') and y06 lost 9% of its words. Flush-right columns are
    emitted right-aligned with a small left pad, and token-per-line
    paragraphs keep their breaks.
    """
    rights, lefts = [], []
    for cell, lines, rect in cells:
        for ln in lines:
            rights.append(rect[2] - ln.bbox[2])
            lefts.append(ln.bbox[0] - rect[0])
    flush_right = len(rights) >= 3 and max(rights) - min(rights) <= 1.5 \
        and max(lefts) - min(lefts) > 3.0
    for cell, lines, rect in cells:
        if not cell.paras or not lines or \
                not all(p.align in ("left", "justify", "right") for p in cell.paras):
            continue
        tokens = True
        for p in list(cell.paras):
            pl = _para_lines(p, lines)
            one = all(len(ln.text.split()) == 1 for ln in pl)
            tokens = tokens and one
            if len(pl) >= 2 and one and not p.line_breaks:
                _split_lines(cell, p, pl)
        gap_r = min(rect[2] - ln.bbox[2] for ln in lines)
        gap_l = min(ln.bbox[0] - rect[0] for ln in lines)
        # a lone column of equal-width figures cannot show its flush edge;
        # values that sit nearer the right rule than the left are set right
        if flush_right or (tokens and gap_r < gap_l):
            cell.pad = (cell.pad[0], 1.0, cell.pad[2], round(max(0.0, gap_r), 1))
            for p in cell.paras:
                p.align = "right"
                p.left_indent = p.first_indent = p.right_indent = 0.0


def _tile_frame(cl, has_text=None):
    """(x0, y0, x1, y1, inner_xs) of a cluster that is a row band of a
    fill-tiled table, or None.

    Tiled means cells drawn as abutting filled rectangles with at most
    horizontal rules -- ReportLab's and the HTML engines' idiom -- and at
    least two columns (an internal tile edge). A cluster with vertical
    rules is a ruled grid, whose own lines already join its rows; one with
    curves is artwork. And cells hold text: at least half the tiles must
    (y59's illustrated notice pages are black tiles with one caption
    between them, and read as a 19-row table of empty cells).
    """
    ds = [d for _, d in cl]
    if any(d.shape == "vline" and d.bbox[3] - d.bbox[1] > 6 for d in ds):
        return None
    if any(d.shape in ("curve", "complex") and not _is_glyphlike(d) for d in ds):
        return None
    tiles = _cell_tiles([d for d in ds if d.fill and d.shape == "rect"
                         and not _is_glyphlike(d)])
    if len(tiles) < 2:
        return None
    if has_text is not None and \
            2 * sum(1 for t in tiles if has_text(t.bbox)) < len(tiles):
        return None
    x0 = min(t.bbox[0] for t in tiles)
    x1 = max(t.bbox[2] for t in tiles)
    inner = _cluster([e for t in tiles for e in (t.bbox[0], t.bbox[2])
                      if x0 + GRID_EDGE_TOL < e < x1 - GRID_EDGE_TOL], 2.0)
    if not inner:
        return None
    y0 = min(d.bbox[1] for d in ds)
    y1 = max(d.bbox[3] for d in ds)
    return (x0, y0, x1, y1, inner)


def _mostly_texted(t: TableEl) -> bool:
    """Do at least half of a table's cells hold text?"""
    cells = [c for row in t.rows for c in row if c is not None]
    return bool(cells) and 2 * sum(1 for c in cells if c.paras) >= len(cells)


def _tile_bands(clusters, blocks, consumed):
    """Clusters that are row bands of ONE fill-tiled table.

    Such a table's unshaded rows draw nothing, so its shaded rows arrive as
    separate drawing clusters with text rows between them. c3_tables'
    merged-header table was a header cluster (whose 'Region' cell, two rows
    tall, beside one-row cells, read as bars of a chart and was rasterised
    with the heading above it) and two zebra rows that became empty
    one-row tables; its nested-detail table lost its nesting the same way
    ('Platform Index amber' as one paragraph). Bands chain when they share
    the table's left and right edges and an internal column edge, and the
    gap between them is a text row: no taller than TILE_BAND_GAP of a band
    row, holding text inside the table's width.
    """
    def has_text(rect):
        return any(id(ln) not in consumed and any(
            s.text.strip() and rect[0] <= (s.bbox[0] + s.bbox[2]) / 2 <= rect[2]
            and rect[1] <= (s.bbox[1] + s.bbox[3]) / 2 <= rect[3] for s in ln.spans)
            for ln in _all_lines(blocks))

    frames = []
    for cl in clusters:
        f = _tile_frame(cl, has_text)
        if f is not None:
            frames.append((f, cl, True))
        elif all(d.shape == "hline" for _, d in cl):
            # rules alone: the row lines of a table nested in a cell
            ds = [d for _, d in cl]
            frames.append(((min(d.bbox[0] for d in ds), min(d.bbox[1] for d in ds),
                            max(d.bbox[2] for d in ds), max(d.bbox[3] for d in ds), []),
                           cl, False))
    frames.sort(key=lambda fc: fc[0][1])

    def tile_rows(cl):
        """Rows of a cluster whose tiles form a FULL lattice -- every row a
        tile in every column -- else 0. y06's worksheet frames are tiles of
        many sizes (a sidebar of 'Part 1' labels beside one wide panel), and
        read as one table they wrapped its worksheets into a nine-row grid
        (164 -> 169 pages)."""
        fills = [d for _, d in cl if d.fill and d.shape == "rect"
                 and not _is_glyphlike(d)]
        tiles = _cell_tiles(fills)
        rows = _cluster([t.bbox[1] for t in tiles], 2.0)
        cols = _cluster([t.bbox[0] for t in tiles], 2.0)
        if len(rows) < 2 or len(cols) < 2 or len(tiles) != len(rows) * len(cols):
            return 0
        seen = set()
        for t in tiles:
            key = (min(range(len(rows)), key=lambda i: abs(rows[i] - t.bbox[1])),
                   min(range(len(cols)), key=lambda i: abs(cols[i] - t.bbox[0])))
            if key in seen:
                return 0
            seen.add(key)
        return len(rows)

    def one_texted_row(cl):
        """A cluster that is ONE row of abutting tiles, every tile holding
        text: a one-row table drawn as fills. y33's consultation questions
        are a numbered badge (a teal tile holding "8") flush against a tinted
        panel holding the question; stacked two to a band they were already a
        table (above), but a question standing alone was classified a figure
        (four substantial fills), and the figure, grown from a 454pt-wide seed,
        swallowed the body lines above it within its reach -- prose
        rasterised on 20 of 60 pages, footnote references with it, so those
        pages' notes could not bind and spilled as typed text (LibreOffice
        raw 62 pages for 60, word recall 0.49 -> 0.99 with this rule). Every
        tile must hold text and the tiles must touch: a row of cards keeps
        its gutters (c1: 9.3pt) and stays cards, and a tile row with an empty
        tile is decoration. 04's KPI tiles (66-546pt, abutting) read this
        way too, at their source x (12pt right of it as cards)."""
        tiles = sorted(_cell_tiles([d for _, d in cl if d.fill and d.shape == "rect"
                                    and not _is_glyphlike(d)]),
                       key=lambda t: t.bbox[0])
        if len(tiles) < 2 or len(_cluster([t.bbox[1] for t in tiles], 2.0)) != 1 \
                or len(_cluster([t.bbox[3] for t in tiles], 2.0)) != 1:
            return False
        if any(abs(b.bbox[0] - a.bbox[2]) > GRID_EDGE_TOL
               for a, b in zip(tiles, tiles[1:])):
            return False
        if not all(has_text(t.bbox) for t in tiles):
            return False
        # A shaded header over unruled body rows is the headed table's
        # (build_headed_table, x04/x10's 'Table 3'), which reads the rows
        # under it; probed on a copy, as it claims lines when it accepts.
        return build_headed_table(cl, blocks, set(consumed)) is None

    def close(cur, bands):
        # trailing rule-only frames belong to whatever follows, not here
        while cur and not cur[-1][2]:
            cur.pop()
        tiled_cls = [c for _, c, tiled in cur if tiled]
        # ...or ONE cluster that is itself rows of tiles: a table whose every
        # row is filled (white body rows under a grey header) touches from
        # row to row and arrives whole. LibreOffice Writer's tables do (y36
        # p2: 5 rows x 3 tiles, no vertical rule); classified as a figure it
        # was refused by the figure budget, each tile became a box, and the
        # boxes a one-row 'cards' table per row with its rules as paragraphs
        # between them -- 110pt over the page.
        if len(tiled_cls) >= 2 or (len(tiled_cls) == 1 and (
                tile_rows(tiled_cls[0]) >= 2 or one_texted_row(tiled_cls[0]))):
            bands.append([c for _, c, _ in cur])

    bands, cur = [], []
    for f, cl, tiled in frames:
        if cur:
            pf = cur[-1][0]                                 # previous frame
            tf = next(fr for fr, _, t in reversed(cur) if t)  # last tiled one
            gap = f[1] - pf[3]
            rows = [d.bbox[3] - d.bbox[1] for _, c, _ in cur + [(f, cl, tiled)]
                    for _, d in c if d.fill and d.shape == "rect"]
            row_h = median(rows) if rows else 20.0
            if tiled:
                fits = abs(f[0] - tf[0]) <= GRID_EDGE_TOL and \
                    abs(f[2] - tf[2]) <= GRID_EDGE_TOL and \
                    any(abs(a - b) <= GRID_EDGE_TOL for a in f[4] for b in tf[4])
            else:
                fits = f[0] >= tf[0] - GRID_EDGE_TOL and f[2] <= tf[2] + GRID_EDGE_TOL
            texted = any(
                id(ln) not in consumed and pf[3] - 1 <= (ln.bbox[1] + ln.bbox[3]) / 2 <= f[1] + 1
                and ln.bbox[0] >= tf[0] - 1 and ln.bbox[2] <= tf[2] + 1
                for ln in _all_lines(blocks))
            if fits and 0 <= gap <= TILE_BAND_GAP * row_h and (texted or gap <= 6):
                cur.append((f, cl, tiled))
                continue
            close(cur, bands)
            cur = []
        if tiled:
            cur = [(f, cl, tiled)]
    close(cur, bands)
    return bands


def build_headed_table(cl, blocks, consumed) -> Optional[TableEl]:
    """A shaded header row over unruled body rows: one table, not a card row
    followed by one paragraph per cell.

    The header is a single row of abutting fill tiles, each holding text;
    the body is every following text row whose pieces each sit inside one
    header column (two columns at least), at a pitch no wider than
    HEADED_ROW_GAP header heights. x04/x10's 'Table 3' (LibreOffice and
    Chrome) was a 'cards' header and then 'January', '88.2%', '96.1%',
    '0.4%' as four stacked paragraphs per row -- 4x the rows' height, which
    took x10 onto a third page once body text was set at its true width.
    """
    ds = [d for _, d in cl]
    if any(d.shape not in ("rect", "hline") for d in ds):
        return None
    tiles = sorted(_cell_tiles([d for d in ds if d.fill and d.shape == "rect"
                                and not _is_glyphlike(d)]), key=lambda t: t.bbox[0])
    if len(tiles) < 2:
        return None
    y0, y1 = tiles[0].bbox[1], tiles[0].bbox[3]
    if any(abs(t.bbox[1] - y0) > 1.5 or abs(t.bbox[3] - y1) > 1.5 for t in tiles) or \
            any(b.bbox[0] - a.bbox[2] > 1.0 for a, b in zip(tiles, tiles[1:])):
        return None
    xs = [tiles[0].bbox[0]] + [t.bbox[2] for t in tiles]
    nc = len(tiles)

    def col_of(f):
        return next((c for c in range(nc) if xs[c] - 2.0 <= f.bbox[0]
                     and f.bbox[2] <= xs[c + 1] + 2.0), None)

    free = [ln for ln in _all_lines(blocks) if id(ln) not in consumed and ln.horizontal]
    head = [ln for ln in free if y0 - 1 <= (ln.bbox[1] + ln.bbox[3]) / 2 <= y1 + 1
            and xs[0] - 2 <= ln.bbox[0] and ln.bbox[2] <= xs[-1] + 2]
    head_frags = [f for ln in head for f in _split_at_span_gaps(ln)]
    if {col_of(f) for f in head_frags} != set(range(nc)):
        return None                     # every header tile holds its label
    tbl = _headed_body(xs, y1, y1 - y0, free, consumed)
    if tbl is None:
        return None
    tbl.bbox = (xs[0], y0, xs[-1], tbl.bbox[3])
    tbl.row_heights = [y1 - y0] + tbl.row_heights
    hrow = []
    for c, t in enumerate(tiles):
        lines = sorted([f for f in head_frags if col_of(f) == c],
                       key=lambda l: (l.bbox[1], l.bbox[0]))
        cell = _cell_from_lines(lines, t.bbox, pad_extra=(GRID_MIN_BOTTOM_PAD, 2.0))
        cell.shading = t.fill
        hrow.append(cell)
    tbl.rows.insert(0, hrow)
    consumed.update(id(ln) for ln in head)
    return tbl


def _headed_body(xs, y_top: float, pitch: float, free, consumed,
                 first_gap: Optional[float] = None) -> Optional[TableEl]:
    """The unruled body rows of a headed table, from y_top down, as a table.

    `first_gap` bounds the distance to the first row (a continuation on the
    next page starts at its top margin, not under a header). Row boundaries
    advance by the rows' own baseline pitch, so equally spaced source rows
    stay equally spaced; the last row is as tall as the one before it.
    """
    nc = len(xs) - 1

    def col_of(f):
        return next((c for c in range(nc) if xs[c] - 2.0 <= f.bbox[0]
                     and f.bbox[2] <= xs[c + 1] + 2.0), None)

    below = sorted((ln for ln in free if ln.bbox[1] >= y_top - 1), key=lambda l: l.baseline)
    grouped = []
    for ln in below:
        if grouped and abs(ln.baseline - grouped[-1][0].baseline) <= 2.0:
            grouped[-1].append(ln)
        else:
            grouped.append([ln])
    rows, bottom = [], y_top
    for row in grouped:
        top = min(ln.bbox[1] for ln in row)
        limit = first_gap if (first_gap is not None and not rows) else HEADED_ROW_GAP * pitch
        if top - bottom > limit:
            break
        frags = [f for ln in row for f in _split_at_span_gaps(ln)]
        cols = [col_of(f) for f in frags]
        if None in cols or len(set(cols)) < 2:
            break
        rows.append((row, frags, cols))
        bottom = max(ln.bbox[3] for ln in row)
    if not rows:
        return None
    base = [max(ln.baseline for ln in r) for r, _, _ in rows]
    first_top = y_top if first_gap is None else \
        min(ln.bbox[1] for ln in rows[0][0]) - 0.25 * pitch
    tops = [first_top]
    for a, b in zip(base, base[1:]):
        tops.append(tops[-1] + (b - a))
    step = (base[-1] - base[-2]) if len(base) >= 2 else pitch
    tops.append(max(tops[-1] + step, max(ln.bbox[3] for ln in rows[-1][0]) + 0.5))
    tbl = TableEl(role="table", bbox=(xs[0], tops[0], xs[-1], tops[-1]))
    tbl.col_edges_drawn = True          # the header tiles are the author's columns
    tbl.col_widths = [xs[c + 1] - xs[c] for c in range(nc)]
    tbl.row_heights = [b - a for a, b in zip(tops, tops[1:])]
    for ri, (row, frags, cols) in enumerate(rows):
        cells = []
        for c in range(nc):
            rect = (xs[c], tops[ri], xs[c + 1], tops[ri + 1])
            lines = [f for f, cc in zip(frags, cols) if cc == c]
            cells.append(_cell_from_lines(sorted(lines, key=lambda l: l.bbox[0]), rect,
                                          pad_extra=(GRID_MIN_BOTTOM_PAD, 2.0)))
        tbl.rows.append(cells)
    consumed.update(id(ln) for r, _, _ in rows for ln in r)
    tbl._headed = (list(xs), pitch)
    return tbl


def build_grid_table(cl, blocks, consumed, tiled: bool = False) -> Optional[TableEl]:
    """A ruled table: lattice from the drawn lines, cells from the drawn EDGES.

    The lattice is every distinct row and column line. A cell boundary exists
    only where ink covers it -- Word, PDFMaker, LibreOffice and ReportLab all
    draw borders per cell side -- so a lattice segment with nothing drawn on
    it is the inside of a merged cell. Before this, every lattice cell was a
    cell: NIST SP 800-171's mapping tables, whose 'Security Requirement' cell
    spans up to twenty rows of ISO controls, had that requirement's text
    distributed over the rows its lines happened to sit in and its words over
    the neighbouring columns ('Rele-|vant', 'No direct | mapping.'); a cover
    table's full-width notices were cut in two (defect catalogue #13).

    Each cell then carries the borders actually drawn on its own sides
    (presence, width, colour), not one style on all four (audit B24).
    """
    ds = [d for _, d in cl]
    hs, vs = [], []
    for d in ds:
        h, v = _edges_of(d)
        hs += h
        vs += v
    hsegs, vsegs = _draw_segments(ds)
    fills = [d for d in ds if d.fill and d.shape == "rect" and not _is_glyphlike(d)]
    tiles = _cell_tiles(fills)
    xs = [v[0] for v in vs if v[2] - v[1] > 6]
    tile_ys = []
    if tiled:
        # A fill-tiled table (see _tile_bands) states its cells as the
        # tiles themselves, and a table nested in one of its cells as the
        # ends of that table's rules: both are lattice lines here.
        xs += [e for t in tiles for e in (t.bbox[0], t.bbox[2])]
        xs += [e for h in hs if h[2] - h[1] > 6 for e in (h[1], h[2])]
        tile_ys = [e for t in tiles for e in (t.bbox[1], t.bbox[3])]
    col_xs = _cluster(xs, 2.0)
    # A row line is a long rule -- or a short one that runs exactly from one
    # column line to another: a narrow column's per-cell border is shorter
    # than the 40pt floor, and when only the narrow columns are divided at
    # that height (the wide ones being merged across it) it is the only
    # evidence the row exists.
    #
    # Either way a row line meets the lattice at both ends -- a column line,
    # or past the outermost one. A rule that stops short of both is ink
    # INSIDE a cell: y01's cover table had a link underline running 314pt
    # under 'https://www.nist.gov/...' (wider than the underline pre-pass
    # admits), and it cut the 'Related Information' cell into two rows.
    def meets(x, side):
        if any(abs(x - c) <= GRID_EDGE_TOL for c in col_xs):
            return True
        return x <= col_xs[0] + GRID_EDGE_TOL if side < 0 \
            else x >= col_xs[-1] - GRID_EDGE_TOL

    long_ys = [h[0] for h in hs if h[2] - h[1] > 40]
    # a rule drawn in abutting pieces is tested as the one rule it is (IRS
    # pub501 draws a box's divider as 41.8-82.4 + 82.4-570.3)
    runs = []
    for y, a, b, _d in sorted(hs, key=lambda h: (round(h[0], 0), h[1])):
        if runs and abs(runs[-1][0] - y) <= 1.0 and a <= runs[-1][2] + 1.0:
            runs[-1][2] = max(runs[-1][2], b)
        else:
            runs.append([y, a, b])
    ys = [r[0] for r in runs if r[2] - r[1] > 40
          and (not col_xs or (meets(r[1], -1) and meets(r[2], 1)))]
    ys += [h[0] for h in hs if h[2] - h[1] > 6
           and any(abs(h[1] - x) <= GRID_EDGE_TOL for x in col_xs)
           and any(abs(h[2] - x) <= GRID_EDGE_TOL for x in col_xs)]
    row_ys = _cluster(ys + tile_ys, 2.0)
    if len(row_ys) < 2 or (len(row_ys) < 3 and len(col_xs) < 3):
        # rules that stop short of every column line are still the only
        # rows this table has: keep the old reading rather than lose it
        # (IRS pub501's worksheets are a framed box whose rows are drawn
        # only as answer blanks; refusing them rasterised the worksheet)
        row_ys = _cluster(long_ys + tile_ys, 2.0)
    if len(row_ys) < 2 or len(col_xs) < 2 or (len(row_ys) < 3 and len(col_xs) < 3):
        return None

    def has_text(rect):
        # by span: a row the parser joined into one Line is centred in the
        # middle of the table, whichever tile its first cell sits in
        for ln in _all_lines(blocks):
            if id(ln) in consumed:
                continue
            for s in ln.spans:
                if not s.text.strip():
                    continue
                cx = (s.bbox[0] + s.bbox[2]) / 2
                cy = (s.bbox[1] + s.bbox[3]) / 2
                if rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]:
                    return True
        return False

    col_xs, row_ys = _extend_by_tiles(col_xs, row_ys, tiles, has_text)
    nr, nc = len(row_ys) - 1, len(col_xs) - 1

    tbl = TableEl(role="table")
    tbl.col_edges_drawn = True   # col_xs came from the author's own grid lines
    tbl.bbox = (col_xs[0], row_ys[0], col_xs[-1], row_ys[-1])
    tbl.col_widths = [col_xs[i + 1] - col_xs[i] for i in range(nc)]
    tbl.row_heights = [row_ys[i + 1] - row_ys[i] for i in range(nr)]

    def shade(rect):
        for f in fills:
            if bbox_overlap(f.bbox, rect) > 0.6 * bbox_area(rect):
                return f.fill
        return None

    lat_shade = [[shade((col_xs[j], row_ys[i], col_xs[j + 1], row_ys[i + 1]))
                  for j in range(nc)] for i in range(nr)]
    # vdrawn[i][j]: boundary at col_xs[j] in row i; hdrawn[i][j]: boundary at
    # row_ys[i] in column j. Outer lines are always boundaries.
    vstyle = [[_seg_cover(vsegs, col_xs[j], row_ys[i], row_ys[i + 1])
               for j in range(nc + 1)] for i in range(nr)]
    hstyle = [[_seg_cover(hsegs, row_ys[i], col_xs[j], col_xs[j + 1])
               for j in range(nc)] for i in range(nr + 1)]
    vdrawn = [[j in (0, nc) or vstyle[i][j][0] >= GRID_EDGE_COVER
               or lat_shade[i][j - 1] != lat_shade[i][j]
               or _tile_edge(tiles, True, col_xs[j], row_ys[i], row_ys[i + 1])
               for j in range(nc + 1)] for i in range(nr)]
    hdrawn = [[i in (0, nr) or hstyle[i][j][0] >= GRID_EDGE_COVER
               or lat_shade[i - 1][j] != lat_shade[i][j]
               or _tile_edge(tiles, False, row_ys[i], col_xs[j], col_xs[j + 1])
               for j in range(nc)] for i in range(nr + 1)]

    # Text the parser holds, by lattice row. A merge is only the drawing's
    # claim; the text can refute it. Where a column line is missing in one
    # row but that row has text on both sides of it and nothing crossing it,
    # the columns are real and simply unruled there (a table ruled only in
    # its header) -- merging would run two columns' text together.
    row_lines = defaultdict(list)
    for ln in _all_lines(blocks):
        if id(ln) in consumed or not ln.horizontal:
            continue
        cx = (ln.bbox[0] + ln.bbox[2]) / 2
        cy = (ln.bbox[1] + ln.bbox[3]) / 2
        if not (tbl.bbox[0] - 1 <= cx <= tbl.bbox[2] + 1 and
                tbl.bbox[1] - 1 <= cy <= tbl.bbox[3] + 1):
            continue
        ri = next((i for i in range(nr)
                   if row_ys[i] - 1 <= cy <= row_ys[i + 1] + 1), None)
        if ri is not None:
            row_lines[ri].append(ln)
    for i in range(nr):
        spans = [s for ln in row_lines.get(i, []) for s in ln.spans if s.text.strip()]
        # each side reaches to the nearest line that IS drawn: the merged
        # run the missing line sits in, not just the lattice cell beside it
        drawn = [j for j in range(nc + 1) if vdrawn[i][j]]
        for j in range(1, nc):
            if vdrawn[i][j]:
                continue
            xb = col_xs[j]
            lo = col_xs[max(p for p in drawn if p < j)]
            hi = col_xs[min(p for p in drawn if p > j)]
            cross = any(s.bbox[0] < xb - 1.0 and s.bbox[2] > xb + 1.0 for s in spans)
            left = any(s.bbox[2] <= xb + 1.0 and s.bbox[0] >= lo - 1.0 for s in spans)
            right = any(s.bbox[0] >= xb - 1.0 and s.bbox[2] <= hi + 1.0 for s in spans)
            if left and right and not cross:
                vdrawn[i][j] = True

    regions = _grid_regions(nr, nc, vdrawn, hdrawn)
    owner = {}
    for (r0, c0), (r1, c1) in regions.items():
        for i in range(r0, r1 + 1):
            for j in range(c0, c1 + 1):
                owner[(i, j)] = (r0, c0)

    cell_lines = defaultdict(list)
    taken = []
    for ri in range(nr):
        # the boundaries that exist in this row: the drawn lines, less the
        # ones a merged region spans
        bounds = [col_xs[0]] + [col_xs[j] for j in range(1, nc)
                                if owner[(ri, j - 1)] != owner[(ri, j)]] + [col_xs[-1]]
        for ln in row_lines.get(ri, []):
            # Assign per column-band fragment, not per line: cells the parser
            # joined into one Line must not land whole in the band their
            # centre happens to fall in (`_fragments_by_column`, defect
            # catalogue #6) -- but only at boundaries this row has.
            for frag in _fragments_by_column(ln, bounds):
                fcx = (frag.bbox[0] + frag.bbox[2]) / 2
                bi = next((j for j in range(len(bounds) - 1)
                           if bounds[j] - 1 <= fcx <= bounds[j + 1] + 1), None)
                if bi is None:
                    continue
                ci = next(j for j in range(nc) if col_xs[j] >= bounds[bi] - 0.01)
                cell_lines[owner[(ri, ci)]].append(frag)
            taken.append(id(ln))

    # A bar chart in a framed plot area has a lattice too -- its stroked
    # bars' sides and the gridlines -- and the lattice test that keeps a
    # merged-cell table out of the bar-chart branch (_classify_cluster)
    # lets it in here. A table's cells hold text; a plot's do not. Measured:
    # y60's MMWR chart produced 64 cells, 2 with text (its legend), while
    # NIST SP 800-171's sparsest mapping table has text in over half.
    texted = sum(1 for k in regions if cell_lines.get(k))
    if len(regions) >= 8 and texted < GRID_MIN_TEXT_FRAC * len(regions) \
            and _has_bars(fills):
        return None
    consumed.update(taken)

    def run_style(styles):
        """One side of a region: the dominant drawn style along it, or None
        when less than half of its lattice segments are drawn."""
        cov = [s[1] for s in styles if s[0] >= GRID_EDGE_COVER and s[1] is not None]
        if not cov or len(cov) * 2 < len(styles):
            return None
        th, col = Counter(cov).most_common(1)[0][0]
        # OOXML border widths run 2..96 eighths of a point
        return (max(0.25, min(th, 12.0)), col)

    # A lattice line that every region crossing it spans (a row line drawn
    # only as answer blanks inside one box, a column line only under the
    # header) is no boundary of the table that results: the grid keeps only
    # the lines some cell ends on. IRS pub501's worksheet is one framed box,
    # not 26 rows of one merged cell.
    keep_r = sorted({0, nr} | {r for (r, _c) in regions} | {r1 + 1 for (r1, _c) in regions.values()})
    keep_c = sorted({0, nc} | {c for (_r, c) in regions} | {c1 + 1 for (_r, c1) in regions.values()})
    rmap = {r: i for i, r in enumerate(keep_r)}
    cmap = {c: i for i, c in enumerate(keep_c)}
    tbl.col_widths = [col_xs[keep_c[i + 1]] - col_xs[keep_c[i]] for i in range(len(keep_c) - 1)]
    tbl.row_heights = [row_ys[keep_r[i + 1]] - row_ys[keep_r[i]] for i in range(len(keep_r) - 1)]
    tbl.rows = [[None] * (len(keep_c) - 1) for _ in range(len(keep_r) - 1)]
    by_col = defaultdict(list)
    for (r0, c0), (r1, c1) in sorted(regions.items()):
        rect = (col_xs[c0], row_ys[r0], col_xs[c1 + 1], row_ys[r1 + 1])
        lines = sorted(cell_lines.get((r0, c0), []),
                       key=lambda l: (l.bbox[1], l.bbox[0]))
        # The bottom pad floor is the row's slack, and every row pays it:
        # the 2.0 default left NIST's 13.4pt rows (1.3 + 10.4 + a 1.7pt
        # gap) 0.3pt tall each, ~8pt over a page of them. Half a point keeps
        # a descender clear of the rule.
        cell = _cell_from_lines(lines, rect, pad_extra=(GRID_MIN_BOTTOM_PAD, 2.0))
        _center_cell(cell, lines, rect)
        cell.col_span = cmap[c1 + 1] - cmap[c0]
        cell.row_span = rmap[r1 + 1] - rmap[r0]
        if cell.row_span > 1 and cell.paras:
            # A merged cell's rows are sized by their own cells; its bottom
            # pad must not claim the whole remainder of the merge, or the
            # last row grows by every rounding error in the ones above it.
            cell.pad = (cell.pad[0], cell.pad[1], 2.0, cell.pad[3])
        cell.borders = {
            "top": run_style([hstyle[r0][j] for j in range(c0, c1 + 1)]),
            "bottom": run_style([hstyle[r1 + 1][j] for j in range(c0, c1 + 1)]),
            "left": run_style([vstyle[i][c0] for i in range(r0, r1 + 1)]),
            "right": run_style([vstyle[i][c1 + 1] for i in range(r0, r1 + 1)]),
        }
        cell.borders = {k: v for k, v in cell.borders.items() if v}
        cell.shading = shade(rect) or lat_shade[r0][c0]
        tbl.rows[rmap[r0]][cmap[c0]] = cell
        if cell.col_span == 1:
            by_col[cmap[c0]].append((cell, lines, rect))
    for col in by_col.values():
        _fit_grid_cells(col)
    return tbl


def build_cards_table(cl, blocks, consumed) -> Optional[TableEl]:
    fills = sorted([d for _, d in cl if d.fill and d.shape == "rect"],
                   key=lambda f: f.bbox[0])
    if not fills:
        return None
    y0 = min(f.bbox[1] for f in fills)
    y1 = max(f.bbox[3] for f in fills)
    tbl = TableEl(role="cards", bbox=(fills[0].bbox[0], y0, fills[-1].bbox[2], y1))
    tbl.col_widths = [f.bbox[2] - f.bbox[0] for f in fills]
    tbl.row_heights = [y1 - y0]
    row = []
    for f in fills:
        lines = _take_lines_in(blocks, f.bbox, consumed)
        cell = _cell_from_lines(sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])), f.bbox,
                                pad_extra=(4.0, 4.0))
        cell.shading = f.fill
        row.append(cell)
    tbl.rows.append(row)
    return tbl


def build_stripes_table(cl, blocks, consumed) -> Optional[TableEl]:
    fills = sorted([d for _, d in cl if d.fill and d.shape == "rect"],
                   key=lambda f: f.bbox[1])
    if not fills:
        return None
    x0 = min(f.bbox[0] for f in fills)
    x1 = max(f.bbox[2] for f in fills)
    region = (x0, fills[0].bbox[1], x1, fills[-1].bbox[3])
    col_lefts = _text_columns(blocks, region, consumed)
    if len(col_lefts) < 2:
        return None
    bounds = list(col_lefts) + [x1]
    tbl = TableEl(role="table", bbox=region)
    tbl.col_widths = [bounds[i + 1] - bounds[i] for i in range(len(col_lefts))]
    for f in fills:
        row = []
        for ci in range(len(col_lefts)):
            rect = (bounds[ci], f.bbox[1], bounds[ci + 1], f.bbox[3])
            lines = _take_lines_in(blocks, rect, consumed)
            cell = _cell_from_lines(sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])), rect)
            cell.shading = f.fill
            row.append(cell)
        tbl.rows.append(row)
        tbl.row_heights.append(f.bbox[3] - f.bbox[1])
    return tbl


def _text_columns(blocks, rect: BBox, consumed) -> List[float]:
    xs = []
    for ln in _all_lines(blocks):
        if id(ln) in consumed:
            continue
        lb = ln.bbox
        cx, cy = (lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2
        if rect[0] - 1 <= cx <= rect[2] + 1 and rect[1] - 1 <= cy <= rect[3] + 1:
            for row in [ln]:
                xs.append(lb[0])
    return _cluster(xs, 7.0)


_SPACE_RUN = re.compile(r" {2,}")


def _mono_space_gaps(ln: Line) -> Line:
    """`ln` with each monospaced span cut where a run of its own spaces is
    wider than a cell gap (RULES_CELL_GAP_EM): a typewriter table's columns.

    FIPS 197's key-expansion tables (y03, Appendix A) set each row as one
    Courier string, its columns two spaces apart ('0914dff4  14dff409
    fa9ebf01 ...'); the parser keeps literal spaces as text, so the row
    reached the rules-table builder as ONE span 401pt wide, and the builder put
    it in the column its centre fell in -- a 55pt cell, which Word,
    LibreOffice and Google Docs all wrapped to seven lines (y03's page 40
    spilled a page in Docs and in both raw lanes). A space in a monospaced
    face is a known advance (the span's width over its characters, 0.6em in
    Courier), so the run is the same gap the parser cuts a line at when it is
    drawn as white rather than typed: two Courier spaces are 1.2em. Each piece
    keeps the span's style; its box is its own characters' advance. A span
    with no such run, or not monospaced, is kept as it is."""
    out, changed = [], False
    for s in ln.spans:
        t = s.text
        if not s.mono or len(t) < 3 or not _SPACE_RUN.search(t.strip(" ")):
            out.append(s)
            continue
        adv = (s.bbox[2] - s.bbox[0]) / len(t)
        if adv <= 0 or not any(len(m.group(0)) * adv > RULES_CELL_GAP_EM * max(s.size, 1.0)
                               for m in _SPACE_RUN.finditer(t.strip(" "))):
            out.append(s)
            continue
        pos = 0
        for m in list(_SPACE_RUN.finditer(t)) + [None]:
            if m is not None and len(m.group(0)) * adv <= RULES_CELL_GAP_EM * max(s.size, 1.0):
                continue
            end = m.start() if m is not None else len(t)
            piece = t[pos:end]
            core = piece.strip(" ")
            if core:
                x0 = s.bbox[0] + (pos + len(piece) - len(piece.lstrip(" "))) * adv
                out.append(replace(s, text=core, origin=(x0, s.origin[1]),
                                   bbox=(x0, s.bbox[1], x0 + len(core) * adv, s.bbox[3])))
            if m is not None:
                pos = m.end()
        changed = True
    if not changed:
        return ln
    return Line(spans=out, dir=ln.dir, bbox=ln.bbox)


def _split_at_span_gaps(ln: Line) -> List[Line]:
    """A Line cut into the pieces separated by a gap wider than the line
    splitter's own (LINE_SPLIT_EM): table cells the parser kept on one line.
    A line with no such gap returns itself."""
    out, cur = [], []
    for s in ln.spans:
        if cur and s.bbox[0] - cur[-1].bbox[2] > RULES_CELL_GAP_EM * max(s.size, cur[-1].size, 1.0):
            out.append(cur)
            cur = []
        cur.append(s)
    if cur:
        out.append(cur)
    if len(out) <= 1:
        return [ln]
    return [Line(spans=sp, dir=ln.dir,
                 bbox=(min(s.bbox[0] for s in sp), min(s.bbox[1] for s in sp),
                       max(s.bbox[2] for s in sp), max(s.bbox[3] for s in sp)))
            for sp in out]


def _box_candidate(d) -> bool:
    """A drawn rectangle the leftover pass would build a box from."""
    return d.shape == "rect" and bool(d.fill or d.stroke) and \
        (d.bbox[2] - d.bbox[0]) > 30 and (d.bbox[3] - d.bbox[1]) > 10


def _split_lines_at_box_edges(blocks, rects, consumed=frozenset()) -> list:
    """Cut every line that runs across the side of a box, at the gap where
    the side is. Returns the cuts, [(block, line, pieces)], for
    _restore_uncut.

    Two panels side by side set their text on shared baselines, and the
    parser joins the two halves of a baseline into one line when the white
    between them is a panel gutter rather than a column gutter: y58's
    'You have earned enough credits to qualif' (45-292) and 'You have enough
    credits to qualify for M' (319-562) are one Line across the 301.4/310.4
    panel edges. Such a line belongs to neither panel -- each box claims only
    lines lying mostly inside it -- so both panels lost their text to the
    flow and the line read across them. A box edge in the white between two
    spans is the author's own statement that they are not one line. Only a
    gap wider than the line splitter's own (`_split_at_span_gaps`) is cut,
    so a word that merely touches a box edge stays whole, and only where a
    box takes a piece: two pieces that both stay in the flow are two lines on
    one baseline, which the flow stacks -- _restore_uncut joins every cut
    back that no region took a piece of (a page on y60 otherwise).

    Run before any region is built, so that the piece left outside a panel
    is where every builder looks for it: y58's 'Earnings Earnings Taxed'
    belongs to the table beside the panel it was joined to."""
    edges = []
    for x0, y0, x1, y1 in rects:
        edges.append((x0, y0, y1))
        edges.append((x1, y0, y1))
    if not edges:
        return []

    def boxed(sp):
        # the fragment a box will claim (build_box's own 'overlap' test)
        bb = (min(s.bbox[0] for s in sp), min(s.bbox[1] for s in sp),
              max(s.bbox[2] for s in sp), max(s.bbox[3] for s in sp))
        return any(bbox_overlap(bb, r) > 0.55 * max(1e-6, bbox_area(bb)) for r in rects)
    cuts = []
    for b in blocks:
        out = []
        for ln in b.lines:
            if len(ln.spans) < 2 or id(ln) in consumed:
                out.append(ln)
                continue
            cy = (ln.bbox[1] + ln.bbox[3]) / 2
            xs = [x for x, y0, y1 in edges
                  if y0 <= cy <= y1 and ln.bbox[0] < x < ln.bbox[2]]
            if not xs:
                out.append(ln)
                continue
            parts, cur = [], [ln.spans[0]]
            for s in ln.spans[1:]:
                p = cur[-1]
                gap = s.bbox[0] - p.bbox[2]
                if gap > RULES_CELL_GAP_EM * max(s.size, p.size, 1.0) and \
                        any(p.bbox[2] - 0.5 <= x <= s.bbox[0] + 0.5 for x in xs):
                    parts.append(cur)
                    cur = []
                cur.append(s)
            parts.append(cur)
            if len(parts) == 1 or not any(boxed(sp) for sp in parts):
                out.append(ln)
                continue
            pieces = [Line(spans=sp, dir=ln.dir, rtl=getattr(ln, "rtl", False),
                           bbox=(min(s.bbox[0] for s in sp), min(s.bbox[1] for s in sp),
                                 max(s.bbox[2] for s in sp), max(s.bbox[3] for s in sp)))
                      for sp in parts]
            cuts.append((b, ln, pieces))
            out.extend(pieces)
        if len(out) != len(b.lines):
            b.lines = out
    return cuts


def _keeps_panel_cuts(blocks, consumed, lay) -> bool:
    """Do this page's panel-side cuts stand (see `_infer_body`)? Yes unless
    the page's flow reads as two columns."""
    return _two_column_gutter(
        [l for l in _all_lines(blocks) if id(l) not in consumed],
        lay.margin_l, lay.page_w - lay.margin_r) is None


# A panel narrower than this share of the content width is a sidebar, not a
# column: the narrowest genuine column of a two-column page is 0.46 of it
# (TWO_COL_MIN_BAND_FRAC's measurement); DOE OIG's sidebar is 0.38, the MMWR
# summary boxes that fill one column of two (y60) 0.48.
SIDEBAR_MAX_FRAC = 0.45
# ... and the text set beside it starts within this many ems of its side: the
# panel's own inset (DOE OIG: 1.1em). A piece further off is another column of
# the page (y59's brochure panels, 5.6em).
SIDEBAR_GAP_EM = 2.0


def _sidebar_cut(cut, rects, consumed, content_w: float) -> bool:
    """Is this panel-side cut a sidebar's -- the panel a sidebar, and the
    piece outside it the start of the text set right beside it?"""
    _b, _ln, pieces = cut
    inside = [p for p in pieces if id(p) in consumed]
    outside = [p for p in pieces if id(p) not in consumed]
    if not inside or not outside:
        return False
    box = next((r for r in rects
                if any(bbox_overlap(p.bbox, r) > 0.55 * max(1e-6, bbox_area(p.bbox))
                       for p in inside)), None)
    if box is None or box[2] - box[0] >= SIDEBAR_MAX_FRAC * max(1.0, content_w):
        return False
    for p in outside:
        size = max((s.size for s in p.spans if s.text.strip()), default=10.0)
        if p.bbox[0] >= box[2] - 1.0:
            gap = p.bbox[0] - box[2]
        elif p.bbox[2] <= box[0] + 1.0:
            gap = box[0] - p.bbox[2]
        else:
            return False
        if gap > SIDEBAR_GAP_EM * size:
            return False
    return True


def _restore_uncut(cuts, consumed) -> None:
    """Put back each cut line unless regions took EVERY piece of it.

    A cut stands when the line was two regions' text on one baseline -- y58's
    two panels, a panel beside a table -- and every piece found its region.
    A piece left in the flow beside a piece a box took is a column of body
    text running past a box: cut, it re-paragraphs the column around the box,
    and on y60 (an MMWR whose summary boxes sit in one column of two) that cost
    a page in LibreOffice; uncut, the flow is exactly what it was."""
    for b, ln, pieces in cuts:
        if all(id(p) in consumed for p in pieces):
            continue
        ids = {id(p) for p in pieces}
        k = next((i for i, l in enumerate(b.lines) if id(l) in ids), None)
        if k is None:
            continue
        b.lines = b.lines[:k] + [ln] + [l for l in b.lines[k:] if id(l) not in ids]


def _gutter_bounds(rows, x0: float, x1: float) -> Optional[List[float]]:
    """Column bounds from the gaps no body-row fragment crosses.

    Right-aligned figures start wherever their width puts them, so their
    left edges do not cluster (BLS's '1,399' and '543' in one column sit
    11pt apart); the band of x they jointly occupy does. Header rows are
    left out of the projection -- a group label centred over two columns
    crosses the gutter between them -- by keeping only rows with the modal
    number of fragments or more. Each bound sits just right of the column
    it closes, so a right-aligned figure still reads as right-aligned.
    """
    counts = [len(r) for r in rows if len(r) >= 2]
    if not counts:
        return None
    mode = max(set(counts), key=counts.count)
    body = [f for r in rows if len(r) >= mode for f in r]
    if any(f.bbox[0] < x0 - 2.0 or f.bbox[2] > x1 + 2.0 for f in body):
        # the rules do not span the text they are supposed to frame (an
        # eLife funding block ruled under two of its three columns): not a
        # table this reading can bound
        return None
    ivs = sorted((f.bbox[0], f.bbox[2]) for f in body)
    merged = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a <= merged[-1][1] + 1.0:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    bounds = [x0]
    for (a0, a1), (b0, b1) in zip(merged, merged[1:]):
        if b0 - a1 >= RULES_MIN_GUTTER:
            bounds.append(a1 + min(2.0, (b0 - a1) / 2))
    bounds.append(x1)
    return bounds if len(bounds) >= 3 else None


# A rule-ruled table -- a rule under EVERY row -- has no row taller than this
# (pt): y36's Navigator table rules rows of one and two lines 20.1-32.2pt
# apart; four lines of 12pt type are under 60. A booktabs table rules only its
# head and foot and is told apart by its body, one band of many rows.
RULED_ROW_MAX_GAP = 60.0
# ...and has at least this many rules (a head rule, a foot rule, two rows).
RULED_ROW_MIN_RULES = 4
# How far past a rule's ends a line may stand and still be the table's (pt).
RULE_TABLE_TEXT_TOL = 1.5


def _ruled_rows(ys) -> bool:
    """Do these rule positions rule every row of one table (see above)?"""
    ys = sorted(ys)
    return len(ys) >= RULED_ROW_MIN_RULES and \
        max(b - a for a, b in zip(ys, ys[1:])) <= RULED_ROW_MAX_GAP


def _bands_texted(sub, blocks, consumed) -> bool:
    """Does every band between consecutive rules of `sub` hold text inside
    the rules' span? Rows do; the white between stacked frames does not
    (lshort's example boxes, y22 p60: a frame's top and bottom rule, white, the
    next frame -- four rules 26-30pt apart that are no table)."""
    ds = sorted((d for _, d in sub), key=lambda d: d.bbox[1])
    x0 = min(d.bbox[0] for d in ds)
    x1 = max(d.bbox[2] for d in ds)
    lines = [ln for ln in _all_lines(blocks) if id(ln) not in consumed and ln.text.strip()
             and x0 <= (ln.bbox[0] + ln.bbox[2]) / 2 <= x1]
    for a, b in zip(ds, ds[1:]):
        if not any(a.bbox[3] < (ln.bbox[1] + ln.bbox[3]) / 2 < b.bbox[1] for ln in lines):
            return False
    return True


def _booktabs_head(ys) -> bool:
    """A head rule, a row-high band, a mid rule, and the body under them: a
    booktabs table, however long its body. The 320pt bound on a rule group's
    span refused y24 p43's 'Reader options' table (95.3 / 116.4 / 477.7) and
    its 360pt body went to the flow, where the column detector read its two
    columns of code as a two-column page. Two rules alone (a page's head and
    foot rules around its prose) still have to fit the bound."""
    ys = sorted(ys)
    return len(ys) >= 3 and ys[1] - ys[0] <= RULED_ROW_MAX_GAP


def _cells_hold_lines(t: TableEl, tol: float = 2.0) -> bool:
    """Does every cell of `t` hold its own widest source line? A reading that
    puts a line in a column narrower than the line has the columns wrong, and
    every such row wraps. Asked of the long booktabs tables only (see
    `_booktabs_head`): y64's BLS tables set each stub's leader up to its first
    figure ('Civilian labor force........ 204,831'), and read as one table
    under their head rules every stub wrapped onto a second line -- 46 pages
    rendered 66 -- where the rule-less row reading had set them as rows."""
    for row in t.rows:
        for ci, cell in enumerate(row):
            if cell is None or not cell.paras:
                continue
            span = max(1, getattr(cell, "col_span", 1))
            cw = sum(t.col_widths[ci:ci + span]) - cell.pad[3]
            for p in cell.paras:
                # Where the writer starts the line: a right- or centre-set
                # paragraph's indent is from the CELL edge, the cell's own pad
                # inside it (write_table's `_depadded` emits the difference),
                # so the two are not added. Added, y24 p45's indented
                # '--epub-embed-font headline.otf' -- one line ending on its
                # column's edge, read as right-set -- was charged its 11.3pt
                # indent twice, failed by 0.4pt, and the whole 33-row table
                # went to the flow as a two-column page.
                lead = max(p.left_indent, cell.pad[1]) \
                    if p.align in ("right", "center") \
                    else p.left_indent + cell.pad[1]
                if p.src_widths and max(p.src_widths) + lead > cw + tol:
                    return False
    return True


def _rule_runs_by_text(grp, blocks, consumed):
    """A page's same-width rules cut into the tables they belong to.

    Rules are grouped by their ends, so two tables of one width on a page are
    one group: the pandoc manual's defaults-file tables (y24 p42), 166-248 and
    378-628, at 110.9-537.1 both, made one 462pt group that the 320pt span
    test refused whole, and both tables were set as tabbed paragraphs --
    each about 70pt longer than its source, and from page 46 on the document
    sat five pages late. Between two tables there is text the tables do not
    hold: a line standing out past the rules' ends ("The value of
    input-files ...", 107.7-539.9; the next heading at 108.0)."""
    grp = sorted(grp, key=lambda t: t[1].bbox[1])
    lines = [ln for ln in _all_lines(blocks)
             if id(ln) not in consumed and ln.text.strip()]
    out, cur = [], [grp[0]]
    for prev, nxt in zip(grp, grp[1:]):
        a, b = prev[1], nxt[1]
        x0 = min(a.bbox[0], b.bbox[0]) - RULE_TABLE_TEXT_TOL
        x1 = max(a.bbox[2], b.bbox[2]) + RULE_TABLE_TEXT_TOL
        lo, hi = a.bbox[3], b.bbox[1]
        # over the rules' span and past an end of it: text BESIDE the rules
        # (lshort's code beside its framed figure, y22 p106) cuts nothing
        if any(lo < (ln.bbox[1] + ln.bbox[3]) / 2 < hi and
               ln.bbox[0] < x1 and ln.bbox[2] > x0 and
               (ln.bbox[0] < x0 or ln.bbox[2] > x1) for ln in lines):
            out.append(cur)
            cur = [nxt]
        else:
            cur.append(nxt)
    out.append(cur)
    return out


def _rule_bands(hgroup, lines) -> Optional[List[List[Line]]]:
    """The rows of a table with a rule under every row: the lines between
    each pair of rules, one row per band -- or None when the rules are not
    row rules (see RULED_ROW_MAX_GAP) or a band holds no text.

    Read line by line instead, a row whose cells are set at different heights
    fell apart: y36's Navigator table centres '1 Navigate By' between the two
    lines of its description, 6pt off each, and became three one-line rows of
    which only one had two cells -- too few for a table, so every row went to
    the flow as three paragraphs, a third taller than the source."""
    ys = [(d.bbox[1] + d.bbox[3]) / 2 for d in hgroup]
    if not _ruled_rows(ys):
        return None
    bands = []
    for a, b in zip(ys, ys[1:]):
        band = [ln for ln in lines if a < (ln.bbox[1] + ln.bbox[3]) / 2 < b]
        if not band:
            return None
        bands.append(sorted(band, key=lambda l: (l.bbox[1], l.bbox[0])))
    return bands


# How far the next page's opening rule may differ in length from the open
# table's head rule and still be the same table's head repeated (pt). y24's
# longtables restate their head on every page 426.2pt long, at 74.9-501.1 on
# versos and 110.9-537.1 on rectos -- to 0.1pt -- so 2pt is drawing noise.
OPEN_FOOT_RULE_TOL = 2.0


def _open_foot(sub, blocks, consumed, nxt_lines, nxt_rules) -> Optional[float]:
    """The foot of a booktabs table the page break cut: a head rule, a
    row-high head band, a mid rule -- and the body under them running off the
    page with no closing rule, because the table goes on. The next page then
    opens, before any of its text, on a rule of the same span: the head
    repeated (LaTeX's longtable). Returns the y at which the cut table ends
    on this page, or None.

    y24 (the pandoc manual) sets its defaults-file tables this way; read as
    two rules alone, its p44 'Options affecting specific writers' table and
    its p45 'Citation rendering' table went to the flow as tabbed paragraphs
    after a lone rule, and from p46 on the document sat a page late.

    Everything under the mid rule must be the table's: no line stands out
    past the rules' ends (prose, a heading), and nothing on the page lies
    below it -- the body is what is left of the page."""
    ds = sorted((d for _, d in sub), key=lambda d: d.bbox[1])
    if len(ds) != 2:
        return None
    head, mid = ds
    ya, yb = (head.bbox[1] + head.bbox[3]) / 2, (mid.bbox[1] + mid.bbox[3]) / 2
    if yb - ya > RULED_ROW_MAX_GAP:
        return None
    x0 = min(d.bbox[0] for d in ds) - RULE_TABLE_TEXT_TOL
    x1 = max(d.bbox[2] for d in ds) + RULE_TABLE_TEXT_TOL
    free = [ln for ln in _all_lines(blocks)
            if id(ln) not in consumed and ln.text.strip()]
    cy = lambda ln: (ln.bbox[1] + ln.bbox[3]) / 2   # noqa: E731
    if not any(ya < cy(ln) < yb and x0 <= ln.bbox[0] and ln.bbox[2] <= x1
               for ln in free):
        return None                       # no head between the rules
    body = [ln for ln in free if cy(ln) > yb]
    if not body or any(ln.bbox[0] < x0 or ln.bbox[2] > x1 for ln in body):
        return None
    rows = _group_lines_by_row(body)
    if len(rows) < 2 or sum(1 for r in rows if len(r) >= 2) < \
            max(2, int(0.6 * len(rows))):
        return None
    # the head restated at the top of the next page, before any text there
    first = min((ln.bbox[1] for ln in nxt_lines if ln.text.strip()),
                default=None)
    # (the same LENGTH: a recto's table repeats on a verso, shifted by the
    # mirrored margins -- y24's 110.9-537.1 on p44 is 74.9-501.1 on p45)
    hw = head.bbox[2] - head.bbox[0]
    if not any(abs((r.bbox[2] - r.bbox[0]) - hw) <= OPEN_FOOT_RULE_TOL and
               (first is None or r.bbox[3] <= first)
               for r in nxt_rules):
        return None
    # the last row ends where the row pitch says the next one would begin:
    # half the white between rows past its last line
    gaps = sorted(min(l.bbox[1] for l in b) - max(l.bbox[3] for l in a)
                  for a, b in zip(rows, rows[1:]))
    white = max(0.0, gaps[len(gaps) // 2])
    return max(ln.bbox[3] for ln in rows[-1]) + white / 2


def _next_page_opening(page, hf):
    """What `_open_foot` reads of the next page: its body lines and its long
    horizontal rules, the page's furniture (running head, folio, head rule)
    left out. Empty for the last page."""
    if page is None:
        return [], []
    ct = hf["consumed_text"].get(page.number, ())
    cd = hf["consumed_draw"].get(page.number, ())
    lines =[ln for bi, b in enumerate(page.blocks) for ln in b.lines
             if (bi, id(ln)) not in ct]
    rules = [d for di, d in enumerate(page.drawings)
             if di not in cd and d.shape == "hline" and d.opacity > 0.05]
    return lines, rules


def build_rules_table(hgroup: List[DrawCmd], blocks, consumed,
                      bottom: Optional[float] = None) -> Optional[TableEl]:
    """A table read between its rules. `bottom`, when given, is the foot of
    a table that runs past its last rule to the page's foot, open (see
    `_open_foot`): every rule is then inside the table, and its last row
    has no bottom border because the source draws none."""
    hgroup = sorted(hgroup, key=lambda d: d.bbox[1])
    x0 = min(d.bbox[0] for d in hgroup)
    x1 = max(d.bbox[2] for d in hgroup)
    top, bot = hgroup[0].bbox[1], hgroup[-1].bbox[3]
    if bottom is not None:
        bot = max(bot, bottom)
    region = (x0 - 2, top - 1, x1 + 2, bot + 1)
    probe = set(consumed)
    whole = _take_lines_in(blocks, region, probe)
    if not whole:
        return None
    # Cells the parser kept on one line are cut apart at their gaps first:
    # BLS's tables (XPP) arrive as 'occupations....... 70,548 72,168 1,399
    # 1,596 1.9', one line per row, which column clustering on line lefts
    # read as four columns of indentation and no numbers at all.
    lines, joined = [], False
    for ln in whole:
        # (a typewriter table's columns are typed spaces: _mono_space_gaps)
        frags = _split_at_span_gaps(_mono_space_gaps(ln))
        joined = joined or len(frags) > 1
        lines.extend(frags)
    rows = _group_lines_by_row(lines)
    bands = _rule_bands(hgroup, lines)
    if bands is not None:
        rows = bands
    if len(rows) < 2:
        return None
    multi = sum(1 for r in rows if len(r) >= 2)
    if multi < max(2, int(0.6 * len(rows))):
        return None
    bounds = _gutter_bounds(rows, x0, x1) if joined else None
    if joined and bounds is None:
        # the cut-apart reading found no columns it can bound: read the
        # lines whole, exactly as before the cut existed
        joined, lines = False, whole
        rows = _group_lines_by_row(lines)
        if bands is not None:
            rows = _rule_bands(hgroup, lines) or rows
        if len(rows) < 2 or sum(1 for r in rows if len(r) >= 2) < \
                max(2, int(0.6 * len(rows))):
            return None
    if bounds is None:
        col_lefts = _cluster([ln.bbox[0] for ln in lines], 7.0)
        if bands is not None:
            # A column starts where no line runs across from the left: an
            # indent inside a cell is not a column (y36's two-digit row
            # numbers sit 5.9pt left of the one-digit ones).
            pieces = [f for ln in whole for f in _split_at_span_gaps(ln)]
            col_lefts = [c for i, c in enumerate(col_lefts)
                         if i == 0 or not any(f.bbox[0] < c - 3.0 and f.bbox[2] > c + 3.0
                                              for f in pieces)]
        if len(col_lefts) < 2:
            return None
        bounds = [x0]
        for i in range(1, len(col_lefts)):
            prev_right = max([l.bbox[2] for l in lines if l.bbox[0] < col_lefts[i] - 7]
                             or [col_lefts[i] - 10])
            bounds.append(min(col_lefts[i] - 2, max(prev_right + 2,
                                                    (prev_right + col_lefts[i]) / 2)))
        bounds.append(x1)
    consumed.update(id(l) for l in whole)
    tbl = TableEl(role="table", bbox=(x0, top, x1, bot))
    tbl.col_widths = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
    row_tops = [top]
    for i in range(1, len(rows)):
        prev_b = max(l.bbox[3] for l in rows[i - 1])
        cur_t = min(l.bbox[1] for l in rows[i])
        mid = (prev_b + cur_t) / 2
        for d in (hgroup[1:] if bottom is not None else hgroup[1:-1]):
            dy = (d.bbox[1] + d.bbox[3]) / 2
            if prev_b - 1 <= dy <= cur_t + 1:
                mid = dy
        row_tops.append(mid)
    row_tops.append(bot)
    rule_ys = [((d.bbox[1] + d.bbox[3]) / 2, max(0.4, d.width or (d.bbox[3] - d.bbox[1])),
                d.stroke or d.fill or "#000000") for d in hgroup]
    nc = len(tbl.col_widths)
    for ri in range(len(rows)):
        # (c0, c1) -> fragments. Cut-apart rows may carry a label centred
        # over two columns ('Employed' over its two Apr. columns): a
        # fragment that crosses a gutter, alone in the columns it covers,
        # is one cell spanning them.
        groups = {}
        if joined:
            claims = []
            for f in rows[ri]:
                cols = [c for c in range(nc)
                        if min(f.bbox[2], bounds[c + 1]) - max(f.bbox[0], bounds[c]) > 1.0]
                if not cols:
                    continue
                claims.append((f, cols[0], cols[-1]))
            for f, c0, c1 in claims:
                if c1 > c0 and any(g is not f and g0 <= c1 and g1 >= c0
                                   for g, g0, g1 in claims):
                    cx = (f.bbox[0] + f.bbox[2]) / 2
                    c0 = c1 = next((c for c in range(nc) if bounds[c] - 1 <= cx
                                    <= bounds[c + 1] + 1), c0)
                key = next((k for k in groups if k[0] <= c1 and k[1] >= c0), None)
                if key is not None:
                    nk = (min(key[0], c0), max(key[1], c1))
                    groups[nk] = groups.pop(key) + [f]
                else:
                    groups[(c0, c1)] = [f]
        else:
            row = rows[ri]
            if bands is not None:
                # a row's cells the parser joined into one line ('4 Set
                # Reminder' + 'Inserts a reminder ...') go to their columns
                row = [f for l in row for f in (
                    _split_at_span_gaps(l) if any(l.bbox[0] < b - 1 < b + 1 < l.bbox[2]
                                                  for b in bounds[1:-1]) else [l])]
            for ci in range(nc):
                rl = [l for l in row
                      if bounds[ci] - 1 <= (l.bbox[0] + l.bbox[2]) / 2 <= bounds[ci + 1] + 1]
                groups[(ci, ci)] = rl
        rowcells = [None] * nc
        c = 0
        while c < nc:
            key = next((k for k in groups if k[0] == c), (c, c))
            rl = groups.get(key, [])
            rect = (bounds[key[0]], row_tops[ri], bounds[key[1] + 1], row_tops[ri + 1])
            cell = _cell_from_lines(sorted(rl, key=lambda l: l.bbox[0]), rect,
                                    pad_extra=(1.5, 1.0))
            cell.col_span = key[1] - key[0] + 1
            for ry, rw, rc in rule_ys:
                if abs(ry - row_tops[ri]) < 2.5:
                    cell.borders["top"] = (rw, rc)
                if abs(ry - row_tops[ri + 1]) < 2.5:
                    cell.borders["bottom"] = (rw, rc)
            rowcells[c] = cell
            c = key[1] + 1
        tbl.rows.append(rowcells)
        tbl.row_heights.append(row_tops[ri + 1] - row_tops[ri])
    return tbl


def build_box(cl, blocks, consumed) -> Optional[TableEl]:
    ds = [d for _, d in cl]
    fill_rect = next((d for d in ds if d.fill and d.shape == "rect"), None)
    stroke_rect = next((d for d in ds if d.stroke and d.shape == "rect"
                        and d.kind in ("stroke", "fillstroke")), None)
    accent = next((d for d in ds if d.shape == "vline"), None)
    base = fill_rect or stroke_rect
    if base is None:
        return None
    rect = base.bbox
    probe = set(consumed)
    lines = _take_lines_in(blocks, rect, probe, mode="overlap")
    if not lines:
        return None
    consumed.update(id(l) for l in lines)
    lines.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
    mono_chars = sum(len(s.text) for l in lines for s in l.spans if s.mono)
    tot = sum(len(s.text) for l in lines for s in l.spans) or 1
    is_code = mono_chars / tot > 0.7
    cell = Cell(borders={}, shading=fill_rect.fill if fill_rect else None)
    if stroke_rect is not None:
        w = max(0.4, stroke_rect.width)
        c = stroke_rect.stroke or "#000000"
        cell.borders = {k: (w, c) for k in ("top", "bottom", "left", "right")}
    if accent is not None and accent.bbox[0] <= rect[0] + 4:
        aw = max(1.0, (accent.bbox[2] - accent.bbox[0]) if accent.fill else accent.width)
        cell.borders["left"] = (aw, accent.fill or accent.stroke or "#000000")
    minx = min(l.bbox[0] for l in lines)
    cell.pad = (0.0, round(max(0, minx - rect[0]), 1), 0.0, 4.0)
    if is_code:
        p = Para(line_breaks=True)
        lines = _merge_row_lines(lines)
        bb = None
        for l in lines:
            bb = bbox_union(bb, l.bbox)
        p.bbox = bb
        base_y = [l.baseline for l in lines]
        diffs = [b2 - b1 for b1, b2 in zip(base_y, base_y[1:]) if b2 > b1]
        # smallest gap cluster = true leading (larger gaps hide blank lines)
        lead = min(_cluster(diffs, 0.8)) if diffs else 11.0
        p.leading = round(lead, 2)
        p._b1 = base_y[0] if base_y else None
        p._size1 = lines[0].spans[0].size if lines and lines[0].spans else 9.0
        runs = []
        total_lines = 1
        for i, ln in enumerate(lines):
            runs.extend(runs_from_spans(ln.spans))
            if i < len(lines) - 1:
                n_breaks = max(1, int(round((base_y[i + 1] - base_y[i]) / max(1.0, lead))))
                runs.append(Run(text="\n" * n_breaks, font=ln.spans[0].font,
                                size=ln.spans[0].size, color=ln.spans[0].color))
                total_lines += n_breaks
        p.runs = runs
        p._vis_lines = total_lines
        cell.paras = [p]
        t0, hh = _para_box(p)
        pad_top = max(0.0, round(t0 - rect[1], 1))
        p.space_before = 0.0
        cell.pad = (pad_top, cell.pad[1],
                    max(0.0, round(rect[3] - (t0 + hh), 1)), cell.pad[3])
    else:
        # Through the flow's own reader, not bare paragraph grouping: a panel
        # holds what a page holds -- typed lists, label/field rows, dot
        # leaders -- and y58's "Important Things to Know" panel came out as
        # ONE paragraph of eleven bullet items run together, 2x its height.
        blk = _mk_block(lines)
        cell.paras = [el for el in _to_flow([("blk", blk.bbox, blk)], minx, rect[2] - 4,
                                            forced=_text_column_edge(lines))
                      if isinstance(el, Para)]
        t0 = _para_box(cell.paras[0])[0] if cell.paras else rect[1]
        pad_top = max(0.0, round(t0 - rect[1], 1))
        end = _space_paras(cell.paras, rect[1] + pad_top)
        cell.pad = (pad_top, cell.pad[1], max(0.0, round(rect[3] - end, 1)),
                    cell.pad[3])
        for p in cell.paras:
            if p.align in ("left", "justify"):
                # From the CELL edge, as the writer reads a cell's indents
                # (it takes the left pad back off), and to the paragraph's
                # TEXT column: a hanging list item's box starts at its
                # marker, and measuring from there put y58's panel bullets
                # 9pt outside their panel's text.
                x = (p.bbox[0] if p.bbox else minx) - min(0.0, p.first_indent)
                p.left_indent = max(0.0, round(x - rect[0], 1))
    role = "code" if is_code else ("box" if (fill_rect or stroke_rect)
                                   else "quote")
    return TableEl(rows=[[cell]], col_widths=[rect[2] - rect[0]],
                   row_heights=[rect[3] - rect[1]], role=role, bbox=rect)


# An ornament on a box -- a numbered badge in a callout's corner (y59's 11pt
# circles), an icon beside its heading -- cannot ride in the box: a one-cell
# table holds paragraphs, and stacked after the box as a picture it spends
# its own height again (seven 15pt lines a page on y59). Up to twice the
# glyph bound, wholly inside a built box, it is left to the box's shading,
# as a smaller ornament anywhere already is (_is_glyphlike).
BOX_ORNAMENT_MAX = 2 * GLYPH_MAX


def _ornament_on_box(d: DrawCmd, elements) -> bool:
    x0, y0, x1, y1 = d.bbox
    if (x1 - x0) > BOX_ORNAMENT_MAX or (y1 - y0) > BOX_ORNAMENT_MAX:
        return False
    return any(isinstance(e, TableEl) and e.role in ("box", "cards") and e.bbox
               and contains(e.bbox, d.bbox, 0.5) for e in elements)


def build_figure(cl_ds: List[DrawCmd], blocks, images, consumed, page: PageIR) -> FigureEl:
    bb = None
    for d in cl_ds:
        bb = bbox_union(bb, d.bbox)
    # Absorption thresholds are frozen against the SEED geometry. Deriving them
    # from `bb` while `bb` is being grown is positive feedback: absorbing a line
    # widens the box, which loosens the test, which absorbs more lines. That
    # loop was measured growing a 490x2pt seed to 103x its area.
    seed = bb
    seed_w = max(1.0, seed[2] - seed[0])
    seed_area = max(1.0, bbox_area(seed))
    page_area = max(1.0, page.width * page.height)
    max_area = min(MAX_FIG_GROWTH * seed_area, MAX_FIG_PAGE_FRAC * page_area)
    for _ in range(6):
        changed = False
        ex = _expand(bb, 14)
        for ln in _all_lines(blocks):
            if id(ln) in consumed:
                continue
            lb = ln.bbox
            if bbox_overlap(lb, ex) > 0:
                inside = bbox_overlap(lb, bb) > 0.8 * max(1e-6, bbox_area(lb))
                small = (lb[3] - lb[1]) <= 45 and \
                    (lb[2] - lb[0]) <= max(1.06 * seed_w, 60)
                if inside or small:
                    cand = bbox_union(bb, lb)
                    if not inside and bbox_area(cand) > max_area:
                        continue          # refuse to grow past the budget
                    bb = cand
                    consumed.add(id(ln))
                    changed = True
        for im in images:
            if getattr(im, "_consumed", False):
                continue
            if bbox_overlap(im.bbox, _expand(bb, 6)) > 0:
                bb = bbox_union(bb, im.bbox)
                im._consumed = True
                changed = True
        if not changed:
            break
    # A chart's axis ticks belong to it even where they stand further off
    # than the 14pt reach: c5_graphics' '100' / '50' / '0' end 15.4pt left of
    # the y-axis, stayed flow, and -- a picture cannot share a line with text
    # -- were stacked UNDER the chart as three paragraphs, 115pt that pushed
    # the whole page down. Only bare numbers beside the figure's own height,
    # measured from the figure as grown above: a tick does not reach further
    # ticks (chained, y59's callout badge numbers carried a mock-up page's
    # picture 160pt across the callouts beside it).
    ref = bb
    for ln in _all_lines(blocks):
        if id(ln) in consumed or not _AXIS_TICK_RE.match(ln.text.strip()):
            continue
        lb = ln.bbox
        cy = (lb[1] + lb[3]) / 2
        if not (ref[1] - 2 <= cy <= ref[3] + 2):
            continue
        if lb[2] >= ref[0] - AXIS_TICK_REACH and lb[0] <= ref[2] + AXIS_TICK_REACH:
            bb = bbox_union(bb, lb)
            consumed.add(id(ln))
    bb = (max(0, bb[0] - 2), max(0, bb[1] - 2),
          min(page.width, bb[2] + 2), min(page.height, bb[3] + 2))
    return FigureEl(page_no=page.number, clip=bb,
                    width=bb[2] - bb[0], height=bb[3] - bb[1])


# The tick labels build_figure takes from beside a chart: a bare number, a
# percentage or a currency amount, and no further off than an axis title's
# gutter (c5's stand 15.4pt off; 24pt leaves room for a wider face's ticks).
_AXIS_TICK_RE = re.compile(r"^[-+−–]?[$€£¥]?\d{1,7}(?:[.,]\d{1,3})*\s?[%kKmM]?$")
AXIS_TICK_REACH = 24.0


def _figure_in_budget(cl_ds, blocks, images, consumed, page, text_area):
    """build_figure, rolled back if it would rasterise too much of the page.

    Rasterising is the only irreversible decision in the pipeline: whatever a
    figure swallows stops being editable text, and no downstream stage can
    recover it. When a figure would eat more than MAX_FIG_TEXT_FRAC of a page's
    text, the classification is far likelier to be wrong than the page is to be
    genuinely that graphical -- so back it out and let the text flow.
    """
    before = set(consumed)
    before_img = [im for im in images if getattr(im, "_consumed", False)]
    fig = build_figure(cl_ds, blocks, images, consumed, page)
    eaten = sum(bbox_area(l.bbox) for l in _all_lines(blocks)
                if id(l) in consumed and id(l) not in before)
    if eaten > MAX_FIG_TEXT_FRAC * text_area:
        consumed.clear()
        consumed.update(before)
        keep = {id(i) for i in before_img}
        for im in images:
            if getattr(im, "_consumed", False) and id(im) not in keep:
                im._consumed = False
        return None
    return fig


# ------------------------------------------------------------------ main
def infer(ir: DocIR, anchored: bool = True,
          anchor_pictures: Optional[bool] = None) -> DocLayout:
    """DocIR -> DocLayout.

    The document's hyphenation evidence is built first and made current for
    the whole inference, so every line join -- paragraphs, cells, headers,
    merged flow -- resolves its line-end hyphen against the same vocabulary
    (see exactdoc.hyphen and _soft_join).

    `anchored`: the output profile positions graphics on the page (options
    capability "anchored"), so a slide's pictures leave the flow
    (`_deck_pages`). False keeps every graphic in the flow, as the Google Docs
    profile always has.

    `anchor_pictures`: a picture set on a text line, wrapped by a paragraph
    or printed into a margin leaves the flow for its own position
    (`_on_text_line`, `_wrapped_by_text`; options capability
    "anchor_pictures"); by default whatever `anchored` is.
    """
    token = hyphen.activate(hyphen.HyphenEvidence.from_ir(ir) if ir.pages else None)
    try:
        lay = _infer(ir, anchored,
                     anchored if anchor_pictures is None else anchor_pictures)
    finally:
        hyphen.deactivate(token)
    hyphen.mark_unhyphenated(lay)
    from .layout import iter_paras
    for p in iter_paras(lay):
        if getattr(p, "rtl", False):
            _balance_brackets(p.runs)
    return lay


# Brackets in right-to-left text, and why a paragraph pass follows the parser's
# per-line mirroring (parse_pdfium._visual_to_logical). A producer draws a
# bracket at an RTL level with its mirrored glyph; what the PDF's ToUnicode
# says for that glyph is the producer's choice (Word maps it to the logical
# character, a visual-order producer to the shape), and PDFium mirrors again
# inside a text object it judges right-to-left (probed: `ואר)` drawn as one
# string reads back `(ראו`) but not in a bracket's own object. So the
# character that arrives can be either, and no per-character rule recovers
# it: measured, y50 p1 read `)Pang, et al., 2002)` and `(Wang & Manning,
# 2012(`, y49 p1 `)להלן: "מחקר הבסיס")`, a synthetic Hebrew page `)ראו להלן(`.
#
# The paragraph does recover it. A bracket left unmatched by a depth scan is
# re-read by its SHAPE in the text: an opener has a space (or nothing, or an
# opening quote) before it and text after it; a closer has text before it and
# a space, punctuation or the end after it. An unmatched closer shaped like an
# opener opened something, and vice versa. A matched bracket is never touched,
# and neither is an unmatched one whose shape agrees with it -- a `1)` list
# marker, a parenthetical continuing from the previous page.
_BRACKET_PAIRS = (("(", ")"), ("[", "]"), ("{", "}"))
_OPEN_BEFORE = frozenset("([{\"'«“‘")
_CLOSE_AFTER = frozenset(".,;:!?)]}\"'»”’،؛")


def _balance_brackets(runs) -> int:
    """Flip mis-oriented brackets in one paragraph's runs; returns the count."""
    flat = [(i, k, ch) for i, r in enumerate(runs) if not r.is_tab
            for k, ch in enumerate(r.text)]
    if not any(ch in "()[]{}" for _, _, ch in flat):
        return 0
    text = "".join(ch for _, _, ch in flat)
    flips = 0
    for op, cl in _BRACKET_PAIRS:
        stack, stray = [], []
        for n, ch in enumerate(text):
            if ch == op:
                stack.append(n)
            elif ch == cl:
                if stack:
                    stack.pop()
                else:
                    stray.append(n)
        stray += stack
        for n in stray:
            prev = text[n - 1] if n else None
            nxt = text[n + 1] if n + 1 < len(text) else None
            opener = (prev is None or prev.isspace() or prev in _OPEN_BEFORE) \
                and nxt is not None and not nxt.isspace() and nxt not in _CLOSE_AFTER
            closer = prev is not None and not prev.isspace() \
                and prev not in _OPEN_BEFORE \
                and (nxt is None or nxt.isspace() or nxt in _CLOSE_AFTER)
            want = op if opener and not closer else cl if closer and not opener \
                else text[n]
            if want != text[n]:
                i, k, _ = flat[n]
                t = runs[i].text
                runs[i].text = t[:k] + want + t[k + 1:]
                text = text[:n] + want + text[n + 1:]
                flips += 1
    return flips


def _infer(ir: DocIR, anchored: bool = True,
           anchor_pictures: bool = True) -> DocLayout:
    lay = DocLayout(src_path=ir.path)
    lay.font_advances = getattr(ir, "font_advances", None) or {}
    if not ir.pages:
        return lay
    p0 = ir.pages[0]
    lay.page_w, lay.page_h = p0.width, p0.height
    n_pages = len(ir.pages)
    hf = detect_hf(ir)
    deck = _deck_pages(ir, hf) if anchored else frozenset()
    if deck and len(deck) == n_pages:
        # A deck has no running furniture to speak of: what repeats is each
        # slide's own text box (y34's deck title at 26-54pt, beside the slide
        # title at 62pt; its slide number beside a footer URL). As a header
        # part the 28pt title reached 66pt down a page whose body starts at
        # 62, every renderer pushed the slide's body below it, and each
        # slide's last line went over the page. Every slide keeps its own.
        hf = _no_furniture()
    groups = _size_groups(ir.pages)
    _measure_margins(lay, ir, hf, groups[0])
    # Pages of another size or orientation are measured on their own: a
    # landscape table page's 650pt lines must neither set a portrait page's
    # right margin nor be wrapped into its 468pt column (design audit B9).
    own_geometry = {}
    for grp in groups[1:]:
        g = DocLayout(page_w=grp[0].width, page_h=grp[0].height)
        _measure_margins(g, ir, hf, grp)
        for p in grp:
            own_geometry[p.number] = g
    if deck and len(deck) == n_pages:
        # A slide's flow has no footer part to protect (above), and its own
        # footer row sits where the source put it: y34's slide numbers end
        # 14.6pt above the paper's edge, under a 14pt reserve, so half a
        # point of flow drift sent one slide in two onto a page of its own.
        for g in [lay] + list(own_geometry.values()):
            g.margin_b = min(g.margin_b, DECK_MARGIN_B)
    _infer_body(lay, ir, hf, n_pages, own_geometry, deck, anchored,
                anchor_pictures)
    return lay


# Two page sizes closer than this in both dimensions are the same size. The
# nearest distinct sizes in common use, A4 and US Letter, differ by 16.7pt in
# width and 49.9pt in height; scanners and imposition software jitter a page
# by a point or two.
PAGE_SIZE_TOL = 3.0


def _size_groups(pages: List[PageIR]) -> List[List[PageIR]]:
    """Pages grouped by size, page 1's group first.

    A document of one size is one group holding `pages` itself, so everything
    measured over it is measured exactly as before.
    """
    groups: List[List[PageIR]] = []
    for p in pages:
        for g in groups:
            if abs(g[0].width - p.width) <= PAGE_SIZE_TOL and \
                    abs(g[0].height - p.height) <= PAGE_SIZE_TOL:
                g.append(p)
                break
        else:
            groups.append([p])
    if len(groups) == 1:
        return [pages]
    return groups


_NUMERIC_CELL = re.compile(r"^[£$€¥(]?[-−]?[\d,]+(\.\d+)?%?\)?$")
NUMERIC_EDGE_MIN = 20            # values in one right-aligned column
FIGURE_COLUMN_SHARE = 0.8        # blocks of figures that make a "column" a value column
FIGURE_COLUMN_MIN = 2           # figure columns that make a page's figures a table
NUMERIC_EDGE_TOL = 1.5           # pt; right-aligned values share their edge


def _figure_cluster(x0: float, blocks, is_figures) -> bool:
    """Do the blocks starting at `x0` (the column detector's 12pt cluster)
    hold figures, FIGURE_COLUMN_SHARE of them and at least FIGURE_COLUMN_MIN?"""
    members = [b for b in blocks if abs(b.bbox[0] - x0) < 12]
    figs = sum(1 for b in members if is_figures(b))
    return figs >= FIGURE_COLUMN_MIN and figs >= FIGURE_COLUMN_SHARE * len(members)


def _numeric_column_edge(body_lines, n_wide: int, page_w: float):
    """The right edge of a right-aligned column of figures that the wide-line
    estimate never sees, or None.

    A spreadsheet export has no prose to measure: y35 (Excel for Microsoft
    365, A4) prints a label column and two columns of rates, 2025/26 ending
    at x 387 and 2026/27 at 465, on all 14 pages. Its wide lines are labels
    welded to the first rate, so the content edge came out at 387 and the
    second column -- 348 figures -- fell outside the text column; the page
    was then read as two text columns, and 14 pages rendered as 15 with the
    figures stacked apart from their labels. A column of figures counts only
    where it outnumbers the wide lines, so a report's table hanging past its
    prose column cannot widen the prose.
    """
    xs = sorted(l.bbox[2] for _pg, l in body_lines
                if _NUMERIC_CELL.match(l.text.strip()))
    if len(xs) < NUMERIC_EDGE_MIN:
        return None
    clusters, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] <= NUMERIC_EDGE_TOL:
            cur.append(x)
        else:
            clusters.append(cur)
            cur = [x]
    clusters.append(cur)
    edges = [max(c) for c in clusters if len(c) >= max(NUMERIC_EDGE_MIN, n_wide)]
    edges = [e for e in edges if page_w - e >= 14.0]
    return max(edges) if edges else None


# A drawing at least this tall a share of its page spans it: page furniture
# (a margin rule, a frame edge), never the edge of the body.
PAGE_RULE_FRAC = 0.9


def _measure_margins(lay: DocLayout, ir: DocIR, hf: dict,
                     pages: List[PageIR]) -> None:
    """Set `lay`'s four margins from `pages`, which share `lay`'s page size."""
    sub_ir = ir if pages is ir.pages else DocIR(path=ir.path, pages=pages,
                                                    meta=ir.meta)
    # ---------- margins
    body_lines = []
    for p in pages:
        ct = hf["consumed_text"][p.number]
        for bi, b in enumerate(p.blocks):
            for l in b.lines:
                if (bi, id(l)) not in ct:
                    body_lines.append((p.number, l))
    left_edges = [l.bbox[0] for _, l in body_lines
                  if l.bbox[0] < 0.35 * lay.page_w]
    ml = _margin_cluster(left_edges, left=True)
    if ml is None:
        # Prefer a measurement of this document over the 1in assumption.
        ml = _margin_by_mass(left_edges, left=True)
    lay.margin_l = float(ml) if ml else 72.0
    gutter = _gutter_column(body_lines, lay.margin_l)
    if gutter is not None:
        # The column the text clusters on is the MAIN column; the page's
        # content starts at the gutter's left. Drawings keep being judged
        # against the main column (`_gutter_main`), exactly as before: the
        # rules beside a gutter's headings were margin furniture then and
        # are not flow now.
        lay._gutter_main = lay.margin_l
        lay.margin_l = gutter
    wide_x1 = [l.bbox[2] for _, l in body_lines
               if (l.bbox[2] - l.bbox[0]) >= 0.45 * lay.page_w and
               l.bbox[2] > 0.6 * lay.page_w]
    mr = _margin_cluster(wide_x1, left=False)
    # two-column pages: an inset full-width element can win the wide-line
    # estimate while the true content edge is the right column's flush
    # edge.  Only ever widens content (edge further right than mr).
    #
    # "Only ever widens" requires something to widen. When the wide-line
    # estimate is missing this used to adopt the two-column edge outright, and
    # a right-column edge is far to the LEFT of the page's content edge, so the
    # rule inverted: it narrowed the content instead of widening it. Measured
    # on y17_rfc9110, whose line geometry is identical under both parsers --
    # PyMuPDF's right edge clusters at 503.6, PDFium's chains to None, and the
    # widener then supplied 332.5 as the content edge. A 266pt content width
    # against a true 438pt re-wraps every paragraph in the document. y02 does
    # the same under PDFium at 353.7.
    #
    # With no estimate the caller already has a defensible answer below --
    # mirror the left margin -- which errs wide, and erring wide costs a little
    # under-wrapping rather than a document-wide re-flow.
    tc_edge = _two_column_right_edge(body_lines, lay.margin_l, lay.page_w)
    if tc_edge is not None and mr is not None and tc_edge > mr + 2.5:
        mr = tc_edge
    # Applied AFTER the widener, not before: the widener exists to rescue an
    # estimate that landed inside the true edge, and on y14_irs_fw9_form it
    # does exactly that -- cluster 402.8, 171.8pt inside, lifted to the right
    # column's flush edge. Checking first would throw that document into the
    # fallback and discard a correct answer the next line was about to supply.
    if _right_edge_misclustered(wide_x1, mr):
        mr = None
    # The document's own full-width rules can place the column edge where
    # the ragged-right text never reaches it in sufficient mass. Compared
    # against whichever estimate survives above -- the cluster, or the
    # mirror-the-left-margin fallback when there is none -- and only ever
    # widens content, the same one-way door as `_two_column_right_edge`.
    base_edge = mr if mr is not None else lay.page_w - lay.margin_l
    pages_lines = []
    for p in pages:
        ct = hf["consumed_text"][p.number]
        pages_lines.append([l for bi, b in enumerate(p.blocks) for l in b.lines
                            if (bi, id(l)) not in ct])
    rule_edge = _rule_right_edge(sub_ir, hf, lay.page_w, wide_x1,
                                 row_x1=_field_row_ends(pages_lines, lay.margin_l,
                                                        lay.page_w),
                                 body_boxes=[(pg, l.bbox) for pg, l in body_lines])
    if rule_edge is not None and rule_edge > base_edge + 2.5:
        mr = rule_edge
    # The same one-way door once more, from the lines that wrapped: the
    # column is at least as wide as the widest of them (WRAP_EDGE_* above).
    base_edge = mr if mr is not None else lay.page_w - lay.margin_l
    wrap_edge = _wrapped_right_edge(sub_ir, hf, lay.page_w)
    if wrap_edge is not None and wrap_edge > base_edge + WRAP_EDGE_MIN_GAIN:
        mirror = lay.page_w - lay.margin_l
        mr = mirror if wrap_edge <= mirror <= wrap_edge + WRAP_EDGE_MIRROR_PT \
            else wrap_edge + 0.5
    # And once more from the figures: a spreadsheet's right-aligned value
    # column is the content's edge even where no line is wide.
    base_edge = mr if mr is not None else lay.page_w - lay.margin_l
    num_edge = _numeric_column_edge(body_lines, len(wide_x1), lay.page_w)
    if num_edge is not None and num_edge > base_edge + WRAP_EDGE_MIN_GAIN:
        mr = num_edge + 0.5
    lay.margin_r = round(lay.page_w - mr, 1) if mr is not None else lay.margin_l
    lay.margin_r = max(14.0, lay.margin_r)
    # Every row candidate in the document, for `_row_pairs`' cross-page
    # column evidence. Measured against the content edges, as the single-
    # column flow sees them.
    lay._row_evidence = _doc_row_evidence(pages_lines, lay.margin_l,
                                          lay.page_w - lay.margin_r)

    band1_h = max((d.bbox[3] for _, d in hf["band_first"]), default=0) \
        if hf["band_first"] else 0
    tops, bots = [], []
    for p in pages:
        ct = hf["consumed_text"][p.number]
        cd = hf["consumed_draw"][p.number]
        ys = [l.bbox[1] for bi, b in enumerate(p.blocks) for l in b.lines
              if (bi, id(l)) not in ct]
        ye = [l.bbox[3] for bi, b in enumerate(p.blocks) for l in b.lines
              if (bi, id(l)) not in ct]
        # A drawing that covers the whole sheet says nothing about where the
        # body starts. RFC 9110 paints a page-sized #e9e9e9 rect (a clipped
        # code-block background) on some pages, and the single most extreme
        # page set margin_t to its 10pt floor -- `pgMar top=200tw` under a
        # header at 35pt (audit B26). Nor does a rule running the page's full
        # height (pleading paper's margin rules: y63 draws three, y 0 to 792,
        # on every page): it set the top margin to 10pt and the bottom to 14,
        # under a two-line running head and a two-line footer, and each
        # page's body was pushed past its foot (5 pages rendered 9).
        draws = [d for di, d in enumerate(p.drawings) if di not in cd and
                 bbox_area(d.bbox) < PAGE_COVER_FRAC * p.width * p.height and
                 (d.bbox[3] - d.bbox[1]) < PAGE_RULE_FRAC * p.height]
        ys += [d.bbox[1] for d in draws]
        ye += [d.bbox[3] for d in draws]
        if ys and not (p.number == 1 and band1_h > 45):
            tops.append(min(ys))
        if ye:
            bots.append(max(ye))
    lay.margin_t = round(max(10.0, min(min(tops) if tops else 54.0, 120.0)), 1)
    max_bot = max(bots) if bots else lay.page_h - 54
    lay.margin_b = round(max(14.0, min(72.0, lay.page_h - max_bot - 16.0)), 1)


# --- gutter columns -----------------------------------------------------------
# A CV set by rendercv, moderncv or Typst puts each entry's dates in a narrow
# left column beside the entry's first line: 'Sept 2018 – May 2023' right-
# aligned to 167pt, 'Princeton University, PhD...' from 176.5. The margin
# cluster sees only the main column (every line of it starts at 176.5) and
# made THAT the page's left edge, so each date line became one paragraph
# starting at the main column -- the date inlined into the role, the line
# 100pt too long, wrapping: y44 went 3 -> 4 pages, and its name and contact
# line were pushed 126pt right with it.
#
# The evidence is a line whose label ends in the white left of the main
# column and whose text resumes AT the main column's edge, on at least two
# lines whose labels share an edge (right-aligned dates end together, left-
# aligned ones start together). A hanging list marker has the same shape and
# is excluded by width: the gutter must be at least SBS_MIN_SIDE_PT wide,
# where an outdented "1." or a section number takes 10-30pt.
GUTTER_EDGE_TOL = 1.5      # pt: the text resumes AT the main column
GUTTER_MIN_GAP = 3.0       # pt of white between a label and the main column
GUTTER_LABEL_EDGE = 2.0    # pt: labels of one column share an edge
GUTTER_MIN_ROWS = 2


def _gutter_column(body_lines, margin_l: float) -> Optional[float]:
    """The page group's true left edge when it has a gutter column, else None.

    Marks each label line with `_gutter` = (index of the first main-column
    span, label edge x, main column x, right-aligned?) for para_from_lines."""
    hits = []
    for _pg, ln in body_lines:
        if not ln.horizontal or len(ln.spans) < 2 or getattr(ln, "rtl", False) or \
                ln.bbox[0] > margin_l - SBS_MIN_SIDE_PT:
            continue
        k = next((i for i, s in enumerate(ln.spans)
                  if abs(s.bbox[0] - margin_l) <= GUTTER_EDGE_TOL), None)
        if not k:
            continue
        label = [s for s in ln.spans[:k] if s.text.strip()]
        if not label:
            continue
        x1 = max(ink_extent(s)[1] for s in label)
        if margin_l - x1 < GUTTER_MIN_GAP:
            continue
        hits.append((ln, k, min(ink_extent(s)[0] for s in label), x1,
                     max(s.bbox[2] for s in ln.spans[:k])))
    if len(hits) < GUTTER_MIN_ROWS:
        return None
    rights = sorted(h[4] for h in hits)
    lefts = sorted(h[2] for h in hits)
    if rights[-1] - rights[0] <= GUTTER_LABEL_EDGE:
        right_al = True
    elif lefts[-1] - lefts[0] <= GUTTER_LABEL_EDGE:
        right_al = False
    else:
        return None
    stop = sorted(h[3] for h in hits)[len(hits) // 2]
    for ln, k, lx0, _x1, _r in hits:
        ln._gutter = (k, stop if right_al else lx0, margin_l, right_al)
    # A main-column line is LEFT-aligned at the main column, however far
    # from the page's new left edge it starts: a one-line bullet reaching the
    # right margin otherwise reads as right-aligned (y44's 'Created on-device
    # ...' set flush right with a 126pt indent and wrapped).
    for _pg, ln in body_lines:
        if abs(ln.bbox[0] - margin_l) <= GUTTER_EDGE_TOL:
            ln._main_col = True
    left = [ln.bbox[0] for _pg, ln in body_lines if ln.bbox[0] < margin_l - 1.0]
    return min(left) if left else None


def _gutter_para(p: Para, lines: List[Line], col_l: float) -> None:
    """Rewrite a paragraph opened by a gutter label as label TAB text, hanging
    at the main column -- the word processor's own form of a dated entry."""
    k, edge, main_x, right_al = lines[0]._gutter
    spans0 = lines[0].spans
    ref = spans0[k]

    def tab():
        return Run(text="\t", font=ref.font, size=ref.size, color=ref.color, is_tab=True)

    label = [r for r in runs_from_spans(spans0[:k]) if r.text]
    while label and not label[-1].text.strip():
        label.pop()
    if label:
        label[-1].text = label[-1].text.rstrip(" ")
    runs = ([tab()] if right_al else []) + label + [tab()] + \
        runs_from_spans(spans0[k:])
    for j in range(1, len(lines)):
        _soft_join(runs, lines[j].text, dehyphenate=False)
        runs.extend(runs_from_spans(lines[j].spans))
    hang = round(main_x - col_l, 1)
    p.runs = runs
    p.align = "left"
    p.left_indent = hang
    p.right_indent = 0.0
    if right_al:
        p.first_indent = -hang
        p.tab_stops = [(round(edge - col_l, 1), "right"), (hang, "left")]
    else:
        p.first_indent = round(edge - main_x, 1)
        p.tab_stops = [(hang, "left")]


def _geometry(lay: DocLayout, own: Optional[DocLayout]) -> DocLayout:
    """`lay` with a page's own size and margins, or `lay` itself."""
    if own is None:
        return lay
    out = replace(lay, page_w=own.page_w, page_h=own.page_h,
                  margin_l=own.margin_l, margin_r=own.margin_r,
                  margin_t=own.margin_t, margin_b=own.margin_b)
    # Row evidence is measured against a geometry's content edges, so a page
    # of another size reads its own group's (see _measure_margins).
    out._row_evidence = getattr(own, "_row_evidence", None)
    out._gutter_main = getattr(own, "_gutter_main", None)
    return out


def _infer_body(lay: DocLayout, ir: DocIR, hf: dict, n_pages: int,
                own_geometry: Dict[int, DocLayout],
                deck: frozenset = frozenset(),
                anchored: bool = True, anchor_pictures: bool = True) -> None:
    # Was the source set with hyphenation? This was `>= 6` hyphenated line
    # pairs anywhere, a count that cannot tell a hyphenating document from a
    # long one full of compounds: SP 800-63B reached it on `Out-of-/Band` and
    # friends (1 attested break against 17 attested compounds) and its title
    # rendered as `Publica-tion`. The document's vocabulary answers the
    # question that was meant -- see hyphen.HyphenEvidence.hyphenates.
    ev = hyphen.current()
    lay.hyphenated = bool(ev is not None and ev.hyphenates)

    # ---------- headers/footers
    rl, rd = hf["rep_lines"], hf["rep_draws"]
    roles = hf["line_roles"]

    def zs(pg, zone):
        zones = (zone, "band1") if zone == "top" else (zone,)
        a = [(z, b, l) for (z, b, l) in rl.get(pg, []) if z in zones]
        b = [(z, d_i, d) for (z, d_i, d) in rd.get(pg, []) if z == zone]
        return a, b

    def page_sig(pg, zone):
        """What a part built from page `pg` would say, numbers normalised."""
        a, b = zs(pg, zone)
        s = [(_role_text(ln, roles.get(id(ln))), _hf_anchor(ln.bbox, lay.page_w))
             for _, _, ln in sorted(a, key=lambda t: (round(t[2].bbox[1] / 3),
                                                      t[2].bbox[0]))]
        s += [(d.shape, round(d.bbox[1] / 3)) for _, _, d in
              sorted(b, key=lambda t: (t[2].bbox[1], t[2].bbox[0]))]
        return tuple(s)

    def modal_page(zone, pages):
        """(signature, first page carrying it, how many pages carry it)."""
        sigs = [(pg, page_sig(pg, zone)) for pg in pages]
        cnt = Counter(s for _, s in sigs if s)
        if not cnt:
            return None, None, 0
        modal, c = cnt.most_common(1)[0]     # ties: the earliest page's
        return modal, next(pg for pg, s in sigs if s == modal), c

    # The default parts are built from the page carrying the MODAL furniture
    # signature, not from page 2 (audit B1). NIST SP 800-171's page 2 is its
    # title page: `detect_hf` found the running head on 111 pages, consumed it
    # from the body, and then no header or footer part was written at all --
    # the running head and the page numbers vanished from every page. On every
    # document whose page 2 carries the common furniture (all 16 gated ones)
    # the modal page IS page 2 and nothing changes.
    if n_pages >= 2:
        later_pages = list(range(2, n_pages + 1))
        parity = hf.get("parity") or {}
        for zone in ("top", "bot"):
            modal, rep, _ = modal_page(zone, later_pages)
            if rep is None and zone == "top" and hf["band_def"]:
                rep = 2                     # a strip band with no text in it
            even_rep = None
            if n_pages >= PARITY_MIN_PAGES:
                # Verso/recto furniture: each parity has its own dominant
                # signature, and they differ (the page number swaps sides, or
                # the text alternates). DOCX states that directly with
                # w:evenAndOddHeaders; the default part is the odd one.
                cls = {par: [pg for pg in later_pages
                             if parity.get(pg, pg % 2) == par] for par in (0, 1)}
                m_o, r_o, c_o = modal_page(zone, cls[1])
                m_e, r_e, c_e = modal_page(zone, cls[0])
                if m_o and m_e and m_o != m_e and \
                        c_o >= max(3, 0.6 * len(cls[1])) and \
                        c_e >= max(3, 0.6 * len(cls[0])):
                    rep, even_rep = r_o, r_e
            if rep is None:
                continue
            a, b = zs(rep, zone)
            part = build_hf_part(a, b, ir.pages[rep - 1], lay.margin_l,
                                 lay.margin_r, roles,
                                 band=hf["band_def"] if zone == "top" else None)
            even = None
            if even_rep is not None:
                a, b = zs(even_rep, zone)
                even = build_hf_part(a, b, ir.pages[even_rep - 1], lay.margin_l,
                                     lay.margin_r, roles,
                                     band=hf["band_def"] if zone == "top" else None)
                lay.even_odd = True
            if zone == "top":
                lay.header_default, lay.header_even = part, even
            else:
                lay.footer_default, lay.footer_even = part, even
    tl1, td1 = zs(1, "top")
    bl1, bd1 = zs(1, "bot")
    # cover band becomes BODY content in its own section (deterministic in
    # both Word and Google Docs; header push behavior varies across renderers)
    if hf["band_first"]:
        band_bb = None
        for _, d in hf["band_first"]:
            band_bb = bbox_union(band_bb, d.bbox)
        blines = [ln for (z, _, ln) in tl1 if z == "band1" or ln.bbox[3] <= band_bb[3] + 2]
        lay.cover_band = build_band_table(hf["band_first"], blines, lay.margin_l,
                                          lay.content_w, roles)
        lay.cover_top = round(max(0.0, band_bb[1]), 1)
        tl1 = [(z, b, l) for (z, b, l) in tl1 if l.bbox[3] > band_bb[3] + 2]
    hdr1 = build_hf_part(tl1, td1, ir.pages[0], lay.margin_l, lay.margin_r, roles)
    ftr1 = build_hf_part(bl1, bd1, ir.pages[0], lay.margin_l, lay.margin_r, roles)

    def sig(part):
        if part is None:
            return None
        s = []
        for el in part.elements:
            if isinstance(el, Para):
                s.append(("p", _norm_text(el.text)))
            elif isinstance(el, TableEl):
                s.append(("t", _norm_text(" ".join(
                    p.text for row in el.rows for c in row if c for p in c.paras))))
        return tuple(s)

    if n_pages >= 2:
        if sig(hdr1) != sig(lay.header_default) or sig(ftr1) != sig(lay.footer_default):
            lay.different_first = True
            lay.header_first = hdr1
            # Page 1 states its own footer, including stating none: a cover
            # page that prints no folio must not be given "PAGE 1" (y02). This
            # used to fall back to the default footer.
            lay.footer_first = ftr1
    else:
        lay.header_default = hdr1
        lay.footer_default = ftr1

    # Running-head sections: varying furniture stated per section.
    rh = _running_head_sections(ir, hf, lay, zs, roles) if n_pages >= 3 else []
    vl = hf.get("var_lines") or {}

    # Page-numbering sections (audit B3): printed numbers that differ from the
    # physical index -- roman front matter, a restart at 1, a slip opinion's
    # per-opinion numbering -- are live PAGE fields whose section states where
    # the count starts and in which format.
    # A section costs a section-break paragraph at a seam, so none is opened
    # unless an emitted part actually shows the number.
    all_parts = [lay.header_default, lay.header_even, lay.header_first,
                 lay.footer_default, lay.footer_even, lay.footer_first]
    all_parts += [p for _, parts, _ in rh for p in parts.values()]
    shows_number = any(_part_has_page_field(p) for p in all_parts)
    num_secs = [HFSection(start_page=s, num_start=v, num_fmt=f)
                for s, f, v in hf.get("num_sections") or []] \
        if shows_number else []
    if len(num_secs) > 1 and num_secs[0].num_fmt is None:
        # An unnumbered lead-in (cover, title page, notices) before numbered
        # front matter. When none of its pages after the first carries any
        # furniture it is written as a section with empty parts, so the
        # running head does not appear on the title page; page 1 keeps its
        # own first-page parts either way.
        end = num_secs[1].start_page
        if end > 2 and not any(rl.get(pg) or rd.get(pg) or vl.get(pg)
                               for pg in range(2, end)):
            num_secs[0].blank = True
    # Merge the two kinds of section start: one DOCX section per start page.
    by_start = {s.start_page: s for s in num_secs}
    for start, parts, title_pg in rh:
        s = by_start.setdefault(start, HFSection(start_page=start))
        s.parts, s.title_pg = parts, title_pg
    if by_start and 1 not in by_start:
        by_start[1] = HFSection(start_page=1)
    lay.hf_sections = [by_start[k] for k in sorted(by_start)]
    if len(lay.hf_sections) == 1 and lay.hf_sections[0].parts is None and \
            lay.hf_sections[0].num_fmt is None:
        lay.hf_sections = []
    if anchored:
        _header_gutter(lay, hf.get("gutter") or {}, n_pages)

    # The body starts where the source body starts in every renderer (audit
    # B26). Measured in the canonical LibreOffice: the body begins at
    # max(top margin, header distance + header height) -- 47pt for a 12pt
    # header at 35pt under a 10pt margin -- and ends at
    # page height - max(bottom margin, footer distance + footer height). Every
    # body position is computed from margin_t, so a margin inside the header
    # displaced every page's content by the difference: y17 was written with
    # `pgMar top=200tw` under a header at 35pt, 37pt of drift on 193 pages.
    _fit_footers_below_body(ir, hf, lay, rh)
    heads = [lay.header_default, lay.header_even]
    feet = [lay.footer_default, lay.footer_even]
    for _, parts, _ in rh:
        heads += [parts.get("header"), parts.get("header_even")]
        feet += [parts.get("footer"), parts.get("footer_even")]
    top_need = max((p.distance + _hf_extent(p) for p in heads
                    if p is not None), default=0.0)
    bot_need = max((p.distance + _hf_extent(p) for p in feet
                    if p is not None), default=0.0)
    # every page geometry carries the same parts (pages of another size get
    # their own measured margins, and the same floor)
    for g in [lay] + list({id(g): g for g in own_geometry.values()}.values()):
        if top_need > g.margin_t:
            g.margin_t = math.ceil(top_need * 10) / 10
        if bot_need > g.margin_b:
            g.margin_b = math.ceil(bot_need * 10) / 10

    # ---------- per-page content
    body_size = _body_font_size(ir, hf)
    doc_lay = lay
    prev_notes = False
    headed_carry = None     # (column xs, row pitch) of a headed table cut by a page
    pages_by_no = {pg.number: pg for pg in ir.pages}   # a cut table's next page
    for p in ir.pages:
        own = own_geometry.get(p.number)
        lay = _geometry(doc_lay, own)
        content_w = lay.content_w
        # side-margin furniture is judged against the main column when the
        # page group has a gutter column (_gutter_column), as it was before
        furniture_l = getattr(lay, "_gutter_main", None) or lay.margin_l
        pl = PageLayout(number=p.number)
        if own is not None:
            pl.page_w, pl.page_h = own.page_w, own.page_h
            pl.margins = (own.margin_l, own.margin_r, own.margin_t, own.margin_b)
        ct = hf["consumed_text"][p.number]
        cd = set(hf["consumed_draw"][p.number])

        blocks: List[TextBlock] = []
        for bi, b in enumerate(p.blocks):
            keep = [l for l in b.lines if (bi, id(l)) not in ct]
            if keep:
                bb = None
                for l in keep:
                    bb = bbox_union(bb, l.bbox)
                blocks.append(TextBlock(lines=keep, bbox=bb))

        consumed: set = set()

        # underline pre-pass: thin short hlines hugging a text baseline
        for di, d in enumerate(p.drawings):
            if di in cd or d.shape != "hline":
                continue
            if (d.bbox[3] - d.bbox[1]) > 2.2:
                continue
            dw = d.bbox[2] - d.bbox[0]
            hit = False
            for ln in _all_lines(blocks):
                for s in ln.spans:
                    if s.bbox[0] - 2.5 <= d.bbox[0] and d.bbox[2] <= s.bbox[2] + 2.5 \
                            and -1.0 <= d.bbox[1] - s.origin[1] <= 3.5 and (
                                dw <= 0.6 * content_w or
                                dw >= UNDERLINE_SPAN_SHARE * (s.bbox[2] - s.bbox[0])):
                        # Past 0.6 of the column only as the span's own
                        # underline: y63's underlined heading "Whether the
                        # Amount Sought is Reasonable" draws a 309.8pt rule
                        # under a 310pt span in a 504pt column. As a rule
                        # element it went into the flow out of order and the
                        # heading behind it took a 539pt space_before.
                        s._ul = True
                        hit = True
            if hit:
                cd.add(di)

        elements: List[Any] = []
        draws = [(i, d) for i, d in enumerate(p.drawings)
                 if i not in cd and d.opacity > 0.05]
        cuts = _split_lines_at_box_edges(blocks, [d.bbox for _, d in draws if _box_candidate(d)])
        # This runs before drawing clustering because a row-regular table is
        # otherwise split into alternating filled-card clusters and bare flow
        # paragraphs.  It has no side effects until the entire segment passes.
        striped = _regular_striped_table_segment(draws, blocks, consumed)
        if striped is not None:
            striped_table, striped_draws = striped
            elements.append(striped_table)
            cd.update(striped_draws)
            draws = [(i, d) for i, d in draws if i not in striped_draws]
        if headed_carry is not None:
            # A headed table that ran to the foot of the last page continues
            # here when this page OPENS with rows in its columns (x10's
            # 'March' row, alone at the top of page 2).
            free = [ln for ln in _all_lines(blocks)
                    if id(ln) not in consumed and ln.horizontal]
            if free:
                xs_c, pitch_c = headed_carry
                cont = _headed_body(xs_c, min(ln.bbox[1] for ln in free), pitch_c,
                                    free, consumed, first_gap=0.5)
                if cont is not None:
                    elements.append(cont)
        leftover = []
        rule_floats = []        # vertical rules drawn behind the text (below)
        page_text_area = sum(bbox_area(l.bbox) for l in _all_lines(blocks)) or 1.0
        clusters = _clusters(draws)
        # Fill-tiled tables first: their row bands are separate clusters,
        # and each alone reads as cards, bars or a figure.
        for band in _tile_bands(clusters, blocks, consumed):
            before = set(consumed)
            el = build_grid_table([it for c in band for it in c], blocks,
                                  consumed, tiled=True)
            if el is not None and len(band) == 1 and not _mostly_texted(el):
                # One cluster of tiles is a table only if its cells hold the
                # text: y59's mock-up notice page (tiles standing for a
                # page's panels) built two tables of empty cells
                consumed.clear()
                consumed.update(before)
                el = None
            if el is not None:
                elements.append(el)
                done = {id(c) for c in band}
                clusters = [c for c in clusters if id(c) not in done]
        for cl in clusters:
            if len(cl) == 1:
                leftover.append(cl[0])
                continue
            kind = _classify_cluster(cl)
            el = None

            def _fig():
                return _figure_in_budget([d for _, d in cl], blocks, p.images,
                                         consumed, p, page_text_area)

            if kind == "figure":
                el = _fig()
            elif kind == "grid":
                el = build_grid_table(cl, blocks, consumed) or _fig()
            elif kind == "cards":
                el = build_headed_table(cl, blocks, consumed) or \
                    build_cards_table(cl, blocks, consumed)
            elif kind == "stripes":
                el = build_stripes_table(cl, blocks, consumed) or _fig()
            elif kind == "boxlike":
                frame = next(d for _, d in cl if d.fill and d.shape == "rect")
                if _blank_picture_frame(frame, p.images):
                    # the frame draws nothing, and the hairlines on its
                    # picture's edges are the picture's border (y36 p16: a
                    # 0.1pt rule down the screenshot's left side, which as
                    # loose ink seeded a figure over half the page)
                    leftover.extend(it for it in cl if it[1] is not frame and
                                    not any(contains(im.bbox, it[1].bbox, 1.0)
                                            for im in p.images))
                    continue
                el = build_box(cl, blocks, consumed)
                if el is None and len(cl) >= 4:
                    el = _fig()
            else:
                leftover.extend(cl)
            if el is not None:
                elements.append(el)
            elif kind != "loose":
                leftover.extend(cl)   # budget refused it: fall back to flow

        # booktabs groups among leftover long hlines
        hl = [(i, d) for i, d in leftover if d.shape == "hline"
              and (d.bbox[2] - d.bbox[0]) >= 60]
        groups = defaultdict(list)
        for i, d in hl:
            groups[(round(d.bbox[0] / 8), round(d.bbox[2] / 8))].append((i, d))
        used = set()
        for key, grp in groups.items():
            gys = sorted(d.bbox[1] for _, d in grp)
            short_group = len(grp) >= 2 and gys[-1] - gys[0] < 320
            # A group inside the span bound is read whole, as it always was:
            # cut at its prose, lshort's example frames (code beside its
            # framed output, y22 p60) became two-column tables of code.
            subs = [grp] if short_group else _rule_runs_by_text(grp, blocks, consumed)
            for sub in subs:
                if len(sub) < 2:
                    continue
                foot = _open_foot(sub, blocks, consumed, *_next_page_opening(
                    pages_by_no.get(p.number + 1), hf)) if len(sub) == 2 else None
                if foot is not None:
                    # A table the page break cut (see _open_foot). Its body
                    # is bounded by no rule, so -- like a long booktabs
                    # head's -- it must hold its own lines.
                    before = set(consumed)
                    t = build_rules_table([d for _, d in sub], blocks, consumed,
                                          bottom=foot)
                    if t is not None and not _cells_hold_lines(t):
                        consumed.clear()
                        consumed.update(before)
                        t = None
                    if t is not None:
                        elements.append(t)
                        used.update(i for i, _ in sub)
                        continue
                ys = sorted(d.bbox[1] for _, d in sub)
                long_head = not (ys[-1] - ys[0] < 320 or _ruled_rows(ys)) and \
                    _booktabs_head(ys)
                # A group the span bound refused is read again only as tables
                # that state themselves -- ruled rows, or a booktabs head:
                # cut from a figure's same-length strokes (lshort's arrows,
                # y22 p106), two rules alone made a "table" of its code.
                if not short_group and not (
                        (_ruled_rows(ys) or _booktabs_head(ys)) and
                        _bands_texted(sub, blocks, consumed)):
                    continue
                if ys[-1] - ys[0] < 320 or _ruled_rows(ys) or long_head:
                    before = set(consumed)
                    t = build_rules_table([d for _, d in sub], blocks, consumed)
                    if t is not None and long_head and not _cells_hold_lines(t):
                        consumed.clear()
                        consumed.update(before)
                        t = None
                    if t is not None:
                        elements.append(t)
                        used.update(i for i, _ in sub)
        leftover = [(i, d) for i, d in leftover if i not in used]

        still = []
        for i, d in leftover:
            # A box, filled OR STROKED: a callout is often an unfilled
            # rectangle around text (measured: a 481x412pt 0.75pt #333333
            # rect around eight paragraphs). The fill-only test below let
            # that rect fall through every later branch and drop silently
            # -- the text survived, the box did not.
            if d.shape == "rect" and (d.fill or d.stroke) \
                    and (d.bbox[2] - d.bbox[0]) > 30 \
                    and (d.bbox[3] - d.bbox[1]) > 10 \
                    and not _blank_picture_frame(d, p.images):
                el = build_box([(i, d)], blocks, consumed)
                if el is not None:
                    el.left_indent = max(0.0, round(d.bbox[0] - lay.margin_l, 1))
                    elements.append(el)
                    continue
            still.append((i, d))
        leftover = still

        # Producers draw one quote bar as several stacked vline segments
        # (measured: 403 segments for 62 bars on the report that motivated
        # the threshold below). Each segment would claim its own slice of
        # the block and cut one quote into as many stacked one-cell tables,
        # so merge segments that share an x-centre and touch vertically
        # into a single bar before the quote test sees them.
        vbar_idx = {i for i, d in leftover if d.shape == "vline"
                    and (d.bbox[3] - d.bbox[1]) >= 16}
        if vbar_idx:
            bars = sorted((d for i, d in leftover if i in vbar_idx),
                          key=lambda d: ((d.bbox[0] + d.bbox[2]) / 2,
                                         d.bbox[1]))
            segs = []
            for d in bars:
                if segs:
                    hb = segs[-1].bbox
                    if abs((d.bbox[0] + d.bbox[2]) / 2
                           - (hb[0] + hb[2]) / 2) <= 1.5 \
                            and d.bbox[1] - hb[3] <= 3.0:
                        segs[-1] = replace(segs[-1], bbox=(
                            min(hb[0], d.bbox[0]), min(hb[1], d.bbox[1]),
                            max(hb[2], d.bbox[2]), max(hb[3], d.bbox[3])))
                        continue
                segs.append(d)
            leftover = [(i, d) for i, d in leftover if i not in vbar_idx] + \
                [(min(vbar_idx), d) for d in segs]

        for i, d in leftover:
            if d.shape == "vline" and (d.bbox[3] - d.bbox[1]) >= 16 and \
                    max(d.width, d.bbox[2] - d.bbox[0]) >= 1.2:
                # 1.2, not 1.8: the qualifier is the text this rule marks,
                # not the rule's own weight. A real report's quote bars are
                # 1.5pt wide with a 0.75pt stroke -- 62 of them, every one
                # rejected by the old 1.8 floor, 6 then rasterised as tall
                # pictures that each consumed a ~300pt line of body height
                # and 56 dropped outright (defect catalogue #5,
                # live-verified). A vline this tall that carries text on
                # its right is a quote bar; a vline that marks nothing
                # falls through to `_take_lines_in` returning empty.
                zone = (d.bbox[2], d.bbox[1] - 2,
                        d.bbox[2] + min(0.9 * content_w, 500), d.bbox[3] + 2)
                probe = set(consumed)
                lines = _take_lines_in(blocks, zone, probe, mode="overlap")
                # Text to the right is necessary, not sufficient: a margin
                # rule beside the whole body has text to its right on every
                # page. Defect catalogue #12.
                if lines and _is_quote_bar(d.bbox, lines, p.drawings):
                    consumed.update(id(l) for l in lines)
                    bb = d.bbox
                    for l in lines:
                        bb = bbox_union(bb, l.bbox)
                    minx = min(l.bbox[0] for l in lines)
                    cell = _cell_from_lines(sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])),
                                            (d.bbox[0], bb[1], bb[2], bb[3]))
                    cell.borders = {"left": (max(1.5, d.bbox[2] - d.bbox[0]),
                                             d.fill or d.stroke or "#000000")}
                    cell.pad = (0.5, round(minx - d.bbox[2], 1), 0.5, 2.0)
                    if cell.paras:
                        # The cell's text starts 0.5pt below the table top,
                        # so the table must start where the first line's
                        # box does, not where the bar does. A bar drawn
                        # beside the text's x-height (x11: from 243.8, its
                        # first line box from 241.5) put every quote line
                        # 2.8pt low and everything after it with them.
                        t0 = _para_box(cell.paras[0])[0]
                        if t0 - 0.5 < bb[1]:
                            bb = (bb[0], round(t0 - 0.5, 1), bb[2], bb[3])
                    qt = TableEl(rows=[[cell]], col_widths=[bb[2] - d.bbox[0]],
                                 row_heights=[None], role="quote", bbox=bb)
                    # Column-relative bar x, so a writer that renders quotes
                    # as bordered PARAGRAPHS (the Google Docs path) can pin
                    # every paragraph's indent to it and draw one continuous
                    # bar. Table indents elsewhere are column-relative by
                    # convention; the quote table used to carry none.
                    qt.left_indent = max(0.0, round(d.bbox[0] - lay.margin_l, 1))
                    elements.append(qt)
                    continue
                if lines:
                    # A rule beside text that is not its quote bar is a
                    # margin or frame line. Before this test it became a
                    # quote; it must not fall through to the stray-shape
                    # branch below instead and be rasterised as a strip
                    # that spends body height.
                    continue
            if d.shape == "hline" and (d.bbox[2] - d.bbox[0]) >= 0.3 * content_w:
                r = RuleEl(width_pct=min(100.0, 100 * (d.bbox[2] - d.bbox[0]) / content_w),
                           thickness=max(0.5, d.width or (d.bbox[3] - d.bbox[1])),
                           color=d.stroke or d.fill or "#000000",
                           length=round(d.bbox[2] - d.bbox[0], 1),
                           left_indent=max(0.0, round(d.bbox[0] - lay.margin_l, 1)))
                r._bbox = d.bbox
                elements.append(r)
                continue
            if _is_glyphlike(d):
                continue        # stray ornament: not worth rasterising a region for
            if _ornament_on_box(d, elements):
                continue
            if anchored and d.shape == "vline" and \
                    (d.bbox[3] - d.bbox[1]) >= VLINE_FLOAT_MIN_FRAC * p.height and \
                    (d.fill and bbox_area(d.bbox) > 400):
                # A vertical rule that is not a quote bar (above) is a frame
                # or margin line, and the flow has nothing to place it with.
                # Its fill passes the stray-shape area test below, so it went
                # into the flow as a picture of a rule, and a picture in the
                # flow spends its full height: RFC 9110's collected ABNF sits
                # in a box drawn as two 0.8pt vlines down the page, 553pt
                # each, and its four pages rendered as twelve. Drawn where the
                # source drew it, behind the text, it spends none. (Not under
                # the Google Docs profile, which keeps the flow; its writer
                # places these itself.)
                fig = build_figure([d], blocks, p.images, consumed, p)
                rule_floats.append(FloatEl(el=fig, bbox=tuple(fig.clip),
                                           behind=True))
                continue
            if d.shape in ("curve", "complex", "line") or (
                    d.fill and bbox_area(d.bbox) > 400):
                # A stray shape is promoted to a rasterised block here on area
                # alone. That test has no sense of position, and a shape lying
                # wholly in a side margin is furniture: rasterising it spends
                # body height the source never spent. Guarded at the promotion
                # site rather than by filtering the drawing list, because
                # shapes in the margin band still legitimately ANCHOR body
                # content -- a quote bar or callout rule sits just outside the
                # column and marks text inside it, and removing it upstream
                # destroys the callout (measured: it moved four gated
                # fixtures).
                if in_side_margin(d.bbox, furniture_l, lay.margin_r, p.width):
                    continue
                elements.append(build_figure([d], blocks, p.images, consumed, p))

        for im in p.images:
            if getattr(im, "_consumed", False) or im.data is None:
                continue
            if in_side_margin(im.bbox, furniture_l, lay.margin_r, p.width) \
                    and p.number not in deck:
                # Marginal logo/icon: furniture, not flow. A slide anchors
                # it where it is instead, which costs the flow nothing.
                continue
            el = ImageEl(data=im.data, ext=im.ext,
                         width=im.bbox[2] - im.bbox[0], height=im.bbox[3] - im.bbox[1])
            el._bbox = im.bbox
            elements.append(el)

        elements = _merge_box_rows(_merge_figures(elements))
        elements = _merge_table_rows(elements, blocks, consumed)
        if cuts and _keeps_panel_cuts(blocks, consumed, lay):
            # Not a two-column page, so the piece left outside a panel is not
            # the other column running past it (y60's MMWR summary boxes, one
            # column of two, which the cut re-paragraphed): it is the text
            # set BESIDE the panel. DOE OIG's highlights page sets a shaded
            # sidebar (x 41-239) beside its findings (252-560); welded back,
            # the sidebar's last lines read across into the findings, the
            # page lost its side-by-side reading, the sidebar stood 570pt
            # above the findings, and every later page was a page late.
            # Kept cut, the region readers lay the two out side by side. Only
            # for a sidebar's cut (`_sidebar_cut`).
            rects = [d.bbox for _, d in draws if _box_candidate(d)]
            cuts = [c for c in cuts
                    if not _sidebar_cut(c, rects, consumed, lay.content_w)]
        _restore_uncut(cuts, consumed)
        if p.number in deck:
            elements, pl.floats = _float_graphics(elements, blocks,
                                                  p.width, p.height)
            pl.floats = rule_floats + list(pl.floats)
        else:
            if anchored:
                elements, pl.floats = _float_backgrounds(elements, blocks,
                                                         lay, p.width, p.height)
                pl.floats = rule_floats + list(pl.floats)
            elif anchor_pictures:
                elements, floated = _float_backgrounds(
                    elements, blocks, lay, p.width, p.height, pictures_only=True)
                pl.floats = list(pl.floats or ()) + floated
            elements = _merge_graphic_rows(elements, blocks, p.number)

        # rebuild flow blocks from unconsumed lines (contiguous runs)
        flow_blocks = []
        for b in blocks:
            cur = []
            for l in b.lines:
                if id(l) in consumed:
                    if cur:
                        flow_blocks.append(_mk_block(cur))
                        cur = []
                else:
                    cur.append(l)
            if cur:
                flow_blocks.append(_mk_block(cur))

        # does a headed table run to the foot of this page? (nothing below it)
        headed_carry = None
        rest = [l.bbox[3] for b in flow_blocks for l in b.lines]
        for el in elements:
            hd = getattr(el, "_headed", None)
            if hd and el.bbox and all(y <= el.bbox[3] + 1.0 for y in rest):
                headed_carry = hd

        page_top = lay.margin_t
        if p.number == 1 and lay.cover_band is not None and lay.cover_band.bbox:
            page_top = lay.cover_band.bbox[3]
        # Footnotes are read off the page's own lines before the flow is built
        # (a mark fragment and its line are still separate there) and bound to
        # the flow after it (the references live in its runs). See notes.py.
        col_l, col_r = lay.margin_l, lay.page_w - lay.margin_r
        pn = find_page_notes([l for b in flow_blocks for l in b.lines],
                             [d for i, d in enumerate(p.drawings) if i not in cd],
                             body_size, col_l, col_r,
                             can_continue=prev_notes)
        pl.chunks = _assemble_chunks(elements, flow_blocks, lay, p, page_top)
        if p.number in deck:
            _lock_slide(pl, lay)
        prev_notes = bool(pn is not None and
                          bind_page_notes(doc_lay, pl, pn, col_l, col_r))
        doc_lay.pages.append(pl)

    lay = doc_lay
    number_footnotes(lay)
    _coalesce_striped_table_segments(lay)
    _propagate_list_hangs([el for pg in lay.pages for els in page_sequences(pg)
                           for el in els if isinstance(el, Para)])
    _mark_headings(lay, body_size)
    # After the hangs (a level's indents are read from them) and the headings
    # (a numbered heading is a heading, not a list item).
    assign_lists(lay, body_size)
    if _can_relax_bottom_margin(lay):
        # DOCX flow has no equivalent of PDF's last-baseline fit.  With a hard
        # source-page break, LibreOffice moving even one final line below the
        # inferred bottom reserve produces a mostly empty extra page. Give plain
        # flow documents the conventional 0.2in minimum reserve instead, or the
        # footer's top when there is a footer. This is deliberately withheld
        # when a cover section or a figure-flow overlay could occupy the same
        # physical bottom area.
        feet = [lay.footer_default, lay.footer_even]
        feet += [s.parts.get(k) for s in lay.hf_sections if s.parts
                 for k in ("footer", "footer_even")]
        floor = max([14.0] + [p.distance + _hf_extent(p) for p in feet
                              if p is not None])
        floor = math.ceil(floor * 10) / 10
        lay.margin_b = min(lay.margin_b, floor)
        for pl in lay.pages:
            if pl.margins is not None:
                ml, mr, mt, mb = pl.margins
                pl.margins = (ml, mr, mt, min(mb, floor))


def _mk_block(lines):
    bb = None
    for l in lines:
        bb = bbox_union(bb, l.bbox)
    return TextBlock(lines=list(lines), bbox=bb)


def _can_relax_bottom_margin(lay: DocLayout) -> bool:
    """Whether a document can safely use the ordinary bottom reserve: 14pt,
    or the top of its footer when it has one.

    A cover has its own vertical coordinate system, and graphic text that
    overlaps a figure cannot be represented as overlapping DOCX flow. Both make
    a global bottom-margin change an unsafe way to recover ordinary text
    overflow. The check is geometric and deliberately says nothing about fixture
    names or parser backends.

    A header or footer no longer refuses. Both used to: before running heads
    were stated as parts, a document had one only when its page 2 did, and the
    refusal took the reserve away from exactly the documents whose furniture
    is now emitted -- the pandoc manual's bottom margin went from 14pt to the
    67pt its lowest source line implies, every page losing the room its
    re-wrapped text had been using. A header never touches the bottom; a
    footer bounds the body by itself in every renderer (measured in the
    canonical LibreOffice: the body ends at page height - max(bottom margin,
    footer distance + footer height)), so the reserve simply stops at the
    footer's top. On the gated documents that carry a footer this changes the
    written bottom margin and nothing that renders (measured: identical raw
    numbers on all 16).
    """
    if lay.cover_band is not None:
        return False
    # A table carried across pages (continuation_only) breaks where the
    # bottom margin says, not at a source page seam: with the 14pt reserve
    # c3_tables' long table took two more rows onto page 1 than its source
    # and its product-lane word placement fell 0.936 -> 0.915.
    if any(getattr(pg, "continuation_only", False) for pg in lay.pages):
        return False
    for page in lay.pages:
        elements = [el for chunk in page.chunks for el in chunk.elements]
        figures = [el for el in elements if isinstance(el, FigureEl)]
        for figure in figures:
            for element in elements:
                if element is figure or not isinstance(
                        element, (Para, TableEl, ImageEl, RuleEl)):
                    continue
                bbox = _el_bbox(element)
                if bbox is None:
                    continue
                # Include nearby axis labels: they can sit just outside a chart
                # while sharing its vertical band, and DOCX cannot overlap them
                # with an inline image the way the PDF does.
                if bbox[1] < figure.clip[3] and bbox[3] > figure.clip[1] and \
                        bbox[0] < figure.clip[2] + 36 and \
                        bbox[2] > figure.clip[0] - 36:
                    return False
    return True


# How close two figure regions must be to be one figure. A row of cards is a
# row, not a stack: the writer emits every FigureEl as a block, so N side-by-side
# regions that failed to merge cost (N-1) x their height in flow the source never
# spent.
#
# 4.0 was 1.3pt short of the case this converter exists for. c1's three
# rounded-corner stat cards share an exact y-extent (222.2..279.5) and sit in
# 9.33pt gutters; after `build_figure`'s own +/-2pt clip padding the surviving
# gap is 5.3pt, so a 4pt expansion missed and PyMuPDF emitted three stacked
# figures -- 171pt of flow against the source's 57pt. Measured: a +115pt step at
# exactly the card row, page 1 overflowing to a third page, and word placement
# 0.797. PDFium reports a stroke ring just outside each fill, merged the row into
# one 495x59 figure on its own, and showed no step at all -- the two arms
# disagreeing was itself the evidence that the row is one figure.
#
# 6.0 clears 5.3 with margin and is still far below the 9.33pt raw gutter, so
# genuinely separate figures a source spaced normally do not collide. Measured
# over the gated sixteen: no document's figure count changes except c1's.
FIG_MERGE_GAP = 6.0


# A slide deck is landscape pages set in presentation type. Measured over both
# corpora (95 documents): two have landscape pages at all -- the PowerPoint
# deck y34 (960x540) sets its text at a character-weighted median of 18.0pt,
# and the InDesign tri-fold y59 at 6.7pt. Body text in a document runs
# 8-12pt; a slide's body is 18-28pt by PowerPoint's own defaults. 14pt sits
# in the empty gap between. The landscape bar admits 4:3 (1.33) and 16:9
# (1.78) slides and US Letter turned sideways (1.29).
DECK_MIN_TEXT_PT = 14.0
DECK_LANDSCAPE = 1.2
# The bottom reserve of a deck's pages (see _infer): enough that no renderer
# refuses it, and no more.
DECK_MARGIN_B = 4.0


def _deck_pages(ir: DocIR, hf: dict) -> frozenset:
    """Page numbers of the document's slides, or an empty set.

    Why a slide is laid out differently at all: it is positioned graphics --
    a logo in the corner beside the footer text, screenshots with callouts
    drawn over them, pictures beside bullet points -- and a flow stacks every
    one of them under the text it sat beside. Measured on y34 (40 slides): the
    16:9 logo alone stood 81pt in the flow below each slide's last line and
    pushed the slide's footer onto a page of its own, and the screenshot
    slides stacked 700pt of pictures into a 512pt page; 40 slides rendered as
    98 pages.

    The test is the document's, not the page's: the median size of the text
    the landscape pages carry (headers and footers excluded). A dense table
    slide is still a slide of its deck.
    """
    land = [p for p in ir.pages if p.width >= DECK_LANDSCAPE * p.height]
    if not land:
        return frozenset()
    sizes = Counter()
    for p in land:
        ct = hf["consumed_text"][p.number]
        for bi, b in enumerate(p.blocks):
            for ln in b.lines:
                if (bi, id(ln)) in ct:
                    continue
                for s in ln.spans:
                    n = len(s.text.strip())
                    if n:
                        sizes[round(s.size, 1)] += n
    total = sum(sizes.values())
    if not total:
        return frozenset()
    acc = 0
    for size in sorted(sizes):
        acc += sizes[size]
        if 2 * acc >= total:
            break
    if size < DECK_MIN_TEXT_PT:
        return frozenset()
    return frozenset(p.number for p in land)


# A picture covering this share of the paper in both dimensions IS the page,
# and the writer places it itself: docxout._FULL_PAGE_FRAC, anchored behind
# text at the page origin in every profile (live-verified on y28's cover,
# docs/evidence/gdocs-2026-10-04-cover-picture.json). The float passes below
# leave such a picture in the flow for that rule, so one picture is never
# handled twice and the gdocs profile, which floats nothing, places it the same
# way as the standard one.
FULL_PAGE_FRAC = 0.97


def _fills_page(bb, page_w: float, page_h: float) -> bool:
    return (bb[2] - bb[0]) >= FULL_PAGE_FRAC * page_w and \
        (bb[3] - bb[1]) >= FULL_PAGE_FRAC * page_h


def _float_graphics(elements, blocks, page_w: float, page_h: float):
    """(flow elements, [FloatEl]): a slide's pictures and drawn figures leave
    the flow for their own positions (see `_deck_pages`). A graphic under the
    page's text goes behind it: slide text is set over its pictures. A
    full-page picture stays for the writer's own rule (FULL_PAGE_FRAC)."""
    text = [l.bbox for l in _all_lines(blocks)]
    keep, floats = [], []
    for e in elements:
        if isinstance(e, ImageEl):
            bb = getattr(e, "_bbox", None)
        elif isinstance(e, FigureEl):
            bb = e.clip
        else:
            keep.append(e)
            continue
        if bb is None or bb[2] - bb[0] <= 0 or bb[3] - bb[1] <= 0 or \
                _fills_page(bb, page_w, page_h):
            keep.append(e)
            continue
        behind = any(bbox_overlap(bb, t) > 0.0 for t in text)
        floats.append(FloatEl(el=e, bbox=tuple(bb), behind=behind))
    return keep, floats


# Text lines a picture must hold, whole, to be the page's background.
BACKGROUND_MIN_LINES = 1
# A picture under the page's text that spans the paper's width is a page
# background element -- a full-bleed strip or panel -- even under the
# `pictures_only` capability (gdocs), where a background otherwise stays in
# the flow. Same share as the full-page rule (FULL_PAGE_FRAC, d630b33), in
# width only: y33's cover strips are 594.8 x 280.6pt and its p3/p4 tinted
# panel 594.0 x 93.5 / 654.4 / 93.1pt on 595.2pt paper (0.998-0.999).
# Stacked in the flow they put y33 at 65 pages for 60 in live Docs (onset
# p2); anchored behind the text at their page position, live Docs read 60
# for 60, word recall 0.271 -> 0.992, within-2pt 0.314, SSIM 0.61 -> 0.74
# (WP27 probe wp27bg, 2026-10-06). A picture inside the margins -- a figure
# a caption is set on -- is narrower and keeps the flow.
PAGE_BACKGROUND_WIDTH_FRAC = FULL_PAGE_FRAC


def _float_backgrounds(elements, blocks, lay: DocLayout, page_w: float,
                       page_h: float, pictures_only: bool = False):
    """(flow elements, [FloatEl]): a picture the page's text is set ON leaves
    the flow for its own position, behind the text.

    A flow stacks a picture and the text drawn over it: y33 (Kofax Power PDF)
    sets its "How to have your say" pages on a full-page tinted panel, a
    594x654pt image, and in the flow it stood a page of blue before the text
    it was behind -- every such page rendered as three. Anchored behind the
    text it spends no flow height, and the page reads as the source does.
    Only raster images: a drawn figure rasterises the text inside its clip
    with it, so it never has live text on it. Not under the Google Docs
    profile (the `anchored` capability), which keeps the flow.

    A picture printed into the page's top or bottom margin goes the same
    way, in front: the flow cannot put it there at all. y33's cover bleeds
    its artwork off the paper's foot (y 530-842 of 842); in the flow it went
    over the page and took a page of its own.

    A full-page picture is left to the writer's own rule (FULL_PAGE_FRAC).

    `pictures_only`: the pictures set on a text line, wrapped by a paragraph
    or printed into a margin leave the flow (the capability "anchor_pictures",
    for a profile that does not position graphics otherwise); a background
    the text is set on stays in it unless it spans the paper's width
    (PAGE_BACKGROUND_WIDTH_FRAC: y33's strips and panels). DOE OIG's highlights picture (y28 page 3,
    320x390pt beside the findings, running off the paper's foot) is the
    margin case.
    """
    lines = [l.bbox for l in _all_lines(blocks)]
    keep, floats = [], []
    for e in elements:
        bb = getattr(e, "_bbox", None) if isinstance(e, ImageEl) else None
        if bb is None or _fills_page(bb, page_w, page_h):
            keep.append(e)
            continue
        under = sum(1 for t in lines if contains(bb, t, pad=0.5)) >= \
            BACKGROUND_MIN_LINES
        bleeds = bb[1] < lay.margin_t - MARGIN_BLEED_PT or \
            bb[3] > page_h - lay.margin_b + MARGIN_BLEED_PT
        if under and pictures_only and \
                (bb[2] - bb[0]) < PAGE_BACKGROUND_WIDTH_FRAC * page_w:
            keep.append(e)
            continue
        if under or bleeds:
            floats.append(FloatEl(el=e, bbox=tuple(bb), behind=under))
            continue
        if any(isinstance(o, TableEl) and o.bbox and
               contains(o.bbox, bb, pad=FRAME_PAD_PT) for o in elements):
            # A picture inside a frame the source drew around it: the frame
            # is a table in the flow, and its cell keeps the picture's room.
            # y12's cover sets its photograph in a ruled frame over the "Get
            # forms" box; the photo was read as wrapped by the contents
            # column beside it (another column, not a wrap) and anchored
            # with square wrapping, so the frame's first row, which already
            # stands for it, could not sit under it -- pushed below the
            # photograph, the frame left the column and the cover ran a page
            # over. Anchored with no wrap, it lies on its own empty cell.
            e.align = "left"
            e.left_indent = max(0.0, round(bb[0] - lay.margin_l, 1))
            floats.append(FloatEl(el=e, bbox=tuple(bb)))
            continue
        wrap = _wrapped_by_text(bb, lines)
        if wrap is not None or _on_text_line(bb, lines):
            # Placed in the flow's terms too, as `_to_flow` places a picture:
            # a writer that cannot anchor it on its page (a merged booklet
            # run, docxout._merge_grid_page_runs) sets it back in the flow.
            e.align = "left"
            e.left_indent = max(0.0, round(bb[0] - lay.margin_l, 1))
            floats.append(FloatEl(el=e, bbox=tuple(bb), wrap=wrap))
        else:
            keep.append(e)
    return keep, floats


def _wrapped_by_text(bb, lines):
    """The clearance (left, top, right, bottom) a paragraph wrapped around the
    picture `bb` keeps from it, or None when the source does not wrap one.

    A wrap is text set beside the picture -- every line in its band clear of
    it, on one side -- that then runs on UNDER (or over) it, across its
    width: SP 800-63B sets a 72pt icon at the head of each authenticator's
    section and wraps the first six lines of the paragraph beside it at
    x 153 before it returns to the margin at 72. Stacked, the icon stood
    below its paragraph, and each such page ran 45-76pt over (three pages
    late by the end of chapter 5). Anchored where it was with the text
    wrapped around it, the paragraph breaks where the source broke it.

    The run under the picture is what separates a wrap from a picture beside
    a column of text, which the side-by-side region readers lay out instead
    (`_side_by_side_chunks`): a column never comes back under its neighbour."""
    beside, below_above = [], False
    for t in lines:
        lh = t[3] - t[1]
        if lh <= 0:
            continue
        ov = min(bb[3], t[3]) - max(bb[1], t[1])
        crosses = t[0] < bb[2] - 1.0 and t[2] > bb[0] + 1.0
        if ov >= WRAP_MIN_OVERLAP * lh:
            if crosses:
                return None
            beside.append(t)
        elif crosses and (0.0 <= t[1] - bb[3] <= WRAP_REACH_LINES * lh or
                          0.0 <= bb[1] - t[3] <= WRAP_REACH_LINES * lh):
            below_above = True
    if len(beside) < WRAP_MIN_LINES or not below_above:
        return None
    if all(t[0] >= bb[2] - 1.0 for t in beside):
        return (0.0, 0.0, round(max(0.0, min(t[0] for t in beside) - bb[2]), 1), 0.0)
    if all(t[2] <= bb[0] + 1.0 for t in beside):
        return (round(max(0.0, bb[0] - max(t[2] for t in beside)), 1), 0.0, 0.0, 0.0)
    return None             # text on both sides: a picture between columns


# A wrap (`_wrapped_by_text`): lines sharing at least this share of their height
# with the picture's band are beside it; at least this many of them, and a line
# within this many of its own heights under or over the picture that crosses
# its width. The 0.5 is ON_LINE_MIN_OVERLAP's; two lines is the least a wrap can
# be, and a single line beside a picture is `_on_text_line`'s case.
WRAP_MIN_OVERLAP = 0.5
WRAP_MIN_LINES = 2
WRAP_REACH_LINES = 2.0


# A picture this far into the top or bottom margin is set in it (pt).
MARGIN_BLEED_PT = 2.0
# A picture inside a table's box to within this much (pt) is framed by it: the
# frame's rule sits on the picture's edge, and a stroke's half-width and the
# rule's own thickness put y12's cover frame (2pt rules) 1-2pt outside it.
FRAME_PAD_PT = 3.0
# A picture is set ON a text line (`_on_text_line`) when a line beside it shares
# at least this share of its height with the picture's band, and the picture is
# no taller than this many of those lines. Measured: NIST's withdrawal-notice
# logo, 28pt beside a 16pt "Date updated" line (overlap 0.69, 1.75 lines), and
# SP 800-63B's contents numbers drawn as 10pt pictures inside 16pt entry lines
# (0.61, 0.6 lines). Two lines keeps a picture beside a paragraph -- a masthead
# logo, a figure with a caption -- for the side-by-side region readers.
ON_LINE_MIN_OVERLAP = 0.5
ON_LINE_MAX_LINES = 2.0


def _on_text_line(bb, lines) -> bool:
    """Is the picture `bb` set on a text line: beside it, in its band?

    The flow stacks every element, so a picture and the line beside it each
    take their own height, one under the other. NIST's withdrawal notice sets
    its logo beside the "Date updated" line at the foot of the page, and
    stacked, the line went over: the notice took two pages, and SP 800-88's
    and 800-63B's every later page was a page late (word recall 0.38, 0.24).
    The contents of SP 800-63B draw each entry's section number as a 10pt
    picture inside the entry's line, and stacked, three contents pages ran
    five lines over each. Anchored at its own position the picture spends no
    flow height and the line keeps its own, which is the page the source set.

    Only when every line in the picture's band is clear of it horizontally:
    a line crossing the picture is text over it (the `under` test's case) or a
    caption, and both are left alone."""
    h = bb[3] - bb[1]
    if h <= 0:
        return False
    best, tallest = 0.0, 0.0
    for t in lines:
        lh = t[3] - t[1]
        ov = min(bb[3], t[3]) - max(bb[1], t[1])
        if lh <= 0 or ov <= 0:
            continue
        if not (t[2] <= bb[0] + 1.0 or t[0] >= bb[2] - 1.0):
            return False
        if ov / lh >= ON_LINE_MIN_OVERLAP:
            best = max(best, ov / lh)
            tallest = max(tallest, lh)
    return best > 0.0 and h <= ON_LINE_MAX_LINES * tallest


# A one-line framed paragraph keeps its own width plus this much (fraction of
# the line, and at least DECK_FRAME_SLACK_PT): enough that a substitute face a
# little wider than the source's does not wrap the line, narrow enough that
# the frame stops short of a neighbour on its row -- LibreOffice moves a frame
# that collides with another down below it.
DECK_FRAME_SLACK = 0.08
DECK_FRAME_SLACK_PT = 6.0
# Height, in points, of each of the two 1pt paragraphs the writer puts on a
# locked slide's page (the seam holder before its frames, the anchor after).
DECK_HOLDER_PT = 1.0


def _frame_para(p: Para, col_l: float, col_r: float) -> None:
    """Lock `p` to its source position: Para.frame, in the coordinates its
    indents were measured in (`col_l`/`col_r`), with indents and tab stops
    made relative to the frame."""
    hang = min(0.0, p.first_indent or 0.0)
    left = col_l + (p.left_indent or 0.0) + hang
    right = col_r - (p.right_indent or 0.0)
    one_line = (getattr(p, "_vis_lines", None) or p.src_lines or 1) <= 1 \
        and not p.line_breaks
    if one_line and p.bbox is not None:
        ink = p.bbox[2] - p.bbox[0]
        room = ink + max(DECK_FRAME_SLACK_PT, DECK_FRAME_SLACK * ink)
        if p.align == "center":
            mid = (p.bbox[0] + p.bbox[2]) / 2
            left, right = mid - room / 2, mid + room / 2
            p.left_indent = p.first_indent = 0.0
        elif p.align == "right":
            left = max(left, p.bbox[2] - room)
            right = p.bbox[2]
        else:
            right = min(right, left - hang + room)
    width = max(4.0, right - left)
    shift = left - col_l
    if p.align != "center" or not one_line:
        # left + hang is the frame's edge, so this is -hang for a hanging
        # item and 0 otherwise; a right-aligned line's frame may start right
        # of its old indent.
        p.left_indent = max(0.0, round((p.left_indent or 0.0) - shift, 1))
    p.right_indent = 0.0
    if p.tab_stops:
        p.tab_stops = [(round(t[0] - shift, 1),) + tuple(t[1:])
                       for t in p.tab_stops]
    top, _h = _para_box(p)
    p.frame = (round(left, 1), round(top, 1), round(width, 1))
    p.space_before = 0.0


def _lock_slide(pl: PageLayout, lay: DocLayout) -> None:
    """A slide's text page-locked where the source set it (Para.frame), its
    pictures already anchored (`_float_graphics`); what stays in the flow --
    tables -- re-spaced against the flow that remains.

    Why frames, on a slide and nowhere else (docs/deep-dive/theory.md §6
    rejects positioned text as the default, and Google Docs breaks it). A
    slide is not a flow:
    it is text boxes placed on a fixed canvas, side by side and over
    pictures, and a flow reproduces it only while every gap it stacks is
    exactly right. Measured on y34, with the pictures anchored and the text
    flowing: 40 slides rendered 49 pages, every extra one a slide whose last
    line -- its slide number, 15pt above the paper's edge -- went over by
    the few points a re-wrapped bullet or a table row had drifted. A text box
    at its own position cannot drift into the next page, and stays text: a
    paragraph in a frame is edited, styled and copied like any other.
    """
    content_l, content_r = lay.margin_l, lay.page_w - lay.margin_r
    elements = []
    for ch in pl.chunks:
        for el in ch.elements:
            if isinstance(el, ColBreak):
                continue
            if isinstance(el, Para) and el.runs and \
                    getattr(el, "_b1", None) is not None and \
                    not getattr(el, "rtl", False):
                # (a right-to-left paragraph's indents are start/end, which
                # `_frame_para` does not read; it keeps the flow)
                cl, cr = getattr(el, "_col", (content_l, content_r))
                _frame_para(el, cl, cr)
            elif isinstance(el, RuleEl) and getattr(el, "_bbox", None):
                bb = el._bbox
                el.frame = (round(bb[0], 1), round(bb[1] - 1.0, 1),
                            round(max(1.0, bb[2] - bb[0]), 1))
                el.left_indent = 0.0
                el.space_before = 0.0
            elif isinstance(el, TableEl) and el.bbox is not None:
                # A floating table (w:tblpPr) at its top-left: y34's content
                # slide sets two tables side by side, which a flow stacks.
                bb = el.bbox
                el.frame = (round(bb[0], 1), round(bb[1], 1),
                            round(bb[2] - bb[0], 1))
                el.space_before = 0.0
            elements.append(el)
    # What flows (tables) starts below the writer's two holder paragraphs.
    cursor = lay.margin_t + 2 * DECK_HOLDER_PT
    for el in elements:
        if getattr(el, "frame", None) is not None:
            continue
        bb = _el_bbox(el)
        if bb is None:
            continue
        if isinstance(el, Para):
            t, h = _para_box(el)
            el.space_before = max(0.0, round(t - cursor, 1))
            cursor = t + h
        else:
            el.space_before = max(0.0, round(bb[1] - cursor, 1))
            cursor = bb[3]
    pl.chunks = [Chunk(n_cols=1, elements=elements)]


# Two graphics are in one row when their vertical extents overlap by this
# share of the shorter one.
GRAPHIC_ROW_OVERLAP = 0.5


def _merge_graphic_rows(elements, blocks, page_no: int):
    """Graphics set side by side -- a row of logos -- become ONE figure.

    The flow can only stack them, so a row of two pictures spent the height of
    both: y30's cover sets the ministry's crest (a drawn figure at x 0-142)
    and the government logo (an image at x 282-463) on one band 42pt tall at
    the paper's foot, and stacked they were 85pt, which went over the page.
    The page's blank verso then became two pages, and every page after it
    sat one place late. One figure, rasterised over both, spends the row's
    height once. Never across text: the region is rendered from the page, and
    a line inside it would be printed twice, once live and once as pixels.
    """
    gr = [e for e in elements if isinstance(e, (ImageEl, FigureEl))
          and _el_bbox(e) is not None]
    if len(gr) < 2:
        return elements
    text = [l.bbox for l in _all_lines(blocks)]
    gr.sort(key=lambda e: _el_bbox(e)[1])
    groups = []
    for e in gr:
        bb = _el_bbox(e)
        for g in groups:
            ub = g[1]
            ov = min(ub[3], bb[3]) - max(ub[1], bb[1])
            short = min(ub[3] - ub[1], bb[3] - bb[1])
            if short > 0 and ov >= GRAPHIC_ROW_OVERLAP * short and \
                    all(bbox_overlap(_el_bbox(m), bb) <= 0 for m in g[0]):
                g[0].append(e)
                g[1] = bbox_union(ub, bb)
                break
        else:
            groups.append([[e], tuple(bb)])
    drop, add = set(), []
    for members, ub in groups:
        if len(members) < 2:
            continue
        # (a line inside a member FIGURE is already its pixels: y30's
        # "EDITION 3.1" box was rasterised with its text)
        clips = [m.clip for m in members if isinstance(m, FigureEl)]
        if any(bbox_overlap(ub, t) > 0 and
               not any(contains(c, t) for c in clips) for t in text):
            continue
        fig = FigureEl(page_no=page_no, clip=tuple(ub),
                       width=ub[2] - ub[0], height=ub[3] - ub[1])
        drop.update(id(m) for m in members)
        add.append(fig)
    if not add:
        return elements
    return [e for e in elements if id(e) not in drop] + add


def _merge_figures(elements):
    figs = [e for e in elements if isinstance(e, FigureEl)]
    other = [e for e in elements if not isinstance(e, FigureEl)]
    merged = True
    while merged:
        merged = False
        out = []
        for f in figs:
            hit = None
            for g in out:
                if bbox_overlap(_expand(f.clip, FIG_MERGE_GAP), g.clip) > 0:
                    hit = g
                    break
            if hit:
                nb = bbox_union(hit.clip, f.clip)
                hit.clip = nb
                hit.width, hit.height = nb[2] - nb[0], nb[3] - nb[1]
                merged = True
            else:
                out.append(f)
        figs = out
    return other + figs


# A row of boxes -- stat tiles, KPI cards -- is drawn as separate panels with a
# gutter between them, so each is its own drawing cluster and becomes its own
# one-cell box. The flow then stacks them: c1_whitepaper's three cards share
# one 53pt band and came out 3 x 53pt tall, the same +106pt step that made
# _merge_figures merge them as pictures. Boxes whose top AND bottom edges agree
# within CARD_ROW_EDGE_TOL sit on one band; c1's measure 224.2/277.5 exactly.
# The gutter between neighbours must be a gutter, not a gap in a page of
# boxes: c1's is 9.3pt, and a half inch is the widest card gutter any of the
# documents with card rows sets.
CARD_ROW_EDGE_TOL = 3.0
CARD_ROW_MAX_GAP = 36.0


# Tables side by side on one band share their top and bottom within this (pt)
# and their rows within TABLE_ROW_ROW_TOL each: FIPS 197's Appendix B states
# (y03 p42) are 4x4 grids at x 123/206/289/372/455, 269.3-327.0 every one.
TABLE_ROW_EDGE_TOL = 2.0
TABLE_ROW_ROW_TOL = 1.0


def _merge_table_rows(elements, blocks, consumed):
    """Grid tables standing side by side on one band -> one table.

    The flow is a single column: tables that share a band were written one
    under another, each at the band's own space-before. y03's Appendix B (the
    AES state after each round step, five 4x4 grids a row, six rows a page)
    came out one grid wide and thirty tall -- two source pages over seven.
    Each table keeps its columns, cells and borders; the white between them
    becomes an empty, unruled column. A label beside the band ('input', the
    round number) sits in a column of its own in the row its centre falls in,
    where the flow had put it after the tables. Only where the white between
    the tables holds no text, so nothing on the page is covered."""
    tabs = [e for e in elements if isinstance(e, TableEl) and e.role == "table"
            and e.bbox and e.rows and len(e.row_heights) == len(e.rows)
            and all(h is not None for h in e.row_heights)]
    if len(tabs) < 2:
        return elements
    free = [ln for ln in _all_lines(blocks) if id(ln) not in consumed and ln.text.strip()]
    tabs.sort(key=lambda e: (round(e.bbox[1]), e.bbox[0]))
    used, merged = set(), {}
    for t in tabs:
        if id(t) in used:
            continue
        row = [u for u in tabs if id(u) not in used and
               abs(u.bbox[1] - t.bbox[1]) <= TABLE_ROW_EDGE_TOL and
               abs(u.bbox[3] - t.bbox[3]) <= TABLE_ROW_EDGE_TOL and
               len(u.rows) == len(t.rows) and
               all(abs(a - b) <= TABLE_ROW_ROW_TOL
                   for a, b in zip(u.row_heights, t.row_heights))]
        if len(row) < 2:
            continue
        row.sort(key=lambda e: e.bbox[0])
        y0 = min(e.bbox[1] for e in row)
        y1 = max(e.bbox[3] for e in row)
        if any(b.bbox[0] < a.bbox[2] - 0.5 for a, b in zip(row, row[1:])):
            continue                         # overlapping: not one band of tables
        gap_text = any(
            a.bbox[2] < (ln.bbox[0] + ln.bbox[2]) / 2 < b.bbox[0] and
            y0 < (ln.bbox[1] + ln.bbox[3]) / 2 < y1
            for a, b in zip(row, row[1:]) for ln in free)
        if gap_text:
            continue
        labels = [ln for ln in free
                  if ln.bbox[2] <= row[0].bbox[0] - 1.0 and
                  y0 <= (ln.bbox[1] + ln.bbox[3]) / 2 <= y1]
        used.update(id(e) for e in row)
        merged[id(row[0])] = _join_tables(row, labels, y0)
        for e in row[1:]:
            merged[id(e)] = None
        consumed.update(id(ln) for ln in labels)
    if not merged:
        return elements
    out = []
    for e in elements:
        if id(e) in merged:
            if merged[id(e)] is not None:
                out.append(merged[id(e)])
            continue
        out.append(e)
    return out


def _join_tables(row, labels, y0) -> TableEl:
    """One table of `row`'s tables, left to right, with a label column."""
    heights = list(row[0].row_heights)
    nr = len(heights)
    row_ys = [y0]
    for h in heights:
        row_ys.append(row_ys[-1] + h)
    cells = [[] for _ in range(nr)]
    widths = []
    x_left = row[0].bbox[0]
    if labels:
        lx = min(ln.bbox[0] for ln in labels) - 1.0
        widths.append(row[0].bbox[0] - lx)
        x_left = lx
        for r in range(nr):
            mine = [ln for ln in labels
                    if row_ys[r] <= (ln.bbox[1] + ln.bbox[3]) / 2 < row_ys[r + 1]
                    or (r == nr - 1 and (ln.bbox[1] + ln.bbox[3]) / 2 >= row_ys[r + 1])]
            rect = (lx, row_ys[r], row[0].bbox[0], row_ys[r + 1])
            c = _cell_from_lines(sorted(mine, key=lambda l: (l.bbox[1], l.bbox[0])),
                                 rect) if mine else Cell(borders={}, pad=(0.0, 0.0, 0.0, 0.0))
            c.borders = {}
            cells[r].append(c)
    for i, t in enumerate(row):
        if i:
            gap = t.bbox[0] - row[i - 1].bbox[2]
            if gap > 0.05:
                widths.append(gap)
                for r in range(nr):
                    cells[r].append(Cell(borders={}, pad=(0.0, 0.0, 0.0, 0.0)))
        widths.extend(t.col_widths)
        for r in range(nr):
            cells[r].extend(t.rows[r])
    bb = (x_left, y0, row[-1].bbox[2], max(e.bbox[3] for e in row))
    out = TableEl(rows=cells, col_widths=widths, row_heights=heights,
                  role="table", bbox=bb)
    out.col_edges_drawn = True
    return out


def _merge_box_rows(elements):
    """Side-by-side one-cell boxes on one band -> one 'cards' table.

    The gutters become empty, unshaded columns, so every card keeps its own
    shading, borders and width and the row costs its height once."""
    boxes = [e for e in elements if isinstance(e, TableEl) and e.role == "box"
             and e.bbox and len(e.rows) == 1 and len(e.rows[0]) == 1
             and e.rows[0][0] is not None]
    if len(boxes) < 2:
        return elements
    boxes.sort(key=lambda e: (e.bbox[1], e.bbox[0]))
    rows, used = [], set()
    for b in boxes:
        if id(b) in used:
            continue
        row = [b]
        for c in boxes:
            if id(c) in used or c is b:
                continue
            if abs(c.bbox[1] - b.bbox[1]) <= CARD_ROW_EDGE_TOL and \
                    abs(c.bbox[3] - b.bbox[3]) <= CARD_ROW_EDGE_TOL:
                row.append(c)
        if len(row) < 2:
            continue
        row.sort(key=lambda e: e.bbox[0])
        if any(not (0.0 <= r2.bbox[0] - r1.bbox[2] <= CARD_ROW_MAX_GAP)
               for r1, r2 in zip(row, row[1:])):
            continue
        used.update(id(e) for e in row)
        rows.append(row)
    if not rows:
        return elements
    merged = {}
    for row in rows:
        cells, widths = [], []
        for i, e in enumerate(row):
            if i:
                gap = row[i].bbox[0] - row[i - 1].bbox[2]
                if gap > 0.05:
                    cells.append(Cell(borders={}, pad=(0.0, 0.0, 0.0, 0.0)))
                    widths.append(gap)
            cells.append(e.rows[0][0])
            widths.append(e.bbox[2] - e.bbox[0])
        bb = None
        for e in row:
            bb = bbox_union(bb, e.bbox)
        t = TableEl(rows=[cells], col_widths=widths, row_heights=[bb[3] - bb[1]],
                    role="cards", bbox=bb)
        # the cards' own drawn edges: the writer must neither widen a card
        # nor span one into the gutter beside it (docxout._fit_col_widths,
        # _span_into_blank_neighbours)
        t.col_edges_drawn = True
        merged[id(row[0])] = t
        for e in row[1:]:
            merged[id(e)] = None
    out = []
    for e in elements:
        if id(e) in merged:
            if merged[id(e)] is not None:
                out.append(merged[id(e)])
            continue
        out.append(e)
    return out


def _el_bbox(e):
    if isinstance(e, Para):
        return e.bbox
    if isinstance(e, TableEl):
        return e.bbox
    if isinstance(e, FigureEl):
        return e.clip
    if isinstance(e, (ImageEl, RuleEl)):
        return getattr(e, "_bbox", None)
    return None


# A role on the left and a date hard against the right margin, sharing one
# baseline, is the defining row of a resume and of most things shaped like one.
# The producer simply drew two runs at two x positions; nothing in the text says
# they belong together, and the two halves do not even reliably arrive in the
# same block -- on the resume fixture, page 1 puts each pair in one block and
# page 2 puts each half in a block of its own.
#
# Both spellings come out wrong, in different ways. Split across blocks, the
# right half becomes its own paragraph pushed across by an ABSOLUTE INDENT
# measured in the source's metrics: 8338 and 9308 twips against a 9026-twip
# content width, i.e. 92% and 103%. The second is past the right margin, so it
# wraps in any reader; the first leaves 0.34in for a date that needs more. (The
# owner's own resume measured 94%, leaving 0.44in for a nine-character date.)
# Inside one block, `_merge_row_lines` joins the halves with a SPACE, so the
# date simply trails the role in mid-line and never reaches the margin at all.
#
# One right-aligned tab stop at the content edge says the thing both spellings
# were trying to say, in a form that survives: the position is anchored to the
# margin rather than to a measured x, so a reader whose font is a hair wider
# still puts the date at the right margin instead of on the next line.
#
# This runs over the whole page's item stream rather than inside paragraph
# building, because that is the only scope where both halves are in view. It is
# also already per-column: `_assemble_chunks` calls `_to_flow` once per column
# band, so on a genuinely two-column page the two columns are never in the same
# stream to be paired.
_ROW_BASELINE_TOL = 2.0   # same baseline, allowing for rounding
_ROW_EDGE_TOL = 3.5       # how far short of the content edge the right half may stop
_ROW_MIN_GAP = 12.0       # a real gap, not two spans of one sentence
_ROW_LEFT_TOL = 12.0      # the left half starts the line, or it is not a row
_ROW_MAX_SHARE = 0.35     # above this the page is columnar, not a row list
# The right half is a FIELD -- a date, a location, a page number -- and the
# left half is a line of text. Both bounds were measured against the documents
# that wanted to be paired and must not be. Without them the rule fired 314
# times on y11_nist_sp80053r5, 98 on y06_irs_1040_instructions and 42 on
# y08_nist_sp80088r1, in three distinct wrong ways: an unsplit two-column body
# whose columns happen to share baselines, a term/definition glossary that was
# never recognised as a table, and bullet lists whose `•` arrives as its own
# line fragment beside the item text.
#
# A field and a column are far apart, so the cut is not a knife edge. x17's
# four right halves measure 0.097, 0.097, 0.204 and 0.097 of the content width;
# a column in a two-column body is about 0.48 by construction, and y08's
# definitions run past 0.60. The left bound separates the same cases from the
# other end: x17's left halves are 0.35 to 0.80 of the content width, while a
# glossary stub (`ATA`, `BD`) and a lone bullet are a few points wide.
_ROW_MAX_RIGHT = 0.30     # right half wider than this is a column, not a field
_ROW_MIN_LEFT = 0.20      # left half narrower than this is a stub or a marker
_ROW_EDGE_BUCKET = 2.0    # how near two rows must end to be the same column


def _row_style(ln: Line):
    """The typographic signature of a row half: dominant span's face and size."""
    s = max(ln.spans, key=lambda s: len(s.text.strip()))
    return (s.font, round(s.size * 2) / 2, s.bold, s.italic)


def _row_contrast(left: Line, right: Line) -> bool:
    """Do the two halves of a row differ in style, as a label and a field do?

    A role and its date are set apart (u1: Georgia-Bold 10 against
    Georgia-Italic 8.6; x17: bold against regular). A sentence broken across
    an unsplit two-column body is one style on both sides of the gap."""
    a, b = _row_style(left), _row_style(right)
    return a[0] != b[0] or a[2] != b[2] or a[3] != b[3] or abs(a[1] - b[1]) >= 0.5


def _row_candidates(lines, col_l, col_r):
    """-> ([(left, right)], n_rows): the geometric half of `_row_pairs`,
    before any column evidence is asked for."""
    if col_r - col_l <= 0:
        return [], 0
    lines = [ln for ln in lines if ln.horizontal and ln.spans]
    if len(lines) < 2:
        return [], 0
    lines.sort(key=lambda l: (round(l.baseline, 1), l.bbox[0]))
    rows = []
    for ln in lines:
        if rows and abs(ln.baseline - rows[-1][0].baseline) <= _ROW_BASELINE_TOL:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    width = col_r - col_l
    pairs = []
    for row in rows:
        # a third fragment on the baseline is a grid, and a grid is a table's
        # problem rather than this one's
        if len(row) != 2:
            continue
        left, right = row
        if left.bbox[0] > col_l + _ROW_LEFT_TOL:
            continue
        if right.bbox[2] < col_r - _ROW_EDGE_TOL:
            continue
        if right.bbox[0] - left.bbox[2] < _ROW_MIN_GAP:
            continue
        if right.bbox[2] - right.bbox[0] > _ROW_MAX_RIGHT * width:
            continue            # a column of text, not a right-aligned field
        if left.bbox[2] - left.bbox[0] < _ROW_MIN_LEFT * width:
            continue            # a table stub or a lone marker, not a row's label
        # a bullet already owns the paragraph's tab stop and its own tab run,
        # and it also reaches this function as a fragment all of its own
        if _line_starts_with_marker(left) or _is_marker_text(left.text):
            continue
        pairs.append((left, right))
    return pairs, len(rows)


def _doc_row_evidence(pages_lines, col_l, col_r):
    """[(right_x1, right_style, left_style)] of every geometric row candidate in
    the document, for `_row_pairs`' cross-page column evidence."""
    out = []
    for lines in pages_lines:
        pairs, _n = _row_candidates(lines, col_l, col_r)
        out.extend((r.bbox[2], _row_style(r), _row_style(l)) for l, r in pairs)
    return out


def _row_pairs(items, col_l, col_r, doc_rows=None):
    """-> ([(left_line, right_line)], {id(line) consumed}).

    The discriminator is the RIGHT half's right edge, and it is deliberately
    about the MARGIN rather than about the pair: two lines sharing a baseline in
    the middle of a column are two columns of something, and only a half flush
    to the edge is the right-aligned field this is meant to catch. The test is
    "not short of the content edge" rather than "within a few points either
    side", because the inferred edge can sit well INSIDE the true text edge --
    on the resume fixture the right-edge clustering puts col_r at 495.1 while
    the dates end at 552.7, and a symmetric test would reject every real row.

    Refuses wholesale when more than a third of the page's baselines pair up.
    That is the signature of a two-column page whose columns were not split:
    every body baseline pairs there, and turning each into a tabbed row would
    weld the columns together. Genuine row lists are a handful among many -- the
    resume fixture pairs 2 baselines of 14 on page 1 and 2 of 16 on page 2.

    `doc_rows` is `_doc_row_evidence` for the whole document; see below for
    the one case it decides.
    """
    lines = []
    for kind, _bb, o in items:
        if kind == "blk":
            lines.extend(_blk_lines(o))
    pairs, n_rows = _row_candidates(lines, col_l, col_r)
    if not pairs:
        return [], set()
    # A tab STOP is a column, so require the evidence of one: at least two rows
    # ending at the same x. A designer sets a right-aligned stop and then uses
    # it repeatedly -- that is what makes a resume's dates or a worksheet's
    # amounts a column -- whereas a single fragment that happens to finish at
    # the margin is just a line that finished at the margin.
    #
    # This is the guard that does the real work on prose. Measured over the
    # expansion corpus, the geometric bounds alone still paired 17 fragment
    # pairs on y06_irs_1040_instructions and 1 on y12_irs_pub15, every one of
    # them a sentence broken across a two-column body or a caption sitting
    # beside a heading, and every one of them alone on its page. Requiring the
    # column takes both to zero while keeping all four of x17's rows (two per
    # page, sharing an edge) and all six of y13_irs_pub501's support-worksheet
    # amounts, which are the same structure as a resume's dates and want the
    # same treatment.
    pairs.sort(key=lambda pr: pr[1].bbox[2])
    kept, cur = [], []
    for pr in pairs:
        if cur and pr[1].bbox[2] - cur[0][1].bbox[2] <= _ROW_EDGE_BUCKET:
            cur.append(pr)
            continue
        if len(cur) >= 2:
            kept.extend(cur)
        cur = [pr]
    if len(cur) >= 2:
        kept.extend(cur)
    # The column a stop belongs to is the DOCUMENT's, not the page's. A résumé
    # whose second page holds one role/date row has that row's tab stop on
    # every other page: measured on the owner's résumé, page 1's two rows end
    # at 553.5 and page 2's single row ends at 553.6, and judged alone the
    # single row was refused -- its date then fell into the description
    # paragraph below it as a 406pt first-line indent (defect catalogue #22).
    # So a pair alone on its page is kept when the document holds another
    # candidate at the same edge in the SAME pair of styles, and the pair's
    # halves differ in style the way a label and a field do. Both conditions
    # are what the prose false positives above lack: a sentence broken across
    # a two-column body is one style on both sides of its gap.
    if doc_rows:
        kept_ids = {id(pr[1]) for pr in kept}
        for left, right in pairs:
            if id(right) in kept_ids or not _row_contrast(left, right):
                continue
            rs, ls = _row_style(right), _row_style(left)
            same = sum(1 for x1, rsig, lsig in doc_rows
                       if abs(x1 - right.bbox[2]) <= _ROW_EDGE_BUCKET
                       and rsig == rs and lsig == ls)
            if same >= 2:
                kept.append((left, right))
    pairs = kept
    if not pairs or len(pairs) > _ROW_MAX_SHARE * n_rows:
        return [], set()
    consumed = set()
    for left, right in pairs:
        consumed.add(id(left))
        consumed.add(id(right))
    return pairs, consumed


def _row_para(left: Line, right: Line, col_l: float, col_r: float) -> Para:
    """One paragraph: left runs, a tab, right runs, one right stop at the edge."""
    p = para_from_lines([left], col_l, col_r)
    # Only the LAST run's trailing space is the gap before the tab. Stripping
    # every run deleted the word space at each run boundary inside the label:
    # y06_irs_1040's "Earned Income Credit (EIC) Table - Continued" is two
    # runs split after "- ", and came out "Table -Continued".
    while p.runs and not p.runs[-1].text.strip():
        p.runs.pop()
    if p.runs:
        p.runs[-1].text = p.runs[-1].text.rstrip(" ")
    p.runs = [r for r in p.runs if r.text]
    ref = p.runs[-1] if p.runs else None
    p.runs.append(Run(text="\t",
                      font=ref.font if ref else left.spans[0].font,
                      size=ref.size if ref else left.spans[0].size,
                      color=ref.color if ref else left.spans[0].color,
                      is_tab=True))
    p.runs += [r for r in runs_from_spans(right.spans) if r.text]
    # A right-aligned paragraph with a right tab stop is a contradiction, and
    # para_from_lines could have inferred one from the left half alone.
    p.align = "left"
    # The stop is the CONTENT WIDTH, not the measured x of the right half:
    # anchoring to the margin is the entire point of the change.
    p.tab_stops = [(round(col_r - col_l, 1), "right")]
    p.bbox = bbox_union(left.bbox, right.bbox)
    p.src_lines = 1
    p.src_widths = [round(right.bbox[2] - left.bbox[0], 1)]
    return p


def _blk_lines(o):
    """A flow item's lines: a TextBlock, or the line list a drop left behind."""
    return o if isinstance(o, list) else o.lines


def _drop_row_lines(items, consumed):
    """items with the paired lines removed, and emptied blocks dropped.

    A block is cut where a removed line stood. The flow is ordered at block
    granularity (see `_split_blocks_at_elements`), so lines kept on BOTH
    sides of a removed one, left in one block, all sorted at the block's top
    -- ahead of the rows taken out from between them. y64's household tables
    are one block per table: the section headings ("WHITE", "Men, 20 years
    and over") stayed in it, came out first, and every row of the table
    followed them, 1-3 pages of spill per table.
    """
    out = []
    for kind, bb, o in items:
        if kind != "blk":
            out.append((kind, bb, o))
            continue
        groups, cur = [], []
        for ln in _blk_lines(o):
            if id(ln) in consumed:
                if cur:
                    groups.append(cur)
                    cur = []
            else:
                cur.append(ln)
        if cur:
            groups.append(cur)
        for keep in groups:
            nb = None
            for ln in keep:
                nb = bbox_union(nb, ln.bbox)
            out.append((kind, nb or bb, keep))
    return out


# A contents line: a title, a run of leader dots, and a page reference. Every
# producer in the corpus draws the dots as text by the time `infer` sees them --
# LibreOffice and Word as "." glyphs filling a dot-leader tab, Chromium's dotted
# border rewritten into the same form by `dialect._drawn_leaders_to_text`.
#
# Left as text, the dots are a fixed-length string that a renderer re-wraps by
# its own metrics, and the line is welded to its neighbours: on
# x02_lo_report_toc the nine entries, all ending at the tab stop, read as one
# 9-line JUSTIFIED paragraph whose 24.5pt pitch could not fit above its first
# line, and the whole contents block landed 7.8pt low. The word processor's own
# idiom is the faithful one: title, TAB, page number, against a right-aligned
# tab stop with a dot leader at the measured edge -- one paragraph per entry.
#
# Only a DENSE run of dots is a word processor's leader, and only that is
# converted. TeX, Typst and Texinfo set spaced leaders (". . . ."), which a
# Word dot leader would redraw dense -- a different look, for no positional
# gain -- and every one of those dots is a word to anything that reads the
# text back: y26's 637-line index lost 21% of its word tokens to them when they
# were converted. Spaced leaders keep their text.
_LEADER_RE = re.compile(
    r"^(?P<label>.*?\S)[ \t]*(?P<dots>[.·…]{4,})[ \t]*"
    r"(?P<num>[0-9]{1,5}|[ivxlcdmIVXLCDM]{1,7}|[A-Z][-–.]?[0-9]{1,4})[ \t]*$")
# Two entries must END at the same x for the edge to be a tab stop rather than
# where one line happened to finish -- the same column evidence `_row_pairs`
# asks of a right-aligned field. A ReportLab contents page with a FIXED run of
# 60 dots after each title (x15_rl_handbook_toc) puts its numbers at 278.6,
# 300.1, 293.1... -- literal text, not a tab -- and is left exactly as it is.
_LEADER_EDGE_TOL = 2.0
_LEADER_EDGE_SHARE = 0.6   # of the page's leader lines that must share the edge


def _leader_lines(items, col_l, col_r):
    """-> ([(line, edge_x)], {id(line)}) for contents lines with dot leaders."""
    cands = []
    for kind, _bb, o in items:
        if kind != "blk":
            continue
        for ln in _blk_lines(o):
            if not ln.horizontal or not ln.spans:
                continue
            if _LEADER_RE.match(ln.text):
                cands.append(ln)
    if len(cands) < 2:
        return [], set()
    cands.sort(key=lambda l: l.bbox[2])
    kept, cur = [], [cands[0]]
    for ln in cands[1:]:
        if ln.bbox[2] - cur[0].bbox[2] <= _LEADER_EDGE_TOL:
            cur.append(ln)
            continue
        if len(cur) >= 2:
            kept.append(cur)
        cur = [ln]
    if len(cur) >= 2:
        kept.append(cur)
    out = []
    for grp in kept:
        # A tab stop holds EVERY entry to its edge; a fixed run of dots lands
        # its numbers wherever the title ended, and a few of them can agree by
        # chance (x15 puts three of eight within 0.6pt of 300.4).
        if len(grp) < _LEADER_EDGE_SHARE * len(cands):
            continue
        edge = max(l.bbox[2] for l in grp)
        out.extend((l, edge) for l in grp)
    return out, {id(l) for l, _ in out}


def _slice_runs_at(runs: List[Run], a: int, b: int) -> List[Run]:
    """Copies of `runs` covering joined-text offsets [a, b)."""
    out, pos = [], 0
    for r in runs:
        n = len(r.text)
        s, e = max(a, pos), min(b, pos + n)
        if s < e:
            out.append(replace(r, text=r.text[s - pos:e - pos]))
        pos += n
    return out


_LEADER_DOTS = re.compile(r"(?:[.·…][ \t]?){4,}")
# Text that ENDS in a dot leader, dense or spaced: a table stub the grid rule
# leaves alone (see `_grid_rows`).
_TRAILING_LEADER_RE = re.compile(
    r"^(?P<label>.*?[^.·…\s])[ \t]*(?P<dots>(?:[.·…][ \t]?){4,})[ \t]*$")


# Of a right-hand cluster's lines, the share that must close a leadered line to
# make it a contents page's number column (see _leadered_numbers).
LEADER_COLUMN_SHARE = 0.6


def _leadered_numbers(x: float, narrow, flow_blocks) -> bool:
    """Is the narrow-block cluster at `x` the page numbers of a contents page
    whose entries end in leaders -- each number on the baseline of a line that
    ends in dots? Those are the ends of rows, not a column. TeX's spaced
    leaders stay text (see _LEADER_RE), so the entry is one line and its
    number another: y24 p3's 'Using pandoc . . . 3' ends at 477.4 and its '3'
    stands at 498.5, and the two-column reading set the entries in a column
    half the page wide, every one wrapping over two lines -- a contents page
    four lines over its foot and every page after it one place late."""
    nums = [l for b in narrow if abs(b.bbox[0] - x) < 12 for l in b.lines]
    # roman too: a front matter's folios head the column ('iii', 'v' on y22)
    if not nums or not all(_NUMERIC_CELL.match(l.text.strip()) or
                           _PAGE_REF.match(l.text.strip()) for l in nums):
        return False
    others = [l for b in flow_blocks for l in b.lines
              if l.bbox[2] < x - 2 and _TRAILING_LEADER_RE.match(l.text.strip())]
    led = sum(1 for n in nums
              if any(abs(o.baseline - n.baseline) < 2.0 for o in others))
    return led >= LEADER_COLUMN_SHARE * len(nums)


def _label_before_leader(runs: List[Run], end: int) -> List[Run]:
    """The label's runs, text [0, end), without the letter-spacing the
    parser measured over a span that also held the leader.

    `parse_pdfium._span_tracking` reads letter-spacing from the mean gap
    between a span's glyphs, and a dot leader is mostly gap: on y64, spans of
    words and leader ("Civilian labor force......") measured 0.47-0.62pt
    against ~0 for the words alone. With the dots drawn by a tab, that
    tracking would only letter-space the title.
    """
    out, pos = [], 0
    for r in runs:
        n = len(r.text)
        if pos < end and r.text:
            c = replace(r, text=r.text[:max(0, min(n, end - pos))])
            if _LEADER_DOTS.search(r.text):
                c.tracking = 0.0
            if c.text:
                out.append(c)
        pos += n
    return out


def _leader_para(ln: Line, edge: float, col_l: float, col_r: float) -> Para:
    """Title, TAB, number -- against a right stop with a dot leader."""
    p = para_from_lines([ln], col_l, col_r)
    runs = runs_from_spans(ln.spans)
    text = "".join(r.text for r in runs)
    m = _LEADER_RE.match(text)
    if m is None:                       # spans re-joined differently: keep it
        return p
    label = _label_before_leader(runs, m.end("label"))
    num = _slice_runs_at(runs, m.start("num"), m.end("num"))
    dots = _slice_runs_at(runs, m.start("dots"), m.end("dots"))
    ref = (label or runs)[-1]
    tab = Run(text="\t", font=ref.font, size=ref.size,
              color=(dots[0].color if dots else ref.color), is_tab=True)
    label = [r for r in label if r.text]
    num = [r for r in num if r.text]
    # The white the source set around its leader stays: a tab's leader is
    # drawn from where the text before it ends to where the text after it
    # starts, so without these the dots touch the title and the number --
    # "INTRODUCTION.......3" for the source's "INTRODUCTION ....... 3", one
    # word where the reader, and word recall, see three (FIPS 180-4's
    # contents, 150 words a page).
    if label and text[m.end("label"):m.start("dots")].strip(" \t") == "" and \
            m.start("dots") > m.end("label"):
        label[-1] = replace(label[-1], text=label[-1].text + " ")
    if num and m.start("num") > m.end("dots"):
        num[0] = replace(num[0], text=" " + num[0].text)
    p.runs = label + [tab] + num
    p.align = "left"
    p.right_indent = 0.0
    p.first_indent = 0.0
    p.tab_stops = [(round(edge - col_l, 1), "right", "dot")]
    p.leader_text = m.group("dots")
    return p


# Contents rows whose page number is a line of its own: a TeX contents page sets
# 'Using pandoc . . . .' (spaced leader, kept as text) and its '3' as two lines
# on one baseline, and its part titles ('Synopsis', bold, no leader) beside
# theirs. Each number on the same right edge as at least TOC_ROW_MIN others,
# half of them closing a leadered entry, ends its entry's row.
TOC_ROW_MIN = 3
TOC_ROW_EDGE_TOL = 1.5
_PAGE_REF = re.compile(r"^(?:[0-9]{1,5}|[ivxlcdmIVXLCDM]{1,7})$")


def _toc_number_rows(items):
    """-> ([(entry line, number line, edge)], {id(line)}) -- see above."""
    lines = [ln for kind, _bb, o in items if kind == "blk"
             for ln in _blk_lines(o) if ln.horizontal and ln.spans]
    nums = [ln for ln in lines if _PAGE_REF.match(ln.text.strip())]
    if len(nums) < TOC_ROW_MIN:
        return [], set()
    cands = []
    for n in nums:
        # any distance: a part title ('Synopsis', 116.0) stands far from its
        # number (498.5) -- the leadered entries vouch for the column
        left = [ln for ln in lines if ln is not n and
                abs(ln.baseline - n.baseline) < 2.0 and 0 < n.bbox[0] - ln.bbox[2]]
        if len(left) == 1:
            cands.append((left[0], n))
    cands.sort(key=lambda c: c[1].bbox[2])
    out, cur = [], []

    def close(grp):
        # y12's checklists space their dots wider than a contents page's
        # (".  .  ."); _LEADER_TAIL reads both (see _drop_leader_values)
        led = sum(1 for e, _ in grp if _TRAILING_LEADER_RE.match(e.text.strip())
                  or _LEADER_TAIL.search(e.text.rstrip()))
        if len(grp) >= TOC_ROW_MIN and 2 * led >= len(grp):
            edge = max(n.bbox[2] for _, n in grp)
            out.extend((e, n, edge) for e, n in grp)

    for c in cands:
        if cur and c[1].bbox[2] - cur[0][1].bbox[2] > TOC_ROW_EDGE_TOL:
            close(cur)
            cur = []
        cur.append(c)
    if cur:
        close(cur)
    return out, {id(x) for e, n, _ in out for x in (e, n)}


# A contents or index line with a SPACED leader and its number in the line
# itself ("bg . . . . . . 126"). The dots stay text (see _LEADER_RE); what
# changes is that each entry is a paragraph of its own whose number sits on a
# right tab stop. Read as prose, an index's entries ran together into one
# paragraph per letter that re-wrapped dot by dot: y26 p206 ("bg ... 126",
# "bind ... 61", ...) came out "bg ......" / "126 bind ......" / "61 ...", two
# lines an entry, and the index took two pages more than its two.
_SPACED_LEADER_RE = re.compile(
    r"^(?P<label>.*?\S)[ \t]*(?P<dots>(?:[.·…][ \t]+){3,}[.·…])[ \t]*"
    r"(?P<num>[0-9]{1,5}(?:,[ \t]*[0-9]{1,5})*|[ivxlcdmIVXLCDM]{1,7})[ \t]*$")


TOC_LEADER_MIN_UNITS = 3
TOC_TAB_MIN_PT = 2.0        # white the tab keeps before the number


def _runs_width(runs) -> Optional[float]:
    """Predicted width of runs in the faces the writer maps them to, or None."""
    from .fonts import map_font
    from .metrics import get_metrics
    met = get_metrics()
    tot = 0.0
    for r in runs:
        w = met.text_width(r.text, map_font(r.font, mono=r.mono, serif=r.serif),
                           r.size, r.bold, r.italic)
        if w is None:
            return None
        tot += w
    return tot


def _spaced_leader_lines(items):
    """-> ([(line, edge_x)], {id(line)}) for spaced-leader lines, two or more
    ending at one edge (the tab-stop evidence of `_leader_lines`)."""
    cands = [ln for kind, _bb, o in items if kind == "blk"
             for ln in _blk_lines(o)
             if ln.horizontal and ln.spans and _SPACED_LEADER_RE.match(ln.text)]
    cands.sort(key=lambda l: l.bbox[2])
    out, cur = [], []
    for ln in cands:
        if cur and ln.bbox[2] - cur[0].bbox[2] > _LEADER_EDGE_TOL:
            if len(cur) >= 2:
                out.extend((l, max(x.bbox[2] for x in cur)) for l in cur)
            cur = []
        cur.append(ln)
    if len(cur) >= 2:
        out.extend((l, max(x.bbox[2] for x in cur)) for l in cur)
    return out, {id(l) for l, _ in out}


def _row_pitch(lines) -> Optional[float]:
    """The baseline pitch of rows set one under another, or None: the median
    step between consecutive baselines no wider than 1.6 of the type size
    (a wider step is a gap between groups, not the pitch)."""
    size = max((s.size for ln in lines for s in ln.spans if s.text.strip()), default=10.0)
    steps = []
    # each row's step to the next row of its OWN column: a contents page set
    # in two columns interleaves their baselines (y06 p2: 98.9 / 98.9, 117.9
    # / 117.9, 130.9 / 136.9 ...), and read together they gave a 9.5pt pitch
    for ln in lines:
        below = [m.baseline - ln.baseline for m in lines
                 if m is not ln and m.baseline - ln.baseline > 0.5 and
                 m.bbox[0] < ln.bbox[2] and m.bbox[2] > ln.bbox[0]]
        if below and min(below) <= 1.6 * size:
            steps.append(min(below))
    return median(steps) if steps else None


def _set_row_pitch(paras, lines) -> None:
    """A row paragraph's exact line is never taller than its rows' pitch. A
    one-line paragraph is set at 1.16 of its size, and lshort's contents
    (y22) set 10.95pt entries 12.2pt apart: at 12.7 a row, 43 rows ran 22pt
    past the page and every contents page spilled."""
    pitch = _row_pitch(lines)
    if pitch is None:
        return
    for p in paras:
        if p.leading and p.leading > pitch:
            p.leading = round(pitch, 2)


def _spaced_leader_para(ln: Line, edge: float, col_l: float, col_r: float) -> Para:
    """Title and its spaced leader as text, a TAB, the number on a right stop."""
    p = para_from_lines([ln], col_l, col_r)
    runs = runs_from_spans(ln.spans)
    text = "".join(r.text for r in runs)
    m = _SPACED_LEADER_RE.match(text)
    if m is None:
        return p
    num = [r for r in _slice_runs_at(runs, m.start("num"), m.end("num")) if r.text]
    # TeX sets its leader dots by glue; the substitute face's '. ' units are
    # wider (y26: an entry's dots ran past the number's place and the number
    # wrapped under them, two lines an entry). Dots the line has no room for
    # in the face that will draw them are left off the end, never below
    # TOC_LEADER_MIN_UNITS; a face the shaper cannot measure keeps them all.
    cuts = [m.start("dots") + k.end() for k in re.finditer(r"[.·…]", m.group("dots"))]
    nw = _runs_width(num)
    room = edge - ln.bbox[0] - (nw if nw is not None else ln.bbox[2] - ln.bbox[0]) \
        - TOC_TAB_MIN_PT
    end = cuts[-1]
    for k in range(len(cuts) - 1, TOC_LEADER_MIN_UNITS - 2, -1):
        end = cuts[k]
        hw = _runs_width(_slice_runs_at(runs, 0, end))
        if hw is None or hw <= room:
            break
    head = [r for r in _slice_runs_at(runs, 0, end) if r.text]
    if not head or not num:
        return p
    ref = head[-1]
    tab = Run(text="\t", font=ref.font, size=ref.size, color=ref.color, is_tab=True)
    p.runs = head + [tab] + num
    p.align = "left"
    p.right_indent = 0.0
    p.first_indent = 0.0
    p.tab_stops = [(round(edge - col_l, 1), "right")]
    return p


def _toc_number_para(entry: Line, num: Line, edge: float, col_l: float,
                     col_r: float) -> Para:
    """The entry, a TAB, its number -- against a right stop at the numbers'
    edge. A spaced leader stays text (see _LEADER_RE); the white TeX leaves
    between its last dot and the number (21pt on y24 p3) is the tab's."""
    p = para_from_lines([entry], col_l, col_r)
    runs = [r for r in runs_from_spans(entry.spans) if r.text]
    while runs and not runs[-1].text.strip():
        runs.pop()
    if len(runs) >= 2 and runs[0].text.strip() in BULLET_CHARS and \
            not runs[0].text.endswith((" ", "\t")) and \
            not runs[1].text.startswith((" ", "\t")):
        # a marker glued to its entry (`_merge_list_markers`) keeps the white
        # the source set after it: y12's checklist rows, "◦Verify ..."
        runs[0] = replace(runs[0], text=runs[0].text + " ")
    if runs:
        runs[-1] = replace(runs[-1], text=runs[-1].text.rstrip(" "))
    ref = runs[-1] if runs else Run(text="", font=num.spans[0].font,
                                    size=num.spans[0].size, color=num.spans[0].color)
    tab = Run(text="\t", font=ref.font, size=ref.size, color=ref.color, is_tab=True)
    p.runs = [r for r in runs if r.text] + [tab] + \
        [r for r in runs_from_spans(num.spans) if r.text]
    p.align = "left"
    p.right_indent = 0.0
    p.first_indent = 0.0
    p.tab_stops = [(round(edge - col_l, 1), "right")]
    p.bbox = bbox_union(entry.bbox, num.bbox)
    p.src_lines = 1
    p.src_widths = [round(num.bbox[2] - entry.bbox[0], 1)]
    return p


# --- rows of cells with no rules ---------------------------------------------
# A table drawn without rules is, to a parser, text fragments on shared
# baselines with wide white between them. `_merge_row_lines` joins such
# fragments with ONE space, so "Relief running   142,000   96,400   45,600"
# arrived as a single run of prose: the numbers lost their columns entirely
# (x10_chrome_tables_plain's borderless table, x13_rl_report_running's), and
# x13's rows -- then centred as a whole, because the joined line happened to
# straddle the page centre -- were displaced 117-124pt. When the fragments
# arrived as separate blocks instead (x10's third table, below a shaded header
# row), each cell became its OWN paragraph and the row stacked vertically: a
# four-cell row consumed four lines, +11.6pt per cell, 39pt by the second row.
#
# A row of cells is written the way a word processor writes one: the fragments
# separated by tabs, against tab stops at the source's own x -- a RIGHT stop at
# the cell's right edge for a number (a column of figures is right-aligned;
# editing one keeps it so), a left stop at its start otherwise.
#
# It must be a grid, not a coincidence: three or more fragments on the row, a
# second such row directly above or below it, and the two rows sharing column
# edges. Fragments must read as cells -- numbers or a few words -- because the
# one thing that also produces aligned multi-fragment rows is an unsplit
# multi-column BODY, whose fragments are lines of prose.
GRID_CELL_GAP_EM = 2.0     # white between cells, in em; word spaces are ~0.25
GRID_CELL_GAP_MIN = 12.0   # pt; and never less than _ROW_MIN_GAP's real gap
GRID_ROW_PITCH_EM = 3.2    # consecutive rows are at most this far apart
GRID_EDGE_TOL = 2.0        # pt; a shared column edge
GRID_CELL_MAX_WORDS = 4    # a cell is a few words; a prose line is not
ROW_ITEMS_MIN = 3          # separate lines on one baseline that are a row (_grid_rows)
ROW_ITEMS_MAX_GAP_EM = 3.0  # ...set at item spacing, not across the page
_NUMERIC_CELL = re.compile(r"[(+\-–−$€£¥]?\s?[0-9][0-9.,\s]*%?\)?")


def _row_fragments(row: List[Line]):
    """A baseline row's spans, grouped into cell fragments at wide gaps."""
    spans = sorted((s for ln in row for s in ln.spans if s.text.strip()),
                   key=lambda s: s.bbox[0])
    if not spans:
        return []
    frags, cur = [], [spans[0]]
    for s in spans[1:]:
        gap = s.bbox[0] - cur[-1].bbox[2]
        if gap >= max(GRID_CELL_GAP_MIN, GRID_CELL_GAP_EM * cur[-1].size):
            frags.append(cur)
            cur = [s]
        else:
            cur.append(s)
    frags.append(cur)
    return frags


def _frag_spans(frag) -> List[Span]:
    """A fragment's spans with the word space restored where they part.

    The same rule `_merge_row_lines` joins row pieces by: spans of one cell
    that the parser kept apart are still separate words. Without it a dense
    numeric table (y06's EIC tables, cells under 2em apart) welded its figures
    into tokens like "5032,2362,6302,959" -- 6% of that document's words.
    """
    out = []
    for s in frag:
        if out:
            prev = out[-1]
            gap = s.bbox[0] - prev.bbox[2]
            if gap > 0.25 * (prev.size or 10.0) and \
                    not prev.text.endswith(" ") and not s.text.startswith(" "):
                out[-1] = replace(prev, text=prev.text + " ")
        out.append(s)
    return out


def _frag_text(frag) -> str:
    return re.sub(r"\s+", " ", "".join(s.text for s in _frag_spans(frag))).strip()


def _cellish(frag) -> bool:
    t = _frag_text(frag)
    return bool(_NUMERIC_CELL.fullmatch(t)) or \
        len(t.split(" ")) <= GRID_CELL_MAX_WORDS


def _shared_edges(fa, fb) -> int:
    """Column edges two rows share, the first cell's left edge excluded."""
    ea = [s[0].bbox[0] for s in fa[1:]] + [s[-1].bbox[2] for s in fa]
    eb = [s[0].bbox[0] for s in fb[1:]] + [s[-1].bbox[2] for s in fb]
    return sum(1 for x in ea if any(abs(x - y) <= GRID_EDGE_TOL for y in eb))


def _grid_rows(items, col_l, col_r):
    """-> ([fragments-per-row], {id(line)}) for rows of a rule-less table."""
    lines = []
    for kind, _bb, o in items:
        if kind == "blk":
            lines.extend(ln for ln in _blk_lines(o) if ln.horizontal and ln.spans)
    if not lines:
        return [], set()
    lines.sort(key=lambda l: (round(l.baseline, 1), l.bbox[0]))
    rows = []
    for ln in lines:
        if rows and abs(ln.baseline - rows[-1][0].baseline) <= _ROW_BASELINE_TOL:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    info = []
    for row in rows:
        frags = _row_fragments(row)
        verbatim = all(s.mono for ln in row for s in ln.spans if s.text.strip())
        # A stub that ends in a dot leader is left as the line it was. Drawn
        # as label + dot-leader tab (y64's 540 BLS rows, dense and spaced),
        # every row fitted and the document lost its spills, but the
        # leader's dots are words to the recall metrics -- y64's doc recall
        # 0.965 -> 0.568 -- and as text, the row overran its first stop in
        # the renderer's wider spaces (+3 pages). Neither is a measured
        # improvement; such tables are a follow-up, not a guess.
        dotted = bool(frags) and \
            bool(_TRAILING_LEADER_RE.match(_frag_text(frags[0])))
        ok = len(frags) >= 3 and not verbatim and not dotted and \
            all(_cellish(f) for f in frags[1:])
        info.append((row, frags, ok))
    keep = set()
    for i in range(len(info) - 1):
        ra, fa, oka = info[i]
        rb, fb, okb = info[i + 1]
        if not (oka and okb):
            continue
        size = max(_line_size(l) for l in ra)
        if rb[0].baseline - ra[0].baseline > GRID_ROW_PITCH_EM * size:
            continue
        if _shared_edges(fa, fb) >= 2:
            keep.update((i, i + 1))
    # A table that breaks across pages can leave ONE row on a page, with its
    # partners on the previous one (x10's "March" row). Alone it cannot show a
    # shared column edge, so it must show cells instead: two or more figures.
    # Figures at the row's own size: under 0.8 of it (the footnote-number
    # bound, `_merge_list_markers`) a digit is a script -- y43's display
    # maths, "X+∞ X∞" with two exponent 2s, became a tabbed row.
    for i, (row, frags, ok) in enumerate(info):
        if not ok or i in keep:
            continue
        size = max(_line_size(l) for l in row)
        if sum(1 for f in frags[1:]
               if _NUMERIC_CELL.fullmatch(_frag_text(f))
               and max(s.size for s in f) >= 0.8 * size) >= 2:
            keep.add(i)
    # A row of items the PARSER already set apart -- three or more lines on
    # one baseline, each a few words, none overlapping -- is one row whatever
    # its gaps: a CV's contact strip (y44: five 'icon + text' items 14pt
    # apart, under the 2em cell gap above). Left as lines, each became a
    # paragraph of its own and the strip stood as a five-line staircase.
    # Lines sharing a baseline are never a stack, so they are written as the
    # row they are, each at its own tab stop.
    for i, (row, frags, ok) in enumerate(info):
        if i in keep or len(row) < ROW_ITEMS_MIN:
            continue
        items = sorted(row, key=lambda l: l.bbox[0])
        pieces = [[s for s in ln.spans if s.text.strip()] for ln in items]
        sizes = [_line_size(ln) for ln in items]
        # A strip, not a coincidence: one size (display maths puts its
        # exponents on the baseline of their sums) and item spacing (a form's
        # 'Name ... Date ... Signature' stands 130-235pt apart; y44's
        # contact items 14pt, 1.4em).
        if max(sizes) - min(sizes) > 0.6 or \
                any(b.bbox[0] - a.bbox[2] > ROW_ITEMS_MAX_GAP_EM * max(sizes)
                    for a, b in zip(items, items[1:])):
            continue
        if any(not p for p in pieces) or \
                any(b.bbox[0] < a.bbox[2] for a, b in zip(items, items[1:])) or \
                any(all(s.mono for s in p) for p in pieces) or \
                not all(_cellish(p) for p in pieces) or \
                bool(_TRAILING_LEADER_RE.match(_frag_text(pieces[0]))):
            continue
        info[i] = (row, pieces, True)
        keep.add(i)
    out, consumed = [], set()
    for i in sorted(keep):
        row, frags, _ = info[i]
        out.append(frags)
        consumed.update(id(l) for l in row)
    return out, consumed


def _grid_para(frags, col_l: float, col_r: float) -> Para:
    """One row of cells: fragments joined by tabs at their source x."""
    spans = [s for f in frags for s in f]
    bb = None
    for s in spans:
        bb = bbox_union(bb, s.bbox)
    line = Line(spans=spans, bbox=bb)
    p = para_from_lines([line], col_l, col_r)
    runs, stops = [], []
    for i, f in enumerate(frags):
        rr = runs_from_spans(_frag_spans(f))
        if rr:
            rr[0].text = rr[0].text.lstrip(" ")
            rr[-1].text = rr[-1].text.rstrip(" ")
        rr = [r for r in rr if r.text]
        if i:
            ref = runs[-1] if runs else (rr[0] if rr else None)
            runs.append(Run(text="\t", font=ref.font if ref else f[0].font,
                            size=ref.size if ref else f[0].size,
                            color=ref.color if ref else f[0].color,
                            is_tab=True))
            if _NUMERIC_CELL.fullmatch(_frag_text(f)):
                stops.append((round(f[-1].bbox[2] - col_l, 1), "right"))
            else:
                stops.append((round(f[0].bbox[0] - col_l, 1), "left"))
        runs.extend(rr)
    p.runs = runs
    p.align = "left"
    p.left_indent = max(0.0, round(frags[0][0].bbox[0] - col_l, 1))
    p.first_indent = 0.0
    p.right_indent = 0.0
    p.tab_stops = stops
    return p


# --- display maths ----------------------------------------------------------
# A displayed equation reaches inference as fragments: the expression, its
# number flush at the margin, a fraction's numerator above and denominator
# below, a sum's limits, each a block of its own (pdfTeX and the journal
# pipelines alike). Built as ordinary flow, every fragment became a paragraph
# one full line tall, stacked: y43 p2's equation (2) is 24pt in the source --
# rows at baselines 513.9 / 520.7 / 527.5 -- and was laid out as six lines,
# 70pt; every numbered equation paid a whole extra line for its number. On the
# maths-heavy papers that was most of the page inflation left once the columns
# were right (y43: 15 source pages -> 29).
#
# A display is written as what it is on the page: one paragraph per BASELINE
# ROW, the row's pieces at their own x by tab stops (the number on a right stop
# at the margin), and each row's exact line height the distance to the next
# row, so the rows overlap exactly as the source's do and the display occupies
# the source's height. LibreOffice 24.2 draws glyphs in an exact line box
# smaller than the font without clipping (measured: a 10pt row in a 6.8pt box
# renders whole, 6.8pt below the row above it).
#
# Rows chain into one display when their baselines are closer than a line of
# text could be: DISPLAY_PITCH_EM of the larger size. Prose never sets lines
# that close (the corpus' tightest body leading is 1.0em); a fraction's rows
# sit 0.68em apart (y43), a script 0.3-0.4em off its row.
DISPLAY_PITCH_EM = 0.9
# White between two pieces of one row that makes them separate pieces (an
# equation and its number, "Φ = diag(S)   or   Φ = block-diag(S)"), rather than
# words of one expression: GRID_CELL_GAP_MIN, the same "real gap" the rule-less
# table rows use.
DISPLAY_PIECE_GAP = 12.0
# A display fragment is a block of one or two baselines; a bigger block is
# prose, except that its first or last line can be a fragment the parser
# glued on (y43 p2's denominator "2" opens the next paragraph's block) when it
# is no wider than this share of the column.
DISPLAY_EDGE_FRAG_FRAC = 0.35
# An equation number at a column edge: "(1)", "(12a)", "(A.3)", "(S2)".
_EQNO_RE = re.compile(r"^\(\s*[A-Z]?\d{1,3}(\.\d{1,3})*[a-z]?\s*\)$")
# Faces that set mathematics, by `_font_key` prefix. A display must show
# maths -- one of these, or a mathematical operator in its text -- before its
# rows are touched: rows of short text that merely sit close are left alone.
_MATH_FONTS = ("cmmi", "cmsy", "cmex", "cmbsy", "cmmib", "msam", "msbm",
               "eufm", "eufb", "eurm", "eusm", "rsfs", "mtmi", "mtsy", "mtex",
               "rmtmi", "txmi", "txsy", "txex", "pxmi", "pxsy", "pxex",
               "ntxmi", "ntxsy", "ntxex", "newtxmi", "mnsymbol", "stixmath",
               "stixtwomath", "latinmodernmath", "lmmath", "cambriamath",
               "xitsmath", "libertinemath", "esint", "stmary", "wasy",
               "symbol", "mtextra")
_MATH_CHARS = frozenset("=+−×÷±∓∑∏∫∮∂∇√∞≤≥≠≈≡∼∝∈∉⊂⊃⊆⊇∪∩∧∨→←↔⇒⇐⇔∀∃"
                        "αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ")
# Accents TeX draws as glyphs of their own above a letter (y40's "Û" is a
# "ˆ" 1.6pt above the U's baseline). A row of nothing else is an overlay on
# the row beneath it, not a row of the display: it rides along when its
# neighbour is in one and never makes a display out of a line of prose.
_ACCENTS = frozenset("ˆ˜¯˙¨´`ˇ˘˚^~·→⃗") | frozenset(chr(c) for c in range(0x300, 0x370))


# A line of PROSE with a script set below it chains like a display -- y40 p1's
# "where Ω = Ns × M = (0, 1) × (0, T], T is fixed time, ..." over a lone "t" --
# and as a display row it would be given the 2.5pt pitch to its script, which
# a wrapped line of text cannot survive. Words decide it: a display row reads
# as symbols and operators with the odd "max" or "if"; prose carries words.
_WORD_RE = re.compile(r"[A-Za-z]{3,}")
DISPLAY_MAX_WORDS = 3


def _prose_row(row: List[Line]) -> bool:
    text = " ".join(s.text for l in row for s in l.spans
                    if not _font_key(s.font).startswith(_MATH_FONTS))
    return len(_WORD_RE.findall(text)) > DISPLAY_MAX_WORDS


def _accent_row(row: List[Line]) -> bool:
    chars = [ch for l in row for ch in l.text if not ch.isspace()]
    return bool(chars) and all(ch in _ACCENTS for ch in chars)


def _font_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", (name or "").lower())


def _mathy(lines) -> bool:
    for ln in lines:
        for s in ln.spans:
            if _font_key(s.font).startswith(_MATH_FONTS):
                return True
            if any(ch in _MATH_CHARS for ch in s.text):
                return True
    return False


def _row_pieces(row: List[Line]) -> List[List[Line]]:
    """A baseline row's lines, grouped left to right into pieces at
    DISPLAY_PIECE_GAP."""
    row = sorted(row, key=lambda l: ink_extent(l.spans[0])[0] if l.spans
                 else l.bbox[0])
    pieces = [[row[0]]]
    for ln in row[1:]:
        x1 = max(l.bbox[2] for l in pieces[-1])
        if ln.bbox[0] - x1 >= DISPLAY_PIECE_GAP:
            pieces.append([ln])
        else:
            pieces[-1].append(ln)
    return pieces


def _display_rows(items, col_l: float, col_r: float):
    """-> ([rows per display], {id(line)}) for displayed equations.

    Each display is a list of rows top to bottom, each row a list of Lines on
    one baseline. See DISPLAY_PITCH_EM for what chains rows."""
    width = max(1.0, col_r - col_l)
    cands = []
    for kind, _bb, o in items:
        if kind != "blk":
            continue
        lines = [ln for ln in _blk_lines(o) if ln.horizontal and ln.spans
                 and ln.text.strip()]
        if not lines:
            continue
        bases = sorted({round(ln.baseline, 0) for ln in lines})
        if len(bases) <= 2:
            cands.extend(lines)
            continue
        lines.sort(key=lambda l: (l.baseline, l.bbox[0]))
        for edge in (lines[0], lines[-1]):
            if edge.bbox[2] - edge.bbox[0] <= DISPLAY_EDGE_FRAG_FRAC * width:
                cands.append(edge)
    if len(cands) < 2:
        return [], set()
    cands.sort(key=lambda l: (l.baseline, l.bbox[0]))
    rows = []
    for ln in cands:
        if rows and abs(ln.baseline - rows[-1][0].baseline) <= \
                max(1.2, 0.18 * _line_size(rows[-1][0])):
            rows[-1].append(ln)
        else:
            rows.append([ln])
    groups, cur = [], [rows[0]]
    for prev, row in zip(rows, rows[1:]):
        em = max(max(_line_size(l) for l in prev), max(_line_size(l) for l in row))
        if row[0].baseline - prev[0].baseline < DISPLAY_PITCH_EM * em:
            cur.append(row)
        else:
            groups.append(cur)
            cur = [row]
    groups.append(cur)
    out, consumed = [], set()
    for g in groups:
        lines = [l for r in g for l in r]
        if not _mathy(lines):
            continue
        real = [r for r in g if not _accent_row(r)]
        if not real:
            continue
        if len(real) >= 2 and any(_prose_row(r) for r in real):
            continue                # a line of text and its scripts
        if len(real) < 2:
            pieces = _row_pieces(real[0])
            if len(pieces) < 2:
                continue
            # one row: an equation and its number, or an expression broken
            # at a wide space -- both need a number at the edge to be told
            # from a row of a table or a label beside its value
            if not any(_EQNO_RE.match(" ".join(l.text for l in p).strip())
                       for p in (pieces[0], pieces[-1])):
                continue
        out.append(g)
        consumed.update(id(l) for l in lines)
    return out, consumed


# A glyph or three set ABOVE or BELOW a line of text rather than beside it --
# the "∼" TeX stacks over "=" to draw ≅, a script whose line the parser broke
# off, an accent -- arrives as a line of its own in a block of its own. Built
# as flow it became a paragraph a full line tall between the lines of its
# paragraph: y43 p4's two-line "Examples. Lie Groups G ≅ G/{e} ..." came out
# as five paragraphs, +30pt, and the page spilled. Such a fragment belongs to
# the line it sits on: within FRAG_REACH_EM of that line's baseline, inside
# its horizontal extent, and much narrower than it.
FRAG_REACH_EM = 0.75       # the host's em box, as `_merge_row_lines` uses
FRAG_MAX_SHARE = 0.25      # of the host's width: a few glyphs, not a line
FRAG_SCRIPT_SIZE = 0.85    # smaller than this share of the host: a script
FRAG_MAX_GLYPHS = 3        # longer non-maths text is a line, not a fragment
# The same line's own continuation, cut off where a script was lifted out of
# it: y43 p4's "...diagonal matrices {diag(e" / ", . . . , e" / ") : θk ∈
# [0, 2π)}." share baseline 595.8 in three blocks, 11.0 and 12.0pt apart --
# past the dialect's fragment join, and each became a one-line paragraph. Once
# the row constructs (tables, label/field rows) have taken their lines, a piece
# of maths on the same baseline starting within this many ems of a line's end,
# and a few glyphs wide against it (FRAG_MAX_SHARE), continues it. A
# neighbouring column's line is neither: prose, and as wide as the line.
FRAG_JOIN_GAP_EM = 1.5


def _insert_spans(host: List[Span], frags: List[Span]) -> List[Span]:
    """`host` with `frags` placed in reading order by x.

    A host span is often a whole line, so sorting by span start would put a
    fragment that sits over the middle of it after its end. A host span the
    fragment falls inside is cut at the character the fragment stands over,
    by the span's mean advance -- a character either way at worst."""
    out = sorted(host, key=lambda s: s.bbox[0])
    for f in sorted(frags, key=lambda s: s.bbox[0]):
        fx = f.bbox[0]
        k = 0
        while k < len(out) and out[k].bbox[2] <= fx:
            k += 1
        if k < len(out) and out[k].bbox[0] < fx and out[k].text:
            s = out[k]
            adv = (s.bbox[2] - s.bbox[0]) / max(1, len(s.text))
            cut = int(round((fx - s.bbox[0]) / adv)) if adv > 0 else 0
            if 0 < cut < len(s.text):
                xc = s.bbox[0] + cut * adv
                a, b = copy.copy(s), copy.copy(s)   # keeps set-on attributes
                a.text, a.bbox = s.text[:cut], (s.bbox[0], s.bbox[1], xc, s.bbox[3])
                b.text, b.bbox = s.text[cut:], (xc, s.bbox[1], s.bbox[2], s.bbox[3])
                b.origin = (xc, s.origin[1])
                out[k:k + 1] = [a, f, b]
                continue
            if cut >= len(s.text):
                k += 1
        out.insert(k, f)
    return out


def _absorb_fragments(items):
    """`items` with small fragment lines moved into the line they are set on.
    Lines are edited in place; a block left empty is dropped."""
    blocks = [o for kind, _bb, o in items if kind == "blk"]
    lines = [(bi, ln) for bi, o in enumerate(blocks) for ln in _blk_lines(o)
             if ln.horizontal and ln.spans and ln.text.strip()]
    if len(lines) < 2:
        return items
    moved, hosts = set(), set()
    # left to right, so a line's continuation pieces join it one after another
    lines.sort(key=lambda t: (round(t[1].baseline), t[1].bbox[0]))
    size = {id(ln): _line_size(ln) for _bi, ln in lines}
    widest = max(ln.bbox[2] - ln.bbox[0] for _bi, ln in lines)
    for bi, fr in lines:
        if id(fr) in moved or id(fr) in hosts:
            continue
        fsz = size[id(fr)]
        fw = fr.bbox[2] - fr.bbox[0]
        # Only maths, or a glyph or three, is ever a fragment (both branches
        # below); deciding that first keeps a page of prose linear here.
        # A short line of WORDS set close above another is a heading or a
        # running head (x07's "Network Planning", 9.3pt over its body line),
        # not a script of it.
        if fw > FRAG_MAX_SHARE * widest:
            continue
        mathy = _mathy([fr])
        if not mathy and len(fr.text.strip()) > FRAG_MAX_GLYPHS:
            continue
        best = None
        for hj, h in lines:
            if h is fr or id(h) in moved:
                continue
            hsz = size[id(h)]
            hw = h.bbox[2] - h.bbox[0]
            if fsz > hsz + 0.1:
                continue
            d = abs(fr.baseline - h.baseline)
            if d < 0.05 * hsz:
                # a continuation: maths, a few glyphs wide -- never the line of
                # a neighbouring column, which is prose as wide as its own
                gap = fr.bbox[0] - h.bbox[2]
                if hj == bi or fw > FRAG_MAX_SHARE * hw or not mathy \
                        or not 0.0 <= gap <= FRAG_JOIN_GAP_EM * hsz:
                    continue
                if best is None or gap < best[0]:
                    best = (gap, h)
                continue
            if fw > FRAG_MAX_SHARE * hw or d > FRAG_REACH_EM * hsz:
                continue
            em = 0.5 * hsz
            if fr.bbox[0] < h.bbox[0] - em or fr.bbox[2] > h.bbox[2] + em:
                continue
            if best is None or d < best[0]:
                best = (d, h)
        if best is None:
            continue
        h = best[1]
        hsz = size[id(h)]
        if abs(fr.baseline - h.baseline) < 0.05 * hsz and h.spans and \
                fr.bbox[0] - h.bbox[2] > 0.25 * hsz and \
                not h.spans[-1].text.endswith(" "):
            last = copy.copy(h.spans[-1])
            last.text += " "
            h.spans = h.spans[:-1] + [last]
        for s in fr.spans:
            if s.size < FRAG_SCRIPT_SIZE * hsz and \
                    fr.baseline < h.baseline - 0.12 * hsz:
                s.superscript = True
        h.spans = _insert_spans(h.spans, fr.spans)
        # Horizontally only: the host keeps its own line box, or the
        # fragment's height above it closes the gap to the paragraph before
        # and the two paragraphs merge.
        h.bbox = (min(h.bbox[0], fr.bbox[0]), h.bbox[1],
                  max(h.bbox[2], fr.bbox[2]), h.bbox[3])
        moved.add(id(fr))
        hosts.add(id(h))
    if not moved:
        return items
    out = []
    for kind, bb, o in items:
        if kind == "blk":
            ls = _blk_lines(o)
            keep = [l for l in ls if id(l) not in moved]
            if not keep:
                continue
            if len(keep) != len(ls):
                ls[:] = keep
                if isinstance(o, TextBlock):
                    o.bbox = _mk_block(keep).bbox
                bb = _mk_block(keep).bbox
        out.append((kind, bb, o))
    return out


def _display_paras(rows, col_l: float, col_r: float) -> List[Para]:
    """One paragraph per row of a display; see the block comment above."""
    bases = [r[0].baseline for r in rows]
    pitches = [b - a for a, b in zip(bases, bases[1:])]
    out = []
    for i, row in enumerate(rows):
        pieces = _row_pieces(row)
        size = max(_line_size(l) for l in row)
        runs, stops = [], []
        for k, piece in enumerate(pieces):
            spans = sorted((s for l in piece for s in l.spans if s.text),
                           key=lambda s: s.bbox[0])
            rr = runs_from_spans(_frag_spans(spans))
            if rr:
                rr[0].text = rr[0].text.lstrip(" ")
                rr[-1].text = rr[-1].text.rstrip(" ")
            rr = [r for r in rr if r.text]
            if not rr:
                continue
            if runs:
                ref = runs[-1]
                runs.append(Run(text="\t", font=ref.font, size=ref.size,
                                color=ref.color, is_tab=True))
                x0 = min(l.bbox[0] for l in piece)
                x1 = max(l.bbox[2] for l in piece)
                text = " ".join(l.text for l in piece).strip()
                if k == len(pieces) - 1 and x1 >= col_r - 3.0 and \
                        _EQNO_RE.match(text):
                    stops.append((round(col_r - col_l, 1), "right"))
                else:
                    stops.append((round(x0 - col_l, 1), "left"))
            runs.extend(rr)
        if not runs:
            continue
        x0 = min(l.bbox[0] for l in row)
        p = Para(runs=runs, align="left", tab_stops=stops)
        p.left_indent = max(0.0, round(x0 - col_l, 1))
        p.bbox = None
        for l in row:
            p.bbox = bbox_union(p.bbox, l.bbox)
        natural = round(max(size * 1.16, 4.0), 2)
        if pitches:
            pitch = pitches[i] if i < len(pitches) else pitches[-1]
            p.leading = round(min(natural, pitch), 2)
        else:
            p.leading = natural
        p._b1 = row[0].baseline
        p._size1 = size
        p._vis_lines = 1
        p._display = True
        p.src_lines = 1
        p.src_widths = [round(max(l.bbox[2] for l in row) - x0, 1)]
        out.append(p)
    return out


_GAP_TOL = 0.5   # pt of overlap forgiven between an element and a line box (rounding)


def _split_blocks_at_elements(items):
    """Cut text blocks wherever a rule, image or figure lies between two of
    their lines.

    The flow is ordered at BLOCK granularity: a block sorts by its top, is
    expanded into paragraphs afterwards, and every element sorts by its own
    top. A rule that sits between two lines of one block therefore sorts after
    the whole block. Measured on the owner's résumé, where PDFium returns each
    section heading and the paragraph under it as ONE block: the rule under
    "SUMMARY" (y=124.5) was emitted after the summary text (131.4-182.1), so
    the heading lost its rule, the text gained one, and a ~20pt hole opened
    before the next heading -- 2 of the page's 6 rules (defect catalogue #8;
    1 of 19 on y13_irs_pub501). A drawn separator between two lines is
    evidence that they are not one block, so the block is cut there.

    Only elements in a genuine GAP qualify: no line box of the block may
    share any of the element's vertical extent. The whole box, descender zone
    included, is the test, because a rule inside it belongs to that line --
    an underline, or a table border the text sits on: y06_irs_1040's
    unrecognised flowchart table draws its row borders 0.5pt below a
    baseline, and a test that trimmed the descender zone cut its cells
    apart mid-sentence. Likewise an element beside the text, which shares
    the lines' vertical extent, never cuts. Tables are not considered: they
    consume the lines they hold, and the flow blocks are already cut around
    consumed lines.
    """
    els = [bb for kind, bb, o in items
           if kind == "el" and bb is not None
           and isinstance(o, (RuleEl, ImageEl, FigureEl))]
    if not els:
        return items
    out = []
    for kind, bb, o in items:
        if kind != "blk":
            out.append((kind, bb, o))
            continue
        lines = list(o) if isinstance(o, list) else list(o.lines)
        if len(lines) < 2:
            out.append((kind, bb, o))
            continue
        cuts = []
        for e in els:
            if e[2] <= bb[0] or e[0] >= bb[2] or e[1] <= bb[1] or e[3] >= bb[3]:
                continue
            crossed = False
            for ln in lines:
                if ln.bbox[1] + _GAP_TOL < e[3] and e[1] < ln.bbox[3] - _GAP_TOL:
                    crossed = True
                    break
            if not crossed:
                cuts.append((e[1] + e[3]) / 2.0)
        if not cuts:
            out.append((kind, bb, o))
            continue
        groups = defaultdict(list)
        for ln in lines:
            cy = (ln.bbox[1] + ln.bbox[3]) / 2.0
            groups[sum(1 for c in cuts if cy > c)].append(ln)
        for k in sorted(groups):
            blk = _mk_block(groups[k])
            out.append(("blk", blk.bbox, blk))
    return out


def _propagate_list_hangs(paras):
    """Give single-line typed-marker items the hang their siblings measured.

    A one-line item carries no continuation line to measure its hang from, so
    it would wrap flush under its marker the moment a reader's metrics push a
    word over -- unlike every sibling in the same list. Siblings share the
    marker column (within `_INLINE_X_TOL`) and the hang is a property of the
    list, so the commonest hang measured at that column is adopted, across
    the document: x17 sets the same list style on both pages and only page 1
    has a wrapped item to measure. The hang is carried as a WIDTH, so an item
    in a column with a different left edge still gets its own indents right.
    """
    hangs = []
    for p in paras:
        if getattr(p, "_list_item", False) and p.first_indent < -1.0 and p.bbox:
            hangs.append((p.bbox[0], getattr(p, "_list_style", None),
                          round(-p.first_indent, 1)))
    if not hangs:
        return
    for p in paras:
        if not (getattr(p, "_list_item", False) and p.bbox
                and abs(p.first_indent) <= 1.0 and p.align in ("left", "justify")):
            continue
        style = getattr(p, "_list_style", None)
        near = Counter(h for x0, st, h in hangs
                       if st == style and abs(p.bbox[0] - x0) <= _INLINE_X_TOL)
        if near:
            h = near.most_common(1)[0][0]
            p.left_indent = round(p.left_indent + p.first_indent + h, 1)
            p.first_indent = -h


def _to_flow(items, col_l, col_r, doc_rows=None, forced=None):
    """`forced`: a text edge; also break paragraphs where the source broke a
    line short of it by hand (`_forced_break`) -- inside panels and layout
    columns only."""
    items = _split_blocks_at_elements(items)
    leaders, lconsumed = _leader_lines(items, col_l, col_r)
    if lconsumed:
        items = _drop_row_lines(items, lconsumed) + \
            [("leader", ln.bbox, (ln, edge)) for ln, edge in leaders]
    tocrows, tconsumed = _toc_number_rows(items)
    if tconsumed:
        items = _drop_row_lines(items, tconsumed) + \
            [("tocrow", bbox_union(e.bbox, n.bbox), (e, n, edge))
             for e, n, edge in tocrows]
    spaced, sconsumed = _spaced_leader_lines(items)
    if sconsumed:
        items = _drop_row_lines(items, sconsumed) + \
            [("spaced", ln.bbox, (ln, edge)) for ln, edge in spaced]
    displays, dconsumed = _display_rows(items, col_l, col_r)
    if dconsumed:
        def _dbb(rows):
            b = None
            for r in rows:
                for l in r:
                    b = bbox_union(b, l.bbox)
            return b
        items = _drop_row_lines(items, dconsumed) + \
            [("display", _dbb(d), d) for d in displays]
    grid, gconsumed = _grid_rows(items, col_l, col_r)
    if gconsumed:
        def _fbb(frags):
            b = None
            for f in frags:
                for s in f:
                    b = bbox_union(b, s.bbox)
            return b
        items = _drop_row_lines(items, gconsumed) + \
            [("grid", _fbb(f), f) for f in grid]
    list_starts = _inline_list_starts(
        [list(o) if isinstance(o, list) else list(o.lines)
         for kind, _bb, o in items if kind == "blk"])
    pairs, consumed = _row_pairs(items, col_l, col_r, doc_rows)
    if consumed:
        items = _drop_row_lines(items, consumed) + \
            [("row", bbox_union(l.bbox, r.bbox), (l, r)) for l, r in pairs]
    # After every row construct has taken its lines: what is left on a shared
    # baseline is a broken line of prose, not cells.
    items = _absorb_fragments(items)
    out = []
    row_paras = []
    for kind, bb, o in sorted(items, key=lambda t: (t[1][1], t[1][0])):
        if kind == "leader":
            out.append(_leader_para(o[0], o[1], col_l, col_r))
        elif kind == "tocrow":
            out.append(_toc_number_para(o[0], o[1], o[2], col_l, col_r))
            row_paras.append(out[-1])
        elif kind == "spaced":
            out.append(_spaced_leader_para(o[0], o[1], col_l, col_r))
            row_paras.append(out[-1])
        elif kind == "display":
            out.extend(_display_paras(o, col_l, col_r))
        elif kind == "grid":
            out.append(_grid_para(o, col_l, col_r))
        elif kind == "row":
            out.append(_row_para(o[0], o[1], col_l, col_r))
        elif kind == "blk":
            out.extend(paras_from_line_list(
                list(o) if isinstance(o, list) else list(o.lines), col_l, col_r,
                list_starts, forced=forced))
        else:
            el = o
            if isinstance(el, TableEl):
                el.left_indent = max(0.0, round((el.bbox[0] if el.bbox else col_l) - col_l, 1))
                # A table whose borders hang left of the column by no more
                # than its first column's left pad -- its text on the column,
                # the way Word draws every table -- records the hang. c3's
                # tables stand 7.5pt left of their text column; clamped at
                # the column, LibreOffice drew them 7.7pt right of the source
                # (within2pt 0.000) while Word 2010 layout, which hangs the
                # border by the cell margin, drew them right.
                hang = round(col_l - el.bbox[0], 1) if el.bbox else 0.0
                lead = [r[0].pad[1] for r in el.rows
                        if r and r[0] is not None and len(r[0].pad) >= 4]
                if el.role not in ("box", "cards") and hang > 0.5 and lead \
                        and hang <= min(lead) + 1.0:
                    el.hang_left = hang
                # A panel wider than its column bleeds where the source drew
                # it: y46's full-bleed summary band (0-595 on a 28pt margin)
                # started at the margin and ran 28pt off the paper.
                if el.role in ("box", "cards") and el.bbox and \
                        el.bbox[0] < col_l - 2.0 and \
                        el.bbox[2] - el.bbox[0] > col_r - col_l + 2.0:
                    el.left_indent = round(el.bbox[0] - col_l, 1)
            elif isinstance(el, (FigureEl, ImageEl)):
                bbx = _el_bbox(el)
                if bbx:
                    cx = (bbx[0] + bbx[2]) / 2
                    if abs(cx - (col_l + col_r) / 2) < 8:
                        el.align = "center"
                    else:
                        el.align = "left"
                        el.left_indent = max(0.0, round(bbx[0] - col_l, 1))
            out.append(el)
    if row_paras:
        _set_row_pitch(row_paras, [ln for ln, _ in spaced] +
                       [e for e, _, _ in tocrows])
    return out


# How far apart (in ems of the text) two right-to-left fragments may stand and
# still join when the first one's last line is full: 1.5-line leading leaves
# 0.48em between line boxes (y49: 5.7pt at 12pt), double spacing ~1em.
RTL_JOIN_GAP_EM = 1.1


def _mergeable(a: Para, b: Para, col_l: Optional[float] = None,
               col_r: Optional[float] = None) -> bool:
    if a.heading or b.heading:
        return False
    # A paragraph that carries its own line breaks (verbatim blocks, the
    # ladder's line-locked encoding) is a sequence of source lines, not a
    # reflowable run of prose. Merging it with a neighbour joins the two
    # with a space and undoes the break structure both were built with.
    if getattr(a, "line_breaks", False) or getattr(b, "line_breaks", False):
        return False
    if any(r.is_tab for r in b.runs):
        return False
    if any(r.is_tab for r in a.runs) and not _item_runs_on(a, col_r):
        return False
    # A display's rows are rows of one equation, set at their own pitch.
    if getattr(a, "_display", False) or getattr(b, "_display", False):
        return False
    if a.align in ("center", "right") or b.align in ("center", "right"):
        return False
    if not a.bbox or not b.bbox:
        return False
    # A paragraph opening with a typed list marker is a new item, however
    # tight the list's leading: y17_rfc9110 p40 sets its four "• …" items
    # 2.7pt apart, inside the 3.2pt join window, and they fused into one
    # paragraph (design audit B16).
    if getattr(b, "_list_item", False):
        return False
    # Likewise a footnote that opens with its own number (`_opens_note`),
    # and a paragraph the source opened by hand (`_forced_break`).
    if getattr(b, "_note", False) or getattr(b, "_forced", False):
        return False
    # ...and one whose first line is INDENTED from its others: that indent is
    # how the source opened it. A fragment continuing `a` begins on a wrapped
    # line, flush with its paragraph. y12 p31: the column's last words, "the
    # same wording.", cut from a line welded across the gutter, sat 2.7pt of
    # box above "If a substitute ...", indented 12pt and 6pt lower than a line
    # pitch, and the join made one paragraph of the two whose leading was
    # read off that gap -- 16.95pt for 11.5pt lines, 44pt over nine lines.
    if b.first_indent > 1.0 and b.align in ("left", "justify"):
        return False
    # Paragraphs continue each other only in one direction, and a
    # right-to-left paragraph continues at its START, which is its right
    # edge: its ragged last line ends anywhere on the left (see _rtl_lines).
    rtl = getattr(a, "rtl", False)
    if rtl != getattr(b, "rtl", False):
        return False
    gap = b.bbox[1] - a.bbox[3]
    reach = 3.2
    if rtl and col_l is not None and col_r is not None and a.src_widths:
        # A right-to-left fragment whose last line runs edge to edge has not
        # ended: in justified text only the paragraph's last line stops short.
        # That is evidence enough to join across 1.5-line leading, which the
        # 3.2pt window cannot span: y49 p1 sets its 12pt body at a 17.7pt
        # pitch (5.7pt between line boxes), the page's tight contents list
        # split every body line into a block of its own, and each became a
        # paragraph that re-wrapped onto two lines -- p1 alone filled 2 pages.
        last_l = a.bbox[2] - a.src_widths[-1]
        sz = max((r.size for r in a.runs if r.text.strip()), default=10.0)
        if abs(a.bbox[2] - col_r) <= FULL_EDGE_PT and \
                abs(last_l - col_l) <= FULL_EDGE_PT:
            reach = max(reach, RTL_JOIN_GAP_EM * sz)
    if not (-2.0 <= gap <= reach):
        return False
    # A justified right-to-left paragraph whose last line stops short has
    # ended (see _short_line_ends_para); the next one is a new paragraph.
    if rtl and a.align == "justify" and len(a.src_widths) >= 2:
        sz = max((r.size for r in a.runs if r.text.strip()), default=10.0)
        if a.src_widths[-1] < max(a.src_widths) - SHORT_END_EM * sz:
            return False
    # An item that hangs continues at its TEXT column, not at its marker: a
    # paragraph starting under the marker is the next paragraph after the
    # list, and one starting at the hang is the item's own continuation.
    if rtl:
        ax = a.bbox[2]
        if getattr(a, "_list_item", False) and a.first_indent < -1.0:
            ax = a.bbox[2] + a.first_indent
        if abs(b.bbox[2] - ax) > 2.5:
            return False
    else:
        ax = a.bbox[0]
        if (getattr(a, "_list_item", False) or getattr(a, "_marker_tab", False)) \
                and a.first_indent < -1.0:
            ax = a.bbox[0] - a.first_indent
        if abs(b.bbox[0] - ax) > 2.5 and not _runs_in(a, b):
            return False
    sa = max((r.size for r in a.runs if r.text.strip()), default=0)
    sb = max((r.size for r in b.runs if r.text.strip()), default=0)
    return abs(sa - sb) < 0.6


def _item_runs_on(a: Para, col_r: Optional[float]) -> bool:
    """Does the marker item `a`, whose one tab follows its marker, run on into
    the next fragment? Only when the item's last line was FULL: a line breaker
    moves a word down only when it does not fit, so a last line that reaches
    the column's right edge wrapped rather than ended.

    EUR-Lex sets each recital as a marker cell and a text cell, and its first
    line, glued to its "(4)" (`_merge_list_markers`), arrives as a block of its
    own above the other lines of the recital. Measured on y18_eurlex_ai_act p2:
    "(4)\tAI is a fast evolving ... and" ends at 527.9 on a 527.9 column, and
    the recital's next line starts at 93.6, the item's text column. Kept
    apart, the first line was a one-line paragraph with no slack at the
    measure, and the substitute face wrapped its last word onto a line of its
    own: one line per recital, four or five a page, which put 2-4 lines of
    every page over its foot (144 pages rendered 240).
    """
    if col_r is None or not getattr(a, "_marker_tab", False) or \
            getattr(a, "rtl", False) or \
            (a.first_indent >= -1.0 and not getattr(a, "_run_in", False)) or \
            sum(1 for r in a.runs if r.is_tab) != 1 or not a.src_widths:
        return False
    x0 = a.bbox[0] if getattr(a, "_vis_lines", 1) == 1 or getattr(a, "_run_in", False) \
        else a.bbox[0] - a.first_indent
    return x0 + a.src_widths[-1] >= col_r - FULL_EDGE_PT


def _runs_in(a: Para, b: Para) -> bool:
    """Is `b` the rest of the one-line marker item `a`, set back at the
    marker's own edge rather than at the item's text (a run-in number: "2.",
    a gap, the text, and the next line under the "2.")? `_item_runs_on`
    has already said that `a`'s line wrapped."""
    return getattr(a, "_marker_tab", False) and a.first_indent < -1.0 and \
        getattr(a, "_vis_lines", 1) == 1 and not getattr(a, "rtl", False) and \
        abs(b.bbox[0] - a.bbox[0]) <= 2.5


def _merge_flow_paras(seq, col_r, col_l=None):
    out = []
    for el in seq:
        if out and isinstance(el, Para) and isinstance(out[-1], Para) \
                and _mergeable(out[-1], el, col_l, col_r):
            a = out[-1]
            if _runs_in(a, el):
                # The item's lines return to the margin under its number: the
                # number keeps its tab to the text, the paragraph its edge.
                a.left_indent = max(0.0, round(a.left_indent + a.first_indent, 1))
                a.first_indent = 0.0
                a._run_in = True
            if getattr(a, "_vis_lines", 1) == 1 and el.bbox and a.bbox:
                delta = round(el.bbox[1] - a.bbox[1], 2)
                if getattr(a, "_marker_tab", False) and \
                        getattr(a, "_b1", None) is not None and \
                        getattr(el, "_b1", None) is not None:
                    # the item's box took its marker's in, so its pitch is
                    # read from the baselines (y18 p55: 10.7 by the boxes,
                    # 10.5 by the baselines, as every other line of the page)
                    delta = round(el._b1 - a._b1, 2)
                if delta > 2:
                    a.leading = delta
            if getattr(a, "rtl", False) and col_l is not None:
                was_flush = abs(a.bbox[0] - col_l) < 3.0   # its END edge
            else:
                was_flush = abs(a.bbox[2] - col_r) < 3.0
            _soft_join(a.runs, el.text, dehyphenate=was_flush)
            a.runs += el.runs
            a.bbox = bbox_union(a.bbox, el.bbox)
            a._vis_lines = getattr(a, "_vis_lines", 1) + getattr(el, "_vis_lines", 1)
            # The SOURCE description has to accumulate too. `_vis_lines` did
            # and `src_lines` did not, so a merged paragraph claimed only its
            # first fragment's line count -- 5169 lines against 6935 on
            # y12_irs_pub15, 4217 against 5324 on y13. That is not a geometry
            # bug: `_para_box` measures height from `_vis_lines`, so the
            # emitted layout was always right. It is a bug in what the layout
            # SAYS about the source, and the consumers of that are the quality
            # ladder, which compares a predicted re-wrap against
            # `src_lines`/`src_widths` and needs them to describe the whole
            # paragraph, and the table-cell height in docxout. Both counts move
            # together so `len(src_widths) == src_lines` survives the merge.
            a.src_lines = (a.src_lines or 0) + (el.src_lines or 0)
            if a.src_widths or el.src_widths:
                a.src_widths = list(a.src_widths) + list(el.src_widths)
            if was_flush and a.align == "left":
                a.align = "justify"
            continue
        out.append(el)
    return out


_DIGIT_RUN = re.compile(r"\d+|.", re.S)
_MIRRORED = dict(zip("()[]{}<>", ")(][}{><"))


def _neutral_rtl_text(t: str) -> str:
    """The logical text of a fragment with no letters drawn in an RTL context.

    A list number separated from its Hebrew item (y49's contents: `2.` set a
    tab's width right of its entry) is a line of its own with no RTL letter, so
    the parser left it in visual order -- `.2`. Read at an RTL base, digits stay
    a unit, everything else reverses and brackets mirror
    (parse_pdfium._visual_to_logical for the letterless case).
    """
    units = _DIGIT_RUN.findall(t)
    return "".join(_MIRRORED.get(u, u) for u in reversed(units))


def _is_marker_line(ln: Line, rtl_form: bool = False) -> bool:
    t = ln.text.strip()
    if rtl_form:
        # The visual form of a right-to-left number marker: `.2` for `2.`.
        # Only ever glued to a right-to-left item (see _merge_list_markers).
        if re.search(r"[^\W\d_]", t):
            return False
        t = _neutral_rtl_text(t)
    # Bare digits count too: step/badge lists number their items "1", "2"
    # without trailing punctuation, and some producers emit each such
    # marker as its own block. Only the separated-marker merge uses this
    # (it still demands a shared baseline with adjacent item text); the
    # inline marker split keeps the stricter NUM_RE.
    #
    # So do a numbered heading's section numbers, "2.5" and "2.5.1": Word
    # sets them a tab ahead of the heading text, and they arrive as a block
    # of their own (y30: "2.5" at x 70.9-88.9, "Licence holder and contact
    # person details" at 113.5 on the same baseline). Unglued, every heading
    # stood a line taller than its source and the page went over.
    return (ln.bbox[2] - ln.bbox[0]) < 44 and bool(
        t in BULLET_CHARS or NUM_RE.match(t) or
        (t.isdigit() and len(t) <= 3) or SECTION_NUM_RE.match(t))


def _has_item_beside(ln: Line, own, flow_blocks, opens_block: bool = False) -> bool:
    """Does another block hold text on `ln`'s baseline, a marker's gap to its
    right (the test `_merge_list_markers` glues by)? Only for a marker that
    STARTS its line at the block's own left edge, where a heading's number
    stands: on a two-column page a block's last line can be a lone "S." at
    the column's right end, with the other column's text a gutter away
    (y41, IEEEtran: glued across the gutter, within-2pt 0.063 -> 0.031).

    `opens_block`: the text must be the FIRST line of its block -- the item's
    first line in a block of its own, which is the run-in shape the opening
    marker rule exists for (all 304 of y18's run-in numbers glue to a
    one-line block). A line in the middle of another block is that block's
    text, already placed in its reading order: y61's three-column Federal
    Register page welds "Mail: OPP Docket, Environmental | Consistent with
    ... | vegetable subgroup ..." across its gutters, line 11 of a 14-line
    block, and its column-1 bullet glued onto it was pulled out of its own
    column and 69pt of that column's flow went with it (dy_p50 33.3 ->
    39.0pt against the accepted wp18-m2 sweep)."""
    left = min(l.bbox[0] for l in own.lines)
    if ln.bbox[0] - left > MARKER_LEFT_TOL_EM * max(_line_size(ln), 1.0):
        return False
    for c in flow_blocks:
        if c is own:
            continue
        for fl in (c.lines[:1] if opens_block else c.lines):
            gap = fl.bbox[0] - ln.bbox[2]
            if fl.spans and abs(fl.baseline - ln.baseline) < 2.5 and \
                    -1.0 < gap < 60:
                return True
    return False


# How far a block-ending marker may start from its block's left edge, in em.
MARKER_LEFT_TOL_EM = 1.0


_LEADER_TAIL = re.compile(r"[^.·…\s][ \t]*(?:[.·…][ \t]{0,3}){4,}$")


def _drop_leader_values(marker_lines, flow_blocks):
    """`marker_lines` without the bare numbers that CLOSE a leadered line on
    their own baseline: those are a leader row's value -- a page reference,
    an amount -- standing at its end, not a marker opening the next item.

    `_is_marker_line` accepts bare digits for step lists, and the glue
    takes whatever text starts within 60pt to their right. y12_irs_pub15 p8
    sets two checklists side by side, each row "Verify work eligibility of
    new employees . . . . . . ." with its page number ("7", "25", "44") at
    the left list's edge, 20-30pt short of the right list's checkboxes and
    items: every number was glued in front of the other list's row -- "7•◦",
    "File Form 944 ... 7not required" -- and those rows, reaching across the
    page's gutter, were laid out under both columns. The same evidence
    `_leadered_numbers` reads for a contents page's number column: a line
    ending in dots on the number's baseline, left of it -- dots set up to
    three spaces apart, as y12 sets them (".  .  ."), where the contents
    page's own pattern stops at one."""
    leadered = [l for b in flow_blocks for l in b.lines
                if _LEADER_TAIL.search(l.text.rstrip())]
    if not leadered:
        return marker_lines
    out = []
    for ln, b in marker_lines:
        if ln.text.strip().isdigit() and any(
                abs(o.baseline - ln.baseline) < 2.0 and
                o.bbox[2] <= ln.bbox[0] + 1.0 for o in leadered):
            continue
        out.append((ln, b))
    return out


def _merge_list_markers(flow_blocks):
    """Some producers (WeasyPrint) emit list markers as separate blocks —
    sometimes several markers stacked in ONE block. Glue each marker line back
    onto the item text line that shares its baseline."""
    marker_lines = []
    rtl_forms = set()
    any_rtl = any(getattr(l, "rtl", False) for b in flow_blocks for l in b.lines)
    for b in flow_blocks:
        if all(_is_marker_line(l) or (any_rtl and _is_marker_line(l, rtl_form=True))
               or not l.text.strip() for l in b.lines):
            for l in b.lines:
                if _is_marker_line(l):
                    marker_lines.append((l, b))
                elif any_rtl and _is_marker_line(l, rtl_form=True):
                    marker_lines.append((l, b))
                    rtl_forms.add(id(l))
        elif len(b.lines) > 1 and _is_marker_line(b.lines[-1]) and \
                _has_item_beside(b.lines[-1], b, flow_blocks):
            # A marker that ENDS a block of prose: in text set at one pitch
            # throughout, a heading's "B." sits a line below the paragraph
            # above it and overlaps its column, so the block builder took it
            # into that block while its item text, a marker's gap to the
            # right, began the next (y63's "B.  Prevailing Party", "I.
            # DISCUSSION"). Left there, the marker closed the paragraph above
            # and its item stood a line lower, alone.
            marker_lines.append((b.lines[-1], b))
        elif len(b.lines) > 1 and _is_marker_line(b.lines[0]) and \
                not _is_marker_line(b.lines[1]) and \
                _has_item_beside(b.lines[0], b, flow_blocks, opens_block=True):
            # A marker that OPENS a block of the item's other lines: a
            # numbered paragraph set run-in, its number at the margin, its
            # first line an indent to the right in a block of its own, and
            # its other lines back at the margin under the number. EUR-Lex's
            # articles (y18 p55: "2." at 67.4, "When assessing ..." at 89.0
            # on its baseline, "criteria:" at 67.4 below) -- left there, the
            # number opened the block of the item's LAST lines ("2.
            # criteria:", two lines) and the first line stood alone above it.
            marker_lines.append((b.lines[0], b))
    marker_lines = _drop_leader_values(marker_lines, flow_blocks)
    marker_ids = {id(l) for l, _ in marker_lines}
    consumed = set()
    for ln, b in marker_lines:
        best = None  # (gap, line, block)
        raised = False
        msz = _line_size(ln)
        for c in flow_blocks:
            for fl in c.lines:
                if id(fl) in marker_ids or id(fl) in consumed or not fl.spans:
                    continue
                gap = fl.bbox[0] - ln.bbox[2]
                # A right-to-left item puts its marker on its RIGHT (y49's
                # contents list: `2.` 26pt right of its entry), and stranded
                # there it became a one-digit paragraph of its own.
                rtl_right = getattr(fl, "rtl", False) and \
                    ln.bbox[0] >= fl.bbox[2] - 1.0
                if rtl_right:
                    gap = ln.bbox[0] - fl.bbox[2]
                elif id(ln) in rtl_forms:
                    continue
                if abs(fl.baseline - ln.baseline) < 2.5 and -1.0 < gap < 60:
                    if best is None or gap < best[0]:
                        best = (gap, fl, c)
                        raised = False
                    continue
                # A footnote's own number: a SMALL digit set raised against
                # the note's first line and abutting it. x05_lo_quotes_notes'
                # are 4.6pt on 8.5pt notes, 3.1pt up -- outside the 2.5pt
                # baseline test above, so each number became a 5pt paragraph
                # of its own AFTER its note (it sits 0.4pt lower on the page).
                fsz = _line_size(fl)
                rise = fl.baseline - ln.baseline
                if msz <= 0.8 * fsz and 0.0 < rise <= 0.6 * fsz and \
                        -1.0 < gap < 0.5 * fsz:
                    if best is None or gap < best[0]:
                        best = (gap, fl, c)
                        raised = True
        if best is not None:
            _, fl, c = best
            if raised:
                # The note's line keeps ITS baseline: `Line.baseline` reads
                # the first span, and the paragraph is anchored on it.
                host_base = fl.baseline
                # A number opening a left-to-right line opens a NOTE, and
                # each note is its own paragraph: y50's one-line notes,
                # 11.5pt apart, had been kept apart only by the stray number
                # paragraphs between them, and once glued they merged into
                # one paragraph that re-wrapped as prose. At the LEFT end of
                # a right-to-left line the same mark is an in-text reference
                # closing that line (y50's body), not a note.
                opens = not _RTL_TEXT.search(fl.text) or (
                    getattr(fl, "rtl", False) and ln.bbox[0] >= fl.bbox[2] - 1.0)
                for s in ln.spans:
                    s.superscript = True
                    s.origin = (s.origin[0], host_base)
                    s._note_mark = opens
            if id(ln) in rtl_forms:
                # Read at the item's direction: `.2` is `2.`.
                for s in ln.spans:
                    s.text = _neutral_rtl_text(s.text)
                ln.spans.reverse()
                if not ln.spans[-1].text.endswith(" "):
                    ln.spans[-1].text += " "
            if getattr(fl, "rtl", False) and ln.bbox[2] <= fl.bbox[0] + 1.0:
                # Left of a right-to-left line is its logical END.
                fl.spans.extend(ln.spans)
            else:
                fl.spans[0:0] = list(ln.spans)
            fl.bbox = bbox_union(fl.bbox, ln.bbox)
            c.bbox = bbox_union(c.bbox, ln.bbox)
            consumed.add(id(ln))
    if not consumed:
        return flow_blocks
    out = []
    for b in flow_blocks:
        keep = [l for l in b.lines if id(l) not in consumed]
        if not keep:
            continue
        if len(keep) == len(b.lines):
            out.append(b)
            continue
        bb = None
        for l in keep:
            bb = bbox_union(bb, l.bbox)
        out.append(TextBlock(lines=keep, bbox=bb))
    return out


def column_grid(line_boxes, content_l: float, content_r: float):
    """Column bands of a >=3 column page, or None.

    Columns are defined by what is NOT there: a gutter is a vertical band the
    text does not cross. Measuring the gutters rather than the column starts
    makes the test independent of how the parser happened to group lines into
    blocks, and independent of indents inside a column -- an indent ladder
    produces many left-edge clusters but no empty band.

    Deliberately restricted to three columns or more. Two-column pages already
    have a detector with its own tuned thresholds and a reference fixture
    (c2_paper2col); rerouting them through this one could only put that
    behaviour at risk for no measured gain.
    """
    n = int(round(content_r - content_l))
    if n < 120 or not line_boxes:
        return None
    scan = [lb for lb in line_boxes
            if (lb[2] - lb[0]) <= COL_SCAN_W_FRAC * (content_r - content_l)]
    if len(scan) < 12:
        return None
    occ = [0] * n
    for lb in scan:
        a = max(0, int(lb[0] - content_l))
        b = min(n, int(math.ceil(lb[2] - content_l)))
        for i in range(a, b):
            occ[i] += 1
    # A heading spanning the whole page crosses a real gutter, so a gutter is
    # a band almost nothing crosses rather than one nothing crosses. The
    # occupancy above already read only the NARROW lines: a spanning line
    # cannot be column content by construction, and counting it against
    # the gutters it spans is how real grids with a few spanning notes
    # lost their detection -- measured on the IRS instructions, whose
    # three-column pages carry spanning cautions at ~4-7% of lines and
    # fell through to the two-column path, whose split then landed on the
    # THIRD column's start and poured columns one and two into one flow
    # with page-absolute indents (182pt inside 165pt sections, every word
    # wrapping; the booklet class's 2.3x page inflation). Spanning lines
    # are still ASSIGNED afterwards, by `_column_of`, exactly as before.
    tol = max(1, int(GUTTER_CROSS_FRAC * len(scan)))
    gutters, i = [], 0
    while i < n:
        if occ[i] > tol:
            i += 1
            continue
        j = i
        while j < n and occ[j] <= tol:
            j += 1
        # an empty run touching either edge is a margin, not a gutter
        if i > 0 and j < n and (j - i) >= MIN_GUTTER_W:
            gutters.append((content_l + i, content_l + j))
        i = j
    if len(gutters) < 2:
        return None
    edges = [content_l] + [x for g in gutters for x in g] + [content_r]
    bands = [(edges[k], edges[k + 1]) for k in range(0, len(edges) - 1, 2)]
    if len(bands) < 3:
        return None
    widths = [b - a for a, b in bands]
    # The band-width floor is the safety the narrow-line scan needs: the
    # scan admits a numeric table's cells as readily as a document's text
    # columns, and only width tells them apart -- y03_nist_fips197's byte
    # table reads as a 5-16 band grid with bands of 49-70pt, where a
    # document's text column is never narrower than ~80pt (a three-column
    # letter page runs ~165pt). Held out here, kept out of the flow.
    if min(widths) < MIN_GRID_BAND_PT:
        return None
    if min(widths) <= 0:
        return None
    # Regularity is tested on the column PITCH, not on the inked band widths.
    # A band is bounded by ink, so a column whose text does not fill it reads
    # narrow: a ragged final column, or one a short right-margin estimate cuts
    # off, fails a width test while the grid behind it is exact. The IRS
    # booklets are the case -- y13_irs_pub501 p2 is three columns starting at
    # x=42/222/402 with pitches 180 and 180, inked widths 168/171/145, and the
    # width test rejected 22 of its 31 pages. Those pages fell through to the
    # two-column path, which merged two of the three columns and emitted
    # 1037pt of content into a 768pt body.
    #
    # Pitch is the grid's own property and content cannot narrow it. It also
    # keeps refusing forms, which is what the width test was really for: a
    # ruled form's bands are 34, 14, 9, 9... and its pitches are just as
    # irregular.
    starts = [a for a, _ in bands]
    pitches = [starts[i + 1] - starts[i] for i in range(len(starts) - 1)]
    if min(pitches) <= 0 or \
            max(pitches) - min(pitches) > GRID_WIDTH_TOL * max(pitches):
        return None                      # not a regular grid
    # Snap the bands out to the grid the pitch describes. They arrive ink
    # bounded and ASSIGNMENT uses them, so a paragraph that fills its column
    # but overhangs the measured band by a point is called page-spanning and
    # drops out of the columns entirely.
    col_w = (sum(pitches) / len(pitches)) - \
        (sum(g1 - g0 for g0, g1 in gutters) / len(gutters))
    if col_w <= 0:
        return None
    bands = [(a, max(b, a + col_w)) for a, b in bands]
    for a, b in bands:
        if sum(1 for lb in line_boxes if lb[0] >= a - 2 and lb[2] <= b + 2) \
                < MIN_COL_LINES:
            return None                  # a band carrying no text is not a column
    return bands


def _band_of(bb, bands) -> Optional[int]:
    """Index of the column band containing bb, or None if it spans bands."""
    for i, (a, b) in enumerate(bands):
        if bb[0] >= a - 2 and bb[2] <= b + 2:
            return i
    return None


def _column_of(bb, bands) -> Optional[int]:
    """Which column bb belongs to, or None if it genuinely spans them.

    `_band_of` answers "does this fit inside a column", which is the right
    question for deciding whether something is full-width furniture and the
    wrong one for deciding where it goes. A bullet hanging into the gutter, a
    hyphen poking past the measured edge, an indented sub-item -- each fits no
    band and is not remotely page-wide, and routing those to the page-spanning
    tail linearises them: measured on y13_irs_pub501 p6, 21 paragraphs became a
    1122pt single-column tail beneath three balanced ~600pt columns, which is
    worse than not recognising the grid at all.

    So width decides. Something wider than one and a half columns really does
    span them and stays out of the grid; anything column-sized belongs to the
    column it overlaps most, and only ties fall back to its centre.
    """
    i = _band_of(bb, bands)
    if i is not None:
        return i
    col_w = max(1e-6, sum(b - a for a, b in bands) / len(bands))
    if (bb[2] - bb[0]) > COL_SPAN_FRAC * col_w:
        return None                      # genuinely spans the grid
    best, best_ov = None, 0.0
    for k, (a, b) in enumerate(bands):
        ov = min(bb[2], b) - max(bb[0], a)
        if ov > best_ov:
            best, best_ov = k, ov
    if best is not None:
        return best
    cx = (bb[0] + bb[2]) / 2.0
    return min(range(len(bands)),
               key=lambda k: abs(cx - (bands[k][0] + bands[k][1]) / 2.0))


def _grid_chunks(elements, flow_blocks, bands, lay: DocLayout,
                 content_l: float, content_r: float) -> List[Chunk]:
    """Lay a >=3 column page out as lead / columns / tail."""
    lay_rows = getattr(lay, "_row_evidence", None)
    banded, spanning = [], []
    for b in flow_blocks:
        groups = defaultdict(list)
        for l in b.lines:
            groups[_column_of(l.bbox, bands)].append(l)
        for bi, ls in groups.items():
            blk = _mk_block(ls)
            (spanning if bi is None else banded).append(
                (bi, ("blk", blk.bbox, blk)))
    for e in elements:
        bb = _el_bbox(e) or (content_l, 0.0, content_r, 0.0)
        bi = _column_of(bb, bands)
        (spanning if bi is None else banded).append((bi, ("el", bb, e)))
    if not banded:
        return []
    col_y0 = min(item[1][1] for _, item in banded)
    lead = [item for _, item in spanning if item[1][3] <= col_y0 + 4]
    tail = [item for _, item in spanning if item[1][3] > col_y0 + 4]

    chunks: List[Chunk] = []
    if lead:
        lead.sort(key=lambda t: (t[1][1], t[1][0]))
        ch = Chunk(n_cols=1)
        ch.elements = _merge_flow_paras(
            _to_flow(lead, content_l, content_r, doc_rows=lay_rows), content_r,
            content_l)
        chunks.append(ch)
    gaps = [bands[i + 1][0] - bands[i][1] for i in range(len(bands) - 1)]
    ch = Chunk(n_cols=len(bands), col_gap=max(10.0, round(sum(gaps) / len(gaps), 1)))
    flows = []
    for i, (a, b) in enumerate(bands):
        items = sorted((t for bi, t in banded if bi == i),
                       key=lambda t: (t[1][1], t[1][0]))
        flows.append(_merge_flow_paras(
            _to_flow(items, a, b, doc_rows=lay_rows), b, a))
        for el in flows[-1]:
            el._col = (a, b)          # see _assemble_chunks
    ch.elements = flows[0]
    for f in flows[1:]:
        ch.elements = ch.elements + [ColBreak()] + f
    chunks.append(ch)
    if tail:
        tail.sort(key=lambda t: (t[1][1], t[1][0]))
        ch2 = Chunk(n_cols=1)
        ch2.elements = _merge_flow_paras(
            _to_flow(tail, content_l, content_r, doc_rows=lay_rows), content_r,
            content_l)
        chunks.append(ch2)
    return chunks


# --- side-by-side regions -----------------------------------------------------
# Designed pages put things NEXT to each other that the flow can only stack:
# shaded panels in two columns (y58_ssa_statement), a sidebar beside the main
# column of a résumé, a ragged-left column against a dotted rule (y46). The
# two-column detector above reads only text-block left edges, so it cannot see
# a column made of panels, and it refuses a column narrower than 35% of the
# page by construction (a sidebar résumé's 140pt sidebar is 27%). Either way
# the page was linearised: panels stacked, sidebar lines interleaved with the
# main column's by baseline.
#
# A side-by-side region is found the way column_grid finds gutters -- by what
# is NOT there -- but over the page's ITEMS (blocks and built elements), not
# its lines: a split x that no item crosses over a band of the page, with
# items on both sides sharing that band. It is laid out only on evidence the
# ordinary two-column path never had (`_side_evidence`).
SBS_MIN_GUTTER = 6.0        # pt of white between the sides: y58's is 8.5
SBS_MIN_BAND_PT = 72.0      # the sides share at least an inch of the page
# A picture beside text is a masthead -- y58's 58pt seal beside its title,
# y46's 65pt photo beside the name -- when it is a picture and not an icon:
# both measure at least this, where y06's TIP/CAUTION icons are 35pt and a
# section tag 21pt. The flow stacked such a picture above the text beside it
# and paid its whole height again: +58pt on y58's first page.
SBS_FIG_MIN_PT = 40.0
# docxout._write_cell_blocks' 1pt carrier after a nested table, plus a point.
NESTED_CARRIER_PT = 2.0
SBS_MIN_SIDE_PT = 60.0      # a side narrower than this is a marker or a stub
# How far a side may overhang the equal columns a section would give it and
# still be set in one. A box's text, not its shading, has to fit -- y58's
# panels bleed 9pt past the text margin on both sides -- and a line drawn
# into the margin is pulled back by at most this much: y58's right-aligned
# date ends 9.5pt past the measured right edge, against the panels' own.
SBS_EQUAL_TOL = 12.0
# A sidebar is the narrow side of an unequal split. 0.35 is the bar the
# two-column detector applies to its right column; below it that detector
# never fires, which is exactly the population this rule exists for.
SBS_SIDEBAR_FRAC = 0.35
# ...beside a MAIN column: the wide side carries at least half the width.
SBS_MAIN_FRAC = 0.5
# Each side is a column of text, not a few labels: five lines at least (the
# sidebar fixture's narrower side has 12, its main column 9), and most of
# them flush at one left edge (all of the fixture's but one wrapped bullet).
SBS_SIDEBAR_MIN_LINES = 5
SBS_FLUSH_SHARE = 0.6
# Two sides whose lines share baselines row by row are one list of label/value
# rows -- a form -- not two columns. Columns set independently coincide by
# chance: the sidebar fixture shares 1 baseline in 9.
SBS_ROW_SHARE_MAX = 0.5
# A drawn separator in the gutter (a rule, or a dotted rule drawn as dots) must
# run alongside at least this share of the band.
SBS_RULE_COVER = 0.5


def _fit_extent(item):
    """(x0, x1) of what must fit in a column: a box's text, else its box."""
    kind, bb, o = item
    if isinstance(o, TableEl) and o.role in ("box", "cards"):
        xs = [p.bbox for row in o.rows for c in row if c for p in c.paras if p.bbox]
        if xs:
            return min(b[0] for b in xs), max(b[2] for b in xs)
    return bb[0], bb[2]


def _side_splits(items, x_lo: float, x_hi: float):
    """Every vertical split of `items`, best first: [(x, band, gl, gr)].

    `band` is a list of (item index, side) -- side 0 left, 1 right -- for a
    run of items, in reading order, that no item crossing x interrupts, with
    both sides sharing at least half of the shorter side's height; gl/gr are
    the gutter's edges. The candidates are the items' own left edges: a
    column starts where its text does. Ranked by the items a band holds."""
    idx = [i for i, it in enumerate(items) if it[1] is not None]
    cand = sorted({round(items[i][1][0], 1) for i in idx
                   if x_lo + SBS_MIN_SIDE_PT <= items[i][1][0] <= x_hi - SBS_MIN_SIDE_PT})
    order = sorted(idx, key=lambda i: (items[i][1][1], items[i][1][0]))
    found = []
    for xs in cand:
        bands, cur = [], []
        for i in order:
            bb = items[i][1]
            if bb[2] <= xs - SBS_MIN_GUTTER:
                cur.append((i, 0))
            elif bb[0] >= xs - 0.5:
                cur.append((i, 1))
            elif cur:
                bands.append(cur)
                cur = []
        if cur:
            bands.append(cur)
        for band in bands:
            L = [items[i][1] for i, s in band if s == 0]
            R = [items[i][1] for i, s in band if s == 1]
            if not L or not R:
                continue
            ly0, ly1 = min(b[1] for b in L), max(b[3] for b in L)
            ry0, ry1 = min(b[1] for b in R), max(b[3] for b in R)
            if min(ly1, ry1) - max(ly0, ry0) < 0.5 * min(ly1 - ly0, ry1 - ry0):
                continue
            gl, gr = max(b[2] for b in L), min(b[0] for b in R)
            if gr - gl < SBS_MIN_GUTTER:
                continue
            # The split must be clean over the band's whole HEIGHT, not just
            # in reading order: an item outside the band that crosses x while
            # standing beside it means the sides are arranged around that
            # item. y59's callouts flank a mock-up whose leader lines make
            # one picture spanning all three; split there, the picture was
            # stacked above a table of callouts and the page ran to three.
            y0, y1 = min(ly0, ry0), max(ly1, ry1)
            members = {i for i, _s in band}
            if any(i not in members and items[i][1][3] > y0 + 2.0 and
                   items[i][1][1] < y1 - 2.0 and
                   items[i][1][0] < xs - SBS_MIN_GUTTER and items[i][1][2] > xs - 0.5
                   for i in idx):
                continue
            found.append(((len(band), y1 - y0), xs, band, gl, gr))
    found.sort(key=lambda f: f[0], reverse=True)
    return [f[1:] for f in found]


def _split_side(items):
    """A side of a side-by-side region, cut again where all of it splits
    cleanly (y46's masthead: the name beside the contact list, beside the
    photo). -> list of sides, left to right."""
    if len(items) < 2:
        return [items]
    xs_lo = min(it[1][0] for it in items)
    xs_hi = max(it[1][2] for it in items)
    for xs, band, _gl, _gr in _side_splits(items, xs_lo - SBS_MIN_SIDE_PT,
                                           xs_hi + SBS_MIN_SIDE_PT):
        if len(band) == len(items):
            left = [items[i] for i, s in band if s == 0]
            right = [items[i] for i, s in band if s == 1]
            if _rows_not_columns(_side_lines(left), _side_lines(right)):
                continue        # a role and its date: one row, two fields
            return _split_side(left) + _split_side(right)
    return [items]


def _rows_not_columns(ll, rl) -> bool:
    """Do two sides' lines pair up baseline by baseline, as the fields of
    rows do (a form's labels and values, a role and its date), rather than
    run independently, as columns' do? See SBS_ROW_SHARE_MAX."""
    if not ll or not rl:
        return False
    narrow, other = (ll, rl) if len(ll) <= len(rl) else (rl, ll)
    shared = sum(1 for a in narrow
                 if any(abs(a.baseline - b.baseline) <= _ROW_BASELINE_TOL for b in other))
    return shared > SBS_ROW_SHARE_MAX * len(narrow)


def _side_lines(items):
    out = []
    for kind, _bb, o in items:
        if kind == "blk":
            out.extend(_blk_lines(o))
    return out


def _side_evidence(left, right, gl: float, gr: float, page: PageIR,
                   content_w: float) -> Optional[str]:
    """Why these two sides are columns, or None.

    'figure'    a picture stands beside text (a masthead's logo or photo)
    'panel'     a shaded or bordered box stands on one side: designed regions
    'rule'      a drawn separator runs down the gutter (y46's dotted rule)
    'sidebar'   a narrow independent column the two-column path cannot see
    """
    for side, other in ((left, right), (right, left)):
        if len(side) == 1 and isinstance(side[0][2], (FigureEl, ImageEl)) and \
                _side_lines(other) and \
                max(it[1][2] for it in other) - min(it[1][0] for it in other) \
                >= SBS_MIN_SIDE_PT:
            # (text beside it, not a gutter of line numbers: y63's pleading
            # numbers stand beside its signature image)
            fb = side[0][1]
            oy0 = min(it[1][1] for it in other)
            oy1 = max(it[1][3] for it in other)
            # ...and the text is BESIDE the picture, not a column the picture
            # merely shares a stretch of: half the text's own height lies
            # alongside it. A paper's figure at the foot of one column beside
            # the other column's last 300pt is a two-column page, not a
            # masthead (y41 p5).
            if min(fb[2] - fb[0], fb[3] - fb[1]) >= SBS_FIG_MIN_PT and \
                    min(fb[3], oy1) - max(fb[1], oy0) >= 0.5 * (oy1 - oy0):
                return "figure"
    if max(it[1][3] for it in left + right) - min(it[1][1] for it in left + right) \
            < SBS_MIN_BAND_PT:
        return None
    for kind, _bb, o in left + right:
        if isinstance(o, TableEl) and o.role in ("box", "cards"):
            return "panel"
    ll, rl = _side_lines(left), _side_lines(right)
    lw = max(it[1][2] for it in left) - min(it[1][0] for it in left)
    rw = max(it[1][2] for it in right) - min(it[1][0] for it in right)
    # Below this every other test is about two COLUMNS OF TEXT: a court
    # pleading's 1-28 line numbers stand beside its text behind a drawn
    # rule, and are a gutter of numbers, not a column.
    if len(ll) < SBS_SIDEBAR_MIN_LINES or len(rl) < SBS_SIDEBAR_MIN_LINES or \
            min(lw, rw) < SBS_MIN_SIDE_PT:
        return None
    y0 = min(it[1][1] for it in left + right)
    y1 = max(it[1][3] for it in left + right)
    # a rule inside a built element is that element's own (a table's column
    # rule: RFC 9110's method table, PLOS One's results tables)
    owned = [_expand(it[1], 2.0) for it in left + right if it[0] == "el"]
    spans = []
    for d in page.drawings:
        x0, dy0, x1, dy1 = d.bbox
        if gl <= (x0 + x1) / 2 <= gr and (x1 - x0) <= RULE_THICK + 1.0 \
                and dy1 > y0 and dy0 < y1 and \
                not any(contains(o, d.bbox, 0.0) for o in owned):
            spans.append((max(y0, dy0), min(y1, dy1)))
    if spans:
        spans.sort()
        cover, (a, b) = 0.0, spans[0]
        for s0, s1 in spans[1:]:
            # a dotted rule is dots a few points apart: bridge those gaps
            if s0 <= b + 6.0:
                b = max(b, s1)
            else:
                cover += b - a
                a, b = s0, s1
        cover += b - a
        if cover >= SBS_RULE_COVER * (y1 - y0):
            return "rule"
    if min(lw, rw) >= SBS_SIDEBAR_FRAC * content_w or \
            max(lw, rw) < SBS_MAIN_FRAC * content_w:
        return None
    # Both sides are text COLUMNS: most of each side's lines start at one x.
    # Side-by-side matter that is not -- a display equation and its number,
    # a table's stub beside its body, LaTeX source beside its typeset output
    # (lshort, FIPS 197) -- starts its lines wherever its content puts them.
    for lines in (ll, rl):
        edge = _mode([ln.bbox[0] for ln in lines], 0)
        if sum(1 for ln in lines if abs(ln.bbox[0] - edge) <= 2.0) \
                < SBS_FLUSH_SHARE * len(lines):
            return None
    narrow = ll if lw <= rw else rl
    other = rl if lw <= rw else ll
    shared = sum(1 for a in narrow
                 if any(abs(a.baseline - b.baseline) <= _ROW_BASELINE_TOL for b in other))
    if shared > SBS_ROW_SHARE_MAX * len(narrow):
        return None
    return "sidebar"


def _stack_in(els, top: float) -> float:
    """Baseline-anchored space_before for a column's elements from `top`."""
    cursor = top
    for el in els:
        bb = _el_bbox(el)
        if bb is None:
            continue
        if isinstance(el, Para):
            t, h = _para_box(el)
            el.space_before = max(0.0, round(t - cursor, 1))
            cursor = t + h
        else:
            el.space_before = max(0.0, round(bb[1] - cursor, 1))
            cursor = bb[3]
    return cursor


def _text_edge(items) -> float:
    """Right edge of a side's TEXT -- its own wrap and alignment edge, which a
    tag or picture standing further out does not move (y46's left column is
    right-aligned to 276.4 beside section tags reaching 287)."""
    xs = [it[1][2] for it in items if it[0] == "blk"] + \
        [_fit_extent(it)[1] for it in items
         if isinstance(it[2], TableEl) and it[2].role in ("box", "cards")]
    return max(xs) if xs else max(_fit_extent(it)[1] for it in items)


def _lines_item(lines):
    lines = sorted(lines, key=lambda l: (round(l.baseline, 1), l.bbox[0]))
    blk = _mk_block(lines)
    return ("blk", blk.bbox, blk)


def _column_flow(items, col_l: float, box_r: float, lay_rows):
    """A side's flow, read against its own text edge and placed in a column
    whose right edge is `box_r`: every paragraph keeps the difference as a
    right indent, so it wraps -- and right-aligns -- where the source did."""
    col_r = min(box_r, _text_edge(items))
    # One column is one text stream. Its lines arrive as many blocks -- the
    # parser cut them wherever the OTHER column's lines interleaved, so the
    # sidebar fixture's every line is a block of its own -- and paragraphs
    # are only read inside a block. Rejoin each run of blocks no element
    # interrupts, so the column's own breaks decide its paragraphs.
    joined, run = [], []
    for it in _by_pos(items):
        if it[0] == "blk":
            run.extend(_blk_lines(it[2]))
            continue
        if run:
            joined.append(_lines_item(run))
            run = []
        joined.append(it)
    if run:
        joined.append(_lines_item(run))
    edge = _text_column_edge(_side_lines(items))
    if not (edge is None or edge < 0 or
            _flush_right_edge(_side_lines(items)) is not None):
        edge = col_r
    flow = _merge_flow_paras(_to_flow(joined, col_l, col_r, doc_rows=lay_rows,
                                      forced=edge), col_r)
    extra = max(0.0, round(box_r - col_r, 1))
    for el in flow:
        # The right indent holds a WRAPPING paragraph to its source measure,
        # and a right-aligned or centred one to its source edge. A one-line
        # left-aligned paragraph has no measure to keep, and pinning its
        # width to its own source line is what wraps it the moment the
        # substitute face is a hair wider (the sidebar fixture's 20pt name).
        if isinstance(el, Para) and extra > 0.0 and \
                ((el.src_lines or 1) > 1 or el.align in ("right", "center")):
            el.right_indent = round((el.right_indent or 0.0) + extra, 1)
        if isinstance(el, Para) and el.align == "right" and el.bbox and \
                (el.src_lines or 1) <= 1:
            # A right-aligned column (y46's left side) sets every line by its
            # right edge; the left indent only bounds the wrap, and at the
            # source's own x it leaves no room for a substitute face a hair
            # wider -- each title wrapped and the column overflowed into
            # the next. See RIGHT_LINE_SLACK.
            w = el.bbox[2] - el.bbox[0]
            el.left_indent = round(max(0.0, el.left_indent - RIGHT_LINE_SLACK * w), 1)
        if isinstance(el, RuleEl) and getattr(el, "_bbox", None):
            # rules carry page-relative indents until a flow places them
            el.left_indent = max(0.0, round(el._bbox[0] - col_l, 1))
        # A panel keeps the x its shading was drawn at, into the margin if the
        # source bled it there (y58's panels start 9pt left of their text).
        if isinstance(el, TableEl) and el.role in ("box", "cards") and el.bbox:
            el.left_indent = round(el.bbox[0] - col_l, 1)
    return flow


def _layout_table(sides, top: float, bottom: float, content_l: float,
                  content_r: float, lay_rows) -> TableEl:
    """A borderless one-row table, one cell per side: the unequal-column form.

    Google Docs imports only equal-width column sections (testkit/
    ooxml_audit.py's RISK note), and a sidebar is unequal by definition; a
    layout table is what a word processor's own résumé templates use, and
    every renderer honours its column widths. A side that is ONE panel becomes
    the cell itself -- its shading, borders and pads -- so a shaded sidebar is
    a shaded cell, not a box nested in one."""
    panels = []
    for its in sides:
        p = None
        if len(its) == 1 and isinstance(its[0][2], TableEl) and \
                its[0][2].role == "box" and its[0][2].bbox:
            p = its[0][2]
        panels.append(p)
    # cell edges: a panel's own box, else the gutter's far side
    edges = []
    for k, its in enumerate(sides):
        if panels[k] is not None:
            x0, x1 = panels[k].bbox[0], panels[k].bbox[2]
        else:
            x0 = min(it[1][0] for it in its)
            x1 = max(_fit_extent(it)[1] for it in its)
        edges.append([x0, x1])
    edges[0][0] = min(edges[0][0], content_l)
    edges[-1][1] = max(edges[-1][1], content_r)
    cells, widths = [], []
    left = edges[0][0]
    for k, its in enumerate(sides):
        x0, x1 = edges[k]
        if k:
            if panels[k] is not None and panels[k - 1] is not None:
                # two shaded panels never touch: the white between them is
                # a column of its own
                cells.append(Cell(borders={}, pad=(0.0, 0.0, 0.0, 0.0)))
                widths.append(max(0.0, x0 - left))
                left = x0
            elif panels[k] is None:
                x0 = left               # a text side owns the gutter before it
        right = x1 if (panels[k] is not None or k == len(sides) - 1) \
            else (edges[k + 1][0] if panels[k + 1] is not None else
                  min(it[1][0] for it in sides[k + 1]))
        # No cell carries a bottom pad: the writer pins the row at least to
        # the region's height instead (see write_table on role "layout").
        if panels[k] is not None:
            cell = copy.copy(panels[k].rows[0][0])
            pt, pl, _pb, pr = cell.pad
            cell.pad = (round(pt + max(0.0, panels[k].bbox[1] - top), 1), pl, 0.0, pr)
            cell.blocks = []
        else:
            flow = _column_flow(its, x0, right, lay_rows)
            _stack_in(flow, top)
            for el in flow:
                if isinstance(el, TableEl) and el.rows and el.rows[0] and \
                        el.rows[-1][0] is not None and len(el.rows[-1][0].pad) >= 4:
                    # A box nested in a column is followed by the 1pt
                    # carrier paragraph a cell must end with: take it out of
                    # the box's own bottom pad, with a point for rounding, so
                    # a panel drawn to the foot of the page still ends on it.
                    c = el.rows[-1][0]
                    c.pad = (c.pad[0], c.pad[1],
                             max(0.0, round(c.pad[2] - NESTED_CARRIER_PT, 1)), c.pad[3])
            cell = Cell(borders={}, pad=(0.0, 0.0, 0.0, 0.0))
            cell.blocks = flow
            cell.paras = [el for el in flow if isinstance(el, Para)]
        cells.append(cell)
        widths.append(max(1.0, right - x0))
        left = right
    t = TableEl(rows=[cells], col_widths=widths, row_heights=[bottom - top],
                role="layout", bbox=(edges[0][0], top, left, bottom))
    # The columns are the page's own regions; a writer resize would move a
    # whole column (see the cards table in _merge_box_rows).
    t.col_edges_drawn = True
    t.left_indent = round(edges[0][0] - content_l, 1)
    return t


def _sbs_regions(items, page: PageIR, content_l: float, content_r: float):
    """The page's items cut into regions top to bottom: ("flow", items) or
    ("band", sides, why, x, y0, y1), a side-by-side band with its evidence.
    The best split that has evidence wins, and what lies above and below it
    is searched again: a masthead's photo-beside-name band and the two
    columns under it are two regions of one page (y46)."""
    if not items:
        return []
    for xs, band, gl, gr in _side_splits(items, content_l, content_r):
        left = [items[i] for i, s in band if s == 0]
        right = [items[i] for i, s in band if s == 1]
        why = _side_evidence(left, right, gl, gr, page, content_r - content_l)
        if why is None:
            continue
        in_band = {i for i, _s in band}
        y0 = min(it[1][1] for it in left + right)
        y1 = max(it[1][3] for it in left + right)
        rest = [it for i, it in enumerate(items) if i not in in_band]
        lead = [it for it in rest if it[1] is None or it[1][1] < y0]
        tail = [it for it in rest if it[1] is not None and it[1][1] >= y0]
        sides = _split_side(left) + _split_side(right)
        return (_sbs_regions(lead, page, content_l, content_r)
                + [("band", sides, why, xs, y0, y1)]
                + _sbs_regions(tail, page, content_l, content_r))
    return [("flow", items)]


def _by_pos(its):
    return sorted(its, key=lambda t: (t[1][1], t[1][0]) if t[1] else (0.0, 0.0))


def _side_by_side_chunks(items, lay: DocLayout, page: PageIR, content_l: float,
                         content_r: float, lay_rows) -> Optional[List[Chunk]]:
    """The page as flow / side-by-side regions, or None when it has none."""
    regions = _sbs_regions(items, page, content_l, content_r)
    if not any(r[0] == "band" for r in regions):
        return None
    chunks: List[Chunk] = []
    for ri, reg in enumerate(regions):
        if reg[0] == "flow":
            ch = Chunk(n_cols=1)
            ch.elements = _merge_flow_paras(
                _to_flow(_by_pos(reg[1]), content_l, content_r, doc_rows=lay_rows),
                content_r)
            chunks.append(ch)
            continue
        _kind, sides, why, xs, y0, y1 = reg
        # A band ruled off from a page that runs on under it in ONE column --
        # a court caption, parties | case title, over the order's text -- is
        # a box of two cells, not a section of two columns: the section
        # breaks around it cost y63 its last footnote's room three pages on
        # (LibreOffice: 5 -> 6 pages, character recall 1.000 -> 0.937; as a
        # layout table 5 pages, recall 1.000, within-2pt 0.087 -> 0.116). A
        # page that goes on in columns keeps its sections: y46's two ruled
        # bands as tables lost within-2pt 0.159 -> 0.044.
        after = regions[ri + 1:]
        ruled_band = why == "rule" and any(r[1] for r in after) and \
            all(r[0] == "flow" for r in after)
        # Equal columns are a section, which every renderer -- Google Docs
        # included -- lays out natively: the right side must start where
        # equal columns put it and each side's text must fit its column.
        equal = False
        if len(sides) == 2 and not ruled_band:
            col_w = content_r - xs
            gap = 2 * xs - content_l - content_r
            l_fit = [_fit_extent(it) for it in sides[0]]
            r_fit = [_fit_extent(it) for it in sides[1]]
            equal = (SBS_MIN_GUTTER <= gap <= MAX_GUTTER_FRAC * (content_r - content_l)
                     and max(f[1] for f in l_fit) <= content_l + col_w + SBS_EQUAL_TOL
                     and max(f[1] for f in r_fit) <= content_r + SBS_EQUAL_TOL)
        if equal:
            ch = Chunk(n_cols=2, col_gap=round(gap, 1))
            lf = _column_flow(_by_pos(sides[0]), content_l, content_l + col_w, lay_rows)
            rf = _column_flow(_by_pos(sides[1]), xs, content_r, lay_rows)
            # the column each paragraph's indents are measured from, for a
            # pass that takes it out of the column (_lock_slide)
            for el in lf:
                el._col = (content_l, content_l + col_w)
            for el in rf:
                el._col = (xs, content_r)
            ch.elements = lf + [ColBreak()] + rf
            ch._sbs = why
        else:
            lt = _layout_table([_by_pos(s) for s in sides], y0, y1,
                               content_l, content_r, lay_rows)
            lt.row_heights = [_layout_row_pin(lt, y0, lay)]
            lt._sbs = why
            ch = Chunk(n_cols=1)
            ch.elements = [lt]
        chunks.append(ch)
    return chunks


# A layout row is pinned (atLeast) to the region it reproduces, so the page
# below it starts where the source's did and a panel cell's shading reaches
# the panel's foot. A row cannot split, so a pin near the page body is fatal
# wherever a renderer adds anything to it: live in Google Docs (2026-10-04),
# the shaded-sidebar page's 778pt row against a 786pt body -- Docs pads every
# row ~1.9pt and appends its own paragraph after a closing table -- left page 1
# blank, the table on page 2 and a blank page 3. The pin keeps two of the
# row's own line pitches clear of the page foot (the closing paragraph, and
# one line of the next page's carrier), plus this much for the row padding.
LAYOUT_ROW_RESERVE_PT = 4.0


def _layout_row_pin(t: TableEl, top: float, lay: DocLayout) -> Optional[float]:
    """The row height a layout table is pinned to: its region's, capped to
    leave LAYOUT_ROW_RESERVE_PT and two line pitches above the page foot, or
    None when nothing is left to pin."""
    leads = [p.leading for row in t.rows for c in row if c is not None
             for p in _cell_all_paras(c) if p.leading]
    lead = max(leads) if leads else 12.0
    foot = (lay.page_h - lay.margin_b) - 2.0 * lead - LAYOUT_ROW_RESERVE_PT
    # A box nested in a column is a row that cannot split either: one drawn
    # to the page foot (the shaded sidebar, 740pt) ends at the same clearance.
    for row in t.rows:
        for c in row:
            for b in (c.blocks if c is not None else []):
                if isinstance(b, TableEl) and b.bbox and b.rows and b.rows[-1] and \
                        b.rows[-1][0] is not None and len(b.rows[-1][0].pad) >= 4:
                    over = b.bbox[3] - foot
                    if over > 0:
                        bc = b.rows[-1][0]
                        bc.pad = (bc.pad[0], bc.pad[1],
                                  max(0.0, round(bc.pad[2] - over, 1)), bc.pad[3])
    room = foot - top
    h = t.row_heights[0] if t.row_heights else None
    if h is None or room <= 0:
        return None
    return h if h <= room else round(room, 1)


def _cell_all_paras(cell):
    """A cell's paragraphs, its nested boxes' included."""
    out = list(cell.paras)
    for b in cell.blocks:
        if isinstance(b, TableEl):
            for row in b.rows:
                for c in row:
                    if c is not None:
                        out.extend(c.paras)
    return out


# The block-cluster split and the gutter agree to the point on a page both
# read correctly (c2_paper2col, 02_research_paper: 0.0-0.6pt); a wrong cluster
# misses by a column's worth (y41 p2: 52pt).
TWO_COL_SPLIT_AGREE = 6.0
# A line belongs to the side of the gutter its centre is on unless it runs
# across the gutter's middle by more than this on BOTH sides -- an overfull
# TeX line pokes a few points into the gutter, a page-wide one crosses it.
GUTTER_SIDE_TOL = 2.0
# How near a joined line's piece must stop to the gutter's edge to be column
# text: the band is measured between the column lines' ink, and a piece stops
# short of it by a glyph's side bearing or a ragged last word.
GUTTER_SPLIT_SLACK = 8.0


def _lead_bottom(lines, content_l: float, content_r: float) -> Optional[float]:
    """The bottom of the page's lowest page-wide line with a column's worth of
    narrower text under it, or None.

    Page-wide is the column scan's own bar (COL_SCAN_W_FRAC); "a column's
    worth" is what `_two_column_gutter` needs to read two columns at all."""
    w = content_r - content_l
    wide = sorted((l.bbox[3] for l in lines if l.horizontal and
                   (l.bbox[2] - l.bbox[0]) > COL_SCAN_W_FRAC * w), reverse=True)
    for y in wide:
        under = sum(1 for l in lines if l.bbox[1] >= y and l.horizontal and
                    (l.bbox[2] - l.bbox[0]) <= COL_SCAN_W_FRAC * w)
        if under >= 2 * TWO_COL_MIN_FULL_LINES:
            return y
    return None


def _split_crossed(lines, col_split: float, content_l: float,
                   content_r: float) -> bool:
    """Is a block-cluster split refuted by the lines that run across it?

    The block-cluster test never asks whether the white left of its right
    cluster is a gutter. On a one-column page of display maths it is not: the
    equation numbers at the margin make the cluster and the page's prose runs
    straight through the "gutter" (y43 p3: 33 of 52 lines). Counted over the
    lines below the topmost right-cluster line, like `_two_column_gutter`'s
    own crossing test.

    Only a split that leaves a margin-narrow "column" is refuted. A right side
    of real width that prose also crosses is a local side-by-side region the
    block path reads as columns -- lshort's code-and-output example boxes,
    which laid out as one column stacked each code line over its output line
    (y22 223 -> 228 pages); that is not this rule's case.
    """
    if content_r - col_split >= TWO_COL_MIN_BAND_FRAC * (content_r - content_l):
        return False
    probe = col_split - 4.0
    right = [l.bbox for l in lines if l.bbox[0] >= col_split - 2.0]
    if not right:
        return True
    y0 = min(b[1] for b in right)
    inside = [l.bbox for l in lines if l.horizontal and l.text.strip()
              and (l.bbox[1] + l.bbox[3]) / 2.0 >= y0]
    crossing = [b for b in inside if b[0] < probe - GUTTER_SIDE_TOL
                and b[2] > col_split + GUTTER_SIDE_TOL]
    return len(crossing) > TWO_COL_MAX_CROSS_FRAC * max(1, len(inside))


def _split_unfilled(lines, col_split: float, col_y0: float, content_l: float,
                    content_r: float) -> bool:
    """Is a block-cluster split two "columns" that neither is set in?

    The gutter reader asks every column for lines that fill it
    (TWO_COL_FULL_LINE_FRAC of the column); the block-cluster reader never
    did. FIPS 180-4 sets its initial hash values as a centred table of
    short rows -- "H0(0)" at x 236, "= 67452301" at 266 -- under headings at
    the margin, and the rows' left edges made a right-hand cluster: the page
    was laid out as two columns of fragments with a column break between,
    ran 655pt over its box, and every page after it was a page late. Real
    columns -- the journals', lshort's code-and-output boxes -- carry lines
    that run the width of their side; a scatter of short pieces on both sides
    of a split is one column of something narrow."""
    lw = col_split - content_l
    rw = content_r - col_split
    full_l = full_r = 0
    reach = col_split
    for ln in lines:
        if not ln.horizontal or not ln.text.strip() or ln.bbox[1] < col_y0:
            continue
        x0, x1 = ln.bbox[0], ln.bbox[2]
        if x1 <= col_split + GUTTER_SIDE_TOL and \
                x1 - x0 >= TWO_COL_FULL_LINE_FRAC * lw:
            full_l += 1
        elif x0 >= col_split - 2.0:
            reach = max(reach, x1)
            if x1 - x0 >= TWO_COL_FULL_LINE_FRAC * rw:
                full_r += 1
    # Not one full line on either side -- the gutter reader wants six per
    # column, but a real two-column page can end on a few lines a column --
    # and a right side that stops short of the middle of its own band. An
    # index is two columns of short entries too (lshort's, pp. 149-153), but
    # its right column runs on towards the margin; FIPS 180-4's table stops
    # at x 341 of a band from 236 to 540.
    return full_l == 0 and full_r == 0 and reach < col_split + 0.5 * rw


def _split_at_gutter(ln: Line, gutter) -> List[Line]:
    """A line the parser joined across the gutter, as its two column halves.

    An equation number at the foot of the left column's measure and the right
    column's line beside it are 15pt apart on y41 p2 -- inside the parser's
    line-join reach -- and arrived as one Line, "(3) ditioning matrix Φ ≈ S
    is often...", which spans the page and cut the columns into three chunks.
    Spans keep their own boxes; a span boundary whose white covers the
    gutter's middle is where the line divides, when one of the two pieces
    stops at that gutter's own edge -- the left piece at the left column's
    measure, or the right piece at the right column's start. The parser also
    keeps a "(14)" with the text after it as a list marker, however far away:
    y41 p3's right-column equation sat 100pt beyond its neighbour's number.
    Nothing else is cut: a span running across the gutter is page-spanning
    text, and a running head's halves (y42: "SIGIR '24, ..." at the left
    margin, the authors 110pt away at the right) touch neither column edge
    and stay one page-wide line.
    """
    if len(ln.spans) < 2:
        return [ln]
    mid = (gutter[0] + gutter[1]) / 2.0
    gw = gutter[1] - gutter[0]
    spans = sorted(ln.spans, key=lambda s: s.bbox[0])
    for k in range(len(spans) - 1):
        a, b = ink_extent(spans[k])[1], ink_extent(spans[k + 1])[0]
        at_edge = abs(a - gutter[0]) <= GUTTER_SPLIT_SLACK or \
            abs(b - gutter[1]) <= GUTTER_SPLIT_SLACK
        if a <= mid <= b and b - a >= 0.5 * gw and at_edge and \
                all(ink_extent(s)[1] <= mid for s in spans[:k + 1]) and \
                all(ink_extent(s)[0] >= mid for s in spans[k + 1:]):
            parts = (spans[:k + 1], spans[k + 1:])
            return [Line(spans=list(p), dir=ln.dir,
                         bbox=(min(s.bbox[0] for s in p),
                               min(s.bbox[1] for s in p),
                               max(s.bbox[2] for s in p),
                               max(s.bbox[3] for s in p)))
                    for p in parts]
    return [ln]


def _gutter_chunks(elements, flow_blocks, lay: DocLayout, gutter,
                   col_split: float, page_top: Optional[float],
                   lead_y: Optional[float] = None) -> List[Chunk]:
    """Lay a two-column page out in reading order, cut at what spans it.

    Every LINE, not every block, is placed: left of the gutter, right of it,
    or across it. Blocks are the parser's grouping and are not trustworthy
    across a gutter -- y39 p3's two biggest blocks each held lines of both
    columns -- whereas a line is never wider than the column it is set in
    unless it really spans the page.

    What spans the page then cuts the page into horizontal bands, in the order
    the source stacks them: a title and abstract above the columns, a
    full-width figure between two runs of columns, a table at the foot. Each
    run of columns between two spanning bands is one two-column chunk, so a
    float in the middle of the page stays in the middle of the page. The
    block-cluster path sends every spanning item below the columns' top to a
    single tail AFTER the columns, which moves a mid-page float -- and the
    column text beneath it -- to the wrong place.
    """
    content_l, content_r = lay.margin_l, lay.page_w - lay.margin_r
    lay_rows = getattr(lay, "_row_evidence", None)
    mid = (gutter[0] + gutter[1]) / 2.0

    def side(bb):
        if bb[0] < mid - GUTTER_SIDE_TOL and bb[2] > mid + GUTTER_SIDE_TOL:
            return 2
        if lead_y is not None and bb[3] <= lead_y + GUTTER_SIDE_TOL:
            return 2                # the page's lead: one column above them
        return 0 if (bb[0] + bb[2]) / 2.0 < mid else 1

    placed = []                     # (side, item)
    for b in flow_blocks:
        groups = defaultdict(list)
        for ln in b.lines:
            for l in _split_at_gutter(ln, gutter):
                groups[side(l.bbox)].append(l)
        if len(groups) == 1:
            placed.append((next(iter(groups)), ("blk", b.bbox, b)))
            continue
        for k, ls in groups.items():
            blk = _mk_block(ls)
            placed.append((k, ("blk", blk.bbox, blk)))
    for e in elements:
        bb = _el_bbox(e) or (content_l, 0.0, content_r, 0.0)
        placed.append((side(bb), ("el", bb, e)))

    def cy(t):
        return (t[1][1] + t[1][3]) / 2.0

    spans = sorted((t for k, t in placed if k == 2),
                   key=lambda t: (t[1][1], t[1][0]))
    cols = [(k, t) for k, t in placed if k != 2]
    groups = []
    for t in spans:
        if groups:
            bottom = max(u[1][3] for u in groups[-1])
            if not any(bottom < cy(c) < t[1][1] for _k, c in cols):
                groups[-1].append(t)
                continue
        groups.append([t])
    # A column item goes after every spanning band that starts above it. One
    # that starts inside a band's extent sits beside it or inside it -- a
    # table's rules inside a full-width figure region that swallowed the
    # table's art (y42 p3) -- and the source shows it no higher than the band.
    cuts = [min(u[1][1] for u in g) for g in groups]
    segs = [[] for _ in range(len(groups) + 1)]
    for k, t in cols:
        segs[sum(1 for c in cuts if t[1][1] > c)].append((k, t))

    left_edges = [t[1][2] for k, t in cols if k == 0]
    gap = col_split - max(left_edges, default=col_split - 24)
    gap = max(10.0, round(gap, 1))
    colr_edge = col_split - gap

    def one_sided_lines(seg):
        """A run of single lines all on one side -- a chapter title above the
        first spanning heading (y26's "Appendix D Indexes") -- is a one-column
        band, not a column section with an empty column: as a section it cost
        an extra section break and its column break at the page top."""
        if len({k for k, _t in seg}) != 1:
            return False
        for _k, (kind, _bb, o) in seg:
            if kind != "blk" or len({round(l.baseline) for l in _blk_lines(o)}) > 1:
                return False
        return True

    plan = []                       # [n_cols, items]
    for i, seg in enumerate(segs):
        if seg and one_sided_lines(seg) and (i < len(groups) or plan):
            seg_items = [t for _k, t in seg]
            if plan and plan[-1][0] == 1:
                plan[-1][1].extend(seg_items)
            else:
                plan.append([1, seg_items])
        elif seg:
            if plan and plan[-1][0] == 2:
                plan[-1][1].extend(seg)
            else:
                plan.append([2, list(seg)])
        if i < len(groups):
            if plan and plan[-1][0] == 1:
                plan[-1][1].extend(groups[i])
            else:
                plan.append([1, list(groups[i])])

    chunks: List[Chunk] = []
    for n, its in plan:
        if n == 1:
            ch = Chunk(n_cols=1)
            ch.elements = _merge_flow_paras(
                _to_flow(its, content_l, content_r, doc_rows=lay_rows),
                content_r)
        else:
            colL = [t for k, t in its if k == 0]
            colR = [t for k, t in its if k == 1]
            ch = Chunk(n_cols=2, col_gap=gap)
            wl, wr = colr_edge - content_l, content_r - col_split
            if abs(wl - wr) > TWO_COL_UNEQUAL_FRAC * max(wl, wr):
                ch.col_widths = [round(wl, 1), round(wr, 1)]
            left_flow = _merge_flow_paras(
                _to_flow(colL, content_l, colr_edge, doc_rows=lay_rows),
                colr_edge)
            right_flow = _merge_flow_paras(
                _to_flow(colR, col_split, content_r, doc_rows=lay_rows),
                content_r)
            ch.elements = left_flow + [ColBreak()] + right_flow
        chunks.append(ch)
    return _position_chunks(chunks, lay, page_top)


def _assemble_chunks(elements, flow_blocks, lay: DocLayout, page: PageIR,
                     page_top: Optional[float] = None) -> List[Chunk]:
    content_l, content_r = lay.margin_l, lay.page_w - lay.margin_r
    lay_rows = getattr(lay, "_row_evidence", None)
    content_w = content_r - content_l
    body_h = lay.page_h - lay.margin_t - lay.margin_b
    flow_blocks = _merge_list_markers(flow_blocks)

    # A >=3 column grid is checked first and, when found, decides the page on
    # its own. The two-column path below is left exactly as it was: it owns
    # every page it already handled, so its reference fixture cannot move.
    bands = column_grid([l.bbox for b in flow_blocks for l in b.lines],
                        content_l, content_r)
    if bands is not None:
        grid = _grid_chunks(elements, flow_blocks, bands, lay,
                            content_l, content_r)
        if grid:
            return _position_chunks(grid, lay, page_top)

    narrow = [b for b in flow_blocks if (b.bbox[2] - b.bbox[0]) <= 0.62 * content_w]
    twocol, col_split, col_y0 = False, None, None
    if narrow:
        lefts = _cluster([b.bbox[0] for b in narrow], 12.0)
        right_cands = [c for c in lefts if c >= content_l + 0.35 * content_w]
        # A cluster of figures is a table's value column, not a second
        # column of text, when the page holds two or more of them: y35's
        # 2025/26 and 2026/27 rates (x 370-387, 440-465) cleared every bar
        # below and the page was set as two text columns, its labels in one
        # and their values a column-break away; on y60 (MMWR) a table's
        # figure column outvoted the page's real right-hand text column. A
        # lone column of figures -- a contents page's page numbers (y32) --
        # keeps the two-column reading it always had: as rows its short
        # titles fall under _row_pairs' label floor and each number would
        # stand on a line of its own.
        def _figs(b):
            return all(_NUMERIC_CELL.match(l.text.strip()) for l in b.lines)
        fig_cols = [c for c in lefts if c > lefts[0] + 12 and
                    _figure_cluster(c, narrow, _figs)]
        if len(fig_cols) >= FIGURE_COLUMN_MIN:
            right_cands = [c for c in right_cands if c not in fig_cols]
        else:
            right_cands = [c for c in right_cands
                           if not _leadered_numbers(c, narrow, flow_blocks)]
        if lefts and abs(lefts[0] - content_l) < 10 and right_cands:
            # dominant right-column cluster (by block count)
            def csize(c):
                return sum(1 for b in narrow if abs(b.bbox[0] - c) < 12)
            rc = max(right_cands, key=csize)
            c1 = [b for b in narrow if abs(b.bbox[0] - lefts[0]) < 12]
            c2 = [b for b in narrow if abs(b.bbox[0] - rc) < 12]
            h1 = sum(b.bbox[3] - b.bbox[1] for b in c1)
            h2 = sum(b.bbox[3] - b.bbox[1] for b in c2)
            # Two blocks in the right cluster is evidence that it is a COLUMN
            # rather than one incidental inset. It is not the only evidence,
            # and requiring it inverted the test: a column that is one
            # uninterrupted block of prose -- which is what a well-formed
            # column is -- was refused for being too clean, while a fragmented
            # one passed. Measured on y12_irs_pub15, whose pages are two
            # columns at x=42 and x=315: p3's right column is 3 blocks and is
            # detected, p4's is a single block 711pt tall and was not, so the
            # page linearised to 1413pt into a 768pt body. A block spanning
            # half the body is stronger evidence of a column than two short
            # ones, so it is accepted too, and a stray 100pt inset still is
            # not.
            tall_single = h2 >= COL_SINGLE_BLOCK_FRAC * max(1.0, body_h)
            if h1 > 60 and h2 > 60 and (len(c2) >= 2 or tall_single):
                col_split = float(_mode([b.bbox[0] for b in c2], 0))
                ys1 = sorted(b.bbox[1] for b in c1)
                ys2 = sorted(b.bbox[1] for b in c2)
                cands = [y for y in ys1 if any(abs(y2 - y) < 160 for y2 in ys2)]
                cands += [y for y in ys2 if any(abs(y1_ - y) < 160 for y1_ in ys1)]
                if cands:
                    twocol = True
                    col_y0 = min(cands) - 4

    flow_lines = [l for b in flow_blocks for l in b.lines]
    gutter = _two_column_gutter(flow_lines, content_l, content_r)
    lead_y = None
    if gutter is None and not twocol:
        # Below a page's lead. A title block's centred author, affiliation
        # and date lines are narrower than the column-scan bar and cross the
        # gutter, and its corner header stretches the crossing test over the
        # title and abstract: y39 p1's introduction, two columns under a
        # full-width abstract, was read by neither test and laid out as one
        # column -- its first page took two. Read again from below the page's
        # lowest wide line that still has a column's worth of text under it;
        # what is above stays a one-column lead, as the block path keeps it.
        lead_y = _lead_bottom(flow_lines, content_l, content_r)
        if lead_y is not None:
            gutter = _two_column_gutter(
                [l for l in flow_lines if l.bbox[1] >= lead_y],
                content_l, content_r)
    if gutter is not None and not twocol and \
            gutter[2] < TWO_COL_MIN_EXTENT_FRAC * max(1.0, body_h):
        gutter = None                    # an inset beside the text, not a column
    if gutter is not None:
        gutter = gutter[:2]
        # The block clusters agree with the white band on every page they
        # already read correctly; their split is kept there, so those pages
        # are assembled from the same numbers as before.
        if not (twocol and abs(col_split - gutter[1]) <= TWO_COL_SPLIT_AGREE):
            col_split = float(round(gutter[1]))
        return _gutter_chunks(elements, flow_blocks, lay, gutter, col_split,
                              page_top, lead_y=lead_y)
    if twocol and (_split_crossed(flow_lines, col_split, content_l, content_r)
                   or _split_unfilled(flow_lines, col_split, col_y0,
                                      content_l, content_r)):
        twocol = False

    items = [("blk", b.bbox, b) for b in flow_blocks]
    for e in elements:
        bb = _el_bbox(e)
        items.append(("el", bb or (content_l, 0, content_r, 0), e))
    items.sort(key=lambda t: (t[1][1], t[1][0]))

    if not twocol:
        # Only where the two-column path above did not fire: every page it
        # owns keeps exactly its layout.
        sbs = _side_by_side_chunks(items, lay, page, content_l, content_r, lay_rows)
        if sbs:
            return _position_chunks(sbs, lay, page_top)

    chunks: List[Chunk] = []
    if not twocol:
        ch = Chunk(n_cols=1)
        ch.elements = _merge_flow_paras(
            _to_flow(items, content_l, content_r, doc_rows=lay_rows), content_r,
            content_l)
        chunks.append(ch)
    else:
        # gutter between the columns (approximate)
        gut_r = col_split - 2
        gut_l = col_split - 26

        def is_lead(t):
            bb = t[1]
            if bb[3] > col_y0 + 4:
                return False
            w = bb[2] - bb[0]
            if w > 0.62 * content_w:
                return True
            # crosses the gutter (e.g. centered title parts) -> lead;
            # fits entirely inside one column -> belongs to the columns
            return not (bb[2] <= gut_l + 2 or bb[0] >= gut_r)

        lead = [t for t in items if is_lead(t)]
        rest = [t for t in items if not is_lead(t)]
        # "Wide" means CROSSING THE COLUMN SPLIT, not a fixed fraction of
        # the page. Measured on the IRS booklets (y06): their columns span
        # 65% of the content width, so the old 0.62 threshold classified
        # every full line of column two as page-spanning -- whole columns
        # were pulled out of the flow into single-column tails carrying
        # page-absolute indents (182pt into 165pt-section columns, every
        # word wrapping), the dominant driver of that class's 2.3x page
        # inflation. An item that fits one side of the split is not wide
        # no matter how much of the page it covers.
        def _spans_split(bb):
            return bb[0] < gut_l and bb[2] > gut_r
        wide_tail = [t for t in rest if _spans_split(t[1])]
        colitems = [t for t in rest if t not in wide_tail]
        if lead:
            ch = Chunk(n_cols=1)
            ch.elements = _merge_flow_paras(
                _to_flow(lead, content_l, content_r, doc_rows=lay_rows), content_r,
                content_l)
            chunks.append(ch)
        colL = [t for t in colitems if t[1][0] < col_split - 20]
        colR = [t for t in colitems if t[1][0] >= col_split - 20]
        gap = col_split - max((t[1][2] for t in colL), default=col_split - 24)
        gap = max(10.0, round(gap, 1))
        if gap > MAX_GUTTER_FRAC * content_w and \
                _prose_between(wide_tail, colitems):
            # Not a gutter: the white between a column of short labels and a
            # column of right-hand fields, with the page's own prose running
            # across it between them. Lay the page out as the single column
            # it is (see MAX_GUTTER_FRAC).
            ch = Chunk(n_cols=1)
            ch.elements = _merge_flow_paras(
                _to_flow(items, content_l, content_r, doc_rows=lay_rows),
                content_r, content_l)
            return _position_chunks([ch], lay, page_top)
        ch = Chunk(n_cols=2, col_gap=gap)
        colr_edge = col_split - gap
        left_flow = _merge_flow_paras(
            _to_flow(colL, content_l, colr_edge, doc_rows=lay_rows), colr_edge,
            content_l)
        right_flow = _merge_flow_paras(
            _to_flow(colR, col_split, content_r, doc_rows=lay_rows), content_r,
            col_split)
        # The column each paragraph's indents are measured from, for a pass
        # that takes it out of the column (_lock_slide).
        for el in left_flow:
            el._col = (content_l, colr_edge)
        for el in right_flow:
            el._col = (col_split, content_r)
        ch.elements = left_flow + [ColBreak()] + right_flow
        chunks.append(ch)
        if wide_tail:
            ch2 = Chunk(n_cols=1)
            ch2.elements = _merge_flow_paras(
                _to_flow(wide_tail, content_l, content_r, doc_rows=lay_rows),
                content_r, content_l)
            chunks.append(ch2)

    return _position_chunks(chunks, lay, page_top)


def _position_chunks(chunks: List[Chunk], lay: DocLayout,
                     page_top: Optional[float]) -> List[Chunk]:
    """Turn absolute source positions into the flow's space_before values."""
    _fuse_baseline_rows(chunks, lay.margin_l, lay.page_w - lay.margin_r)
    base = page_top if page_top is not None else lay.margin_t
    for ch in chunks:
        top = base
        if ch.n_cols > 1:
            # columns must START at the first content top: renderers apply the
            # first paragraph's space-before to the whole column region, so we
            # hoist the common gap out of the columns into a pre-section spacer
            firsts = []
            take_next = True
            for el in ch.elements:
                if isinstance(el, ColBreak):
                    take_next = True
                    continue
                if take_next and _el_bbox(el) is not None:
                    t = _para_box(el)[0] if isinstance(el, Para) else _el_bbox(el)[1]
                    firsts.append(t)
                    take_next = False
            if firsts:
                target = min(firsts)
                ch.pre_gap = max(0.0, round(target - base, 1))
                top = base + ch.pre_gap
        cursor = top
        maxy = top
        held = None         # the table or figure the cursor stands at the foot of
        held_fig = False
        for el in ch.elements:
            if isinstance(el, ColBreak):
                cursor = top
                held = None
                continue
            bb = _el_bbox(el)
            if bb is None:
                continue
            if isinstance(el, Para):
                t, h = _para_box(el)
                el.space_before = max(0.0, round(t - cursor, 1))
                cursor = t + h
                held = None
            else:
                el.space_before = max(0.0, round(bb[1] - cursor, 1))
                # A rule that ends above the cursor inside the table just
                # stacked lies in the span that table already took -- BLS's
                # column-group rule under "Seasonally
                # adjusted" (y 80) flowed after its table (y 67-274) -- and
                # does not move the cursor back up: the note under the
                # table took 200pt of space before from it and left its
                # page (y64 p22/p23, each a page in LibreOffice). Only a
                # table just stacked holds the cursor so. A picture may be
                # anchored out of the flow: y17 p174's code panel (y
                # 142-696, behind its text in the gdocs profile) held it
                # past the rule along its own top edge, and the first code
                # line lost its 9.7pt of space before. A paragraph's box is
                # its lines, not a span the flow has taken: held behind
                # three rules drawn under y37's lines, the cursor moved its
                # later pages (criterion 8: dy_p50 27.4 -> 31.0). And only a
                # rule: a table or picture set inside the table's span is
                # stacked after it in the flow with its own height --
                # y59's InDesign panels (23 tables and 4 pictures inside a
                # table just stacked) held there put Word at 25 pages for
                # 6 against 23.
                #
                # A drawn figure just stacked holds a rule inside its span
                # the same way: the figure is always in the flow (only raster
                # pictures float, `_float_backgrounds`), and its height is
                # already counted. y21 p39 sets a figure at y 319-505 with
                # three rules inside it (y 338, 386, 480): released, the
                # first pulled the cursor back to 338 and the rest took
                # 47.9, 93.4 and 23.8pt of space before -- 165pt counted
                # twice, the page ran over, and every page after it was a
                # page late (49 -> 50 pages for 48, word recall 0.88 ->
                # 0.80). Inside means inside both spans: a rule on the
                # figure's top edge, or wider than the figure, is not in it
                # -- under the gdocs profile y17 p174's code panel keeps its
                # 4.8pt side bar (x 527-531, y 140-698) in the flow as a
                # figure, and its full-width top rule (x 66-529) must still
                # release the cursor for the first code line.
                inside = held is not None and isinstance(el, RuleEl) and \
                    bb[1] >= held[1] and bb[3] <= cursor and \
                    (not held_fig or (bb[1] > held[1] and
                                      bb[0] >= held[0] - 1.0 and
                                      bb[2] <= held[2] + 1.0))
                if not inside:
                    cursor = bb[3]
                    held = bb if isinstance(el, (TableEl, FigureEl)) else None
                    held_fig = isinstance(el, FigureEl)
            maxy = max(maxy, cursor)
        base = maxy
    return chunks


# --- one row, one line -------------------------------------------------------
# Two one-line paragraphs set on one baseline, side by side, are one line of the
# page. The flow stacks them, and the row then stands two lines tall. Measured
# where it costs pages: SP 800-63B's contents set each chapter number a tab
# ahead of its entry ("1" at x 72, "Purpose ....... 1" at x 96, one baseline),
# and its title page sets two columns of authors and affiliations row by row --
# each page of them ran 55-180pt over its box. FIPS 180-4's padding figure sets
# "a", "b", "c" under one brace on one baseline, three lines for one.
#
# The fragments become one paragraph: the first keeps its own start, and each
# later one follows a tab to a stop at its own edge -- left, right or centre as
# the fragment was aligned -- which is how the producer set the row. Only short
# rows of short fragments: when both are wider than ROW_FUSE_MAX_SHARE of the
# column they are the lines of two columns the column readers did not split,
# and welding a page's columns line by line is not this rule's call.
ROW_FUSE_BASELINE_TOL = 2.0     # one baseline, as _ROW_BASELINE_TOL
ROW_FUSE_MIN_GAP = 1.0          # side by side: the right one starts past the left
ROW_FUSE_MAX_SHARE = 0.40       # a column line is ~0.48 of a two-column page
ROW_FUSE_MAX_SIZE_RATIO = 1.6   # a title beside its small print is two lines
# Three or more fragments fuse only when each is at most this share of the
# column: FIPS 180-4's brace labels are a few points wide, a three-column page's
# lines about 0.3 (`_row_accepted`).
ROW_FUSE_MANY_SHARE = 0.25


def _one_line(p) -> bool:
    """A one-line flow paragraph this rule may fuse: not a list item (its
    marker belongs to lists.assign_lists), a display row, a frame or a note."""
    return bool(isinstance(p, Para) and p.runs and not p.line_breaks and
                not p.rtl and p.frame is None and not p.role and
                (getattr(p, "_vis_lines", None) or p.src_lines or 1) <= 1 and
                (p.src_lines or 1) <= 1 and p.bbox is not None and
                getattr(p, "_b1", None) is not None and
                not getattr(p, "_display", False) and
                not getattr(p, "_list_item", False) and
                not getattr(p, "_note", False))


def _row_fusable(a: Para, b: Para, col_l: float, col_r: float) -> bool:
    if not (_one_line(a) and _one_line(b)):
        return False
    if abs(a._b1 - b._b1) > ROW_FUSE_BASELINE_TOL:
        return False
    col_w = col_r - col_l
    left, right = (a, b) if a.bbox[0] <= b.bbox[0] else (b, a)
    if right.bbox[0] - left.bbox[2] < ROW_FUSE_MIN_GAP:
        return False
    wa, wb = a.bbox[2] - a.bbox[0], b.bbox[2] - b.bbox[0]
    if min(wa, wb) > ROW_FUSE_MAX_SHARE * max(1.0, col_w):
        return False
    wl, wr = left.bbox[2] - left.bbox[0], right.bbox[2] - right.bbox[0]
    if left.bbox[0] <= col_l + _ROW_LEFT_TOL and \
            right.bbox[2] >= col_r - _ROW_EDGE_TOL and \
            right.bbox[0] - left.bbox[2] >= _ROW_MIN_GAP and \
            wr <= _ROW_MAX_RIGHT * col_w and wl >= _ROW_MIN_LEFT * col_w:
        # A label and a field at the margin: `_row_pairs`' shape, and its
        # call. It pairs them only on a column's worth of evidence (two rows
        # at one edge, or the document's), because without it the same shape
        # is a sentence broken across an unsplit two-column body; what it
        # refused stays refused.
        return False
    sa = max((r.size for r in a.runs if r.text.strip()), default=0.0)
    sb = max((r.size for r in b.runs if r.text.strip()), default=0.0)
    if min(sa, sb) <= 0 or max(sa, sb) > ROW_FUSE_MAX_SIZE_RATIO * min(sa, sb):
        return False
    return True


def _fragment_stop(p: Para, col_l: float):
    """The tab stop that puts fragment `p` where the source set it."""
    if p.align == "right":
        return (round(p.bbox[2] - col_l, 1), "right")
    if p.align == "center":
        return (round((p.bbox[0] + p.bbox[2]) / 2 - col_l, 1), "center")
    return (round(p.bbox[0] - col_l, 1), "left")


def _fuse_row(a: Para, b: Para, col_l: float) -> Para:
    """One paragraph for two one-line fragments of a row (see above)."""
    left, right = (a, b) if a.bbox[0] <= b.bbox[0] else (b, a)
    p = copy.copy(left)
    runs = [copy.copy(r) for r in left.runs]
    while runs and not runs[-1].is_tab and not runs[-1].text.strip():
        runs.pop()
    if runs and not runs[-1].is_tab:
        runs[-1].text = runs[-1].text.rstrip(" ")
    stops = list(left.tab_stops)
    ref = next((r for r in reversed(left.runs) if r.text.strip()), left.runs[0])
    tab = replace(ref, text="\t", is_tab=True, link=None, dest=None,
                  field=None, footnote=None, footnote_mark=False,
                  underline=False, superscript=False)
    if left.align in ("right", "center"):
        # A row that opens with a right- or centre-set fragment starts at the
        # column edge and tabs to it.
        runs = [copy.copy(tab)] + runs
        stops.append(_fragment_stop(left, col_l))
        p.left_indent = 0.0
        p.first_indent = 0.0
        if left.leader_text:
            p._leader_tab = next((k for k, r in enumerate(runs)
                                  if k > 0 and r.is_tab), None)
    p.align = "left"
    head = [copy.copy(r) for r in right.runs]
    while head and not head[0].is_tab and not head[0].text.strip():
        head.pop(0)
    if head and not head[0].is_tab:
        head[0].text = head[0].text.lstrip(" ")
    if right.leader_text:
        # the gdocs writer types this fragment's leader at its own tab
        p._leader_tab = len(runs) + 1 + next(
            (k for k, r in enumerate(head) if r.is_tab), 0)
        p.leader_text = right.leader_text
    runs += [tab] + head
    stops.append(_fragment_stop(right, col_l))
    stops += list(right.tab_stops)
    seen, uniq = set(), []
    for st in sorted(stops, key=lambda t: t[0]):
        if st[0] in seen:
            continue
        seen.add(st[0])
        uniq.append(st)
    p.runs = runs
    p.tab_stops = uniq
    p.right_indent = 0.0
    p.bbox = bbox_union(a.bbox, b.bbox)
    tall = a if (a.leading or 0) >= (b.leading or 0) else b
    p.leading = tall.leading
    p._b1 = tall._b1
    p._size1 = getattr(tall, "_size1", getattr(p, "_size1", 10.0))
    p._vis_lines = 1
    p.src_lines = 1
    p.src_widths = [round(p.bbox[2] - p.bbox[0], 1)]
    p.space_after = max(a.space_after or 0.0, b.space_after or 0.0)
    if getattr(p, "_bookmark", None) is None and \
            getattr(right, "_bookmark", None) is not None:
        p._bookmark = right._bookmark
    return p


def _row_of(els, i):
    """The run of one-line fragments from `els[i]` that share its baseline,
    in flow order."""
    row = [els[i]]
    if not _one_line(els[i]):
        return row
    j = i + 1
    while j < len(els) and _one_line(els[j]) and \
            abs(els[j]._b1 - row[0]._b1) <= ROW_FUSE_BASELINE_TOL:
        row.append(els[j])
        j += 1
    return row


def _row_accepted(row, col_l: float, col_r: float) -> bool:
    """Is this baseline's run of fragments one row to fuse? Two fragments by
    `_row_fusable`. Three or more are a row of short pieces -- labels under a
    brace, a contents line's parts -- only when they stand side by side,
    every piece is short and all are set at one size. Three column-wide lines
    of prose on shared baselines are three columns, and a sign beside its
    raised exponents is maths; neither is this rule's
    (test_rule_less_grid_rows)."""
    if len(row) < 2:
        return False
    if len(row) == 2:
        return _row_fusable(row[0], row[1], col_l, col_r)
    xs = sorted(row, key=lambda p: p.bbox[0])
    if any(b.bbox[0] - a.bbox[2] < ROW_FUSE_MIN_GAP for a, b in zip(xs, xs[1:])):
        return False
    sizes = [max((r.size for r in p.runs if r.text.strip()), default=0.0)
             for p in row]
    if min(sizes) <= 0 or max(sizes) > ROW_FUSE_MAX_SIZE_RATIO * min(sizes):
        return False
    # The leftmost piece may be a row's label -- BLS's "Participation rate
    # ......" stub, 44% of the column, before five figures that each stood a
    # line of their own (a 39-page release rendered 46) -- but every piece
    # after it is short.
    return all(p.bbox[2] - p.bbox[0] <=
               ROW_FUSE_MANY_SHARE * max(1.0, col_r - col_l)
               for p in xs[1:])


def _fuse_baseline_rows(chunks: List[Chunk], col_l: float, col_r: float) -> None:
    """Fuse each one-column chunk's same-baseline fragments (see above), in
    place. Runs before the chunks are positioned, so the spacing chain is read
    off the fused rows."""
    for ch in chunks:
        if ch.n_cols != 1:
            continue
        els, out, i = ch.elements, [], 0
        while i < len(els):
            el = els[i]
            if not isinstance(el, Para):
                out.append(el)
                i += 1
                continue
            cl, cr = getattr(el, "_col", (col_l, col_r))
            row = _row_of(els, i)
            if _row_accepted(row, cl, cr):
                row = sorted(row, key=lambda p: p.bbox[0])
                fused = row[0]
                for p in row[1:]:
                    fused = _fuse_row(fused, p, cl)
                out.append(fused)
            else:
                # not a row: the fragments keep the flow they had
                out.extend(row)
            i += len(row)
        ch.elements = out


def _body_font_size(ir: DocIR, hf) -> float:
    counter = Counter()
    for p in ir.pages:
        ct = hf["consumed_text"][p.number]
        for bi, b in enumerate(p.blocks):
            for l in b.lines:
                if (bi, id(l)) in ct:
                    continue
                for s in l.spans:
                    counter[round(s.size * 2) / 2] += len(s.text)
    return counter.most_common(1)[0][0] if counter else 10.5


def _n_lines(p: Para) -> int:
    return 1 + sum(r.text.count("\n") for r in p.runs)


def _para_box(p: Para):
    """(top, height) the paragraph occupies in Word terms, baseline-anchored.

    Word puts the baseline at (line_height - descent) from the line top when
    line spacing is 'exactly'. Anchoring on baselines keeps the vertical
    rhythm identical across renderers regardless of font bbox differences.
    """
    n = getattr(p, "_vis_lines", None) or _n_lines(p)
    L = p.leading or 0.0
    b1 = getattr(p, "_b1", None)
    if not L or b1 is None:
        bb = p.bbox or (0, 0, 0, 0)
        return bb[1], bb[3] - bb[1]
    desc = 0.21 * getattr(p, "_size1", 10.0)
    top = b1 - (L - desc)
    return top, n * L


def _mark_headings(lay: DocLayout, body_size: float):
    sizes = set()

    def candidates():
        for pg in lay.pages:
            for els in page_sequences(pg):
                for el in els:
                    if isinstance(el, Para) and el.runs:
                        yield el

    for el in candidates():
        mx = max((r.size for r in el.runs if r.text.strip()), default=0)
        boldn = sum(len(r.text) for r in el.runs if r.bold)
        totn = max(1, sum(len(r.text) for r in el.runs))
        if mx >= body_size * 1.12 and boldn >= 0.6 * totn and _n_lines(el) <= 3 \
                and len(el.text) < 200:
            sizes.add(round(mx * 2) / 2)
    ranked = sorted(sizes, reverse=True)
    for el in candidates():
        mx = max((r.size for r in el.runs if r.text.strip()), default=0)
        boldn = sum(len(r.text) for r in el.runs if r.bold)
        totn = max(1, sum(len(r.text) for r in el.runs))
        key = round(mx * 2) / 2
        if key in ranked and boldn >= 0.6 * totn and _n_lines(el) <= 3 and len(el.text) < 200:
            el.heading = min(6, ranked.index(key) + 1)
    _mark_caps_headings(lay, body_size, ranked)


# A résumé's section headings are set AT BODY SIZE -- "SUMMARY", "EXPERIENCE",
# "TECHNICAL SKILLS" are Georgia-Bold 9.49pt over a 9.7pt body on the owner's
# résumé, Liberation Sans Bold 9.49 over Liberation Serif 9.7 on x17 -- so the
# size ladder above never sees them, and Google Docs' outline of a converted
# résumé was empty. What marks them is everything except size: bold capitals,
# a short line of their own, letter-spacing, and a full-width rule hard
# against them. Capitals and bold alone are not enough: bold caps labels
# ("NOTE:", table captions, "WARNING") are everywhere in government documents.
# So a body-size heading needs, beyond bold caps on one short line, at least
# one of the two typographic devices that announce a SECTION: tracking (the
# parser's own measurement, `Span.tracked`) or a rule directly above or below.
_CAPS_HEADING_MAX_CHARS = 60     # a section title, not a sentence in capitals
_CAPS_HEADING_RULE_GAP = 12.0    # pt between heading and rule; résumés measure 3.3-6
_CAPS_HEADING_MIN_SIZE = 0.9     # x body size: smaller caps are labels and captions
_CAPS_HEADING_EDGE_TOL = 2.0     # pt; résumé headings measure 0.0 (u1, x17)


def _caps_heading_text(t: str) -> bool:
    # A colon with text after it is a label and its value ("CATEGORY: COMPUTER
    # SECURITY" on y10_nist_fips180's cover), not a section title.
    if re.search(r":\s*\S", t):
        return False
    letters = [c for c in t if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def _mark_caps_headings(lay: DocLayout, body_size: float, ranked):
    for pg in lay.pages:
        for els in page_sequences(pg):
            for i, el in enumerate(els):
                # Right-aligned caps over a rule is a running head left in the
                # flow (y22_lshort's "CONTENTS" over its headrule), not a
                # section opening.
                if not isinstance(el, Para) or el.heading or not el.runs \
                        or el.align == "right":
                    continue
                # A section opens at its column's edge (or centred over it).
                # An indented bold-caps word over a rule is a label inside a
                # figure or form: y06_irs_1040's flowchart "AND" at 115.9pt,
                # y10_nist_fips180's cover metadata at 18pt.
                if el.align != "center" and el.left_indent > _CAPS_HEADING_EDGE_TOL:
                    continue
                text = el.text.strip()
                if not text or len(text) > _CAPS_HEADING_MAX_CHARS \
                        or _n_lines(el) != 1 or (el.src_lines or 1) != 1 \
                        or any(r.is_tab for r in el.runs) \
                        or not _caps_heading_text(text):
                    continue
                runs = [r for r in el.runs if r.text.strip()]
                totn = sum(len(r.text) for r in runs)
                if sum(len(r.text) for r in runs if r.bold) < 0.6 * totn:
                    continue
                mx = max(r.size for r in runs)
                if mx < _CAPS_HEADING_MIN_SIZE * body_size or mx >= 1.12 * body_size:
                    continue
                ruled = False
                bb = el.bbox
                for j in (i - 1, i + 1):
                    if 0 <= j < len(els) and isinstance(els[j], RuleEl) and bb:
                        rb = getattr(els[j], "_bbox", None)
                        if rb and (0 <= rb[1] - bb[3] <= _CAPS_HEADING_RULE_GAP
                                   or 0 <= bb[1] - rb[3] <= _CAPS_HEADING_RULE_GAP):
                            ruled = True
                if not (ruled or getattr(el, "_tracked", False)):
                    continue
                # Below every size-ranked heading: these are the sections
                # those headings (a title, if any) contain.
                el.heading = min(6, len(ranked) + 1)
