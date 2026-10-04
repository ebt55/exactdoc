"""A column of short labels beside a column of right-hand fields is not two columns.

x11_chrome_toc_headings is a plain single-column report. Its contents entries
put page numbers against the right margin, which -- once the page-number lines
read as narrow blocks at x=502 -- satisfied every test the two-column detector
asked: a left cluster at the margin, a right cluster past 35% of the width, more
than 60pt of text in each. Nothing asked whether the white between them was a
gutter. It was 238pt: the headings were poured into column one, the body
paragraphs (which cross the split) into a single-column tail beneath, and the
page rendered as two. Every genuine two-column chunk in both corpora has a
gutter of at most 0.234 of the content width; x11's was 0.485.
"""
import unittest

from exactdoc.infer import MAX_GUTTER_FRAC, _prose_between, infer
from exactdoc.layout import Para
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock

PAGE_W, PAGE_H = 612.0, 792.0


def _blk(text, x0, x1, base, size=11.0):
    sp = Span(text=text, font="LiberationSerif", size=size, color="#111111",
              bold=False, italic=False, mono=False, serif=True,
              superscript=False, bbox=(x0, base - 9.8, x1, base + 2.4),
              origin=(x0, base))
    ln = Line(spans=[sp], bbox=sp.bbox)
    return TextBlock(lines=[ln], bbox=ln.bbox)


def _report_with_right_fields():
    """Headings and short labels at the margin, page numbers against the
    right edge, full-width body paragraphs in between."""
    blocks, y = [], 90.0
    for k in range(3):
        blocks.append(_blk("Section heading %d" % k, 58.0, 170.0, y, 13.5))
        y += 22.0
        for i in range(4):                    # a contents-like run of rows
            blocks.append(_blk("Entry %d.%d" % (k, i), 58.0, 130.0, y))
            blocks.append(_blk(str(k + i), 549.0, 554.5, y))
            y += 19.6
        for i in range(4):                    # a body paragraph crossing it
            blocks.append(_blk("The depot replacement programme was approved "
                               "on the understanding that service levels",
                               58.0, 550.0, y))
            y += 15.8
        y += 14.0
    return DocIR(path="t.pdf", pages=[PageIR(1, PAGE_W, PAGE_H, blocks=blocks)])


def _true_two_columns():
    blocks = []
    for x0, x1 in ((72.0, 300.0), (312.0, 540.0)):
        for b in range(3):
            lines = []
            for i in range(5):
                base = 110.0 + 80.0 * b + 14.0 * i
                sp = Span(text="the quick brown fox jumps over a lazy dog",
                          font="Helvetica", size=10.0, color="#000000",
                          bold=False, italic=False, mono=False, serif=False,
                          superscript=False, bbox=(x0, base - 10, x1, base),
                          origin=(x0, base))
                lines.append(Line(spans=[sp], bbox=sp.bbox))
            blocks.append(TextBlock(lines=lines, bbox=(x0, lines[0].bbox[1],
                                                       x1, lines[-1].bbox[3])))
    return DocIR(path="t.pdf", pages=[PageIR(1, PAGE_W, PAGE_H, blocks=blocks)])


class ProseBetween(unittest.TestCase):
    """The guard needs the page's prose across the gap, not just a wide gap.

    y37's PLOS tables leave their stub and last columns either side of the
    detected table; the gap is 0.437 of the content but nothing between the
    "columns" is prose, and single-column layout stacked every label over its
    figure (+4 pages). Only text blocks lying within the columns' own vertical
    span count.
    """

    def test_a_table_across_the_gap_is_not_prose(self):
        cols = [("blk", (200.0, 195.0, 252.0, 416.0), None),
                ("blk", (524.0, 195.0, 556.0, 416.0), None)]
        table = [("el", (263.0, 193.0, 523.0, 418.0), None)]
        self.assertFalse(_prose_between(table, cols))

    def test_paragraphs_between_the_items_are(self):
        cols = [("blk", (58.0, 179.0, 170.0, 194.0), None),
                ("blk", (549.0, 203.0, 554.5, 333.0), None),
                ("blk", (58.0, 670.0, 242.0, 682.0), None)]
        body = [("blk", (58.0, 377.0, 549.0, 420.0), None)]
        self.assertTrue(_prose_between(body, cols))

    def test_prose_only_above_or_below_is_a_lead_or_tail(self):
        cols = [("blk", (72.0, 200.0, 300.0, 600.0), None),
                ("blk", (312.0, 200.0, 540.0, 600.0), None)]
        lead = [("blk", (72.0, 100.0, 540.0, 150.0), None)]
        self.assertFalse(_prose_between(lead, cols))


class LabelFieldPage(unittest.TestCase):
    def test_stays_one_column_in_reading_order(self):
        lay = infer(_report_with_right_fields())
        chunks = [ch for pg in lay.pages for ch in pg.chunks]
        self.assertTrue(all(ch.n_cols == 1 for ch in chunks))
        paras = [e for ch in chunks for e in ch.elements if isinstance(e, Para)]
        tops = [p.bbox[1] for p in paras]
        self.assertEqual(tops, sorted(tops), "elements must keep page order")

    def test_genuine_two_columns_still_split(self):
        lay = infer(_true_two_columns())
        chunks = [ch for pg in lay.pages for ch in pg.chunks]
        two = [ch for ch in chunks if ch.n_cols == 2]
        self.assertTrue(two)
        self.assertLess(two[0].col_gap, MAX_GUTTER_FRAC * lay.content_w)


if __name__ == "__main__":
    unittest.main()
