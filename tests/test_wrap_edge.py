"""The column is at least as wide as the lines that wrapped in it.

`_margin_cluster` takes the rightmost cluster holding 8% of the wide lines, and
a ragged-right document does not put 8% of its lines at any one x: on
x05_lo_quotes_notes it put the content edge at 529.0 while a wrapped line ends
at 547.2 (LibreOffice's text area ends at 546.9), on x02_lo_report_toc at 535.1
against 541.1. Every such paragraph re-wrapped a line longer in the render.

Also here: a rule edge is in the text when right-aligned FIELDS reach it on more
than one page (x17's dates under its section rules), not only when wide lines
do -- and not when the only text there is one cover page's masthead (EUR-Lex).
"""
import unittest

from exactdoc.infer import _rule_right_edge, _wrapped_right_edge, infer
from exactdoc.model import DocIR, DrawCmd, Line, PageIR, Span, TextBlock

PAGE_W = 612.0
WORDS = "the depot replacement programme was approved on the understanding"


def _line(x0, x1, base, text=WORDS, mono=False, size=11.0):
    sp = Span(text=text, font="LiberationSerif", size=size, color="#000000",
              bold=False, italic=False, mono=mono, serif=True,
              superscript=False, bbox=(x0, base - 9.8, x1, base + 2.4),
              origin=(x0, base))
    return Line(spans=[sp], bbox=sp.bbox)


def _para(ends, base, x0=65.0, last=300.0, mono=False):
    lines = [_line(x0, e, base + 14.5 * i, mono=mono) for i, e in enumerate(ends)]
    lines.append(_line(x0, last, base + 14.5 * len(ends), mono=mono))
    return TextBlock(lines=lines, bbox=(x0, lines[0].bbox[1],
                                        max(l.bbox[2] for l in lines),
                                        lines[-1].bbox[3]))


def _hf(n=1):
    return {"consumed_text": {i: set() for i in range(1, n + 1)},
            "consumed_draw": {i: set() for i in range(1, n + 1)},
            "rep_lines": {}, "rep_draws": {}, "line_roles": {},
            "band_first": []}


def _ragged_doc():
    # the cluster lands at 529 (most wrapped lines stop there); the widest
    # wrapped line reaches 547.2
    blocks = [_para([529.0, 529.2, 528.8], 100.0),
              _para([529.1, 541.1, 529.0], 170.0),
              _para([547.2, 529.0, 528.9], 240.0),
              _para([534.9, 529.1, 529.0], 310.0)]
    return DocIR(path="t.pdf", pages=[PageIR(1, PAGE_W, 792.0, blocks=blocks)])


class WrappedEdge(unittest.TestCase):
    def test_the_widest_wrapped_line_bounds_the_column(self):
        self.assertAlmostEqual(_wrapped_right_edge(_ragged_doc(), _hf(), PAGE_W),
                               547.2, delta=0.01)

    def test_infer_widens_to_the_mirrored_margin(self):
        lay = infer(_ragged_doc())
        # 612 - 65 = 547 lies within 8pt of 547.2? no -- it is 0.2 SHORT, so
        # the widest line itself (plus 0.5) is the edge
        self.assertGreaterEqual(lay.page_w - lay.margin_r, 547.2)
        self.assertLess(lay.page_w - lay.margin_r, 548.0)

    def test_code_lines_are_not_wraps(self):
        blocks = [_para([600.0 - 14.5, 580.0, 590.0], 100.0 + 70 * i, mono=True)
                  for i in range(3)]
        ir = DocIR(path="t.pdf", pages=[PageIR(1, PAGE_W, 792.0, blocks=blocks)])
        self.assertIsNone(_wrapped_right_edge(ir, _hf(), PAGE_W))

    def test_one_overfull_line_does_not_set_the_column(self):
        # TeX lets an unbreakable line run out past the measure; among 60
        # wrapped lines one such outlier is above the 98th percentile
        blocks = [_para([500.0, 500.4, 499.8], 60.0 + 58.0 * i) for i in range(20)]
        blocks[7] = _para([500.0, 575.0, 499.8], 60.0 + 58.0 * 7)
        ir = DocIR(path="t.pdf", pages=[PageIR(1, PAGE_W, 1600.0, blocks=blocks)])
        self.assertAlmostEqual(_wrapped_right_edge(ir, _hf(), PAGE_W), 500.4,
                               delta=0.01)

    def test_a_nested_line_is_not_a_continuation(self):
        # the next line starts further right: a sub-item, not a wrap
        b = _para([547.2], 100.0)
        b.lines[1] = _line(95.0, 300.0, b.lines[1].baseline)
        ir = DocIR(path="t.pdf", pages=[PageIR(1, PAGE_W, 792.0, blocks=[b] * 1)])
        self.assertIsNone(_wrapped_right_edge(ir, _hf(), PAGE_W))


def _hline(x0, x1, y):
    return DrawCmd(kind="stroke", shape="hline", bbox=(x0, y, x1, y + 0.75),
                   fill=None, stroke="#444444", width=0.75, opacity=1.0,
                   n_items=1)


class RuleEdgeFields(unittest.TestCase):
    def _ir(self, pages):
        return DocIR(path="t.pdf", pages=[
            PageIR(n, 595.0, 842.0, blocks=[], drawings=[
                _hline(43.5, 552.8, 90.0 + 60 * k) for k in range(3)])
            for n in range(1, pages + 1)])

    WIDE = [530.0, 529.0, 541.3, 517.9] * 4          # ragged prose, p90 ~541

    @staticmethod
    def _prose(pages):
        """Wide prose lines from y=110 to y=300 on each page."""
        return [(pg, (43.5, y, 530.0, y + 10.0)) for pg in pages
                for y in (110.0, 200.0, 290.0)]

    def test_right_aligned_fields_on_two_pages_put_the_edge_in_the_text(self):
        fields = [(1, (505.5, 170.0, 552.3, 178.0)),   # x17's dates, mid-page
                  (1, (505.5, 256.0, 552.3, 264.0)),
                  (2, (505.5, 250.0, 552.3, 258.0))]
        edge = _rule_right_edge(self._ir(2), _hf(2), 595.0, self.WIDE,
                                body_boxes=self._prose((1, 2)) + fields)
        self.assertAlmostEqual(edge, 552.8, delta=0.5)

    def test_one_cover_page_masthead_is_not_evidence(self):
        masthead = [(1, (513.6, 150.0, 552.6, 158.0))] * 3
        self.assertIsNone(_rule_right_edge(self._ir(3), _hf(3), 595.0,
                                           self.WIDE,
                                           body_boxes=self._prose((1, 2, 3)) + masthead))

    def test_page_furniture_below_the_prose_is_not_evidence(self):
        # an RFC's "Page N", at the foot of every page, outside its prose
        footers = [(pg, (511.5, 760.0, 552.6, 768.0)) for pg in (1, 2, 3)]
        self.assertIsNone(_rule_right_edge(self._ir(3), _hf(3), 595.0,
                                           self.WIDE,
                                           body_boxes=self._prose((1, 2, 3)) + footers))


if __name__ == "__main__":
    unittest.main()
