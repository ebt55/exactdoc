"""Columns that never share a baseline still have a gutter you can see.

`_column_split` reads column structure off baselines carrying one line per
column. That is strong evidence where it exists and NO evidence where it does
not: columns set on independent vertical grids never co-occur on a baseline, so
nothing is proposed. Measured on y06, 91 of 126 pages came back empty, and on
those pages most baselines carry a single line.

`_projection_gutters` looks from the other direction -- a whitespace profile of
the page -- and is consulted only when the rows are silent. Two things make it
work where the empty-band attempt this module has warned about since did not:
a line wider than GUTTER_SPAN_FRAC of the content is excluded, because a
full-width title crossing a gutter is not evidence the gutter is absent; and
the corridor is tolerant rather than empty, because a strict white band is a
page-wide AND that one stray line closes.

    python tests/test_pdfium_gutter_profile.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.model import Line, Span                          # noqa: E402
from exactdoc.parse_pdfium import (COLUMN_MAX,                 # noqa: E402
                                   GUTTER_CROSS_FRAC, GUTTER_MIN_LINES,
                                   GUTTER_SPAN_FRAC, _build_blocks,
                                   _column_split, _projection_gutters)

# y06's geometry: content 60..589, three columns gutting at 216 and 396.
COL3 = [(60.0, 210.0), (222.0, 390.0), (402.0, 589.0)]
COL2 = [(60.0, 290.0), (310.0, 589.0)]
CONTENT_W = 529.0

# Crossing fraction measured in place over the expansion corpus: the gutters
# the row model evidences, and the centre of every column they imply.
MEASURED_CROSSING = {
    "real gutters p50": 0.008,
    "real gutters p75": 0.012,
    "column centres p50": 0.304,
}


def _line(x0, x1, baseline, size=10.0, text="word"):
    bbox = (x0, baseline - size, x1, baseline + 2.0)
    span = Span(text=text, font="Helvetica", size=size, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=bbox, origin=(x0, baseline))
    return Line(spans=[span], bbox=bbox)


def _staggered(cols, n=10, pitch=11.5):
    """Columns on INDEPENDENT vertical grids -- the shape rows cannot read.

    Each column is offset by a different fraction of the pitch, so no two
    columns ever share a rounded baseline and `_column_split` sees only
    single-line rows.
    """
    out = []
    for ci, (x0, x1) in enumerate(cols):
        for i in range(n):
            out.append(_line(x0, x1, 100.0 + ci * 3.7 + i * pitch))
    out.sort(key=lambda l: (l.baseline, l.bbox[0]))
    return out


class TheThreshold(unittest.TestCase):
    """It has to separate two measured populations, not just be a number."""

    def test_it_admits_the_gutters_the_corpus_actually_has(self):
        self.assertGreater(GUTTER_CROSS_FRAC,
                           MEASURED_CROSSING["real gutters p75"])

    def test_it_is_far_below_a_column_centre(self):
        self.assertLess(GUTTER_CROSS_FRAC * 10,
                        MEASURED_CROSSING["column centres p50"])

    def test_a_strict_empty_band_would_not_do(self):
        # 0.0 is what an empty-band test means, and it missed 31 of the 45
        # gutters the row model finds. The tolerance is the whole point.
        self.assertGreater(GUTTER_CROSS_FRAC, 0.0)

    def test_the_span_exclusion_keeps_column_lines(self):
        # A member of a two-column page is about half the content; of a
        # three-column page, about a third. Neither may be excluded as a
        # spanning element, or the profile has no evidence left.
        self.assertGreater(GUTTER_SPAN_FRAC, 0.5)
        # ...and a full-width title must be.
        self.assertLess(GUTTER_SPAN_FRAC, 1.0)


class TheRowsAreSilent(unittest.TestCase):
    def test_staggered_columns_defeat_the_row_model(self):
        # Pins the premise this function exists for.
        self.assertEqual(_column_split(_staggered(COL3)), [])
        self.assertEqual(_column_split(_staggered(COL2)), [])

    def test_the_profile_reads_three_staggered_columns(self):
        got = _projection_gutters(_staggered(COL3))
        self.assertEqual(len(got), 2)
        self.assertAlmostEqual(got[0], 216.0, delta=2.0)
        self.assertAlmostEqual(got[1], 396.0, delta=2.0)

    def test_the_profile_reads_two_staggered_columns(self):
        got = _projection_gutters(_staggered(COL2))
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got[0], 300.0, delta=2.0)


class ASpanningTitleIsNotEvidence(unittest.TestCase):
    def test_a_full_width_title_does_not_close_the_gutter(self):
        """The failure mode that sank the earlier empty-band attempt."""
        lines = _staggered(COL3)
        lines.insert(0, _line(60.0, 589.0, 80.0, size=18.0, text="A Title"))
        self.assertEqual(len(_projection_gutters(lines)), 2)

    def test_several_spanning_rules_still_do_not_close_it(self):
        lines = _staggered(COL3)
        for i in range(4):
            lines.append(_line(60.0, 589.0, 90.0 + i * 40.0, size=18.0))
        self.assertEqual(len(_projection_gutters(lines)), 2)

    def test_a_single_stray_crossing_line_does_not_close_it(self):
        """A strict white band is a page-wide AND; one line must not undo 60.

        The tolerance is a FRACTION of the page's body lines, so what counts
        as a stray depends on how much else is there -- on a 60-line page one
        crossing is 1.7% and is absorbed, on a 30-line page it is 3.3% and is
        not. That is the intended reading: on a sparse page a single crossing
        line really is a meaningful share of the evidence.
        """
        lines = _staggered(COL3, n=20)
        lines.append(_line(200.0, 410.0, 95.0))     # narrow enough to count
        self.assertEqual(len(_projection_gutters(lines)), 2)

    def test_but_a_run_of_crossing_lines_does(self):
        # Tolerant is not blind: if the text really runs across the corridor,
        # there is no corridor. These are narrow enough not to be excluded as
        # spanning, so they are counted rather than ignored.
        lines = _staggered(COL2, n=20)
        lines += [_line(250.0, 350.0, 100.0 + i * 11.5) for i in range(20)]
        self.assertEqual(_projection_gutters(lines), [])


class Stage2RulesStillApply(unittest.TestCase):
    def test_a_word_gap_inside_a_line_cannot_open_a_gutter(self):
        # Lines project as SOLID intervals; a justified paragraph's internal
        # spacing is not white space in this sense.
        lines = [_line(60.0, 589.0, 100.0 + i * 11.5) for i in range(20)]
        self.assertEqual(_projection_gutters(lines), [])

    def test_a_ragged_right_margin_is_not_a_gutter(self):
        # There is no content to the right of it.
        lines = [_line(60.0, 300.0 + (i % 5) * 8.0, 100.0 + i * 11.5)
                 for i in range(20)]
        self.assertEqual(_projection_gutters(lines), [])

    def test_nothing_wider_than_column_max_is_proposed(self):
        four = [(60.0, 190.0), (200.0, 320.0), (330.0, 450.0), (460.0, 589.0)]
        self.assertEqual(_projection_gutters(_staggered(four)), [])
        self.assertEqual(COLUMN_MAX, 3)

    def test_a_column_needs_more_than_two_lines(self):
        thin = _staggered(COL2, n=GUTTER_MIN_LINES - 1)
        self.assertEqual(_projection_gutters(thin), [])

    def test_narrow_cells_are_refused(self):
        cells = [(60.0, 120.0), (200.0, 260.0), (400.0, 460.0)]
        self.assertEqual(_projection_gutters(_staggered(cells)), [])


class TheRowModelWins(unittest.TestCase):
    """Requirement: supplement, never replace. A page the rows can read must
    not be able to move."""

    def test_build_blocks_prefers_the_row_answer(self):
        # Baseline-aligned two-column page: the rows evidence 300.0, and that
        # is what assembly must use even though a profile would also fire.
        rows = []
        for i in range(8):
            for x0, x1 in COL2:
                rows.append(_line(x0, x1, 100.0 + i * 14.0))
        self.assertEqual(_column_split(rows), [300.0])
        blocks = _build_blocks(rows)
        self.assertLess(len(blocks), len(rows))

    def test_a_staggered_page_no_longer_shatters(self):
        lines = _staggered(COL3, n=8)
        blocks = _build_blocks(lines)
        self.assertLess(len(blocks), len(lines),
                        "every line became its own block again")
        self.assertGreater(max(len(b.lines) for b in blocks), 1)

    def test_a_single_column_page_is_untouched(self):
        lines = [_line(60.0, 500.0, 100.0 + i * 11.5) for i in range(10)]
        self.assertEqual(_projection_gutters(lines), [])
        self.assertEqual(len(_build_blocks(lines)), 1)


if __name__ == "__main__":
    unittest.main()
