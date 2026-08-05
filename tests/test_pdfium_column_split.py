"""A page has as many columns as it has, and one gutter cannot separate three.

`_column_split` used to look for exactly two wide groups on a baseline and
return the single best-supported gutter. On y06 -- two- and three-column
throughout -- that found a gutter on 8 of 40 sampled pages, and where it did
fire on a three-column page it returned the WRONG one: the two-line rows of
that page are baselines where the middle column happens to be empty, and their
midpoint is a gutter that does not exist. Page 6 votes 14-to-4 for 308, which
sits inside the middle column, while its three-line rows agree 10-to-1 and
9-to-1 on the real gutters at 216 and 396.

The consequence downstream is the whole of parity bug B: columns that are not
separated interleave in reading order, consecutive lines stop overlapping
horizontally, and every line becomes its own block and then its own paragraph.

    python tests/test_pdfium_column_split.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.model import Line, Span                          # noqa: E402
from exactdoc.parse_pdfium import (COLUMN_MAX,                 # noqa: E402
                                   COLUMN_MEMBER_FRAC, _band_of,
                                   _build_blocks, _column_split)

# y06's geometry: content 60..589, three columns gutting at 216 and 396.
COL3 = [(60.0, 210.0), (222.0, 390.0), (402.0, 589.0)]
COL2 = [(60.0, 290.0), (310.0, 589.0)]
CONTENT_W = 529.0


def _line(x0, x1, baseline, size=10.0, text="word"):
    bbox = (x0, baseline - size, x1, baseline + 2.0)
    span = Span(text=text, font="Helvetica", size=size, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=bbox, origin=(x0, baseline))
    return Line(spans=[span], bbox=bbox)


def _rows(spans_per_row, n, top=100.0, pitch=14.0):
    """`n` baselines, each carrying one line per (x0, x1) given."""
    out = []
    for i in range(n):
        for x0, x1 in spans_per_row:
            out.append(_line(x0, x1, top + i * pitch))
    return out


class TwoColumnsAreJudgedExactlyAsBefore(unittest.TestCase):
    """The generalisation must not move the case that already worked."""

    def test_a_two_column_page_returns_its_one_gutter(self):
        self.assertEqual(_column_split(_rows(COL2, 6)), [300.0])

    def test_the_member_width_bar_at_two_columns_is_the_old_constant(self):
        # It used to read `0.25 * content_w`. Written per column it has to
        # come out at the same number, or two-column pages have been retuned.
        self.assertAlmostEqual(COLUMN_MEMBER_FRAC * CONTENT_W / 2,
                               0.25 * CONTENT_W)

    def test_a_narrow_member_is_still_refused(self):
        # The right-hand group is a quarter of the width of its column.
        rows = _rows([(60.0, 290.0), (310.0, 350.0)], 6)
        self.assertEqual(_column_split(rows), [])

    def test_two_rows_are_not_enough_evidence(self):
        self.assertEqual(_column_split(_rows(COL2, 2)), [])

    def test_a_word_space_is_not_a_gutter(self):
        rows = _rows([(60.0, 290.0), (293.0, 589.0)], 6)   # 3pt apart
        self.assertEqual(_column_split(rows), [])


class ThreeColumns(unittest.TestCase):
    def test_a_three_column_page_returns_both_gutters(self):
        self.assertEqual(_column_split(_rows(COL3, 6)), [216.0, 396.0])

    def test_the_more_numerous_two_line_rows_do_not_win(self):
        """The y06 page-6 shape, and the reason arity is not a popularity vote.

        Twelve baselines carry only the outer two columns -- the middle one is
        empty there -- and vote for 306, which is inside the middle column.
        Six carry all three and vote for the real 216 and 396.
        """
        lines = _rows([COL3[0], COL3[2]], 12, top=100.0)
        lines += _rows(COL3, 6, top=100.0 + 12 * 14.0)
        got = _column_split(lines)
        self.assertEqual(got, [216.0, 396.0])
        self.assertNotIn(306.0, got)

    def test_an_incomplete_three_column_reading_is_refused(self):
        """One gutter consistent, the other scattered, on six good rows.

        Every row is a legal three-column row -- three wide members, two real
        gaps -- but the second boundary sits somewhere different on each, so
        only the first clears the vote. Accepting that one alone would cut the
        page into two bands with the middle column's lines falling on both
        sides of the cut, which shatters it rather than assembling it. An
        N-column reading needs all N-1 of its gutters or it is not one.
        """
        lines = []
        for i, mid_end in enumerate((330.0, 340.0, 350.0, 360.0, 370.0, 380.0)):
            y = 100.0 + i * 14.0
            lines.append(_line(60.0, 210.0, y))                  # gutter 216
            lines.append(_line(222.0, mid_end, y))
            lines.append(_line(mid_end + 12.0, 589.0, y))        # scattered
        self.assertEqual(_column_split(lines), [])

    def test_the_consistent_gutter_of_that_page_really_was_acceptable(self):
        # Pins the premise: without the completeness rule, 216 alone clears
        # the vote on that page and would have been returned.
        lines = []
        for i, mid_end in enumerate((330.0, 340.0, 350.0, 360.0, 370.0, 380.0)):
            y = 100.0 + i * 14.0
            lines.append(_line(60.0, 210.0, y))
            lines.append(_line(222.0, mid_end, y))
            lines.append(_line(mid_end + 12.0, 589.0, y))
        # the same page read as two columns -- drop the third member -- does
        # return that gutter, so the refusal above is the completeness rule
        # and not a lack of evidence.
        two = [l for l in lines if l.bbox[0] in (60.0, 222.0)]
        self.assertEqual(_column_split(two), [216.0])


class TablesAreStillRefused(unittest.TestCase):
    def test_four_groups_on_a_baseline_are_not_four_columns(self):
        four = [(60.0, 190.0), (200.0, 320.0), (330.0, 450.0), (460.0, 589.0)]
        self.assertEqual(_column_split(_rows(four, 6)), [])

    def test_the_cap_is_three(self):
        self.assertEqual(COLUMN_MAX, 3)

    def test_narrow_cells_are_refused_at_three_as_well(self):
        # Three cells of 60pt on a 529pt page: each is well under half of its
        # own column, which is what tells a cell from a column.
        cells = [(60.0, 120.0), (200.0, 260.0), (400.0, 460.0)]
        self.assertEqual(_column_split(_rows(cells, 6)), [])


class Bands(unittest.TestCase):
    def test_a_boundary_belongs_to_the_left_band(self):
        # The two-column form split on `centre <= col_x`; N bands must keep it.
        self.assertEqual(_band_of(216.0, [216.0, 396.0]), 0)
        self.assertEqual(_band_of(216.1, [216.0, 396.0]), 1)
        self.assertEqual(_band_of(396.0, [216.0, 396.0]), 1)
        self.assertEqual(_band_of(500.0, [216.0, 396.0]), 2)

    def test_no_gutters_is_one_band(self):
        self.assertEqual(_band_of(300.0, []), 0)


class AgainstTheRealAssembly(unittest.TestCase):
    def test_three_interleaved_columns_no_longer_become_one_block_per_line(self):
        """The failure this exists to remove.

        Three columns of eight lines. Handed over in reading order they
        interleave, so consecutive lines never overlap horizontally and the
        pre-fix assembly made 24 blocks -- one per line. Separated into bands
        each column assembles on its own.
        """
        lines = []
        for i in range(8):
            for x0, x1 in COL3:
                lines.append(_line(x0, x1, 100.0 + i * 11.5))
        lines.sort(key=lambda l: (l.baseline, l.bbox[0]))
        blocks = _build_blocks(lines)
        self.assertLess(len(blocks), len(lines),
                        "every line became its own block again")
        self.assertGreater(max(len(b.lines) for b in blocks), 1)

    def test_a_single_column_page_is_untouched(self):
        lines = [_line(60.0, 400.0, 100.0 + i * 11.5) for i in range(10)]
        self.assertEqual(_column_split(lines), [])
        self.assertEqual(len(_build_blocks(lines)), 1)


if __name__ == "__main__":
    unittest.main()
