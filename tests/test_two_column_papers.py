"""Journal and arXiv papers: two-column pages, display maths, stacked glyphs.

WP12. Measured with the line microscope (THEORY section 4) on the seven
academic papers of the expansion corpus, the raw lane rendered y41 (IEEEtran)
8 -> 20 pages, y39 (Copernicus) 11 -> 28, y43 (NeurIPS) 15 -> 31. The causes
these tests pin:

* the two-column split taken from the most populous block cluster landed
  52pt inside y41 p2's left column -- display-maths fragments outnumbered the
  right column's blocks -- and every line rendered one character wide; the
  gutter (white the column lines never cross) is now the evidence;
* a full-width float in mid-page was moved below the columns;
* a line the parser joined across the gutter ("(3)" + right-column text) cut
  the columns into three chunks;
* equation numbers at the margin of a one-column page passed for a column;
* the parser grouped a two-column body's maths-fragmented baselines as table
  rows, fusing both columns into page-wide blocks;
* a displayed equation's fragments became one full-line paragraph each;
* a glyph TeX stacks over another (the "~" of a congruence sign) became a
  paragraph between the lines of its own.
"""
import unittest

from exactdoc import fonts
from exactdoc.infer import (infer, _absorb_fragments, _display_paras,
                            _display_rows, _split_at_gutter, _split_crossed,
                            _two_column_gutter)
from exactdoc.layout import ColBreak, Para
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock
from exactdoc.parse_pdfium import _group_table_rows

PAGE_W, PAGE_H = 612.0, 792.0
L0, L1 = 54.0, 300.0        # left column
R0, R1 = 312.0, 558.0       # right column
PROSE = "the quick brown fox jumps over the lazy dog and keeps on running"


def _span(x0, x1, base, text, size=10.0, font="NimbusRomNo9L-Regu"):
    return Span(text=text, font=font, size=size, color="#000000", bold=False,
                italic=False, mono=False, serif=True, superscript=False,
                bbox=(x0, base - 0.8 * size, x1, base + 0.2 * size),
                origin=(x0, base))


def _line(x0, x1, base, text=PROSE, size=10.0, font="NimbusRomNo9L-Regu"):
    s = _span(x0, x1, base, text, size, font)
    return Line(spans=[s], bbox=s.bbox)


def _block(lines):
    bb = (min(l.bbox[0] for l in lines), min(l.bbox[1] for l in lines),
          max(l.bbox[2] for l in lines), max(l.bbox[3] for l in lines))
    return TextBlock(lines=list(lines), bbox=bb)


def _column(x0, x1, top, n, pitch=12.0, per_block=4):
    lines = [_line(x0, x1, top + pitch * i) for i in range(n)]
    return [_block(lines[i:i + per_block]) for i in range(0, n, per_block)]


def _doc(blocks):
    return DocIR(path="paper.pdf", pages=[
        PageIR(number=1, width=PAGE_W, height=PAGE_H, blocks=blocks)])


def _chunks(lay):
    return [ch for pl in lay.pages for ch in pl.chunks]


def _texts(elements):
    return [e.text for e in elements if isinstance(e, Para)]


class GutterDetection(unittest.TestCase):
    def test_two_columns_with_a_display_and_its_number(self):
        lines = [l for b in _column(L0, L1, 100, 30) + _column(R0, R1, 100, 30)
                 for l in b.lines]
        # a display in the left column: the expression, and its number flush
        # at the column's right edge
        lines += [_line(140, 230, 500, "x = y + z", font="CMMI10"),
                  _line(288, 300, 500, "(1)")]
        g = _two_column_gutter(lines, L0, R1)
        self.assertIsNotNone(g)
        self.assertLessEqual(g[0], R0)
        self.assertGreaterEqual(g[1], L1)
        self.assertGreater(g[1] - g[0], 8.0)

    def test_a_one_column_page_with_equation_numbers_has_no_gutter(self):
        lines = [_line(L0, R1, 100 + 12 * i) for i in range(30)]
        lines += [_line(250, 330, 470 + 30 * k, "a = b", font="CMMI10")
                  for k in range(6)]
        lines += [_line(540, R1, 470 + 30 * k, "(%d)" % (k + 1))
                  for k in range(6)]
        self.assertIsNone(_two_column_gutter(lines, L0, R1))

    def test_a_short_inset_beside_text_is_not_a_column(self):
        # six lines on the right beside a tall column: the band qualifies,
        # the shorter column does not run a fifth of the body
        lines = [l for b in _column(L0, L1, 100, 50) for l in b.lines]
        lines += [l for b in _column(R0, R1, 100, 6) for l in b.lines]
        g = _two_column_gutter(lines, L0, R1)
        self.assertIsNotNone(g)
        self.assertLess(g[2], 0.2 * (PAGE_H - 100))


class Sidebar(unittest.TestCase):
    """A narrow metadata column beside the main column (y40's title page)."""

    S0, S1 = 54.0, 150.0          # sidebar
    M0, M1 = 215.0, 558.0         # main column

    def _lines(self, side_pitch):
        side = [_line(self.S0, self.S1, 104 + side_pitch * i, "Editor, Univ.",
                      size=7.0) for i in range(40)]
        # paragraphs end short, as real ones do: the column's full lines are
        # wider than the narrow-line scan reads, its last lines are not
        main = [_line(self.M0, self.M1 if i % 5 else self.M0 + 180,
                      100 + 12 * i) for i in range(40)]
        return side, main

    def test_a_sidebar_on_its_own_grid_is_a_column(self):
        side, main = self._lines(9.0)
        g = _two_column_gutter(side + main, self.S0, self.M1)
        self.assertIsNotNone(g)
        self.assertGreaterEqual(g[0], self.S1 - 1)
        self.assertLessEqual(g[1], self.M0 + 1)

    def test_labels_on_their_values_baselines_are_rows_not_a_column(self):
        # a glossary: every term sits on the baseline of its definition
        side, main = self._lines(12.0)
        side = [_line(self.S0, self.S1, 100 + 12 * i, "Term") for i in range(40)]
        self.assertIsNone(_two_column_gutter(side + main, self.S0, self.M1))

    def test_unequal_widths_reach_the_section_standard_profile_only(self):
        from exactdoc.docxout import _section_widths, _config_section
        from exactdoc.layout import Chunk, DocLayout
        from docx import Document
        from docx.oxml.ns import qn
        ch = Chunk(n_cols=2, col_gap=65.0, col_widths=[96.0, 343.0])

        class Ctx:
            output_profile = "standard"
        self.assertEqual(_section_widths(ch, Ctx), (96.0, 343.0))
        Ctx.output_profile = "gdocs"
        self.assertIsNone(_section_widths(ch, Ctx))
        doc = Document()
        _config_section(doc.sections[0], DocLayout(), cols=2, col_gap=65.0,
                        col_widths=(96.0, 343.0))
        cols = doc.sections[0]._sectPr.find(qn("w:cols"))
        self.assertEqual(cols.get(qn("w:equalWidth")), "0")
        self.assertEqual([c.get(qn("w:w")) for c in cols.findall(qn("w:col"))],
                         ["1920", "6860"])
        # re-configured as equal columns, the per-column widths go
        _config_section(doc.sections[0], DocLayout(), cols=2, col_gap=24.0)
        self.assertEqual(cols.findall(qn("w:col")), [])
        self.assertEqual(cols.get(qn("w:equalWidth")), "1")

    def test_end_to_end_widths_follow_the_page(self):
        side, main = self._lines(9.0)
        blocks = [_block(side[i:i + 5]) for i in range(0, 40, 5)]
        blocks += [_block(main[i:i + 5]) for i in range(0, 40, 5)]
        lay = infer(_doc(blocks))
        two = [ch for ch in _chunks(lay) if ch.n_cols == 2]
        self.assertEqual(len(two), 1)
        w = two[0].col_widths
        self.assertEqual(len(w), 2)
        self.assertLess(w[0], 0.5 * w[1])


class MidPageSpanningFloat(unittest.TestCase):
    """A full-width caption between two runs of columns stays between them."""

    def _ir(self):
        blocks = [_block([_line(200, 412, 70, "A Paper Title", size=14)])]
        blocks += _column(L0, L1, 110, 16) + _column(R0, R1, 110, 16)
        blocks += [_block([_line(L0, R1, 330, PROSE + " " + PROSE),
                           _line(L0, 400, 342, "the caption ends here")])]
        blocks += _column(L0, L1, 380, 30) + _column(R0, R1, 380, 30)
        return _doc(blocks)

    def test_bands_in_source_order(self):
        lay = infer(self._ir())
        shape = [ch.n_cols for ch in _chunks(lay)]
        self.assertEqual(shape, [1, 2, 1, 2])
        caption = _chunks(lay)[2]
        self.assertTrue(any("caption ends here" in t
                            for t in _texts(caption.elements)))

    def test_a_title_line_above_the_first_heading_is_not_a_column_section(self):
        # y26's index pages: "Appendix D Indexes" sits in the left column's
        # x-range above the spanning "D.1 ..." heading
        blocks = [_block([_line(L0, 180, 70, "Appendix D Indexes", size=14)]),
                  _block([_line(L0, 420, 100, "D.1 Index of Shell Builtins",
                                size=12)])]
        blocks += _column(L0, L1, 130, 40) + _column(R0, R1, 130, 40)
        shape = [ch.n_cols for ch in _chunks(infer(_doc(blocks)))]
        self.assertEqual(shape, [1, 2])

    def test_each_column_run_has_one_column_break(self):
        lay = infer(self._ir())
        for ch in _chunks(lay):
            if ch.n_cols == 2:
                self.assertEqual(
                    sum(1 for e in ch.elements if isinstance(e, ColBreak)), 1)


class LineJoinedAcrossTheGutter(unittest.TestCase):
    GUTTER = (300.0, 312.0)

    def test_number_and_right_column_text_divide(self):
        ln = Line(spans=[_span(288, 300, 200, "(3)"),
                         _span(312, 558, 200, "ditioning matrix is applied")],
                  bbox=(288, 192, 558, 202))
        parts = _split_at_gutter(ln, self.GUTTER)
        self.assertEqual([p.text for p in parts],
                         ["(3)", "ditioning matrix is applied"])

    def test_a_running_heads_halves_stay_one_line(self):
        # the left half ends far short of the gutter, the right half starts
        # far past it: a page-wide line, not two column lines
        ln = Line(spans=[_span(54, 190, 40, "Conference '24, City"),
                         _span(420, 558, 40, "A. Author et al.")],
                  bbox=(54, 32, 558, 42))
        self.assertEqual(len(_split_at_gutter(ln, self.GUTTER)), 1)

    def test_a_span_across_the_gutter_is_not_cut(self):
        ln = Line(spans=[_span(54, 558, 40, PROSE)], bbox=(54, 32, 558, 42))
        self.assertEqual(len(_split_at_gutter(ln, self.GUTTER)), 1)


class EquationNumbersAreNotAColumn(unittest.TestCase):
    def test_split_with_margin_narrow_right_side_is_refuted(self):
        # prose between the numbered displays, as on y43 p3
        lines = []
        for k in range(6):
            lines += [_line(L0, R1, 100 + 80 * k + 12 * i) for i in range(4)]
            lines.append(_line(540, R1, 160 + 80 * k, "(%d)" % k))
        self.assertTrue(_split_crossed(lines, 540.0, L0, R1))

    def test_a_wide_right_side_is_left_to_the_block_path(self):
        # lshort's code-and-output boxes: real side-by-side regions that
        # prose also crosses keep their reading
        lines = [_line(L0, R1, 100 + 12 * i) for i in range(30)]
        self.assertFalse(_split_crossed(lines, 312.0, L0, R1))

    def test_end_to_end_one_column_page(self):
        blocks = []
        y = 100.0
        for k in range(8):
            blocks.append(_block([_line(L0, R1, y + 12 * i) for i in range(3)]))
            y += 46
            x = 200 + 9 * k             # displays do not share a left edge
            blocks.append(_block([_line(x, x + 120, y, "f(x) = g(x)",
                                        font="CMMI10")]))
            blocks.append(_block([_line(540, R1, y, "(%d)" % (k + 1))]))
            y += 20
        lay = infer(_doc(blocks))
        self.assertTrue(all(ch.n_cols == 1 for ch in _chunks(lay)))
        paras = [e for ch in _chunks(lay) for e in ch.elements
                 if isinstance(e, Para)]
        numbered = [p for p in paras if "(3)" in p.text]
        self.assertEqual(len(numbered), 1)
        self.assertIn("f(x) = g(x)", numbered[0].text)
        self.assertEqual(numbered[0].tab_stops[-1][1], "right")


class ParserTwoColumnBody(unittest.TestCase):
    """`_group_table_rows` must not read a two-column body as a table."""

    def _blocks(self):
        left, right = [], []
        for i in range(12):
            base = 100 + 12 * i
            if i in (3, 7, 10):
                left.append(_line(46.5, 110, base, "short end."))
            else:
                left.append(_line(46.5, 287.4, base))
            if i in (2, 5, 8):
                # an inline formula breaks the right column's line into
                # abutting pieces
                right += [_line(307.3, 362.4, base, "time t + u"),
                          _line(363.2, 430.0, base, "k", font="CMMI10"),
                          _line(430.8, 548.2, base, ". It is convenient")]
            else:
                right.append(_line(307.3, 548.2, base))
        return [_block(left[:6]), _block(left[6:]),
                _block(right[:9]), _block(right[9:])]

    def test_no_block_straddles_the_gutter(self):
        out = _group_table_rows(self._blocks(), [296.0])
        for b in out:
            xs = [l.bbox[0] for l in b.lines]
            self.assertFalse(min(xs) < 296.0 < max(xs),
                             "a block holds both columns: %r" % b.text[:60])

    def test_a_table_inside_one_column_still_groups(self):
        rows = []
        for i in range(4):
            base = 100 + 12 * i
            rows.append(_block([_line(320, 360, base, "Load")]))
            rows.append(_block([_line(380, 420, base, "12.%d" % i)]))
            rows.append(_block([_line(440, 480, base, "3.%d" % i)]))
        out = _group_table_rows(rows, [296.0])
        self.assertLess(len(out), len(rows))


class DisplayedEquations(unittest.TestCase):
    COL = (108.0, 504.0)

    def _items(self, lines):
        return [("blk", l.bbox, _block([l])) for l in lines]

    def test_a_fraction_is_one_paragraph_per_row_at_its_own_pitch(self):
        num = _line(347.3, 367.7, 513.9, "g(t)2", font="CMMI10")
        main = Line(spans=[_span(218.5, 343.9, 520.7, "pt(x) = div(f) +",
                                 font="CMMI10")], bbox=(218.5, 512.7, 343.9, 522.7))
        eqno = _line(493.1, 504.7, 520.7, "(2)")
        den = _line(355.3, 360.3, 527.5, "2", font="CMR10")
        rows, used = _display_rows(self._items([num, main, eqno, den]), *self.COL)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 3)
        paras = _display_paras(rows[0], *self.COL)
        self.assertEqual(len(paras), 3)
        self.assertAlmostEqual(paras[0].leading, 6.8, places=1)
        self.assertAlmostEqual(paras[1].leading, 6.8, places=1)
        self.assertIn("(2)", paras[1].text)
        self.assertEqual(paras[1].tab_stops[-1],
                         (round(self.COL[1] - self.COL[0], 1), "right"))

    def test_a_line_of_prose_and_its_subscript_is_not_a_display(self):
        prose = _line(108, 504, 500, "where Omega = N x M, T is fixed time, "
                      "and the two small parameters are", font="NimbusRomNo9L-Regu")
        sub = _line(250, 254, 502.5, "t", size=7.0, font="CMMI7")
        rows, used = _display_rows(self._items([prose, sub]), *self.COL)
        self.assertEqual(rows, [])

    def test_lines_of_prose_close_together_are_left_alone(self):
        a = _line(108, 300, 500, "a caption line")
        b = _line(108, 300, 507, "a second line")
        rows, used = _display_rows(self._items([a, b]), *self.COL)
        self.assertEqual(rows, [])
        self.assertEqual(used, set())

    def test_a_label_beside_a_value_is_not_an_equation(self):
        a = Line(spans=[_span(108, 200, 500, "Total = 12"),
                        _span(300, 340, 500, "units")], bbox=(108, 492, 340, 502))
        rows, _ = _display_rows(self._items([a]), *self.COL)
        self.assertEqual(rows, [])


class StackedFragments(unittest.TestCase):
    def test_a_glyph_set_above_the_line_joins_it(self):
        host = Line(spans=[_span(108, 210, 458.5, "Lie Groups G "),
                           _span(210, 505, 458.5, "= G/{e} are symmetric")],
                    bbox=(108, 450.5, 505, 460.5))
        tilde = _line(215.1, 222.8, 455.8, "∼", font="CMSY10")
        items = [("blk", host.bbox, _block([host])),
                 ("blk", tilde.bbox, _block([tilde]))]
        out = _absorb_fragments(items)
        self.assertEqual(len(out), 1)
        text = out[0][2].lines[0].text
        self.assertIn("∼", text)
        self.assertLess(text.index("G "), text.index("∼"))
        self.assertLess(text.index("∼"), text.index("= G/"))

    def test_a_same_baseline_continuation_joins_its_line(self):
        host = _line(108, 376.2, 595.8, "the set of all diagonal matrices {diag(e")
        cont = _line(387.2, 413.9, 595.8, ", . . . , e", font="CMMI10")
        items = [("blk", host.bbox, _block([host])),
                 ("blk", cont.bbox, _block([cont]))]
        out = _absorb_fragments(items)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0][2].lines[0].text.endswith(", . . . , e"))

    def test_two_column_lines_on_one_baseline_stay_apart(self):
        a = _line(L0, L1, 200)
        b = _line(R0, R1, 200)
        items = [("blk", a.bbox, _block([a])), ("blk", b.bbox, _block([b]))]
        self.assertEqual(len(_absorb_fragments(items)), 2)


class AcademicFaces(unittest.TestCase):
    def test_libertine_is_a_serif(self):
        self.assertEqual(fonts.map_font("LinLibertineT"), "Times New Roman")
        t = fonts.font_traits("LinLibertineTB")
        self.assertEqual(t.cls, "serif")
        self.assertTrue(t.bold)
        self.assertTrue(fonts.font_traits("LinLibertineTI").italic)

    def test_biolinum_is_a_sans(self):
        self.assertEqual(fonts.map_font("LinBiolinumT"), "Arial")
        self.assertTrue(fonts.font_traits("LinBiolinumTB").bold)

    def test_mathtime_and_txfonts_are_the_body_serif(self):
        for name in ("MTMI", "MTSYN", "RMTMI", "txmiaX", "txsys"):
            self.assertEqual(fonts.font_traits(name).cls, "serif", name)


if __name__ == "__main__":
    unittest.main()
