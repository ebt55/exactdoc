"""A manual's side-by-side example stands at its source height (WP46).

y22 (lshort) sets most of its examples as LaTeX source in monospace on the
left and the typeset result in a ruled frame on the right. Inference wrote
them one after the other -- the source, then the result -- so an example
took both heights: p58's third, 191pt of source then 170pt of result for a
189pt band, and 22 of the book's one-column pages ran past the body in the
page model by 2-398pt (WP35's Docs diagnosis). Now a band whose one side is
code (`infer.SBS_CODE_MONO`) and whose other side is typeset text, or a
picture, is a two-sided region (`infer._code_beside`, evidence "example"),
and a text block the parser grouped across the gutter is cut into its two
sides first (`infer._part_code_beside`). A list of monospaced terms beside
their definitions, row by row, stays a list.

    python -m unittest tests.test_code_beside_output
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import infer as I  # noqa: E402
from exactdoc.layout import FigureEl, TableEl  # noqa: E402
from exactdoc.model import Line, Span, TextBlock  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None

W, H = 595.0, 842.0
CODE = ["\\begin{equation}", "  a^2 + b^2 = c^2", "\\end{equation}",
        "Einstein says", "\\begin{equation}", "  E = mc^2", "\\end{equation}",
        "He didn't say", "\\begin{equation}", "  1 + 1 = 3", "\\end{equation}"]
RESULT = ["Add a squared and b squared to get c squared.",
          "Einstein says that energy equals mass times",
          "the speed of light squared, and he did not say",
          "that one and one make three, which it does not."]


def _example_pdf(path, frame=True):
    """Intro text, then an example: CODE in Courier at x=113 beside RESULT
    in Times at x=307 inside a frame of four hairlines, then more text."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Roman", 11)
    for i, t in enumerate(["The equation environment numbers what it sets.",
                           "Here is an example of it and of the eqref command."]):
        c.drawString(142, H - (140 + 14 * i), t)
    top = 200.0
    c.setFont("Courier", 10)
    for i, t in enumerate(CODE):
        c.drawString(113.4, H - (top + 12 * i), t)
    if frame:
        c.setLineWidth(0.1)
        x0, x1, y0, y1 = 298.3, 499.7, top + 20, top + 20 + 76
        for a, b, cc, d in ((x0, y0, x1, y0), (x0, y1, x1, y1),
                            (x0, y0, x0, y1), (x1, y0, x1, y1)):
            c.line(a, H - b, cc, H - d)
    c.setFont("Times-Roman", 10)
    for i, t in enumerate(RESULT):
        c.drawString(306.8, H - (top + 36 + 13 * i), t)
    c.setFont("Times-Roman", 11)
    for i in range(4):
        c.drawString(142, H - (top + 160 + 14 * i),
                     "After the example the text goes on in one column, %d." % i)
    c.showPage()
    c.save()


def _terms_pdf(path):
    """A list of monospaced options, each on the baseline of its definition."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    for i in range(6):
        y = H - (150 + 30 * i)
        c.setFont("Courier", 10)
        c.drawString(113.4, y, "--option-%d" % i)
        c.setFont("Times-Roman", 10)
        c.drawString(306.8, y, "Sets option %d for the whole run and" % i)
        c.drawString(306.8, y - 12, "every file it reads after that.")
    c.showPage()
    c.save()


def _infer(path):
    from exactdoc.dialect import normalize
    from exactdoc.parse_pdfium import parse_pdf
    return I.infer(normalize(parse_pdf(path, keep_image_data=True)))


def _els(lay):
    return [el for ch in lay.pages[0].chunks for el in ch.elements]


def _span(text, x, base, mono, size=10.0):
    w = 0.6 * size * len(text) if mono else 0.45 * size * len(text)
    return Span(text=text, font="Courier" if mono else "Times-Roman", size=size,
                color="#000000", bold=False, italic=False, mono=mono,
                serif=not mono, superscript=False,
                bbox=(x, base - 0.8 * size, x + w, base + 0.2 * size),
                origin=(x, base))


def _line(*spans):
    return Line(spans=list(spans),
                bbox=(min(s.bbox[0] for s in spans), min(s.bbox[1] for s in spans),
                      max(s.bbox[2] for s in spans), max(s.bbox[3] for s in spans)))


def _blk(lines):
    blk = TextBlock(lines=lines, bbox=None)
    blk.bbox = (min(l.bbox[0] for l in lines), min(l.bbox[1] for l in lines),
                max(l.bbox[2] for l in lines), max(l.bbox[3] for l in lines))
    return ("blk", blk.bbox, blk)


class TheEvidence(unittest.TestCase):
    def _sides(self, code_lines, text_lines, text_x=306.8):
        left = [_blk([_line(_span(t, 113.4, 200 + 12 * i, True))
                      for i, t in enumerate(code_lines)])]
        right = [_blk([_line(_span(t, text_x, 206 + 13 * i, False))
                       for i, t in enumerate(text_lines)])] if text_lines else []
        return left, right

    def test_code_beside_its_result_is_an_example(self):
        left, right = self._sides(CODE[:5], RESULT[:2])
        self.assertTrue(I._code_beside(left, right))
        self.assertTrue(I._code_beside(right, left))       # either side

    def test_one_line_of_code_is_a_term_not_an_example(self):
        left, right = self._sides(CODE[:1], RESULT[:2])
        self.assertFalse(I._code_beside(left, right))

    def test_code_beside_code_is_not_an_example(self):
        left = [_blk([_line(_span(t, 113.4, 200 + 12 * i, True)) for i, t in enumerate(CODE[:4])])]
        right = [_blk([_line(_span(t, 306.8, 200 + 12 * i, True)) for i, t in enumerate(CODE[4:8])])]
        self.assertFalse(I._code_beside(left, right))

    def test_terms_on_their_definitions_baselines_are_rows(self):
        left = [_blk([_line(_span("--opt-%d" % i, 113.4, 200 + 24 * i, True))
                      for i in range(5)])]
        right = [_blk([_line(_span("Sets option %d for the run" % i, 306.8,
                                   200 + 24 * i + d, False))
                       for i in range(5) for d in (0, 12)])]
        self.assertFalse(I._code_beside(left, right))

    def test_a_picture_is_a_result(self):
        left, _ = self._sides(CODE[:5], None)
        fig = FigureEl(page_no=1, clip=(306.8, 200.0, 486.8, 320.0),
                       width=180.0, height=120.0)
        right = [("el", (306.8, 200.0, 486.8, 320.0), fig)]
        self.assertTrue(I._code_beside(left, right))

    def test_a_drawn_grid_without_a_word_is_a_picture(self):
        from exactdoc.layout import Cell, Para, Run
        t = TableEl(rows=[[Cell(paras=[Para(runs=[Run(text="☞ ✔", font="x",
                                                       size=10, color="#000000")])])]])
        self.assertTrue(I._textless_table(t))
        t.rows[0][0].paras[0].runs[0].text = "x = 1"
        self.assertFalse(I._textless_table(t))


class TheBlockCut(unittest.TestCase):
    def test_a_block_across_the_gutter_is_cut_into_its_sides(self):
        # y22 p46: source and result lines interleaved in one parser block
        lines = []
        for i, t in enumerate(CODE[:5]):
            lines.append(_line(_span(t, 113.4, 200 + 12 * i, True)))
            if i < 3:
                lines.append(_line(_span(RESULT[i][:30], 306.8, 200.4 + 12 * i, False)))
        items = I._part_code_beside([_blk(lines)])
        self.assertEqual(len(items), 2)
        xs = sorted(it[1][0] for it in items)
        self.assertAlmostEqual(xs[0], 113.4, delta=0.1)
        self.assertAlmostEqual(xs[1], 306.8, delta=0.1)

    def test_a_block_with_code_on_both_sides_of_text_is_kept(self):
        lines = [_line(_span(CODE[0], 113.4, 200, True)),
                 _line(_span(RESULT[0][:20], 306.8, 212, False)),
                 _line(_span(CODE[1], 113.4, 224, True)),
                 _line(_span(CODE[2], 400.0, 236, True))]
        items = [_blk(lines)]
        self.assertIs(I._part_code_beside(items), items)


@unittest.skipIf(_canvas is None, "reportlab not installed")
class EndToEnd(unittest.TestCase):
    def test_the_example_is_one_region_at_its_source_height(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ex.pdf")
            _example_pdf(p)
            lay = _infer(p)
        tables = [el for el in _els(lay) if isinstance(el, TableEl) and el.role == "layout"]
        self.assertEqual(len(tables), 1)
        t = tables[0]
        self.assertEqual(getattr(t, "_sbs", None), "example")
        cells = t.rows[0]
        texts = [" ".join(p.text for p in c.paras) for c in cells if c is not None]
        self.assertTrue(any("begin{equation}" in s for s in texts))
        self.assertTrue(any("Einstein says that energy" in s for s in texts))
        # the region is the band's height, not the two sides stacked
        self.assertLess(t.bbox[3] - t.bbox[1], 12 * len(CODE) + 20)

    def test_without_a_frame_too(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ex.pdf")
            _example_pdf(p, frame=False)
            lay = _infer(p)
        self.assertTrue(any(isinstance(el, TableEl) and getattr(el, "_sbs", None) == "example"
                            for el in _els(lay)))

    def test_a_term_list_stays_a_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "terms.pdf")
            _terms_pdf(p)
            lay = _infer(p)
        self.assertFalse(any(isinstance(el, TableEl) and getattr(el, "_sbs", None) == "example"
                             for el in _els(lay)))


if __name__ == "__main__":
    unittest.main()
