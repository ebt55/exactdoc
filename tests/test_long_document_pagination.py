"""Long documents keep every source page on its own page (WP23).

Every source page ends in a hard break, so a page whose content renders even a
line taller than its box puts every later page one place late -- and word
recall, which scores words on the right page, collapses from there. The first
page where each long promised document diverged, found with a source-to-render
page map, fell into a handful of classes; each is pinned here on synthetic
input:

1. Preformatted text cut at its own grid: the gutter bound on the parser's
   justification exemption read an ASCII-art figure's recurring box sides as
   a column gutter (RFC 9000 p16; `parse_pdfium._same_mono_face`).
2. A vertical rule rasterised into the flow as a picture of its own height
   (RFC 9110's collected-ABNF box; `infer.VLINE_FIGURE_MIN_PT`).
3. A picture set on a text line, or wrapped by a paragraph, stacked under it
   (NIST's withdrawal-notice logo, SP 800-63B's contents numbers and icons;
   `infer._on_text_line`, `infer._wrapped_by_text`).
4. Fragments of one row -- a contents number and its entry, two columns of
   authors -- stacked one per line (`infer._fuse_baseline_rows`).
5. A one-line title given exactly its own width and wrapped by a hair
   (`ladder.relieve_one_line`).
6. A drop cap's em box swallowing the lines beside it as its "scripts" and
   sorting them into one line of interleaved characters (SP 800-171's chapter
   openings; `parse_pdfium._absorb_script_rows`).
7. A contents line's words glued together: a separated marker ("1." +
   "INTRODUCTION") and a tab leader drawn against its title and number
   (`infer._merge_list_markers`, `infer._leader_para`).
8. A table of short rows read as two columns (`infer._split_unfilled`).
9. Pictures floated on a page that a booklet run then merges
   (`docxout._floats_into_flow`).
"""
import io
import os
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

from exactdoc import infer as I
from exactdoc import ladder as L
from exactdoc.docxout import _gdocs_typed_leader, write_docx
from exactdoc.layout import (Chunk, DocLayout, FigureEl, FloatEl, ImageEl,
                             PageLayout, Para, Run)
from exactdoc.metrics import get_metrics
from exactdoc.model import DocIR, DrawCmd, ImageObj, Line, PageIR, Span, TextBlock

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cf0000000301010018dd8db00000000049454e44ae426082")


def _line(text, x0, top, x1, size=12.0, font="Times-Roman"):
    s = Span(text, font, size, "#000000", False, False, False, True, False,
             (x0, top, x1, top + 1.2 * size), (x0, top + 0.95 * size))
    return Line([s], s.bbox)


def _block(lines):
    bb = (min(l.bbox[0] for l in lines), min(l.bbox[1] for l in lines),
          max(l.bbox[2] for l in lines), max(l.bbox[3] for l in lines))
    return TextBlock(list(lines), bb)


def _paras(lay, n=0):
    return [e for ch in lay.pages[n].chunks for e in ch.elements
            if isinstance(e, Para)]


# ------------------------------------------------------------ 1. the parser
def _mono_figure_pdf(path, font="Courier", rows=6):
    """Rows of a box drawn in `font`: `|` then a literal space, and the far
    side 27 cells right of it set by a second string -- the producer moves
    over the spaces between, as xml2rfc/WeasyPrint does."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=(595, 842))
    cell = 0.6 * 9.5
    for i in range(rows):
        y = 700 - 11 * i
        c.setFont(font, 9.5)
        c.drawString(100, y, "| ")
        c.drawString(100 + 28 * cell, y, "|")
    c.save()


class MonospaceGridGaps(unittest.TestCase):
    def _lines(self, font):
        from exactdoc.parse_pdfium import parse_pdf
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "fig.pdf")
            _mono_figure_pdf(p, font=font)
            ir = parse_pdf(p, keep_image_data=False)
        return [ln for b in ir.pages[0].blocks for ln in b.lines]

    def test_a_box_drawn_in_monospace_stays_one_line_per_row(self):
        lines = self._lines("Courier")
        self.assertEqual(len(lines), 6, [l.text for l in lines])
        for ln in lines:
            # every cell of the gap survives: 27 spaces between the sides
            self.assertEqual(ln.text.strip(), "|" + " " * 27 + "|")

    def test_proportional_text_still_splits_at_a_recurring_gap(self):
        # the booklets' gutter (y13): the bound is unchanged off monospace
        lines = self._lines("Helvetica")
        self.assertEqual(len(lines), 12, [l.text for l in lines])


# --------------------------------------------------------- 2. vertical rules
def _vline(x0, y0, x1, y1):
    return DrawCmd(kind="fill", shape="vline", bbox=(x0, y0, x1, y1),
                   fill="#eeeeee", stroke=None, width=0.0, opacity=1.0, n_items=1)


class VerticalRulesAreNotFigures(unittest.TestCase):
    def _page(self, height):
        body = [_line("ABNF rule number %d = token / quoted-string" % i,
                      76.0, 150.0 + 11 * i, 400.0, size=9.5, font="Courier")
                for i in range(20)]
        return PageIR(number=1, width=595.0, height=842.0, blocks=[_block(body)],
                      drawings=[_vline(65.9, 142.0, 66.7, 142.0 + height),
                                _vline(528.6, 142.0, 529.4, 142.0 + height)])

    def test_a_box_side_down_the_page_takes_no_flow_height(self):
        lay = I.infer(DocIR(path="x.pdf", pages=[self._page(553.0)]))
        pg = lay.pages[0]
        els = [e for ch in pg.chunks for e in ch.elements]
        self.assertFalse(any(isinstance(e, FigureEl) for e in els))
        # drawn where the source drew them, behind the text
        sides = [f for f in pg.floats if isinstance(f.el, FigureEl)]
        self.assertEqual(len(sides), 2)
        self.assertTrue(all(f.behind and f.wrap is None for f in sides))

    def test_the_google_docs_profile_keeps_its_flow(self):
        # its writer places these itself; inference leaves them as they were
        lay = I.infer(DocIR(path="x.pdf", pages=[self._page(553.0)]),
                      anchored=False)
        self.assertEqual(lay.pages[0].floats, [])

    def test_a_bar_shorter_than_half_the_page_keeps_the_old_path(self):
        # an accent bar beside a heading (y48): not a frame's side
        h = (I.VLINE_FLOAT_MIN_FRAC - 0.1) * 842.0
        lay = I.infer(DocIR(path="x.pdf", pages=[self._page(h)]))
        self.assertFalse([f for f in lay.pages[0].floats
                          if isinstance(f.el, FigureEl)])


# -------------------------------------------- 3. pictures on and in the text
def _img(bb):
    return ImageObj(bbox=bb, xref=1, width=1, height=1, data=_PNG, ext="png")


class PicturesBesideText(unittest.TestCase):
    def test_a_logo_beside_the_date_line_floats(self):
        page = PageIR(number=1, width=612.0, height=792.0,
                      blocks=[_block([_line("Warning Notice", 72.0, 100.0, 300.0)]),
                              _block([_line("Date updated: May 14, 2024", 72.0,
                                            733.0, 211.0)])],
                      images=[_img((361.0, 716.0, 540.0, 744.0))])
        lay = I.infer(DocIR(path="x.pdf", pages=[page]))
        pg = lay.pages[0]
        self.assertEqual(len(pg.floats), 1)
        self.assertIsNone(pg.floats[0].wrap)
        self.assertFalse(pg.floats[0].behind)
        els = [e for ch in pg.chunks for e in ch.elements]
        self.assertFalse(any(isinstance(e, ImageEl) for e in els))

    def test_the_google_docs_profile_keeps_it_in_the_flow(self):
        page = PageIR(number=1, width=612.0, height=792.0,
                      blocks=[_block([_line("Date updated: May 14, 2024", 72.0,
                                            733.0, 211.0)])],
                      images=[_img((361.0, 716.0, 540.0, 744.0))])
        lay = I.infer(DocIR(path="x.pdf", pages=[page]), anchored=False)
        self.assertFalse(lay.pages[0].floats)

    def test_on_text_line_bounds(self):
        line = (72.0, 733.0, 211.0, 749.0)
        self.assertTrue(I._on_text_line((361.0, 716.0, 540.0, 744.0), [line]))
        # a picture three lines tall beside one line is a figure, not a mark
        self.assertFalse(I._on_text_line((361.0, 700.0, 540.0, 749.0), [line]))
        # text crossing the picture is not beside it
        self.assertFalse(I._on_text_line((150.0, 730.0, 180.0, 745.0), [line]))
        # a line grazing the band is not on it
        self.assertFalse(I._on_text_line((361.0, 744.0, 540.0, 760.0), [line]))

    def _wrap_lines(self):
        beside = [(153.0, 495.0 + 13.9 * i, 540.0, 511.0 + 13.9 * i)
                  for i in range(6)]
        under = [(72.0, 578.0 + 13.9 * i, 540.0, 594.0 + 13.9 * i)
                 for i in range(4)]
        return beside, under

    def test_a_paragraph_wrapped_around_an_icon(self):
        beside, under = self._wrap_lines()
        bb = (72.0, 499.0, 144.0, 571.0)
        self.assertEqual(I._wrapped_by_text(bb, beside + under),
                         (0.0, 0.0, 9.0, 0.0))
        # beside a column that never comes back under it: not a wrap
        self.assertIsNone(I._wrapped_by_text(bb, beside))
        # text on both sides: a picture between columns
        left = [(20.0, 495.0, 60.0, 511.0), (20.0, 509.0, 60.0, 525.0)]
        self.assertIsNone(I._wrapped_by_text(bb, beside + under + left))

    def test_a_wrapped_float_is_written_with_square_wrap(self):
        body = Para(runs=[Run(text="A multi-factor OTP device generates OTPs.",
                              font="Times-Roman", size=12.0, color="#000000")])
        pg = PageLayout(1, [Chunk(elements=[body])])
        pg.floats = [FloatEl(el=ImageEl(data=_PNG, ext="png", width=72.0,
                                        height=72.0),
                             bbox=(72.0, 499.0, 144.0, 571.0),
                             wrap=(0.0, 0.0, 9.0, 0.0))]
        lay = DocLayout(pages=[pg])
        lay.page_w, lay.page_h = 612.0, 792.0
        lay.margin_l = lay.margin_r = 72.0
        lay.margin_t = lay.margin_b = 72.0
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "w.docx")
            write_docx(lay, path, output_profile="standard")
            with zipfile.ZipFile(path) as z:
                root = ET.fromstring(z.read("word/document.xml"))
        a = root.find(".//" + WP + "anchor")
        self.assertIsNotNone(a.find(WP + "wrapSquare"))
        self.assertIsNone(a.find(WP + "wrapNone"))
        self.assertEqual(a.get("distR"), str(9 * 12700))
        names = [c.tag.split("}")[1] for c in a]
        self.assertLess(names.index("effectExtent"), names.index("wrapSquare"))
        self.assertLess(names.index("wrapSquare"), names.index("docPr"))


# ------------------------------------------------------ 4. one row, one line
def _frag(text, x0, x1, baseline, align="left", li=0.0, stops=(), leader=""):
    p = Para(runs=[Run(r, "Arial", 12.0, "#000000", is_tab=(r == "\t"))
                   for r in text], align=align, left_indent=li,
             tab_stops=list(stops), leader_text=leader, leading=13.9,
             src_lines=1, bbox=(x0, baseline - 12.5, x1, baseline + 3.5))
    p._b1, p._size1, p._vis_lines = baseline, 12.0, 1
    return p


def _toc_chunk():
    """SP 800-63B's contents: each chapter number a tab ahead of its entry,
    the entry carrying its own dot leader to the page number."""
    els = []
    for i, (num, entry) in enumerate([("1", "Purpose"), ("2", "Introduction"),
                                      ("3", "Definitions")]):
        base = 103.0 + 19.9 * i
        els.append(_frag([num], 72.0, 78.7, base))
        els.append(_frag([entry, "\t", str(i + 1)], 96.0, 539.5, base, li=24.0,
                         stops=[(468.0, "right", "dot")], leader="....."))
    return Chunk(n_cols=1, elements=els)


class OneRowOneLine(unittest.TestCase):
    def test_a_contents_number_and_its_entry_are_one_line(self):
        ch = _toc_chunk()
        lay = DocLayout()
        lay.page_w, lay.page_h = 612.0, 792.0
        lay.margin_l = lay.margin_r = 72.0
        lay.margin_t, lay.margin_b = 68.0, 32.0
        I._position_chunks([ch], lay, None)
        paras = ch.elements
        self.assertEqual([p.text for p in paras],
                         ["1\tPurpose\t1", "2\tIntroduction\t2",
                          "3\tDefinitions\t3"])
        for p in paras:
            self.assertEqual([tuple(t) for t in p.tab_stops],
                             [(24.0, "left"), (468.0, "right", "dot")])
            self.assertEqual((p.src_lines, p.left_indent, p.align),
                             (1, 0.0, "left"))
            # the gdocs writer types the leader at the entry's tab, not the
            # number's
            self.assertEqual(p._leader_tab, 3)
        # one line each: the next row's gap is read off the fused row
        self.assertAlmostEqual(paras[1].space_before, 19.9 - 13.9, delta=0.11)

    def test_a_right_set_fragment_tabs_to_its_right_edge(self):
        a = _line("Paul A. Grassi", 236.0, 182.0, 306.0)
        b = _line("Ray A. Perlner", 462.0, 182.0, 534.0)
        page = PageIR(number=1, width=612.0, height=792.0,
                      blocks=[_block([a]), _block([b])])
        lay = I.infer(DocIR(path="x.pdf", pages=[page]))
        paras = _paras(lay)
        self.assertEqual(len(paras), 1)
        self.assertEqual(paras[0].text.replace("\t", "|").strip("|"),
                         "Paul A. Grassi|Ray A. Perlner")

    def test_two_columns_of_prose_are_not_welded(self):
        w = 612.0 - 144.0
        a = _line("x" * 40, 72.0, 200.0, 72.0 + 0.47 * w)
        b = _line("y" * 40, 72.0 + 0.53 * w, 200.0, 540.0)
        pa = Para(runs=[Run("x", "Times-Roman", 12.0, "#000000")], bbox=a.bbox,
                  src_lines=1)
        pb = Para(runs=[Run("y", "Times-Roman", 12.0, "#000000")], bbox=b.bbox,
                  src_lines=1)
        pa._b1 = pb._b1 = a.baseline
        self.assertFalse(I._row_fusable(pa, pb, 72.0, 72.0 + w))

    def test_different_baselines_are_different_lines(self):
        pa = Para(runs=[Run("1", "Times-Roman", 12.0, "#000000")],
                  bbox=(72.0, 90.0, 79.0, 104.0), src_lines=1)
        pb = Para(runs=[Run("Purpose", "Times-Roman", 12.0, "#000000")],
                  bbox=(96.0, 104.0, 150.0, 118.0), src_lines=1)
        pa._b1, pb._b1 = 101.0, 115.0
        self.assertFalse(I._row_fusable(pa, pb, 72.0, 540.0))

    def test_the_gdocs_leader_goes_to_the_entrys_own_tab(self):
        p = Para(runs=[Run("1", "Arial", 12.0, "#000000"),
                       Run("\t", "Arial", 12.0, "#000000", is_tab=True),
                       Run("Purpose", "Arial", 12.0, "#000000"),
                       Run("\t", "Arial", 12.0, "#000000", is_tab=True),
                       Run("1", "Arial", 12.0, "#000000")],
                 tab_stops=[(24.0, "left"), (468.0, "right", "dot")],
                 leader_text="......")
        p._leader_tab = 3
        q = _gdocs_typed_leader(p)
        self.assertEqual([r.text for r in q.runs],
                         ["1", "\t", "Purpose", "....", "\t", "1"])


# ------------------------------------------------ 5. one line stays one line
def _title(align, li, ri, text="Zero Trust Architecture", size=28.0):
    p = Para(runs=[Run(text, "Times-Roman", size, "#000000")], align=align,
             left_indent=li, right_indent=ri, leading=32.5, src_lines=1)
    return p


class OneLineStaysOneLine(unittest.TestCase):
    def setUp(self):
        self.m = get_metrics()
        self.w = L.one_line_width(_title("right", 0, 0), self.m)
        self.assertIsNotNone(self.w)

    def test_a_right_set_title_gives_up_its_left_indent(self):
        col = 468.5
        p = _title("right", col - self.w + 2.0, 0.0)   # its own width, 2pt short
        self.assertEqual(L.predict_lines(p, col - p.left_indent, self.m), 2)
        self.assertTrue(L.relieve_one_line(p, col - p.left_indent, self.m))
        self.assertEqual(p.right_indent, 0.0)
        self.assertEqual(L.predict_lines(p, col - p.left_indent, self.m), 1)

    def test_a_centred_title_gives_up_both_sides_evenly(self):
        col = 468.5
        side = (col - self.w + 3.0) / 2
        p = _title("center", side, side)
        avail = col - 2 * side
        self.assertTrue(L.relieve_one_line(p, avail, self.m))
        self.assertAlmostEqual(p.left_indent, p.right_indent, delta=0.11)
        self.assertEqual(L.predict_lines(
            p, col - p.left_indent - p.right_indent, self.m), 1)

    def test_a_line_that_fills_its_column_is_prose_not_a_title(self):
        # y40's "Proof. Assume that ..." read as right-set: 94% of its column
        col = 241.0
        p = _title("right", 13.9, 0.0, text="Proof. Assume that the arbitrary "
                   "function u attains its minimum", size=10.0)
        p.bbox = (64.0, 625.0, 291.0, 634.0)
        self.assertFalse(L.relieve_one_line(p, col - 13.9, self.m))
        self.assertEqual(p.left_indent, 13.9)

    def test_a_line_wider_than_its_column_is_left_alone(self):
        p = _title("right", 10.0, 0.0)
        self.assertFalse(L.relieve_one_line(p, self.w / 2, self.m))
        self.assertEqual(p.left_indent, 10.0)

    def test_a_line_that_fits_by_a_hair_is_given_the_slack(self):
        # SP 800-171's 14pt running title fitted 189.1pt by the shaper's
        # account and wrapped in Word
        col = 468.5
        p = _title("right", col - self.w - 0.3, 0.0)
        self.assertEqual(L.predict_lines(p, col - p.left_indent, self.m), 1)
        self.assertTrue(L.relieve_one_line(p, col - p.left_indent, self.m))
        room = col - p.left_indent
        self.assertGreaterEqual(room, self.w * (1 + L.RELIEF_SLACK_FRAC)
                                + L.RELIEF_SLACK_PT - 0.11)

    def test_a_line_that_fits_is_left_alone(self):
        p = _title("right", 100.0, 0.0)
        self.assertFalse(L.relieve_one_line(p, 468.5 - 100.0, self.m))
        self.assertEqual(p.left_indent, 100.0)

    def test_the_ladder_relieves_flow_lines_only(self):
        col = 468.5
        p = _title("right", col - self.w + 2.0, 0.0)
        lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[p])])])
        lay.page_w, lay.page_h = 612.0, 792.0
        lay.margin_l, lay.margin_r = 72.0, 612.0 - 72.0 - col
        lay.margin_t = lay.margin_b = 72.0
        rep = L.apply_ladder(lay, metrics=self.m)
        self.assertEqual(rep["relieved"], 1)


# ------------------------------------------------------------ 6. drop caps
_DROP_LINES = ["oday, more than at any time in history, the federal government",
               "service providers to help carry out a wide range of missions",
               "using information systems. Many federal contractors process",
               "sensitive federal information to support the delivery of",
               "federal agencies (e.g., providing financial services; and"]


def _drop_cap_pdf(path):
    """SP 800-171's chapter opening, at its measured baselines: a 51pt "T"
    (185.5) beside three 11pt lines (160.7, 174.2, 187.6)."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=(612, 792))
    c.setFont("Times-Roman", 51)
    c.drawString(90, 792 - 185.5, "T")
    c.setFont("Times-Roman", 11)
    for i, t in enumerate(_DROP_LINES):
        # just right of the cap, as SP 800-171's lines are (0.1pt)
        x = 90.0 + c.stringWidth("T", "Times-Roman", 51) + 0.5 if i < 3 else 90.0
        c.drawString(x, 792 - (160.7 + 13.45 * i), t)
    c.save()


class DropCaps(unittest.TestCase):
    def test_the_lines_beside_a_drop_cap_are_not_its_scripts(self):
        from exactdoc.parse_pdfium import parse_pdf
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "cap.pdf")
            _drop_cap_pdf(p)
            ir = parse_pdf(p, keep_image_data=False)
        texts = [ln.text.strip() for b in ir.pages[0].blocks for ln in b.lines]
        for t in _DROP_LINES:
            self.assertIn(t, texts)
        self.assertIn("T", texts)


# --------------------------------------- 8. two "columns" nobody set text in
class UnfilledColumnSplit(unittest.TestCase):
    def _lines(self, right_x1=341.0, full=False):
        lines = [_line("5.3.1 SHA-1", 72.0, 365.0, 151.0),
                 _line("5.3.2 SHA-224", 72.0, 515.0, 165.0),
                 _line("hex:", 72.0, 546.0, 93.0)]
        for i in range(8):
            top = 412.0 + 19.0 * i
            lines.append(_line("H%d(0)" % i, 236.0, top, 256.0))
            lines.append(_line("= 67452301", 266.0, top, right_x1))
        if full:
            lines += [_line("x" * 60, 72.0, 600.0 + 14 * i, 230.0)
                      for i in range(6)]
        return lines

    def test_a_table_of_short_rows_is_not_two_columns(self):
        self.assertTrue(I._split_unfilled(self._lines(), 236.0, 360.0,
                                          72.0, 540.0))

    def test_a_right_side_running_to_the_margin_is_a_column(self):
        # an index's right column runs on towards the margin (lshort)
        self.assertFalse(I._split_unfilled(self._lines(right_x1=520.0), 236.0,
                                           360.0, 72.0, 540.0))

    def test_a_side_set_in_full_lines_is_a_column(self):
        self.assertFalse(I._split_unfilled(self._lines(full=True), 236.0,
                                           360.0, 72.0, 540.0))


# ------------------------------- 9. floats on a page a booklet run merges
class FloatsBackIntoTheFlow(unittest.TestCase):
    def test_a_merged_page_keeps_its_pictures(self):
        from exactdoc.docxout import _floats_into_flow
        a = Para(runs=[Run("above", "Arial", 10.0, "#000000")],
                 bbox=(72.0, 100.0, 300.0, 112.0))
        b = Para(runs=[Run("below", "Arial", 10.0, "#000000")],
                 bbox=(72.0, 300.0, 300.0, 312.0))
        im = ImageEl(data=_PNG, ext="png", width=40.0, height=20.0)
        pg = PageLayout(3, [Chunk(elements=[a, b])])
        pg.floats = [FloatEl(el=im, bbox=(400.0, 200.0, 440.0, 220.0))]
        _floats_into_flow(pg)
        self.assertEqual(pg.floats, [])
        self.assertEqual(pg.chunks[0].elements, [a, im, b])


# ----------------------------- 10. a sidebar beside a column, not welded
def _two_span_line(a, ax0, ax1, b, bx0, bx1, top, size=12.0):
    sa = Span(a, "Times-Roman", size, "#000000", False, False, False, True,
              False, (ax0, top, ax1, top + 1.2 * size), (ax0, top + 0.95 * size))
    sb = Span(b, "Times-Roman", size, "#000000", False, False, False, True,
              False, (bx0, top, bx1, top + 1.2 * size), (bx0, top + 0.95 * size))
    return Line([sa, sb], (ax0, top, bx1, top + 1.2 * size))


class SidebarBesideColumn(unittest.TestCase):
    def test_a_line_welded_across_the_panel_side_stays_cut(self):
        # DOE OIG's highlights page: a shaded sidebar (x 41-239) beside the
        # findings (252-560); the parser joins the two halves of a shared
        # baseline into one line across the panel's side.
        side = [_line("Sidebar line number %d of the panel" % i, 54.0,
                      200.0 + 14.0 * i, 224.0) for i in range(20)]
        col = [_line("Findings line number %d runs across the right column"
                     % i, 252.0, 207.0 + 14.0 * i, 558.0) for i in range(20)]
        welded = [_two_span_line("determine whether the Department ", 54.0,
                                 224.0, "We suggest that the Department", 252.0,
                                 492.0, 523.0 + 14.0 * i) for i in range(3)]
        panel = DrawCmd(kind="fill", shape="rect", bbox=(40.6, 189.3, 238.6, 738.9),
                        fill="#e7f5f7", stroke=None, width=0.0, opacity=1.0,
                        n_items=1)
        page = PageIR(number=1, width=612.0, height=792.0,
                      blocks=[_block(side), _block(col), _block(welded)],
                      drawings=[panel])
        lay = I.infer(DocIR(path="x.pdf", pages=[page]))
        texts = []
        for ch in lay.pages[0].chunks:
            for e in ch.elements:
                texts.append(getattr(e, "text", "") or "")
                for row in getattr(e, "rows", []) or []:
                    for c in row:
                        texts += [q.text for q in (c.paras if c else [])]
        self.assertFalse(any("determine whether" in t and "We suggest" in t
                             for t in texts), texts)

    def test_only_a_sidebars_cut_stands(self):
        inside = _line("determine whether the Department", 54.0, 523.0, 224.0)
        beside = _line("We suggest that the Department", 252.0, 523.0, 492.0)
        far = _line("We suggest that the Department", 320.0, 523.0, 560.0)
        consumed = {id(inside)}
        side = (40.6, 189.3, 238.6, 738.9)
        self.assertTrue(I._sidebar_cut((None, None, [inside, beside]), [side],
                                       consumed, 520.0))
        # a panel a column wide is one column of two (y60's summary boxes)
        column = (36.0, 72.0, 293.0, 740.0)
        self.assertFalse(I._sidebar_cut((None, None, [inside, beside]),
                                        [column], consumed, 540.0))
        # text a column away is another column of the page (y59's brochure)
        self.assertFalse(I._sidebar_cut((None, None, [inside, far]), [side],
                                        consumed, 520.0))


# ------------------------------------------------ 7. a contents line's words
class ContentsLineWords(unittest.TestCase):
    def test_a_glued_marker_keeps_its_word_space(self):
        marker = _line("1.", 72.0, 237.0, 79.0, size=10.0)
        entry = _line("INTRODUCTION", 91.6, 237.0, 170.0, size=10.0)
        blocks = [_block([marker]), _block([entry])]
        out = I._merge_list_markers(blocks)
        lines = [ln for b in out for ln in b.lines]
        self.assertEqual([ln.text for ln in lines], ["1. INTRODUCTION"])

    def test_a_marker_that_abuts_its_item_is_left_as_drawn(self):
        marker = _line("1.", 72.0, 237.0, 79.0, size=10.0)
        entry = _line("INTRODUCTION", 79.5, 237.0, 160.0, size=10.0)
        out = I._merge_list_markers([_block([marker]), _block([entry])])
        self.assertEqual([ln.text for b in out for ln in b.lines],
                         ["1.INTRODUCTION"])

    def test_the_leaders_white_stays_around_the_tab(self):
        ln = _line("INTRODUCTION " + "." * 40 + " 3", 91.6, 237.0, 540.0,
                   size=10.0)
        p = I._leader_para(ln, 540.0, 72.0, 540.0)
        self.assertEqual(p.text, "INTRODUCTION \t 3")
        self.assertEqual(p.tab_stops, [(468.0, "right", "dot")])
        # a leader the producer drew against its words stays against them
        ln2 = _line("Introduction" + "." * 40 + "3", 91.6, 237.0, 540.0,
                    size=10.0)
        self.assertEqual(I._leader_para(ln2, 540.0, 72.0, 540.0).text,
                         "Introduction\t3")

    def test_the_gdocs_typed_leader_gives_up_a_dot_per_space(self):
        p = Para(runs=[Run("INTRODUCTION ", "Times-Roman", 10.0, "#000000"),
                       Run("\t", "Times-Roman", 10.0, "#000000", is_tab=True),
                       Run(" 3", "Times-Roman", 10.0, "#000000")],
                 tab_stops=[(468.0, "right", "dot")], leader_text="." * 10)
        q = _gdocs_typed_leader(p)
        self.assertEqual(q.runs[1].text, "." * 6)

    def test_the_gdocs_typed_leader_never_overruns_its_stop(self):
        # Live: FIPS 180-4's chapter entries, their text a marker space wider
        # than the source's, ran a few points past the stop and Docs put
        # each page number on a line of its own.
        from exactdoc.docxout import _runs_width, _text_metrics
        label = Run("2. DEFINITIONS ", "Times-Bold", 10.0, "#000000", bold=True,
                    serif=True)
        p = Para(runs=[label, Run("\t", "Times-Roman", 10.0, "#000000", is_tab=True),
                       Run("4", "Times-Bold", 10.0, "#000000", bold=True, serif=True)],
                 left_indent=19.6, tab_stops=[(468.0, "right", "dot")],
                 leader_text="." * 400)
        q = _gdocs_typed_leader(p)
        m = _text_metrics("gdocs")
        used = 19.6 + _runs_width(q.runs[:2], m, "gdocs") + \
            _runs_width(q.runs[3:], m, "gdocs")
        self.assertLess(used, 468.0)
        self.assertGreater(len(q.runs[1].text), 100)


if __name__ == "__main__":
    unittest.main()
