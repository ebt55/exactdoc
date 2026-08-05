"""A spill of one or two lines is absorbed into its page, not stranded after it.

Every source page ends in an explicit page break, so the reconstruction has no
slack at the bottom. A page whose content runs past the page box pushes the
overhanging lines onto a new rendered page, and the hard break then fires and
advances again -- leaving the spill alone on a page of its own. Measured on the
expansion corpus, that is where the excess pages come from: y02's reference arm
renders 114 source pages as 173, and 59 of the 173 are thin.

The cap is on the STRANDED LINES, not on the overflow in points. On y02 source
page 20 the flow runs 38pt past the box -- three lines' worth -- and exactly one
line is stranded, because 91pt of that overflow is the gap in front of the last
element and a gap at the top of a page is dropped rather than rendered. Capping
on the overflow refuses that page; capping on what is stranded accepts it.

Everything here is a refusal test as much as an action test. The predicate
declines a page it cannot predict, a page stranding more than two lines, and a
page whose gaps cannot cover the overflow in full, and in every one of those
cases the page is written the way it shipped.

**Requires the optional `mupdf` extra**, for the whole module rather than a
class or two. Every question here is downstream of "how many lines will this
paragraph render as", which is `ladder.predict_lines`, which needs base-14 text
metrics MuPDF is the only source of in this tree (see `exactdoc/metrics.py`).
Without it `_page_spill` returns None everywhere and these tests do not measure
a weaker predicate -- they measure an absent one. Skipping is therefore the
honest answer and asserting would be theatre.
"""
import unittest

import mupdf_extra

from exactdoc.docxout import (PAGE_BREAK_PARA_PT, SPILL_EDGE_SLACK_PT,
                              SPILL_GAP_FLOOR_PT, SPILL_MAX_LINES,
                              SPILL_MIN_GAP_SCALE, SPILL_SAFETY_PT,
                              _absorb_page_spill, _body_capacity, _page_spill)
from exactdoc.layout import (Chunk, ColBreak, DocLayout, HFPart, PageLayout,
                             Para, RuleEl, Run, TableEl)


def setUpModule():
    if not mupdf_extra.AVAILABLE:
        raise unittest.SkipTest(mupdf_extra.REASON)

CONTENT_W = 468.0
LEAD = 11.5
OVER = SPILL_EDGE_SLACK_PT + 6.0      # comfortably past the boundary bias


def _lay():
    return DocLayout(page_w=612.0, page_h=792.0, margin_l=72.0, margin_r=72.0,
                     margin_t=72.0, margin_b=72.0)


def _capacity(lay):
    return _body_capacity(lay)


def _para(gap=0.0, lead=LEAD, font="Arial", text="alpha beta gamma"):
    # Arial maps onto a base-14 family, so predict_lines can measure it, and a
    # short line at 468pt cannot wrap -- each of these is exactly one line,
    # which is what makes the arithmetic below deterministic.
    p = Para(runs=[Run(text=text, font=font, size=10.0, color="#000000")],
             leading=lead)
    p.space_before = gap
    p.src_lines = 1
    return p


def _page(lay, over_pt, tail=1, n=30, gap=8.0, lead=LEAD):
    """A one-column page whose last `tail` single-line paragraphs run over.

    The first of them ends `over_pt` past the page box, so `over_pt` at or below
    the boundary bias strands nothing at all. Each further tail paragraph
    follows with no gap of its own, so it is stranded too.
    """
    head = [_para(gap=gap, lead=lead) for _ in range(n - tail)]
    rest = [_para(gap=0.0, lead=lead) for _ in range(tail)]
    used = (n - tail) * (gap + lead)
    rest[0].space_before = round(_capacity(lay) + over_pt - used - lead, 1)
    return PageLayout(number=1, chunks=[Chunk(n_cols=1, elements=head + rest)])


def _gaps(pg):
    return [el.space_before for ch in pg.chunks for el in ch.elements
            if isinstance(el, Para)]


class Prediction(unittest.TestCase):
    def test_a_page_built_to_run_over_is_predicted_to_run_over(self):
        lay = _lay()
        over, stranded = _page_spill(_page(lay, OVER), CONTENT_W, lay)
        self.assertAlmostEqual(over, OVER, delta=0.2)
        self.assertEqual(stranded, 1)

    def test_a_page_with_room_to_spare_strands_nothing(self):
        lay = _lay()
        over, stranded = _page_spill(_page(lay, -40.0), CONTENT_W, lay)
        self.assertAlmostEqual(over, -40.0, delta=0.2)
        self.assertEqual(stranded, 0)

    def test_each_further_overhanging_line_is_counted(self):
        lay = _lay()
        for tail in (1, 2, 3, 5):
            over, stranded = _page_spill(_page(lay, OVER, tail=tail),
                                         CONTENT_W, lay)
            self.assertEqual(stranded, tail)
            self.assertAlmostEqual(over, OVER + (tail - 1) * LEAD, delta=0.3)

    def test_the_page_break_paragraph_is_taken_off_the_capacity(self):
        # The break paragraph carries an exact 1pt line and continues onto the
        # page it opens, so the usable box is that much shorter than the margins.
        self.assertGreater(PAGE_BREAK_PARA_PT, 0.0)
        lay = _lay()
        pg = _page(lay, 0.0)
        self.assertAlmostEqual(sum(_gaps(pg)) + 30 * LEAD, _capacity(lay),
                               delta=0.2)


class TheBodyBox(unittest.TestCase):
    """`w:pgMar/@footer` measures the bottom of the footer from the bottom of
    the page, and the footer grows upward. When it reaches past the bottom
    margin the renderer shortens the body, and an inferred bottom margin is
    routinely smaller than the footer distance."""

    def test_margins_alone_when_there_is_no_header_or_footer(self):
        lay = _lay()
        self.assertAlmostEqual(
            _body_capacity(lay),
            lay.page_h - lay.margin_t - lay.margin_b - PAGE_BREAK_PARA_PT,
            delta=0.01)

    def test_a_footer_reaching_past_a_thin_bottom_margin_shortens_the_body(self):
        lay = _lay()
        lay.margin_b = 14.0
        roomy = _body_capacity(lay)
        lay.footer_default = HFPart(elements=[_para()], distance=36.0)
        self.assertLess(_body_capacity(lay), roomy)
        # 36pt to the bottom of the footer plus one line of footer, against the
        # 14pt margin the layout asked for.
        self.assertAlmostEqual(roomy - _body_capacity(lay), 36.0 + LEAD - 14.0,
                               delta=0.2)

    def test_a_footer_inside_a_generous_margin_costs_nothing(self):
        lay = _lay()                       # 72pt bottom margin
        roomy = _body_capacity(lay)
        lay.footer_default = HFPart(elements=[_para()], distance=36.0)
        self.assertAlmostEqual(_body_capacity(lay), roomy, delta=0.01)

    def test_the_header_is_the_same_construct_upside_down(self):
        lay = _lay()
        lay.margin_t = 10.0
        roomy = _body_capacity(lay)
        lay.header_default = HFPart(elements=[_para()], distance=30.0)
        self.assertAlmostEqual(roomy - _body_capacity(lay), 30.0 + LEAD - 10.0,
                               delta=0.2)

    def test_a_non_paragraph_element_counts_its_own_box(self):
        lay = _lay()
        pg = _page(lay, -60.0)
        base = _page_spill(pg, CONTENT_W, lay)[0]
        rule = RuleEl(width_pct=100.0, thickness=1.0, color="#000000")
        rule._bbox = (0.0, 0.0, 100.0, 20.0)   # what `infer._el_bbox` reads
        rule.space_before = 5.0
        pg.chunks[0].elements.append(rule)
        self.assertAlmostEqual(_page_spill(pg, CONTENT_W, lay)[0], base + 25.0,
                               delta=0.2)


class Refusals(unittest.TestCase):
    """Every one of these leaves the page written the way it shipped."""

    def test_an_unpredictable_font_declines_the_page(self):
        # Georgia has no base-14 equivalent, so predict_lines returns None --
        # the same answer that has always kept the column break in place.
        lay = _lay()
        pg = _page(lay, OVER)
        pg.chunks[0].elements[0] = _para(gap=8.0, font="Georgia")
        self.assertIsNone(_page_spill(pg, CONTENT_W, lay))
        self.assertEqual(_absorb_page_spill(pg, CONTENT_W, lay), {})

    def test_a_multi_column_page_is_never_answered(self):
        lay = _lay()
        pg = _page(lay, OVER)
        pg.chunks[0].n_cols = 2
        self.assertIsNone(_page_spill(pg, CONTENT_W, lay))
        self.assertEqual(_absorb_page_spill(pg, CONTENT_W, lay), {})

    def test_a_continuation_page_is_never_answered(self):
        lay = _lay()
        pg = _page(lay, OVER)
        pg.continuation_only = True
        self.assertIsNone(_page_spill(pg, CONTENT_W, lay))

    def test_a_column_break_on_a_one_column_page_declines(self):
        lay = _lay()
        pg = _page(lay, OVER)
        pg.chunks[0].elements.insert(3, ColBreak())
        self.assertIsNone(_page_spill(pg, CONTENT_W, lay))

    def test_an_element_with_no_box_declines(self):
        lay = _lay()
        pg = _page(lay, -60.0)
        pg.chunks[0].elements.append(RuleEl(width_pct=100.0, thickness=1.0,
                                            color="#000000"))
        self.assertIsNone(_page_spill(pg, CONTENT_W, lay))

    def test_a_block_crossing_the_boundary_declines(self):
        # How a renderer splits a block across a page is not modelled here, and
        # a half-stranded block is not a two-line spill.
        lay = _lay()
        pg = _page(lay, -20.0)
        rule = RuleEl(width_pct=100.0, thickness=1.0, color="#000000")
        rule._bbox = (0.0, 0.0, 100.0, 60.0)
        rule.space_before = 0.0
        pg.chunks[0].elements.append(rule)
        self.assertIsNone(_page_spill(pg, CONTENT_W, lay))

    def test_a_table_is_measured_by_the_box_it_had_in_the_source(self):
        # Not a refusal, and that was measured rather than assumed. Refusing
        # every page carrying a table -- on the theory that a content-driven
        # row height cannot be predicted from a source box -- cost more real
        # pages than it saved: y01 recovered 3 pages and 7 with tables counted,
        # 1 and 2 with them refused, while y02's false firings only fell from
        # 27 to 21. The source box is a rough model of a table and a rough
        # model is better here than none.
        lay = _lay()
        pg = _page(lay, -60.0)
        base = _page_spill(pg, CONTENT_W, lay)[0]
        table = TableEl(rows=[[None]], col_widths=[100.0], space_before=4.0)
        table.bbox = (0.0, 0.0, 100.0, 30.0)
        pg.chunks[0].elements.insert(0, table)
        self.assertAlmostEqual(_page_spill(pg, CONTENT_W, lay)[0], base + 34.0,
                               delta=0.2)

    def test_an_empty_page_is_never_answered(self):
        lay = _lay()
        self.assertIsNone(_page_spill(PageLayout(number=1), CONTENT_W, lay))

    def test_a_page_that_strands_nothing_is_left_alone(self):
        lay = _lay()
        self.assertEqual(_absorb_page_spill(_page(lay, -40.0), CONTENT_W, lay), {})

    def test_a_page_exactly_at_capacity_is_left_alone(self):
        lay = _lay()
        self.assertEqual(_absorb_page_spill(_page(lay, 0.0), CONTENT_W, lay), {})

    def test_stranding_more_than_two_lines_is_left_alone(self):
        # Not a spill: a page that genuinely does not fit. Buying it back would
        # cost more spacing than the page is worth.
        lay = _lay()
        pg = _page(lay, OVER, tail=SPILL_MAX_LINES + 1)
        self.assertEqual(_page_spill(pg, CONTENT_W, lay)[1], SPILL_MAX_LINES + 1)
        self.assertEqual(_absorb_page_spill(pg, CONTENT_W, lay), {})

    def test_stranding_exactly_two_lines_still_fires(self):
        lay = _lay()
        pg = _page(lay, OVER, tail=SPILL_MAX_LINES)
        self.assertTrue(_absorb_page_spill(pg, CONTENT_W, lay))

    def test_gaps_that_cannot_cover_the_overflow_are_not_spent(self):
        # Every gap is already at its floor, so there is nothing to reclaim. A
        # partial payment would spend the spacing and still lose the page.
        lay = _lay()
        n = int(_capacity(lay) // (SPILL_GAP_FLOOR_PT + LEAD)) + 2
        pg = PageLayout(number=1, chunks=[Chunk(
            n_cols=1,
            elements=[_para(gap=SPILL_GAP_FLOOR_PT) for _ in range(n)])])
        over, stranded = _page_spill(pg, CONTENT_W, lay)
        self.assertGreater(over, 0.0)
        self.assertGreater(stranded, 0)
        self.assertEqual(_absorb_page_spill(pg, CONTENT_W, lay), {})


class BoundaryBias(unittest.TestCase):
    """A line poking a little past the bottom is read as fitting, so a
    prediction that is marginally pessimistic finds nothing stranded and the
    page keeps the behaviour that shipped."""

    def test_the_edge_slack_is_positive(self):
        self.assertGreater(SPILL_EDGE_SLACK_PT, 0.0)

    def test_a_line_just_inside_the_bias_strands_nothing(self):
        lay = _lay()
        pg = _page(lay, SPILL_EDGE_SLACK_PT - 1.0)
        self.assertEqual(_page_spill(pg, CONTENT_W, lay)[1], 0)
        self.assertEqual(_absorb_page_spill(pg, CONTENT_W, lay), {})

    def test_a_line_just_outside_the_bias_is_absorbed(self):
        lay = _lay()
        pg = _page(lay, SPILL_EDGE_SLACK_PT + 1.0)
        self.assertEqual(_page_spill(pg, CONTENT_W, lay)[1], 1)
        self.assertTrue(_absorb_page_spill(pg, CONTENT_W, lay))


class ThePlan(unittest.TestCase):
    def test_it_pays_at_least_the_predicted_overflow(self):
        lay = _lay()
        pg = _page(lay, OVER)
        plan = _absorb_page_spill(pg, CONTENT_W, lay)
        paid = sum(el.space_before - plan[id(el)]
                   for ch in pg.chunks for el in ch.elements if id(el) in plan)
        self.assertGreaterEqual(paid, OVER)
        self.assertAlmostEqual(paid, OVER + SPILL_SAFETY_PT, delta=0.3)

    def test_it_never_crushes_a_gap_below_its_floor(self):
        lay = _lay()
        pg = _page(lay, OVER)
        plan = _absorb_page_spill(pg, CONTENT_W, lay)
        self.assertTrue(plan)
        for ch in pg.chunks:
            for el in ch.elements:
                if id(el) not in plan:
                    continue
                floor = max(SPILL_GAP_FLOOR_PT,
                            el.space_before * SPILL_MIN_GAP_SCALE)
                self.assertGreaterEqual(plan[id(el)], floor - 0.05)
                self.assertLess(plan[id(el)], el.space_before)

    def test_it_takes_from_the_largest_gap_first(self):
        lay = _lay()
        pg = _page(lay, OVER)
        paras = [el for ch in pg.chunks for el in ch.elements]
        widest = max(paras, key=lambda p: p.space_before)
        self.assertIn(id(widest), _absorb_page_spill(pg, CONTENT_W, lay))

    def test_the_absorbed_page_strands_nothing(self):
        lay = _lay()
        pg = _page(lay, OVER)
        plan = _absorb_page_spill(pg, CONTENT_W, lay)
        for ch in pg.chunks:
            for el in ch.elements:
                if id(el) in plan:
                    el.space_before = plan[id(el)]
        over, stranded = _page_spill(pg, CONTENT_W, lay)
        self.assertLess(over, 0.0)
        self.assertEqual(stranded, 0)

    def test_planning_mutates_nothing(self):
        # The refine loop writes the same layout once per round; a correction
        # applied in place would compound on every pass.
        lay = _lay()
        pg = _page(lay, OVER)
        before = _gaps(pg)
        self.assertTrue(_absorb_page_spill(pg, CONTENT_W, lay))
        self.assertEqual(_gaps(pg), before)
        self.assertEqual(_absorb_page_spill(pg, CONTENT_W, lay),
                         _absorb_page_spill(pg, CONTENT_W, lay))


class TheWriter(unittest.TestCase):
    """The plan has to reach the file, and `lay` has to survive the write."""

    @staticmethod
    def _befores(path):
        import re
        import zipfile
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        return [int(v) for v in re.findall(r'w:before="(\d+)"', xml)]

    def _write(self, lay):
        import os
        import tempfile
        from exactdoc.docxout import write_docx
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        write_docx(lay, path)
        return path

    def _two_page_layout(self, over_pt):
        # The second page settles comfortably, so it never fires and every gap
        # it contributes is its own. -40pt is as slack as this builder goes
        # while keeping the tail gap positive; a negative gap is written as
        # zero and would show up as the writer adding space it was not asked
        # for.
        lay = _lay()
        lay.pages = [_page(lay, over_pt), _page(lay, -40.0)]
        for i, pg in enumerate(lay.pages):
            pg.number = i + 1
        return lay

    def test_a_spilling_page_is_written_with_less_space_than_it_carries(self):
        lay = self._two_page_layout(OVER)
        asked = sum(g for pg in lay.pages for g in _gaps(pg))
        emitted = sum(self._befores(self._write(lay))) / 20.0
        # Exactly the overflow plus the safety margin, and nothing else, is
        # missing from the file. Only the first page spills.
        self.assertAlmostEqual(asked - emitted, OVER + SPILL_SAFETY_PT,
                               delta=0.5)

    def test_the_write_does_not_modify_the_layout(self):
        # write_docx documents itself as pure and the refine loop depends on it:
        # a gap reduced in place would compound on every round.
        lay = self._two_page_layout(OVER)
        before = [_gaps(pg) for pg in lay.pages]
        self._write(lay)
        self.assertEqual([_gaps(pg) for pg in lay.pages], before)

    def test_writing_twice_produces_the_same_gaps(self):
        lay = self._two_page_layout(OVER)
        self.assertEqual(self._befores(self._write(lay)),
                         self._befores(self._write(lay)))

    def test_a_settled_document_is_written_exactly_as_before(self):
        # Nothing fires, so every emitted gap is the layout's own.
        lay = self._two_page_layout(-40.0)
        emitted = [v for v in self._befores(self._write(lay)) if v]
        asked = sum(g for pg in lay.pages for g in _gaps(pg) if g > 0.05)
        self.assertAlmostEqual(sum(emitted) / 20.0, asked, delta=0.5)


if __name__ == "__main__":
    unittest.main()
