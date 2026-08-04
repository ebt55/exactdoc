"""Vertical text is out of flow, and a widener needs something to widen.

Both are backend-parity defects that defeated the inflation guards under the
PDFium parse while leaving the PyMuPDF parse alone.

1. PDFium reports no writing direction. `_build_lines` groups by baseline, so a
   rotated margin strip shattered into dozens of 1-4 character fragments with
   interleaved text ('T', 'ihsp', 'ub', 'clia'). On NIST SP 800-207 that was
   2777 phantom body lines at x=17, which dragged the inferred left margin from
   72.0 to 16.8 -- moving the body column over the margin band, so the
   side-margin furniture guard stopped firing (66 promotable shapes -> 13) and
   the document re-inflated from ~44 to ~80 pages of emitted height.

2. `_two_column_right_edge` is documented as only ever WIDENING the content
   edge. With no wide-line estimate to widen it was adopted outright, and a
   right-column edge sits far LEFT of the page's content edge, so the rule
   inverted and narrowed instead. y17_rfc9110's line geometry is identical
   under both parsers; PyMuPDF's right edge clusters at 503.6 and PDFium's
   chains to None, after which the widener supplied 332.5 -- a 266pt content
   width against a true 438pt, which re-wraps every paragraph.
"""
import unittest

from exactdoc.infer import infer
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock
from exactdoc.parse_pdfium import (VERT_MIN_CHARS, _Char, _split_vertical_runs)

PAGE_W = 612.0


def _char(u, ox, oy, size=10.0):
    c = _Char()
    c.u = u
    c.ox, c.oy = ox, oy
    c.x0, c.y0, c.x1, c.y1 = ox, oy - size, ox + size * 0.5, oy
    c.size = size
    c.font = "Helvetica"
    c.flags = 0
    c.color = "#000000"
    c.gen = 0
    return c


def _vertical_run(text, x=18.0, y0=200.0, step=5.0):
    return [_char(u, x, y0 + i * step) for i, u in enumerate(text)]


def _horizontal_run(text, x0=72.0, y=100.0, step=6.0):
    return [_char(u, x0 + i * step, y) for i, u in enumerate(text)]


class VerticalRuns(unittest.TestCase):
    def test_a_vertical_run_leaves_the_flow_as_one_rotated_line(self):
        chars = _vertical_run("This publication is available")
        flow, rotated = _split_vertical_runs(chars)
        self.assertEqual(flow, [])
        self.assertEqual(len(rotated), 1)
        self.assertEqual(rotated[0].text, "This publication is available")

    def test_the_rotated_line_declares_a_vertical_direction(self):
        _, rotated = _split_vertical_runs(_vertical_run("available free of charge"))
        self.assertEqual(rotated[0].dir, (0.0, 1.0))
        self.assertFalse(rotated[0].horizontal)

    def test_it_reads_in_increasing_y_rather_than_stream_order(self):
        chars = _vertical_run("abcdef")[::-1]      # content-stream order reversed
        chars = chars + _vertical_run("ghijklmn", y0=230.0)
        _, rotated = _split_vertical_runs(chars)
        self.assertTrue(rotated)
        self.assertEqual(rotated[0].text[:6], "abcdef")

    def test_horizontal_text_is_untouched(self):
        chars = _horizontal_run("ordinary body text on one line")
        flow, rotated = _split_vertical_runs(chars)
        self.assertEqual(len(flow), len(chars))
        self.assertEqual(rotated, [])

    def test_a_short_stack_stays_in_flow(self):
        # a couple of stacked glyphs inside ordinary text must not be diverted
        chars = _vertical_run("ab")
        flow, rotated = _split_vertical_runs(chars)
        self.assertEqual(rotated, [])
        self.assertEqual(len(flow), 2)

    def test_the_run_length_floor_is_respected(self):
        short = _vertical_run("x" * (VERT_MIN_CHARS - 1))
        self.assertEqual(_split_vertical_runs(short)[1], [])
        long = _vertical_run("y" * VERT_MIN_CHARS)
        self.assertEqual(len(_split_vertical_runs(long)[1]), 1)

    def test_a_vertical_strip_beside_body_text_splits_cleanly(self):
        chars = _horizontal_run("body text here") + \
            _vertical_run("sidebar citation strip") + \
            _horizontal_run("more body", y=140.0)
        flow, rotated = _split_vertical_runs(chars)
        self.assertEqual(len(rotated), 1)
        self.assertNotIn("sidebar", "".join(c.u for c in flow))


def _line(x0, x1, y, text="word"):
    span = Span(text=text, font="Helvetica", size=10.0, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=(x0, y - 10, x1, y), origin=(x0, y))
    return Line(spans=[span], bbox=(x0, y - 10, x1, y))


def _narrow_two_column_page():
    """Two narrow columns on the left half: a two-column edge well left of the
    page's content edge, and no line wide enough to give a wide-line estimate."""
    lines = []
    for i in range(12):
        lines.append(_line(61.5, 200.0, 100.0 + 14 * i))
        lines.append(_line(240.0, 380.0, 100.0 + 14 * i))
    blk = TextBlock(lines=lines, bbox=(61.5, 90.0, 380.0, 260.0))
    return DocIR(path="narrow.pdf",
                 pages=[PageIR(number=1, width=PAGE_W, height=792.0,
                               blocks=[blk])])


class WidenerNeedsSomethingToWiden(unittest.TestCase):
    def test_a_two_column_edge_does_not_become_the_content_edge(self):
        lay = infer(_narrow_two_column_page())
        content_r = lay.page_w - lay.margin_r
        self.assertGreater(
            content_r, 400.0,
            "with no wide-line estimate the two-column edge must not be "
            "adopted: it sits left of the content edge and narrows the page")

    def test_it_falls_back_to_mirroring_the_left_margin(self):
        lay = infer(_narrow_two_column_page())
        self.assertAlmostEqual(lay.margin_r, lay.margin_l, delta=0.6)


if __name__ == "__main__":
    unittest.main()
