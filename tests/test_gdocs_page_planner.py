"""Google Docs page count and placement: the line model and the page planner
(WP19, WP19b).

The gdocs profile ships with no refine loop and every source page ends in a
page break, so a page Docs sets a point longer than the writer planned costs a
whole page. Measured on Google's own exports of the 2c1c68f sweep (68
documents, diagnosis in the WP19 report), what Docs adds to the writer's model
is partly systematic -- corrected at source -- and partly a paragraph
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

WP19b, on Google's exports of the WP19 probe-1 documents: every gap is moved
for where Docs puts a paragraph's first baseline (all the leading's extra
below it, not above as in Word terms), a quote's or box's own gap and edges
are written, and all of it applies on every page -- the shipped form's
errors, which cancelled on pages that fit, are each corrected instead.
"""
import os
import re
import tempfile
import unittest
import zipfile

from exactdoc import docxout as D
from exactdoc.docxout import (GDOCS_GENTLE_GAP_SCALE, GDOCS_PAGE_SAFETY_PT,
                              GDOCS_PICTURE_ABOVE_PT, GDOCS_PICTURE_BELOW_PT,
                              GDOCS_RULE_EXCESS_PT, SPILL_GAP_FLOOR_PT,
                              SPILL_MIN_GAP_SCALE, _body_capacity, _docs_lead,
                              _gdocs_mixed_lines, _gdocs_page_model,
                              _gdocs_page_plan, _natural_factor, write_docx)
from exactdoc.layout import (Cell, Chunk, DocLayout, ImageEl, PageLayout, Para,
                             RuleEl, Run, TableEl)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
LEAD = 12.0
BODY = 12.0


def _run(text="body text", font="Georgia", size=10.0, **kw):
    return Run(text=text, font=font, size=size, color="#000000", **kw)


def _para(gap=6.0, lines=2, lead=LEAD, font="Georgia", text="alpha beta gamma"):
    # Georgia has no width table: the planner takes the source line count,
    # so the arithmetic below is exact.
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


def _xml(lay, profile="gdocs"):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "o.docx")
        write_docx(lay, path, output_profile=profile)
        with zipfile.ZipFile(path) as z:
            return z.read("word/document.xml").decode("utf-8")


def _befores(xml):
    return [int(v) / 20.0 for v in re.findall(r'w:before="(\d+)"', xml)]


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

    def _line(self, para, full=False):
        lay = _lay()
        els = [para]
        if full:
            # a full page whose gaps are already at their floor
            room = _body_capacity(lay) - 3.0 - para.src_lines * para.leading
            k = int(room // (2 * LEAD))
            fill = [_para(gap=0.0, lead=room / (2 * k)) for _ in range(k)]
            els = fill + [para]
        lay.pages = [PageLayout(1, [Chunk(elements=els)])]
        xml = _xml(lay)
        return int(re.findall(r'w:line="(\d+)" w:lineRule="auto"', xml)[-1])

    def test_the_multiple_is_taken_against_the_emitted_size(self):
        # a 10.91pt LaTeX body is written at 11.0 (half-points): y26's lines
        # measured 13.33pt in Docs against 13.15 written at the 10.91 multiple
        p = Para(runs=[_run("alpha beta gamma delta " * 14, font="Times-Roman",
                            size=10.91)], leading=13.15)
        p.src_lines = D.predict_lines_for(p, 468.0, D._text_metrics("gdocs"))
        self.assertGreaterEqual(p.src_lines, 2)
        want = round(240 * 13.15 / (11.0 * 1.150))
        # on every page, full or not: the shipped form's 1.144 is gone
        self.assertEqual(self._line(p, full=True), want)
        self.assertEqual(self._line(p), want)

    def test_a_jittered_paragraph_keeps_its_median(self):
        # Word's grid steps 13.68 / 13.92 and the gap below was computed
        # against the 13.92 median: the paragraph plus its gap advance as the
        # source did, and the mean would lift everything after it
        p = _para(lines=5, lead=13.92)
        p._pitch_max, p._pitch_n = 13.92, 5
        self.assertEqual(_docs_lead(p, 12.0), 13.92)

    def test_a_single_line_keeps_its_leading(self):
        # hand-campaign lever [E] shaved 0.38pt off a one-line paragraph; on
        # the probe-1 exports such paragraphs then advanced 0.39pt short of the
        # source each (248 boundaries): its leading is what infer anchored on
        p = _para(lines=1, lead=11.6)
        self.assertEqual(_docs_lead(p, 10.0), 11.6)

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


def _times(text, size=9.33, lead=13.33, lines=2, gap=0.0):
    return Para(runs=[_run(text, font="Times-Roman", size=size)], leading=lead,
                space_before=gap, src_lines=lines)


class TheLinePlacement(unittest.TestCase):
    """Word terms put a line's extra leading above its baseline; Docs puts it
    below. Measured on the probe-1 exports (1,268 boundaries): heading -> body
    -2.50pt median, body -> heading +2.09, residual after the model 0.00."""

    @staticmethod
    def _moves(els, first_fixed=False, top=0.0):
        lay = _lay()
        _pre, flow = D._gdocs_flow(_page(els), 468.0, lay, 0.0)
        gap_of = {id(el): el.space_before for el, _n, _h, _b in flow}
        return D._gdocs_baseline_gaps(flow, gap_of, lay, first_fixed, top)

    def test_the_first_baseline_offsets(self):
        # c1_whitepaper's body: Times 9.33pt (written 9.5) at a 13.33pt pitch
        body = _times("retrieval quality degrades " * 6)
        lead, desc, line, first = D._gdocs_para_box(body)
        self.assertEqual(lead, 13.33)
        self.assertAlmostEqual(desc, D.GDOCS_WRITER_DESCENT_EM * 9.33)
        self.assertAlmostEqual(first, (0.8911 + 0.0425) * 9.5, places=3)
        self.assertAlmostEqual(line, 13.33, delta=0.03)       # quantised multiple
        # a multiple under 1 scales the offset with it (a tight list item)
        item = _times("tail queries", lead=10.0, lines=1)
        lead, desc, line, first = D._gdocs_para_box(item)
        self.assertAlmostEqual(first, (0.8911 + 0.0425) * 9.5 * line / (9.5 * 1.15),
                               places=2)

    def test_a_heading_then_body_text(self):
        # c1's "1. Executive summary" (Arial 12.44 at 14.43) and the body under
        # it: Docs set the body 2.57pt high there
        head = Para(runs=[_run("1. Executive summary", font="Helvetica-Bold",
                               size=12.44, bold=True)], leading=14.43,
                    space_before=17.5, src_lines=1, heading=1)
        body = _times("retrieval quality degrades " * 6, gap=5.4)
        moves = self._moves([head, body])
        self.assertAlmostEqual(moves[id(body)] - 5.4, 2.4, delta=0.3)

    def test_a_uniform_page_moves_only_its_first_gap(self):
        # the corrections telescope: equal leadings leave every later gap as is
        els = [_times("alpha beta " * 9, gap=6.0) for _ in range(5)]
        moves = self._moves(els)
        first = D._gdocs_para_box(els[0])
        self.assertAlmostEqual(moves[id(els[0])] - 6.0,
                               (first[0] - first[1]) - first[3], delta=0.06)
        for el in els[1:]:
            self.assertAlmostEqual(moves[id(el)], 6.0, delta=0.11)

    def test_a_gap_docs_drops_is_not_moved(self):
        els = [_times("alpha beta " * 9, gap=6.0), _times("gamma " * 9, gap=6.0)]
        moves = self._moves(els, first_fixed=True)
        self.assertEqual(moves[id(els[0])], 6.0)

    def test_the_tallest_run_on_the_first_line_sets_its_baseline(self):
        # y02's chapter opening: a 51pt initial in a 10.7pt paragraph
        p = Para(runs=[_run("T", font="Times-Roman", size=51.0),
                       _run("he tailoring criteria " * 8, font="Times-Roman",
                            size=10.66)], leading=59.16, src_lines=1)
        first = D._gdocs_para_box(p)[3]
        self.assertGreater(first, 40.0)
        # and not a run further down the paragraph
        q = Para(runs=[_run("plain words " * 30, font="Times-Roman", size=10.0),
                       _run("BIG", font="Times-Roman", size=30.0)],
                 leading=12.0, src_lines=4)
        self.assertLess(D._gdocs_para_box(q)[3], 12.0)

    def test_a_clamped_page_top_is_given_back_below(self):
        # x08's second page: infer clamped the first gap at zero, so the model
        # starts that paragraph 3.69pt lower than the source drew it
        lay = _lay(margin_t=66.0)
        p = _times("mitigation is available " * 6, size=10.99, lead=15.75, lines=3)
        p._b1 = 75.75
        _pre, flow = D._gdocs_flow(_page([p, _times("next " * 9, gap=9.0)]), 468.0,
                                   lay, 0.0)
        self.assertAlmostEqual(D._gdocs_top_clamp(flow, lay, 0.0),
                               66.0 + 15.75 - D.GDOCS_WRITER_DESCENT_EM * 10.99 - 75.75,
                               places=6)

    def test_lines_are_predicted_a_soft_break_at_a_time(self):
        # y26's code listings: the ladder read a break as a space
        metrics = D._text_metrics("gdocs")
        code = Para(runs=[_run("_completion_loader()\n{\n    . \"/etc/bash_completion.d/$1.sh\""
                               " >/dev/null 2>&1 && return 124\n}", font="Courier",
                               size=10.91, mono=True)], leading=13.15, src_lines=4,
                    line_breaks=True)
        self.assertGreaterEqual(D._gdocs_lines(code, 400.0, metrics), 4)
        # a line's own indentation is width Docs sets
        ind = Para(runs=[_run(" " * 15 + "complete [-abcdefgjksuv] [-o comp-option] "
                              "[-DEI] [-A action]", font="Courier", size=10.91,
                              mono=True)], leading=13.15, src_lines=1, line_breaks=True)
        flat = Para(runs=[_run("complete [-abcdefgjksuv] [-o comp-option] [-DEI] "
                               "[-A action]", font="Courier", size=10.91, mono=True)],
                    leading=13.15, src_lines=1, line_breaks=True)
        self.assertEqual(D._gdocs_lines(flat, 450.0, metrics), 1)
        self.assertEqual(D._gdocs_lines(ind, 450.0, metrics), 2)

    def test_a_shorter_rewrap_keeps_the_lines_below_in_place(self):
        # x09: four source lines Docs sets in three -- the line goes to the
        # next gap, but only where the page fits with the source's four
        lay = _lay()
        p = _times("depot replacement " * 4, size=10.99, lead=15.75, lines=4)
        nxt = _times("next paragraph " * 3, gap=10.0, lines=1)
        pg = _page([p, nxt])
        _pre, flow = D._gdocs_flow(pg, 468.0, lay, 0.0)
        self.assertEqual(flow[0][1], 1)                  # predicted: one line
        p.src_lines = 2                                  # the source had two
        plan = D._gdocs_baseline_plan(pg, 468.0, lay, 0.0, {}, False,
                                      body_line=BODY)
        plain = D._gdocs_baseline_gaps(flow, {id(p): 0.0, id(nxt): 10.0}, lay, False)
        self.assertAlmostEqual(plan[id(nxt)] - plain[id(nxt)], 15.75, delta=0.15)
        # a page that would not fit with the source's lines keeps the plain move
        full = _fill(lay, slack=4.0)
        pg = _page(full + [p, nxt])
        plan = D._gdocs_baseline_plan(pg, 468.0, lay, 0.0, {}, False, body_line=BODY)
        self.assertLess(plan.get(id(nxt), 10.0), 10.0 + 15.75 - 1.0)


class Blocks(unittest.TestCase):
    """Quotes and callout boxes in the gdocs paragraph form."""

    @staticmethod
    def _box(gap=12.0, bw=0.75, role="box"):
        p = _times("Key finding. Precision in the bottom decile fell 41%.",
                   lead=10.82, lines=1)
        p.bbox = (75.0, 415.5, 400.0, 425.9)
        p._b1 = 423.84
        cell = Cell(paras=[p], shading="#EEF7F1",
                    borders={} if role == "box" else {"left": (1.5, "#BBBBBB")},
                    pad=(7.7, 13.0, 9.3, 4.0))
        return TableEl(rows=[[cell]], col_widths=[490.0], role=role,
                       space_before=gap, bbox=(61.5, 407.85, 551.5, 435.18))

    def _written(self, block, after=None):
        lay = _lay()
        lay.pages = [_page([_para(gap=0.0), block] + ([after] if after else []),
                           number=1)]
        return _xml(lay)

    def test_a_box_keeps_its_own_gap(self):
        # c1's callouts sat 9.9 and 9.4pt high in Docs: their 12.0 / 11.2pt
        # gaps were not written
        xml = self._written(self._box(gap=12.0))
        p = re.search(r"<w:p>(?:(?!</w:p>).)*?Key finding(?:(?!</w:p>).)*?</w:p>", xml, re.S).group(0)
        before = int(re.search(r'w:before="(\d+)"', p).group(1)) / 20.0
        self.assertGreater(before, 9.0)

    def test_a_box_border_is_drawn_outside_its_padding(self):
        # Docs: first baseline = border width + padding + the line's ascent
        # below the box top (y02's eight boxes within 0.3pt)
        t = self._box()
        box = D._gdocs_para_box(t.rows[0][0].paras[0])
        top, bottom = D._gdocs_box_spaces(t, 0.75, 0.75, 7.7, 9.3)
        self.assertAlmostEqual(top, (423.84 - 407.85) - 0.75 - box[3], places=6)
        last = D._gdocs_last_baseline(t.rows[0][0].paras[0])
        self.assertAlmostEqual(bottom, (435.18 - last) - (box[2] - box[3]) - 0.75,
                               places=6)
        # a 3pt border (01_whitepaper_market) takes three points of padding
        top3, bottom3 = D._gdocs_box_spaces(t, 3.0, 3.0, 7.7, 9.3)
        self.assertAlmostEqual(top - top3, 2.25, places=6)
        self.assertAlmostEqual(bottom - bottom3, 2.25, places=6)

    def test_without_infer_baselines_the_source_spaces_stand(self):
        t = self._box()
        del t.rows[0][0].paras[0]._b1
        self.assertEqual(D._gdocs_box_spaces(t, 0.75, 0.75, 7.7, 9.3), (7.7, 9.3))

    def test_a_quote_keeps_its_gap_and_its_edges(self):
        # 04_exec_brief's quote: 20.2pt high for its 18.3pt gap, the text after
        # it 8.1pt high without its edges
        t = self._box(gap=18.3, role="quote")
        top, bottom = D._gdocs_quote_edges(t)
        box = D._gdocs_para_box(t.rows[0][0].paras[0])
        self.assertAlmostEqual(top, (423.84 - 407.85) - box[3], places=6)
        self.assertGreater(bottom, 0.0)
        nxt = _para(gap=30.8, text="Deployment trajectory")
        xml = self._written(t, after=nxt)
        p = re.search(r"<w:p>(?:(?!</w:p>).)*?Key finding(?:(?!</w:p>).)*?</w:p>", xml, re.S).group(0)
        before = int(re.search(r'w:before="(\d+)"', p).group(1)) / 20.0
        self.assertGreater(before, 18.3)
        # WP24: the space after rides on what follows -- Docs set 04's heading
        # 6.5pt high with 8.0pt written as the quote's space after
        self.assertIn('w:after="0"', p)
        q = re.search(r"<w:p>(?:(?!</w:p>).)*?Deployment trajectory(?:(?!</w:p>).)*?</w:p>",
                      xml, re.S).group(0)
        got = int(re.search(r'w:before="(\d+)"', q).group(1)) / 20.0
        # (and the heading's own first-baseline move, under a point)
        self.assertAlmostEqual(got, 30.8 + bottom, delta=1.0)
        self.assertGreater(got, 30.8 + bottom - 0.15)

    def test_a_box_past_the_column_keeps_its_widest_line(self):
        # 03_tech_report_code's warning box (x 57-555, column to 551.6): the
        # right indent from the box edge left the text 3.4pt short of the
        # source's one line, and Docs set it as two
        t = self._box()
        p = t.rows[0][0].paras[0]
        t.bbox = (57.0, 407.85, 555.0, 435.18)
        t.left_indent = -15.0                    # the column starts at 72.0
        p.bbox = (75.0, 415.5, 535.0, 425.9)
        xml = self._written(t)
        w = re.search(r"<w:p>(?:(?!</w:p>).)*?Key finding(?:(?!</w:p>).)*?</w:p>", xml, re.S).group(0)
        right = int(re.search(r'w:right="(\d+)"', w).group(1)) / 20.0
        self.assertLessEqual(right, (72.0 + 468.0) - 535.0 + 0.05)
        # inside the column the box's own inset stands
        t2 = self._box()
        t2.rows[0][0].paras[0].bbox = (75.0, 415.5, 500.0, 425.9)
        t2.left_indent = 61.5 - 72.0
        xml = self._written(t2)
        w = re.search(r"<w:p>(?:(?!</w:p>).)*?Key finding(?:(?!</w:p>).)*?</w:p>", xml, re.S).group(0)
        # (the inset 51.5pt, capped at the schema's 31)
        self.assertAlmostEqual(int(re.search(r'w:right="(\d+)"', w).group(1)) / 20.0,
                               31.0, delta=0.1)

    def test_the_standard_profile_keeps_the_table_form(self):
        xml = self._written(self._box())
        lay = _lay()
        lay.pages = [_page([_para(gap=0.0), self._box()], number=1)]
        std = _xml(lay, "standard")
        self.assertIn("<w:tbl>", std)
        self.assertNotIn("<w:tbl>", xml)


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
        self.assertGreaterEqual(free, BODY + GDOCS_PAGE_SAFETY_PT - 0.11)
        self.assertLess(free, BODY + GDOCS_PAGE_SAFETY_PT + 0.1 * len(plan) + 0.11)

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

    def test_a_page_within_a_body_line_of_saving_is_paid(self):
        # y36's copyright page and y02's chapter opening came out of the model
        # 0.3-4pt short of their budget at the floors, and fitted in Docs once
        # paid: the body line is the budget's own allowance for Docs' error
        lay = _lay()
        els = [_para(gap=10.0) for _ in range(30)]
        pg = _page(els)
        over = _used(pg, lay, {}) - _body_capacity(lay)
        total = sum(el.space_before - max(SPILL_GAP_FLOOR_PT,
                                          el.space_before * SPILL_MIN_GAP_SCALE)
                    for el in els)
        short = over + GDOCS_PAGE_SAFETY_PT - total
        self.assertGreater(short, 0.0)
        self.assertTrue(_gdocs_page_plan(pg, 468.0, lay, 0.0, short + 0.5, False))
        self.assertEqual(_gdocs_page_plan(pg, 468.0, lay, 0.0, short - 0.5, False), {})
    def test_a_table_gap_is_spent_like_any_other(self):
        # the writer honours a planned table gap on its spacer paragraph
        lay = _lay()
        els = _fill(lay, slack=3.0)
        cell = Cell(paras=[_para(gap=0.0, lines=1)])
        t = TableEl(rows=[[cell], [Cell(paras=[_para(gap=0.0, lines=1)])]],
                    col_widths=[468.0], space_before=30.0,
                    bbox=(72.0, 0.0, 540.0, 24.0))
        els.insert(len(els) - 1, t)
        els[-1].space_before = 0.0
        pg = _page(els)
        plan = _gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False)
        self.assertIn(id(t), plan)
        self.assertLess(plan[id(t)], 30.0)

    def test_the_gap_docs_drops_after_the_seam_is_room_not_currency(self):
        lay = _lay()
        els = _fill(lay, slack=3.0)
        els[0].space_before += 20.0              # 17pt over -- unless dropped
        pg = _page(els)

        def paid(plan):
            return sum(el.space_before - plan[id(el)] for el in els if id(el) in plan)
        kept = _gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, False)
        self.assertGreater(paid(kept), 17.0 + BODY)
        # dropped, the 28pt first gap leaves room: much less to find, and
        # nothing taken from the dropped gap itself
        plan = _gdocs_page_plan(pg, 468.0, lay, 0.0, BODY, True)
        self.assertNotIn(id(els[0]), plan)
        self.assertLess(paid(plan), paid(kept) - 20.0)
        free = _body_capacity(lay) - _used(pg, lay, plan, drops=True)
        self.assertGreaterEqual(free, BODY + GDOCS_PAGE_SAFETY_PT - 0.11)

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
        alone = _gdocs_page_model(_page([body]), 468.0, lay, 0.0, False, {})[0]
        self.assertAlmostEqual(used, alone)

    def test_an_ordinary_figure_stays(self):
        pg = _page([self._fig(200.0, 150.0), self._fig(6.0, 20.0), _para()])
        self.assertEqual(D._gdocs_vertical_rules(pg, BODY), {})

    def test_written_anchored_not_inline(self):
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


class EveryPage(unittest.TestCase):
    def test_a_page_with_room_is_not_at_risk(self):
        lay = _lay()
        pg = _page(_fill(lay, slack=60.0))
        self.assertFalse(D._gdocs_page_at_risk(pg, 468.0, lay, 0.0, BODY, False))
        pg = _page(_fill(lay, slack=5.0))
        self.assertTrue(D._gdocs_page_at_risk(pg, 468.0, lay, 0.0, BODY, False))

    def test_a_page_before_a_blank_page_spends_no_gap(self):
        # y30's cover overflows onto its blank verso by design: the writer
        # holds no page for the blank, and fitting the cover would delete it
        lay = _lay()
        full = _fill(lay, slack=3.0)
        lay.pages = [_page([_para(gap=0.0)], number=1),
                     _page(full, number=2),
                     PageLayout(number=3, chunks=[Chunk(elements=[])]),
                     _page([_para()], number=4)]
        got = _befores(_xml(lay))
        for el in full[1:]:
            self.assertTrue(any(abs(b - el.space_before) <= 0.11 for b in got),
                            el.space_before)

    def test_a_fitting_page_is_written_in_the_calibrated_form(self):
        # its rule pays its Docs excess too: the shipped form's errors no
        # longer cancel anything (c1, x05, probe 1)
        lay = _lay()
        rule = RuleEl(width_pct=100.0, thickness=0.75, color="#cccccc",
                      space_before=10.0)
        lay.pages = [_page([_para(gap=0.0)], number=1),
                     _page([_para(), rule, _para()], number=2)]
        got = _befores(_xml(lay))
        self.assertNotIn(10.0, got)
        self.assertTrue(any(abs(b - (10.0 - GDOCS_RULE_EXCESS_PT)) <= 1.0 for b in got))

    def test_the_holder_keeps_a_page_top_gap(self):
        # on since probe 2: within-2pt up on all eight documents flown with it
        self.assertTrue(D.GDOCS_PAGE_TOP_HOLDER)
        lay = _lay()
        top = _para(gap=18.0)
        lay.pages = [_page([_para(gap=0.0)], number=1), _page([top, _para()], number=2)]
        held = _xml(lay)
        D.GDOCS_PAGE_TOP_HOLDER = False
        try:
            plain = _xml(lay)
        finally:
            D.GDOCS_PAGE_TOP_HOLDER = True
        self.assertEqual(plain.count("<w:pageBreakBefore/>"), 1)
        self.assertEqual(held.count("<w:pageBreakBefore/>"), 1)
        # the gap follows an empty 1pt holder that took the break
        self.assertEqual(held.count('<w:sz w:val="2"/>'), 2)
        self.assertTrue(any(b >= 18.0 - D.GDOCS_HOLDER_PT - 0.11 for b in _befores(held)))


def _grid(rows=5, gap=8.0, row_h=24.0, top=300.0):
    cells = [[Cell(paras=[_para(gap=0.0, lines=1)])] for _ in range(rows)]
    return TableEl(rows=cells, col_widths=[468.0], role="table", space_before=gap,
                   bbox=(72.0, top, 540.0, top + rows * row_h))


class WP24(unittest.TestCase):
    """What WP19b's live flight (probe 3) left: pages the model cannot add up,
    data tables, the cover page's rule, a quote's space after."""

    def test_a_page_the_model_cannot_add_up_keeps_the_shipped_form(self):
        # y46's two-column CV lost its page to a box gap written on a page the
        # model never saw; 02's columns lost their baselines
        lay = _lay()
        body = _times("alpha beta gamma delta " * 9, size=10.0, lead=12.6, lines=3)
        two = PageLayout(number=2, chunks=[Chunk(n_cols=2, elements=[body])])
        lay.pages = [_page([_para(gap=0.0)], number=1), two]
        xml = _xml(lay)
        legacy = round(240 * 12.6 / (10.0 * D.NATURAL_DEFAULT))       # 1.144, unquantised
        calibrated = round(240 * 12.6 / (10.0 * 1.150))
        self.assertNotEqual(legacy, calibrated)
        lines = [int(v) for v in re.findall(r'w:line="(\d+)" w:lineRule="auto"', xml)]
        self.assertIn(legacy, lines)
        # the probe's `wp24c` variant writes such a page calibrated too
        D.GDOCS_UNMODELLED_SHIPPED = False
        try:
            lines = [int(v) for v in re.findall(r'w:line="(\d+)" w:lineRule="auto"',
                                                _xml(lay))]
        finally:
            D.GDOCS_UNMODELLED_SHIPPED = True
        self.assertIn(calibrated, lines)
        self.assertNotIn(legacy, lines)
        # the same paragraph on a page the model adds up is calibrated
        lay.pages = [_page([_para(gap=0.0)], number=1), _page([body], number=2)]
        lines = [int(v) for v in re.findall(r'w:line="(\d+)" w:lineRule="auto"',
                                            _xml(lay))]
        self.assertIn(calibrated, lines)
        self.assertNotIn(legacy, lines)

    def test_a_full_such_page_is_written_calibrated(self):
        # y12's two-column pages, their columns within a line of the box:
        # 71 pages shipped, 69 calibrated (live, WP24 probe)
        lay = _lay()
        body = _times("alpha beta gamma delta " * 9, size=10.0, lead=12.6, lines=3)
        cap = _body_capacity(lay)
        # Georgia has no width table: each takes its source line count
        full = [_para(gap=0.0, lines=4, lead=12.6)
                for _ in range(int(cap // (4 * 12.6)) + 1)]
        two = PageLayout(number=2, chunks=[Chunk(n_cols=2, elements=[body] + full)])
        self.assertTrue(D._gdocs_unmodelled_tight(two, 468.0, lay, 0.0, BODY))
        roomy = PageLayout(number=2, chunks=[Chunk(n_cols=2, elements=[body])])
        self.assertFalse(D._gdocs_unmodelled_tight(roomy, 468.0, lay, 0.0, BODY))
        lay.pages = [_page([_para(gap=0.0)], number=1), two]
        lines = [int(v) for v in re.findall(r'w:line="(\d+)" w:lineRule="auto"',
                                            _xml(lay))]
        self.assertIn(round(240 * 12.6 / (10.0 * 1.150)), lines)
        self.assertNotIn(round(240 * 12.6 / (10.0 * D.NATURAL_DEFAULT)), lines)

    def test_a_box_on_such_a_page_writes_no_gap_of_its_own(self):
        lay = _lay()
        box = Blocks._box(gap=21.3)
        two = PageLayout(number=2, chunks=[Chunk(n_cols=2, elements=[_para(), box])])
        lay.pages = [_page([_para(gap=0.0)], number=1), two]
        xml = _xml(lay)
        p = re.search(r"<w:p>(?:(?!</w:p>).)*?Key finding(?:(?!</w:p>).)*?</w:p>", xml, re.S).group(0)
        self.assertEqual(int(re.search(r'w:before="(\d+)"', p).group(1)), 0)

    def test_a_data_table_stands_taller_in_docs(self):
        t = _grid(rows=5)
        self.assertAlmostEqual(D._gdocs_table_excess(t),
                               D.GDOCS_TABLE_TOP_PT + 4 * D.GDOCS_TABLE_GROW_PT
                               + D.GDOCS_TABLE_FOOT_PT)
        # a code block or a one-row grid keeps the per-row allowance
        one = _grid(rows=1)
        self.assertAlmostEqual(D._gdocs_table_excess(one), D.GDOCS_TABLE_ROW_EXCESS_PT)
        code = _grid(rows=3)
        code.role = "code"
        self.assertFalse(D._gdocs_data_table(code))

    @staticmethod
    def _moves(els, t):
        """Gaps moved with `t` a data table, and with the same table read as
        a code block (no data-table excess): the difference is the rule."""
        lay = _lay()
        out = []
        for role in ("table", "code"):
            t.role = role
            _pre, flow = D._gdocs_flow(_page(els), 468.0, lay, 0.0)
            gap_of = {id(el): el.space_before for el, _n, _h, _b in flow}
            out.append(D._gdocs_baseline_gaps(flow, gap_of, lay, False))
        t.role = "table"
        return out

    def test_the_lines_under_a_data_table_pay_its_excess(self):
        # 01's pricing table set everything under it 5.3pt low, x04's 5pt
        t = _grid(rows=5, gap=8.0)
        cap = _times("Table 1: Normalized pricing", gap=4.4, lines=1)
        after = _times("We model total cost " * 6, gap=9.2)
        data, code = self._moves([_times("intro " * 9), t, cap, after], t)
        # the spacer pays the table's top
        self.assertAlmostEqual(data[id(t)], code[id(t)] - D.GDOCS_TABLE_TOP_PT,
                               delta=0.11)
        # what the rows and the foot add is paid by the gap under it
        rest = 4 * D.GDOCS_TABLE_GROW_PT + D.GDOCS_TABLE_FOOT_PT
        self.assertAlmostEqual(data[id(cap)], code[id(cap)] - rest, delta=0.11)
        self.assertAlmostEqual(data[id(after)], code[id(after)], delta=0.11)
        # a gap too small to pay it all gives what it has, the next the rest
        cap.space_before = 0.0
        data, code = self._moves([_times("intro " * 9), t, cap, after], t)
        self.assertEqual(data[id(cap)], 0.0)
        self.assertAlmostEqual(data[id(after)], code[id(after)] - (rest - code[id(cap)]),
                               delta=0.11)

    def test_a_table_without_a_spacer_passes_its_top_down(self):
        t = _grid(rows=3, gap=0.3)
        after = _times("next " * 9, gap=12.0)
        data, code = self._moves([_times("intro " * 9), t, after], t)
        self.assertEqual(data[id(t)], 0.3)
        self.assertAlmostEqual(data[id(after)], code[id(after)] - D._gdocs_table_excess(t),
                               delta=0.11)
    def test_unmeasured_scripts_get_no_rewrap_line(self):
        # x06's Cyrillic and Greek paragraphs: a re-wrap the width tables
        # cannot see gave a line to the gap under each, and Docs kept them
        ru = _times("Замещающие автобусы курсируют в течение всего периода " * 2,
                    size=11.0, lead=14.5, lines=3)
        en = _times("Replacement buses run for the whole of the period " * 2,
                    size=11.0, lead=14.5, lines=3)
        self.assertFalse(D._gdocs_measured(ru))
        self.assertTrue(D._gdocs_measured(en))
        lay = _lay()
        for p, credited in ((en, True), (ru, False)):
            nxt = _times("next paragraph " * 3, gap=10.0, lines=1)
            _pre, flow = D._gdocs_flow(_page([p, nxt]), 468.0, lay, 0.0)
            p.src_lines = flow[0][1] + 1           # the source had one more line
            gap_of = {id(p): 0.0, id(nxt): 10.0}
            plain = D._gdocs_baseline_gaps(flow, gap_of, lay, False)
            wrapped = D._gdocs_baseline_gaps(flow, gap_of, lay, False, rewrap=True)
            self.assertEqual(wrapped[id(nxt)] > plain[id(nxt)] + 1.0, credited)

    def test_the_cover_page_rule_pays_its_excess(self):
        # 01_whitepaper_market's cover-page rule set its body 2.9pt low
        lay = _lay()
        rule = RuleEl(width_pct=100.0, thickness=0.75, color="#cccccc",
                      space_before=9.6)
        lay.pages = [_page([_para(gap=0.0), rule, _para()], number=1),
                     _page([_para()], number=2)]
        lay.cover_band = TableEl(rows=[[Cell(paras=[_para(gap=0.0, lines=1)],
                                             shading="#1E3A5F")]],
                                 col_widths=[612.0], bbox=(0.0, 0.0, 612.0, 120.0))
        got = _befores(_xml(lay))
        self.assertTrue(any(abs(b - (9.6 - GDOCS_RULE_EXCESS_PT)) <= 0.35 for b in got),
                        got)


class AnchoredPictures(unittest.TestCase):
    """The capability `anchor_pictures`: infer's
    on-a-line and wrapped pictures leave the flow without the rest of
    `anchored`."""

    def test_gdocs_has_it_without_the_rest_of_anchored(self):
        # granted live (WP24 wp24a: y01 81 -> 80, y28 22 -> 21, the synthetic
        # set 6 -> 5); slides and backgrounds stay in the flow
        from exactdoc.options import capabilities
        self.assertIn("anchor_pictures", capabilities("gdocs"))
        self.assertNotIn("anchored", capabilities("gdocs"))
        self.assertIn("anchored", capabilities("standard"))

    def test_on_a_line_only(self):
        from exactdoc import infer as I
        lay = _lay()
        line = Para(runs=[_run("1.2 Scope")])
        blocks = []
        logo = ImageEl(data=b"x", ext="png", width=17.0, height=10.0)
        logo._bbox = (72.0, 200.0, 89.0, 210.0)
        under = ImageEl(data=b"x", ext="png", width=200.0, height=100.0)
        under._bbox = (72.0, 300.0, 272.0, 400.0)

        class _L:
            def __init__(self, bb):
                self.bbox = bb
        orig = I._all_lines
        I._all_lines = lambda _b: [_L((95.0, 198.0, 300.0, 212.0)),
                                   _L((80.0, 340.0, 260.0, 352.0))]
        try:
            keep, floats = I._float_backgrounds([logo, under, line], blocks, lay,
                                                612.0, 792.0, pictures_only=True)
            full_keep, full_floats = I._float_backgrounds([logo, under, line], blocks,
                                                          lay, 612.0, 792.0)
        finally:
            I._all_lines = orig
        self.assertEqual([f.el for f in floats], [logo])
        self.assertIn(under, keep)                # a background stays in the flow
        self.assertEqual({id(f.el) for f in full_floats}, {id(logo), id(under)})


class TheWriter(unittest.TestCase):
    def _doc(self):
        lay = _lay()
        first = _page([_para(gap=0.0)], number=1)
        full = _page(_fill(lay, slack=3.0))
        lay.pages = [first, full]
        return lay, full

    def test_gdocs_pays_and_so_does_the_standard_profile(self):
        # Until WP34 the standard profile left a page 3pt inside its box as
        # it was. It now has its own planner (`pagefit.fit_page`), on its own
        # line model; this file pins only that the gdocs page is paid.
        lay, full = self._doc()
        asked = sum(el.space_before for el in full.chunks[0].elements)
        std = _befores(_xml(lay, "standard"))
        gd = _befores(_xml(lay, "gdocs"))
        self.assertLess(sum(gd), asked)
        self.assertLess(sum(std), asked)

    def test_the_layout_is_not_modified(self):
        lay, full = self._doc()
        asked = [el.space_before for el in full.chunks[0].elements]
        _xml(lay, "gdocs")
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
            # the multiple of the 13.92 median at Times' 1.150 (242), not the
            # 13.80 mean's (240)
            self.assertIn(round(240 * 13.92 / (12.0 * 1.150)), lines)
            self.assertNotIn(round(240 * 13.80 / (12.0 * 1.150)), lines)
            # the standard profile writes the same median, exactly
            std = os.path.join(d, "std.docx")
            convert(src, std, options=RAW, max_pages=0)
            xml = zipfile.ZipFile(std).read("word/document.xml").decode("utf-8")
            self.assertRegex(xml, r'w:lineRule="exact" w:line="278"')


if __name__ == "__main__":
    unittest.main()
