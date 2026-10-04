"""A one-line cell wider than its column spans the blank cells beside it.

x14's totals block is an indented table (322pt): "Contingency applied" drew
81.5pt from a 35pt column across the empty 54.5pt one beside it, under a rule
that runs the whole row. The width fit widened the label column, spending
"room" counted from the container's left edge that in fact lay LEFT of the
table, and the amounts landed 48-52pt in the right margin in LibreOffice and
Google Docs alike. Now the room is counted to the table's right, and the label
spans the blank cell -- what the source drew.
"""
import os
import re
import tempfile
import unittest
import zipfile

from exactdoc.docxout import (_absorbable, _fit_col_widths,
                              _span_into_blank_neighbours, write_docx)
from exactdoc.layout import Cell, Chunk, DocLayout, PageLayout, Para, Run, TableEl

RULE = (0.9, "#333333")


def _cell(text="", width=None, borders=None):
    p = Para(runs=[Run(text=text, font="Helvetica", size=8.0, color="#000000")]
             if text else [])
    if text:
        p.src_lines = 1
        p.src_widths = [width]
    return Cell(paras=[p] if text else [], pad=(4.0, 0.0, 4.0, 1.0),
                borders=dict(borders or {}))


def _totals(left_indent=322.1):
    rows = [[_cell(borders={"top": RULE}), _cell("Subtotal", 33.0, {"top": RULE}),
             _cell("43,518.00", 40.0, {"top": RULE})],
            [_cell("Contingency applied", 81.5, {"bottom": RULE}),
             _cell(borders={"bottom": RULE}),
             _cell("-6,568.00", 38.0, {"bottom": RULE})]]
    return TableEl(rows=rows, col_widths=[35.0, 54.5, 62.5],
                   row_heights=[None, None], left_indent=left_indent)


class SpanIntoBlank(unittest.TestCase):
    def test_the_label_spans_the_blank_cell_and_keeps_the_rule(self):
        t = _span_into_blank_neighbours(_totals())
        label = t.rows[1][0]
        self.assertEqual(label.col_span, 2)
        self.assertIsNone(t.rows[1][1])
        self.assertEqual(label.borders.get("bottom"), RULE)
        self.assertEqual(t.col_widths, [35.0, 54.5, 62.5])

    def test_the_layout_is_not_mutated(self):
        src = _totals()
        _span_into_blank_neighbours(src)
        self.assertEqual(src.rows[1][0].col_span, 1)
        self.assertIsNotNone(src.rows[1][1])

    def test_a_neighbour_with_text_a_fill_or_a_different_rule_is_not_absorbed(self):
        c = _cell("Contingency applied", 81.5, {"bottom": RULE})
        self.assertFalse(_absorbable(c, _cell("x", 5.0, {"bottom": RULE})))
        shaded = _cell(borders={"bottom": RULE})
        shaded.shading = "#EEEEEE"
        self.assertFalse(_absorbable(c, shaded))
        self.assertFalse(_absorbable(c, _cell(borders={})))
        self.assertFalse(_absorbable(c, _cell(borders={"bottom": RULE,
                                                       "left": RULE})))
        self.assertTrue(_absorbable(c, _cell(borders={"bottom": RULE})))

    def test_a_drawn_grid_is_left_as_drawn(self):
        t = _totals()
        t.col_edges_drawn = True
        self.assertIs(_span_into_blank_neighbours(t), t)


class RoomIsToTheRight(unittest.TestCase):
    def test_an_indented_table_does_not_grow_into_the_margin(self):
        # the source table already ends 3.9pt past the column (474.1pt); with
        # no room to its right it must not grow at all
        t = _totals()
        widths = _fit_col_widths(t, content_w=470.2)
        self.assertAlmostEqual(sum(widths), 152.0, places=3)

    def test_an_unindented_table_may_still_grow_into_free_room(self):
        t = _totals(left_indent=0.0)
        widths = _fit_col_widths(t, content_w=470.2)
        self.assertGreater(widths[0], 35.0)


class EndToEnd(unittest.TestCase):
    def test_the_written_table_stays_inside_the_column(self):
        lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[_totals()])])])
        lay.page_w, lay.margin_l, lay.margin_r = 612.0, 70.9, 70.9
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "t.docx")
            write_docx(lay, path)
            with zipfile.ZipFile(path) as z:
                doc = z.read("word/document.xml").decode("utf-8")
        grid = [int(x) for x in re.findall(r'<w:gridCol w:w="(\d+)"', doc)]
        ind = int(re.search(r'<w:tblInd w:w="(\d+)"', doc).group(1))
        self.assertLessEqual(ind + sum(grid), round((322.1 + 152.0) * 20) + 2)
        self.assertIn('<w:gridSpan w:val="2"/>', doc)


if __name__ == "__main__":
    unittest.main()
