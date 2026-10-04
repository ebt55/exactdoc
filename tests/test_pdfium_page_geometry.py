"""PDFium geometry: every coordinate in the IR is on the page a viewer shows.

PDFium reports glyph boxes, object bounds, path points, link rectangles and
destinations in PDF USER space. The IR is top-left points on the VISIBLE page:
the CropBox (clipped to the MediaBox) with /Rotate applied. The parser used to
flip y against the displayed height and nothing else, which is right only for
an unrotated box at the origin. Measured on synthetic pages (design audit B6):

    CropBox [50 50 562 742]   baseline -8 instead of 42, x 50pt out
    MediaBox origin (50, 50)  baseline 92 instead of 142
    /Rotate 90                baseline -88, the rectangle lost

and objects inside a Form XObject kept FORM-space bounds (B7): a rectangle in
a form drawn at translate(150, 400) came back at (0, 752, 120, 792).

    python tests/test_pdfium_page_geometry.py
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pypdfium2 as pdfium  # noqa: E402

from exactdoc.parse_pdfium import _Frame, parse_pdf  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None


def _reference(path, draw=None):
    """Text at user (100, 700), a 200x50 rect at (100, 600): the probe page."""
    c = _canvas.Canvas(path, pagesize=(612, 792))
    c.setFont("Helvetica", 12)
    c.drawString(100, 700, "Reference line at x100 baseline700")
    c.rect(100, 600, 200, 50, stroke=1, fill=0)
    if draw:
        draw(c)
    c.save()
    return path


def _post(src, dst, fn):
    pdf = pdfium.PdfDocument(src)
    try:
        for i in range(len(pdf)):
            fn(pdf[i])
        pdf.save(dst)
    finally:
        pdf.close()
    return dst


def _lines(ir, pno=0):
    return [ln for b in ir.pages[pno].blocks for ln in b.lines]


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class VisibleFrame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        d = cls._dir.name
        cls.ref = _reference(os.path.join(d, "ref.pdf"))
        cls.crop = _post(cls.ref, os.path.join(d, "crop.pdf"),
                         lambda p: p.set_cropbox(50, 50, 562, 742))
        cls.mbox = _post(cls.ref, os.path.join(d, "mbox.pdf"),
                         lambda p: p.set_mediabox(50, 50, 662, 842))

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def _one(self, path):
        ir = parse_pdf(path, keep_image_data=False)
        (line,) = _lines(ir)
        (rect,) = ir.pages[0].drawings
        return ir.pages[0], line, rect

    def test_plain_page_is_the_historical_flip(self):
        page, line, rect = self._one(self.ref)
        self.assertEqual((page.width, page.height), (612.0, 792.0))
        self.assertAlmostEqual(line.bbox[0], 100.0, places=3)
        self.assertAlmostEqual(line.baseline, 92.0, places=3)
        self.assertEqual(tuple(round(v, 3) for v in rect.bbox),
                         (100.0, 142.0, 300.0, 192.0))

    def test_cropbox_origin_is_subtracted(self):
        page, line, rect = self._one(self.crop)
        self.assertEqual((round(page.width), round(page.height)), (512, 692))
        # user (100, 700) in a window whose top-left is user (50, 742)
        self.assertAlmostEqual(line.bbox[0], 50.0, places=2)
        self.assertAlmostEqual(line.baseline, 42.0, places=2)
        self.assertEqual(tuple(round(v, 2) for v in rect.bbox),
                         (50.0, 92.0, 250.0, 142.0))

    def test_mediabox_origin_is_subtracted(self):
        page, line, rect = self._one(self.mbox)
        self.assertEqual((round(page.width), round(page.height)), (612, 792))
        self.assertAlmostEqual(line.bbox[0], 50.0, places=2)
        self.assertAlmostEqual(line.baseline, 142.0, places=2)
        self.assertEqual(tuple(round(v, 2) for v in rect.bbox),
                         (50.0, 192.0, 250.0, 242.0))


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class Rotation(unittest.TestCase):
    """A /Rotate 90 page is the landscape page a viewer shows."""

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        d = cls._dir.name

        # The ordinary way a landscape page is made by rotation: content drawn
        # turned a quarter in a portrait MediaBox, /Rotate 90 to read it.
        # Under /Rotate 90 a landscape point (X, Y) is portrait user
        # (612 - Y, X): the matrix [0 1 -1 0 612 0].
        def landscape(c):
            c.saveState()
            c.translate(612, 0)
            c.rotate(90)             # landscape x runs up portrait y
            c.setFont("Helvetica", 12)
            c.drawString(72, 540, "Landscape heading reads left to right")
            c.rect(72, 400, 300, 40, stroke=1, fill=0)
            c.restoreState()

        c = _canvas.Canvas(os.path.join(d, "turned.pdf"), pagesize=(612, 792))
        landscape(c)
        c.save()
        cls.turned = _post(os.path.join(d, "turned.pdf"),
                           os.path.join(d, "rot90.pdf"),
                           lambda p: p.set_rotation(90))
        # Drawings only: with no text to read, the displayed /Rotate decides.
        bare = os.path.join(d, "bare.pdf")
        c = _canvas.Canvas(bare, pagesize=(612, 792))
        c.rect(100, 600, 200, 50, stroke=1, fill=0)
        c.save()
        cls.rot = {deg: _post(bare, os.path.join(d, "r%d.pdf" % deg),
                              lambda p, deg=deg: p.set_rotation(deg))
                   for deg in (90, 180, 270)}
        # Upright text turned sideways by /Rotate: the page reads unrotated.
        ref = _reference(os.path.join(d, "ref.pdf"))
        cls.sideways = {deg: _post(ref, os.path.join(d, "s%d.pdf" % deg),
                                   lambda p, deg=deg: p.set_rotation(deg))
                        for deg in (90, 180, 270)}
        # Sideways content and NO /Rotate: a landscape table on a portrait sheet.
        c = _canvas.Canvas(os.path.join(d, "sheet.pdf"), pagesize=(612, 792))
        landscape(c)
        c.save()
        cls.sheet = os.path.join(d, "sheet.pdf")

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_rotated_landscape_page_reads_horizontally(self):
        ir = parse_pdf(self.turned, keep_image_data=False)
        page = ir.pages[0]
        self.assertEqual((round(page.width), round(page.height)), (792, 612))
        (line,) = _lines(ir)
        self.assertEqual(line.text, "Landscape heading reads left to right")
        self.assertTrue(line.horizontal)
        self.assertFalse(page.rotated)
        # landscape text at (72, 540) from the landscape bottom -> top-left 72
        self.assertAlmostEqual(line.bbox[0], 72.0, delta=0.5)
        self.assertAlmostEqual(line.baseline, 612.0 - 540.0, delta=0.5)
        (rect,) = page.drawings
        self.assertEqual(tuple(round(v, 1) for v in rect.bbox),
                         (72.0, 612.0 - 440.0, 372.0, 612.0 - 400.0))

    def test_rect_lands_where_the_viewer_draws_it(self):
        # user rect (100, 600)-(300, 650) on a 612x792 MediaBox
        want = {90: (600.0, 100.0, 650.0, 300.0),
                180: (312.0, 600.0, 512.0, 650.0),
                270: (142.0, 312.0, 192.0, 512.0)}
        for deg, path in self.rot.items():
            with self.subTest(rotate=deg):
                ir = parse_pdf(path, keep_image_data=False)
                (rect,) = ir.pages[0].drawings
                self.assertEqual(tuple(round(v, 1) for v in rect.bbox), want[deg])

    def test_upright_text_turned_sideways_is_read_upright(self):
        """In the displayed frame every glyph would be vertical, taken out of
        the flow by inference, and the page's text lost."""
        for deg, path in self.sideways.items():
            with self.subTest(rotate=deg):
                ir = parse_pdf(path, keep_image_data=False)
                page = ir.pages[0]
                self.assertEqual((round(page.width), round(page.height)), (612, 792))
                (line,) = _lines(ir)
                self.assertEqual(line.text, "Reference line at x100 baseline700")
                self.assertAlmostEqual(line.baseline, 92.0, places=2)
                (rect,) = page.drawings
                self.assertEqual(tuple(round(v, 1) for v in rect.bbox),
                                 (100.0, 142.0, 300.0, 192.0))

    def test_sideways_sheet_without_rotate_is_turned_to_read(self):
        ir = parse_pdf(self.sheet, keep_image_data=False)
        page = ir.pages[0]
        self.assertEqual((round(page.width), round(page.height)), (792, 612))
        (line,) = _lines(ir)
        self.assertEqual(line.text, "Landscape heading reads left to right")
        self.assertAlmostEqual(line.baseline, 612.0 - 540.0, delta=0.5)

    def test_figure_clips_are_rendered_in_the_reading_frame(self):
        """render_clip turns the render the way the parse turned the page, so
        a clip of the text's bbox holds the text's ink."""
        import io
        from PIL import Image
        from exactdoc.backend import PDFiumBackend
        bk = PDFiumBackend()
        for path in (self.sideways[90], self.sheet, self.turned):
            ir = parse_pdf(path, keep_image_data=False)
            (line,) = _lines(ir)
            png = bk.render_clip(path, 1, line.bbox, dpi=144)
            im = Image.open(io.BytesIO(png)).convert("L")
            with self.subTest(path=os.path.basename(path)):
                # a horizontal line of text: wider than tall, and inked
                self.assertGreater(im.width, 3 * im.height)
                self.assertLess(im.getextrema()[0], 100)
            session = bk.clip_renderer(path)
            try:
                self.assertEqual(session.render_clip(1, line.bbox, dpi=144), png)
            finally:
                session.close()

    def test_frame_matches_pdfium_page_to_device(self):
        """The mapping is PDFium's own: cross-checked against FPDF_PageToDevice."""
        import ctypes
        import pypdfium2.raw as raw
        for deg, path in self.rot.items():
            pdf = pdfium.PdfDocument(path)
            try:
                page = pdf[0]
                fr = _Frame.of(page)
                scale = 10           # PageToDevice answers in integer pixels
                W, H = int(fr.w * scale), int(fr.h * scale)
                for x, y in ((100.0, 600.0), (300.0, 650.0), (37.0, 81.0)):
                    dx, dy = ctypes.c_int(), ctypes.c_int()
                    raw.FPDF_PageToDevice(page.raw, 0, 0, W, H, 0, x, y,
                                          ctypes.byref(dx), ctypes.byref(dy))
                    got = fr.pt(x, y)
                    with self.subTest(rotate=deg, point=(x, y)):
                        self.assertAlmostEqual(got[0], dx.value / scale, delta=0.15)
                        self.assertAlmostEqual(got[1], dy.value / scale, delta=0.15)
                page.close()
            finally:
                pdf.close()


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class FormXObjects(unittest.TestCase):
    """Objects inside a form are placed through the form's matrix (B7)."""

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        path = os.path.join(cls._dir.name, "formx.pdf")
        c = _canvas.Canvas(path, pagesize=(612, 792))
        c.beginForm("inner")
        c.rect(0, 0, 30, 10, stroke=0, fill=1)
        c.endForm()
        c.beginForm("f1")
        c.rect(0, 0, 120, 40, stroke=1, fill=0)
        c.setFont("Helvetica", 10)
        c.drawString(5, 15, "inside form xobject")
        c.saveState()
        c.translate(200, 0)
        c.scale(2, 2)
        c.doForm("inner")            # a form inside a form, scaled
        c.restoreState()
        c.endForm()
        c.saveState()
        c.translate(150, 400)
        c.doForm("f1")
        c.restoreState()
        c.setFont("Helvetica", 12)
        c.drawString(72, 720, "page text outside form")
        c.save()
        cls.ir = parse_pdf(path, keep_image_data=False)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_rect_in_form_is_in_page_space(self):
        boxes = sorted(tuple(round(v, 1) for v in d.bbox)
                       for d in self.ir.pages[0].drawings)
        self.assertIn((150.0, 352.0, 270.0, 392.0), boxes)
        self.assertNotIn((0.0, 752.0, 120.0, 792.0), boxes)

    def test_nested_form_composes_both_matrices(self):
        boxes = sorted(tuple(round(v, 1) for v in d.bbox)
                       for d in self.ir.pages[0].drawings)
        # inner 30x10 rect, scaled 2x at (200, 0) inside f1, f1 at (150, 400)
        self.assertIn((350.0, 372.0, 410.0, 392.0), boxes)

    def test_text_in_form_is_unchanged(self):
        texts = {ln.text: ln for ln in _lines(self.ir)}
        self.assertAlmostEqual(texts["inside form xobject"].bbox[0], 155.0, delta=0.5)


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class OffPage(unittest.TestCase):
    """A printer's slug beyond the trim is not page content (defect #5)."""

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        d = cls._dir.name
        src = os.path.join(d, "slug_src.pdf")
        c = _canvas.Canvas(src, pagesize=(612, 900))
        c.setFont("Helvetica", 8)
        # above the 792pt trim: the Antenna House proof slug
        c.drawString(42, 860, "Page 2 of 52 Fileid: proofs MUST be removed before printing")
        c.line(42, 850, 570, 850)                       # slug rule, off-page
        c.setFont("Helvetica", 12)
        c.drawString(72, 700, "Body text on the trimmed page")
        c.line(72, 690, 540, 690)
        c.showPage()
        c.save()
        cls.pdf = _post(src, os.path.join(d, "slug.pdf"),
                        lambda p: p.set_cropbox(0, 0, 612, 792))
        cls.ir = parse_pdf(cls.pdf, keep_image_data=False)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_slug_text_is_not_extracted(self):
        texts = [ln.text for ln in _lines(self.ir)]
        self.assertEqual(texts, ["Body text on the trimmed page"])
        self.assertGreater(self.ir.pages[0].hidden_chars.get("offpage", 0), 40)

    def test_slug_rule_is_not_a_drawing(self):
        (rule,) = self.ir.pages[0].drawings
        self.assertAlmostEqual(rule.bbox[1], 792 - 690, delta=1.0)

    def test_refine_loop_lines_agree(self):
        """page_lines (what the refine loop compares) drops the slug too."""
        from exactdoc.backend import PDFiumBackend
        (lines,) = PDFiumBackend().page_lines(self.pdf)
        self.assertEqual([t for t, *_ in lines], ["Body text on the trimmed page"])


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class LinksInTheFrame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        d = cls._dir.name
        src = os.path.join(d, "links_src.pdf")
        c = _canvas.Canvas(src, pagesize=(612, 792))
        c.setFont("Helvetica", 12)
        c.drawString(100, 700, "the specification")
        c.linkURL("https://example.com/spec", (100, 695, 210, 715), relative=0)
        c.drawString(100, 500, "jump to section")
        c.linkAbsolute("jump", "sec1", (100, 495, 190, 515))
        c.showPage()
        c.bookmarkPage("sec1", fit="XYZ", left=0, top=600)
        c.drawString(100, 600, "Section One")
        c.showPage()
        c.save()
        cls.pdf = _post(src, os.path.join(d, "links.pdf"),
                        lambda p: p.set_cropbox(50, 50, 562, 742))
        cls.ir = parse_pdf(cls.pdf, keep_image_data=False)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_link_rect_and_anchor_text_share_the_frame(self):
        uri = [lk for lk in self.ir.pages[0].links if lk.get("uri")]
        (lk,) = uri
        self.assertEqual(tuple(round(v, 1) for v in lk["bbox"]),
                         (50.0, 742.0 - 715.0, 160.0, 742.0 - 695.0))
        spans = [s for ln in _lines(self.ir) for s in ln.spans
                 if s.link == "https://example.com/spec"]
        self.assertTrue(spans, "the anchor text lost its link")

    def test_goto_destination_is_in_the_target_frame(self):
        dests = [lk["dest"] for lk in self.ir.pages[0].links if "dest" in lk]
        self.assertTrue(dests)
        dest = dests[0]
        self.assertEqual(dest.page, 1)
        # user y 600 on a page whose visible top is user 742
        self.assertAlmostEqual(dest.y, 742.0 - 600.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
