"""Focused contracts for PDFium's same-baseline wide-gap reconstruction.

    python tests/test_pdfium_line_splitting.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.parse_pdfium import _Char, _build_lines  # noqa: E402


def _char(text, x0, x1, generated=False):
    char = _Char()
    char.u = text
    char.x0, char.x1 = x0, x1
    char.y0, char.y1 = 0.0, 10.0
    char.ox, char.oy = x0, 10.0
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


if __name__ == "__main__":
    unittest.main()
