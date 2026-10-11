"""An accent-bar panel under the gdocs profile: its wrap edge and its sides.

01_whitepaper_market's "Key Insight" panel is a tinted rect (x 57-555) with a
3pt blue bar down its left edge and two lines of text (69-545.0). The gdocs
profile writes a box as bordered paragraphs (`docxout._write_box_paragraphs`),
and on the README's hero picture (Google's export of the 2026-10-11 final
sweep) Docs set it with three more words on its first line and a full blue
frame, where the source, Word and LibreOffice (both the standard profile's
one-cell table) show the bar alone and the source's wrap. Two defects of the
paragraph form, both in the DOCX, neither in Docs:

1. The right indent was the box-edge-to-text inset (10pt), but `w:ind right`
   is measured from the COLUMN's edge. Right only where the box's edge meets
   the column's; on the cover page, which the gdocs profile writes with zero
   side margins (the column is the page), the text ran to 602. A box narrower
   than its column wrapped past its own edge the same way on any page.
   `docxout._gdocs_box_right`: the text wraps at the box's own text edge (its
   right edge less the cell's right pad, the edge `infer.build_box` flowed its
   lines against) and the right rail stands on the box's edge.
2. A side the source did not stroke borrowed the left bar. Such a side is now
   a rail in the fill's colour, as an unstroked filled panel's are.

    python -m unittest tests.test_gdocs_accent_panel
"""
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None

W, H = 612.0, 792.0
BODY = ("Modern inference workloads exhibit sharply bimodal traffic patterns, with sustained "
        "baseline demand punctuated by bursts that exceed steady-state volume by an order of "
        "magnitude. Provisioning for peak wastes capacity; provisioning for baseline degrades "
        "latency guarantees precisely when demand is highest.")
NOTE = ("Key Insight: Across the 41 organizations surveyed, tiered inference reduced cost per "
        "thousand requests by a median of 38% while improving p99 latency by 22%, and the "
        "adoption cost was recovered within two budget cycles at every site we measured.")
PAD_L, PAD_R = 12.0, 10.0
# (page, x0, x1): a full-column panel and a narrower one on a cover-band page
# (zero side margins under gdocs) and on an ordinary page
PANELS = ((1, 69.0, 543.0), (1, 120.0, 430.0), (2, 69.0, 543.0), (2, 160.0, 500.0))


def _wrap(c, text, width, font="Helvetica", size=10.0):
    lines, cur = [], []
    for w in text.split():
        if cur and c.stringWidth(" ".join(cur + [w]), font, size) > width:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    lines.append(" ".join(cur))
    return lines


def _accent_pdf(path):
    """Two pages; returns {(page, x0): widest line's right edge} per panel."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    widest = {}

    def body(y):
        c.setFont("Helvetica", 10.5)
        c.setFillColorRGB(0.12, 0.16, 0.22)
        for ln in _wrap(c, BODY, 468.0, size=10.5):
            c.drawString(72.0, H - y, ln)
            y += 15.0
        return y + 10.0

    def panel(page, y, x0, x1):
        lines = _wrap(c, NOTE, x1 - x0 - PAD_L - PAD_R)
        bot = y + 12.0 + 14.0 * len(lines) + 4.0
        c.setFillColorRGB(0.937, 0.965, 1.0)
        c.rect(x0, H - bot, x1 - x0, bot - y, fill=1, stroke=0)
        c.setStrokeColorRGB(0.145, 0.388, 0.922)
        c.setLineWidth(3.0)
        c.line(x0, H - y, x0, H - bot)
        c.setFillColorRGB(0.12, 0.16, 0.22)
        c.setFont("Helvetica", 10.0)
        for k, ln in enumerate(lines):
            c.drawString(x0 + PAD_L, H - (y + 20.0 + 14.0 * k), ln)
        widest[(page, x0)] = x0 + PAD_L + max(c.stringWidth(ln, "Helvetica", 10.0)
                                              for ln in lines)
        return bot + 18.0

    c.setFillColorRGB(0.118, 0.227, 0.373)
    c.rect(0, H - 150, W, 150, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(72, H - 80, "The Economics of Tiered Inference")
    y = body(190.0)
    for page in (1, 2):
        if page == 2:
            c.showPage()
            y = body(72.0)
        for _p, x0, x1 in (p for p in PANELS if p[0] == page):
            y = body(panel(page, y, x0, x1))
    c.showPage()
    c.save()
    return widest


def _sections(doc):
    """[(page_w, margin_l, margin_r, [paragraph xml])] in document order."""
    body = doc.split("<w:body>")[1]
    out, pend = [], []
    for el in re.findall(r"<w:p(?: [^>]*)?>.*?</w:p>|<w:sectPr(?: [^>]*)?>.*?</w:sectPr>",
                         body, re.S):
        sect = el if el.startswith("<w:sectPr") else None
        if sect is None:
            pend.append(el)
            m = re.search(r"<w:sectPr(?: [^>]*)?>.*?</w:sectPr>", el, re.S)
            sect = m.group(0) if m else None
        if sect is not None:
            g = lambda a: int(re.search(r'<w:%s w:%s' % a, sect).group(1)) / 20.0  # noqa: E731
            out.append((g(('pgSz', 'w="(\\d+)"')),
                        g(('pgMar[^>]*', 'left="(-?\\d+)"')),
                        g(('pgMar[^>]*', 'right="(-?\\d+)"')), pend))
            pend = []
    return out


def _boxed(path):
    """[(text left, wrap edge, right rail x, {side: colour})] of every
    paragraph carrying a right border."""
    with zipfile.ZipFile(path) as z:
        doc = z.read("word/document.xml").decode("utf-8")
    out = []
    for pw, ml, mr, paras in _sections(doc):
        for p in paras:
            ppr = p.split("</w:pPr>")[0]
            if "<w:pBdr>" not in ppr or "<w:right w:val" not in ppr:
                continue
            ind = re.search(r"<w:ind ([^/]*)/>", ppr)
            ind = ind.group(1) if ind else ""
            at = lambda a: re.search(r'w:%s="(-?\d+)"' % a, ind)  # noqa: E731
            il, ir = ((int(at(a).group(1)) / 20.0 if at(a) else 0.0)
                      for a in ("left", "right"))
            sides = {s: (int(sp), c) for s, sp, c in re.findall(
                r'<w:(top|left|bottom|right) w:val="single" w:sz="\d+" '
                r'w:space="(\d+)" w:color="(\w+)"', ppr)}
            edge = pw - mr - ir
            out.append((ml + il, edge, edge + sides["right"][0],
                        {s: c for s, (_sp, c) in sides.items()}))
    return out


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class AccentPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from exactdoc.convert import convert
        from exactdoc.options import PDFIUM_GDOCS_CANDIDATE, RAW
        cls._dir = tempfile.TemporaryDirectory()
        pdf = os.path.join(cls._dir.name, "accent.pdf")
        cls.widest = _accent_pdf(pdf)
        cls.gd = os.path.join(cls._dir.name, "gd.docx")
        cls.std = os.path.join(cls._dir.name, "std.docx")
        convert(pdf, cls.gd, options=PDFIUM_GDOCS_CANDIDATE)
        convert(pdf, cls.std, options=RAW)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def _panels(self):
        boxed = _boxed(self.gd)
        self.assertEqual(len(boxed), len(PANELS))
        return list(zip(PANELS, boxed))

    def test_each_panel_wraps_at_its_own_text_edge(self):
        for (page, x0, x1), (left, edge, _rail, _c) in self._panels():
            self.assertAlmostEqual(left, x0 + PAD_L, delta=0.6)
            # never inside the widest source line, never past the box's text
            # edge (its right edge less the cell's 4pt pad)
            self.assertGreaterEqual(edge, self.widest[(page, x0)] - 0.05,
                                    (page, x0, edge))
            self.assertLessEqual(edge, x1 - 4.0 + 0.6, (page, x0, edge))

    def test_the_right_rail_stands_on_the_box_edge(self):
        for (page, x0, x1), (_l, _e, rail, _c) in self._panels():
            self.assertAlmostEqual(rail, x1, delta=0.6, msg=(page, x0))

    def test_only_the_bar_is_drawn_in_the_bar_colour(self):
        for _panel, (_l, _e, _r, colours) in self._panels():
            self.assertEqual(colours["left"], "2563EB")
            self.assertEqual({c for s, c in colours.items() if s != "left"},
                             {"EFF6FF"})

    def test_the_standard_profile_keeps_its_one_cell_table(self):
        with zipfile.ZipFile(self.std) as z:
            doc = z.read("word/document.xml").decode("utf-8")
        self.assertEqual(_boxed(self.std), [])
        self.assertEqual(doc.count('w:fill="EFF6FF"'), len(PANELS))
        self.assertEqual(len(re.findall(r'<w:left w:val="single" w:sz="24" '
                                        r'w:space="0" w:color="2563EB"/>', doc)),
                         len(PANELS))


if __name__ == "__main__":
    unittest.main()
