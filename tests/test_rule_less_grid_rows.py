"""Rows of a table drawn without rules become tabbed paragraphs.

Without rules a table reaches inference as text fragments on shared baselines.
Joined by `_merge_row_lines`, "Relief running   142,000   96,400   45,600"
became one line of prose and the figures lost their columns (x10, x13 -- and
x13's rows, then centred as a whole, moved 117-124pt). Arriving as separate
blocks, each cell became its own paragraph and the row stacked vertically
(x10's third table: +11.6pt per cell, 39pt by the second row). A row of cells
is written as a word processor writes one: tabs against stops at the source x,
right-aligned for figures.
"""
import unittest

from exactdoc.infer import infer
from exactdoc.layout import Para
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock

ROWS = [("Item", "Committed", "Drawn", "Remaining"),
        ("Relief running", "142,000", "96,400", "45,600"),
        ("Signage and information", "38,500", "38,500", "0"),
        ("Temporary lighting", "61,200", "12,050", "49,150")]
# left edge of the label, RIGHT edges of the figure columns
X_LABEL, X_RIGHT = 64.7, (358.2, 441.8, 547.8)


def _span(text, x0, base, size=10.0):
    w = 5.0 * len(text)
    return Span(text=text, font="LiberationSerif", size=size, color="#111111",
                bold=False, italic=False, mono=False, serif=True,
                superscript=False, bbox=(x0, base - 8.9, x0 + w, base + 2.2),
                origin=(x0, base))


def _row_spans(cells, base):
    out = [_span(cells[0], X_LABEL, base)]
    for t, xr in zip(cells[1:], X_RIGHT):
        out.append(_span(t, xr - 5.0 * len(t), base))
    return out


def _body(base):
    sp = Span(text="The depot replacement programme was approved on the "
              "understanding that service", font="LiberationSerif", size=11.0,
              color="#111111", bold=False, italic=False, mono=False, serif=True,
              superscript=False, bbox=(57.8, base - 9.8, 550.0, base + 2.4),
              origin=(57.8, base))
    ln = Line(spans=[sp], bbox=sp.bbox)
    return TextBlock(lines=[ln], bbox=ln.bbox)


def _page(one_line_per_row=True):
    blocks = [_body(100.0)]
    for i, cells in enumerate(ROWS):
        base = 150.0 + 22.5 * i
        spans = _row_spans(cells, base)
        if one_line_per_row:      # x13: the parser kept the row on one line
            ln = Line(spans=spans, bbox=(spans[0].bbox[0], spans[0].bbox[1],
                                         spans[-1].bbox[2], spans[0].bbox[3]))
            blocks.append(TextBlock(lines=[ln], bbox=ln.bbox))
        else:                     # x10: every cell is a block of its own
            for s in spans:
                ln = Line(spans=[s], bbox=s.bbox)
                blocks.append(TextBlock(lines=[ln], bbox=ln.bbox))
    blocks.append(_body(260.0))
    return DocIR(path="t.pdf", pages=[PageIR(1, 612.0, 792.0, blocks=blocks)])


def _paras(ir):
    lay = infer(ir)
    return [e for pg in lay.pages for ch in pg.chunks for e in ch.elements
            if isinstance(e, Para)], lay


class GridRows(unittest.TestCase):
    def _check(self, ir):
        paras, lay = _paras(ir)
        rows = [p for p in paras if p.tab_stops]
        self.assertEqual([p.text for p in rows],
                         ["\t".join(c) for c in ROWS])
        for p in rows[1:]:
            self.assertEqual([a for _, a in p.tab_stops], ["right"] * 3)
            for (pos, _a), xr in zip(p.tab_stops, X_RIGHT):
                self.assertAlmostEqual(pos + lay.margin_l, xr, delta=0.6)
            self.assertAlmostEqual(p.left_indent + lay.margin_l, X_LABEL,
                                   delta=0.6)
            self.assertEqual(p.align, "left")
        return paras

    def test_a_row_held_on_one_line(self):
        self._check(_page(one_line_per_row=True))

    def test_a_row_of_separate_blocks_is_one_paragraph_not_a_stack(self):
        paras = self._check(_page(one_line_per_row=False))
        # four rows, two body paragraphs: no stacked one-cell paragraphs
        self.assertEqual(len(paras), len(ROWS) + 2)

    def test_prose_columns_are_not_cells(self):
        # three wide fragments of prose on shared baselines: not a table
        blocks = []
        for i in range(4):
            base = 150.0 + 14.0 * i
            for x0 in (60.0, 230.0, 400.0):
                sp = Span(text="words of a running column line", font="Helvetica",
                          size=9.0, color="#000000", bold=False, italic=False,
                          mono=False, serif=False, superscript=False,
                          bbox=(x0, base - 8, x0 + 150.0, base + 2),
                          origin=(x0, base))
                ln = Line(spans=[sp], bbox=sp.bbox)
                blocks.append(TextBlock(lines=[ln], bbox=ln.bbox))
        paras, _ = _paras(DocIR(path="t.pdf",
                                pages=[PageIR(1, 612.0, 792.0, blocks=blocks)]))
        self.assertFalse(any(p.tab_stops for p in paras))

    def test_a_lone_row_needs_figures(self):
        # one row of words, no partner row: a coincidence, left alone
        blocks = [_body(100.0)]
        spans = [_span(t, x, 150.0) for t, x in
                 (("Name", 64.7), ("Date", 300.0), ("Signature", 450.0))]
        for s in spans:
            ln = Line(spans=[s], bbox=s.bbox)
            blocks.append(TextBlock(lines=[ln], bbox=ln.bbox))
        paras, _ = _paras(DocIR(path="t.pdf",
                                pages=[PageIR(1, 612.0, 792.0, blocks=blocks)]))
        self.assertFalse(any(p.tab_stops for p in paras))

    def test_figures_closer_than_a_cell_gap_keep_their_word_space(self):
        # y06's EIC tables: cells under 2em apart fall into one fragment, and
        # its figures must stay separate words ("503 2,236", not "5032,236")
        blocks = [_body(100.0)]
        for i in range(2):
            base = 150.0 + 12.0 * i
            spans = [_span("12,250", 64.7, base), _span("12,300", 130.0, base),
                     _span("503", 230.0, base), _span("2,236", 252.0, base),
                     _span("2,630", 330.0, base)]
            ln = Line(spans=spans, bbox=(64.7, base - 8.9, 355.0, base + 2.2))
            blocks.append(TextBlock(lines=[ln], bbox=ln.bbox))
        paras, _ = _paras(DocIR(path="t.pdf",
                                pages=[PageIR(1, 612.0, 792.0, blocks=blocks)]))
        rows = [p for p in paras if p.tab_stops]
        self.assertEqual(len(rows), 2)
        self.assertIn("503 2,236", rows[0].text)

    def test_exponents_in_display_maths_are_not_figures(self):
        # y43: two summation signs and their two raised 2s on one baseline
        blocks = [_body(200.0)]
        for t, x, sz in (("X+∞", 137.0, 10.0), ("X∞", 164.0, 10.0),
                         ("2", 408.0, 5.0), ("2", 434.0, 5.0)):
            s = _span(t, x, 150.0, size=sz)
            ln = Line(spans=[s], bbox=s.bbox)
            blocks.append(TextBlock(lines=[ln], bbox=ln.bbox))
        paras, _ = _paras(DocIR(path="t.pdf",
                                pages=[PageIR(1, 612.0, 792.0, blocks=blocks)]))
        self.assertFalse(any(p.tab_stops for p in paras))

    def test_a_lone_row_of_figures_continues_a_table(self):
        # x10's "March" row, alone at the top of page 2
        blocks = [_body(200.0)]
        for s in _row_spans(("March", "89.5%", "97.0%", "0.3%"), 150.0):
            ln = Line(spans=[s], bbox=s.bbox)
            blocks.append(TextBlock(lines=[ln], bbox=ln.bbox))
        paras, _ = _paras(DocIR(path="t.pdf",
                                pages=[PageIR(1, 612.0, 792.0, blocks=blocks)]))
        rows = [p for p in paras if p.tab_stops]
        self.assertEqual([p.text for p in rows], ["March\t89.5%\t97.0%\t0.3%"])


if __name__ == "__main__":
    unittest.main()
