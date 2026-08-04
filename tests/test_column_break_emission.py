"""An explicit column break is emitted only when column one will not overflow.

The break says "column one ends HERE". Measured on an isolated OOXML matrix at
y12_irs_pub15's own geometry, that is right in one case and destructive in
another:

    column 1 content   with the break          without it
    under-fills        19/66  correct          66/28  columns MERGE
    just fits          66/66                   66/66  identical
    OVERFLOWS          66/10  col 2 abandoned  66/66  degrades by lines

When column one overflows, its spill enters column two and the break then
fires FROM column two, advancing to the next page and abandoning it. That is
the whole of y12's defect: 59 source pages rendering as 114 with every second
column empty.

So the break is kept unless an overflow is predicted, the prediction is
`ladder.predict_lines`, and an unpredictable paragraph keeps the break --
the behaviour that shipped.
"""
import unittest

from exactdoc.docxout import COL_OVERFLOW_SLACK_PT, _column_one_overflows
from exactdoc.layout import Chunk, ColBreak, DocLayout, Para, Run

PAGE_H = 792.0
CONTENT_W = 528.0


def _lay(margin_t=10.0, margin_b=14.0):
    return DocLayout(page_w=612.0, page_h=PAGE_H, margin_l=42.0, margin_r=42.0,
                     margin_t=margin_t, margin_b=margin_b)


def _para(n_lines, text_per_line=44, size=10.0, lead=11.5):
    # Arial maps to a base-14 family, so predict_lines can measure it.
    p = Para(runs=[Run(text=("employment tax deposit rules apply here " * 2)
                       [:text_per_line] * n_lines,
                       font="Arial", size=size, color="#000000")],
             leading=lead)
    p.src_lines = n_lines
    return p


def _chunk(paras, n_cols=2, gap=15.5, pre_gap=0.0):
    ch = Chunk(n_cols=n_cols, col_gap=gap, pre_gap=pre_gap)
    ch.elements = list(paras) + [ColBreak(), _para(4)]
    return ch


class Predicate(unittest.TestCase):
    def test_a_short_first_column_does_not_overflow(self):
        ch = _chunk([_para(6)])
        self.assertFalse(_column_one_overflows(ch, CONTENT_W, _lay()))

    def test_a_very_long_first_column_overflows(self):
        ch = _chunk([_para(400)])
        self.assertTrue(_column_one_overflows(ch, CONTENT_W, _lay()))

    def test_a_single_column_chunk_is_never_asked(self):
        ch = _chunk([_para(400)], n_cols=1)
        self.assertFalse(_column_one_overflows(ch, CONTENT_W, _lay()))

    def test_the_pre_gap_reduces_capacity(self):
        # the same content against a column shortened by a large hoisted gap
        paras = [_para(60)]
        roomy = _column_one_overflows(_chunk(paras, pre_gap=0.0),
                                      CONTENT_W, _lay())
        tight = _column_one_overflows(_chunk(paras, pre_gap=600.0),
                                      CONTENT_W, _lay())
        self.assertFalse(roomy)
        self.assertTrue(tight)

    def test_an_unpredictable_paragraph_keeps_the_break(self):
        # Georgia has no base-14 equivalent, so predict_lines returns None and
        # the conservative answer is "no overflow", i.e. keep the break -- the
        # behaviour that shipped before any prediction existed.
        p = Para(runs=[Run(text="x " * 4000, font="Georgia", size=10.0,
                           color="#000000")], leading=11.5)
        p.src_lines = 400
        ch = Chunk(n_cols=2, col_gap=15.5)
        ch.elements = [p, ColBreak(), _para(4)]
        self.assertFalse(_column_one_overflows(ch, CONTENT_W, _lay()))

    def test_only_column_one_is_counted(self):
        # content after the break must not influence the decision
        a = _chunk([_para(6)])
        b = Chunk(n_cols=2, col_gap=15.5)
        b.elements = [_para(6), ColBreak(), _para(4000)]
        self.assertFalse(_column_one_overflows(a, CONTENT_W, _lay()))
        self.assertFalse(_column_one_overflows(b, CONTENT_W, _lay()))


class BoundaryBias(unittest.TestCase):
    """The matrix shows 'just fits' works either way, so the slack is free and
    is spent biasing toward keeping the break."""

    def test_the_slack_is_positive(self):
        self.assertGreater(COL_OVERFLOW_SLACK_PT, 0.0)

    def test_a_column_at_exactly_capacity_keeps_its_break(self):
        lay = _lay()
        capacity = lay.page_h - lay.margin_t - lay.margin_b
        n = int(capacity // 11.5)          # fills the column almost exactly
        self.assertFalse(_column_one_overflows(_chunk([_para(n)]),
                                               CONTENT_W, lay))


if __name__ == "__main__":
    unittest.main()
