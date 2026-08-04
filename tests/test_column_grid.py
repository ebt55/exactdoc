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

from exactdoc.infer import (column_grid, infer, _band_of, _margin_by_mass,
                            _margin_cluster, MIN_COL_LINES)
from exactdoc.layout import ColBreak
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
