"""Lattice evidence outranks the bar-chart shape test.

`_classify_cluster` asked, before anything else about structure, whether three
or more filled rectangles share a bottom edge with heights differing by more
than 1.3x. That is true of a bar chart -- and equally true of a table row whose
merged cells have different heights.

When the bar test won, a whole bordered table was classified 'figure'. The
figure budget then correctly refused to rasterise that much text, and the
fallback path broke the cluster into one single-cell box per rectangle. NIST
SP 800-171 p94 is a single table 686pt tall; it became 55 stacked boxes
totalling 2947pt plus 1294pt of figures over the same region -- 4258pt of flow
for a 686pt page, about six output pages for one source page.

The discriminator is the lattice: a bar chart has ONE baseline and no interior
horizontal rules, while a table has long edges at many distinct rows and
columns. Measured over all 45 fixtures, no cluster the bar test claims on a
gated fixture has a lattice -- including c5_graphics, the chart fixture.
"""
import unittest

from exactdoc.infer import _classify_cluster
from exactdoc.model import DrawCmd


def _rect(x0, y0, x1, y1, fill="#dddddd"):
    return DrawCmd(kind="fill", shape="rect", bbox=(x0, y0, x1, y1), fill=fill,
                   stroke=None, width=0.0, opacity=1.0, n_items=1)


def _hline(x0, x1, y):
    return DrawCmd(kind="fill", shape="hline", bbox=(x0, y, x1, y + 1.0),
                   fill="#000000", stroke=None, width=0.5, opacity=1.0,
                   n_items=1)


def _vline(x, y0, y1):
    return DrawCmd(kind="fill", shape="vline", bbox=(x, y0, x + 1.0, y1),
                   fill="#000000", stroke=None, width=0.5, opacity=1.0,
                   n_items=1)


def _cl(draws):
    return list(enumerate(draws))


# Cells that share a bottom edge with very different heights: exactly the
# shape the bar-chart test looks for.
MERGED_CELLS = [_rect(90.0, 100.0, 300.0, 200.0),
                _rect(300.0, 140.0, 430.0, 200.0),
                _rect(430.0, 160.0, 520.0, 200.0)]


class TableWins(unittest.TestCase):
    def test_merged_cells_plus_lattice_is_a_grid(self):
        draws = list(MERGED_CELLS)
        for y in (100.0, 150.0, 200.0, 250.0):
            draws.append(_hline(90.0, 520.0, y))
        for x in (90.0, 300.0, 520.0):
            draws.append(_vline(x, 100.0, 250.0))
        self.assertEqual(_classify_cluster(_cl(draws)), "grid")

    def test_plain_uniform_grid_is_still_a_grid(self):
        draws = []
        for y in (100.0, 150.0, 200.0, 250.0):
            draws.append(_hline(90.0, 520.0, y))
        for x in (90.0, 300.0, 520.0):
            draws.append(_vline(x, 100.0, 250.0))
        self.assertEqual(_classify_cluster(_cl(draws)), "grid")


class ChartStillWins(unittest.TestCase):
    def test_bars_on_one_baseline_are_a_figure(self):
        # no interior rules: nothing that looks like a table
        bars = [_rect(100.0, 200.0, 130.0, 300.0),
                _rect(150.0, 240.0, 180.0, 300.0),
                _rect(200.0, 260.0, 230.0, 300.0)]
        self.assertEqual(_classify_cluster(_cl(bars)), "figure")

    def test_bars_with_only_an_axis_are_still_a_figure(self):
        # one baseline rule and one axis is not a lattice
        bars = [_rect(100.0, 200.0, 130.0, 300.0),
                _rect(150.0, 240.0, 180.0, 300.0),
                _rect(200.0, 260.0, 230.0, 300.0),
                _hline(90.0, 320.0, 300.0),
                _vline(90.0, 180.0, 300.0)]
        self.assertEqual(_classify_cluster(_cl(bars)), "figure")

    def test_equal_height_bars_are_not_claimed_by_the_bar_test(self):
        # the bar test needs differing heights; equal ones fall through and
        # must NOT be mistaken for a grid either
        bars = [_rect(100.0, 200.0, 130.0, 300.0),
                _rect(150.0, 200.0, 180.0, 300.0),
                _rect(200.0, 200.0, 230.0, 300.0)]
        self.assertNotEqual(_classify_cluster(_cl(bars)), "grid")


class LatticeThresholds(unittest.TestCase):
    def test_two_rules_are_not_a_lattice(self):
        draws = list(MERGED_CELLS)
        draws.append(_hline(90.0, 520.0, 100.0))
        draws.append(_vline(90.0, 100.0, 250.0))
        # 2 h-edges and 1 v-edge: below the lattice bar, so the bar-chart
        # test still decides and still says figure
        self.assertEqual(_classify_cluster(_cl(draws)), "figure")

    def test_short_rules_do_not_count_as_lattice_edges(self):
        # horizontal edges must span more than 40pt to count
        draws = list(MERGED_CELLS)
        for y in (100.0, 150.0, 200.0, 250.0):
            draws.append(_hline(90.0, 118.0, y))
        for x in (90.0, 300.0, 520.0):
            draws.append(_vline(x, 100.0, 250.0))
        self.assertEqual(_classify_cluster(_cl(draws)), "figure")


if __name__ == "__main__":
    unittest.main()
