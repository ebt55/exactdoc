"""PDFium table-row regrouping: a row's cells belong in one block.

BLOCK_SAME_ROW_EM cannot join them -- a real table's cell gaps run to ~15em and
the constant is 1.2em -- and dialect._join_ruled_rows only repairs rows inside a
RULED band. x10_chrome_tables_plain's second table is borderless, so its 5x4
cells stayed one block each: 40 paragraphs against PyMuPDF's 16, +2 pages, and a
page-aligned word_recall of 0.4664 against 0.9963 while doc_recall held at
0.9851. The words were never lost; they moved pages.

What decides a table here is REPETITION, not width.

    python tests/test_pdfium_table_rows.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.model import Line, Span, TextBlock          # noqa: E402
from exactdoc.parse_pdfium import _group_table_rows       # noqa: E402
from exactdoc.parse_pdfium import parse_pdf as parse_pdfium  # noqa: E402

X10 = os.path.join(ROOT, "testkit", "fixtures_expansion",
                   "x10_chrome_tables_plain.pdf")


def _line(x0, x1, baseline, text="cell", size=10.0):
    bbox = (x0, baseline - size, x1, baseline + 2.0)
    span = Span(text=text, font="Helvetica", size=size, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=bbox, origin=(x0, baseline))
    return Line(spans=[span], bbox=bbox)


def _one_block_each(lines):
    """The shattered shape PDFium produces: one block per cell."""
    return [TextBlock(lines=[l], bbox=l.bbox) for l in lines]


def _grid(baselines, xs, width=40.0):
    lines = []
    for b in baselines:
        for x in xs:
            lines.append(_line(x, x + width, b))
    return lines


def _rows_in_blocks(blocks):
    """[{baselines within a block}] -- how many cells share each block."""
    out = []
    for b in blocks:
        by_base = {}
        for l in b.lines:
            by_base.setdefault(round(l.baseline, 1), []).append(l)
        out.append(max((len(v) for v in by_base.values()), default=0))
    return sorted(out, reverse=True)


class GroupsARepeatedGrid(unittest.TestCase):
    def test_borderless_table_rows_become_one_block_each(self):
        # 4 rows x 3 columns, no ruling lines anywhere.
        lines = _grid([100.0, 122.0, 144.0, 166.0], [60.0, 200.0, 340.0])
        got = _group_table_rows(_one_block_each(lines))
        self.assertEqual(len(got), 4)
        self.assertEqual(_rows_in_blocks(got), [3, 3, 3, 3])

    def test_every_cell_survives_the_regrouping(self):
        lines = _grid([100.0, 122.0, 144.0], [60.0, 200.0, 340.0])
        got = _group_table_rows(_one_block_each(lines))
        self.assertEqual(sum(len(b.lines) for b in got), len(lines))

    def test_block_bbox_covers_the_row_it_now_holds(self):
        lines = _grid([100.0, 122.0, 144.0], [60.0, 200.0, 340.0])
        got = _group_table_rows(_one_block_each(lines))
        for b in got:
            self.assertAlmostEqual(b.bbox[0], 60.0, delta=0.01)
            self.assertAlmostEqual(b.bbox[2], 380.0, delta=0.01)


class RefusesWhatIsNotATable(unittest.TestCase):
    def test_two_aligned_baselines_are_a_coincidence(self):
        # TABLE_MIN_ROWS is 3: a table repeats, and twice is not repetition.
        lines = _grid([100.0, 122.0], [60.0, 200.0, 340.0])
        blocks = _one_block_each(lines)
        self.assertEqual(len(_group_table_rows(blocks)), len(blocks))

    def test_a_two_column_page_is_not_a_table(self):
        # Each baseline carries exactly two lines and both are WIDE -- the same
        # discriminator _column_split uses for the page as a whole.
        lines = []
        for b in (100.0, 122.0, 144.0, 166.0, 188.0):
            lines.append(_line(60.0, 290.0, b))
            lines.append(_line(320.0, 550.0, b))
        blocks = _one_block_each(lines)
        self.assertEqual(len(_group_table_rows(blocks)), len(blocks))

    def test_columns_that_do_not_repeat_are_refused(self):
        # Same number of cells per row, but staggered: no column recurs.
        lines = []
        for i, b in enumerate((100.0, 122.0, 144.0, 166.0)):
            for x in (60.0 + 37 * i, 200.0 + 41 * i, 340.0 + 53 * i):
                lines.append(_line(x, x + 40.0, b))
        blocks = _one_block_each(lines)
        self.assertEqual(len(_group_table_rows(blocks)), len(blocks))

    def test_ordinary_prose_has_one_line_per_baseline(self):
        lines = [_line(60.0, 520.0, 100.0 + 15.0 * i, text="wrapped prose")
                 for i in range(12)]
        blocks = _one_block_each(lines)
        self.assertEqual(len(_group_table_rows(blocks)), len(blocks))

    def test_too_few_blocks_to_judge(self):
        blocks = _one_block_each(_grid([100.0], [60.0, 200.0]))
        self.assertEqual(len(_group_table_rows(blocks)), len(blocks))


class DoesNotDoubleGroup(unittest.TestCase):
    """A ruled table is already joined by dialect._join_ruled_rows."""

    def test_rows_already_in_one_block_are_left_alone(self):
        lines = _grid([100.0, 122.0, 144.0], [60.0, 200.0, 340.0])
        rows = [lines[0:3], lines[3:6], lines[6:9]]
        blocks = []
        for r in rows:
            bb = (min(l.bbox[0] for l in r), min(l.bbox[1] for l in r),
                  max(l.bbox[2] for l in r), max(l.bbox[3] for l in r))
            blocks.append(TextBlock(lines=list(r), bbox=bb))
        got = _group_table_rows(blocks)
        self.assertEqual(len(got), 3)
        self.assertEqual(_rows_in_blocks(got), [3, 3, 3])

    def test_regrouping_is_idempotent(self):
        lines = _grid([100.0, 122.0, 144.0, 166.0], [60.0, 200.0, 340.0])
        once = _group_table_rows(_one_block_each(lines))
        twice = _group_table_rows(once)
        self.assertEqual(len(once), len(twice))
        self.assertEqual(_rows_in_blocks(once), _rows_in_blocks(twice))


class OnTheDocumentThatFoundIt(unittest.TestCase):
    def test_x10_borderless_table_rows_are_grouped(self):
        # Table 2 spans roughly y 438..547 and has no ruling lines. Before this
        # rule every one of its cells was a block of its own.
        ir = parse_pdfium(X10, keep_image_data=False)
        page = ir.pages[0]
        grouped = 0
        for b in page.blocks:
            by_base = {}
            for l in b.lines:
                if 430 <= l.bbox[1] <= 560:
                    by_base.setdefault(round(l.baseline, 0), []).append(l)
            grouped += sum(1 for v in by_base.values() if len(v) >= 3)
        self.assertGreaterEqual(grouped, 4, "borderless rows still shattered")

    def test_x10_block_count_moves_toward_the_reference(self):
        ir = parse_pdfium(X10, keep_image_data=False)
        # 69 before this rule; the PyMuPDF reference is 22.
        self.assertLess(sum(len(p.blocks) for p in ir.pages), 45)


if __name__ == "__main__":
    unittest.main()
