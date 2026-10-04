"""A picture that fills the page is placed on the page, not in the margins.

y28's designed cover is one 612x792 picture. Written inline it sat inside the
section margins -- at (73.5, 39.6) in Google Docs and (81.1, 38.8) in
LibreOffice -- ran off the right and bottom edges, and its overflow pushed a
blank page in front of the memo. Anchored behind text at the page origin it
lands at (0, 0, 612, 792) in both and the memo is back on page 2 (live,
2026-10-04). Scanned pages kept as their image (y56, y57) take the same path.
"""
import io
import os
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

from exactdoc.docxout import write_docx
from exactdoc.layout import Chunk, DocLayout, ImageEl, PageLayout, Para, Run

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


def _png(w=64, h=64):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (20, 60, 140)).save(buf, "PNG")
    return buf.getvalue()


def _doc(elements, profile):
    lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=list(elements))])])
    lay.page_w, lay.page_h = 612.0, 792.0
    lay.margin_l, lay.margin_r, lay.margin_t, lay.margin_b = 72.0, 58.0, 25.0, 14.0
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "p.docx")
        write_docx(lay, path, output_profile=profile)
        with zipfile.ZipFile(path) as z:
            return ET.fromstring(z.read("word/document.xml"))


class FullPagePicture(unittest.TestCase):
    def test_a_page_sized_picture_is_anchored_at_the_page_origin(self):
        for profile in ("standard", "gdocs"):
            root = _doc([ImageEl(data=_png(), ext="png", width=612.0, height=792.0)],
                        profile)
            self.assertEqual(root.findall(".//" + WP + "inline"), [], profile)
            anchors = root.findall(".//" + WP + "anchor")
            self.assertEqual(len(anchors), 1, profile)
            a = anchors[0]
            self.assertEqual(a.get("behindDoc"), "1")
            for tag in ("positionH", "positionV"):
                pos = a.find(WP + tag)
                self.assertEqual(pos.get("relativeFrom"), "page")
                self.assertEqual(pos.find(WP + "posOffset").text, "0")
            self.assertIsNotNone(a.find(WP + "wrapNone"))
            # schema order: positions, extent, wrap, docPr, ..., graphic
            names = [c.tag.split("}")[1] for c in a]
            self.assertLess(names.index("extent"), names.index("wrapNone"))
            self.assertLess(names.index("wrapNone"), names.index("docPr"))
            self.assertEqual(names[-1], "graphic")
            # the carrying paragraph takes no room of its own
            sp = root.find(".//" + W + "p/" + W + "pPr/" + W + "spacing")
            self.assertEqual((sp.get(W + "lineRule"), sp.get(W + "line")),
                             ("exact", "20"))

    def test_a_nearly_page_sized_picture_is_centred_on_the_page(self):
        root = _doc([ImageEl(data=_png(), ext="png", width=600.0, height=780.0)],
                    "gdocs")
        a = root.find(".//" + WP + "anchor")
        self.assertIsNotNone(a)
        self.assertEqual(a.find(WP + "positionH/" + WP + "posOffset").text,
                         str(6 * 12700))
        self.assertEqual(a.find(WP + "positionV/" + WP + "posOffset").text,
                         str(6 * 12700))

    def test_an_ordinary_picture_stays_inline(self):
        body = Para(runs=[Run(text="Text beside a figure.", font="Helvetica",
                              size=11.0, color="#000000")])
        for w, h in ((300.0, 200.0), (612.0, 300.0), (480.0, 792.0)):
            root = _doc([body, ImageEl(data=_png(), ext="png", width=w, height=h)],
                        "standard")
            self.assertEqual(root.findall(".//" + WP + "anchor"), [], (w, h))
            self.assertEqual(len(root.findall(".//" + WP + "inline")), 1, (w, h))


class FullPageCoverEndToEnd(unittest.TestCase):
    def test_a_full_bleed_cover_image_converts_to_an_anchored_picture(self):
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.utils import ImageReader
        except ImportError:                                # pragma: no cover
            self.skipTest("reportlab is not installed")
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        with tempfile.TemporaryDirectory() as td:
            pdf = os.path.join(td, "cover.pdf")
            c = canvas.Canvas(pdf, pagesize=(612, 792))
            c.drawImage(ImageReader(io.BytesIO(_png(306, 396))), 0, 0, 612, 792)
            c.showPage()
            c.setFont("Helvetica", 11)
            c.drawString(72, 700, "The memorandum begins on the second page.")
            c.showPage()
            c.save()
            out = os.path.join(td, "cover.docx")
            convert(pdf, out, options=RAW)
            with zipfile.ZipFile(out) as z:
                root = ET.fromstring(z.read("word/document.xml"))
        self.assertEqual(len(root.findall(".//" + WP + "anchor")), 1)
        self.assertEqual(root.findall(".//" + WP + "inline"), [])


if __name__ == "__main__":
    unittest.main()
