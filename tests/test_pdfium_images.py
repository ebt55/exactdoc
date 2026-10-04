"""Placed images: transparency kept, JPEGs passed through, losses counted.

Measured before (design audit B10/B11/B28, defect catalogue #9):

  * an RGBA logo with an SMask arrived as RGB with a BLACK background where the
    source is transparent -- y20's cover logo, y01's TOC section numbers;
  * a 1.32MB JPEG became a 5.44MB PNG (4.1x);
  * an extraction exception silently set data=None, and nothing counted it;
  * one bad link annotation discarded every link on its page;
  * figure clips re-opened the source PDF once per clip (117 opens on y06).

    python tests/test_pdfium_images.py
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import parse_pdfium  # noqa: E402
from exactdoc.parse_pdfium import parse_pdf  # noqa: E402

try:
    from PIL import Image, ImageDraw
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.lib.utils import ImageReader
except ImportError:                                    # pragma: no cover
    _canvas = None


def _photo_jpeg(mode="RGB", size=(320, 240)):
    im = Image.new("RGB", size)
    px = im.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = ((x * 7 + y * 3) % 256, (x * y) % 256, (x * 5) % 256)
    if mode != "RGB":
        im = im.convert(mode)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _raw_pdf_with_image(path, jpeg, width, height, colorspace="/DeviceRGB",
                        decode=None):
    """A one-page PDF whose only content is one DCT image XObject.

    Written by hand because the point is the image dictionary itself --
    /Decode, /ColorSpace -- which no generator here lets a caller set.
    """
    extra = (" /Decode %s" % decode) if decode else ""
    content = b"q 200 0 0 150 72 500 cm /Im1 Do Q"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        ("<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s "
         "/BitsPerComponent 8 /Filter /DCTDecode%s /Length %d >>\nstream\n"
         % (width, height, colorspace, extra, len(jpeg))).encode() + jpeg
        + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, xref)
    with open(path, "wb") as f:
        f.write(bytes(out))
    return path


@unittest.skipIf(_canvas is None, "reportlab and Pillow are required")
class ImagePayloads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        d = cls._dir.name
        cls.jpeg = _photo_jpeg()
        path = os.path.join(d, "images.pdf")
        c = _canvas.Canvas(path, pagesize=(612, 792))
        c.setFillColorRGB(0.2, 0.4, 0.9)
        c.rect(300, 450, 250, 250, stroke=0, fill=1)       # blue box behind the logo
        c.drawImage(ImageReader(io.BytesIO(cls.jpeg)), 72, 100, 320, 240)
        logo = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        ImageDraw.Draw(logo).ellipse((25, 25, 175, 175), fill=(220, 30, 30, 255))
        buf = io.BytesIO()
        logo.save(buf, "PNG")
        buf.seek(0)
        c.drawImage(ImageReader(buf), 325, 475, 200, 200, mask="auto")
        c.save()
        cls.ir = parse_pdf(path)
        cls.pdf = path

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def _by_size(self):
        return sorted(self.ir.pages[0].images, key=lambda im: -(im.bbox[2] - im.bbox[0]))

    def test_jpeg_stream_is_embedded_as_it_is(self):
        photo = self._by_size()[0]
        self.assertEqual(photo.ext, "jpeg")
        self.assertEqual(photo.data, self.jpeg, "the stream must pass through untouched")

    def test_soft_mask_is_transparency_not_black(self):
        logo = [im for im in self.ir.pages[0].images if im.ext == "png"]
        (logo,) = logo
        pil = Image.open(io.BytesIO(logo.data))
        self.assertEqual(pil.mode, "RGBA")
        self.assertEqual(pil.getpixel((2, 2))[3], 0, "the corner is transparent")
        r, g, b, a = pil.getpixel((pil.width // 2, pil.height // 2))
        self.assertEqual(a, 255)
        self.assertGreater(r, 150)

    def test_nothing_was_dropped(self):
        self.assertEqual(self.ir.pages[0].images_dropped, 0)

    def test_inverted_decode_is_not_passed_through(self):
        """/Decode [1 0 ...] paints the negative; the raw stream would not."""
        jpeg = _photo_jpeg(size=(64, 48))
        with tempfile.TemporaryDirectory() as d:
            plain = parse_pdf(_raw_pdf_with_image(os.path.join(d, "p.pdf"), jpeg, 64, 48))
            inv = parse_pdf(_raw_pdf_with_image(os.path.join(d, "i.pdf"), jpeg, 64, 48,
                                                decode="[1 0 1 0 1 0]"))
        (p,), (i,) = plain.pages[0].images, inv.pages[0].images
        self.assertEqual((p.ext, p.data), ("jpeg", jpeg))
        self.assertEqual(i.ext, "png")
        px = Image.open(io.BytesIO(i.data)).convert("RGB").getpixel((0, 0))
        src = Image.open(io.BytesIO(jpeg)).convert("RGB").getpixel((0, 0))
        self.assertGreater(sum(abs(a - b) for a, b in zip(px, src)), 300,
                           "the PNG carries PDFium's inverted pixels")

    def test_cmyk_jpeg_is_not_passed_through(self):
        jpeg = _photo_jpeg(mode="CMYK", size=(64, 48))
        with tempfile.TemporaryDirectory() as d:
            ir = parse_pdf(_raw_pdf_with_image(os.path.join(d, "c.pdf"), jpeg, 64, 48,
                                               colorspace="/DeviceCMYK"))
        (im,) = ir.pages[0].images
        self.assertEqual(im.ext, "png")

    def test_a_failed_extraction_is_counted_and_reported(self):
        with mock.patch.object(parse_pdfium, "_image_payload",
                               side_effect=RuntimeError("undecodable")):
            ir = parse_pdf(self.pdf)
        self.assertEqual(ir.pages[0].images_dropped, 2)
        self.assertTrue(all(im.data is None for im in ir.pages[0].images))
        from exactdoc.convert import convert
        out = os.path.join(self._dir.name, "dropped.docx")
        printed = io.StringIO()
        with mock.patch.object(parse_pdfium, "_image_payload",
                               side_effect=RuntimeError("undecodable")), \
                contextlib.redirect_stdout(printed):
            convert(self.pdf, out, oracle="none", refine_rounds=0)
        self.assertIn("2 image(s) could not be embedded", printed.getvalue())

    def test_docx_is_smaller_with_the_stream(self):
        from exactdoc.convert import convert
        out = os.path.join(self._dir.name, "images.docx")
        convert(self.pdf, out, oracle="none", refine_rounds=0)
        media = [n for n in zipfile.ZipFile(out).namelist() if n.startswith("word/media/")]
        self.assertTrue(any(n.endswith((".jpg", ".jpeg")) for n in media), media)


@unittest.skipIf(_canvas is None, "reportlab and Pillow are required")
class LinkGuards(unittest.TestCase):
    def test_one_bad_annotation_costs_one_link(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "links.pdf")
            c = _canvas.Canvas(path, pagesize=(612, 792))
            c.setFont("Helvetica", 12)
            for k in range(3):
                y = 700 - 40 * k
                c.drawString(100, y, "link number %d" % k)
                c.linkURL("https://example.com/%d" % k, (100, y - 5, 200, y + 15),
                          relative=0)
            c.save()
            real = parse_pdfium._one_link
            calls = []

            def flaky(doc, link, frame):
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("malformed annotation")
                return real(doc, link, frame)

            with mock.patch.object(parse_pdfium, "_one_link", side_effect=flaky):
                ir = parse_pdf(path, keep_image_data=False)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(ir.pages[0].links), 2)


@unittest.skipIf(_canvas is None, "reportlab and Pillow are required")
class ClipRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = os.path.join(cls._dir.name, "fig.pdf")
        c = _canvas.Canvas(cls.pdf, pagesize=(612, 792))
        c.setFillColorRGB(0.8, 0.1, 0.1)
        c.circle(150, 650, 60, stroke=1, fill=1)
        c.showPage()
        c.setFillColorRGB(0.1, 0.6, 0.1)
        c.circle(300, 400, 80, stroke=1, fill=1)
        c.save()

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def _layout(self, n=3):
        from exactdoc.layout import Chunk, DocLayout, FigureEl, PageLayout
        pages = []
        for pno, clip in ((1, (80.0, 70.0, 220.0, 210.0)), (2, (210.0, 300.0, 390.0, 480.0))):
            figs = [FigureEl(page_no=pno, clip=clip, width=140.0, height=140.0)
                    for _ in range(n)]
            pages.append(PageLayout(number=pno, chunks=[Chunk(elements=figs)]))
        return DocLayout(pages=pages, src_path=self.pdf)

    def test_session_renders_what_render_clip_renders(self):
        from exactdoc.backend import PDFiumBackend
        bk = PDFiumBackend()
        session = bk.clip_renderer(self.pdf)
        try:
            for pno, clip in ((1, (80.0, 70.0, 220.0, 210.0)), (2, (210.0, 300.0, 390.0, 480.0))):
                self.assertEqual(session.render_clip(pno, clip, dpi=96),
                                 bk.render_clip(self.pdf, pno, clip, dpi=96))
        finally:
            session.close()

    def test_write_opens_the_document_once(self):
        from exactdoc.backend import PDFiumBackend
        from exactdoc.docxout import write_docx
        bk = PDFiumBackend()
        opened = []
        real = bk.clip_renderer

        def counting(path):
            opened.append(path)
            return real(path)

        report = {}
        with mock.patch.object(bk, "clip_renderer", side_effect=counting), \
                mock.patch.object(bk, "render_clip",
                                  side_effect=AssertionError("re-opened the PDF")):
            out = os.path.join(self._dir.name, "figs.docx")
            write_docx(self._layout(), out, dpi=72, backend=bk, image_report=report)
        self.assertEqual(opened, [self.pdf])
        media = [n for n in zipfile.ZipFile(out).namelist() if n.startswith("word/media/")]
        self.assertTrue(media)
        self.assertEqual(report, {})

    def test_a_figure_that_cannot_render_is_counted(self):
        from exactdoc.docxout import write_docx

        class Broken:
            name = "broken"

            def render_clip(self, *a, **k):
                raise RuntimeError("renderer failed")

        report = {}
        write_docx(self._layout(n=1), os.path.join(self._dir.name, "broken.docx"),
                   dpi=72, backend=Broken(), image_report=report)
        self.assertEqual(report, {"dropped": 2})


if __name__ == "__main__":
    unittest.main()
