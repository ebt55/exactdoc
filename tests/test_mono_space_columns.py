"""A typewriter table's columns are its typed spaces.

FIPS 197's key-expansion tables (y03, Appendix A) set each row as one Courier
string, columns two spaces apart: '0914dff4  14dff409  fa9ebf01 ...'. The
parser keeps literal spaces as text, so a row reached the rules-table builder
as one span 401pt wide and landed whole in the 55pt column its centre fell in,
which every renderer wrapped to seven lines -- y03's page 40 spilled a page in
Google Docs and in both raw lanes. `infer._mono_space_gaps` cuts a monospaced
span where a run of its own spaces is wider than a cell gap
(RULES_CELL_GAP_EM), the same gap the parser cuts a line at when the white is
drawn rather than typed.

    python -m unittest tests.test_mono_space_columns
"""
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import infer  # noqa: E402
from exactdoc.model import Line, Span  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None


def _span(text, x0=100.0, size=10.0, adv=6.0, mono=True):
    return Span(text=text, font="Courier" if mono else "Times-Roman", size=size,
                color="#000000", bold=False, italic=False, mono=mono, serif=not mono,
                superscript=False, bbox=(x0, 700.0, x0 + adv * len(text), 710.0),
                origin=(x0, 708.0))


def _line(*spans):
    return Line(spans=list(spans), dir=(1.0, 0.0),
                bbox=(min(s.bbox[0] for s in spans), 700.0, max(s.bbox[2] for s in spans), 710.0))


class Cut(unittest.TestCase):
    def test_two_courier_spaces_are_a_column_gap(self):
        ln = _line(_span("0914dff4  14dff409  fa9ebf01"))
        out = infer._mono_space_gaps(ln)
        self.assertEqual([s.text for s in out.spans], ["0914dff4", "14dff409", "fa9ebf01"])
        # each piece at its own characters' advance
        self.assertEqual([s.bbox[0] for s in out.spans], [100.0, 160.0, 220.0])
        self.assertEqual([s.bbox[2] for s in out.spans], [148.0, 208.0, 268.0])
        self.assertTrue(all(s.font == "Courier" and s.mono for s in out.spans))
        # cut apart, the pieces are the builder's cells
        self.assertEqual(len(infer._split_at_span_gaps(out)), 3)

    def test_one_space_is_a_word_space(self):
        ln = _line(_span("603deb10 9ba35411"))
        self.assertIs(infer._mono_space_gaps(ln), ln)

    def test_a_proportional_span_is_left_alone(self):
        ln = _line(_span("Total  carried forward", mono=False, adv=4.5))
        self.assertIs(infer._mono_space_gaps(ln), ln)

    def test_the_run_must_be_wider_than_a_cell_gap(self):
        # a condensed monospace: 0.5em a character, two spaces are 1.0em --
        # under RULES_CELL_GAP_EM -- and three are 1.5em
        two = _line(_span("abc  def", adv=5.0))
        self.assertIs(infer._mono_space_gaps(two), two)
        three = infer._mono_space_gaps(_line(_span("abc   def", adv=5.0)))
        self.assertEqual([s.text for s in three.spans], ["abc", "def"])

    def test_leading_and_trailing_spaces_are_not_pieces(self):
        out = infer._mono_space_gaps(_line(_span("  10   8e6925af  ")))
        self.assertEqual([s.text for s in out.spans], ["10", "8e6925af"])
        self.assertEqual(out.spans[0].bbox[0], 112.0)
        self.assertEqual(out.spans[1].bbox[0], 142.0)      # its 8th character


def _table_pdf(path):
    """A ruled typewriter table: a header in Times, rows each ONE Courier
    string whose columns are two spaces apart, and some rows filling only
    their first and last columns."""
    W, H = 612, 792
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Roman", 11)
    c.drawString(72, H - 80, "Appendix A. Key expansion of a 128-bit key.")
    rows = [("4", "09cf4f3c  cf4f3c09  8a84eb01  01000000  8b84eb01  2b7e1516 a0fafe17"),
            ("5", "a0fafe17                                        28aed2a6 88542cb1"),
            ("6", "88542cb1                                        abf71588 23a33939"),
            ("7", "23a33939                                        09cf4f3c 2a6c7605"),
            ("8", "2a6c7605  6c76052a  50386be5  02000000  52386be5  a0fafe17 f2c295f2"),
            ("9", "f2c295f2                                        88542cb1 7a96b943")]
    top = 110
    c.setLineWidth(0.5)
    c.line(84, H - top, 528, H - top)
    c.setFont("Times-Roman", 10)
    for x, h in ((96, "i"), (125, "temp"), (184, "After"), (303, "Rcon"), (362, "XOR"),
                 (420, "w[i-Nk]"), (476, "w[i]")):
        c.drawString(x, H - (top + 14), h)
    c.line(84, H - (top + 20), 528, H - (top + 20))
    y = top + 36
    for i, row in rows:
        c.setFont("Courier", 10)
        c.drawString(97 if len(i) == 1 else 91, H - y, i)
        c.drawString(125.5, H - y, row)
        y += 16.8
    c.line(84, H - (y - 8), 528, H - (y - 8))
    c.setFont("Times-Roman", 11)
    c.drawString(72, H - (y + 20), "The table ends here and the text goes on below it.")
    c.showPage()
    c.save()
    return path


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        cls._dir = tempfile.TemporaryDirectory()
        pdf = _table_pdf(os.path.join(cls._dir.name, "keys.pdf"))
        cls.out = os.path.join(cls._dir.name, "raw.docx")
        convert(pdf, cls.out, options=RAW)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def _cells(self):
        with zipfile.ZipFile(self.out) as z:
            doc = z.read("word/document.xml").decode("utf-8")
        tbl = re.search(r"<w:tbl>.*?</w:tbl>", doc, re.S)
        self.assertIsNotNone(tbl, "the ruled rows are a table")
        return ["".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", c))
                for c in re.findall(r"<w:tc>.*?</w:tc>", tbl.group(0), re.S)]

    def test_no_cell_holds_a_whole_row(self):
        cells = self._cells()
        self.assertTrue(any("8a84eb01" in c for c in cells))
        self.assertFalse(any("09cf4f3c" in c and "8a84eb01" in c for c in cells), cells)
        self.assertFalse(any("2a6c7605" in c and "02000000" in c for c in cells), cells)

    def test_each_value_is_a_cell_of_its_own_column(self):
        cells = self._cells()
        self.assertIn("01000000", [c.strip() for c in cells])
        self.assertIn("02000000", [c.strip() for c in cells])


if __name__ == "__main__":
    unittest.main()
