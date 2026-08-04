"""PDFium list markers: a marker and its item are two lines on one baseline.

That is what PyMuPDF reports -- on x03_lo_lists_nested, `1.` at x[64.90, 73.15]
and `Establish the temporary layover` at x[82.90, 222.97], both on baseline
442.55 -- and infer._merge_list_markers is written against exactly that shape.
PDFium reported one merged line because the 9.75pt gap is under LINE_SPLIT_EM
(1.10em = 12.1pt here), so the wide-gap rule never saw it.

This is a different question from the wide-gap rule and is a separate test file
for the same reason it is a separate function: that one is about interword
spacing, this one is about a specific leading token.

    python tests/test_pdfium_list_markers.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.parse_pdfium import _Char, _build_lines      # noqa: E402
from exactdoc.parse_pdfium import parse_pdf as parse_pdfium  # noqa: E402

X03 = os.path.join(ROOT, "testkit", "fixtures_expansion",
                   "x03_lo_lists_nested.pdf")


def _char(text, x0, x1, size=11.0, baseline=100.0, generated=False):
    char = _Char()
    char.u = text
    char.x0, char.x1 = x0, x1
    char.y0, char.y1 = baseline - size, baseline
    char.ox, char.oy = x0, baseline
    char.size = size
    char.font = "Helvetica"
    char.flags = 0
    char.color = "#000000"
    char.gen = generated
    return char


def _run(text, x0, advance=2.75, size=11.0, baseline=100.0):
    return [_char(ch, x0 + i * advance, x0 + (i + 1) * advance,
                  size=size, baseline=baseline)
            for i, ch in enumerate(text)]


class SplitsAMarkerFromItsItem(unittest.TestCase):
    def test_numbered_marker_becomes_its_own_line(self):
        # x03's real geometry: `1.` 64.90-73.15, item starts 82.90.
        chars = (_run("1.", 64.90, advance=4.125)
                 + _run("Establish the bay", 82.90))
        self.assertEqual([l.text for l in _build_lines(chars)],
                         ["1.", "Establish the bay"])

    def test_both_lines_share_the_baseline(self):
        chars = _run("1.", 64.90, advance=4.125) + _run("Establish", 82.90)
        lines = _build_lines(chars)
        self.assertEqual(len({round(l.baseline, 2) for l in lines}), 1)

    def test_a_generated_space_after_the_marker_does_not_hide_the_gap(self):
        # PDFium synthesises a space after `1.`; measuring the gap from ITS end
        # instead of the marker's ink missed the split by a quarter point.
        chars = (_run("1.", 64.90, advance=4.125)
                 + [_char(" ", 73.15, 76.25, generated=True)]
                 + _run("Establish", 82.90))
        self.assertEqual([l.text for l in _build_lines(chars)],
                         ["1.", "Establish"])

    def test_bullet_and_lettered_and_parenthesised_markers(self):
        for marker in ("•", "a.", "iv.", "(2)", "3)"):
            width = 4.125 * len(marker)
            chars = (_run(marker, 64.90, advance=4.125)
                     + _run("item text", 64.90 + width + 9.75))
            self.assertEqual([l.text for l in _build_lines(chars)],
                             [marker, "item text"], marker)


class RefusesWhatIsNotAMarker(unittest.TestCase):
    def test_an_ordinary_short_first_word_does_not_split(self):
        # `The` is not marker vocabulary, and its trailing space is ordinary.
        chars = _run("The", 64.90) + _run("depot programme", 64.90 + 8.25 + 3.1)
        self.assertEqual(len(_build_lines(chars)), 1)

    def test_a_short_word_with_a_wide_gap_still_does_not_split(self):
        # Vocabulary is the gate, not the gap.
        chars = _run("of", 64.90) + _run("something", 64.90 + 5.5 + 9.75)
        self.assertEqual(len(_build_lines(chars)), 1)

    def test_a_hanging_indent_continuation_has_no_marker_to_match(self):
        chars = _run("continued text of the item", 82.90)
        self.assertEqual(len(_build_lines(chars)), 1)

    def test_a_marker_hugging_its_item_is_not_split(self):
        # An ordinary interword space: no structural separation, no split.
        chars = _run("1.", 64.90, advance=4.125) + _run("Establish", 76.25)
        self.assertEqual(len(_build_lines(chars)), 1)

    def test_a_number_mid_line_is_not_a_marker(self):
        # `fragment` is everything since the last split, so `2.` here is
        # preceded by text and never reaches the vocabulary test alone.
        chars = _run("see 2.", 64.90) + _run("below", 64.90 + 16.5 + 9.75)
        self.assertEqual(len(_build_lines(chars)), 1)

    def test_only_the_first_marker_on_a_row_can_split(self):
        # A later `2.` inside the item is content, not a second marker. Gaps
        # are kept under LINE_SPLIT_EM so the wide-gap rule stays out of it.
        chars = (_run("1.", 64.90, advance=4.125)      # marker
                 + _run("step", 82.90)                  # item starts here
                 + _run("2.", 100.0, advance=4.125)     # inside the item
                 + _run("again", 118.0))
        lines = _build_lines(chars)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].text, "1.")
        self.assertEqual(lines[1].text.split(), ["step", "2.", "again"])


class OnTheDocumentThatFoundIt(unittest.TestCase):
    def test_x03_numbered_markers_are_separate_lines(self):
        ir = parse_pdfium(X03, keep_image_data=False)
        markers = [l.text for p in ir.pages for b in p.blocks for l in b.lines
                   if l.text.strip() in ("1.", "2.", "3.")]
        self.assertGreaterEqual(len(markers), 6)

    def test_x03_marker_geometry_matches_the_reference(self):
        ir = parse_pdfium(X03, keep_image_data=False)
        hit = [l for p in ir.pages for b in p.blocks for l in b.lines
               if l.text.strip() == "1." and abs(l.baseline - 442.55) < 0.5]
        self.assertEqual(len(hit), 1)
        self.assertAlmostEqual(hit[0].bbox[0], 64.90, delta=0.1)
        self.assertAlmostEqual(hit[0].bbox[2], 73.15, delta=0.1)


if __name__ == "__main__":
    unittest.main()
