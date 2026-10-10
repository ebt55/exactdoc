"""A panel shaded line by line is one box under the gdocs profile.

Word shades a paragraph's lines one filled rectangle each, and inference
builds one box per rectangle: the NIST notice on the copyright page of y01,
y08 and y09 is thirteen one-line boxes. Written one bordered paragraph per
line, Google Docs set every line 1.5pt taller than the source (its own top and
bottom border) and re-wrapped the lines the source had justified tighter than
Times sets them -- y09's panel 2.6 lines taller on Google's export of the
71558af sweep. `docxout._gdocs_line_boxes` writes such a run as the one panel
it is: a single four-side box, each source paragraph one flowing paragraph,
the form y02's notice panel takes and Docs sets within 0.3pt of the source.

    python -m unittest tests.test_gdocs_line_panels
"""
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import docxout  # noqa: E402
from exactdoc.layout import Cell, Chunk, PageLayout, Para, Run, TableEl  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None


COLUMN = 468.0          # the page's text column; the panel's text spans it


def _wrap(text, width=COLUMN - 1.0):
    """`text` broken into lines greedily at `width` with the gdocs width
    tables -- the way the source's justified lines fill the panel."""
    m = docxout._text_metrics("gdocs")
    lines, cur = [], []
    for w in text.split():
        if cur and m.text_width(" ".join(cur + [w]), "Times New Roman", 10.0) > width:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    lines.append(" ".join(cur))
    return lines


def _line_box(text, top, pitch=11.5, full=True, after=0.0, fill="#dadada", pad_top=0.0):
    """One line of a shaded panel as inference builds it: a one-cell box whose
    only paragraph is the line, its baseline 9pt under the box top."""
    b1 = top + pad_top + 9.0
    p = Para(runs=[Run(text=text, font="Times-Roman", size=10.0, color="#000000")],
             leading=11.62, left_indent=9.5, src_lines=1,
             bbox=(72.0, b1 - 7.5, 540.0 if full else 200.0, b1 + 2.2))
    p._b1 = b1
    p._size1 = 10.0
    bot = top + pad_top + pitch + after
    cell = Cell(paras=[p], shading=fill, borders={}, pad=(pad_top, 9.5, after, 4.0))
    return TableEl(rows=[[cell]], col_widths=[487.0], row_heights=[bot - top],
                   left_indent=-9.5, role="box", bbox=(62.5, top, 549.5, bot))


ONE = ("Certain commercial entities, equipment, or materials may be identified in this "
       "document in order to describe an experimental procedure or concept adequately. Such "
       "identification is not intended to imply recommendation or endorsement by the "
       "institute, nor is it intended to imply that they are the best available.")
TWO = ("There may be references in this publication to other publications currently under "
       "development in accordance with its assigned statutory responsibilities, and they "
       "may be used before their completion.")


def _panel_page():
    els, top = [], 100.0
    rows = []
    for text, after in ((ONE, 6.0), (TWO, 0.0)):
        lines = _wrap(text)
        for k, ln in enumerate(lines):
            last = k == len(lines) - 1
            rows.append((ln, not last, after if last else 0.0))
    for k, (text, full, after) in enumerate(rows):
        box = _line_box(text, top, full=full, after=after, pad_top=7.8 if k == 0 else 0.0)
        els.append(box)
        top = box.bbox[3]
    body = Para(runs=[Run(text="After the panel.", font="Times-Roman", size=10.0,
                          color="#000000")], leading=12.0, src_lines=1,
                bbox=(72, top + 20, 200, top + 30))
    return PageLayout(number=3, chunks=[Chunk(elements=els + [body])]), \
        [len(_wrap(ONE)), len(_wrap(TWO))]


class Panels(unittest.TestCase):
    def test_a_run_of_line_boxes_is_one_panel_of_flowing_paragraphs(self):
        pg, counts = _panel_page()
        self.assertGreaterEqual(counts[0], 3)
        out = docxout._gdocs_line_boxes(pg, COLUMN)
        self.assertIsNot(out, pg)
        els = out.chunks[0].elements
        self.assertEqual(len(els), 2)                  # the panel, the body
        panel = els[0]
        self.assertEqual(panel.role, "box")
        self.assertEqual(panel.bbox[1], 100.0)
        self.assertAlmostEqual(panel.bbox[3], pg.chunks[0].elements[-2].bbox[3])
        paras = panel.rows[0][0].paras
        self.assertEqual([p.src_lines for p in paras], counts)
        self.assertEqual(paras[0].text, ONE)
        self.assertEqual(paras[1].text, TWO)
        self.assertEqual(paras[0].align, "justify")
        self.assertAlmostEqual(paras[0].leading, 11.5)
        self.assertEqual(paras[0].space_before, 0.0)
        # the source's 6pt between the paragraphs, in Word terms
        self.assertAlmostEqual(paras[1].space_before, 6.0, places=1)
        # the panel's own padding: the first line's top, the last line's bottom
        self.assertEqual(panel.rows[0][0].pad[0], 7.8)

    def test_the_layout_is_not_mutated(self):
        pg, _counts = _panel_page()
        n = len(pg.chunks[0].elements)
        before = [(id(el), el.rows[0][0].paras[0].text) for el in pg.chunks[0].elements[:-1]]
        docxout._gdocs_line_boxes(pg, COLUMN)
        self.assertEqual(len(pg.chunks[0].elements), n)
        self.assertEqual([(id(el), el.rows[0][0].paras[0].text)
                          for el in pg.chunks[0].elements[:-1]], before)

    def test_a_paragraph_docs_would_rewrap_is_left_as_written(self):
        # the same lines in a narrower column: joined, they would set in more
        # lines than the source's, which the panel's modelled height cannot pay
        pg, _counts = _panel_page()
        self.assertIs(docxout._gdocs_line_boxes(pg, COLUMN - 60.0), pg)

    def test_boxes_that_do_not_abut_stay_apart(self):
        a = _line_box("one line box standing on its own here", 100.0)
        b = _line_box("another line box well below the first", 140.0)
        pg = PageLayout(number=1, chunks=[Chunk(elements=[a, b])])
        self.assertIs(docxout._gdocs_line_boxes(pg, COLUMN), pg)

    def test_a_different_fill_is_a_different_panel(self):
        a = _line_box("one line box in grey shading here", 100.0, full=False)
        b = _line_box("the next line in another colour", a.bbox[3], fill="#ffeecc", full=False)
        pg = PageLayout(number=1, chunks=[Chunk(elements=[a, b])])
        self.assertIs(docxout._gdocs_line_boxes(pg, COLUMN), pg)

    def test_a_line_ending_on_a_hyphen_is_left_as_written(self):
        a = _line_box("a line that breaks a word across the line with a hyph-", 100.0)
        b = _line_box("enated word on the next line of the panel", a.bbox[3])
        pg = PageLayout(number=1, chunks=[Chunk(elements=[a, b])])
        self.assertIs(docxout._gdocs_line_boxes(pg, COLUMN), pg)

    def test_a_lone_line_box_is_left_as_written(self):
        a = _line_box("a single shaded line", 100.0)
        pg = PageLayout(number=1, chunks=[Chunk(elements=[a])])
        self.assertIs(docxout._gdocs_line_boxes(pg, COLUMN), pg)

    def test_short_lines_stay_their_own_paragraphs(self):
        # two short abutting lines (a heading band's): one panel, the lines
        # their own paragraphs, nothing to re-wrap
        a = _line_box("A shaded heading", 100.0, full=False)
        b = _line_box("and its second line", a.bbox[3], full=False)
        pg = PageLayout(number=1, chunks=[Chunk(elements=[a, b])])
        out = docxout._gdocs_line_boxes(pg, COLUMN)
        paras = out.chunks[0].elements[0].rows[0][0].paras
        self.assertEqual([p.text for p in paras], ["A shaded heading", "and its second line"])


def _panel_pdf(path):
    """A notice panel Word-style: each line its own filled rectangle, the
    paragraphs' lines justified, 6pt between the two paragraphs."""
    W, H = 612, 792
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Roman", 10)
    c.drawString(72, H - 90, "A paragraph of body text above the notice panel on this page.")
    paras = [
        "Certain commercial entities, equipment, or materials may be identified in this "
        "document in order to describe an experimental procedure or concept adequately. Such "
        "identification is not intended to imply recommendation or endorsement by the "
        "institute, nor is it intended to imply that the entities, materials, or equipment "
        "are necessarily the best available.",
        "There may be references in this publication to other publications currently under "
        "development in accordance with its assigned statutory responsibilities. The "
        "information in this publication, including concepts and methodologies, may be used "
        "by agencies even before the completion of such companion publications.",
    ]
    y, pitch, width = 130.0, 11.5, 468.0
    for pi, text in enumerate(paras):
        lines, cur = [], []
        for w in text.split():
            if c.stringWidth(" ".join(cur + [w]), "Times-Roman", 10) > width:
                lines.append(cur)
                cur = [w]
            else:
                cur.append(w)
        lines.append(cur)
        for li, ln in enumerate(lines):
            last = li == len(lines) - 1
            top = y - 9.0 - (7.8 if (pi == 0 and li == 0) else 0.0)
            bot = y + 2.5 + (6.0 if last else 0.0)
            c.setFillColorRGB(0.855, 0.855, 0.855)
            c.rect(62.5, H - bot, 487.0, bot - top, fill=1, stroke=0)
            c.setFillColorRGB(0, 0, 0)
            t = c.beginText(72, H - y)
            t.setFont("Times-Roman", 10)
            s = " ".join(ln)
            if not last:
                t.setWordSpace((width - c.stringWidth(s, "Times-Roman", 10)) / s.count(" "))
            t.textOut(s)
            c.drawText(t)
            y = bot + 9.0 if last else y + pitch
    c.setFont("Times-Roman", 10)
    c.drawString(72, H - (y + 30), "Comments on this publication may be submitted below.")
    c.showPage()
    c.save()
    return path


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from exactdoc.convert import convert
        from exactdoc.options import PDFIUM_GDOCS_CANDIDATE
        cls._dir = tempfile.TemporaryDirectory()
        pdf = _panel_pdf(os.path.join(cls._dir.name, "panel.pdf"))
        cls.gd = os.path.join(cls._dir.name, "gd.docx")
        cls.per_line = os.path.join(cls._dir.name, "per_line.docx")
        convert(pdf, cls.gd, options=PDFIUM_GDOCS_CANDIDATE)
        # the form before the panel join: one bordered paragraph a line
        keep = docxout._gdocs_line_boxes
        docxout._gdocs_line_boxes = lambda pg, content_w: pg
        try:
            convert(pdf, cls.per_line, options=PDFIUM_GDOCS_CANDIDATE)
        finally:
            docxout._gdocs_line_boxes = keep

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    @staticmethod
    def _boxed(path):
        with zipfile.ZipFile(path) as z:
            doc = z.read("word/document.xml").decode("utf-8")
        out = []
        for p in re.findall(r"<w:p(?: [^>]*)?>.*?</w:p>", doc, re.S):
            ppr = p.split("</w:pPr>")[0]
            sides = {s for s in ("top", "left", "bottom", "right")
                     if '<w:%s w:val="single"' % s in ppr}
            if sides:
                text = "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p))
                out.append((sides, 'w:jc w:val="both"' in ppr, text))
        return out

    def test_the_synthetic_panel_reproduces_the_line_box_form(self):
        boxed = self._boxed(self.per_line)
        self.assertGreaterEqual(len(boxed), 6)
        self.assertTrue(all(s == {"top", "left", "bottom", "right"} for s, _j, _t in boxed))

    def test_gdocs_writes_one_panel(self):
        boxed = self._boxed(self.gd)
        self.assertEqual(len(boxed), 2)                       # two source paragraphs
        (s0, j0, t0), (s1, j1, t1) = boxed
        self.assertEqual(s0, {"top", "left", "right"})
        self.assertEqual(s1, {"left", "bottom", "right"})
        self.assertTrue(j0 and j1)
        self.assertTrue(t0.startswith("Certain commercial") and
                        t0.endswith("the best available."), t0)
        self.assertNotIn("  ", t0)
        self.assertTrue(t1.startswith("There may be") and
                        t1.endswith("companion publications."), t1)

    def test_no_word_is_lost_or_doubled(self):
        words = lambda rows: " ".join(t for _s, _j, t in rows).split()
        self.assertEqual(words(self._boxed(self.gd)), words(self._boxed(self.per_line)))


if __name__ == "__main__":
    unittest.main()
