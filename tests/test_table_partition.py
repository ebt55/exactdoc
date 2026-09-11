"""Table cell partition and the quote-bar paragraph form.

Defect catalogue #6: the parser joins adjacent table cells into one Line
when their gap is under its join threshold ("1 " + "v0_cand_z4js_s7"
arrived as one line), and assigning whole lines by centre put two cells'
text into one cell. Spans keep their own boxes, so the grid builder now
fragments each line at the detected column bands.

The quote-bar form: under the gdocs profile a quote table is written as
body paragraphs carrying a left border -- measured on Google's export,
every line inside a table cell rendered 1-2pt taller than source and the
block spilled its page -- with the border form the live campaign verified
(val=single sz=12 space=N colour=BBBBBB).
"""
import unittest

from exactdoc.infer import _fragments_by_column
from exactdoc.model import Line, Span


def _span(text, x0, x1, y=100.0):
    return Span(text=text, font="Consolas", size=8.0, color="#000000",
                bold=False, italic=False, mono=True, serif=False,
                superscript=False, bbox=(x0, y - 8, x1, y),
                origin=(x0, y))


COLS = [61.0, 72.0, 204.0, 252.0, 279.0, 397.0, 438.0, 495.0, 520.0]


class FragmentByColumn(unittest.TestCase):
    def test_joined_cells_split_at_bands(self):
        # the exact measured line: "1 " at 61-67 (col 0), run name at
        # 74.6-137 (col 1) -- one Line, two cells' text
        ln = Line(spans=[_span("1 ", 61.2, 66.9), _span("v0_cand_z4js_s7", 74.6, 137.2)],
                  bbox=(61.2, 92.0, 137.2, 100.0))
        frags = _fragments_by_column(ln, COLS)
        self.assertEqual(len(frags), 2)
        self.assertEqual(frags[0].text, "1 ")
        self.assertEqual(frags[1].text, "v0_cand_z4js_s7")

    def test_single_band_line_returns_itself(self):
        ln = Line(spans=[_span("CR", 398.4, 409.3)], bbox=(398.4, 92.0, 409.3, 100.0))
        frags = _fragments_by_column(ln, COLS)
        self.assertEqual(len(frags), 1)
        self.assertIs(frags[0], ln)

    def test_contiguous_same_band_spans_stay_one_fragment(self):
        ln = Line(spans=[_span("REFUSAL_", 281.5, 330.0), _span("NO_VERDICT", 330.0, 375.6)],
                  bbox=(281.5, 92.0, 375.6, 100.0))
        frags = _fragments_by_column(ln, COLS)
        self.assertEqual(len(frags), 1)
        self.assertEqual(frags[0].text, "REFUSAL_NO_VERDICT")

    def test_three_header_cells_split(self):
        ln = Line(spans=[_span("condition", 206.8, 250.0),
                         _span("rung", 254.0, 278.0),
                         _span("human (first)", 281.5, 337.3)],
                  bbox=(206.8, 92.0, 337.3, 100.0))
        frags = _fragments_by_column(ln, COLS)
        self.assertEqual([f.text for f in frags],
                         ["condition", "rung", "human (first)"])

    def test_fragments_keep_geometry(self):
        ln = Line(spans=[_span("1 ", 61.2, 66.9), _span("v0_cand", 74.6, 137.2)],
                  bbox=(61.2, 92.0, 137.2, 100.0))
        f0, f1 = _fragments_by_column(ln, COLS)
        self.assertAlmostEqual(f0.bbox[0], 61.2)
        self.assertAlmostEqual(f1.bbox[2], 137.2)
        self.assertAlmostEqual(f1.bbox[1], 92.0)


if __name__ == "__main__":
    unittest.main()
