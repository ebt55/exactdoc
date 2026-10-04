"""Word spaces the parser used to lose (defect catalogue #15, README #48).

Two separate mechanisms, both measured on real documents:

  * a gap at a STYLE boundary was never tested for a space at all -- xml2rfc
    draws `A sender ` then jumps over the bold `MUST NOT` to `generate`, and
    RFC 9110 read `MUST NOTgenerate` 26 times in 30 pages;
  * PDFium's text page skips a text object with no width, so a producer that
    draws each glyph as its own object (Chromium) loses every space glyph at
    that step; a space kerned against a capital then leaves too small a gap
    for PDFium's own re-synthesis: `Asmaller`, `CobaltAnalytics`.

    python tests/test_word_spaces.py
"""
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.parse_pdfium import (_Char, _build_lines,  # noqa: E402
                                   _restore_dropped_spaces)


def _char(u, x0, x1, size=10.0, font="Helvetica", baseline=100.0, gen=False):
    c = _Char()
    c.u = u
    c.x0, c.x1 = x0, x1
    c.y0, c.y1 = baseline - size, baseline
    c.ox, c.oy = x0, baseline
    c.size = size
    c.font = font
    c.flags = 0
    c.color = "#000000"
    c.gen = gen
    return c


def _word(text, x0, adv=5.0, **kw):
    return [_char(ch, x0 + i * adv, x0 + (i + 1) * adv, **kw)
            for i, ch in enumerate(text)]


class StyleBoundarySpaces(unittest.TestCase):
    def test_keyword_gap_at_a_style_boundary_is_a_space(self):
        # RFC 9110's geometry: a 9pt bold keyword, then 2.10pt (0.233em of
        # 9pt) to the regular 10pt continuation, no glyph in between.
        chars = (_word("MAY", 10.0, adv=6.0, size=9.0, font="NotoSerif-Bold")
                 + _word("attempt", 30.1, adv=5.0, font="NotoSerif-Regular"))
        self.assertEqual(_build_lines(chars)[0].text, "MAY attempt")

    def test_boundary_inside_a_word_stays_joined(self):
        # A ligature drawn from a second font (`de` + `fi` + `ned`) sits flush:
        # boundary gaps inside words measured <=0.06em.
        chars = (_word("de", 10.0) + _word("fi", 20.5, font="Noto2")
                 + _word("ned", 30.9))
        self.assertEqual(_build_lines(chars)[0].text, "defined")

    def test_in_span_bar_is_unchanged(self):
        # Same style both sides: 0.22em is still not a space (the old bar).
        chars = _word("ab", 10.0) + _word("cd", 22.2)
        self.assertEqual(_build_lines(chars)[0].text, "abcd")


class DroppedSpaceGlyphs(unittest.TestCase):
    def test_kerned_space_is_restored(self):
        # x17: `A` 43.50-50.50, space object at 49.50, `s` at 51.75.
        chars = [_char("A", 43.5, 50.5, size=9.7)] + \
            _word("smaller", 51.75, adv=3.8, size=9.7)
        n = _restore_dropped_spaces(chars, [(49.5, 100.0)])
        self.assertEqual(n, 1)
        self.assertEqual(_build_lines(chars)[0].text, "A smaller")

    def test_zero_width_object_inside_a_word_is_not_a_space(self):
        # InDesign stacks empty objects on a glyph's own origin inside words
        # (`M|anager`): no gap, origin at the glyph's start.
        chars = [_char("M", 10.0, 18.0)] + _word("anager", 18.0)
        self.assertEqual(_restore_dropped_spaces(chars, [(10.0, 100.0)]), 0)
        self.assertEqual(_build_lines(chars)[0].text, "Manager")

    def test_existing_space_is_not_doubled(self):
        chars = _word("platform", 10.0) + [_char(" ", 50.0, 52.0, gen=True)] + \
            _word("that", 52.5)
        self.assertEqual(_restore_dropped_spaces(chars, [(49.9, 100.0)]), 0)

    def test_point_off_the_line_is_ignored(self):
        chars = [_char("A", 43.5, 50.5)] + _word("s", 51.75)
        self.assertEqual(_restore_dropped_spaces(chars, [(49.5, 120.0)]), 0)

    def test_end_to_end_on_a_synthetic_pdf(self):
        # One text object per glyph, the space kerned 1pt back into `A`:
        # PDFium's own text reads `Asmaller`.
        from reportlab.pdfgen import canvas
        from exactdoc.parse_pdfium import parse_pdf
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(300, 200))
        c.setFont("Helvetica", 10)
        c.drawString(20.0, 100, "A")
        c.drawString(25.67, 100, " ")
        c.drawString(28.0, 100, "smaller")
        c.save()
        fd, path = tempfile.mkstemp(suffix=".pdf")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(buf.getvalue())
            ir = parse_pdf(path)
        finally:
            os.unlink(path)
        texts = [ln.text for b in ir.pages[0].blocks for ln in b.lines]
        self.assertEqual(texts, ["A smaller"])


if __name__ == "__main__":
    unittest.main()
