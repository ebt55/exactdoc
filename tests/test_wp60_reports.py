"""Long Word-made reports: a highlights sidebar beside its column, and a framed
chart (WP60).

Two mechanisms, each of which cost a long report a page wherever it occurred,
and every page after it its place.

* **The highlights sidebar.** An OIG report opens on a "highlights" page: a
  shaded panel down the left (x 37-191) and the findings column beside it,
  starting 5pt from the panel's fill. Three things kept the page from reading
  side by side, and the panel stood above its column:
    - the gutter search wanted 6pt of white (SBS_MIN_GUTTER), where a drawn
      panel's edge is itself the boundary (`_side_splits`, PANEL_MIN_GUTTER);
    - a cut at the panel edge was judged on its own piece -- a bullet's
      hanging continuation 25pt off the panel -- not on the column, and welded
      back it read across sidebar and column (`_sidebar_boxes`);
    - the page's footer, printed without its folio on this one page, joined
      the band and broke the panel's cell (`foot_not_band`).
* **The framed chart.** A chart's frame was built as a box holding the
  chart's labels as paragraphs, and the chart's ink as a figure after it: the
  labels twice, stacked (`_frames_to_figures`).

Every reading is the standard profile's (`_wp60`, keyed on the gdocs
profile's `tab_layouts=False`).

    python -m unittest tests.test_wp60_reports
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from exactdoc import infer as I                                 # noqa: E402
from exactdoc.layout import FigureEl, Para, TableEl             # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                     # pragma: no cover
    _canvas = None

W, H = 612.0, 792.0
WORDS = ("the department generally implemented the two pillars we reviewed "
         "which focused on surging resources to the border and increasing "
         "efficiencies for migrant processing during the period").split()


def _line(k, n=11):
    return " ".join(WORDS[(k * 3 + i) % len(WORDS)] for i in range(n))


def _text(c, x, top, s, size=11, font="Helvetica"):
    c.setFont(font, size)
    c.drawString(x, H - top - size, s)


def _joined(c, top, pieces, size=11, font="Helvetica"):
    """Several pieces on one baseline in ONE text object, as Word writes a
    line that tabs across: the parser reads them as one line."""
    t = c.beginText()
    t.setFont(font, size)
    t.setTextOrigin(pieces[0][0], H - top - size)
    x0 = pieces[0][0]
    for x, txt in pieces:
        t.moveCursor(x - x0, 0)
        x0 = x
        t.textOut(txt)
        t.setTextOrigin(x, H - top - size)
    c.drawText(t)


def _footer(c, folio):
    pieces = [(72, "www.example.gov")]
    if folio is not None:
        pieces.append((300, str(folio)))
    pieces.append((500, "RPT-25-01"))
    _joined(c, 745, pieces, 9)


def _body_page(c, k):
    for i in range(38):
        _text(c, 72, 80 + 16 * i, _line(k * 40 + i, 13))
    _footer(c, k + 2)


def _sidebar_pdf(path, pages=3):
    """Page 1: a highlights page -- a tinted panel x 37-191, sidebar text in
    it, the findings column from x 196 (5pt off the fill) with a bulleted
    list whose hanging continuation (x 216) shares a baseline with a sidebar
    line, and a footer without a folio. Then body pages with the folio."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    _text(c, 180, 30, "AGENCY HIGHLIGHTS", 18, "Helvetica-Bold")
    c.setFillColorRGB(0.84, 0.89, 0.92)
    c.rect(37, H - 715, 154, 607, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    _text(c, 46, 120, "September 26, 2025", 12, "Helvetica-Bold")
    _text(c, 46, 160, "Why We Did This", 14, "Helvetica-Bold")
    side = [" ".join(WORDS[(i * 2 + j) % len(WORDS)] for j in range(4))
            for i in range(22)]
    side_y = {190 + 15 * i: t for i, t in enumerate(side)}
    _text(c, 196, 110, "What We Found", 14, "Helvetica-Bold")
    col = []                                       # (top, x, text)
    y = 145
    for i in range(3):
        col.append((y, 196, _line(i, 10)))
        y += 15
    y += 5
    for b in range(3):
        col.append((y, 198, "•"))
        col.append((y, 216, _line(20 + b, 9)))
        for j in range(2):
            y += 15
            col.append((y, 216, _line(30 + b * 2 + j, 9)))
        y += 20
    for i in range(14):
        col.append((y, 196, _line(40 + i, 10)))
        y += 15
    # the sidebar's lines set on the column's baselines where they meet:
    # a sidebar line and a hanging continuation in ONE text object
    for top, x, t in col:
        st = side_y.pop(top, None)
        if st is not None and x == 216:
            _joined(c, top, [(46, st), (216, t)], 10)
        else:
            _text(c, x, top, t)
            if st is not None:
                _text(c, 46, top, st, 10)
    for top, t in side_y.items():
        _text(c, 46, top, t, 10)
    _footer(c, None)
    c.showPage()
    for k in range(pages - 1):
        _body_page(c, k)
        c.showPage()
    c.save()


def _chart_pdf(path, frame=True, labels=True):
    """Page 1: a paragraph, a bar chart on a white chart area (the frame, as
    Word and Excel draw it: a white-filled rectangle under the plot), its
    axis ticks, data labels and legend inside the area but beyond the bars'
    reach, a paragraph. Then a body page."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    for i in range(2):
        _text(c, 72, 105 + 15 * i, _line(i, 13))
    top, bot = 140, 480                              # frame, top-down
    if frame:
        c.setFillColorRGB(1, 1, 1)
        c.rect(120, H - bot, 420, bot - top, stroke=0, fill=1)
    base = 430
    heights = [80, 170, 200, 140, 110, 60]
    # the plot: one drawn path, as a chart's series is one shape
    c.setFillColorRGB(0.1, 0.25, 0.5)
    path = c.beginPath()
    for k, hgt in enumerate(heights):
        path.rect(160 + 60 * k, H - base, 30, hgt)
    path.rect(150, H - base - 1, 375, 1)          # the axis joins the bars
    c.drawPath(path, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    if labels:
        for k, hgt in enumerate(heights):
            x = 160 + 60 * k
            _text(c, x + 4, base - hgt - 30, str(hgt), 10)
            _text(c, x + 4, base - hgt - 44, "+%d%%" % (hgt // 7), 10)
            _text(c, x + 4, base - hgt - 58, "n=%d" % (hgt // 3), 10)
    if labels:
        for k in range(len(heights)):
            _text(c, 160 + 60 * k + 3, base + 22, "20%02d" % (16 + k), 10)
        for t in range(0, 250, 50):
            _text(c, 128, base - t - 5, str(t), 10)
        _text(c, 230, 462, "Federal    Non-Federal    Total", 10)
    c.setFillColorRGB(0, 0, 0)
    for i in range(2):
        _text(c, 72, 500 + 15 * i, _line(10 + i, 13))
    c.showPage()
    _body_page(c, 0)
    c.showPage()
    c.save()


def _tinted_table_pdf(path):
    """A tinted panel holding a 3x3 grid of short words -- no figure in it."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFillColorRGB(0.9, 0.93, 0.96)
    c.rect(72, H - 300, 468, 150, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    for r in range(3):
        for k in range(3):
            _text(c, 90 + 160 * k, 170 + 40 * r, "Cell %d%d" % (r, k))
    c.showPage()
    c.save()


def _callout_pdf(path):
    """A framed callout: a small drawn icon beside a wrapped paragraph."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setStrokeColorRGB(0.2, 0.2, 0.2)
    c.rect(72, H - 300, 468, 140, stroke=1, fill=0)
    c.setFillColorRGB(0.9, 0.6, 0.1)
    c.circle(100, H - 190, 12, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    for i in range(6):
        _text(c, 130, 175 + 15 * i, _line(i, 12))
    c.showPage()
    c.save()


def _infer(pdf, tab_layouts=True):
    from exactdoc.backend import get_backend
    from exactdoc.dialect import normalize
    from exactdoc.input import parse as parse_input
    return I.infer(normalize(parse_input(get_backend("pdfium"), pdf)),
                   anchored=True, anchor_pictures=True, tab_layouts=tab_layouts)


class _Rule:
    """`with _Rule("figure_frame", True):` -- one WP60 switch, for a test."""

    def __init__(self, rule, on):
        self.rule, self.on = rule, on

    def __enter__(self):
        self.saved = I.WP60_RULES.get(self.rule)
        I.WP60_RULES[self.rule] = self.on

    def __exit__(self, *exc):
        I.WP60_RULES[self.rule] = self.saved


def _els(pg):
    return [el for ch in pg.chunks for el in ch.elements]


@unittest.skipUnless(_canvas is not None, "needs reportlab")
class TheHighlightsSidebar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = os.path.join(cls._dir.name, "sidebar.pdf")
        _sidebar_pdf(cls.pdf)
        cls.lay = _infer(cls.pdf)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_the_panel_and_its_column_are_one_side_by_side_row(self):
        tabs = [e for e in _els(self.lay.pages[0])
                if isinstance(e, TableEl) and e.role == "layout"]
        self.assertEqual(len(tabs), 1, "one layout row: panel | column")
        cells = tabs[0].rows[0]
        self.assertTrue(cells[0].shading, "the panel IS the shaded cell")
        right = " ".join(p.text for p in cells[-1].paras)
        self.assertIn("What We Found", right)
        self.assertNotIn("www.example.gov", " ".join(p.text for p in cells[0].paras))

    def test_no_line_reads_across_panel_and_column(self):
        for e in _els(self.lay.pages[0]):
            if isinstance(e, Para) and e.bbox and e.bbox[1] > 108:
                self.assertFalse(e.bbox[0] < 191 < e.bbox[2] and e.bbox[2] > 300,
                                 "a paragraph spans the panel edge: %r" % e.text[:60])

    def test_the_gdocs_profile_keeps_its_reading(self):
        g = _infer(self.pdf, tab_layouts=False)
        self.assertFalse([e for e in _els(g.pages[0])
                          if isinstance(e, TableEl) and e.role == "layout"])

    def test_each_reading_has_its_switch(self):
        for rule in ("sidebar_per_box", "panel_gutter", "foot_not_band"):
            self.assertIn(rule, I.WP60_RULES)

    @unittest.skipUnless(shutil.which("soffice") and importlib.util.find_spec("fitz"),
                         "renders with LibreOffice and reads with PyMuPDF")
    def test_it_renders_page_for_page(self):
        sys.path.insert(0, os.path.join(ROOT, "testkit"))
        import fitz
        import harness
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        out = os.path.join(self._dir.name, "s.docx")
        convert(self.pdf, out, options=RAW, max_pages=0)
        r = fitz.open(harness.docx_to_pdf(out, self._dir.name))
        self.assertEqual(len(r), 3)
        self.assertIn("What We Found", r[0].get_text())


def _ln(x0, top, x1, text="word word word", size=11.0):
    from exactdoc.model import Line, Span
    bb = (float(x0), float(top), float(x1), float(top) + size + 2)
    return Line(spans=[Span(text=text, font="Helvetica", size=size, color="#000000",
                            bold=False, italic=False, mono=False, serif=False,
                            superscript=False, bbox=bb, origin=(bb[0], bb[3] - 2))],
                bbox=bb)


def _blk(lines):
    from exactdoc.model import TextBlock
    bb = (min(l.bbox[0] for l in lines), min(l.bbox[1] for l in lines),
          max(l.bbox[2] for l in lines), max(l.bbox[3] for l in lines))
    return TextBlock(lines=list(lines), bbox=bb)


class ThePanelIsJudgedWhole(unittest.TestCase):
    """`_sidebar_boxes`: the column's edge, not the cut piece's."""

    def setUp(self):
        self.box = (37.0, 108.0, 191.0, 715.0)
        # a sidebar line and a bullet's hanging continuation, joined and cut
        self.inside = _ln(46, 300, 170, "the sidebar text")
        self.outside = _ln(216, 300, 550, "from the components and partners")
        self.joined = _ln(46, 300, 550, "joined")
        self.column = [_ln(196, 140 + 15 * i, 550) for i in range(8)]
        self.blocks = [_blk([self.inside, self.outside]), _blk(self.column)]
        self.cut = (self.blocks[0], self.joined, [self.inside, self.outside])
        self.consumed = {id(self.inside)}

    def test_a_hanging_piece_does_not_unmake_a_sidebar(self):
        self.assertFalse(I._sidebar_cut(self.cut, [self.box], self.consumed, 486.0),
                         "the per-cut test measures the 25pt piece")
        self.assertIn(self.box, I._sidebar_boxes([self.cut], [self.box], self.blocks,
                                                 self.consumed, 486.0))

    def test_a_panel_far_from_its_neighbour_is_no_sidebar(self):
        far = [_ln(260, 140 + 15 * i, 550) for i in range(8)]   # 5.3em off
        blocks = [self.blocks[0], _blk(far)]
        self.assertFalse(I._sidebar_boxes([self.cut], [self.box], blocks,
                                          self.consumed, 486.0))

    def test_a_wide_panel_is_a_column_not_a_sidebar(self):
        wide = (37.0, 108.0, 300.0, 715.0)
        self.assertFalse(I._sidebar_boxes([self.cut], [wide], self.blocks,
                                          self.consumed, 486.0))


class TheFootIsNoSide(unittest.TestCase):
    """`foot_not_band`: a footer line under both sides ends the band."""

    def _items(self):
        from exactdoc.layout import Cell
        panel = TableEl(rows=[[Cell(shading="#D6E3EB", borders={})]],
                        col_widths=[154.0], role="box", bbox=(37.0, 108.0, 191.0, 715.0))
        col = _blk([_ln(196, 110 + 15 * i, 550) for i in range(38)])
        foot_l = _blk([_ln(72, 746, 145, "www.example.gov", 9)])
        foot_r = _blk([_ln(500, 746, 544, "RPT-25-01", 9)])
        return [("el", panel.bbox, panel), ("blk", col.bbox, col),
                ("blk", foot_l.bbox, foot_l), ("blk", foot_r.bbox, foot_r)]

    def _band(self, on):
        from exactdoc.model import PageIR
        saved = dict(I.WP60_RULES)
        I.WP60_RULES["foot_not_band"] = on
        try:
            regs = I._sbs_regions(self._items(), PageIR(number=1, width=W, height=H),
                                  72.0, 558.0)
        finally:
            I.WP60_RULES.clear()
            I.WP60_RULES.update(saved)
        return [r for r in regs if r[0] == "band"]

    def test_the_footer_stays_out_of_the_sidebar_band(self):
        band = self._band(True)
        self.assertEqual(len(band), 1)
        self.assertLess(band[0][5], 730, "the band ends with the panel, not the foot")

    def test_without_the_rule_it_joins_the_band(self):
        band = self._band(False)
        self.assertTrue(band)
        self.assertGreater(band[0][5], 745)


class TheFooterEcho(unittest.TestCase):
    """`_drop_footer_echoes`: a foot line below the panels that the footer
    part already prints is that footer."""

    def _run(self, lines, panel=True, footer="www.example.gov 4 RPT-25-01",
             wide=False):
        from exactdoc.layout import Cell, HFPart
        from exactdoc.model import PageIR
        els = []
        if panel:
            els.append(TableEl(rows=[[Cell(shading="#D6E3EB", borders={})]],
                               col_widths=[154.0], role="box",
                               bbox=(37.0, 108.0, 300.0 if wide else 191.0, 715.0)))
        part = HFPart(elements=[Para(runs=[], leading=11.0)])
        part.elements[0].runs = []
        from exactdoc.layout import Run
        part.elements[0].runs = [Run(text=footer, font="Helvetica", size=9,
                                     color="#000000")]
        consumed = set()
        I._drop_footer_echoes([_blk(lines)], consumed, els,
                              PageIR(number=4, width=W, height=H), [part, None, None],
                              486.0)
        return consumed

    def test_the_folio_less_footer_is_the_footer(self):
        foot = _ln(72, 746, 145, "www.example.gov", 9)
        tag = _ln(500, 746, 544, "RPT-25-01", 9)
        self.assertEqual(self._run([foot, tag]), {id(foot), id(tag)})

    def test_body_text_and_unknown_lines_stay(self):
        body = _ln(196, 700, 550, "the findings continue here")
        other = _ln(72, 746, 300, "Printed on recycled paper", 9)
        self.assertEqual(self._run([body, other]), set())

    def test_no_panel_no_rule(self):
        foot = _ln(72, 746, 145, "www.example.gov", 9)
        self.assertEqual(self._run([foot], panel=False), set())

    def test_a_column_wide_box_is_no_sidebar_page(self):
        """MMWR's summary boxes fill a column of two (0.48 of the measure):
        their pages keep their foot lines."""
        foot = _ln(72, 746, 145, "www.example.gov", 9)
        self.assertEqual(self._run([foot], wide=True), set())


@unittest.skipUnless(_canvas is not None, "needs reportlab")
class TheFramedChart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = os.path.join(cls._dir.name, "chart.pdf")
        _chart_pdf(cls.pdf)
        with _Rule("figure_frame", True):
            cls.lay = _infer(cls.pdf)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_the_frame_is_the_charts_and_its_labels_are_not_text(self):
        els = _els(self.lay.pages[0])
        figs = [e for e in els if isinstance(e, FigureEl)]
        self.assertEqual(len(figs), 1)
        self.assertLessEqual(figs[0].clip[1], 141)
        self.assertGreaterEqual(figs[0].clip[3], 479)
        self.assertFalse([e for e in els if isinstance(e, TableEl) and e.role == "box"])
        text = " ".join(e.text for e in els if isinstance(e, Para))
        for label in ("2016", "200", "170"):
            self.assertNotIn(label, text.split())

    def test_the_gdocs_profile_keeps_its_reading(self):
        g = _infer(self.pdf, tab_layouts=False)
        self.assertTrue([e for e in _els(g.pages[0])
                         if isinstance(e, TableEl) and e.role == "box"])

    def test_it_is_off_by_default(self):
        """Census (WP60): as a frame-to-figure rule it rasterises chart labels
        that were text -- every one of them also painted by the picture, but
        the page's text LCS falls -- and it flips 40 boxes across 9 documents.
        Off until that trade is decided."""
        self.assertFalse(I.WP60_RULES["figure_frame"])

    def test_a_tinted_table_stays_text(self):
        d = tempfile.mkdtemp(dir=self._dir.name)
        pdf = os.path.join(d, "t.pdf")
        _tinted_table_pdf(pdf)
        with _Rule("figure_frame", True):
            els = _els(_infer(pdf).pages[0])
        self.assertFalse([e for e in els if isinstance(e, FigureEl)])
        text = " ".join(p.text for e in els for p in
                        ([e] if isinstance(e, Para) else
                         [p for row in getattr(e, "rows", []) for c in row if c
                          for p in c.paras]))
        self.assertIn("Cell 11", text)

    def test_a_callout_with_an_icon_stays_a_box(self):
        d = tempfile.mkdtemp(dir=self._dir.name)
        pdf = os.path.join(d, "c.pdf")
        _callout_pdf(pdf)
        with _Rule("figure_frame", True):
            els = _els(_infer(pdf).pages[0])
        boxes = [e for e in els if isinstance(e, TableEl) and e.role == "box"]
        self.assertEqual(len(boxes), 1)
        self.assertIn("department", " ".join(p.text for row in boxes[0].rows
                                              for c in row if c for p in c.paras))

    @unittest.skipUnless(shutil.which("soffice") and importlib.util.find_spec("fitz"),
                         "renders with LibreOffice and reads with PyMuPDF")
    def test_it_renders_page_for_page(self):
        sys.path.insert(0, os.path.join(ROOT, "testkit"))
        import fitz
        import harness
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        out = os.path.join(self._dir.name, "c.docx")
        with _Rule("figure_frame", True):
            convert(self.pdf, out, options=RAW, max_pages=0)
        r = fitz.open(harness.docx_to_pdf(out, self._dir.name))
        self.assertEqual(len(r), 2)


if __name__ == "__main__":
    unittest.main()
