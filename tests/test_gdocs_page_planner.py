"""Google Docs page count: the joint recalibration and the page planner (WP19).

The gdocs profile ships with no refine loop and every source page ends in a
page break, so a page Docs sets a point longer than the writer planned costs a
whole page. Measured on Google's own exports of the 2c1c68f sweep (68
documents, diagnosis in the WP19 report), what Docs adds to the writer's model
is partly systematic -- corrected here at source -- and partly a paragraph
wrapping a line longer than predicted, which the planner budgets for:

1. Arial and Times New Roman at their true natural factor 1.150, and Roboto
   Mono (y17's ABNF appendix, every line 15.3% tall) with the families Docs
   embeds in its exports.
2. A line multiple is computed against the EMITTED half-point size.
3. A paragraph keeps its median pitch: infer's gaps were computed against it.
4. Lines mixing families or sizes (Times with inline Courier New, capitals
   over small capitals) are set taller by Docs; the paragraph's multiple is
   chosen for its total.
5. Rules and inline pictures are compensated by what Docs adds to them.
6. Each page is modelled as Docs sets it and keeps a body line plus a safety
   free, paid from its own gaps from the foot up, gently first, never past
   the refine floors.

All of that is written ONLY on a page at risk in Docs. A page that fits as the
profile shipped it keeps that form byte for byte: its errors cancel, and the
first live probe measured placement on such pages falling when one of a
cancelling pair was corrected (c1 within-2pt 0.154 -> 0.064, x05 0.785 ->
0.066) while the pages at risk came back (y18 258 -> 145, y17 217 -> 195).
"""
import os
import re
import tempfile
import unittest
import zipfile

from exactdoc import docxout as D
from exactdoc.docxout import (GDOCS_GENTLE_GAP_SCALE, GDOCS_PAGE_SAFETY_PT,
                              GDOCS_PICTURE_ABOVE_PT, GDOCS_PICTURE_BELOW_PT,
                              GDOCS_RULE_EXCESS_PT, GDOCS_SINGLE_LINE_SHAVE_PT,
                              SPILL_GAP_FLOOR_PT, SPILL_MIN_GAP_SCALE,
                              _body_capacity, _docs_lead, _gdocs_mixed_lines,
                              _gdocs_page_model, _gdocs_page_plan,
                              _natural_factor, write_docx)
from exactdoc.layout import (Chunk, DocLayout, ImageEl, PageLayout, Para,
                             RuleEl, Run)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
LEAD = 12.0
BODY = 12.0


def _run(text="body text", font="Georgia", size=10.0, **kw):
    return Run(text=text, font=font, size=size, color="#000000", **kw)


def _para(gap=6.0, lines=2, lead=LEAD, font="Georgia", text="alpha beta gamma"):
    # Georgia has no width table: the planner takes the source line count,
    # so the arithmetic below is exact. Two-line paragraphs keep the single-
    # line lever out of the sums.
    return Para(runs=[_run(text, font=font)], leading=lead, space_before=gap,
                src_lines=lines)


def _lay(**kw):
    d = dict(page_w=612.0, page_h=792.0, margin_l=72.0, margin_r=72.0,
             margin_t=72.0, margin_b=72.0)
    d.update(kw)
    return DocLayout(**d)


def _page(els, number=2):
    return PageLayout(number=number, chunks=[Chunk(n_cols=1, elements=els)])


def _fill(lay, slack, gap=8.0):
    """Two-line paragraphs `gap` apart whose stack ends `slack` inside the box
    (negative: past it); the last gap takes up the remainder."""
    pitch = gap + 2 * LEAD
    target = _body_capacity(lay) - slack
    n = int(target // pitch)
    paras = [_para(gap=gap) for _ in range(n)]
    paras[-1].space_before = round(gap + target - n * pitch, 2)
    return paras


def _used(pg, lay, plan, drops=False):
    return _gdocs_page_model(pg, 468.0, lay, 0.0, drops, plan)[0]


class Calibration(unittest.TestCase):
    def test_arial_and_times_at_their_true_factor(self):
        # Docs' pitch equals the font's hhea line (1.150) and the 2c1c68f
        # exports set every Times/Arial line 0.5% taller than written at 1.144
        self.assertEqual(_natural_factor("Arial"), 1.150)
        self.assertEqual(_natural_factor("Times New Roman"), 1.150)

    def test_families_read_from_docs_embedded_fonts(self):
        for fam, f in (("Roboto Mono", 1.319), ("Open Sans", 1.362),
                       ("Source Code Pro", 1.257), ("Figtree", 1.200),
                       ("Tahoma", 1.207), ("Ubuntu", 1.149)):
            self.assertAlmostEqual(_natural_factor(fam), f, places=3, msg=fam)
        # each line metric sums to its factor
        for fam, (a, d, g) in D.GDOCS_LINE_METRICS.items():
            self.assertAlmostEqual(a + d + g, _natural_factor(fam), delta=0.002,
                                   msg=fam)

    def _line(self, para, at_risk=False):
        lay = _lay()
        els = [para]
        if at_risk:
            # a full page whose gaps are already at their floor: inside its
            # box, short of its budget, and nothing the gaps alone can pay
            room = _body_capacity(lay) - 3.0 - para.src_lines * para.leading
            k = int(room // (2 * LEAD))
            fill = [_para(gap=0.0, lead=room / (2 * k)) for _ in range(k)]
            els = fill + [para]
        lay.pages = [PageLayout(1, [Chunk(elements=els)])]
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "c.docx")
            write_docx(lay, path, output_profile="gdocs")
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8")
        return int(re.findall(r'w:line="(\d+)" w:lineRule="auto"', xml)[-1])

    def test_the_multiple_is_taken_against_the_emitted_size(self):
        # a 10.91pt LaTeX body is written at 11.0 (half-points): y26's lines
        # measured 13.33pt in Docs against 13.15 written at the 10.91 multiple
        p = Para(runs=[_run("alpha beta gamma delta " * 14, font="Times-Roman",
                            size=10.91)], leading=13.15)
        p.src_lines = D.predict_lines_for(p, 468.0, D._text_metrics("gdocs"))
        self.assertGreaterEqual(p.src_lines, 2)
        self.assertEqual(self._line(p, at_risk=True),
                         round(240 * 13.15 / (11.0 * 1.150)))
        # on a page that fits, the shipped form: 1.144 over the unquantised size
        self.assertEqual(self._line(p), round(240 * 13.15 / (10.91 * 1.144)))

    def test_a_jittered_paragraph_keeps_its_median(self):
        # Word's grid steps 13.68 / 13.92 and the gap below was computed
        # against the 13.92 median: the paragraph plus its gap advance as the
        # source did, and the mean would lift everything after it
        p = _para(lines=5, lead=13.92)
        p._pitch_max, p._pitch_n = 13.92, 5
        self.assertEqual(_docs_lead(p, 12.0), 13.92)

    def test_the_single_line_lever_stands(self):
        p = _para(lines=1, lead=11.6)
        self.assertAlmostEqual(_docs_lead(p, 10.0), 11.6 - GDOCS_SINGLE_LINE_SHAVE_PT)

    def test_a_line_mixing_courier_into_times_is_set_taller(self):
        # four lines; one Courier New run, a quarter of the way in, on line 2
        runs = [_run("a" * 30, font="Times-Roman", size=11.0),
                _run("code", font="Courier", size=11.0, mono=True),
                _run("b" * 86, font="Times-Roman", size=11.0)]
        p = Para(runs=runs, leading=13.15, src_lines=4)
        f = _gdocs_mixed_lines(p, runs, 11.0, "Times New Roman", 4)
        mixed = 0.8911 + 0.3003 + 0.0425           # Times ascent+gap, Courier descent
        self.assertAlmostEqual(f, (3 * 1.150 + (1.150 + mixed - 1.1499)) / 4,
                               places=4)

    def test_a_larger_run_of_the_same_family_raises_its_line(self):
        # y10's contents lines: 8pt small capitals under 10pt initials set at
        # 13.94pt in Docs where 11.17 was asked -- the multiple x 10pt x 1.150
        runs = [_run("G", font="Times-Roman", size=10.0),
                _run("LOSSARY OF TERMS", font="Times-Roman", size=8.0)]
        p = Para(runs=runs, leading=11.55, src_lines=1)
        f = _gdocs_mixed_lines(p, runs, 8.0, "Times New Roman", 1)
        self.assertAlmostEqual(f, 1.150 * 10.0 / 8.0, places=3)
        # a smaller run does not
        runs[0] = _run("x", font="Times-Roman", size=6.0)
        self.assertEqual(_gdocs_mixed_lines(p, runs, 8.0, "Times New Roman", 1), 0.0)

    def test_a_source_that_stepped_its_own_mixed_lines_is_corrected_too(self):
        # Word sets the Courier line taller itself, and infer anchored the next
        # paragraph's gap on the moved baseline: the source's extra is in the
        # gap, so Docs setting the line taller again would count it twice
        runs = [_run("a" * 30, font="Times-Roman", size=11.0),
                _run("code", font="Courier", size=11.0, mono=True),
                _run("b" * 86, font="Times-Roman", size=11.0)]
        p = Para(runs=runs, leading=13.15, src_lines=4)
        self.assertGreater(_gdocs_mixed_lines(p, runs, 11.0, "Times New Roman", 4), 1.15)

    def test_arial_in_times_takes_the_largest_ascent_plus_gap(self):
        # the calibration page: an Arial run in an 11pt Times line set 12.70pt
        runs = [_run("times words " * 3, font="Times-Roman", size=11.0),
                _run("arial", font="Helvetica", size=11.0)]
        p = Para(runs=runs, leading=12.65, src_lines=1)
        f = _gdocs_mixed_lines(p, runs, 11.0, "Times New Roman", 1)
        self.assertAlmostEqual(11.0 * f, 12.70, delta=0.02)

    def test_one_family_needs_no_correction(self):
        runs = [_run("plain " * 20, font="Times-Roman", size=11.0)]
        p = Para(runs=runs, leading=13.15, src_lines=3)
        self.assertEqual(_gdocs_mixed_lines(p, runs, 11.0, "Times New Roman", 3), 0.0)

    def test_soft_broken_lines_are_counted_exactly(self):
        runs = [_run("one\ntwo\n", font="Times-Roman", size=11.0),
                _run("code", font="Courier", size=11.0, mono=True),
                _run("\nfour", font="Times-Roman", size=11.0)]
        p = Para(runs=runs, leading=13.15, src_lines=4, line_breaks=True)
        f = _gdocs_mixed_lines(p, runs, 11.0, "Times New Roman", 4)
        self.assertAlmostEqual(f, (3 * 1.150 + (1.150 + 0.0840)) / 4, places=3)


class Planner(unittest.TestCase):
    def test_a_page_with_room_is_left_alone(self):
        lay = _lay()
        pg = _page(_fill(lay, slack=BODY + GDOCS_PAGE_SAFETY_PT + 5.0))
        self.assertEqual(_gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False), {})

    def test_a_full_page_keeps_a_body_line_and_the_safety_free(self):
        lay = _lay()
        pg = _page(_fill(lay, slack=3.0))
        plan = _gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False)
        self.assertTrue(plan)
        free = _body_capacity(lay) - _used(pg, lay, plan)
        # gaps are written in tenths, rounded down so the page never pays less
        self.assertGreaterEqual(free, BODY + GDOCS_PAGE_SAFETY_PT - 0.01)
        self.assertLess(free, BODY + GDOCS_PAGE_SAFETY_PT + 0.1 * len(plan) + 0.01)

    def test_the_reclaim_is_gentle_first_and_from_the_foot_up(self):
        lay = _lay()
        els = _fill(lay, slack=3.0)
        pg = _page(els)
        plan = _gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False)
        for el in els:
            if id(el) in plan:
                self.assertGreaterEqual(plan[id(el)] + 0.1,
                                        el.space_before * GDOCS_GENTLE_GAP_SCALE)
        # the lowest gaps pay; the top of the page keeps its source spacing
        touched = [i for i, el in enumerate(els) if id(el) in plan]
        self.assertTrue(touched)
        self.assertEqual(touched, list(range(touched[0], len(els))))
        self.assertGreater(touched[0], len(els) // 2)

    def test_an_overflow_is_paid_down_to_the_refine_floors(self):
        lay = _lay()
        els = _fill(lay, slack=-40.0)           # three lines over
        pg = _page(els)
        plan = _gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False)
        self.assertLessEqual(_used(pg, lay, plan), _body_capacity(lay) + 0.6)
        for el in els:
            floor = max(SPILL_GAP_FLOOR_PT, el.space_before * SPILL_MIN_GAP_SCALE)
            self.assertGreaterEqual(plan.get(id(el), el.space_before) + 0.1, floor)

    def test_a_page_its_gaps_cannot_save_is_left_as_spaced(self):
        lay = _lay()
        els = [_para(gap=3.0) for _ in range(30)]     # 163pt over, 30pt of gaps
        pg = _page(els)
        self.assertGreater(_used(pg, lay, {}) - _body_capacity(lay), 150.0)
        self.assertEqual(_gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False), {})

    def test_the_gap_docs_drops_after_the_seam_is_room_not_currency(self):
        lay = _lay()
        els = _fill(lay, slack=3.0)
        els[0].space_before += 20.0              # 17pt over -- unless dropped
        pg = _page(els)

        def paid(plan):
            return sum(el.space_before - plan[id(el)] for el in els if id(el) in plan)
        kept = _gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False)
        self.assertGreater(paid(kept), 17.0 + BODY)
        # dropped, the 28pt first gap leaves 11pt free: 3pt more to find
        plan = _gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, True)
        self.assertNotIn(id(els[0]), plan)
        self.assertAlmostEqual(paid(plan), BODY + GDOCS_PAGE_SAFETY_PT - 11.0,
                               delta=0.1 * len(plan) + 0.05)

    def test_a_rule_pays_its_docs_excess_from_its_own_gap(self):
        lay = _lay()
        rule = RuleEl(width_pct=100.0, thickness=0.75, color="#cccccc",
                      space_before=10.0)
        pg = _page([_para(), rule, _para()])
        plan = _gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False)
        self.assertAlmostEqual(plan[id(rule)], 10.0 - GDOCS_RULE_EXCESS_PT)

    def test_an_inline_picture_pays_above_and_below(self):
        lay = _lay()
        im = ImageEl(data=b"", ext="png", width=50.0, height=40.0,
                     space_before=6.0)
        after = _para(gap=5.0)
        pg = _page([_para(), im, after])
        plan = _gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False)
        self.assertAlmostEqual(plan[id(im)], 6.0 - GDOCS_PICTURE_ABOVE_PT)
        self.assertAlmostEqual(plan[id(after)], round(5.0 - GDOCS_PICTURE_BELOW_PT, 1))

    def test_a_page_filling_picture_takes_no_flow(self):
        lay = _lay()
        im = ImageEl(data=b"", ext="png", width=612.0, height=792.0,
                     space_before=6.0)
        pg = _page([im, _para()])
        self.assertEqual(_gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False), {})

    def test_columns_and_continuations_are_not_planned(self):
        lay = _lay()
        pg = PageLayout(number=2, chunks=[Chunk(n_cols=2, elements=_fill(lay, -5.0))])
        self.assertEqual(_gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False), {})
        pg = _page(_fill(lay, slack=-5.0))
        pg.continuation_only = True
        self.assertEqual(_gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False), {})


class VerticalRules(unittest.TestCase):
    def _fig(self, w, h, x0=64.0, y0=68.5):
        from exactdoc.layout import FigureEl
        return FigureEl(page_no=1, clip=(x0, y0, x0 + w, y0 + h), width=w,
                        height=h, space_before=0.0)

    def test_a_box_side_leaves_the_flow_for_the_page(self):
        # y17's ABNF appendix: 4.75 x 629pt sides of a code box
        side = self._fig(4.75, 629.08)
        body = _para()
        pg = _page([side, self._fig(4.75, 629.08, x0=526.6), body])
        got = D._gdocs_vertical_rules(pg, BODY)
        self.assertEqual(len(got), 2)
        fl = got[id(side)]
        self.assertTrue(fl.behind)
        self.assertEqual(fl.bbox, side.clip)
        lay = _lay()
        used = _gdocs_page_model(pg, 468.0, lay, 0.0, False, {}, skip=got)[0]
        self.assertAlmostEqual(used, body.space_before + 2 * LEAD)

    def test_an_ordinary_figure_stays(self):
        pg = _page([self._fig(200.0, 150.0), self._fig(6.0, 20.0), _para()])
        self.assertEqual(D._gdocs_vertical_rules(pg, BODY), {})

    def test_written_anchored_not_inline(self):
        # tall enough that the page, written inline, cannot fit: at risk
        side = self._fig(4.75, 640.0)
        lay = _lay()
        lay.pages = [_page([_para(gap=0.0)], number=1),
                     _page([side, _para(), _para()], number=2)]
        for profile, anchors, inlines in (("gdocs", 1, 0), ("standard", 0, 1)):
            ctx = D.WriteCtx(output_profile=profile,
                             line_mode=D.line_mode_for(profile),
                             render_clip=lambda *a: _png())
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "v.docx")
                write_docx(lay, path, ctx=ctx)
                xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
            self.assertEqual(xml.count("<wp:anchor"), anchors, profile)
            self.assertEqual(xml.count("<wp:inline"), inlines, profile)


def _png():
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (4, 40), (0, 0, 0)).save(b, "PNG")
    return b.getvalue()


class OnlyPagesAtRisk(unittest.TestCase):
    def test_a_page_with_room_is_not_at_risk(self):
        lay = _lay()
        pg = _page(_fill(lay, slack=60.0))
        self.assertFalse(D._gdocs_page_at_risk(pg, 468.0, lay, 0.0, BODY, False))
        pg = _page(_fill(lay, slack=5.0))
        self.assertTrue(D._gdocs_page_at_risk(pg, 468.0, lay, 0.0, BODY, False))

    def test_a_page_before_a_blank_page_is_left_as_shipped(self):
        # y30's cover overflows onto its blank verso by design: the writer
        # holds no page for the blank, and fitting the cover would delete it
        lay = _lay()
        rule = RuleEl(width_pct=100.0, thickness=0.75, color="#cccccc",
                      space_before=10.0)
        full = _fill(lay, slack=3.0)
        lay.pages = [_page([_para(gap=0.0)], number=1),
                     _page(full + [rule], number=2),
                     PageLayout(number=3, chunks=[Chunk(elements=[])]),
                     _page([_para()], number=4)]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "o.docx")
            write_docx(lay, path, output_profile="gdocs")
            xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
        for el in full:
            self.assertIn('w:before="%d"' % round(el.space_before * 20), xml)

    def test_the_shipped_form_is_modelled_at_its_true_height(self):
        # Times at 1.144: every line 0.5% taller in Docs than asked
        lay = _lay()
        p = Para(runs=[_run("x" * 40, font="Times-Roman", size=12.0)],
                 leading=14.0, src_lines=10)
        pg = _page([p])
        legacy = _gdocs_page_model(pg, 468.0, lay, 0.0, False, {}, legacy=True)[0]
        calibrated = _gdocs_page_model(pg, 468.0, lay, 0.0, False, {})[0]
        self.assertAlmostEqual(calibrated % 14.0, 0.0, places=6)   # n x 14.0
        self.assertAlmostEqual(legacy / calibrated, 1.150 / 1.144, places=6)

    def test_a_fitting_page_is_written_as_shipped(self):
        lay = _lay()
        rule = RuleEl(width_pct=100.0, thickness=0.75, color="#cccccc",
                      space_before=10.0)
        lay.pages = [_page([_para(gap=0.0)], number=1),
                     _page([_para(), rule, _para()], number=2)]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "o.docx")
            write_docx(lay, path, output_profile="gdocs")
            xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
        self.assertIn('w:before="200"', xml)         # the rule's own 10pt

    def test_the_holder_keeps_a_page_top_gap_when_switched_on(self):
        lay = _lay()
        top = _para(gap=18.0)
        lay.pages = [_page([_para(gap=0.0)], number=1), _page([top, _para()], number=2)]

        def written():
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "o.docx")
                write_docx(lay, path, output_profile="gdocs")
                return zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
        self.assertFalse(D.GDOCS_PAGE_TOP_HOLDER)       # off until measured
        plain = written()
        D.GDOCS_PAGE_TOP_HOLDER = True
        try:
            held = written()
        finally:
            D.GDOCS_PAGE_TOP_HOLDER = False
        self.assertEqual(plain.count("<w:pageBreakBefore/>"), 1)
        self.assertEqual(held.count("<w:pageBreakBefore/>"), 1)
        # the gap now follows an empty 1pt holder that took the break
        self.assertIn('w:before="356"', held)            # 18pt less 0.22
        self.assertEqual(held.count('<w:sz w:val="2"/>'), 2)


class TheWriter(unittest.TestCase):
    @staticmethod
    def _befores(lay, profile):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "o.docx")
            write_docx(lay, path, output_profile=profile)
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8")
        return [int(v) for v in re.findall(r'w:before="(\d+)"', xml)]

    def _doc(self):
        lay = _lay()
        first = _page([_para(gap=0.0)], number=1)
        full = _page(_fill(lay, slack=3.0))
        lay.pages = [first, full]
        return lay, full

    def test_gdocs_pays_and_the_standard_profile_does_not(self):
        lay, full = self._doc()
        asked = [round(el.space_before * 20) for el in full.chunks[0].elements]
        std = self._befores(lay, "standard")
        gd = self._befores(lay, "gdocs")
        for v in asked[1:]:
            self.assertIn(v, std)
        self.assertLess(sum(gd), sum(std))

    def test_the_layout_is_not_modified(self):
        lay, full = self._doc()
        asked = [el.space_before for el in full.chunks[0].elements]
        self._befores(lay, "gdocs")
        self.assertEqual([el.space_before for el in full.chunks[0].elements], asked)


def _jittered_pdf(path):
    """A Times paragraph set on Word's grid: 12pt type, nine lines whose
    pitches alternate 13.92 / 13.68 (NIST SP 800-63B's body): median 13.92,
    mean 13.80."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=(612, 792))
    words = ("Verifiers shall require subscriber chosen memorized secrets to be "
             "at least eight characters in length and should permit them to be "
             "at least sixty four characters long").split()
    y = 700.0
    for k in range(9):
        c.setFont("Times-Roman", 12)
        c.drawString(72, y, " ".join(words[k:k + 11]))
        y -= 13.92 if k % 2 == 0 else 13.68
    c.save()


class TheMedianPitchEndToEnd(unittest.TestCase):
    def test_both_profiles_keep_the_median(self):
        from exactdoc.convert import convert
        from exactdoc.options import PDFIUM_GDOCS_CANDIDATE, RAW
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "j.pdf")
            _jittered_pdf(src)
            gd = os.path.join(d, "gd.docx")
            convert(src, gd, options=PDFIUM_GDOCS_CANDIDATE, max_pages=0)
            xml = zipfile.ZipFile(gd).read("word/document.xml").decode("utf-8")
            lines = [int(v) for v in re.findall(r'w:line="(\d+)" w:lineRule="auto"', xml)]
            # a page that fits keeps the shipped multiple of the 13.92 median
            # (1.144: 243), not the 13.80 mean's
            self.assertIn(243, lines)
            self.assertNotIn(241, lines)
            # the standard profile writes the same median, exactly
            std = os.path.join(d, "std.docx")
            convert(src, std, options=RAW, max_pages=0)
            xml = zipfile.ZipFile(std).read("word/document.xml").decode("utf-8")
            self.assertRegex(xml, r'w:lineRule="exact" w:line="278"')


if __name__ == "__main__":
    unittest.main()
