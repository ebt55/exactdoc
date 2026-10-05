"""The standard profile's page-fit planner (WP30, `exactdoc/pagefit.py`).

Every source page ends in a hard page break, so a page LibreOffice or Word
sets a line taller than the writer planned spills, and every later page sits
one place late. Measured on the checkpoint's LibreOffice renders, the page
model here is exact to a point on most pages, and what it misses is mostly a
paragraph wrapping one line longer: a page predicted to keep under a body
line spare spilled 12-17% of the time, past 20pt 1-3%. So a page predicted
to keep less than a body line plus PAGEFIT_SAFETY_PT is paid from its own
gaps, gently first, from the foot up; every other page is written byte for
byte as before, and a page its gaps cannot save is left as the source spaced
it. Each test builds the page out of layout objects, so the arithmetic is
exact; the last class converts a small reportlab PDF end to end.
"""
import os
import re
import tempfile
import unittest
import zipfile

from exactdoc.docxout import (SPILL_GAP_FLOOR_PT, SPILL_MIN_GAP_SCALE,
                              _body_capacity, write_docx)
from exactdoc.layout import (Chunk, ColBreak, DocLayout, PageLayout, Para,
                             RuleEl, Run)
from exactdoc.pagefit import (PAGEFIT_GENTLE_GAP_SCALE, PAGEFIT_SAFETY_PT,
                              fit_page, page_model, para_lines)

LEAD = 12.0
BODY = 12.0          # the body line every test page passes in
CW = 468.0


def _run(text="alpha beta gamma", font="Georgia", size=10.0):
    return Run(text=text, font=font, size=size, color="#000000")


def _para(gap=8.0, lines=2, lead=LEAD, text="alpha beta gamma",
          font="Georgia"):
    # Georgia has no width table, so the model takes the source line count
    # and the arithmetic below is exact.
    return Para(runs=[_run(text, font=font)], leading=lead, space_before=gap,
                src_lines=lines)


def _lay(**kw):
    d = dict(page_w=612.0, page_h=792.0, margin_l=72.0, margin_r=72.0,
             margin_t=72.0, margin_b=72.0)
    d.update(kw)
    return DocLayout(**d)


def _page(els, number=2, n_cols=1):
    return PageLayout(number=number, chunks=[Chunk(n_cols=n_cols, elements=els)])


def _fill(lay, spare, gap=8.0):
    """Two-line paragraphs `gap` apart whose stack ends `spare` inside the box
    (negative: past it); the last gap takes the remainder."""
    pitch = gap + 2 * LEAD
    target = _body_capacity(lay) - spare
    n = int(target // pitch)
    paras = [_para(gap=gap) for _ in range(n)]
    paras[-1].space_before = round(gap + target - n * pitch, 2)
    return paras


def _used(pg, lay, plan=None):
    return page_model(pg, CW, lay, 0.0, plan or {}, None)[0]


class TheModel(unittest.TestCase):
    def test_a_page_adds_up_to_what_it_was_built_to(self):
        lay = _lay()
        pg = _page(_fill(lay, spare=30.0))
        self.assertAlmostEqual(_used(pg, lay), _body_capacity(lay) - 30.0,
                               delta=0.1)

    def test_a_rule_is_its_exact_two_point_line(self):
        lay = _lay()
        pg = _page([_para(gap=0.0), RuleEl(width_pct=100, thickness=1.0,
                                           color="#000000", space_before=6.0)])
        self.assertAlmostEqual(_used(pg, lay), 2 * LEAD + 6.0 + 2.0)

    def test_columns_and_column_breaks_are_not_additive(self):
        lay = _lay()
        self.assertIsNone(page_model(_page([_para()], n_cols=2), CW, lay, 0.0,
                                     {}, None))
        self.assertIsNone(page_model(_page([_para(), ColBreak(), _para()]),
                                     CW, lay, 0.0, {}, None))

    def test_footnote_text_leaves_the_body_when_notes_are_real(self):
        lay = _lay()
        note = _para(gap=4.0, lines=1)
        note.role = "footnote"
        pg = _page([_para(gap=0.0), note])
        self.assertAlmostEqual(page_model(pg, CW, lay, 30.0, {}, None)[0],
                               2 * LEAD)
        self.assertAlmostEqual(page_model(pg, CW, lay, 0.0, {}, None)[0],
                               2 * LEAD + 4.0 + LEAD)

    def test_a_carrier_seam_drops_the_first_gap(self):
        # LibreOffice drops the page-top gap of the element after a page-break
        # carrier (B23): room the page has, and not a gap the plan can pay.
        lay = _lay()
        rule = RuleEl(width_pct=100, thickness=1.0, color="#000000",
                      space_before=20.0)
        pg = _page([rule, _para(gap=5.0)])
        used, gaps = page_model(pg, CW, lay, 0.0, {}, None, drop_first_gap=True)
        self.assertAlmostEqual(used, 2.0 + 5.0 + 2 * LEAD)
        self.assertEqual([g[0] for g in gaps], [pg.chunks[0].elements[1]])


class TheLineCount(unittest.TestCase):
    def setUp(self):
        from exactdoc.docxout import _text_metrics
        self.m = _text_metrics("standard")

    def test_forced_breaks_count_one_line_each_at_least(self):
        # `predict_lines` reads a soft break as a space: three short lines
        # locked with "\n" re-flowed as one.
        p = Para(runs=[_run("one\ntwo\nthree", font="Helvetica")], leading=12,
                 src_lines=3)
        self.assertEqual(para_lines(p, CW, self.m), 3)

    def test_a_line_padded_with_spaces_is_never_fewer_than_the_source(self):
        # y22 (lshort) sets code beside its output with runs of spaces; the
        # predictor measures one space per gap and called two lines one.
        text = "\\begin{verbatim}" + " " * 60 + "the output"
        p = Para(runs=[_run(text, font="Courier")], leading=12, src_lines=2)
        self.assertEqual(para_lines(p, CW, self.m), 2)

    def test_an_ordinary_paragraph_is_the_predicted_wrap(self):
        p = Para(runs=[_run("word " * 200, font="Helvetica")], leading=12,
                 src_lines=1)
        self.assertGreater(para_lines(p, CW, self.m), 3)

    def test_no_width_table_is_the_source_count(self):
        p = _para(lines=4)
        self.assertEqual(para_lines(p, CW, self.m), 4)


class ThePlan(unittest.TestCase):
    def _plan(self, pg, lay, plan=None, notes_h=0.0, rep=None):
        return fit_page(pg, CW, lay, notes_h, BODY, plan if plan is not None
                        else {}, report=rep)

    def test_a_page_with_a_body_line_to_spare_keeps_the_callers_plan(self):
        lay = _lay()
        pg = _page(_fill(lay, spare=BODY + PAGEFIT_SAFETY_PT + 0.5))
        given = {"sentinel": 1.0}
        self.assertIs(self._plan(pg, lay, given), given)

    def test_a_page_short_of_its_budget_is_paid_exactly_that(self):
        lay = _lay()
        pg = _page(_fill(lay, spare=3.0))
        plan = self._plan(pg, lay)
        self.assertTrue(plan)
        after = _used(pg, lay, plan)
        want = _body_capacity(lay) - BODY - PAGEFIT_SAFETY_PT
        self.assertLessEqual(after, want + 1e-6)
        self.assertGreater(after, want - 0.1 * len(plan) - 1e-6)

    def test_the_foot_pays_first(self):
        lay = _lay()
        els = _fill(lay, spare=3.0)
        plan = self._plan(_page(els), lay)
        paid = [i for i, el in enumerate(els) if id(el) in plan]
        # need ~11pt; the last gaps (8pt, gentle floor 4.8pt) pay it
        self.assertEqual(paid, list(range(len(els) - len(paid), len(els))))
        self.assertLess(len(paid), len(els) // 2)

    def test_gently_before_the_floors(self):
        lay = _lay()
        els = _fill(lay, spare=-40.0)
        plan = self._plan(_page(els), lay)
        floors = [plan.get(id(el), el.space_before) for el in els]
        # 40 over plus the budget: the gentle tier (60%) of every gap first;
        # no gap below its gentle floor while another sits above it
        gentle = [max(SPILL_GAP_FLOOR_PT, el.space_before *
                      PAGEFIT_GENTLE_GAP_SCALE) for el in els]
        below = [f < g - 0.11 for f, g in zip(floors, gentle)]
        above = [f > g + 0.11 for f, g in zip(floors, gentle)]
        self.assertFalse(any(below) and any(above))

    def test_a_page_its_gaps_cannot_save_is_left_as_spaced(self):
        lay = _lay()
        els = _fill(lay, spare=-200.0)
        given = {}
        rep = {}
        self.assertIs(self._plan(_page(els), lay, given, rep=rep), given)
        self.assertTrue(rep["at_risk"])
        self.assertGreater(rep["short"], 0.0)

    def test_the_cap_leaves_a_page_many_lines_over_as_spaced(self):
        # PAGEFIT_MAX_OVER_LINES: y59's first page, 11 body lines over by
        # the model, was paid back into its box and its placement fell
        from exactdoc import pagefit
        lay = _lay()
        far = _page(_fill(lay, spare=-4 * BODY))
        near = _page(_fill(lay, spare=-2 * BODY))
        was = pagefit.PAGEFIT_MAX_OVER_LINES
        pagefit.PAGEFIT_MAX_OVER_LINES = 3
        try:
            given = {}
            self.assertIs(self._plan(far, lay, given), given)
            self.assertTrue(self._plan(near, lay))
        finally:
            pagefit.PAGEFIT_MAX_OVER_LINES = was
        self.assertTrue(self._plan(far, lay))

    def test_no_gap_goes_below_the_refine_floor(self):
        lay = _lay()
        els = _fill(lay, spare=-60.0)
        plan = self._plan(_page(els), lay)
        self.assertTrue(plan)
        for el in els:
            floor = max(SPILL_GAP_FLOOR_PT, el.space_before * SPILL_MIN_GAP_SCALE)
            self.assertGreaterEqual(plan.get(id(el), el.space_before),
                                    floor - 0.1 - 1e-6)

    def test_the_notes_area_is_room_the_body_does_not_have(self):
        lay = _lay()
        pg = _page(_fill(lay, spare=40.0))
        self.assertEqual(self._plan(pg, lay), {})
        self.assertTrue(self._plan(pg, lay, notes_h=35.0))

    def test_nothing_is_mutated(self):
        lay = _lay()
        els = _fill(lay, spare=-20.0)
        before = [el.space_before for el in els]
        self._plan(_page(els), lay)
        self.assertEqual([el.space_before for el in els], before)

    def test_a_continuation_page_is_not_asked(self):
        lay = _lay()
        pg = _page(_fill(lay, spare=3.0))
        pg.continuation_only = True
        self.assertEqual(self._plan(pg, lay), {})


def _befores(lay, profile="standard"):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "o.docx")
        write_docx(lay, path, output_profile=profile)
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8")
    return [int(v) for v in re.findall(r'w:before="(\d+)"', xml)]


class _On(unittest.TestCase):
    """The planner is shipped off (`pagefit.PAGEFIT_ENABLED`); these tests
    switch it on for themselves."""

    def setUp(self):
        from exactdoc import pagefit
        self._was = pagefit.PAGEFIT_ENABLED
        pagefit.PAGEFIT_ENABLED = True

    def tearDown(self):
        from exactdoc import pagefit
        pagefit.PAGEFIT_ENABLED = self._was


class TheSwitch(unittest.TestCase):
    def test_off_by_default_and_then_the_writer_is_as_before(self):
        from exactdoc import pagefit
        self.assertFalse(pagefit.PAGEFIT_ENABLED)
        lay = _lay()
        full = _page(_fill(lay, spare=3.0))
        lay.pages = [_page([_para(gap=0.0)], number=1), full]
        asked = [round(el.space_before * 20) for el in full.chunks[0].elements]
        got = _befores(lay)
        for v in asked:
            self.assertIn(v, got)


class TheWriter(_On):
    def _doc(self, spare):
        lay = _lay()
        first = _page([_para(gap=0.0)], number=1)
        full = _page(_fill(lay, spare=spare))
        last = _page([_para(gap=0.0)], number=3)
        lay.pages = [first, full, last]
        return lay, full

    def test_a_page_that_fits_is_written_with_its_own_gaps(self):
        lay, full = self._doc(spare=40.0)
        asked = [round(el.space_before * 20) for el in full.chunks[0].elements]
        got = _befores(lay)
        for v in asked:
            self.assertIn(v, got)

    def test_a_page_at_risk_is_written_with_less_space(self):
        lay, full = self._doc(spare=3.0)
        asked = sum(el.space_before for el in full.chunks[0].elements)
        got = sum(_befores(lay)) / 20.0
        self.assertAlmostEqual(asked - got, BODY + PAGEFIT_SAFETY_PT - 3.0,
                               delta=0.5)

    def test_the_layout_is_not_modified(self):
        lay, full = self._doc(spare=3.0)
        asked = [el.space_before for el in full.chunks[0].elements]
        _befores(lay)
        self.assertEqual([el.space_before for el in full.chunks[0].elements],
                         asked)

    def test_a_page_before_a_blank_page_is_left_as_spaced(self):
        # Its overflow is what fills the blank verso (y30's cover): fitting
        # it would delete that page.
        lay, full = self._doc(spare=3.0)
        lay.pages.insert(2, PageLayout(number=3, chunks=[Chunk(elements=[])]))
        lay.pages[3].number = 4
        asked = [round(el.space_before * 20) for el in full.chunks[0].elements]
        got = _befores(lay)
        for v in asked:
            self.assertIn(v, got)


def _three_page_pdf(path, paras=(6, 14, 4)):
    """Pages of three-line Helvetica paragraphs (two full lines and a short
    one, 13pt pitch, 9pt apart) under a folio. Page 2's fourteen paragraphs
    end some 6pt inside the body box the folio leaves: inside it, but under
    a body line to spare."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas
    words = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda "
             "mu nu xi omicron pi rho sigma tau").split()
    c = canvas.Canvas(path, pagesize=(612, 792))
    for page, count in enumerate(paras, start=1):
        y = 82.0
        for p in range(count):
            for ln in range(3):
                line, k = [], 0
                while True:
                    w = words[(p * 3 + ln + k) % len(words)]
                    if stringWidth(" ".join(line + [w]), "Helvetica", 10) > \
                            (440 if ln < 2 else 200):
                        break
                    line.append(w)
                    k += 1
                c.setFont("Helvetica", 10)
                c.drawString(72, 792 - y, " ".join(line))
                y += 13.0
            y += 9.0
        c.setFont("Helvetica", 9)
        c.drawString(300, 40, str(page))
        c.showPage()
    c.save()


class EndToEnd(_On):
    """Converted open-loop, only the tight page's gaps change, only at its
    foot, and by about what a body line plus the safety needs."""

    def _befores(self, pdf, d, planner=True):
        from exactdoc import pagefit
        from exactdoc.convert import convert_result
        from exactdoc.options import RAW
        out = os.path.join(d, "p.docx" if planner else "c.docx")
        pagefit.PAGEFIT_ENABLED = planner
        try:
            convert_result(pdf, out, options=RAW)
        finally:
            pagefit.PAGEFIT_ENABLED = True
        with zipfile.ZipFile(out) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        return [int(v) for v in re.findall(r'w:before="(\d+)"', xml)]

    def test_only_the_tight_page_moves(self):
        try:
            import reportlab  # noqa: F401
        except ImportError:
            self.skipTest("reportlab not installed")
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "t.pdf")
            _three_page_pdf(pdf)
            planned = self._befores(pdf, d)
            control = self._befores(pdf, d, planner=False)
        self.assertEqual(len(planned), len(control))
        moved = [i for i, (a, b) in enumerate(zip(planned, control)) if a != b]
        self.assertTrue(moved)
        # one run of gaps, ending at page 2's last paragraph (page 3 has
        # four paragraphs and so four befores after it)
        self.assertEqual(moved, list(range(moved[0], moved[-1] + 1)))
        self.assertEqual(moved[-1], len(control) - 5)
        paid = sum(control) - sum(planned)
        self.assertGreater(paid, 0)
        self.assertLess(paid / 20.0, 13.0 + PAGEFIT_SAFETY_PT)
        self.assertTrue(all(a <= b for a, b in zip(planned, control)))
