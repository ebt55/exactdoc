"""Line assembly: overprinted lines, logo glyphs, starved paragraphs.

Catalogue #24 (lines interleaved letter by letter), #14 (the TeX logo's
lowered `E` on a line of its own) and #23 (one character per line), each
traced to the stage that assembles lines and fixed there.

    python tests/test_line_assembly.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.parse_pdfium import _Char, _build_lines  # noqa: E402
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock  # noqa: E402


def _char(u, x0, x1, size=10.0, baseline=100.0, font="Helvetica"):
    c = _Char()
    c.u = u
    c.x0, c.x1 = x0, x1
    c.y0, c.y1 = baseline - size, baseline
    c.ox, c.oy = x0, baseline
    c.size = size
    c.font = font
    c.flags = 0
    c.color = "#000000"
    c.gen = False
    return c


def _word(text, x0, adv, **kw):
    return [_char(ch, x0 + i * adv, x0 + (i + 1) * adv, **kw)
            for i, ch in enumerate(text)]


class OverprintedLines(unittest.TestCase):
    def test_heading_over_footer_stays_two_lines(self):
        # x07: a 13.5pt heading 0.75pt from the baseline of an 8pt footer that
        # runs under it. Baseline grouping used to sort both into one row.
        heading = _word("4. Circulation", 57.8, 6.1, size=13.5, baseline=695.25,
                        font="Sans-Bold")
        footer = _word("Transit Authority Operations", 57.8, 4.4, size=8.0,
                       baseline=696.0, font="Sans")
        texts = sorted(ln.text for ln in _build_lines(heading + footer))
        self.assertEqual(texts, ["4. Circulation", "Transit Authority Operations"])

    def test_same_baseline_neighbours_still_join(self):
        # RFC 9110: a 9pt bold keyword inline with 10pt text never overlaps it.
        chars = (_word("A sender ", 10.0, 5.0) +
                 _word("MUST", 55.0, 6.0, size=9.0, font="Bold") +
                 _word(" do it", 79.0, 5.0))
        self.assertEqual(len(_build_lines(chars)), 1)

    def test_a_long_fragment_is_not_a_script(self):
        # Pub 501: an 8pt line of the next column 2.5pt above a row that holds
        # a 9.6pt bullet was absorbed glyph by glyph as a "superscript".
        host = [_char("•", 48.0, 51.8, size=9.6, baseline=588.7)] + \
            _word("No estimated tax ", 59.0, 4.0, size=8.0, baseline=588.68) + \
            _word("Box 1e on line", 400.0, 4.0, size=8.0, baseline=588.68)
        other = _word("ple, you should file if one of", 222.0, 4.0, size=8.0,
                      baseline=586.18)
        lines = _build_lines(host + other)
        self.assertFalse(any(s.superscript for ln in lines for s in ln.spans))
        self.assertIn("ple, you should file if one of", [ln.text for ln in lines])

    def test_real_superscript_is_still_absorbed(self):
        chars = (_word("Researcher", 0.0, 1.0) +
                 _word("1", 10.5, 2.0, size=7.0, baseline=96.0) +
                 _word(",B", 12.6, 1.0))
        line = _build_lines(chars)[0]
        self.assertEqual(line.text, "Researcher1,B")
        self.assertEqual([s.text for s in line.spans if s.superscript], ["1"])


class LogoGlyphs(unittest.TestCase):
    def test_tex_logo_lowered_e_stays_in_the_word(self):
        # lshort: T 176.85-184.72, E lowered 2.34pt at 182.91-190.32,
        # X 188.96-197.14, all 10.91pt.
        chars = [_char("T", 176.85, 184.72, size=10.91, baseline=557.01),
                 _char("E", 182.91, 190.32, size=10.91, baseline=559.35),
                 _char("X", 188.96, 197.14, size=10.91, baseline=557.01)]
        lines = _build_lines(chars)
        self.assertEqual([ln.text for ln in lines], ["TEX"])
        self.assertFalse(any(s.superscript for s in lines[0].spans))

    def test_latex_logo_raised_a_over_l(self):
        chars = [_char("L", 169.61, 176.42, size=10.91, baseline=557.01),
                 _char("A", 172.51, 178.48, size=7.97, baseline=555.33),
                 _char("T", 176.85, 184.72, size=10.91, baseline=557.01),
                 _char("E", 182.91, 190.32, size=10.91, baseline=559.35),
                 _char("X", 188.96, 197.14, size=10.91, baseline=557.01)]
        lines = _build_lines(chars)
        self.assertEqual([ln.text for ln in lines], ["LATEX"])

    def test_a_fraction_denominator_is_not_a_logo_glyph(self):
        # Frontiers: `∂s` set 3.2pt under `∂u` at the same size. It sits
        # beneath host glyphs rather than between them.
        num = [_char("x", 10.0, 15.0, size=9.0), _char("∂", 15.0, 20.0, size=9.0),
               _char("u", 20.0, 25.0, size=9.0)]
        den = [_char("∂", 15.0, 20.0, size=9.0, baseline=103.2)]
        self.assertEqual(len(_build_lines(num + den)), 2)

    def test_three_full_size_glyphs_are_a_line(self):
        host = _word("word", 10.0, 5.0)
        lower = _word("abc", 30.5, 5.0, baseline=103.0)
        self.assertEqual(len(_build_lines(host + lower)), 2)


def _span(text, x0, x1, y, size=10.0):
    return Span(text=text, font="Sans", size=size, color="#000000", bold=False,
                italic=False, mono=False, serif=False, superscript=False,
                bbox=(x0, y - size, x1, y), origin=(x0, y))


class LineLevelGuards(unittest.TestCase):
    def test_dialect_does_not_join_an_overprint(self):
        from exactdoc.dialect import normalize
        head = Line(spans=[_span("4. Circulation", 57.8, 143.2, 695.25, 13.5)],
                    bbox=(57.8, 681.75, 143.2, 695.25))
        foot = Line(spans=[_span("Transit Authority Operations", 57.8, 295.5,
                                 696.0, 8.0)], bbox=(57.8, 688.0, 295.5, 696.0))
        ir = DocIR("s.pdf", [PageIR(1, 612, 792, blocks=[
            TextBlock(lines=[head], bbox=head.bbox),
            TextBlock(lines=[foot], bbox=foot.bbox)])])
        normalize(ir)
        texts = sorted(ln.text for b in ir.pages[0].blocks for ln in b.lines)
        self.assertEqual(texts, ["4. Circulation", "Transit Authority Operations"])

    def test_infer_rows_keep_an_overprint_apart(self):
        from exactdoc.infer import _merge_row_lines
        head = Line(spans=[_span("4. Circulation", 57.8, 143.2, 695.25, 13.5)],
                    bbox=(57.8, 681.75, 143.2, 695.25))
        foot = Line(spans=[_span("Transit Authority Operations", 57.8, 295.5,
                                 696.0, 8.0)], bbox=(57.8, 688.0, 295.5, 696.0))
        self.assertEqual(len(_merge_row_lines([head, foot])), 2)


class StarvedParagraphs(unittest.TestCase):
    def test_line_beyond_the_column_keeps_room(self):
        # RFC 9110's footer `Page 5` at 512-539 against a body column ending at
        # 506: the indent (446) exceeded the column (440).
        from exactdoc.infer import para_from_lines
        ln = Line(spans=[_span("Page 5", 512.0, 538.8, 735.6, 9.0)],
                  bbox=(512.0, 726.6, 538.8, 735.6))
        p = para_from_lines([ln], 65.9, 506.1)
        room = (506.1 - 65.9) - p.left_indent - p.right_indent
        self.assertGreaterEqual(room + 0.05, 538.8 - 512.0)
        self.assertEqual(p.align, "right")

    def test_running_text_a_few_points_over_is_left_alone(self):
        # WDR: column-2 paragraphs 5.7pt past an inferred edge. That is a
        # margin estimate, not a starved paragraph; moving them cost 2 pages.
        from exactdoc.infer import para_from_lines
        lines = [Line(spans=[_span("running text line %d" % i, 297.0, 508.5,
                                   100.0 + 14 * i)],
                      bbox=(297.0, 90.0 + 14 * i, 508.5, 100.0 + 14 * i))
                 for i in range(4)]
        p = para_from_lines(lines, 67.5, 502.8)
        self.assertEqual(p.left_indent, 229.5)

    def test_ordinary_indent_is_untouched(self):
        from exactdoc.infer import para_from_lines
        ln = Line(spans=[_span("quoted text", 102.0, 300.0, 200.0)],
                  bbox=(102.0, 190.0, 300.0, 200.0))
        p = para_from_lines([ln], 72.0, 540.0)
        self.assertEqual(p.left_indent, 30.0)


if __name__ == "__main__":
    unittest.main()
