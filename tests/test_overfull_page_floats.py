"""A first page of placed pictures the flow cannot hold is laid out as a slide (WP50).

The mechanism. A front page set as a composition -- a masthead with a badge
beside it, photographs down a sidebar beside the lead story; a cover's grid
of partner logos over a hero picture and the title -- is placed, not
flowed. A flow stacks its pictures one after another, the stack is taller
than the page by more than its gaps can pay, the page spills, and every
later page sits one place late (a 10-page newsletter rendered 12, a 15-page
agency report 17 with its title broken over pages 1 and 2).

`infer._float_overfull` gives such a page the deck's treatment: graphics
anchored where the source set them (`_float_graphics`), text page-locked
where it was (`_lock_slide`). Only on page one, only when the page model
says the stack overruns the box by more than its gaps can pay AND two of its
graphics stand side by side, never on a page whose paragraph runs on over
the seam. Standard profiles only (`anchored`); the Google Docs profile keeps
the flow.

    python -m unittest tests.test_overfull_page_floats
"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from exactdoc import infer as I                                # noqa: E402

try:
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as _canvas
    from PIL import Image
except ImportError:                                    # pragma: no cover
    _canvas = None

W, H = 612.0, 792.0
LINE = ("Manufacturers should take ownership of the security outcomes of "
        "their customers.")


def _logo(seed, w=240, h=120):
    im = Image.new("RGB", (w, h), (255, 255, 255))
    px = im.load()
    for x in range(w):
        for y in range(h):
            if (x // (8 + seed) + y // (6 + seed)) % 3 == 0:
                px[x, y] = (20 * seed % 255, 80, 160)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    buf.seek(0)
    return ImageReader(buf)


def _composed_pdf(path, body_pages=2, photos=3, lines=32):
    """Page 1, a newsletter's front page: a masthead with a badge beside it,
    a sidebar of `photos` photographs down the left, a headline and `lines`
    lines of the lead story in the column beside them, a name line at the
    foot -- every object placed. Then `body_pages` pages of ordinary text.

    Stacked, the sidebar stands above the story it is set beside: the page
    model reads ~1100pt of flow for a ~690pt box."""
    c = _canvas.Canvas(path, pagesize=(W, H))

    def img(seed, x, top, w, h, iw=240, ih=120):
        c.drawImage(_logo(seed, iw, ih), x, H - top - h, width=w, height=h)
    img(1, 20, 20, 300, 110)                       # masthead
    img(2, 340, 30, 250, 90)                       # badge beside it
    for k, (top, h) in enumerate(((200, 180), (420, 120), (580, 120))[:photos]):
        img(3 + k, 18, top, 142, h, 160, 160)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(192, H - 200, "FROM THE DIRECTOR")
    c.setFont("Times-Roman", 11)
    words = LINE.split()
    for i in range(lines):
        c.drawString(190, H - 236 - 14.5 * i,
                     " ".join(words[i % 4:i % 4 + 9]) + ".")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20, H - 745, "THE DIRECTOR, PUBLIC AGENCY")
    c.showPage()
    for _ in range(body_pages):
        c.setFont("Times-Roman", 11)
        for i in range(40):
            c.drawString(72, H - 80 - 15 * i, LINE)
        c.showPage()
    c.save()


def _infer(pdf, anchored):
    from exactdoc.backend import get_backend
    from exactdoc.dialect import normalize
    from exactdoc.input import parse as parse_input
    return I.infer(normalize(parse_input(get_backend("pdfium"), pdf)),
                   anchored=anchored, anchor_pictures=True)


@unittest.skipUnless(_canvas is not None, "needs reportlab and Pillow")
class TheComposedCover(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = os.path.join(cls._dir.name, "composed.pdf")
        _composed_pdf(cls.pdf)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_its_graphics_are_anchored_and_its_text_flows(self):
        lay = _infer(self.pdf, anchored=True)
        p1 = lay.pages[0]
        self.assertEqual(len(p1.floats), 5, "masthead, badge, 3 photographs")
        flow = [el for ch in p1.chunks for el in ch.elements]
        self.assertFalse([el for el in flow
                          if isinstance(el, (I.ImageEl, I.FigureEl))])
        text = " ".join(el.text for el in flow if isinstance(el, I.Para))
        self.assertIn("FROM THE DIRECTOR", text)

    def test_ordinary_text_pages_are_untouched(self):
        lay = _infer(self.pdf, anchored=True)
        for pg in lay.pages[1:]:
            self.assertEqual(pg.floats, [])

    def test_the_flow_profile_keeps_its_flow(self):
        """gdocs (no `anchored`): the pictures stay in the flow as before."""
        lay = _infer(self.pdf, anchored=False)
        flow = [el for ch in lay.pages[0].chunks for el in ch.elements]
        self.assertTrue(any(isinstance(el, (I.ImageEl, I.FigureEl, I.TableEl))
                            for el in flow))

    def test_a_page_that_fits_is_never_touched(self):
        d = tempfile.mkdtemp(dir=self._dir.name)
        pdf = os.path.join(d, "fits.pdf")
        _composed_pdf(pdf, photos=1, lines=8)
        old = I.OVERFULL_FLOATS
        try:
            I.OVERFULL_FLOATS = False
            off = _infer(pdf, anchored=True)
        finally:
            I.OVERFULL_FLOATS = old
        on = _infer(pdf, anchored=True)
        self.assertEqual(len(on.pages[0].floats), len(off.pages[0].floats))

    @unittest.skipUnless(shutil.which("soffice") and
                         importlib.util.find_spec("fitz"),
                         "renders with LibreOffice and reads with PyMuPDF")
    def test_it_renders_page_for_page(self):
        sys.path.insert(0, os.path.join(ROOT, "testkit"))
        import fitz
        import harness
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        out = os.path.join(self._dir.name, "c.docx")
        convert(self.pdf, out, options=RAW, max_pages=0)
        with zipfile.ZipFile(out) as z:
            self.assertGreaterEqual(
                z.read("word/document.xml").decode("utf-8").count("<wp:anchor"),
                5)
        rendered = fitz.open(harness.docx_to_pdf(out, self._dir.name))
        self.assertEqual(len(rendered), 3)
        words = " ".join(w[4] for w in rendered[0].get_text("words"))
        for w in ("DIRECTOR", "Manufacturers", "AGENCY"):
            self.assertIn(w, words)


class TheSeamRule(unittest.TestCase):
    def _page(self, n, texts):
        from exactdoc.model import Line, PageIR, Span, TextBlock
        p = PageIR(number=n, width=W, height=H)
        lines = []
        for i, t in enumerate(texts):
            bb = (72.0, 100.0 + 14 * i, 300.0, 112.0 + 14 * i)
            lines.append(Line(spans=[Span(
                text=t, font="Times", size=11, color="#000000", bold=False,
                italic=False, mono=False, serif=True, superscript=False,
                bbox=bb, origin=(bb[0], bb[3] - 2))], bbox=bb))
        p.blocks = [TextBlock(lines=lines, bbox=(72.0, 100.0, 300.0, 400.0))]
        return p

    def _hf(self):
        from collections import defaultdict
        return {"consumed_text": defaultdict(set)}

    def test_a_sentence_running_over_the_seam(self):
        a = self._page(1, ["The agencies urge manufacturers to"])
        b = self._page(2, ["revamp their design and development."])
        self.assertTrue(I._runs_over_seam(self._hf(), a, b))

    def test_a_closed_page(self):
        a = self._page(1, ["The agencies urge manufacturers to act."])
        b = self._page(2, ["revamp their design and development."])
        self.assertFalse(I._runs_over_seam(self._hf(), a, b))
        c = self._page(2, ["Overview of the principles"])
        a2 = self._page(1, ["The agencies urge manufacturers to"])
        self.assertFalse(I._runs_over_seam(self._hf(), a2, c))
        self.assertFalse(I._runs_over_seam(self._hf(), a2, None))


if __name__ == "__main__":
    unittest.main()
