"""A refined write keeps the source's page seams between multi-column pages.

The open-loop merge (`docxout._merge_grid_page_runs`) joins every run of
same-shape multi-column pages into one flow without page seams -- the booklet's
trade, which outside the booklet signature nothing asked for. A flow has
nothing to resynchronise it: on IRS Pub 15 (y12) one run ended a page ahead in
Word and a page behind in LibreOffice. With the seams kept, both renderers map
every page that fits its box one to one, so under the refine loop the writer
keeps them (`_plan_flows`, frozen once by `_freeze_flows`), and only a page
that cannot hold its box even with every gap at the loop's floor flows on into
the next ones -- until their room has absorbed it, or the plan stops.

Every test here builds its pages from real paragraphs of a known height
(one-word lines at a 12pt pitch), on a letter page with 36pt margins: a body
box of 792 - 72 - 1 = 719pt.
"""
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from exactdoc import docxout
from exactdoc.docxout import (_body_capacity, _flow_balance, _freeze_flows,
                              _merge_grid_page_runs, _plan_flows,
                              _seam_excess, write_docx)
from exactdoc.layout import (Chunk, ColBreak, DocLayout, PageLayout, Para,
                             Run)

PITCH = 12.0


def para(tag="word", sb=0.0):
    p = Para(runs=[Run(text=tag, font="Helvetica", size=10.0,
                       color="#000000")])
    p.leading = PITCH
    p.src_lines = 1
    p.space_before = sb
    return p


def column(lines, tag, sb=0.0):
    return [para("%s%d" % (tag, k), sb) for k in range(lines)]


def two_col_page(number, left, right, n_cols=2, gap=18.0):
    """A page that is one grid: `left` lines, a column break, `right` lines."""
    g = Chunk(n_cols=n_cols, col_gap=gap)
    g.elements = column(left, "p%dL" % number) + [ColBreak()] + \
        column(right, "p%dR" % number)
    return PageLayout(number=number, chunks=[g])


def one_col_page(number, lines=10):
    c = Chunk(n_cols=1)
    c.elements = column(lines, "p%d" % number)
    return PageLayout(number=number, chunks=[c])


def layout(pages):
    lay = DocLayout(src_path="x.pdf")
    lay.page_w, lay.page_h = 612.0, 792.0
    lay.margin_l = lay.margin_r = 36.0
    lay.margin_t = lay.margin_b = 36.0
    lay.pages = pages
    return lay


def colbreaks(pg):
    return sum(isinstance(e, ColBreak) for c in pg.chunks for e in c.elements)


class Geometry(unittest.TestCase):
    def test_the_box_these_tests_assume(self):
        self.assertAlmostEqual(_body_capacity(layout([])), 719.0)

    def test_a_page_is_measured_at_its_tallest_column(self):
        lay = layout([two_col_page(1, 50, 70)])
        # 70 lines of 12pt: 840pt in a 719pt box
        self.assertAlmostEqual(_seam_excess(lay.pages[0], lay, None), 121.0)

    def test_gaps_are_counted_at_the_loops_floor(self):
        g = Chunk(n_cols=2, col_gap=18.0)
        g.elements = column(55, "a", sb=10.0) + [ColBreak()] + column(10, "b")
        lay = layout([PageLayout(number=1, chunks=[g])])
        # 55 x (12 + 10 x 0.30) = 825: the loop can crush the gaps that far
        # and no further
        self.assertAlmostEqual(_seam_excess(lay.pages[0], lay, None), 106.0)

    def test_a_flow_counts_both_columns_end_to_end(self):
        lay = layout([two_col_page(1, 50, 50)])
        self.assertAlmostEqual(_flow_balance(lay.pages[0], lay, None, 2),
                               1200.0 - 2 * 719.0)


class Plan(unittest.TestCase):
    def test_pages_that_fit_keep_their_seams(self):
        lay = layout([two_col_page(i + 1, 50, 50) for i in range(3)])
        self.assertEqual(_plan_flows(lay), {1: False, 2: False, 3: False})

    def test_a_page_that_cannot_fit_flows_until_its_overflow_is_absorbed(self):
        lay = layout([two_col_page(1, 58, 70),     # 121pt over at the floor
                      two_col_page(2, 50, 50),     # 238pt of room
                      two_col_page(3, 50, 50)])
        self.assertEqual(_plan_flows(lay), {1: True, 2: False, 3: False})

    def test_a_flow_that_its_run_cannot_absorb_stops_the_plan(self):
        # Page 2 overruns by far more than page 3 has room for, and page 4
        # is another shape, so the run ends still carrying the overflow: the
        # seam after it, and every seam after that, is not trusted.
        lay = layout([two_col_page(1, 50, 50), two_col_page(2, 58, 110),
                      two_col_page(3, 50, 50), one_col_page(4),
                      two_col_page(5, 50, 50)])
        self.assertEqual(_plan_flows(lay), {1: False})

    def test_one_column_pages_are_not_planned(self):
        lay = layout([one_col_page(1), one_col_page(2)])
        self.assertEqual(_plan_flows(lay), {})

    def test_a_booklet_keeps_its_flow(self):
        lay = layout([two_col_page(i + 1, 50, 50, n_cols=3)
                      for i in range(12)])
        self.assertEqual(_plan_flows(lay), {})

    def test_the_gdocs_profile_is_never_planned(self):
        lay = layout([two_col_page(i + 1, 50, 50) for i in range(3)])
        self.assertEqual(_plan_flows(lay, "gdocs"), {})


class Merge(unittest.TestCase):
    def test_open_loop_pages_still_merge(self):
        lay = layout([two_col_page(i + 1, 50, 50) for i in range(3)])
        out = _merge_grid_page_runs(lay.pages)
        self.assertEqual(len(out), 1)
        self.assertEqual(colbreaks(out[0]), 0)

    def test_planned_pages_keep_their_seams_and_column_breaks(self):
        lay = layout([two_col_page(i + 1, 50, 50) for i in range(3)])
        _freeze_flows(lay)
        out = _merge_grid_page_runs(lay.pages)
        self.assertEqual([p.number for p in out], [1, 2, 3])
        self.assertEqual([colbreaks(p) for p in out], [1, 1, 1])

    def test_a_planned_flow_merges_exactly_its_pages(self):
        lay = layout([two_col_page(1, 58, 70), two_col_page(2, 50, 50),
                      two_col_page(3, 50, 50)])
        _freeze_flows(lay)
        out = _merge_grid_page_runs(lay.pages)
        self.assertEqual([p.number for p in out], [1, 3])
        self.assertEqual(colbreaks(out[0]), 0,
                         "inside the flow the column breaks are dropped")

    def test_after_the_plan_stops_the_merge_is_the_open_loop_one(self):
        lay = layout([two_col_page(1, 50, 50), two_col_page(2, 58, 110),
                      two_col_page(3, 50, 50), one_col_page(4),
                      two_col_page(5, 50, 50), two_col_page(6, 50, 50)])
        _freeze_flows(lay)
        out = _merge_grid_page_runs(lay.pages)
        self.assertEqual([p.number for p in out], [1, 2, 4, 5])


class Freeze(unittest.TestCase):
    def test_the_plan_is_made_once(self):
        lay = layout([two_col_page(1, 58, 70), two_col_page(2, 50, 50)])
        _freeze_flows(lay)
        self.assertEqual([p.flow_next for p in lay.pages], [True, False])
        # the loop then squeezes page 1 until it fits: the plan holds
        lay.pages[0].chunks[0].elements[60:] = []
        _freeze_flows(lay)
        self.assertEqual([p.flow_next for p in lay.pages], [True, False])

    def test_unplanned_pages_carry_no_stamp(self):
        lay = layout([one_col_page(1), two_col_page(2, 50, 50)])
        _freeze_flows(lay)
        self.assertIsNone(getattr(lay.pages[0], "flow_next", None))
        self.assertIs(lay.pages[1].flow_next, False)

    def test_what_is_not_a_layout_is_left_alone(self):
        _freeze_flows(object())

    def test_the_refine_loop_freezes_the_plan_before_its_first_write(self):
        from exactdoc import refine as R
        calls = []

        def fake_write(lay, path, **_kw):
            calls.append("write")
            raise RuntimeError("stop after the first write")

        with mock.patch("exactdoc.docxout._freeze_flows",
                        side_effect=lambda lay, prof: calls.append(prof)), \
                mock.patch("exactdoc.docxout.write_docx",
                           side_effect=fake_write), \
                tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Exception):
                R.refine(layout([]), "in.pdf", os.path.join(d, "o.docx"),
                         rounds=1, render=lambda c, s: None,
                         output_profile="standard")
        self.assertEqual(calls[:2], ["standard", "write"])


class Writer(unittest.TestCase):
    """What the renderer is handed: seams and column breaks, or one flow."""

    def _xml(self, lay):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            write_docx(lay, path, dpi=240, output_profile="standard")
            with zipfile.ZipFile(path) as z:
                return z.read("word/document.xml").decode("utf-8")
        finally:
            os.unlink(path)

    def test_a_refined_write_keeps_every_seam(self):
        lay = layout([two_col_page(i + 1, 50, 50) for i in range(3)])
        _freeze_flows(lay)
        xml = self._xml(lay)
        self.assertGreaterEqual(xml.count("pageBreakBefore"), 2)
        self.assertEqual(xml.count('w:type="column"'), 3)

    def test_an_open_loop_write_is_one_flow(self):
        lay = layout([two_col_page(i + 1, 50, 50) for i in range(3)])
        xml = self._xml(lay)
        self.assertNotIn("pageBreakBefore", xml)
        self.assertEqual(xml.count('w:type="column"'), 0)

    def test_the_layout_is_not_modified_by_a_planned_write(self):
        lay = layout([two_col_page(i + 1, 50, 50) for i in range(3)])
        _freeze_flows(lay)
        self.assertEqual(self._xml(lay), self._xml(lay))
        self.assertEqual([len(p.chunks[0].elements) for p in lay.pages],
                         [101, 101, 101])


if __name__ == "__main__":
    unittest.main()
