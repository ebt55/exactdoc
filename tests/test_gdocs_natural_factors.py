"""Google Docs line heights for the Calibri family.

The gdocs profile writes a line height as a multiple of the font's natural
line, so it must know each family's natural line in Docs. Calibri and its
metric clone Carlito -- the most common family in Word documents -- were
missing and took the 1.144 default: every line rendered 6.7% tall, and y30
went 33 source pages to 43 in Docs. Measured live 2026-10-04 (one paragraph per
page, 9-12 single-spaced lines at 11pt and 9pt): Carlito and Calibri 1.2207,
Cambria 1.1724, Caladea 1.1500.
"""
import os
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

from exactdoc.docxout import NATURAL_FACTORS, _natural_factor, write_docx
from exactdoc.layout import Chunk, DocLayout, PageLayout, Para, Run

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class CalibriFamily(unittest.TestCase):
    def test_measured_factors(self):
        self.assertAlmostEqual(_natural_factor("Carlito"), 1.221, places=3)
        self.assertAlmostEqual(_natural_factor("Calibri"), 1.221, places=3)
        self.assertAlmostEqual(_natural_factor("Cambria"), 1.172, places=3)
        self.assertAlmostEqual(_natural_factor("Caladea"), 1.150, places=3)
        for fam in ("carlito", "calibri", "cambria", "caladea"):
            self.assertIn(fam, NATURAL_FACTORS)

    def test_remeasured_families(self):
        # live 2026-10-04: each equals its font file's hhea line
        for fam, f in (("Courier New", 1.133), ("Georgia", 1.1365),
                       ("Roboto", 1.200), ("Noto Serif", 1.362),
                       ("Noto Sans", 1.362), ("Verdana", 1.2155),
                       ("Vollkorn", 1.393), ("Consolas", 1.171)):
            self.assertAlmostEqual(_natural_factor(fam), f, places=4, msg=fam)

    def test_arial_and_times_at_their_true_value(self):
        # They were held at 1.144 because the true factor ALONE broke 01's
        # SSIM bound (pass 12). WP19 moved them with the levers tuned around
        # them, on the evidence of Google's own exports (every Times/Arial
        # line 0.5% tall at 1.144); see tests/test_gdocs_page_planner.py.
        self.assertEqual(_natural_factor("Arial"), 1.150)
        self.assertEqual(_natural_factor("Times New Roman"), 1.150)

    def test_a_carlito_line_at_its_natural_pitch_is_single_spacing(self):
        # 11pt Carlito at Docs' own 13.43pt pitch is exactly 1.0 x natural, so
        # the gdocs multiple is w:line 240 -- not the 256 (+6.7%) the 1.144
        # default produced.
        p = Para(runs=[Run(text="Calibri body text in a Word document.",
                           font="Calibri", size=11.0, color="#000000")],
                 leading=11.0 * 1.2207)
        # two source lines: a one-line paragraph takes the separate 0.38pt
        # single-line lever (docxout.write_para), which is not under test here
        p.src_lines = 2
        lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[p])])])
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "c.docx")
            write_docx(lay, path, output_profile="gdocs")
            with zipfile.ZipFile(path) as z:
                root = ET.fromstring(z.read("word/document.xml"))
        fonts = {e.get(W + "ascii") for e in root.iter(W + "rFonts")}
        self.assertIn("Carlito", fonts)
        sp = root.find(".//" + W + "pPr/" + W + "spacing")
        self.assertEqual(sp.get(W + "lineRule"), "auto")
        self.assertAlmostEqual(int(sp.get(W + "line")), 240, delta=1)


if __name__ == "__main__":
    unittest.main()
