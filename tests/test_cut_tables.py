"""Tables cut by a page break (WP26).

Each case is the smallest reproduction of what the pandoc manual (y24) does at
pp. 44-46, measured on that document first:

* a booktabs table at a page's foot -- head rule, head row, mid rule, body --
  with no closing rule, because it goes on; the next page restates the head
  (LaTeX's longtable), on a verso shifted by the mirrored margins;
* a continuation table whose one indented, column-edge-ending line reads as
  right-set, and whose indent was charged twice when the table was asked
  whether its cells hold their lines.

    python tests/test_cut_tables.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import infer as I                            # noqa: E402
from exactdoc.infer import infer                           # noqa: E402
from exactdoc.layout import Cell, Para, TableEl            # noqa: E402
from exactdoc.model import DocIR, DrawCmd, Line, PageIR, Span, TextBlock  # noqa: E402

W, H = 612.0, 792.0
# y24's measured geometry: rectos 110.9-537.1, versos 74.9-501.1; the right
# column 180.2pt in; rows 14.9pt apart, 9.2pt tall
RECTO, VERSO = (110.9, 537.1), (74.9, 501.1)
RIGHT = 180.2
PITCH = 14.9


def _span(text, x0, base, size=9.0, x1=None, mono=True):
    x1 = x1 if x1 is not None else x0 + 0.56 * size * len(text)
    return Span(text, "Mono", size, "#000000", False, False, mono, False, False,
                (x0, base - 0.75 * size, x1, base + 0.27 * size), (x0, base))


def _ln(text, x0, base, x1=None, mono=True):
    s = _span(text, x0, base, x1=x1, mono=mono)
    return Line([s], s.bbox)


def _hline(x0, x1, y, w=0.55):
    return DrawCmd("stroke", "hline", (x0, y - w / 2, x1, y + w / 2), None,
                   "#000000", w, 1.0, 2)


def _union(lines):
    bb = None
    for l in lines:
        bb = l.bbox if bb is None else (min(bb[0], l.bbox[0]), min(bb[1], l.bbox[1]),
                                        max(bb[2], l.bbox[2]), max(bb[3], l.bbox[3]))
    return bb


def _page(n, blocks, drawings):
    return PageIR(number=n, width=W, height=H,
                  blocks=[TextBlock(list(b), _union(b)) for b in blocks if b],
                  drawings=list(drawings))


def _head(span, top):
    """Head rule, head row, mid rule at `top` (21pt apart, as y24's)."""
    x0, x1 = span
    lines = [_ln("command line", x0, top + 14.8, x1=x0 + 69.1, mono=False),
             _ln("defaults file", x0 + RIGHT, top + 14.8, x1=x0 + RIGHT + 56.8,
                 mono=False)]
    return lines, [_hline(x0, x1, top, 0.87), _hline(x0, x1, top + 21.0)]


def _rows(span, first_base, n, seed=0):
    x0, _ = span
    out = []
    for i in range(n):
        k = seed + i
        out.append(_ln("--option-%d value" % k, x0, first_base + PITCH * i))
        out.append(_ln("option-%d: value" % k, x0 + RIGHT, first_base + PITCH * i))
    return out


def _prose(x0, x1, base, n):
    return [_ln("Prose that is not the table's, set across the column %d." % i,
                x0, base + 12.7 * i, x1=x1, mono=False) for i in range(n)]


def _cut_document(next_opens_with_head=True, prose_under_body=False):
    # page 1 (a recto): prose, then a table cut by the page foot
    p1_text = _prose(108.0, 539.0, 80.0, 12)
    head, head_rules = _head(RECTO, 536.1)
    body = _rows(RECTO, 572.0, 10)
    if prose_under_body:
        body = body[:-4]
        p1_text += _prose(108.0, 539.0, 700.0, 1)
    p1 = _page(1, [p1_text, head, body], head_rules)
    # page 2 (a verso): the head restated, the rest of the rows, a closing
    # rule, prose after it
    blocks2, draws2 = [], []
    if next_opens_with_head:
        head2, head2_rules = _head(VERSO, 58.0)
        blocks2.append(head2)
        draws2 += head2_rules
        body2 = _rows(VERSO, 93.0, 3, seed=10)
        draws2.append(_hline(VERSO[0], VERSO[1], 93.0 + PITCH * 2 + 5.0, 0.87))
        blocks2.append(body2)
        blocks2.append(_prose(72.0, 504.0, 160.0, 20))
    else:
        blocks2.append(_prose(72.0, 504.0, 72.0, 30))
    p2 = _page(2, blocks2, draws2)
    return DocIR(path="cut.pdf", pages=[p1, p2])


def _tables(lay, page):
    return [e for ch in lay.pages[page - 1].chunks for e in ch.elements
            if isinstance(e, TableEl) and e.role == "table"]


class TableCutByThePageFoot(unittest.TestCase):
    def test_the_cut_table_is_a_table_on_its_own_page(self):
        lay = infer(_cut_document())
        tabs = _tables(lay, 1)
        self.assertEqual(len(tabs), 1)
        t = tabs[0]
        self.assertEqual(len(t.col_widths), 2)
        self.assertEqual(len(t.rows), 11)          # the head and ten rows
        self.assertIn("command line", t.rows[0][0].paras[0].text)
        # the head's two rules are its borders; the last row has none,
        # because the source draws none
        self.assertIn("top", t.rows[0][0].borders)
        self.assertIn("bottom", t.rows[0][0].borders)
        self.assertNotIn("bottom", t.rows[-1][0].borders)
        # rows that do not grow: each as tall as its pitch, the last ending
        # half a row-gap under its line
        for h in t.row_heights[2:]:
            self.assertAlmostEqual(h, PITCH, delta=0.6)
        last_line_bottom = 572.0 + PITCH * 9 + 0.27 * 9.0
        self.assertAlmostEqual(t.bbox[3], last_line_bottom + (PITCH - 9.27) / 2,
                               delta=0.6)
        # and its continuation, under the restated head, is the next page's
        tabs2 = _tables(lay, 2)
        self.assertEqual(len(tabs2), 1)
        self.assertEqual(len(tabs2[0].rows), 4)

    def test_no_restated_head_on_the_next_page_leaves_two_rules_alone(self):
        lay = infer(_cut_document(next_opens_with_head=False))
        self.assertEqual(_tables(lay, 1), [])

    def test_prose_under_the_body_is_no_cut_table(self):
        lay = infer(_cut_document(prose_under_body=True))
        self.assertEqual(_tables(lay, 1), [])

    def test_open_foot_reads_only_a_head_pair(self):
        head, rules = _head(RECTO, 536.1)
        body = _rows(RECTO, 572.0, 6)
        blocks = [TextBlock(head, _union(head)), TextBlock(body, _union(body))]
        nxt_rules = [_hline(VERSO[0], VERSO[1], 58.0)]
        sub = list(enumerate(rules))
        foot = I._open_foot(sub, blocks, set(), [], nxt_rules)
        self.assertIsNotNone(foot)
        # rules further apart than a row are no head (RULED_ROW_MAX_GAP)
        far = [(0, rules[0]), (1, _hline(RECTO[0], RECTO[1], 536.1 + 80.0))]
        self.assertIsNone(I._open_foot(far, blocks, set(), [], nxt_rules))
        # a next-page rule of another length is another table's
        short = [_hline(VERSO[0], VERSO[1] - 120.0, 58.0)]
        self.assertIsNone(I._open_foot(sub, blocks, set(), [], short))
        # a next-page rule under that page's first text is not its opening
        late = [_ln("Some heading", 72.0, 50.0, x1=200.0, mono=False)]
        self.assertIsNone(I._open_foot(sub, blocks, set(), late, nxt_rules))


class CellsHoldLines(unittest.TestCase):
    def _table(self, align):
        p = Para(align=align, left_indent=11.3)
        p.src_widths = [169.7]
        cell = Cell(paras=[p], pad=(1.2, 11.3, 2.8, 1.0))
        return TableEl(rows=[[cell]], col_widths=[183.1], row_heights=[14.9])

    def test_a_right_set_line_is_not_charged_its_indent_twice(self):
        """y24 p45: '--epub-embed-font headline.otf', 86.2-256.0 in a column
        74.9-258.0 -- indented 11.3pt and ending on the column edge."""
        self.assertTrue(I._cells_hold_lines(self._table("right")))
        self.assertTrue(I._cells_hold_lines(self._table("center")))

    def test_a_left_set_line_still_is(self):
        self.assertFalse(I._cells_hold_lines(self._table("left")))


if __name__ == "__main__":
    unittest.main()
