"""The family table: PostScript names -> class, weight, slant and target family.

Each case below is a font the corpus census found mapped wrong (B12, B13), a
profile decision (B14), or the East Asian slot (B30). The end-to-end class
builds a PDF whose fonts carry NO descriptor -- flags arrive as 0, exactly as
pdfTeX's Type 1 fonts do -- so the name is the only evidence there is.

    python -m unittest tests.test_font_family_table
"""
import os
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.fonts import (east_asian_family, font_table_desc,   # noqa: E402
                            font_traits, lookup_family, map_font)
from exactdoc.layout import Chunk, DocLayout, PageLayout, Para, Run   # noqa: E402

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class TeXAndURWNames(unittest.TestCase):
    """B13: the names pdfTeX documents use, with no flags to fall back on."""

    def test_urw_clones_map_to_the_family_they_clone(self):
        for name, want in (("NimbusRomNo9L-Regu", "Times New Roman"),
                           ("NimbusRomNo9L-ReguItal", "Times New Roman"),
                           ("NimbusRomNo9L-Regu-Slant_167", "Times New Roman"),
                           ("ABCDEF+NimbusRomNo9L-Medi", "Times New Roman"),
                           ("NimbusSanL-Regu", "Arial"),
                           ("NimbusSanL-BoldItal", "Arial"),
                           ("NimbusMonL-Regu", "Courier New"),
                           ("NimbusRoman-Regular", "Times New Roman"),
                           ("NimbusMonoPS-Bold", "Courier New"),
                           ("TeXGyreTermes-Regular", "Times New Roman"),
                           ("TeXGyreHeros-Bold", "Arial"),
                           ("TeXGyreCursor-Regular", "Courier New")):
            # flags say nothing (serif=False, mono=False): the name decides
            self.assertEqual(map_font(name), want, name)
            self.assertEqual(map_font(name, profile="gdocs"), want, name)

    def test_typewriter_faces_stay_monospace(self):
        for name in ("CMTT10", "CMTT9", "CMTT12", "CMSLTT10", "CMITT10",
                     "ABCDEF+CMTT10", "CMUTypewriter-Light",
                     "CMUTypewriter-BoldItalic", "LMMono10-Regular",
                     "LMMonoLt10-Bold", "SFTT1000", "NimbusMonL-Bold",
                     "Menlo-Regular", "OCRAStd"):
            self.assertEqual(map_font(name), "Courier New", name)
            self.assertEqual(font_traits(name).cls, "mono", name)

    def test_computer_modern_classes(self):
        for name, cls in (("CMR10", "serif"), ("CMBX12", "serif"),
                          ("CMSL10", "serif"), ("CMMI10", "serif"),
                          ("CMSS10", "sans"), ("CMSSBX10", "sans"),
                          ("CMUSerif-Roman", "serif"), ("CMUSansSerif", "sans"),
                          ("CMUSansSerif-Bold", "sans"),
                          ("LMRoman10-Regular", "serif"), ("LMSans10-Bold", "sans"),
                          ("SFRM1095", "serif"), ("SFSS1000", "sans")):
            self.assertEqual(font_traits(name).cls, cls, name)
        self.assertEqual(map_font("CMUSansSerif"), "Arial")
        self.assertEqual(map_font("CMR10"), "Times New Roman")

    def test_weight_and_slant_carried_in_the_shape_code(self):
        """CMBX is Bold Extended; nothing in 'CMBX12' reads 'bold'."""
        for name, bold, italic in (("CMBX12", True, False), ("CMB10", True, False),
                                   ("CMBXTI10", True, True), ("CMSL10", False, True),
                                   ("CMTI10", False, True), ("CMMI10", False, True),
                                   ("CMSSBX10", True, False), ("CMR10", False, False),
                                   ("CMTT10", False, False), ("CMSLTT10", False, True),
                                   ("SFBX1200", True, False), ("SFTI1000", False, True)):
            t = font_traits(name)
            self.assertEqual((t.bold, t.italic), (bold, italic), name)


class StyleWords(unittest.TestCase):
    def test_abbreviated_weights_are_bold(self):
        for name in ("HelveticaNeueLTStd-Bd", "HelveticaNeueLTStd-BdCn",
                     "HelveticaNeueLTStd-BdIt", "HelveticaNeueLTStd-BlkCn",
                     "HelveticaLTStd-Blk", "ITCFranklinGothicStd-Demi",
                     "URWGothicL-Demi", "MinionPro-Semibold", "FreeSerifBold",
                     "Arial,Bold", "Calibri-BoldItalic"):
            self.assertTrue(font_traits(name).bold, name)

    def test_medium_is_bold_only_where_the_foundry_meant_it(self):
        """NimbusRomNo9L-Medi is Times-Bold's clone; Roboto-Medium is weight 500."""
        self.assertTrue(font_traits("NimbusRomNo9L-Medi").bold)
        self.assertTrue(font_traits("NimbusRomNo9L-MediItal").bold)
        self.assertFalse(font_traits("Roboto-Medium").bold)
        self.assertFalse(font_traits("Gotham-Medium").bold)

    def test_light_is_not_bold(self):
        for name in ("SourceSansPro-SemiLight", "URWBookmanL-Ligh",
                     "CallunaSans-Light", "HelveticaNeue-Light"):
            self.assertFalse(font_traits(name).bold, name)

    def test_abbreviated_slants_are_italic(self):
        for name in ("EUAlbertina-ReguItal", "EUAlbertina-BoldItal",
                     "NimbusSanL-ReguItal", "NimbusMonL-ReguObli",
                     "Calluna-It", "HelveticaNeueLTStd-It",
                     "NimbusRomNo9L-Regu-Slant_167", "Times New Roman,Italic",
                     "CMUSansSerif-Oblique"):
            self.assertTrue(font_traits(name).italic, name)

    def test_italic_words_are_style_tokens_not_substrings_of_the_family(self):
        # "it" inside a family name is not a slant
        for name in ("Summit-Regular", "Gravitas-Bold", "Britannic"):
            self.assertFalse(font_traits(name).italic, name)

    def test_regular_and_roman_say_nothing(self):
        for name in ("HelveticaNeueLTStd-Roman", "EUAlbertina-Regu",
                     "Times-Roman", "Palatino-Roman"):
            t = font_traits(name)
            self.assertEqual((t.bold, t.italic), (False, False), name)


class RomanIsNotSerifEvidence(unittest.TestCase):
    """B12: 'Roman' is the upright style of Helvetica Neue, not a serif."""

    def test_helvetica_neue_roman_is_sans(self):
        for name in ("HelveticaNeueLTStd-Roman", "HelveticaNeue-Roman",
                     "HelveticaNeueLTPro-Roman"):
            self.assertEqual(font_traits(name).cls, "sans", name)
            self.assertEqual(map_font(name, serif=True), "Arial", name)

    def test_parser_serif_flag(self):
        from exactdoc import parse_pdfium as P
        cases = (
            ("HelveticaNeueLTStd-Roman", 0, False, False),
            ("Times-Roman", 0, True, False),        # the base-14 case still works
            ("SomeFoundryRoman", 0, False, False),  # 'roman' alone: no evidence
            ("SomeFoundrySerif", 0, True, False),
            ("URWGothicL-Book", 0, False, False),   # 'book' is a weight word
            # the table outranks a WRONG descriptor bit (measured on lshort)
            ("CMUSansSerif", P._FLAG_SERIF, False, False),
            ("CMUTypewriter-Light", P._FLAG_SERIF, False, True),
            ("CMTT10", 0, False, True),
        )
        for font, flags, serif, mono in cases:
            c = P._Char()
            c.font, c.flags, c.size, c.color = font, flags, 10.0, "#000000"
            st = P._style(c)
            self.assertEqual((st[6], st[5]), (serif, mono), font)

    def test_parser_weight_from_the_name(self):
        from exactdoc import parse_pdfium as P
        for font, bold, italic in (("CMBX12", True, False),
                                   ("NimbusRomNo9L-Medi", True, False),
                                   ("EUAlbertina-ReguItal", False, True),
                                   ("Helvetica", False, False)):
            c = P._Char()
            c.font, c.flags, c.size, c.color = font, 0, 10.0, "#000000"
            st = P._style(c)
            self.assertEqual((st[3], st[4]), (bold, italic), font)
            self.assertEqual(c.mono_hint, font_traits(font).cls == "mono")


class SerifFamiliesWithoutFlags(unittest.TestCase):
    def test_albertina_and_book_faces(self):
        for name, want in (("EUAlbertina-Regu", "Times New Roman"),
                           ("CenturySchoolbook-Italic", "Times New Roman"),
                           ("Palatino-Roman", "Times New Roman"),
                           ("URWPalladioL-Roma", "Times New Roman"),
                           ("C059-Roman", "Times New Roman"),
                           ("CenturyGothic-Bold", "Arial"),   # not "century"
                           ("HelveticaWorld-Regular", "Arial"),
                           ("UniversalStd-NewswithCommPi", "Arial")):
            self.assertEqual(map_font(name), want, name)
        self.assertEqual(font_traits("CenturyGothic").cls, "sans")
        self.assertEqual(font_traits("UniversalStd-NewswithCommPi").cls, "symbol")

    def test_numbered_duplicate_resources_keep_their_family(self):
        # WeasyPrint/cairo append a digit to a second resource of the same face
        self.assertEqual(map_font("NotoSerif-Regular2"), "Noto Serif")
        self.assertEqual(map_font("ArialMT2"), "Arial")

    def test_native_families_pass_through_under_their_own_names(self):
        for name, want in (("NotoSerif-Regular", "Noto Serif"),
                           ("RobotoMono-Regular", "Roboto Mono"),
                           ("Roboto-Medium", "Roboto"),
                           ("TrebuchetMS-Bold", "Trebuchet MS"),
                           ("Consolas-Bold", "Consolas"),
                           ("Ubuntu-Regular", "Ubuntu"),
                           ("Vollkorn-Regular", "Vollkorn"),
                           ("Libre Baskerville", "Libre Baskerville")):
            self.assertEqual(map_font(name), want, name)
        self.assertEqual(font_traits("RobotoMono-Regular").cls, "mono")

    def test_unknown_names_still_use_the_flags(self):
        self.assertIsNone(lookup_family("SomeFoundryFont"))
        self.assertEqual(map_font("SomeFoundryFont"), "Arial")
        self.assertEqual(map_font("SomeFoundryFont", serif=True), "Times New Roman")
        self.assertEqual(map_font("SomeFoundryFont", mono=True), "Courier New")


class EastAsianSlot(unittest.TestCase):
    """B30: a CJK run names its own face in w:eastAsia."""

    def test_only_cjk_text_in_a_cjk_face(self):
        self.assertEqual(east_asian_family("WenQuanYiZenHei", "检索质量"),
                         "WenQuanYi Zen Hei")
        self.assertEqual(east_asian_family("NotoSansCJKjp-Regular", "コーパス"),
                         "Noto Sans CJK JP")
        self.assertIsNone(east_asian_family("WenQuanYiZenHei", "Latin only"))
        self.assertIsNone(east_asian_family("LiberationSerif", "检索质量"))
        self.assertIsNone(east_asian_family("WenQuanYiZenHei", "检索", "gdocs"))

    def test_writer_sets_the_slot_and_declares_the_face(self):
        from exactdoc.docxout import write_docx
        lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[
            Para(runs=[Run(text="检索质量随着语料库", font="WenQuanYiZenHei",
                           size=11.0, color="#000000")]),
            Para(runs=[Run(text="Plain Latin", font="WenQuanYiZenHei",
                           size=11.0, color="#000000")])])])])
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "ea.docx")
            write_docx(lay, out, output_profile="standard")
            with zipfile.ZipFile(out) as z:
                doc = ET.fromstring(z.read("word/document.xml"))
                ft = ET.fromstring(z.read("word/fontTable.xml"))
        slots = [(rf.get(W + "ascii"), rf.get(W + "eastAsia"), rf.get(W + "cs"))
                 for rf in doc.iter(W + "rFonts")]
        self.assertIn(("Arial", "WenQuanYi Zen Hei", "Arial"), slots)
        self.assertIn(("Arial", "Arial", "Arial"), slots)
        decl = {f.get(W + "name"): f for f in ft.findall(W + "font")}
        self.assertIn("WenQuanYi Zen Hei", decl)
        self.assertEqual(decl["WenQuanYi Zen Hei"].find(W + "charset").get(W + "val"),
                         "86")

    def test_font_table_descriptor_follows_the_class(self):
        self.assertEqual(font_table_desc("Roboto Mono")[:2], ("modern", "fixed"))
        self.assertEqual(font_table_desc("Courier New")[:2], ("modern", "fixed"))
        self.assertEqual(font_table_desc("Noto Serif")[:2], ("roman", "variable"))
        self.assertEqual(font_table_desc("Calibri")[:2], ("swiss", "variable"))
        self.assertEqual(font_table_desc("Unheard Of"), ("auto", "variable", "00"))


def _raw_pdf(fonts_and_text):
    """A one-page PDF whose fonts are bare /Type1 references: no FontDescriptor,
    no embedding, so PDFium reports flags 0 -- what pdfTeX's Type 1 fonts look
    like to the parser's flag test."""
    objs = []
    font_refs = []
    content = []
    y = 720
    for i, (base, text) in enumerate(fonts_and_text):
        objs.append(("<< /Type /Font /Subtype /Type1 /BaseFont /%s "
                     "/Encoding /WinAnsiEncoding >>" % base))
        font_refs.append("/F%d %d 0 R" % (i + 1, 5 + i))
        esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content.append("BT /F%d 11 Tf 72 %d Td (%s) Tj ET" % (i + 1, y, esc))
        y -= 60
    stream = "\n".join(content).encode("latin-1")
    head = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << %s >> >> /Contents 4 0 R >>" % " ".join(font_refs),
    ]
    body = [h.encode("latin-1") for h in head]
    body.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream +
                b"\nendstream")
    body += [o.encode("latin-1") for o in objs]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, b in enumerate(body, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + b + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(body) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(body) + 1, xref))
    return bytes(out)


def _on(el):
    """A w:b / w:i toggle that is present and not switched off."""
    return el is not None and el.get(W + "val") not in ("0", "false")


class EndToEnd(unittest.TestCase):
    """Parser and writer together, on fonts whose only evidence is the name."""

    CASES = (("CMTT10", "def rerank(docs): return sorted(docs)"),
             ("NimbusRomNo9L-Medi", "Section heading in Times bold"),
             ("HelveticaNeueLTStd-Roman", "Form line in Helvetica Neue"),
             ("EUAlbertina-ReguItal", "Recital in the Official Journal"))

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.pdf = os.path.join(cls.td.name, "names.pdf")
        with open(cls.pdf, "wb") as fh:
            fh.write(_raw_pdf(cls.CASES))

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_parser_reads_class_weight_and_slant_from_the_name(self):
        from exactdoc.parse_pdfium import parse_pdf
        ir = parse_pdf(self.pdf, keep_image_data=False)
        spans = {s.font: s for p in ir.pages for b in p.blocks
                 for ln in b.lines for s in ln.spans if s.text.strip()}
        self.assertTrue(spans["CMTT10"].mono)
        self.assertFalse(spans["CMTT10"].serif)
        self.assertTrue(spans["NimbusRomNo9L-Medi"].bold)
        self.assertTrue(spans["NimbusRomNo9L-Medi"].serif)
        self.assertFalse(spans["HelveticaNeueLTStd-Roman"].serif)
        self.assertTrue(spans["EUAlbertina-ReguItal"].italic)
        self.assertTrue(spans["EUAlbertina-ReguItal"].serif)

    def test_docx_writes_the_right_families(self):
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        out = os.path.join(self.td.name, "names.docx")
        convert(self.pdf, out, options=RAW.replace(backend="pdfium"))
        with zipfile.ZipFile(out) as z:
            doc = ET.fromstring(z.read("word/document.xml"))
        runs = {}
        for r in doc.iter(W + "r"):
            t = "".join(x.text or "" for x in r.iter(W + "t"))
            rpr = r.find(W + "rPr")
            if not t.strip() or rpr is None:
                continue
            rf = rpr.find(W + "rFonts")
            runs[t.split()[0]] = (rf.get(W + "ascii"), _on(rpr.find(W + "b")),
                                  _on(rpr.find(W + "i")))
        self.assertEqual(runs["def"][0], "Courier New")
        self.assertEqual(runs["Section"], ("Times New Roman", True, False))
        self.assertEqual(runs["Form"][0], "Arial")
        self.assertEqual(runs["Recital"], ("Times New Roman", False, True))


if __name__ == "__main__":
    unittest.main()
