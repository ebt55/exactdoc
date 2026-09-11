"""TeX Computer Modern PUA characters translate to what they read as.

Both parsers synthesise Adobe's PUA assignments for CM glyphs with no
Unicode (delimiter pieces, oldstyle digits); without translation the DOCX
carries Private Use characters that render as garbage. The table was
derived from the embedded CFF charsets of the corpus's own documents --
see the comment on `_TEX_PUA_TO_UNICODE` in dialect.py.
"""
import unittest

from exactdoc.dialect import normalize, _TEX_PUA_TO_UNICODE
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock


def _page_with(spans):
    lines = [Line([s], s.bbox) for s in spans]
    blocks = [TextBlock(lines, lines[0].bbox)]
    return PageIR(number=1, width=612.0, height=792.0, blocks=blocks)


def _span(text, font):
    return Span(text, font, 10.0, "#000000", False, False, False, False,
                False, (40.0, 100.0, 200.0, 112.0), (40.0, 110.0))


class TexPUATranslation(unittest.TestCase):
    def test_cmex_delimiter_pieces_become_base_characters(self):
        # the exact PUA values observed on y22_lshort p71: a tall bracket
        # drawn as top/ex/bottom pieces, and brace pieces from p111
        s = _span("\uf8eb\uf8ec\uf8ed \uf8f1\uf8f2\uf8f3 \uf8ee\uf8ef\uf8f0",
                  "CMEX10")
        ir = DocIR(path="x.pdf", pages=[_page_with([s])])
        normalize(ir)
        # in the real documents the pieces sit on different lines; in one
        # span they simply read as the base character, once per piece
        self.assertEqual(s.text, "((( {{{ [[[")

    def test_cmmi_oldstyle_and_dotless(self):
        s = _span("\uf731\uf732\uf733\uf734 \uf6be", "CMMI10")
        ir = DocIR(path="x.pdf", pages=[_page_with([s])])
        normalize(ir)
        self.assertEqual(s.text, "1234 \u0237")

    def test_non_cm_font_is_untouched(self):
        # a PUA value in another face keeps its producer's meaning: the
        # table is keyed to fonts, not to bare codepoints
        s = _span("\uf8eb", "ZapfDingbats")
        ir = DocIR(path="x.pdf", pages=[_page_with([s])])
        normalize(ir)
        self.assertEqual(s.text, "\uf8eb")

    def test_plain_cm_text_is_untouched(self):
        s = _span("ordinary math italic", "CMMI10")
        ir = DocIR(path="x.pdf", pages=[_page_with([s])])
        normalize(ir)
        self.assertEqual(s.text, "ordinary math italic")

    def test_every_table_value_maps_to_bmp(self):
        for v in _TEX_PUA_TO_UNICODE.values():
            self.assertLess(ord(v), 0x3000)


if __name__ == "__main__":
    unittest.main()
