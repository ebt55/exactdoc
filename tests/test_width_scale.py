"""Runs draw at the width the source drew them at: w:w for two measured residuals.

The half-point size residual (defect catalogue #19: 9.33pt can only be written
as 9.5, +1.8% wide) and the monospace substitution residual (CMTT10 draws at
0.525em, Courier New at 0.600, +14%) both re-wrap text the source fitted. The
writer states the product as w:w, the ladder shapes with it, and the parser
supplies the source's own advances.

    python -m unittest tests.test_width_scale
"""
import os
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import ladder                                          # noqa: E402
from exactdoc.layout import Chunk, DocLayout, PageLayout, Para, Run  # noqa: E402
from exactdoc.metrics import (apply_width_scale, get_metrics,        # noqa: E402
                              run_width_scale, shaped_size)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CMTT = {ch: 0.525 for ch in "abcdefghijklmnopqrstuvwxyz()=_.:,0123456789"}


def _run(text, font="LiberationSerif", size=10.0, **kw):
    return Run(text=text, font=font, size=size, color="#000000", **kw)


class Scale(unittest.TestCase):
    m = get_metrics()

    def test_a_half_point_size_needs_no_scale(self):
        self.assertEqual(run_width_scale(_run("body", size=10.5), {}, self.m), 0.0)
        self.assertEqual(run_width_scale(_run("body", size=11.0), {}, self.m), 0.0)

    def test_the_size_residual(self):
        # c1_whitepaper's body: 9.33pt written as 9.5
        self.assertAlmostEqual(run_width_scale(_run("body", size=9.33), {}, self.m),
                               0.98)
        # the owner's resume: 9.6975pt written as 9.5
        self.assertAlmostEqual(run_width_scale(_run("body", size=9.6975), {}, self.m),
                               1.02)
        # under half a percent rounds to w:w=100: nothing is written
        self.assertEqual(run_width_scale(_run("body", size=10.99), {}, self.m), 0.0)

    def test_typewriter_residual_from_the_sources_own_advances(self):
        r = _run("def main(): return 0", font="CMTT10", size=10.0, mono=True)
        self.assertAlmostEqual(run_width_scale(r, {"CMTT10": CMTT}, self.m), 0.88)
        # without the source's measurement only the (zero) size residual is left
        self.assertEqual(run_width_scale(r, {}, self.m), 0.0)
        # a glyph the PDF never drew makes the family residual unmeasured
        r2 = _run("def main(): return 0 #", font="CMTT10", size=10.0, mono=True)
        self.assertEqual(run_width_scale(r2, {"CMTT10": CMTT}, self.m), 0.0)

    def test_proportional_family_mismatch_is_not_compensated(self):
        cmr = {ch: 0.5 for ch in "abcdefghijklmnopqrstuvwxyz"}
        r = _run("plain prose", font="CMR10", size=10.0)
        self.assertEqual(run_width_scale(r, {"CMR10": cmr}, self.m), 0.0)

    def test_a_mismatch_past_the_cap_is_left_alone(self):
        narrow = {ch: 0.40 for ch in CMTT}         # -33% against Courier New
        r = _run("def main(): return 0", font="CMTT10", size=10.0, mono=True)
        self.assertEqual(run_width_scale(r, {"CMTT10": narrow}, self.m), 0.0)

    def test_shaped_size_is_what_the_writer_draws(self):
        r = _run("x", size=9.33)
        self.assertEqual(shaped_size(r), 9.33)
        r.width_scale = 0.98
        self.assertAlmostEqual(shaped_size(r), 9.5 * 0.98)


class LadderAndWriter(unittest.TestCase):
    CODE = "result = compute_checksum(buffer, offset, length)"

    def _layout(self):
        p = Para(runs=[_run(self.CODE, font="CMTT10", size=10.0, mono=True)],
                 src_lines=1)
        lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[p])])])
        lay.font_advances = {"CMTT10": CMTT}
        return lay, p

    def test_the_ladder_predicts_the_compensated_width(self):
        lay, p = self._layout()
        m = get_metrics()
        src_w = 0.525 * 10.0 * len(self.CODE)          # what the PDF drew
        avail = src_w + 3.0
        # unscaled Courier New does not fit the source's column ...
        self.assertEqual(ladder.predict_lines(p, avail, m), 2)
        # ... scaled to the source's pitch it does, as it did in the PDF
        self.assertEqual(apply_width_scale(lay, m), 1)
        self.assertEqual(ladder.predict_lines(p, avail, m), 1)

    def test_writer_emits_w_w_before_sz_in_the_standard_profile_only(self):
        from exactdoc.docxout import write_docx
        lay, p = self._layout()
        apply_width_scale(lay)
        with tempfile.TemporaryDirectory() as td:
            got = {}
            for prof in ("standard", "gdocs"):
                out = os.path.join(td, prof + ".docx")
                write_docx(lay, out, output_profile=prof)
                with zipfile.ZipFile(out) as z:
                    doc = ET.fromstring(z.read("word/document.xml"))
                got[prof] = [list(rpr) for rpr in doc.iter(W + "rPr")
                             if rpr.find(W + "w") is not None]
        self.assertEqual(len(got["standard"]), 1)
        kids = [el.tag for el in got["standard"][0]]
        wel = got["standard"][0][kids.index(W + "w")]
        self.assertEqual(wel.get(W + "val"), "88")
        self.assertLess(kids.index(W + "w"), kids.index(W + "sz"))
        self.assertEqual(got["gdocs"], [])


def _cmtt_listing_pdf():
    """A code listing in a bare /CMTT10 font with TeX's 525-unit cell: no
    descriptor, so only the name says monospace, and only /Widths says 0.525."""
    lines = [(72.0, 700, "def f(x):"), (72.0 + 4 * 5.25, 688, "if x:"),
             (72.0 + 8 * 5.25, 676, "return x"), (72.0 + 4 * 5.25, 664, "return 0")]
    content = "\n".join("BT /F1 10 Tf %.2f %d Td (%s) Tj ET" % (x, y, t)
                        for x, y, t in lines).encode("latin-1")
    widths = " ".join(["525"] * 95)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            ("<< /Type /Font /Subtype /Type1 /BaseFont /CMTT10 /FirstChar 32 "
             "/LastChar 126 /Widths [%s] /Encoding /WinAnsiEncoding >>"
             % widths).encode("latin-1")]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for n, o in enumerate(objs, start=1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % n + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, x)
    return bytes(out)


class ParserAdvances(unittest.TestCase):
    def test_typewriter_indentation_is_counted_in_its_own_cell(self):
        """CMTT's cell is 0.525em; counted in Courier's 0.6em an eight-space
        indent came back as seven."""
        from exactdoc.parse_pdfium import parse_pdf
        with tempfile.TemporaryDirectory() as td:
            pdf = os.path.join(td, "cmtt.pdf")
            with open(pdf, "wb") as fh:
                fh.write(_cmtt_listing_pdf())
            ir = parse_pdf(pdf, keep_image_data=False)
        self.assertAlmostEqual(ir.font_advances["CMTT10"]["d"], 0.525, places=3)
        texts = [ln.text for p in ir.pages for b in p.blocks for ln in b.lines]
        self.assertIn("        return x", texts)
        self.assertIn("    if x:", texts)
        self.assertTrue(all(s.mono for p in ir.pages for b in p.blocks
                            for ln in b.lines for s in ln.spans if s.text.strip()))

    def test_the_parser_records_each_fonts_own_advances(self):
        from reportlab.pdfgen import canvas
        from exactdoc.parse_pdfium import parse_pdf
        with tempfile.TemporaryDirectory() as td:
            pdf = os.path.join(td, "adv.pdf")
            c = canvas.Canvas(pdf)
            c.setFont("Courier", 10)
            c.drawString(72, 700, "fixed pitch text")
            c.setFont("Times-Roman", 10)
            c.drawString(72, 650, "mmm iii")
            c.save()
            ir = parse_pdf(pdf, keep_image_data=False)
        adv = ir.font_advances
        self.assertAlmostEqual(adv["Courier"]["f"], 0.600, places=2)
        self.assertAlmostEqual(adv["Times-Roman"]["m"], 0.778, places=2)
        self.assertAlmostEqual(adv["Times-Roman"]["i"], 0.278, places=2)
        self.assertNotIn(" ", adv["Courier"])


if __name__ == "__main__":
    unittest.main()
