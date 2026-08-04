"""Three-or-more column pages, detected from their gutters.

The IRS 1040 instructions are a three-column booklet. exactdoc emitted every
page as a single column, so three ~700pt columns became one ~2100pt flow and
each source page needed about 2.7 output pages -- 126 pages rendered as 308.

Two separate failures produced that, and both are covered here:

1. `margin_l` silently fell back to the constant 72.0. `_cluster` chains, so
   y06's 14,050 left edges collapsed into 3 very wide clusters, none of which
   passed `_margin_cluster`'s 8%-membership test. The true margin is 42.0, and
   the column detector requires the first column to start at the content edge,
   so it could never fire. `_margin_by_mass` measures the document instead of
   assuming 1in, and is consulted ONLY when clustering finds nothing.

2. Column detection was hard-coded to two columns. `column_grid` recognises
   N>=3 columns from their GUTTERS -- vertical bands the text does not cross --
   which is independent of how the parser grouped lines into blocks. That
   matters: on y06 p6 the parser emits one 57-line block spanning columns 2
   and 3, so any block-based test misses the structure entirely.

Deliberately restricted to N>=3: two-column pages keep their existing detector
and its reference fixture (c2_paper2col), which this must not disturb.
"""
import unittest

from exactdoc.infer import (column_grid, infer, _band_of, _column_of, _margin_by_mass,
                            _margin_cluster, MIN_COL_LINES)
from exactdoc.layout import ColBreak, Para
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock

PAGE_W, PAGE_H = 612.0, 792.0
CL, CR = 72.0, 540.0            # content column of the synthetic page
# three 148pt columns separated by 12pt gutters
BANDS = [(72.0, 220.0), (232.0, 380.0), (392.0, 540.0)]


def _boxes(bands, rows=10, y0=100.0, step=14.0):
    out = []
    for a, b in bands:
        for i in range(rows):
            out.append((a, y0 + i * step, b, y0 + i * step + 10.0))
    return out


def _line(x0, x1, y, text="the quick brown fox jumps over a lazy dog"):
    span = Span(text=text, font="Helvetica", size=10.0, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=(x0, y - 10, x1, y), origin=(x0, y))
    return Line(spans=[span], bbox=(x0, y - 10, x1, y))


def _ir_from_bands(bands, rows=12, per_block=4):
    """One page whose text sits entirely inside the given column bands.

    Several blocks per column, as a real page has: the two-column detector
    requires at least two blocks in the right-hand column before it will call
    a page columnar.
    """
    blocks = []
    for a, b in bands:
        lines = [_line(a, b, 110.0 + 14.0 * i) for i in range(rows)]
        for s in range(0, rows, per_block):
            grp = lines[s:s + per_block]
            if not grp:
                continue
            blocks.append(TextBlock(
                lines=grp, bbox=(a, grp[0].bbox[1], b, grp[-1].bbox[3])))
    pg = PageIR(number=1, width=PAGE_W, height=PAGE_H, blocks=blocks)
    return DocIR(path="cols.pdf", pages=[pg])


def _chunks(lay):
    return [ch for pl in lay.pages for ch in pl.chunks]


class GridDetection(unittest.TestCase):
    def test_three_columns(self):
        g = column_grid(_boxes(BANDS), CL, CR)
        self.assertIsNotNone(g)
        self.assertEqual(len(g), 3)
        for (ga, gb), (ea, eb) in zip(g, BANDS):
            self.assertAlmostEqual(ga, ea, delta=2.0)
            self.assertAlmostEqual(gb, eb, delta=2.0)

    def test_four_columns(self):
        bands = [(72.0, 174.0), (186.0, 288.0), (300.0, 402.0), (414.0, 516.0)]
        g = column_grid(_boxes(bands), CL, 516.0)
        self.assertIsNotNone(g)
        self.assertEqual(len(g), 4)

    def test_full_width_heading_does_not_hide_the_gutters(self):
        # a title spanning all three columns crosses both gutters; a gutter is
        # a band almost nothing crosses, not one nothing crosses
        boxes = _boxes(BANDS) + [(72.0, 60.0, 540.0, 78.0)]
        self.assertIsNotNone(column_grid(boxes, CL, CR))


class GridRefusal(unittest.TestCase):
    def test_single_column_is_not_a_grid(self):
        boxes = [(72.0, 100.0 + 14 * i, 540.0, 110.0 + 14 * i) for i in range(20)]
        self.assertIsNone(column_grid(boxes, CL, CR))

    def test_two_columns_defer_to_the_existing_detector(self):
        two = [(72.0, 300.0), (312.0, 540.0)]
        self.assertIsNone(column_grid(_boxes(two), CL, CR),
                          "N=2 must fall through to the two-column path")

    def test_irregular_widths_are_a_table_not_columns(self):
        # y06 p49: 20 bands of widths 34,14,9,9,... -- a form, not a grid
        bands, x = [], 72.0
        for w in (34, 14, 9, 9, 9, 9, 9, 9):
            bands.append((x, x + w))
            x += w + 10
        self.assertIsNone(column_grid(_boxes(bands), CL, CR))

    def test_band_carrying_no_text_is_not_a_column(self):
        thin = [BANDS[0], BANDS[1], BANDS[2]]
        boxes = _boxes(thin[:2], rows=10) + _boxes(thin[2:], rows=MIN_COL_LINES - 1)
        self.assertIsNone(column_grid(boxes, CL, CR))

    def test_narrow_content_area_is_refused(self):
        self.assertIsNone(column_grid(_boxes(BANDS), 72.0, 150.0))

    def test_no_lines_is_refused(self):
        self.assertIsNone(column_grid([], CL, CR))


class BandAssignment(unittest.TestCase):
    def test_line_inside_a_band(self):
        self.assertEqual(_band_of((232.0, 10.0, 380.0, 20.0), BANDS), 1)

    def test_line_spanning_bands_has_no_band(self):
        self.assertIsNone(_band_of((72.0, 10.0, 540.0, 20.0), BANDS))


def _ragged_last_column(rows=12, y0=100.0, step=14.0):
    """Three columns at pitch 180, whose LAST column's text stops short.

    y13_irs_pub501 p2's shape: starts 42/222/402, pitches 180 and 180, but
    inked widths 168/171/145 because the third column is ragged.
    """
    out = []
    for start, width in ((42.0, 168.0), (222.0, 171.0), (402.0, 145.0)):
        for i in range(rows):
            out.append((start, y0 + i * step, start + width, y0 + i * step + 10.0))
    return out


class PitchRegularity(unittest.TestCase):
    def test_a_ragged_last_column_is_still_a_grid(self):
        g = column_grid(_ragged_last_column(), 42.0, 547.0)
        self.assertIsNotNone(g, "inked widths 168/171/145 differ by 15%, but "
                                "the pitches are 180 and 180 -- it is a grid")
        self.assertEqual(len(g), 3)

    def test_the_bands_are_snapped_out_to_the_pitch(self):
        g = column_grid(_ragged_last_column(), 42.0, 547.0)
        widths = [b - a for a, b in g]
        self.assertAlmostEqual(max(widths) - min(widths), 0.0, delta=6.0)

    def test_a_form_is_still_refused_on_pitch(self):
        # y06 p49: bands 34,14,9,9... -- irregular widths AND pitches
        boxes, x = [], 72.0
        for w in (34.0, 14.0, 9.0, 9.0, 9.0, 9.0):
            for i in range(10):
                boxes.append((x, 100.0 + 14 * i, x + w, 110.0 + 14 * i))
            x += w + 10.0
        self.assertIsNone(column_grid(boxes, 72.0, CR))


class ColumnAssignment(unittest.TestCase):
    """Where an item goes, as distinct from whether it fits."""

    def test_an_exact_fit_keeps_its_band(self):
        self.assertEqual(_column_of((232.0, 10.0, 380.0, 20.0), BANDS), 1)

    def test_a_slight_overhang_joins_the_column_it_overlaps(self):
        # a bullet hanging left into the gutter: fits no band, is not spanning
        self.assertIsNone(_band_of((226.0, 10.0, 384.0, 20.0), BANDS))
        self.assertEqual(_column_of((226.0, 10.0, 384.0, 20.0), BANDS), 1)

    def test_a_full_width_item_still_spans(self):
        self.assertIsNone(_column_of((72.0, 10.0, 540.0, 20.0), BANDS))

    def test_the_span_threshold_is_one_and_a_half_columns(self):
        col_w = BANDS[0][1] - BANDS[0][0]
        narrow = (100.0, 10.0, 100.0 + 1.4 * col_w, 20.0)
        wide = (100.0, 10.0, 100.0 + 1.6 * col_w, 20.0)
        self.assertIsNotNone(_column_of(narrow, BANDS))
        self.assertIsNone(_column_of(wide, BANDS))

    def test_an_item_between_columns_takes_the_nearer_one(self):
        # overlaps band 2 more than band 1
        self.assertEqual(_column_of((370.0, 10.0, 470.0, 20.0), BANDS), 2)


class NoStrandedTail(unittest.TestCase):
    """The tail is what made recognising the grid cost pages rather than save
    them: items that overhang their ink band used to be linearised beneath the
    columns instead of joining them."""

    def test_overhanging_items_do_not_become_a_single_column_tail(self):
        bands = _ragged_last_column()
        # a line in column 2 that overhangs its inked band by 4pt
        blocks = []
        for start, width in ((42.0, 168.0), (222.0, 171.0), (402.0, 145.0)):
            lines = [_line(start, start + width, 110.0 + 14.0 * i)
                     for i in range(12)]
            blocks.append(TextBlock(lines=lines,
                                    bbox=(start, 100.0, start + width, 280.0)))
        over = _line(222.0, 397.0, 290.0)
        blocks.append(TextBlock(lines=[over], bbox=(222.0, 280.0, 397.0, 290.0)))
        ir = DocIR(path="ragged.pdf",
                   pages=[PageIR(number=1, width=PAGE_W, height=792.0,
                                 blocks=blocks)])
        lay = infer(ir)
        chunks = [ch for pl in lay.pages for ch in pl.chunks]
        self.assertTrue(any(ch.n_cols == 3 for ch in chunks))
        tails = [ch for ch in chunks
                 if ch.n_cols == 1 and any(isinstance(el, Para)
                                           for el in ch.elements)]
        self.assertEqual(tails, [], "an overhanging line must join its column, "
                                    "not open a one-column tail")


class MarginByMass(unittest.TestCase):
    def test_finds_the_leftmost_edge_carrying_mass(self):
        vals = [42.0] * 40 + [54.0] * 30 + [94.0] * 20
        self.assertAlmostEqual(_margin_by_mass(vals), 42.0, delta=0.6)

    def test_ignores_a_stray_outlier(self):
        vals = [12.0] + [42.0] * 60 + [54.0] * 30
        self.assertAlmostEqual(_margin_by_mass(vals), 42.0, delta=0.6)

    def test_empty_is_none(self):
        self.assertIsNone(_margin_by_mass([]))

    def test_only_consulted_when_clustering_finds_nothing(self):
        # a well-behaved page: _margin_cluster answers, so the mass estimate
        # is never reached and cannot move the result
        vals = [61.5] * 20 + [100.0] * 4
        self.assertIsNotNone(_margin_cluster(vals, left=True))


class EndToEnd(unittest.TestCase):
    def test_three_column_page_emits_one_three_column_chunk(self):
        lay = infer(_ir_from_bands(BANDS))
        cols = [ch for ch in _chunks(lay) if ch.n_cols == 3]
        self.assertEqual(len(cols), 1, "expected a single 3-column chunk")
        breaks = sum(1 for el in cols[0].elements if isinstance(el, ColBreak))
        self.assertEqual(breaks, 2, "three columns need two column breaks")

    def test_two_column_page_still_uses_the_two_column_path(self):
        lay = infer(_ir_from_bands([(72.0, 300.0), (312.0, 540.0)]))
        self.assertTrue(any(ch.n_cols == 2 for ch in _chunks(lay)),
                        "the two-column path must keep owning N=2")
        self.assertFalse(any(ch.n_cols >= 3 for ch in _chunks(lay)))

    def test_single_column_page_stays_one_column(self):
        lay = infer(_ir_from_bands([(72.0, 540.0)]))
        self.assertTrue(all(ch.n_cols == 1 for ch in _chunks(lay)))


if __name__ == "__main__":
    unittest.main()
