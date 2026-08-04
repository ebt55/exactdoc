"""PDFium super/subscript reattachment: the IR contract is PyMuPDF's line.

A script sits on its own baseline, so PDFium's baseline grouping gives it a
line of its own.  Measured on c2_paper2col, that turned `A. Researcher1,
B. Coauthor2` into three lines and therefore three TextBlocks, which put the
markers beyond the reach of infer._merge_row_lines' script pass -- that one
merges lines within a block.  The knock-on was structural, not cosmetic: one
marker sorted into the wrong column ahead of its real first paragraph, and the
gap the marker vacated was refilled with a synthesised space.

    python tests/test_pdfium_script_absorption.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.parse_pdfium import _Char, _build_lines  # noqa: E402


def _char(text, x0, x1, size=10.0, baseline=10.0):
    char = _Char()
    char.u = text
    char.x0, char.x1 = x0, x1
    char.y0, char.y1 = baseline - size, baseline
    char.ox, char.oy = x0, baseline
    char.size = size
    char.font = "Helvetica"
    char.flags = 0
    char.color = "#000000"
    char.gen = False
    return char


def _word(text, x0, size=10.0, baseline=10.0, advance=1.0):
    return [_char(letter, x0 + index * advance, x0 + (index + 1) * advance,
                  size=size, baseline=baseline)
            for index, letter in enumerate(text)]


class PdfiumScriptAbsorption(unittest.TestCase):
    def _authors(self, marker_x0=10.5, marker_baseline=6.0):
        """`Researcher` + a raised `1` + `,B` -- c2_paper2col's author line.

        The marker is 7pt against 10pt text and raised 4pt, which is what
        PDFium reports for that document. The trailing fragment carries no
        literal space, so any space in the result was synthesised here.
        """
        return (_word("Researcher", 0.0)
                + _word("1", marker_x0, size=7.0, baseline=marker_baseline,
                        advance=2.0)
                + _word(",B", 12.6))

    def test_superscript_rejoins_its_host_line_in_reading_order(self):
        lines = _build_lines(self._authors())
        self.assertEqual([line.text for line in lines], ["Researcher1,B"])

    def test_absorbed_marker_is_flagged_superscript(self):
        line = _build_lines(self._authors())[0]
        raised = [span for span in line.spans if span.superscript]
        self.assertEqual([span.text for span in raised], ["1"])
        # ...and the host text either side of it is not
        self.assertEqual([span.text for span in line.spans if not span.superscript],
                         ["Researcher", ",B"])

    def test_absorption_leaves_no_synthesised_space_behind(self):
        # Removing the marker leaves a 2.6pt hole between `Researcher` and `,`,
        # which is wider than SPACE_GAP_EM at 10pt: the gap heuristic refilled
        # it, giving `Researcher ,` against PyMuPDF's `Researcher1,`. The
        # marker occupying its own hole is what stops that.
        self.assertNotIn(" ", _build_lines(self._authors())[0].text)

    def test_line_baseline_stays_the_host_baseline(self):
        # Line.baseline is the FIRST span's origin, so a raised span that led
        # the line would report the script's baseline as the whole line's.
        self.assertEqual(_build_lines(self._authors())[0].baseline, 10.0)

    def test_fragment_left_of_the_host_is_refused(self):
        # Same size and baseline offset, but it would lead the line.
        chars = _word("Researcher", 10.0) + _word("1", 8.0, size=7.0,
                                                  baseline=6.0, advance=2.0)
        self.assertEqual(sorted(line.text for line in _build_lines(chars)),
                         ["1", "Researcher"])

    def test_same_size_fragment_stays_its_own_line(self):
        # A 10pt fragment against 10pt text is a line, however close it sits.
        chars = _word("Researcher", 0.0) + _word("1", 10.5, size=10.0,
                                                 baseline=6.0, advance=2.0)
        self.assertEqual(sorted(line.text for line in _build_lines(chars)),
                         ["1", "Researcher"])

    def test_fragment_outside_the_em_box_stays_its_own_line(self):
        # Raised 9pt on 10pt text is 0.9em: a separate line of small print,
        # not a script.
        chars = _word("Researcher", 0.0) + _word("1", 10.5, size=7.0,
                                                 baseline=1.0, advance=2.0)
        self.assertEqual(sorted(line.text for line in _build_lines(chars)),
                         ["1", "Researcher"])

    def test_distant_fragment_stays_its_own_line(self):
        # Beyond SCRIPT_REACH_EM of the host's last character: a footnote
        # marker belongs to the text it touches, not to the nearest line.
        chars = _word("Researcher", 0.0) + _word("1", 40.0, size=7.0,
                                                 baseline=6.0, advance=2.0)
        self.assertEqual(sorted(line.text for line in _build_lines(chars)),
                         ["1", "Researcher"])

    def test_subscript_is_absorbed_without_being_marked_superscript(self):
        chars = (_word("H", 0.0, advance=10.0)
                 + _word("2", 10.5, size=7.0, baseline=12.0, advance=2.0)
                 + _word("O", 12.6, advance=10.0))
        line = _build_lines(chars)[0]
        self.assertEqual(line.text, "H2O")
        self.assertEqual([span.superscript for span in line.spans],
                         [False, False, False])

    def test_a_wide_gap_split_is_never_undone(self):
        # One baseline row carrying a large first cell and small later cells --
        # a table row, split on purpose at LINE_SPLIT_EM. The split boundary is
        # measured against the ADJACENT characters (6pt here) while the reach
        # test uses the row's largest (30pt), so without the same-row guard the
        # second cell would be absorbed back into the first.
        chars = (_word("T", 0.0, size=30.0, advance=30.0)
                 + _word("ab", 30.0, size=6.0, advance=3.0)
                 + _word("cd", 43.0, size=6.0, advance=3.0))
        self.assertEqual([line.text for line in _build_lines(chars)],
                         ["Tab", "cd"])


if __name__ == "__main__":
    unittest.main()
