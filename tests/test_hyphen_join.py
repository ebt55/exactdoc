"""Dehyphenation only at the wrap edge (defect catalogue #10).

A real 32-page ragged-right report lost 41 drawn hyphens through the join:
every one was text ("co-author" split across lines), none a hyphenation
break, because a ragged-right line never needs to buy width. The join now
takes the geometry verdict from the caller: a hyphen whose line reached the
column edge is a break and is dehyphenated; one on a short line is text and
is kept.
"""
import unittest

from exactdoc.infer import _soft_join, para_from_lines
from exactdoc.layout import Run
from exactdoc.model import Line, Span


def _span(text, x0, x1, y):
    return Span(text=text, font="Georgia", size=10.0, color="#000000",
                bold=False, italic=False, mono=False, serif=True,
                superscript=False, bbox=(x0, y - 10, x1, y),
                origin=(x0, y))


def _line(text, x0, x1, y):
    return Line(spans=[_span(text, x0, x1, y)], bbox=(x0, y - 10, x1, y))


def _runs(text):
    return [Run(text=text, font="Georgia", size=10.0, color="#000000",
                bold=False, italic=False, mono=False, serif=True)]


COL_R = 539.0


class SoftJoinVerdict(unittest.TestCase):
    def test_hyphen_at_wrap_edge_is_dehyphenated(self):
        r = _runs("black-")
        _soft_join(r, "box things", dehyphenate=True)
        self.assertEqual(r[0].text, "black")

    def test_real_hyphen_short_line_is_kept(self):
        r = _runs("co-")
        _soft_join(r, "author wrote", dehyphenate=False)
        self.assertEqual(r[0].text, "co-")

    def test_real_hyphen_adds_no_space_before_continuation(self):
        # the kept hyphen already separates the halves; the join must not
        # also insert a space ("co- author")
        r = _runs("co-")
        _soft_join(r, "author wrote", dehyphenate=False)
        self.assertEqual(r[0].text, "co-")
        r2 = _runs("word")
        _soft_join(r2, "next line", dehyphenate=False)
        self.assertEqual(r2[0].text, "word ")

    def test_default_verdict_preserves_old_behaviour(self):
        # every pre-existing caller that passes no verdict dehyphenates,
        # so the signature change alone moves nothing
        r = _runs("black-")
        _soft_join(r, "box things")
        self.assertEqual(r[0].text, "black")


class GeometryThreading(unittest.TestCase):
    def _two_line_para(self, top_x1, bottom_text="authors wrote it"):
        top = _line("co-", 57.0, top_x1, 100.0)
        bottom = _line(bottom_text, 57.0, 300.0, 114.0)
        return para_from_lines([top, bottom], 57.0, COL_R)

    def test_short_ragged_line_keeps_hyphen(self):
        # the line stops 44pt short of the column: the hyphen is text
        p = self._two_line_para(COL_R - 44.0)
        self.assertEqual(p.runs[0].text, "co-")
        self.assertEqual(p.runs[1].text, "authors wrote it")

    def test_line_reaching_column_dehyphenates(self):
        # the line reaches the wrap edge: the hyphen bought it width
        p = self._two_line_para(COL_R - 1.0)
        self.assertEqual(p.runs[0].text, "co")

    def test_inset_paragraph_dehyphenates_at_its_own_edge(self):
        # a justified paragraph wrapping against an inset right edge (right
        #_indent > 0) wraps there, not at col_r; a hyphenated line that
        # reaches the inset is at its wrap edge and dehyphenates
        lines = [_line("black-", 90.0, 469.0, 100.0 + 14 * i)
                 for i in range(3)]
        lines[-1] = _line("box again", 90.0, 469.0, 100.0 + 14 * 2)
        p = para_from_lines(lines, 57.0, COL_R)
        self.assertGreater(p.right_indent, 40.0)
        self.assertEqual(p.runs[0].text, "black")


if __name__ == "__main__":
    unittest.main()
