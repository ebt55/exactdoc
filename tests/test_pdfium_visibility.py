"""PDFium visibility: the IR carries the text a reader sees (design audit B8).

PDFium's text page reports every glyph a content stream SHOWS, painted or not.
Before this, all of these arrived as ordinary text:

  * render mode 3 (invisible) -- the OCR layer of every scanner-to-PDF
    workflow, which came out as the page image AND a visible second copy of its
    text; and Distiller's invisible line-start spaces (y19: doubled spaces)
  * text clipped away
  * white text on the bare page (y21's "Public Disclosure Authorized")
  * 0.01pt text (y12/y13's duplicated form numbers: "1040-X1040-X")
  * text outside the visible page (the printer's slug: test_pdfium_page_geometry)

The OCR layer is the exception that matters most: invisible text over a page
image IS the document's text. By default it becomes the page's text and the
scan it duplicates is left out; `ocr_layer="image"` keeps the scan instead.

    python tests/test_pdfium_visibility.py
"""
import io
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.parse_pdfium import parse_pdf  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image, ImageDraw
except ImportError:                                    # pragma: no cover
    _canvas = None


def _texts(ir, pno=0):
    return [ln.text for b in ir.pages[pno].blocks for ln in b.lines]


def _scan_png(text="Scanned page text (pixels)"):
    im = Image.new("RGB", (850, 1100), "white")
    ImageDraw.Draw(im).text((130, 120), text, fill="black")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    buf.seek(0)
    return ImageReader(buf)


def _ocr_pdf(path, ink=(0, 0, 0)):
    """A full-page scan under an invisible (Tr 3) OCR layer."""
    c = _canvas.Canvas(path, pagesize=(612, 792))
    c.drawImage(_scan_png(), 0, 0, 612, 792)
    to = c.beginText(100, 700)
    to.setTextRenderMode(3)
    to.setFont("Helvetica", 12)
    to.setFillColorRGB(*ink)
    to.textLine("Scanned page text invisible OCR layer line one")
    to.textLine("second OCR line with more invisible words here")
    c.drawText(to)
    c.save()
    return path


@unittest.skipIf(_canvas is None, "reportlab and Pillow are required")
class HiddenText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        path = os.path.join(cls._dir.name, "hidden.pdf")
        c = _canvas.Canvas(path, pagesize=(612, 792))
        c.setFont("Helvetica", 12)
        c.drawString(72, 720, "visible line")
        # white on the bare page
        c.setFillColorRGB(1, 1, 1)
        c.drawString(72, 700, "white on white hidden text")
        # white on a dark band: a heading, and it must stay
        c.setFillColorRGB(0.1, 0.2, 0.4)
        c.rect(60, 640, 300, 30, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.drawString(72, 650, "white heading on a band")
        c.setFillColorRGB(0, 0, 0)
        # clipped: only the first 50pt is painted
        c.saveState()
        p = c.beginPath()
        p.rect(72, 600, 50, 20)
        c.clipPath(p, stroke=0, fill=0)
        c.drawString(72, 605, "clipped text mostly invisible beyond fifty points")
        c.restoreState()
        # a 0.01pt speck
        c.setFont("Helvetica", 0.01)
        c.drawString(300, 520, "1040-X")
        c.setFont("Helvetica", 12)
        c.drawString(72, 520, "last visible line")
        # invisible, and no image beneath it: not an OCR layer. Last, because
        # Tr is graphics state and outlives the text object that set it.
        to = c.beginText(72, 560)
        to.setTextRenderMode(3)
        to.setFont("Helvetica", 12)
        to.textLine("invisible text with nothing under it")
        c.drawText(to)
        c.save()
        cls.ir = parse_pdf(path, keep_image_data=False)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_only_what_is_painted_is_text(self):
        texts = _texts(self.ir)
        self.assertIn("visible line", texts)
        self.assertIn("white heading on a band", texts)
        self.assertIn("last visible line", texts)
        joined = " ".join(texts)
        for gone in ("white on white", "invisible text", "1040-X", "beyond fifty"):
            self.assertNotIn(gone, joined)

    def test_clipped_text_keeps_its_visible_part(self):
        (clipped,) = [t for t in _texts(self.ir) if t.startswith("clipped")]
        self.assertLess(len(clipped), len("clipped text"))

    def test_reasons_are_recorded(self):
        hidden = self.ir.pages[0].hidden_chars
        self.assertEqual(set(hidden), {"background", "clipped", "invisible", "tiny"})
        self.assertEqual(hidden["tiny"], len("1040-X"))
        self.assertEqual(self.ir.pages[0].ocr_chars, 0)


@unittest.skipIf(_canvas is None, "reportlab and Pillow are required")
class OcrLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = _ocr_pdf(os.path.join(cls._dir.name, "ocr.pdf"))
        cls.white = _ocr_pdf(os.path.join(cls._dir.name, "ocr_white.pdf"),
                             ink=(1, 1, 1))

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_text_mode_makes_the_layer_the_text(self):
        ir = parse_pdf(self.pdf, keep_image_data=False)
        page = ir.pages[0]
        self.assertEqual(_texts(ir), [
            "Scanned page text invisible OCR layer line one",
            "second OCR line with more invisible words here"])
        self.assertEqual(page.images, [], "the scan duplicates the text")
        self.assertGreater(page.ocr_chars, 60)

    def test_layer_is_inked_whatever_colour_it_was_never_painted_in(self):
        ir = parse_pdf(self.white, keep_image_data=False)
        colours = {s.color for b in ir.pages[0].blocks for ln in b.lines
                   for s in ln.spans}
        self.assertEqual(colours, {"#000000"})

    def test_image_mode_keeps_the_scan_and_drops_the_layer(self):
        ir = parse_pdf(self.pdf, keep_image_data=False, ocr_layer="image")
        page = ir.pages[0]
        self.assertEqual(_texts(ir), [])
        self.assertEqual(len(page.images), 1)
        self.assertGreater(page.ocr_chars, 60)

    def test_scan_classifies_an_ocr_layer_as_text_in_both_modes(self):
        from exactdoc.scan import classify_ir
        for mode in ("text", "image"):
            with self.subTest(mode=mode):
                ir = parse_pdf(self.pdf, keep_image_data=False, ocr_layer=mode)
                self.assertEqual(classify_ir(ir).classification, "digital")

    def test_bad_mode_is_refused(self):
        with self.assertRaises(ValueError):
            parse_pdf(self.pdf, ocr_layer="both")

    def test_conversion_is_an_editable_document(self):
        from exactdoc.convert import convert
        out = os.path.join(self._dir.name, "ocr.docx")
        convert(self.pdf, out, oracle="none", refine_rounds=0)
        xml = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
        self.assertIn("second OCR line with more invisible words here", xml)
        self.assertNotIn("<w:drawing>", xml)

    def test_conversion_in_image_mode_is_the_picture(self):
        from exactdoc.convert import convert
        out = os.path.join(self._dir.name, "ocr_img.docx")
        convert(self.pdf, out, oracle="none", refine_rounds=0, ocr_layer="image")
        xml = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
        self.assertNotIn("invisible words", xml)
        self.assertIn("<w:drawing>", xml)

    def test_cli_flag_reaches_the_parser(self):
        from exactdoc.cli import build_parser
        args = build_parser().parse_args([self.pdf, "--ocr-layer", "image"])
        self.assertEqual(args.ocr_layer, "image")
        self.assertEqual(build_parser().parse_args([self.pdf]).ocr_layer, "text")

    def test_options_validate_the_mode(self):
        from exactdoc.errors import ConfigurationError
        from exactdoc.options import PRODUCT
        self.assertEqual(PRODUCT.ocr_layer, "text")
        with self.assertRaises(ConfigurationError):
            PRODUCT.replace(ocr_layer="both")


@unittest.skipIf(_canvas is None, "reportlab and Pillow are required")
class IconLettering(unittest.TestCase):
    """An icon's label is part of the icon, not of the line beside it.

    IRS publications draw TIP / CAUTION badges as small Form XObjects that
    paint their own shape and letter it. Placed where they are drawn, the
    label sits on the body line and fused with it ("CAUTIONrect SSN, ...").
    A callout BOX drawn as a form is text on a fill too, and stays text: the
    test is the form's size (ICON_MAX_PT).
    """

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        path = os.path.join(cls._dir.name, "icons.pdf")
        c = _canvas.Canvas(path, pagesize=(612, 792))
        c.beginForm("tip")
        c.setFillColorRGB(0, 0, 0)
        c.roundRect(0, 0, 28, 20, 5, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(5, 7, "TIP")
        c.endForm()
        c.beginForm("callout")
        c.setFillColorRGB(0.85, 0.9, 1.0)
        c.rect(0, 0, 300, 60, stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica", 10)
        c.drawString(10, 25, "Callout text inside a shaded box form")
        c.endForm()
        c.saveState()
        c.translate(72, 600)
        c.doForm("tip")
        c.restoreState()
        c.setFont("Helvetica", 10)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(104, 607, "body text that runs beside the tip icon")
        c.saveState()
        c.translate(72, 450)
        c.doForm("callout")
        c.restoreState()
        c.save()
        cls.ir = parse_pdf(path, keep_image_data=False)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_label_is_not_fused_into_the_body_line(self):
        texts = _texts(self.ir)
        self.assertIn("body text that runs beside the tip icon", texts)
        self.assertFalse(any("TIP" in t for t in texts), texts)
        self.assertEqual(self.ir.pages[0].hidden_chars.get("icon"), 3)

    def test_callout_box_form_is_still_text(self):
        self.assertIn("Callout text inside a shaded box form", _texts(self.ir))

    def test_the_icon_shape_is_where_it_was_drawn(self):
        boxes = [tuple(round(v) for v in d.bbox) for d in self.ir.pages[0].drawings]
        self.assertIn((72, 172, 100, 192), boxes)


@unittest.skipIf(_canvas is None, "reportlab and Pillow are required")
class InvisibleTextIsNotAnOcrLayerWithoutAScan(unittest.TestCase):
    """Invisible text on a page whose image is a small logo stays hidden."""

    def test_logo_does_not_make_a_scan(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "logo.pdf")
            c = _canvas.Canvas(path, pagesize=(612, 792))
            c.drawImage(_scan_png("logo"), 72, 650, 100, 100)
            to = c.beginText(72, 600)
            to.setTextRenderMode(3)
            to.setFont("Helvetica", 12)
            to.textLine("hidden keywords for search engines")
            c.drawText(to)
            c.save()
            ir = parse_pdf(path, keep_image_data=False)
        self.assertEqual(_texts(ir), [])
        self.assertEqual(len(ir.pages[0].images), 1)
        self.assertEqual(ir.pages[0].ocr_chars, 0)


if __name__ == "__main__":
    unittest.main()
