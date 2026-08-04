"""A merged paragraph must describe ALL the source lines it swallowed.

`_merge_flow_paras` accumulated `_vis_lines` and forgot `src_lines`, so a
paragraph built from several blocks claimed only its first fragment's line
count: 5169 lines against 6935 on y12_irs_pub15, 4217 against 5324 on y13.

This is deliberately NOT a geometry bug. `_para_box` measures a paragraph's
height from `_vis_lines`, which did accumulate, so the emitted layout was
always right -- y12 p4's columns come out at 690pt and 702pt with 60 and 61
lines, matching the source exactly. What was wrong is what the layout SAYS
about the source, and its consumers are `ladder.py`, which compares a predicted
re-wrap against `src_lines`/`src_widths`, and the table-cell height in
`docxout`.

The invariant both counts have to satisfy is that they agree with each other
and with the lines that fed them, through every merge path.
"""
import unittest

from exactdoc.infer import _merge_flow_paras, _n_lines, infer
from exactdoc.layout import Para, Run
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock

PAGE_W, PAGE_H = 612.0, 792.0


def _para(top, n_lines, x0=72.0, x1=520.0, size=10.0, lead=11.5):
    p = Para(runs=[Run(text="word " * 8, font="Helvetica", size=size,
                       color="#000000")],
             leading=lead, bbox=(x0, top, x1, top + n_lines * lead))
    p.src_lines = n_lines
    p.src_widths = [x1 - x0] * n_lines
    p._vis_lines = n_lines
    return p


def _vis(p):
    return getattr(p, "_vis_lines", None) or _n_lines(p)


class MergeAccounting(unittest.TestCase):
    def test_merging_two_paragraphs_sums_their_source_lines(self):
        a, b = _para(100.0, 4), _para(146.0, 3)
        out = _merge_flow_paras([a, b], 520.0)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].src_lines, 7)

    def test_merging_keeps_widths_and_lines_in_step(self):
        out = _merge_flow_paras([_para(100.0, 4), _para(146.0, 3)], 520.0)
        self.assertEqual(len(out[0].src_widths), out[0].src_lines)

    def test_src_lines_tracks_vis_lines_through_a_chain(self):
        seq = [_para(100.0 + 46.0 * i, 4) for i in range(4)]
        out = _merge_flow_paras(seq, 520.0)
        for p in out:
            self.assertEqual(p.src_lines, _vis(p))

    def test_an_unmerged_paragraph_is_unchanged(self):
        a = _para(100.0, 5)
        out = _merge_flow_paras([a], 520.0)
        self.assertEqual(out[0].src_lines, 5)
        self.assertEqual(len(out[0].src_widths), 5)


def _line(x0, x1, y, text="the quick brown fox jumps over a lazy dog"):
    span = Span(text=text, font="Helvetica", size=10.0, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=(x0, y - 10, x1, y), origin=(x0, y))
    return Line(spans=[span], bbox=(x0, y - 10, x1, y))


class EndToEndInvariant(unittest.TestCase):
    """Over a whole document, the two counts must agree."""

    def _doc(self, blocks_per_page=3, lines_per_block=6):
        blocks, y = [], 60.0
        for _ in range(blocks_per_page):
            lines = [_line(72.0, 520.0, y + 11.5 * i)
                     for i in range(lines_per_block)]
            blocks.append(TextBlock(lines=lines,
                                    bbox=(72.0, y - 11.5, 520.0,
                                          y + 11.5 * lines_per_block)))
            y += 11.5 * lines_per_block + 1.0     # inside the merge gap
        return DocIR(path="acct.pdf",
                     pages=[PageIR(number=1, width=PAGE_W, height=PAGE_H,
                                   blocks=blocks)])

    def test_src_lines_equals_vis_lines_document_wide(self):
        lay = infer(self._doc())
        paras = [el for pl in lay.pages for ch in pl.chunks
                 for el in ch.elements if isinstance(el, Para)]
        self.assertTrue(paras)
        self.assertEqual(sum(p.src_lines for p in paras),
                         sum(_vis(p) for p in paras))

    def test_every_paragraph_keeps_widths_in_step(self):
        lay = infer(self._doc())
        for pl in lay.pages:
            for ch in pl.chunks:
                for el in ch.elements:
                    if isinstance(el, Para) and el.src_widths:
                        self.assertEqual(len(el.src_widths), el.src_lines,
                                         repr(el.text[:40]))


if __name__ == "__main__":
    unittest.main()
