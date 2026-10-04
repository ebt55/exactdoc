"""Drawings are structural evidence only when a reader can see them.

Three defects, one family -- structure inferred from ink that is invisible or
is not what it looks like:

  * Word paints paragraph shading as one #ffffff rectangle per LINE. Each became
    a single-cell 'box' table, so a 7-line paragraph came out as 7 stacked
    tables (y01 p21; 111 white unbordered boxes on y01).
  * Word paints a 0.48pt / 1.5pt square wherever two table borders meet. Each
    one left of cell text became a "•" (y02: 1,286 bullets for 24 real ones).
  * A light page-height rule in y09's left margin was taken for a quote bar and
    wrapped 56 of 59 pages in a one-cell quote table.

Every test pairs the defect with its control: the same evidence in the form a
real box, bullet or quote bar takes must still produce that structure.

    python tests/test_drawing_visibility.py
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import dialect                                  # noqa: E402
from exactdoc.dialect import (_drop_invisible_fills,          # noqa: E402
                              _drop_transparent, _markers_to_text, normalize)
from exactdoc.infer import _classify_cluster, _is_quote_bar, infer  # noqa: E402
from exactdoc.layout import TableEl                           # noqa: E402
from exactdoc.model import (DocIR, DrawCmd, ImageObj, Line,   # noqa: E402
                            PageIR, Span, TextBlock)

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None

W, H = 612.0, 792.0


def _line(text, x0, top, size=12.0, x1=None):
    x1 = x1 if x1 is not None else x0 + 0.5 * size * len(text)
    bb = (x0, top, x1, top + size * 1.2)
    sp = Span(text=text, font="Helvetica", size=size, color="#000000",
              bold=False, italic=False, mono=False, serif=False,
              superscript=False, bbox=bb, origin=(x0, top + size))
    return Line(spans=[sp], bbox=bb)


def _fill(x0, y0, x1, y1, colour="#ffffff", shape="rect", kind="fill",
          stroke=None, opacity=1.0):
    return DrawCmd(kind=kind, shape=shape, bbox=(x0, y0, x1, y1),
                   fill=colour if kind != "stroke" else None, stroke=stroke,
                   width=0.75 if stroke else 0.0, opacity=opacity, n_items=5)


def _page(lines=(), drawings=(), images=()):
    pg = PageIR(number=1, width=W, height=H)
    pg.blocks = [TextBlock(lines=[ln], bbox=ln.bbox) for ln in lines]
    pg.drawings = list(drawings)
    pg.images = list(images)
    return pg


def _elements(lay):
    return [el for pl in lay.pages for ch in pl.chunks for el in ch.elements]


def _text(page):
    return [ln.text for b in page.blocks for ln in b.lines]


# ---------------------------------------------------------------- B5: fills
class PageColouredFills(unittest.TestCase):
    def _shaded_paragraph(self, n=7):
        """y01 p21: one #ffffff rectangle behind each line of a paragraph."""
        lines, rects = [], []
        for i in range(n):
            top = 560.0 + 13.8 * i
            lines.append(_line("If CSPs process attributes for purposes other "
                               "than identity", 72.0, top, x1=526.0))
            rects.append(_fill(72.0, top, 526.6, top + 13.8))
        return lines, rects

    def test_per_line_shading_is_dropped(self):
        lines, rects = self._shaded_paragraph()
        page = _page(lines, rects)
        self.assertEqual(_drop_invisible_fills(page), 7)
        self.assertEqual(page.drawings, [])

    def test_per_line_shading_no_longer_builds_boxes(self):
        lines, rects = self._shaded_paragraph()
        ir = DocIR(path="shaded.pdf", pages=[_page(lines, rects)])
        boxes = [el for el in _elements(infer(normalize(ir)))
                 if isinstance(el, TableEl)]
        self.assertEqual(boxes, [], "white-on-white shading is not a box")

    def test_without_the_rule_each_line_was_a_box(self):
        # The defect this pins, reproduced on the un-normalised page: infer
        # alone still boxes every line, so the fix lives in dialect.
        lines, rects = self._shaded_paragraph(3)
        ir = DocIR(path="shaded.pdf", pages=[_page(lines, rects)])
        boxes = [el for el in _elements(infer(ir)) if isinstance(el, TableEl)]
        self.assertEqual(len(boxes), 3)

    def test_white_knockout_on_a_dark_band_is_kept(self):
        band = _fill(54.0, 189.0, 558.0, 309.0, "#1e3a5f")
        card = _fill(80.0, 213.0, 300.0, 237.0)
        page = _page([_line("Realtime", 84.0, 216.0)], [band, card])
        self.assertEqual(_drop_invisible_fills(page), 0)
        self.assertIn(card, page.drawings)

    def test_white_zebra_row_between_tinted_rows_is_kept(self):
        # 01_whitepaper_market / 03 / r1: white rows of a striped table share
        # an edge with the tinted ones and the grid's rules.
        rows = [_fill(54.0, 237.0, 558.0, 261.0, "#f8fafc"),
                _fill(54.0, 261.0, 558.0, 285.0),
                _fill(54.0, 285.0, 558.0, 309.0, "#f8fafc")]
        page = _page([_line("Batch", 60.0, 264.0)], rows)
        self.assertEqual(_drop_invisible_fills(page), 0)

    def test_white_fill_framed_by_separate_rules_is_kept(self):
        rules = [_fill(54.0, 78.0, 558.0, 78.0, None, "hline", "stroke", "#99f6e4"),
                 _fill(54.0, 100.0, 558.0, 100.0, None, "hline", "stroke", "#99f6e4")]
        cell = _fill(54.0, 78.0, 558.0, 100.0)
        page = _page([_line("fail_open", 60.0, 82.0)], rules + [cell])
        self.assertEqual(_drop_invisible_fills(page), 0)

    def test_tints_are_never_candidates(self):
        # the lightest visible tints in the gated corpus
        for tint in ("#f8fafc", "#f6f8fa", "#f2f5f8"):
            page = _page([_line("code", 60.0, 160.0)],
                         [_fill(54.0, 150.0, 558.0, 280.0, tint)])
            self.assertEqual(_drop_invisible_fills(page), 0, tint)

    def test_stroked_white_box_is_kept(self):
        box = _fill(54.0, 150.0, 558.0, 280.0, kind="fillstroke",
                    stroke="#333333")
        page = _page([_line("callout", 60.0, 160.0)], [box])
        self.assertEqual(_drop_invisible_fills(page), 0)

    def test_white_rules_are_not_candidates(self):
        # y09 p54 draws a whole table in #ffffff borders: its geometry is the
        # only evidence of the rows and columns, so rules stay.
        grid = [_fill(72.0, 100.9, 521.5, 101.4, shape="hline"),
                _fill(134.8, 101.4, 135.2, 127.3, shape="vline"),
                _fill(72.0, 100.9, 72.5, 101.4)]          # a joint square
        page = _page([], grid)
        self.assertEqual(_drop_invisible_fills(page), 0)

    def test_image_inside_the_fill_does_not_save_it(self):
        # y01's section numbers are images drawn ON the heading shading
        img = ImageObj(bbox=(71.5, 471.6, 87.8, 480.7), xref=0, width=16, height=9)
        page = _page([_line("Privacy Requirements", 100.8, 468.6)],
                     [_fill(70.6, 469.9, 541.4, 482.6)], [img])
        self.assertEqual(_drop_invisible_fills(page), 1)

    def test_fill_over_part_of_an_image_is_a_knockout(self):
        img = ImageObj(bbox=(50.0, 400.0, 300.0, 600.0), xref=0, width=250, height=200)
        page = _page([_line("label", 210.0, 455.0)],
                     [_fill(200.0, 450.0, 400.0, 470.0)], [img])
        self.assertEqual(_drop_invisible_fills(page), 0)

    def test_white_card_on_a_light_backdrop_survives_normalize(self):
        # Visibility is decided before the backdrop is removed: a #ffffff card
        # on a #f8f8f8 page background (light enough to be dropped as a
        # backdrop afterwards) is visible by contrast.
        backdrop = _fill(0.0, 0.0, W, H, "#f8f8f8")
        card = _fill(72.0, 100.0, 540.0, 200.0)
        ir = DocIR(path="card.pdf",
                   pages=[_page([_line("inside", 80.0, 120.0)], [backdrop, card])])
        normalize(ir)
        self.assertEqual(ir.pages[0].drawings, [card])
        self.assertEqual(ir.meta["_normalized"]["backdrops"], 1)
        self.assertEqual(ir.meta["_normalized"]["invisible_fills"], 0)

    def test_white_card_on_a_white_backdrop_is_dropped(self):
        # ...and on a backdrop of its own colour neither is visible: both go,
        # the page-sized one included.
        backdrop = _fill(0.0, 0.0, W, H, "#ffffff")
        card = _fill(72.0, 100.0, 540.0, 200.0)
        ir = DocIR(path="card.pdf",
                   pages=[_page([_line("inside", 80.0, 120.0)], [backdrop, card])])
        normalize(ir)
        self.assertEqual(ir.pages[0].drawings, [])
        self.assertEqual(ir.meta["_normalized"]["invisible_fills"], 2)


class TransparentInk(unittest.TestCase):
    def test_zero_alpha_and_unpainted_paths_are_dropped(self):
        ghost = _fill(10.0, 10.0, 200.0, 200.0, "#000000", opacity=0.0)
        outline = _fill(10.0, 10.0, 15.0, 15.0, None, "complex", "stroke",
                        "#000000", opacity=0.03)       # y03's glyph outlines
        nothing = DrawCmd(kind="fill", shape="complex", bbox=(0, 0, 5, 5),
                          fill=None, stroke=None, width=0.0, opacity=0.0,
                          n_items=3)
        solid = _fill(300.0, 300.0, 400.0, 400.0, "#000000")
        page = _page([], [ghost, outline, nothing, solid])
        self.assertEqual(_drop_transparent(page), 3)
        self.assertEqual(page.drawings, [solid])

    def test_fillstroke_with_a_transparent_fill_keeps_its_stroke(self):
        d = _fill(10.0, 10.0, 200.0, 200.0, "#000000", kind="fillstroke",
                  stroke="#000000", opacity=0.02)
        page = _page([], [d])
        self.assertEqual(_drop_transparent(page), 0)


# ------------------------------------------------------------ B4: markers
class TableBorderJoints(unittest.TestCase):
    def _word_table_row(self, joint=0.48):
        """y01 p1: a ruled row whose junction squares sit left of cell text."""
        lines = [_line("Series/Number", 72.9, 234.3, 11.0),
                 _line("NIST Special Publication 800-63B", 185.2, 234.4, 11.0),
                 _line("Title", 72.9, 248.2, 11.0),
                 _line("Digital Identity Guidelines", 185.2, 248.2, 11.0)]
        draws = []
        for y in (234.72, 248.64, 262.56):
            draws += [_fill(66.72, y, 68.22, y + joint, "#000000"),
                      _fill(68.22, y, 179.52, y + joint, "#000000", "hline"),
                      _fill(179.52, y, 179.52 + joint, y + joint, "#000000"),
                      _fill(179.52 + joint, y, 543.72, y + joint, "#000000", "hline")]
        for y0, y1 in ((235.2, 248.64), (249.12, 262.56)):
            draws += [_fill(66.72, y0, 68.22, y1, "#000000", "vline"),
                      _fill(179.52, y0, 179.52 + joint, y1, "#000000", "vline")]
        return lines, draws

    def test_joints_are_not_bullets(self):
        lines, draws = self._word_table_row()
        page = _page(lines, draws)
        self.assertEqual(_markers_to_text(page), 0)
        self.assertNotIn("•", "".join(_text(page)))
        self.assertEqual(len(page.drawings), len(draws))

    def test_thick_joints_are_not_bullets_either(self):
        # a 3pt border's joint clears the size floor; touching the rule ends
        # is what gives it away
        lines, draws = self._word_table_row(joint=3.0)
        page = _page(lines, draws)
        self.assertEqual(_markers_to_text(page), 0)

    def test_leader_dots_are_not_bullets(self):
        # x11: Chromium draws a dotted TOC leader as 0.75pt squares; the last
        # one sits just left of the page number
        lines = [_line("1", 300.0, 200.0, 11.0), _line("2", 300.0, 220.0, 11.0)]
        dots = [_fill(297.0, 208.0, 297.75, 208.75, "#999999"),
                _fill(297.0, 228.0, 297.75, 228.75, "#999999")]
        page = _page(lines, dots)
        self.assertEqual(_markers_to_text(page), 0)

    def test_chromium_discs_still_become_bullets(self):
        # c6 / x09: 3.0pt discs against 10.5-11pt text (0.27-0.29em)
        lines = [_line("First item", 90.0, 200.0, 11.0),
                 _line("Second item", 90.0, 220.0, 11.0)]
        discs = [_fill(79.5, 205.7, 82.5, 208.7, "#000000", "curve"),
                 _fill(79.5, 225.7, 82.5, 228.7, "#000000", "curve")]
        page = _page(lines, discs)
        self.assertEqual(_markers_to_text(page), 2)
        self.assertEqual(_text(page).count("•"), 2)


class JointSquaresAreNotBars(unittest.TestCase):
    def test_shaded_heading_with_corner_joints_is_not_a_chart(self):
        # y08 chapter heading: a fill, its four border segments and the four
        # 0.48pt corner joints. Two joints share the fill's bottom edge, and
        # the bar-chart test used to read three 'bars' of different heights.
        ds = [_fill(66.6, 72.48, 545.4, 88.32, "#000000"),
              _fill(66.12, 72.0, 66.6, 72.48, "#244061"),
              _fill(66.6, 72.0, 545.4, 72.48, "#244061", "hline"),
              _fill(545.4, 72.0, 545.88, 72.48, "#244061"),
              _fill(66.12, 88.32, 66.6, 88.8, "#244061"),
              _fill(66.6, 88.32, 545.4, 88.8, "#244061", "hline"),
              _fill(545.4, 88.32, 545.88, 88.8, "#244061"),
              _fill(66.12, 72.48, 66.6, 88.32, "#244061", "vline"),
              _fill(545.4, 72.48, 545.88, 88.32, "#244061", "vline")]
        self.assertNotEqual(_classify_cluster(list(enumerate(ds))), "figure")

    def test_real_bars_still_make_a_chart(self):
        ds = [_fill(100.0 + 30 * i, 400.0 - 40 * i, 120.0 + 30 * i, 500.0,
                    "#2563eb") for i in range(4)]
        self.assertEqual(_classify_cluster(list(enumerate(ds))), "figure")


# ------------------------------------------------------- quote bars (#12)
class QuoteBars(unittest.TestCase):
    def _body(self, top=72.0, n=40, x0=72.0, size=12.0):
        return [_line("Zero trust is a set of cybersecurity paradigms that move "
                      "defenses", x0, top + 16.2 * i, size, x1=540.0)
                for i in range(n)]

    def _quotes(self, lines, bar, extra=()):
        ir = DocIR(path="q.pdf", pages=[_page(lines, [bar] + list(extra))])
        return [el for el in _elements(infer(ir))
                if isinstance(el, TableEl) and el.role == "quote"]

    def test_page_height_margin_rule_is_not_a_quote_bar(self):
        # y09: a 0.75pt #dadada rule at x=41, y 72-720, beside the body at 72
        bar = _fill(40.85, 72.3, 42.25, 720.3, None, "vline", "stroke", "#dadada")
        self.assertEqual(self._quotes(self._body(), bar), [])

    def test_genuine_quote_bar_still_builds_its_quote(self):
        # 04_exec_brief: a 3.5pt bar at x=57, its quote starting 14pt right
        lines = [_line('"The bottleneck moved from model quality to operational',
                       71.0, 388.2, 13.0, x1=514.9),
                 _line('budget cycle."', 71.0, 406.2, 13.0),
                 _line("VP Platform Engineering", 71.0, 427.9, 9.0)]
        bar = _fill(57.0, 383.0, 57.0, 446.0, None, "vline", "stroke", "#7c3aed")
        bar = DrawCmd(**{**bar.__dict__, "width": 3.5})
        self.assertEqual(len(self._quotes(lines, bar)), 1)

    def test_bar_far_taller_than_its_text_is_not_a_quote_bar(self):
        lines = [_line("a short note beside a column rule", 80.0, 300.0, 11.0)]
        bar = _fill(70.0, 100.0, 71.5, 700.0, "#333333", "vline")
        self.assertEqual(self._quotes(lines, bar), [])

    def test_rejected_bar_is_not_rasterised_instead(self):
        # A filled rule inside the column, far from its text: not a quote bar,
        # and not a stray shape to rasterise into a 600pt strip either.
        from exactdoc.layout import FigureEl
        lines = self._body(top=100.0, n=30, x0=260.0)
        bar = _fill(200.0, 100.0, 202.0, 700.0, "#333333", "vline")
        ir = DocIR(path="q.pdf", pages=[_page(lines, [bar])])
        els = _elements(infer(ir))
        self.assertEqual([e for e in els if isinstance(e, FigureEl)], [])
        self.assertEqual([e for e in els if isinstance(e, TableEl)], [])

    def test_left_side_of_a_frame_is_not_a_quote_bar(self):
        # NIST covers: the title box is four separate 1.5pt segments
        title = [_line("Withdrawn NIST Technical Series Publication", 101.9,
                       79.6, 22.0, x1=510.0)]
        left = _fill(65.04, 73.5, 66.54, 116.34, "#000000", "vline")
        top = _fill(66.54, 72.0, 545.46, 73.5, "#000000", "hline")
        bot = _fill(66.54, 116.34, 545.46, 117.84, "#000000", "hline")
        self.assertEqual(self._quotes(title, left, [top, bot]), [])
        lines = title
        self.assertFalse(_is_quote_bar(left.bbox, lines, [left, top, bot]))
        self.assertTrue(_is_quote_bar(left.bbox, lines, [left]))


# ------------------------------------------------- end to end through PDFium
def _word_export_pdf(path):
    """Paragraph shading, a Word-ruled table and a real two-item list."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    # shaded paragraph: a white rectangle behind every line, drawn first
    for i in range(5):
        top = 120.0 + 14.0 * i
        c.setFillColorRGB(1, 1, 1)
        c.rect(70.56, H - top - 14.0, 470.0, 14.0, stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica", 12)
        c.drawString(72.0, H - top - 11.0, "Shaded paragraph line %d of the "
                     "same paragraph, wrapping as Word wrapped it" % (i + 1))
    # ruled table: filled border segments with 0.48pt joint squares
    j = 0.48
    c.setFillColorRGB(0, 0, 0)
    for y in (300.0, 320.0, 340.0):
        for x0, x1 in ((72.0, 72.0 + j), (180.0, 180.0 + j), (400.0, 400.0 + j)):
            c.rect(x0, H - y - j, x1 - x0, j, stroke=0, fill=1)
        c.rect(72.0 + j, H - y - j, 180.0 - 72.0 - j, j, stroke=0, fill=1)
        c.rect(180.0 + j, H - y - j, 400.0 - 180.0 - j, j, stroke=0, fill=1)
    for y0 in (300.0 + j, 320.0 + j):
        for x in (72.0, 180.0, 400.0):
            c.rect(x, H - y0 - (20.0 - j), j, 20.0 - j, stroke=0, fill=1)
    c.setFont("Helvetica", 11)
    for row, y in enumerate((300.0, 320.0)):
        c.drawString(77.0, H - y - 14.0, "Key %d" % row)
        c.drawString(185.0, H - y - 14.0, "Value %d" % row)
    # a real list: 3pt discs left of 11pt items
    for i, text in enumerate(("First item", "Second item")):
        base = 420.0 + 18.0 * i
        c.circle(81.0, H - base + 3.5, 1.5, stroke=0, fill=1)
        c.drawString(90.0, H - base, text)
    c.save()
    return path


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from exactdoc.parse_pdfium import parse_pdf
        cls._dir = tempfile.TemporaryDirectory()
        pdf = _word_export_pdf(os.path.join(cls._dir.name, "word.pdf"))
        cls.ir = normalize(parse_pdf(pdf, keep_image_data=False))
        cls.lay = infer(cls.ir)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_shading_rectangles_were_dropped(self):
        self.assertEqual(self.ir.meta["_normalized"]["invisible_fills"], 5)

    def test_no_box_tables(self):
        roles = [el.role for el in _elements(self.lay) if isinstance(el, TableEl)]
        self.assertNotIn("box", roles)

    def test_exactly_the_two_real_bullets(self):
        self.assertEqual(self.ir.meta["_normalized"]["vector_markers"], 2)
        # the marker block is joined to its item's row by normalize
        text = _text(self.ir.pages[0])
        self.assertEqual("".join(text).count("•"), 2)
        self.assertEqual(sorted(t for t in text if "•" in t),
                         ["• First item", "• Second item"])


class Constants(unittest.TestCase):
    def test_floors_sit_between_the_measured_populations(self):
        # genuine discs: 2.67-3.0pt at 0.27-0.29em; joints 0.48/1.5pt
        self.assertLess(dialect.MARKER_MIN_PT, 2.67)
        self.assertGreater(dialect.MARKER_MIN_PT, 1.5)
        self.assertLess(dialect.MARKER_MIN_EM, 0.27)
        self.assertGreater(dialect.MARKER_MIN_EM, 0.15)


if __name__ == "__main__":
    unittest.main()
