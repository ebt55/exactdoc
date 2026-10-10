"""A full-bleed background picture leaves the flow under Google Docs too (WP27b).

y33 (Kofax Power PDF) sets its cover on three full-bleed strips (594.8 x
280.6pt on 595.2pt paper) and its "How to have your say" pages on a tinted
panel (594.0pt wide). The gdocs profile's `anchor_pictures` capability left a
picture the text is set on in the flow, so each strip or panel stood a page of
picture before its text: live Docs 65 pages for 60, onset p2. Anchored behind
the text at its page position (probe wp27bg), live Docs read 60 for 60.

    python tests/test_page_backgrounds.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.infer import infer                                     # noqa: E402
from exactdoc.layout import ImageEl                                  # noqa: E402
from exactdoc.model import DocIR, ImageObj, Line, PageIR, Span, TextBlock  # noqa: E402

W, H = 595.2, 842.0
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
       b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")


def _line(text, x0, base, size=11.0, x1=None):
    x1 = x1 if x1 is not None else x0 + 0.48 * size * len(text)
    s = Span(text, "Calibri", size, "#000000", False, False, False, False, False,
             (x0, base - 0.95 * size, x1, base + 0.27 * size), (x0, base))
    return Line([s], s.bbox)


def _page(pic_bbox):
    lines = [_line("How to have your say", 72.0, 120.0, size=13.0)] + \
        [_line("submission text line %d about the proposals in this paper" % i,
               72.0, 160.0 + 15.5 * i, x1=520.0) for i in range(30)]
    blocks = [TextBlock(lines, (72.0, 107.0, 520.0, 613.0))]
    im = ImageObj(bbox=pic_bbox, xref=7, width=100, height=100, data=PNG, ext="png")
    return PageIR(number=1, width=W, height=H, blocks=blocks, images=[im])


def _gdocs(page):
    # the gdocs profile: anchored=False, anchor_pictures=True (options)
    return infer(DocIR(path="bg.pdf", pages=[page]), anchored=False,
                 anchor_pictures=True)


def _in_flow(lay):
    return [e for ch in lay.pages[0].chunks for e in ch.elements
            if isinstance(e, ImageEl)]


class FullBleedBackground(unittest.TestCase):

    def test_a_panel_across_the_paper_goes_behind_its_text(self):
        lay = _gdocs(_page((0.0, 93.5, 594.0, 747.9)))      # y33 p3's panel
        self.assertEqual(_in_flow(lay), [])
        fl = lay.pages[0].floats
        self.assertEqual(len(fl), 1)
        self.assertTrue(fl[0].behind)

    def test_a_picture_inside_the_margins_keeps_the_flow(self):
        lay = _gdocs(_page((72.0, 140.0, 520.0, 400.0)))
        self.assertEqual(len(_in_flow(lay)), 1)
        self.assertFalse(lay.pages[0].floats)


if __name__ == "__main__":
    unittest.main()
