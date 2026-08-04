"""Focused contracts for PDFium's same-baseline wide-gap reconstruction.

    python tests/test_pdfium_line_splitting.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.parse_pdfium import _Char, _build_lines  # noqa: E402


def _char(text, x0, x1, generated=False, baseline=10.0):
    char = _Char()
    char.u = text
    char.x0, char.x1 = x0, x1
    char.y0, char.y1 = baseline - 10.0, baseline
    char.ox, char.oy = x0, baseline
    char.size = 10.0
    char.font = "Helvetica"
    char.flags = 0
    char.color = "#000000"
    char.gen = generated
    return char


def _word(text, x0):
    return [_char(letter, x0 + index, x0 + index + 1)
            for index, letter in enumerate(text)]


class PdfiumWideGapLineSplitting(unittest.TestCase):
    def test_stretched_literal_interword_space_stays_on_one_line(self):
        # The 18pt gap after the literal space is 1.8em: ordinary wide-gap
        # logic would split it, but it is a justified prose line.
        chars = _word("left", 0.0) + [_char(" ", 4.0, 5.0)] + _word("right", 23.0)
        lines = _build_lines(chars)
        self.assertEqual([line.text for line in lines], ["left right"])

    def test_equivalent_generated_space_keeps_wide_gap_split(self):
        chars = (_word("left", 0.0) + [_char(" ", 4.0, 5.0, generated=True)]
                 + _word("right", 23.0))
        lines = _build_lines(chars)
        self.assertEqual([line.text for line in lines], ["left", "right"])

    def test_leading_literal_space_keeps_wide_gap_split(self):
        chars = [_char(" ", 0.0, 1.0)] + _word("code", 19.0)
        lines = _build_lines(chars)
        # The whitespace-only fragment is discarded as before, while the code
        # fragment keeps its original x position instead of being merged left.
        self.assertEqual([line.text for line in lines], ["code"])
        self.assertEqual(lines[0].bbox[0], 19.0)


class TheExemptionIsBoundedByPageRepetition(unittest.TestCase):
    """A gap position that recurs down a page is a gutter, not stretched space.

    The exemption above was unbounded, so on a dense multi-column booklet -- the
    producer emits a real space at the end of every column line -- it forgave
    the gutter too and joined column 2's prose to column 3's mid-sentence: 947
    of y13_irs_pub501's 4499 lines, 21%, against PyMuPDF's zero.

    No em-threshold separates the two: y13's gutters are 1.26em and
    01_whitepaper's legitimate justified gaps are 1.73em. Repetition does.
    Measured, exempted gaps clustered by x per page: 01 has 9 exemptions on one
    page and its largest cluster is ONE; y13 has clusters of 54, 27, 20, 20.
    """

    def _column_page(self, rows, gap=23.0):
        """`rows` lines of `left<space><gap>right`, all at the same gutter x."""
        chars = []
        for i in range(rows):
            y = 10.0 + 20.0 * i
            chars += [_char(c.u if hasattr(c, "u") else c, 0, 0) for c in []]
            for j, letter in enumerate("left"):
                chars.append(_char(letter, j, j + 1, baseline=y))
            chars.append(_char(" ", 4.0, 5.0, baseline=y))
            for j, letter in enumerate("right"):
                chars.append(_char(letter, gap + j, gap + j + 1, baseline=y))
        return chars

    def test_a_repeated_gap_position_splits(self):
        lines = _build_lines(self._column_page(6))
        self.assertEqual(len(lines), 12)
        self.assertEqual(sorted({l.text for l in lines}), ["left", "right"])

    def test_a_single_stretched_space_still_does_not_split(self):
        # One row: no repetition, so the exemption stands -- this is the
        # original contract and the reason the bound is repetition-based.
        lines = _build_lines(self._column_page(1))
        self.assertEqual([l.text for l in lines], ["left right"])

    def test_below_the_repetition_bound_the_exemption_survives(self):
        # Three rows is under GUTTER_MIN_ROWS; 01_whitepaper's nine legitimate
        # justified gaps never cluster beyond one.
        lines = _build_lines(self._column_page(3))
        self.assertEqual([l.text for l in lines], ["left right"] * 3)

    def test_gaps_at_scattered_x_are_not_a_gutter(self):
        # Same number of wide gaps, but each at its own x -- 01's shape.
        chars = []
        for i in range(8):
            y = 10.0 + 20.0 * i
            for j, letter in enumerate("left"):
                chars.append(_char(letter, j, j + 1, baseline=y))
            chars.append(_char(" ", 4.0, 5.0, baseline=y))
            start = 23.0 + 9.0 * i          # wanders, as a word space does
            for j, letter in enumerate("right"):
                chars.append(_char(letter, start + j, start + j + 1, baseline=y))
        self.assertEqual([l.text for l in _build_lines(chars)],
                         ["left right"] * 8)


if __name__ == "__main__":
    unittest.main()
