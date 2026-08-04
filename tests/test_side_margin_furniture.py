"""Side-margin furniture must not consume body-flow height.

The defect this pins down: NIST SP 800-63B draws a rotated "available free of
charge from..." citation strip in its left margin, backed by a white rectangle
at x=3..37 on a page whose body column starts at x=72. Inference promoted that
rectangle to a rasterised FigureEl and the writer emitted it as an ordinary
block element, so every page paid 432pt of body height for a shape that sat
outside the body entirely. With a hard page break per source page, each source
page then needed two output pages: 80 -> 158, and word_recall fell to 0.13
because nearly every word landed on the wrong page.

The rule is geometric and carries no fixture knowledge: a shape lying wholly in
a left/right margin band is furniture. The control tests below move the same
rectangle into the body column and require that it still becomes a figure --
the rule must discriminate on position, not suppress rectangles in general.
"""
import unittest

from exactdoc.infer import infer, in_side_margin, MARGIN_BAND_CLEARANCE
from exactdoc.layout import FigureEl, Para
from exactdoc.model import DocIR, DrawCmd, Line, PageIR, Span, TextBlock

PAGE_W, PAGE_H = 612.0, 792.0
BODY_L, BODY_R = 72.0, 522.0        # inferred column on the synthetic page


def _line(x0, x1, y, text="the quick brown fox jumps over the lazy dog"):
    span = Span(text=text, font="Helvetica", size=10.0, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=(x0, y - 10, x1, y), origin=(x0, y))
    return Line(spans=[span], bbox=(x0, y - 10, x1, y))


def _rect(x0, y0, x1, y1):
    """A filled white rectangle -- the NIST sidebar backing shape."""
    return DrawCmd(kind="fill", shape="rect", bbox=(x0, y0, x1, y1),
                   fill="#ffffff", stroke=None, width=0.0, opacity=1.0,
                   n_items=1)


def _page(rect=None, n_pages=1):
    """Body text in y=60..170, leaving y>200 clear for the test rectangle."""
    pages = []
    for pno in range(1, n_pages + 1):
        lines = [_line(BODY_L, BODY_R, 60.0 + 12.0 * i) for i in range(10)]
        blk = TextBlock(lines=lines, bbox=(BODY_L, 50.0, BODY_R, 170.0))
        pages.append(PageIR(number=pno, width=PAGE_W, height=PAGE_H,
                            blocks=[blk],
                            drawings=[rect] if rect is not None else []))
    return DocIR(path="synthetic.pdf", pages=pages)


def _figures(lay):
    return [el for pl in lay.pages for ch in pl.chunks for el in ch.elements
            if isinstance(el, FigureEl)]


class Predicate(unittest.TestCase):
    def test_left_band(self):
        # the real NIST geometry: x=1..39 against a column starting at 72
        self.assertTrue(in_side_margin((1, 190, 39, 621), 72.0, 89.7, PAGE_W))

    def test_right_band(self):
        # column is [72, 552] here, so furniture must start clear of 552
        self.assertTrue(in_side_margin((560, 190, 600, 621), 72.0, 60.0, PAGE_W))
        # ...and a shape reaching back into the column is not furniture
        self.assertFalse(in_side_margin((540, 190, 600, 621), 72.0, 60.0, PAGE_W))

    def test_body_content_is_never_furniture(self):
        self.assertFalse(in_side_margin((72, 190, 522, 621), 72.0, 90.0, PAGE_W))

    def test_shape_straddling_the_column_edge_is_kept(self):
        # a full-bleed cover band starts left of the margin but reaches into
        # the column: it is content, and suppressing it would lose the page
        self.assertFalse(in_side_margin((0, 0, 612, 120), 72.0, 90.0, PAGE_W))

    def test_clearance_protects_a_grazing_shape(self):
        # a shape ending exactly at the column edge may be ordinary content
        # against a slightly mis-inferred margin, so it is NOT furniture
        self.assertFalse(in_side_margin((10, 100, 72.0, 200), 72.0, 90.0, PAGE_W))
        edge = 72.0 - MARGIN_BAND_CLEARANCE
        self.assertTrue(in_side_margin((10, 100, edge, 200), 72.0, 90.0, PAGE_W))


class MarginRectDoesNotEnterFlow(unittest.TestCase):
    def test_margin_rect_emits_no_figure(self):
        lay = infer(_page(_rect(3.0, 300.0, 37.0, 700.0)))
        self.assertEqual(_figures(lay), [],
                         "a rectangle wholly in the left margin must not "
                         "become an in-flow figure")

    def test_margin_rect_costs_no_body_height(self):
        without = infer(_page(None))
        with_rect = infer(_page(_rect(3.0, 300.0, 37.0, 700.0)))

        def flow_height(lay):
            total = 0.0
            for pl in lay.pages:
                for ch in pl.chunks:
                    for el in ch.elements:
                        if isinstance(el, Para):
                            total += el.space_before + el.space_after + \
                                max(1, el.src_lines) * (el.leading or 12.0)
                        else:
                            bb = getattr(el, "clip", None) or \
                                getattr(el, "bbox", None)
                            if bb:
                                total += bb[3] - bb[1]
            return total

        self.assertAlmostEqual(flow_height(with_rect), flow_height(without),
                               delta=0.5)

    def test_repeats_on_every_page(self):
        lay = infer(_page(_rect(3.0, 300.0, 37.0, 700.0), n_pages=6))
        self.assertEqual(len(lay.pages), 6)
        self.assertEqual(_figures(lay), [])

    def test_right_margin_rect_also_suppressed(self):
        # symmetric: change bars and tabs live on either side
        lay = infer(_page(_rect(560.0, 300.0, 600.0, 700.0)))
        self.assertEqual(_figures(lay), [])


class MarginShapesThatAnchorBodyContent(unittest.TestCase):
    """A shape in the margin band is not automatically furniture.

    The first version of this rule filtered every side-margin drawing out of
    the pipeline, and moved four gated fixtures. The reason: a blockquote or
    callout bar sits just OUTSIDE the body column and marks text INSIDE it, so
    removing it upstream destroys the callout. The rule therefore guards only
    the branch that promotes a stray shape to a standalone raster.
    """

    def _page_with_quote_bar(self):
        lines = [_line(BODY_L, BODY_R, 300.0 + 12.0 * i) for i in range(8)]
        blk = TextBlock(lines=lines, bbox=(BODY_L, 290.0, BODY_R, 396.0))
        # a 2pt bar at x=68..70, wholly left of the column but anchoring text
        bar = DrawCmd(kind="stroke", shape="vline", bbox=(68.0, 296.0, 70.0, 398.0),
                      fill=None, stroke="#2563eb", width=2.0, opacity=1.0,
                      n_items=1)
        pg = PageIR(number=1, width=PAGE_W, height=PAGE_H, blocks=[blk],
                    drawings=[bar])
        return DocIR(path="quotebar.pdf", pages=[pg])

    def test_quote_bar_in_the_margin_still_builds_its_callout(self):
        ir = self._page_with_quote_bar()
        lay = infer(ir)
        roles = [el.role for pl in lay.pages for ch in pl.chunks
                 for el in ch.elements if hasattr(el, "role")]
        self.assertIn("quote", roles,
                      "a margin quote bar must still anchor its callout; "
                      "filtering side-margin drawings wholesale breaks this")

    def test_quote_bar_is_geometrically_in_the_margin(self):
        # the bar really is in the band -- this test would be vacuous otherwise
        self.assertTrue(in_side_margin((68.0, 296.0, 70.0, 398.0), 72.0,
                                       90.0, PAGE_W))


class BodyRectIsStillAFigure(unittest.TestCase):
    """The control: the rule discriminates on position, not on shape."""

    def test_same_rect_inside_the_column_becomes_a_figure(self):
        lay = infer(_page(_rect(200.0, 300.0, 234.0, 700.0)))
        figs = _figures(lay)
        self.assertEqual(len(figs), 1,
                         "an identical rectangle inside the body column is "
                         "content and must still be rasterised")
        self.assertGreater(figs[0].height, 300.0)


if __name__ == "__main__":
    unittest.main()
