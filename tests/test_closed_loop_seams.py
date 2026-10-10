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
                              _lever_room, _replan_flows,
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


def stamp(lay, plan):
    for pg in lay.pages:
        if pg.number in plan:
            pg.flow_next = plan[pg.number]


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
        stamp(lay, _plan_flows(lay))
        out = _merge_grid_page_runs(lay.pages)
        self.assertEqual([p.number for p in out], [1, 3])
        self.assertEqual(colbreaks(out[0]), 0,
                         "inside the flow the column breaks are dropped")

    def test_after_the_plan_stops_the_merge_is_the_open_loop_one(self):
        lay = layout([two_col_page(1, 50, 50), two_col_page(2, 58, 110),
                      two_col_page(3, 50, 50), one_col_page(4),
                      two_col_page(5, 50, 50), two_col_page(6, 50, 50)])
        stamp(lay, _plan_flows(lay))
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

    def test_where_the_model_stops_the_pages_are_a_seamed_probe(self):
        lay = layout([two_col_page(1, 50, 50), two_col_page(2, 58, 110),
                      two_col_page(3, 50, 50), one_col_page(4),
                      two_col_page(5, 50, 50)])
        _freeze_flows(lay)
        self.assertEqual([getattr(p, "flow_next", None) for p in lay.pages],
                         [False, False, False, None, False])
        self.assertEqual([getattr(p, "flow_probe", False) for p in lay.pages],
                         [False, True, True, False, True])

    def test_a_booklet_and_gdocs_are_never_stamped(self):
        lay = layout([two_col_page(i + 1, 50, 50, n_cols=3)
                      for i in range(12)])
        _freeze_flows(lay)
        self.assertTrue(all(getattr(p, "flow_next", None) is None
                            for p in lay.pages))
        lay = layout([two_col_page(1, 50, 50)])
        _freeze_flows(lay, "gdocs")
        self.assertIsNone(getattr(lay.pages[0], "flow_next", None))

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


def measured(spill, need):
    return {"spill": spill, "need": need, "room": [None] * len(spill),
            "anchors": 100, "offset": [0.0] * len(spill),
            "out_pages": len(spill), "src_pages": len(spill)}


class Replan(unittest.TestCase):
    """The probe read off the loop's first render (`_replan_flows`).

    Page 2 (58 + 110 lines) overruns the model by far more than pages 3
    and 4 have room for, so the model stops the plan at page 2 and pages
    2-4 are the probe."""

    def probe(self):
        lay = layout([two_col_page(1, 50, 50), two_col_page(2, 58, 110),
                      two_col_page(3, 50, 50), two_col_page(4, 50, 50)])
        _freeze_flows(lay)
        return lay

    def stamps(self, lay):
        return [getattr(p, "flow_next", None) for p in lay.pages]

    def test_the_levers_are_the_loops_own_rounds(self):
        p = Para(runs=[Run(text="x", font="Helvetica", size=10.0,
                           color="#000000")])
        p.space_before = 100.0
        g = Chunk(n_cols=2, col_gap=18.0)
        g.elements = [p]
        # half of the gaps a round, none below 30% of itself: 50 + 25 + 12.5
        self.assertAlmostEqual(_lever_room(PageLayout(number=1, chunks=[g]),
                                           3), 87.5)
        self.assertAlmostEqual(_lever_room(PageLayout(number=1, chunks=[g]),
                                           1), 50.0)

    def test_a_probe_that_held_is_kept_as_written(self):
        lay = self.probe()
        self.assertFalse(_replan_flows(lay, measured([0, 0, 0, 0],
                                                     [None] * 4)))
        self.assertEqual(self.stamps(lay), [False] * 4)
        self.assertFalse(any(getattr(p, "flow_probe", False)
                             for p in lay.pages))

    def test_a_spill_the_loop_can_take_back_holds(self):
        lay = self.probe()
        # page 2's levers: 168 lines x 12pt x 3% = 60pt
        self.assertFalse(_replan_flows(lay, measured([0, 1, 0, 0],
                                                     [None, 40.0, None, None])))
        self.assertEqual(self.stamps(lay), [False] * 4)

    def test_a_page_the_render_shows_broken_stops_the_plan_as_before(self):
        lay = self.probe()
        self.assertTrue(_replan_flows(lay, measured([0, 1, 0, 0],
                                                    [None, 900.0, None, None])))
        self.assertEqual(self.stamps(lay), [False, None, None, None])
        out = _merge_grid_page_runs(lay.pages)
        self.assertEqual([p.number for p in out], [1, 2],
                         "after the stop, the open-loop merge")

    def test_an_unreadable_render_keeps_the_models_stop(self):
        lay = self.probe()
        self.assertTrue(_replan_flows(lay, measured([0, 0, 0], [None] * 3)))
        self.assertEqual(self.stamps(lay), [False, None, None, None])

    def test_a_document_without_a_probe_is_never_replanned(self):
        lay = layout([two_col_page(i + 1, 50, 50) for i in range(3)])
        _freeze_flows(lay)
        self.assertFalse(_replan_flows(lay, measured([1, 1, 1],
                                                     [900.0] * 3)))
        self.assertEqual(self.stamps(lay), [False] * 3)


class ProbeRound(unittest.TestCase):
    """In the refine loop: a probe that changes the plan is not a candidate,
    and round 0 is written again; one that does not is round 0."""

    def _run(self, ms, changed):
        from exactdoc import refine as R
        from tests.test_refine_loop import _FakeBackend, _Writer
        renders = []

        def render(candidate, scratch):
            renders.append(candidate)
            return os.path.join(scratch, "r.pdf")

        report = {}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("exactdoc.docxout.write_docx", side_effect=_Writer()), \
                mock.patch("exactdoc.refine._measure", side_effect=ms), \
                mock.patch("exactdoc.refine._apply", return_value=True) as ap, \
                mock.patch("exactdoc.docxout._replan_flows",
                           side_effect=changed) as rp:
            R.refine(object(), "in.pdf", os.path.join(d, "o.docx"), rounds=1,
                     render=render, backend=_FakeBackend({}), report=report)
        return renders, report, ap, rp

    def m(self, pages, spill, off):
        return {"out_pages": pages, "src_pages": 2, "spill": spill,
                "offset": off, "need": [None] * len(spill)}

    def test_a_probe_that_changes_the_plan_is_discarded(self):
        renders, report, ap, rp = self._run(
            [self.m(4, [2, 0], [9.0, 9.0]), self.m(2, [0, 0], [3.0, 0.0]),
             self.m(2, [0, 0], [0.0, 0.0])], [True])
        self.assertEqual(rp.call_count, 1, "the plan is read off one probe")
        self.assertEqual(len(renders), 3)
        self.assertTrue(report["rounds"][0].get("probe"))
        self.assertEqual(report["published_round"], 1)
        self.assertEqual(ap.call_count, 1,
                         "nothing the probe measured is applied")

    def test_a_probe_that_keeps_the_plan_is_round_0(self):
        renders, report, ap, rp = self._run(
            [self.m(2, [0, 0], [3.0, 0.0]), self.m(2, [0, 0], [0.0, 0.0])],
            [False])
        self.assertEqual(len(renders), 2)
        self.assertNotIn("probe", report["rounds"][0])


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
