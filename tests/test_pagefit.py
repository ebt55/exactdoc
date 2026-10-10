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
                              _hang_body, fit_page, page_model, para_lines,
                              plan_page)

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

    def _row(self, date, body, stops):
        tab = Run(text="\t", font="Helvetica", size=10.0, color="#000000",
                  is_tab=True)
        return Para(runs=[tab, _run(date, font="Helvetica"), tab,
                          _run(body, font="Helvetica")],
                    leading=12, src_lines=1, left_indent=128.9,
                    first_indent=-128.9, tab_stops=stops)

    def test_a_hanging_row_is_its_body_after_the_hang(self):
        # y44 p1: "<tab>Sept 2018 - May 2023<tab>Princeton University, ..."
        # with its date out in the hang (stops 118.7 right, 128.9 left) was
        # predicted at two lines with the date counted into the line; one
        # line in the source and in both renderers.
        date = "Sept 2018 - May 2023"
        words = "Princeton University PhD in Computer Science Princeton NJ"
        p = self._row(date, words, [(118.7, "right"), (128.9, "left")])
        avail = CW - p.left_indent
        from exactdoc.docxout import predict_lines_for
        whole = predict_lines_for(Para(runs=[_run(date + " " + words,
                                                  font="Helvetica")],
                                       leading=12), avail - 60.0, self.m)
        self.assertEqual(para_lines(p, avail - 60.0, self.m), 1)
        self.assertEqual(whole, 2)          # the date counted in: two lines

    def test_the_hang_tab_defaults_to_the_first_tab(self):
        # "1.<tab>text": no stop named, the implicit one at the left indent
        p = self._row("1.", "alpha", [])
        p.runs = p.runs[1:]
        self.assertEqual(_hang_body(p)[0].text, "alpha")
        self.assertIsNone(_hang_body(_para()))           # no hang, no tab

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

    def _capped(self, lines, *pages):
        from exactdoc import pagefit
        was = pagefit.PAGEFIT_MAX_OVER_LINES
        pagefit.PAGEFIT_MAX_OVER_LINES = lines
        try:
            return [self._plan(pg, lay, given) for pg, lay, given in pages]
        finally:
            pagefit.PAGEFIT_MAX_OVER_LINES = was

    def test_the_cap_leaves_a_page_many_lines_over_as_spaced(self):
        # PAGEFIT_MAX_OVER_LINES: y59's first page, 11 body lines over by
        # the model, fitted in the render all the same; paid back to the
        # floors (one 233pt gap cut to 70pt) its placement fell. Six lines
        # over here, the gentle tier holds 76.8pt against the 86pt the page
        # needs.
        lay = _lay()
        far = _page(_fill(lay, spare=-6 * BODY))
        near = _page(_fill(lay, spare=-2 * BODY))
        given = {}
        far_plan, near_plan = self._capped(3, (far, lay, given),
                                           (near, lay, {}))
        self.assertIs(far_plan, given)
        self.assertTrue(near_plan)
        self.assertTrue(self._plan(far, lay))          # 6 lines < 10

    def test_past_the_cap_a_gentle_plan_is_still_paid(self):
        # y21 p6, 10.9 body lines over, whose gaps pay it without going
        # under 60% of any of them, was a real spill: paid, the page fitted
        # (planner sweep 2026-10-10). Four lines over here, the gentle tier
        # (76.8pt) covers the 62pt the page needs.
        lay = _lay()
        els = _fill(lay, spare=-4 * BODY)
        plan, = self._capped(3, (_page(els), lay, {}))
        self.assertTrue(plan)
        for el in els:
            gentle = max(SPILL_GAP_FLOOR_PT,
                         el.space_before * PAGEFIT_GENTLE_GAP_SCALE)
            self.assertGreaterEqual(plan.get(id(el), el.space_before),
                                    gentle - 0.1 - 1e-6)

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


class UnderTheLoop(unittest.TestCase):
    """`plan_page`: open-loop every write plans afresh; under the refine loop
    a page is planned on its first write and later rounds hold each planned
    gap as a ceiling, so a push the loop makes from its render is not taken
    back by the model (y44 p1 paid 16 -> 49 -> 64pt re-planned), and a gap
    the loop reduces further is the loop's (y53 p11)."""

    def _plan(self, pg, lay, memo, plan=None):
        return plan_page(pg, CW, lay, 0.0, BODY,
                         plan if plan is not None else {}, memo=memo)

    def test_open_loop_is_fit_page(self):
        lay = _lay()
        pg = _page(_fill(lay, spare=3.0))
        self.assertEqual(self._plan(pg, lay, None),
                         fit_page(pg, CW, lay, 0.0, BODY, {}))

    def test_a_push_by_the_loop_is_kept(self):
        lay = _lay()
        els = _fill(lay, spare=3.0)
        pg = _page(els)
        memo = {}
        first = self._plan(pg, lay, memo)
        self.assertTrue(first)
        taken = {id(el): el.space_before - first[id(el)]
                 for el in els if id(el) in first}
        # the loop moves the page down 20pt by its first gap
        els[0].space_before += 20.0
        second = self._plan(pg, lay, memo)
        self.assertEqual(second, first)
        self.assertNotIn(id(els[0]), second)
        # re-planned, the model would have taken the push back
        fresh = self._plan(pg, lay, None)
        self.assertGreater(sum(el.space_before - fresh.get(id(el), el.space_before)
                               for el in els),
                           sum(taken.values()) + 15.0)

    def test_the_loop_and_the_plan_never_compound(self):
        lay = _lay()
        els = _fill(lay, spare=3.0)
        pg = _page(els)
        memo = {}
        first = self._plan(pg, lay, memo)
        k = max(i for i, el in enumerate(els) if id(el) in first)
        # the loop, reading a spill, takes half of the last gap
        els[k].space_before *= 0.5
        second = self._plan(pg, lay, memo)
        self.assertEqual(second[id(els[k])],
                         min(els[k].space_before, first[id(els[k])]))
        self.assertGreaterEqual(second[id(els[k])],
                                els[k].space_before - 1e-9)

    def test_a_page_left_alone_first_stays_the_callers(self):
        lay = _lay()
        els = _fill(lay, spare=40.0)
        pg = _page(els)
        memo = {}
        self.assertEqual(self._plan(pg, lay, memo), {})
        els[0].space_before += 35.0          # now inside a body line
        given = {"sentinel": 1.0}
        self.assertIs(self._plan(pg, lay, memo, given), given)

    def test_the_writer_holds_the_plan_on_the_loop_layout(self):
        from exactdoc import pagefit
        was = pagefit.PAGEFIT_ENABLED
        pagefit.PAGEFIT_ENABLED = True
        try:
            lay = _lay()
            first = _page([_para(gap=0.0)], number=1)
            full = _page(_fill(lay, spare=3.0))
            lay.pages = [first, full]
            for pg in lay.pages:
                pg.top_gap_fits = True           # as refine._freeze_seams
            one = _befores(lay)
            self.assertIn("_pagefit_memo", lay.__dict__)
            full.chunks[0].elements[0].space_before += 10.0
            two = _befores(lay)
            # the pushed first gap is written as pushed; nothing else moved
            diff = [b - a for a, b in zip(one, two) if a != b]
            self.assertEqual(diff, [200])
            # open-loop, nothing is held on the layout
            lay2 = _lay()
            lay2.pages = [_page([_para(gap=0.0)], number=1),
                          _page(_fill(lay2, spare=3.0))]
            _befores(lay2)
            self.assertNotIn("_pagefit_memo", lay2.__dict__)
        finally:
            pagefit.PAGEFIT_ENABLED = was


def _befores(lay, profile="standard"):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "o.docx")
        write_docx(lay, path, output_profile=profile)
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8")
    return [int(v) for v in re.findall(r'w:before="(\d+)"', xml)]


class _On(unittest.TestCase):
    """The planner is shipped on (`pagefit.PAGEFIT_ENABLED`, WP34); these
    tests pin it on for themselves, whatever the switch says."""

    def setUp(self):
        from exactdoc import pagefit
        self._was = pagefit.PAGEFIT_ENABLED
        pagefit.PAGEFIT_ENABLED = True

    def tearDown(self):
        from exactdoc import pagefit
        pagefit.PAGEFIT_ENABLED = self._was


class TheSwitch(unittest.TestCase):
    def _lay(self):
        lay = _lay()
        full = _page(_fill(lay, spare=3.0))
        lay.pages = [_page([_para(gap=0.0)], number=1), full]
        return lay, full

    def _xml(self, lay, profile, planner):
        from exactdoc import pagefit
        was = pagefit.PAGEFIT_ENABLED
        pagefit.PAGEFIT_ENABLED = planner
        try:
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "o.docx")
                write_docx(lay, path, output_profile=profile)
                with zipfile.ZipFile(path) as z:
                    return {n: z.read(n) for n in z.namelist()
                            if n.startswith("word/") and n.endswith(".xml")}
        finally:
            pagefit.PAGEFIT_ENABLED = was

    def test_on_for_the_standard_profile(self):
        from exactdoc import pagefit
        self.assertTrue(pagefit.PAGEFIT_ENABLED)
        lay, full = self._lay()
        asked = sum(el.space_before for el in full.chunks[0].elements)
        self.assertLess(sum(_befores(lay)) / 20.0, asked)

    def test_off_the_writer_is_as_before(self):
        lay, full = self._lay()
        asked = [round(el.space_before * 20) for el in full.chunks[0].elements]
        xml = self._xml(lay, "standard", False)["word/document.xml"]
        got = [int(v) for v in re.findall(r'w:before="(\d+)"', xml.decode())]
        for v in asked:
            self.assertIn(v, got)

    def test_the_gdocs_profile_never_asks_it(self):
        # gdocs pages are planned by `_gdocs_page_plan` on Docs' own metrics;
        # the switch must not move one byte of a gdocs DOCX.
        lay, _full = self._lay()
        self.assertEqual(self._xml(lay, "gdocs", True),
                         self._xml(lay, "gdocs", False))
        self.assertNotEqual(self._xml(lay, "standard", True),
                            self._xml(lay, "standard", False))


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
