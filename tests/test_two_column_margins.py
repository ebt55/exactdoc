"""General two-column right-edge inference and separated bare-digit markers.

The c2_paper2col failure mode: a full-width inset abstract supplies the only
lines wide enough for the wide-line right-margin estimate, so the inferred
content edge lands at the abstract's edge (~509pt on a 612pt page) instead of
the right column's flush edge (~551pt).  `_two_column_right_edge` recovers the
true edge from repeated column geometry alone -- no backend or fixture
conditionals -- and only ever widens content.
"""
import unittest

from exactdoc.infer import _is_marker_line, _two_column_right_edge, column_grid
from exactdoc.model import Line, Span


def _line(x0, x1, y, text="x"):
    span = Span(text=text, font="Helvetica", size=10.0, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=(x0, y - 10, x1, y),
                origin=(x0, y))
    return Line(spans=[span], bbox=(x0, y - 10, x1, y))


def _two_col_page():
    """Synthetic c2-style geometry on a 612pt page, margin_l=61.5."""
    lines = []
    y = 100.0
    # left column: starts at margin, ends well before column 2 (gutter)
    for i in range(10):
        lines.append((1, _line(61.5, 295.0, y + 14 * i)))
    # right column: second x0 cluster, flush right edge at 551
    for i in range(10):
        lines.append((1, _line(317.0, 551.0, y + 14 * i)))
    # inset abstract: wide lines that win the wide-line estimate at 509
    for i in range(4):
        lines.append((1, _line(104.0, 509.0, 40.0 + 12 * i)))
    return lines


class TwoColumnRightEdge(unittest.TestCase):
    def test_recovers_right_column_flush_edge(self):
        edge = _two_column_right_edge(_two_col_page(), 61.5, 612.0)
        self.assertIsNotNone(edge)
        self.assertAlmostEqual(edge, 551.0, delta=1.0)

    def test_single_column_page_returns_none(self):
        lines = [(1, _line(72.0, 540.0, 100.0 + 14 * i)) for i in range(12)]
        self.assertIsNone(_two_column_right_edge(lines, 72.0, 612.0))

    def test_no_gutter_no_second_column(self):
        # a mid-page x0 cluster (e.g. indented quotes) without left-column
        # lines ending before it must not be read as a second column
        lines = [(1, _line(72.0, 540.0, 100.0 + 14 * i)) for i in range(8)]
        lines += [(1, _line(300.0, 540.0, 300.0 + 14 * i)) for i in range(4)]
        self.assertIsNone(_two_column_right_edge(lines, 72.0, 612.0))

    def test_requires_repeated_flush_edge(self):
        # ragged right edges in the middle band: no flush cluster, no edge
        lines = [(1, _line(61.5, 295.0, 100.0 + 14 * i)) for i in range(6)]
        lines += [(1, _line(317.0, 400.0 + 37 * i, 100.0 + 14 * i))
                  for i in range(6)]
        self.assertIsNone(_two_column_right_edge(lines, 61.5, 612.0))


class BareDigitMarkers(unittest.TestCase):
    def test_bare_digit_is_a_marker_line(self):
        # step/badge lists number items "1".."4" with no trailing
        # punctuation; PDFium emits each as its own block (01_whitepaper p3)
        self.assertTrue(_is_marker_line(_line(60.0, 66.7, 74.7, text="1")))
        self.assertTrue(_is_marker_line(_line(60.0, 66.7, 74.7, text="42")))

    def test_wide_or_wordy_lines_are_not_markers(self):
        self.assertFalse(_is_marker_line(_line(60.0, 120.0, 74.7, text="1")))
        self.assertFalse(_is_marker_line(_line(60.0, 90.0, 74.7, text="12345")))
        self.assertFalse(_is_marker_line(_line(60.0, 90.0, 74.7, text="word")))


if __name__ == "__main__":
    unittest.main()


class NarrowLineGutterScan(unittest.TestCase):
    """Spanning lines cannot veto a real grid (the y06 class)."""

    def _page_lines(self, n_rows, spanning_every):
        lines = []
        for i in range(n_rows):
            y = 100.0 + 12 * i
            lines.append(_line(42.0, 214.0, y, text=f"col1 row {i}"))
            lines.append(_line(224.0, 396.0, y, text=f"col2 row {i}"))
            lines.append(_line(406.0, 570.0, y, text=f"col3 row {i}"))
            if i % spanning_every == 0:
                lines.append(_line(76.0, 570.0, y + 5, text="spanning note"))
        return lines

    def test_grid_with_spanning_notes_detected(self):
        # 3 spanning notes among 40 lines of columns: ~7% crossings, the
        # regime that lost every IRS 3-col page before the narrow scan
        lines = self._page_lines(40, 13)
        bands = column_grid([l.bbox for l in lines], 42.0, 570.0)
        self.assertIsNotNone(bands)
        self.assertEqual(len(bands), 3)

    def test_numeric_table_bands_held_out_by_width(self):
        # a byte-table shape: narrow cells with clean gutters, but bands
        # far below a text column's width
        lines = []
        for i in range(40):
            y = 100.0 + 12 * i
            for x0, x1 in ((42, 72), (109, 139), (196, 226), (283, 313)):
                lines.append(_line(x0, x1, y))
        self.assertIsNone(column_grid([l.bbox for l in lines], 42.0, 570.0))


if __name__ == "__main__":
    unittest.main()
