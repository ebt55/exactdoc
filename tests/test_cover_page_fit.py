"""A full-sheet cover stays one page, and states no footer it does not print (WP50).

The mechanism. A designed cover is often one filled shape the size of the
sheet -- a Word "full-page shape", which Word exports bled past the paper on
every side -- with the title set on it in white. `detect_hf.top_bands` reads
any full-width fill that starts at the page top as a COVER BAND, and the band
becomes one table row whose height is content-driven: the paragraphs spaced
from the fill's top and a bottom pad to its foot (`infer.build_band_table`).
For a full-sheet fill that row is taller than any page box (a fill drawn from
y -18 to H + 18 is 36pt taller than the paper), so the renderer split it: the
cover took two pages and every later page sat one place late. And the cover
section was given `footer_first or footer_default`, so a cover that prints
no folio carried the running footer -- whose height came out of the cover's
box as well -- and the unnumbered lead-in after it carried the numbered
section's footer with a count that had not started.

`docxout._fit_cover_band` keeps the band on the sheet and inside the cover
section's body box (from the white the source never shows: the off-sheet
overhang, then the bottom pad); `docxout._cover_states_no_footer` and the
after-cover branch state what `_infer_body` decided. Standard profile only:
the Google Docs profile's cover form is unmeasured live in this shape and is
held byte-identical (asserted below).

    python -m unittest tests.test_cover_page_fit
"""
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from exactdoc import docxout as D                              # noqa: E402
from exactdoc.layout import Cell, DocLayout, Para, Run, TableEl  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None

W, H = 612.0, 792.0
LINE = ("The board reviewed the year's results and the programme for the "
        "next one in detail.")


def _cover_pdf(path, bleed=18.0, lead_in=2, numbered=6):
    """Page 1: a full-sheet dark shape (bled `bleed` past the paper, as Word
    exports a full-page shape) with a white title on it and no folio. Then
    `lead_in` unnumbered pages of body text, then `numbered` pages whose foot
    prints "R-1", "R-2", ... -- a section-local running footer."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFillColorRGB(0.13, 0.12, 0.12)
    c.rect(-bleed, -bleed, W + 2 * bleed, H + 2 * bleed, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(90, H - 250, "Northwind Holdings")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(300, H - 520, "2025 Annual Review")
    c.showPage()
    for pg in range(lead_in + numbered):
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Times-Roman", 11)
        for i in range(30):
            c.drawString(72, H - 90 - 14 * i, LINE)
        if pg >= lead_in:
            c.setFont("Times-Roman", 9)
            c.drawCentredString(W / 2, 40, "R-%d" % (pg - lead_in + 1))
        c.showPage()
    c.save()


def _convert(pdf, out, gdocs=False):
    from exactdoc.convert import convert
    from exactdoc.options import PDFIUM_GDOCS_CANDIDATE, RAW
    convert(pdf, out, options=PDFIUM_GDOCS_CANDIDATE if gdocs else RAW,
            max_pages=0)
    with zipfile.ZipFile(out) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()
                if n.startswith("word/") and n.endswith((".xml", ".rels"))}


def _sections(doc_xml):
    return re.findall(r"<w:sectPr\b.*?</w:sectPr>", doc_xml, re.S)


def _rels(parts):
    return dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"',
                           parts["word/_rels/document.xml.rels"])) \
        if "word/_rels/document.xml.rels" in parts else {}


# --------------------------------------------------------------- the clamp
def _band(y0, y1, pad_bot, sb0=100.0):
    cell = Cell(shading="#222222", borders={})
    cell.paras = [Para(runs=[Run(text="Title", font="Helvetica", size=26,
                                 color="#FFFFFF")], leading=30.0)]
    cell.paras[0].space_before = sb0
    cell.pad = (0.0, 10.0, pad_bot, 0.0)
    return TableEl(rows=[[cell]], col_widths=[W], row_heights=[y1 - y0],
                   role="band", bbox=(0.0, y0, W, y1))


def _lay(cover_top=0.0, margin_b=36.0):
    lay = DocLayout(page_w=W, page_h=H)
    lay.margin_b = margin_b
    lay.cover_top = cover_top
    return lay


class TheClamp(unittest.TestCase):
    def test_a_band_inside_its_box_is_untouched(self):
        """01/04/c1's strips (112-174pt) must not move: byte-identity."""
        b = _band(0.0, 174.0, pad_bot=24.0, sb0=68.2)
        D._fit_cover_band(b, _lay(), None, None, 36.0)
        self.assertEqual(b.rows[0][0].pad, (0.0, 10.0, 24.0, 0.0))
        self.assertEqual(b.rows[0][0].paras[0].space_before, 68.2)

    def test_the_off_sheet_top_comes_out_of_the_first_space(self):
        """Spaced from y -18, the title sat 18pt low on a page whose band
        starts at the paper's top."""
        b = _band(-18.0, H + 18.0, pad_bot=400.0, sb0=267.0)
        D._fit_cover_band(b, _lay(), None, None, 36.0)
        self.assertAlmostEqual(b.rows[0][0].paras[0].space_before, 249.0)

    def test_a_full_sheet_band_fits_the_cover_box(self):
        lay = _lay(margin_b=36.0)
        b = _band(-18.0, H + 18.0, pad_bot=400.0, sb0=267.0)
        D._fit_cover_band(b, lay, None, None, 36.0)
        removed = 18.0 + (400.0 - b.rows[0][0].pad[2])
        height = (H + 36.0) - removed
        from exactdoc.pagefit import PAGEFIT_SAFETY_PT
        room = H - 0.0 - 36.0 - D.SECT_BREAK_PARA_PT - PAGEFIT_SAFETY_PT
        self.assertLessEqual(height, room + 0.05)
        self.assertGreater(b.rows[0][0].pad[2], 0.0)

    def test_a_footer_on_the_cover_is_part_of_its_box(self):
        from exactdoc.layout import HFPart
        foot = HFPart(elements=[Para(runs=[Run(text="1", font="Helvetica",
                                                size=9, color="#000000")],
                                        leading=11.0)],
                      distance=50.0)
        foot.elements[0].src_lines = 1
        free, footed = (_band(0.0, H, pad_bot=300.0) for _ in range(2))
        D._fit_cover_band(free, _lay(margin_b=20.0), None, None, 50.0)
        D._fit_cover_band(footed, _lay(margin_b=20.0), None, foot, 50.0)
        self.assertAlmostEqual(free.rows[0][0].pad[2] - footed.rows[0][0].pad[2],
                               (50.0 + 11.0) - 20.0, places=1)

    def test_text_is_never_clipped(self):
        """A band whose text alone overruns the box keeps its text: only the
        bottom pad is spent, never below zero."""
        b = _band(0.0, H + 100.0, pad_bot=20.0)
        D._fit_cover_band(b, _lay(), None, None, 36.0)
        self.assertEqual(b.rows[0][0].pad[2], 0.0)
        self.assertEqual(b.rows[0][0].paras[0].space_before, 100.0)


class TheFooterRule(unittest.TestCase):
    def _ctx(self, profile):
        return type("Ctx", (), {"output_profile": profile})()

    def test_only_a_cover_stated_footerless_and_only_standard(self):
        lay = DocLayout(page_w=W, page_h=H)
        lay.footer_default = object()
        lay.different_first, lay.footer_first = True, None
        self.assertTrue(D._cover_states_no_footer(lay, self._ctx("standard")))
        self.assertFalse(D._cover_states_no_footer(lay, self._ctx("gdocs")))
        lay.different_first = False      # page 1 shares the default parts
        self.assertFalse(D._cover_states_no_footer(lay, self._ctx("standard")))
        lay.different_first, lay.footer_first = True, object()
        self.assertFalse(D._cover_states_no_footer(lay, self._ctx("standard")))


@unittest.skipUnless(_canvas is not None, "needs reportlab")
class TheWordMadeCover(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = os.path.join(cls._dir.name, "cover.pdf")
        _cover_pdf(cls.pdf)
        cls.std = _convert(cls.pdf, os.path.join(cls._dir.name, "s.docx"))

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_the_cover_section_states_no_footer(self):
        secs = _sections(self.std["word/document.xml"])
        self.assertGreaterEqual(len(secs), 3)
        self.assertNotIn("footerReference", secs[0],
                         "the cover prints no folio")

    def test_the_lead_in_is_blank_and_the_numbered_part_is_footed(self):
        secs = _sections(self.std["word/document.xml"])
        rels = _rels(self.std)
        def footer_text(sec):
            m = re.search(r'footerReference w:type="default" r:id="(rId\d+)"', sec)
            if not m:
                return None
            xml = self.std.get("word/" + rels[m.group(1)], "")
            return re.sub(r"<[^>]+>", "", xml).strip()
        self.assertEqual(footer_text(secs[1]), "",
                         "the unnumbered lead-in prints no footer")
        numbered = [s for s in secs if "w:pgNumType" in s and 'w:start="1"' in s]
        self.assertTrue(numbered, "the numbered section restarts at 1")
        stated = footer_text(numbered[0])
        self.assertIsNotNone(stated, "the numbered section restates the footer")
        self.assertIn("R-", stated)

    def test_the_gdocs_profile_keeps_its_cover_form(self):
        """Held byte-identical: the cover footer is still the default one."""
        g = _convert(self.pdf, os.path.join(self._dir.name, "g.docx"), gdocs=True)
        secs = _sections(g["word/document.xml"])
        self.assertIn("footerReference", secs[0])

    @unittest.skipUnless(shutil.which("soffice") and
                         importlib.util.find_spec("fitz"),
                         "renders with LibreOffice and reads with PyMuPDF")
    def test_it_renders_page_for_page_with_the_title_on_page_one(self):
        sys.path.insert(0, os.path.join(ROOT, "testkit"))
        import fitz
        import harness
        for bleed in (18.0, 0.0):
            with self.subTest(bleed=bleed):
                d = tempfile.mkdtemp(dir=self._dir.name)
                pdf = os.path.join(d, "c.pdf")
                _cover_pdf(pdf, bleed=bleed)
                out = os.path.join(d, "c.docx")
                _convert(pdf, out)
                rendered = fitz.open(harness.docx_to_pdf(out, d))
                self.assertEqual(len(rendered), 9)
                words = [w[4] for w in rendered[0].get_text("words")]
                for w in ("Northwind", "Holdings", "2025", "Annual", "Review"):
                    self.assertIn(w, words)
                self.assertNotIn("R-1", " ".join(words))


if __name__ == "__main__":
    unittest.main()
