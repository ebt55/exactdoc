"""Column inference: a line welded across a gutter, and a rule that pulled
the flow's cursor back up.

WP25. Measured with a source-to-render page map on the LibreOffice raw lane:

* y64_bls_release_xpp p8: "the U.S. Bureau of Labor Statistics (BLS). "
  (ending at x 223) and "Establishment survey" (starting at 339, an indented
  first line) share a baseline across a 295-317 gutter. The gap's midpoint
  (281) is far from the gutter's (306), so the justification exemption
  forgave it; one line ran from margin to margin and cut the column grid into
  three chunks (39 pages rendered 44).
* y64 p22/p23: a table's column-group rule (y 80) flowed after the table
  (y 67-274) and moved the spacing cursor back up, so the note under the
  table took 200-312pt of space before and left its page.
"""
import unittest

from exactdoc.infer import _position_chunks
from exactdoc.layout import (Chunk, DocLayout, FigureEl, Para, RuleEl, Run,
                             TableEl)
from exactdoc.parse_pdfium import _Char, _build_lines


# --------------------------------------------------------------- the parser
def _char(text, x0, x1, baseline):
    c = _Char()
    c.u = text
    c.x0, c.x1 = x0, x1
    c.y0, c.y1 = baseline - 10.0, baseline
    c.ox, c.oy = x0, baseline
    c.size = 10.0
    c.font = "Helvetica"
    c.flags = 0
    c.color = "#000000"
    c.gen = False
    return c


def _word(text, x0, baseline):
    return [_char(ch, x0 + i, x0 + i + 1, baseline) for i, ch in enumerate(text)]


def _row(left, l0, right, r0, baseline):
    """`left` set from l0, a literal space after it, `right` set from r0."""
    end = l0 + len(left)
    return (_word(left, l0, baseline) + [_char(" ", end, end + 1.0, baseline)]
            + _word(right, r0, baseline))


class AGapHoldingTheGutterSplits(unittest.TestCase):
    """Six column rows put the gutter's channel at x 9-30 (left lines end at
    8 after their space, right lines start at 30)."""

    def _page(self, extra):
        chars = []
        for i in range(6):
            chars += _row("leftcol", 0.0, "rightcol", 30.0, 10.0 + 20.0 * i)
        return chars + extra

    def test_short_left_line_beside_indented_right_line(self):
        # BLS's shape: the left paragraph's last line stops short (x 3) and
        # the right paragraph's first line is indented (x 45). Midpoint 24.5
        # is 5pt from the gutter's 19.5, beyond GUTTER_X_TOL; the gap still
        # holds the whole channel.
        lines = _build_lines(self._page(_row("end", 0.0, "Indented", 45.0,
                                             130.0)))
        texts = [l.text for l in lines]
        self.assertIn("end", texts)
        self.assertIn("Indented", texts)
        self.assertNotIn("end Indented", texts)

    def test_a_stretched_space_clear_of_the_channel_stays(self):
        # a justified gap of 2em inside the right column, not across the
        # gutter: the exemption still forgives it
        lines = _build_lines(self._page(_row("aaaa", 31.0, "bbbb", 56.0,
                                             130.0)))
        self.assertIn("aaaa bbbb", [l.text for l in lines])

    def test_a_ragged_column_is_measured_at_its_measure(self):
        # y61's shape: the left column's lines end anywhere from x 2 to 17,
        # so their MEDIAN end (11) stops well short of the gutter. A line
        # ending at 16 beside an indented right line is still cut: the
        # channel's left edge is the column's measure (GUTTER_CHANNEL_Q).
        chars = []
        for i, n in enumerate((1, 4, 7, 10, 13, 16)):
            chars += _row("x" * n, 0.0, "rightcol", 30.0, 10.0 + 20.0 * i)
        chars += _row("y" * 15, 0.0, "Indented", 45.0, 130.0)
        texts = [l.text for l in _build_lines(chars)]
        self.assertIn("y" * 15, texts)
        self.assertIn("Indented", texts)

    def test_preformatted_text_is_not_cut_at_a_channel(self):
        # y17's ABNF: one monospace face on both sides of the gap, an
        # alignment column rather than a gutter -- the line stays whole
        row = _row("end", 0.0, "Indented", 45.0, 130.0)
        for c in row:
            c.font = "RobotoMono-Regular"
        texts = [l.text for l in _build_lines(self._page(row))]
        self.assertNotIn("end", texts)
        self.assertTrue(any(t.startswith("end ") and t.endswith(" Indented")
                            for t in texts), texts)

    def test_no_gutter_no_channel(self):
        # one such row alone is a stretched space, as it always was
        lines = _build_lines(_row("end", 0.0, "Indented", 45.0, 10.0))
        self.assertEqual([l.text for l in lines], ["end Indented"])


# ------------------------------------------------------------ the spacing chain
class ARuleInsideTheStackedSpan(unittest.TestCase):
    def _chunks(self):
        table = TableEl(bbox=(36.0, 67.0, 575.0, 274.0))
        rule = RuleEl(width_pct=60.0, thickness=0.6, color="#000000",
                      length=363.0)
        rule._bbox = (211.6, 79.6, 575.0, 80.2)
        note = Para(runs=[Run(text="NOTE: detail will not add to totals.",
                              font="Arial", size=8.0, color="#000000")],
                    bbox=(36.0, 280.0, 543.0, 296.0))
        return [Chunk(n_cols=1, elements=[table, rule, note])], note

    def test_does_not_move_the_cursor_back_up(self):
        chunks, note = self._chunks()
        _position_chunks(chunks, DocLayout(), page_top=50.0)
        # 280 - 274: the gap under the table, not 280 - 80
        self.assertAlmostEqual(note.space_before, 6.0, places=1)

    def _after(self, first, rule_box, text_top):
        rule = RuleEl(width_pct=90.0, thickness=0.8, color="#cccccc",
                      length=463.0)
        rule._bbox = rule_box
        text = Para(runs=[Run(text="Accept = [ ( media-range", font="Courier",
                              size=9.5, color="#222222")],
                    bbox=(75.0, text_top, 500.0, text_top + 10.0))
        _position_chunks([Chunk(n_cols=1, elements=[first, rule, text])],
                         DocLayout(), page_top=50.0)
        return text

    def test_a_picture_does_not_hold_the_cursor(self):
        # y17 p174: a code panel (y 142-696) set behind its text in the
        # gdocs profile, then the rule along its top edge, then the first
        # code line at 150.9. The picture is not known to take its box in
        # the flow, so the rule moves the cursor as it always did.
        panel = FigureEl(page_no=174, clip=(65.9, 141.6, 529.4, 695.6),
                         width=463.5, height=554.0)
        text = self._after(panel, (65.9, 141.6, 529.4, 142.4), 150.9)
        self.assertAlmostEqual(text.space_before, 8.5, places=1)

    def test_a_paragraph_does_not_hold_the_cursor(self):
        # a rule drawn under a paragraph's lines, above its box's foot
        para = Para(runs=[Run(text="intro", font="Arial", size=10.0,
                              color="#000000")], bbox=(75.0, 100.0, 500.0, 130.0))
        text = self._after(para, (75.0, 120.0, 500.0, 120.8), 140.0)
        self.assertAlmostEqual(text.space_before, 19.2, places=1)

    def test_a_table_inside_the_table_is_not_held(self):
        # y59's shape: a second table set inside the first one's span is
        # stacked after it with its own height; the cursor follows it as
        # it did before WP25
        outer = TableEl(bbox=(36.0, 67.0, 575.0, 274.0))
        inner = TableEl(bbox=(300.0, 100.0, 575.0, 200.0))
        text = Para(runs=[Run(text="after", font="Arial", size=10.0,
                              color="#000000")], bbox=(36.0, 280.0, 300.0, 290.0))
        _position_chunks([Chunk(n_cols=1, elements=[outer, inner, text])],
                         DocLayout(), page_top=50.0)
        self.assertAlmostEqual(text.space_before, 80.0, places=1)

    def test_rules_inside_a_figure_just_stacked_are_held(self):
        # y21 p39: a figure (y 319-505) with three rules inside its span
        # (y 338, 386, 480), then a caption line at 502.8. Released, the
        # rules took 47.9 and 93.4pt of space before and the caption 23.8:
        # the figure's height counted twice.
        fig = FigureEl(page_no=39, clip=(65.25, 319.5, 510.25, 505.4),
                       width=445.0, height=185.9)
        rules = []
        for y in (338.6, 386.5, 479.9):
            r = RuleEl(width_pct=44.0, thickness=0.5, color="#000000",
                       length=195.0)
            r._bbox = (206.25, y, 401.25, y)
            rules.append(r)
        cap = Para(runs=[Run(text="broadening domestically.", font="Arial",
                             size=8.0, color="#000000")],
                   bbox=(130.25, 502.8, 463.6, 513.4))
        _position_chunks([Chunk(n_cols=1, elements=[fig] + rules + [cap])],
                         DocLayout(), page_top=50.0)
        self.assertEqual([r.space_before for r in rules], [0.0, 0.0, 0.0])
        self.assertLess(cap.space_before, 1.0)

    def test_a_rule_wider_than_the_figure_is_not_held(self):
        # gdocs y17 p174: the code panel's side bar stays in the flow as a
        # narrow figure; the panel's full-width top rule releases the cursor
        bar = FigureEl(page_no=174, clip=(526.6, 140.4, 531.4, 697.6),
                       width=4.8, height=557.2)
        text = self._after(bar, (65.9, 141.6, 529.4, 142.4), 150.9)
        self.assertAlmostEqual(text.space_before, 8.5, places=1)

    def test_only_a_rule_inside_the_table_is_held(self):
        # a rule that starts above the table just stacked is not inside it
        table = TableEl(bbox=(36.0, 67.0, 575.0, 274.0))
        text = self._after(table, (36.0, 60.0, 575.0, 60.8), 280.0)
        self.assertAlmostEqual(text.space_before, 219.2, places=1)


if __name__ == "__main__":
    unittest.main()
