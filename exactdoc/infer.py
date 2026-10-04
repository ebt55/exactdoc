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
                     ColBreak, Chunk, PageLayout, HFPart, HFSection, DocLayout)
from .furniture import (DECIMAL, num_tokens, page_number_model, is_page_number,
                        furniture_text, printed_parity, numbering_sections)
from . import hyphen
from .lists import assign_lists
from .notes import bind_page_notes, find_page_notes, number_footnotes

BULLET_CHARS = set("•◦▪‣·-–—*➤►○●♦")
NUM_RE = re.compile(r"^\(?(\d{1,3}|[a-zA-Z]|[ivxlIVXL]{1,5})[\.\)\:]$")

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
    if sum(1 for b in left if b[2] - b[0] >= TWO_COL_FULL_LINE_FRAC * lw) < \
            TWO_COL_MIN_FULL_LINES or \
            sum(1 for b in right if b[2] - b[0] >= TWO_COL_FULL_LINE_FRAC * rw) < \
            TWO_COL_MIN_FULL_LINES:
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
        row.sort(key=lambda l: l.bbox[0])
        if len(row) == 1:
            out.append(row[0])
            continue
        spans = []
        for i, ln in enumerate(row):
            if i > 0 and spans:
                gap = ln.bbox[0] - row[i - 1].bbox[2]
                if gap > 0.25 * (spans[-1].size or 10) and \
                        not spans[-1].text.endswith(" "):
                    spans[-1].text += " "
            spans.extend(ln.spans)
        bb = None
        for ln in row:
            bb = bbox_union(bb, ln.bbox)
        out.append(Line(spans=spans, bbox=bb, dir=row[0].dir))
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
_INLINE_ORD_RE = re.compile(r"(\(?)(\d{1,3}|[ivx]{1,5}|[a-zA-Z])([.)])(?=\s+\S)")
_INLINE_X_TOL = 2.0     # same list column: markers of one list share their x
_INLINE_HANG_MAX = 40.0  # a hang wider than this is a new column, not a marker's width


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
                if 1.5 < nx.bbox[0] - ln.bbox[0] <= _INLINE_HANG_MAX \
                        and 0 < nx.baseline - ln.baseline <= 2.2 * sz \
                        and _inline_marker(nx.text) is None:
                    hang = True
            cands.append((ln, m[0], m[1], hang))
    out = set()
    for ln, style, vals, hang in cands:
        peers = [c for c in cands if c[1] == style and c[0] is not ln
                 and abs(c[0].bbox[0] - ln.bbox[0]) <= _INLINE_X_TOL]
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


def _opens_note(ln: Line) -> bool:
    """Does the line open with a glued footnote number (`_merge_list_markers`)?"""
    first = min((s for s in ln.spans if s.text.strip()),
                key=lambda s: s.bbox[0], default=None)
    return first is not None and getattr(first, "_note_mark", False)


def _split_lines_to_paras(lines: List[Line],
                          list_starts: Optional[set] = None) -> List[List[Line]]:
    """Group a flat list of lines into paragraphs on large baseline gaps,
    dominant-size jumps, letter-spacing changes, or list-marker starts.

    `list_starts` holds the `_line_key`s of lines that open a list item with a
    typed marker, decided over the whole flow by `_inline_list_starts`."""
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
        if deltas[i] > max(lead * 1.55, lead + 4.0) or size_jump or track_jump \
                or _line_starts_with_marker(ln) or _line_key(ln) in list_starts \
                or _opens_note(ln):
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
    p = Para(bbox=bbox)
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
        elif col_r - x1 < 2.5 and x0 - col_l > 10:
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
    over = start + width - room
    if start <= 0 or over <= OVERHANG_TOL:
        return
    short = (p.src_lines or 1) <= 1 and width <= SHORT_LINE_FRAC * room
    if not short and room - start >= STARVED_FRAC * width:
        return
    p.left_indent = round(max(0.0, -p.first_indent, p.left_indent - over), 1)


def paras_from_line_list(lines: List[Line], col_l: float, col_r: float,
                         list_starts: Optional[set] = None) -> List[Para]:
    out = []
    ccx = (col_l + col_r) / 2
    list_starts = list_starts or set()
    for grp in _split_lines_to_paras(lines, list_starts):
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
                    continue
        p = para_from_lines(grp, col_l, col_r,
                            list_start=_line_key(grp[0]) in list_starts)
        p._note = _opens_note(grp[0])
        out.append(p)
    return out


# ------------------------------------------------------------------ HF detect
def _norm_text(t: str) -> str:
    return re.sub(r"\d+", "#", t.strip())


def detect_hf(ir: DocIR):
    n = len(ir.pages)
    H = ir.pages[0].height if ir.pages else 792
    W = ir.pages[0].width if ir.pages else 612
    res = {
        "consumed_text": defaultdict(set), "consumed_draw": defaultdict(set),
        "band_first": None, "band_def": None, "rep_lines": defaultdict(list),
        "rep_draws": defaultdict(list), "line_roles": {},
        "page_numbers": {}, "num_sections": [], "parity": {},
        # varying furniture: consumed from the body, not part of the modal
        # signature; `infer` states it per running-head section
        "var_lines": defaultdict(list),
    }
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
        for sig, occ in geo.items():
            per_page = defaultdict(list)
            for pg, bi, ln in occ:
                per_page[pg].append((bi, ln))
            single = [pg for pg, v in per_page.items() if len(v) == 1]
            if len(single) < geo_need:
                continue
            for pg in single:
                bi, ln = per_page[pg][0]
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
        for di, d in enumerate(p.drawings):
            if di in res["consumed_draw"][p.number]:
                continue
            y0, y1 = d.bbox[1], d.bbox[3]
            zone = "top" if y1 <= TOPZ else ("bot" if y0 >= p.height - BOTZ else None)
            if zone and d.shape in ("hline", "vline", "rect", "line"):
                sig = (zone, round(y0 / 3), round(d.bbox[0] / 5), d.shape, d.fill, d.stroke)
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
    # the source's own per-page furniture rules. Reverted; the +2% class
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
            if 0 < y0 - ry < 18:
                pp.border_top = (th, colr, round(y0 - ry, 1))
            elif 0 < ry - y1 < 18:
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


def _clusters(draws):
    n = len(draws)
    uf = _UF(n)
    for i in range(n):
        for j in range(i + 1, n):
            if _touches(draws[i][1].bbox, draws[j][1].bbox):
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


def _classify_cluster(cl) -> str:
    ds = [d for _, d in cl]
    art = [d for d in ds if d.shape in ("curve", "complex", "line")
           and not _is_glyphlike(d)]
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
    if len(fills) == 1:
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

    def close(cur, bands):
        # trailing rule-only frames belong to whatever follows, not here
        while cur and not cur[-1][2]:
            cur.pop()
        if sum(1 for _, _, tiled in cur if tiled) >= 2:
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


def build_rules_table(hgroup: List[DrawCmd], blocks, consumed) -> Optional[TableEl]:
    hgroup = sorted(hgroup, key=lambda d: d.bbox[1])
    x0 = min(d.bbox[0] for d in hgroup)
    x1 = max(d.bbox[2] for d in hgroup)
    top, bot = hgroup[0].bbox[1], hgroup[-1].bbox[3]
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
        frags = _split_at_span_gaps(ln)
        joined = joined or len(frags) > 1
        lines.extend(frags)
    rows = _group_lines_by_row(lines)
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
        if len(rows) < 2 or sum(1 for r in rows if len(r) >= 2) < \
                max(2, int(0.6 * len(rows))):
            return None
    if bounds is None:
        col_lefts = _cluster([ln.bbox[0] for ln in lines], 7.0)
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
        for d in hgroup[1:-1]:
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
            for ci in range(nc):
                rl = [l for l in rows[ri]
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
        cell.paras = paras_from_line_list(lines, minx, rect[2] - 4)
        t0 = _para_box(cell.paras[0])[0] if cell.paras else rect[1]
        pad_top = max(0.0, round(t0 - rect[1], 1))
        end = _space_paras(cell.paras, rect[1] + pad_top)
        cell.pad = (pad_top, cell.pad[1], max(0.0, round(rect[3] - end, 1)),
                    cell.pad[3])
        for p in cell.paras:
            if p.align in ("left", "justify"):
                p.left_indent = max(0.0, round((p.bbox[0] if p.bbox else minx) - minx, 1))
    role = "code" if is_code else ("box" if (fill_rect or stroke_rect)
                                   else "quote")
    return TableEl(rows=[[cell]], col_widths=[rect[2] - rect[0]],
                   row_heights=[rect[3] - rect[1]], role=role, bbox=rect)


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
    bb = (max(0, bb[0] - 2), max(0, bb[1] - 2),
          min(page.width, bb[2] + 2), min(page.height, bb[3] + 2))
    return FigureEl(page_no=page.number, clip=bb,
                    width=bb[2] - bb[0], height=bb[3] - bb[1])


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
def infer(ir: DocIR) -> DocLayout:
    """DocIR -> DocLayout.

    The document's hyphenation evidence is built first and made current for
    the whole inference, so every line join -- paragraphs, cells, headers,
    merged flow -- resolves its line-end hyphen against the same vocabulary
    (see exactdoc.hyphen and _soft_join).
    """
    token = hyphen.activate(hyphen.HyphenEvidence.from_ir(ir) if ir.pages else None)
    try:
        lay = _infer(ir)
    finally:
        hyphen.deactivate(token)
    hyphen.mark_unhyphenated(lay)
    return lay


def _infer(ir: DocIR) -> DocLayout:
    lay = DocLayout(src_path=ir.path)
    lay.font_advances = getattr(ir, "font_advances", None) or {}
    if not ir.pages:
        return lay
    p0 = ir.pages[0]
    lay.page_w, lay.page_h = p0.width, p0.height
    n_pages = len(ir.pages)
    hf = detect_hf(ir)
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
    _infer_body(lay, ir, hf, n_pages, own_geometry)
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
        # header at 35pt (audit B26).
        draws = [d for di, d in enumerate(p.drawings) if di not in cd and
                 bbox_area(d.bbox) < PAGE_COVER_FRAC * p.width * p.height]
        ys += [d.bbox[1] for d in draws]
        ye += [d.bbox[3] for d in draws]
        if ys and not (p.number == 1 and band1_h > 45):
            tops.append(min(ys))
        if ye:
            bots.append(max(ye))
    lay.margin_t = round(max(10.0, min(min(tops) if tops else 54.0, 120.0)), 1)
    max_bot = max(bots) if bots else lay.page_h - 54
    lay.margin_b = round(max(14.0, min(72.0, lay.page_h - max_bot - 16.0)), 1)


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
    return out


def _infer_body(lay: DocLayout, ir: DocIR, hf: dict, n_pages: int,
                own_geometry: Dict[int, DocLayout]) -> None:
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
    for p in ir.pages:
        own = own_geometry.get(p.number)
        lay = _geometry(doc_lay, own)
        content_w = lay.content_w
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
            if (d.bbox[3] - d.bbox[1]) > 2.2 or (d.bbox[2] - d.bbox[0]) > 0.6 * content_w:
                continue
            hit = False
            for ln in _all_lines(blocks):
                for s in ln.spans:
                    if s.bbox[0] - 2.5 <= d.bbox[0] and d.bbox[2] <= s.bbox[2] + 2.5 \
                            and -1.0 <= d.bbox[1] - s.origin[1] <= 3.5:
                        s._ul = True
                        hit = True
            if hit:
                cd.add(di)

        elements: List[Any] = []
        draws = [(i, d) for i, d in enumerate(p.drawings)
                 if i not in cd and d.opacity > 0.05]
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
        page_text_area = sum(bbox_area(l.bbox) for l in _all_lines(blocks)) or 1.0
        clusters = _clusters(draws)
        # Fill-tiled tables first: their row bands are separate clusters,
        # and each alone reads as cards, bars or a figure.
        for band in _tile_bands(clusters, blocks, consumed):
            el = build_grid_table([it for c in band for it in c], blocks,
                                  consumed, tiled=True)
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
            if len(grp) >= 2:
                ys = sorted(d.bbox[1] for _, d in grp)
                if ys[-1] - ys[0] < 320:
                    t = build_rules_table([d for _, d in grp], blocks, consumed)
                    if t is not None:
                        elements.append(t)
                        used.update(i for i, _ in grp)
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
                    and (d.bbox[3] - d.bbox[1]) > 10:
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
                if in_side_margin(d.bbox, lay.margin_l, lay.margin_r, p.width):
                    continue
                elements.append(build_figure([d], blocks, p.images, consumed, p))

        for im in p.images:
            if getattr(im, "_consumed", False) or im.data is None:
                continue
            if in_side_margin(im.bbox, lay.margin_l, lay.margin_r, p.width):
                continue        # marginal logo/icon: furniture, not flow
            el = ImageEl(data=im.data, ext=im.ext,
                         width=im.bbox[2] - im.bbox[0], height=im.bbox[3] - im.bbox[1])
            el._bbox = im.bbox
            elements.append(el)

        elements = _merge_figures(elements)

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
        prev_notes = bool(pn is not None and
                          bind_page_notes(doc_lay, pl, pn, col_l, col_r))
        doc_lay.pages.append(pl)

    lay = doc_lay
    number_footnotes(lay)
    _coalesce_striped_table_segments(lay)
    _propagate_list_hangs([el for pg in lay.pages for ch in pg.chunks
                           for el in ch.elements if isinstance(el, Para)])
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
    p.runs = [r for r in label if r.text] + [tab] + [r for r in num if r.text]
    p.align = "left"
    p.right_indent = 0.0
    p.first_indent = 0.0
    p.tab_stops = [(round(edge - col_l, 1), "right", "dot")]
    p.leader_text = m.group("dots")
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
    for bi, fr in lines:
        if id(fr) in moved or id(fr) in hosts:
            continue
        fsz = _line_size(fr)
        fw = fr.bbox[2] - fr.bbox[0]
        best = None
        for hj, h in lines:
            if h is fr or id(h) in moved:
                continue
            hsz = _line_size(h)
            hw = h.bbox[2] - h.bbox[0]
            if fsz > hsz + 0.1:
                continue
            d = abs(fr.baseline - h.baseline)
            if d < 0.05 * hsz:
                # a continuation: maths, a few glyphs wide -- never the line of
                # a neighbouring column, which is prose as wide as its own
                gap = fr.bbox[0] - h.bbox[2]
                if hj == bi or fw > FRAG_MAX_SHARE * hw or not _mathy([fr]) \
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
        hsz = _line_size(h)
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


def _to_flow(items, col_l, col_r, doc_rows=None):
    items = _split_blocks_at_elements(items)
    leaders, lconsumed = _leader_lines(items, col_l, col_r)
    if lconsumed:
        items = _drop_row_lines(items, lconsumed) + \
            [("leader", ln.bbox, (ln, edge)) for ln, edge in leaders]
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
    for kind, bb, o in sorted(items, key=lambda t: (t[1][1], t[1][0])):
        if kind == "leader":
            out.append(_leader_para(o[0], o[1], col_l, col_r))
        elif kind == "display":
            out.extend(_display_paras(o, col_l, col_r))
        elif kind == "grid":
            out.append(_grid_para(o, col_l, col_r))
        elif kind == "row":
            out.append(_row_para(o[0], o[1], col_l, col_r))
        elif kind == "blk":
            out.extend(paras_from_line_list(
                list(o) if isinstance(o, list) else list(o.lines), col_l, col_r,
                list_starts))
        else:
            el = o
            if isinstance(el, TableEl):
                el.left_indent = max(0.0, round((el.bbox[0] if el.bbox else col_l) - col_l, 1))
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
    return out


def _mergeable(a: Para, b: Para) -> bool:
    if a.heading or b.heading:
        return False
    # A paragraph that carries its own line breaks (verbatim blocks, the
    # ladder's line-locked encoding) is a sequence of source lines, not a
    # reflowable run of prose. Merging it with a neighbour joins the two
    # with a space and undoes the break structure both were built with.
    if getattr(a, "line_breaks", False) or getattr(b, "line_breaks", False):
        return False
    if any(r.is_tab for r in a.runs) or any(r.is_tab for r in b.runs):
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
    # Likewise a footnote that opens with its own number (`_opens_note`).
    if getattr(b, "_note", False):
        return False
    gap = b.bbox[1] - a.bbox[3]
    if not (-2.0 <= gap <= 3.2):
        return False
    # An item that hangs continues at its TEXT column, not at its marker: a
    # paragraph starting under the marker is the next paragraph after the
    # list, and one starting at the hang is the item's own continuation.
    ax = a.bbox[0]
    if getattr(a, "_list_item", False) and a.first_indent < -1.0:
        ax = a.bbox[0] - a.first_indent
    if abs(b.bbox[0] - ax) > 2.5:
        return False
    sa = max((r.size for r in a.runs if r.text.strip()), default=0)
    sb = max((r.size for r in b.runs if r.text.strip()), default=0)
    return abs(sa - sb) < 0.6


def _merge_flow_paras(seq, col_r):
    out = []
    for el in seq:
        if out and isinstance(el, Para) and isinstance(out[-1], Para) \
                and _mergeable(out[-1], el):
            a = out[-1]
            if getattr(a, "_vis_lines", 1) == 1 and el.bbox and a.bbox:
                delta = round(el.bbox[1] - a.bbox[1], 2)
                if delta > 2:
                    a.leading = delta
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


def _is_marker_line(ln: Line) -> bool:
    t = ln.text.strip()
    # Bare digits count too: step/badge lists number their items "1", "2"
    # without trailing punctuation, and some producers emit each such
    # marker as its own block. Only the separated-marker merge uses this
    # (it still demands a shared baseline with adjacent item text); the
    # inline marker split keeps the stricter NUM_RE.
    return (ln.bbox[2] - ln.bbox[0]) < 44 and bool(
        t in BULLET_CHARS or NUM_RE.match(t) or
        (t.isdigit() and len(t) <= 3))


def _merge_list_markers(flow_blocks):
    """Some producers (WeasyPrint) emit list markers as separate blocks —
    sometimes several markers stacked in ONE block. Glue each marker line back
    onto the item text line that shares its baseline."""
    marker_lines = []
    for b in flow_blocks:
        if all(_is_marker_line(l) or not l.text.strip() for l in b.lines):
            marker_lines.extend((l, b) for l in b.lines if _is_marker_line(l))
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
                opens = not _RTL_TEXT.search(fl.text)
                for s in ln.spans:
                    s.superscript = True
                    s.origin = (s.origin[0], host_base)
                    s._note_mark = opens
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
            _to_flow(lead, content_l, content_r, doc_rows=lay_rows), content_r)
        chunks.append(ch)
    gaps = [bands[i + 1][0] - bands[i][1] for i in range(len(bands) - 1)]
    ch = Chunk(n_cols=len(bands), col_gap=max(10.0, round(sum(gaps) / len(gaps), 1)))
    flows = []
    for i, (a, b) in enumerate(bands):
        items = sorted((t for bi, t in banded if bi == i),
                       key=lambda t: (t[1][1], t[1][0]))
        flows.append(_merge_flow_paras(
            _to_flow(items, a, b, doc_rows=lay_rows), b))
    ch.elements = flows[0]
    for f in flows[1:]:
        ch.elements = ch.elements + [ColBreak()] + f
    chunks.append(ch)
    if tail:
        tail.sort(key=lambda t: (t[1][1], t[1][0]))
        ch2 = Chunk(n_cols=1)
        ch2.elements = _merge_flow_paras(
            _to_flow(tail, content_l, content_r, doc_rows=lay_rows), content_r)
        chunks.append(ch2)
    return chunks


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
                   col_split: float, page_top: Optional[float]) -> List[Chunk]:
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
                              page_top)
    if twocol and _split_crossed(flow_lines, col_split, content_l, content_r):
        twocol = False

    items = [("blk", b.bbox, b) for b in flow_blocks]
    for e in elements:
        bb = _el_bbox(e)
        items.append(("el", bb or (content_l, 0, content_r, 0), e))
    items.sort(key=lambda t: (t[1][1], t[1][0]))

    chunks: List[Chunk] = []
    if not twocol:
        ch = Chunk(n_cols=1)
        ch.elements = _merge_flow_paras(
            _to_flow(items, content_l, content_r, doc_rows=lay_rows), content_r)
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
                _to_flow(lead, content_l, content_r, doc_rows=lay_rows), content_r)
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
                content_r)
            return _position_chunks([ch], lay, page_top)
        ch = Chunk(n_cols=2, col_gap=gap)
        colr_edge = col_split - gap
        left_flow = _merge_flow_paras(
            _to_flow(colL, content_l, colr_edge, doc_rows=lay_rows), colr_edge)
        right_flow = _merge_flow_paras(
            _to_flow(colR, col_split, content_r, doc_rows=lay_rows), content_r)
        ch.elements = left_flow + [ColBreak()] + right_flow
        chunks.append(ch)
        if wide_tail:
            ch2 = Chunk(n_cols=1)
            ch2.elements = _merge_flow_paras(
                _to_flow(wide_tail, content_l, content_r, doc_rows=lay_rows),
                content_r)
            chunks.append(ch2)

    return _position_chunks(chunks, lay, page_top)


def _position_chunks(chunks: List[Chunk], lay: DocLayout,
                     page_top: Optional[float]) -> List[Chunk]:
    """Turn absolute source positions into the flow's space_before values."""
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
        for el in ch.elements:
            if isinstance(el, ColBreak):
                cursor = top
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
            maxy = max(maxy, cursor)
        base = maxy
    return chunks


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
            for ch in pg.chunks:
                for el in ch.elements:
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
        for ch in pg.chunks:
            els = [e for e in ch.elements if not isinstance(e, ColBreak)]
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
