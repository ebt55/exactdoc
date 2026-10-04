"""Source letter-spacing measured, carried and written (catalogue #10).

`Run.char_spacing` was only ever set by the ladder's compression, so résumé
headings lost their tracking, Chromium body text lost the 5-7% its drawn lines
carry over the font's advances (and re-wrapped), and the World Development
Report kept `O V E R V I E W` as eight words.

    python tests/test_letter_spacing.py
"""
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import hyphen  # noqa: E402
from exactdoc.infer import runs_from_spans  # noqa: E402
from exactdoc.layout import Chunk, DocLayout, PageLayout, Para, Run  # noqa: E402
from exactdoc.model import Span  # noqa: E402
from exactdoc.parse_pdfium import _Char, _build_lines, _span_tracking  # noqa: E402


def _char(u, x0, x1, size=10.0):
    c = _Char()
    c.u = u
    c.x0, c.x1 = x0, x1
    c.y0, c.y1 = 90.0, 100.0
    c.ox, c.oy = x0, 100.0
    c.size = size
    c.font = "Sans"
    c.flags = 0
    c.color = "#000000"
    c.gen = False
    return c


def _set(text, gaps, adv=5.0, size=10.0):
    """Glyphs of `text` with the given gap after each (cycled)."""
    out, x = [], 10.0
    for i, ch in enumerate(text):
        out.append(_char(ch, x, x + adv, size))
        x += adv + gaps[i % len(gaps)]
    return out


class Measurement(unittest.TestCase):
    def test_uniform_heading_tracking(self):
        # the owner's resume: 1.5pt on 9.49pt type, every gap the same
        cs = _set("EXPERIENCE", [1.5], size=9.49)
        track, spaced = _span_tracking(cs)
        self.assertAlmostEqual(track, 1.5, places=2)
        self.assertFalse(spaced)

    def test_noisy_positive_spacing_emits_its_mean(self):
        # Chromium body text: positions on a pixel grid, mean ~0.03em
        cs = _set("maintained", [0.55, 0.0, 0.3, 0.45, 0.2])
        track, _ = _span_tracking(cs)
        self.assertAlmostEqual(track, sum([0.55, 0.0, 0.3, 0.45, 0.2,
                                           0.55, 0.0, 0.3, 0.45]) / 9, places=2)

    def test_rounding_with_a_long_tail_is_not_tracking(self):
        # cairo: a median of 0.023em pulled down to a mean of 0.013em by the
        # odd tightly-kerned pair -- rounding, not spacing
        cs = _set("protocols", [0.23, 0.23, 0.23, 0.23, -0.6])
        self.assertEqual(_span_tracking(cs), (0.0, False))

    def test_kerning_is_not_emitted(self):
        cs = _set("redirections", [-0.3])
        self.assertEqual(_span_tracking(cs), (0.0, False))

    def test_untracked_text(self):
        cs = _set("ordinary", [0.0])
        self.assertEqual(_span_tracking(cs), (0.0, False))

    def test_spaced_capitals(self):
        # WDR: OVERVIEW at 20pt with 8.4pt between letters, each gap wider
        # than a space so the parser puts a space in each.
        cs = _set("OVERVIEW", [8.4], adv=12.0, size=20.0)
        line = _build_lines(cs)[0]
        self.assertTrue(line.spans[0].spaced_letters)
        self.assertAlmostEqual(line.spans[0].tracking, 8.4, places=2)
        self.assertEqual(line.text.replace(" ", ""), "OVERVIEW")


def _span(text, tracking=0.0, spaced=False):
    return Span(text=text, font="Sans", size=20.0, color="#000000", bold=True,
                italic=False, mono=False, serif=False, superscript=False,
                bbox=(0, 0, 100, 20), origin=(0, 20), tracking=tracking,
                spaced_letters=spaced)


class Carrying(unittest.TestCase):
    def test_tracking_reaches_the_run(self):
        self.assertEqual(runs_from_spans([_span("SUMMARY", 1.5)])[0].tracking, 1.5)

    def test_spaced_capitals_close_up_when_the_document_spells_the_word(self):
        ev = hyphen.HyphenEvidence([["The Overview chapter opens the report."]])
        token = hyphen.activate(ev)
        try:
            r = runs_from_spans([_span("O V E R V I E W", 8.4, True)])[0]
        finally:
            hyphen.deactivate(token)
        self.assertEqual((r.text, r.tracking), ("OVERVIEW", 8.4))

    def test_a_row_of_letters_keeps_its_spaces(self):
        ev = hyphen.HyphenEvidence([["Index"]])
        token = hyphen.activate(ev)
        try:
            r = runs_from_spans([_span("A B C D E", 8.4, True)])[0]
        finally:
            hyphen.deactivate(token)
        self.assertEqual((r.text, r.tracking), ("A B C D E", 0.0))

    def test_lines_of_nearly_equal_spacing_merge(self):
        runs = runs_from_spans([_span("ab ", 0.30), _span("cd", 0.36)])
        self.assertEqual(len(runs), 1)
        self.assertAlmostEqual(runs[0].tracking, (0.30 * 3 + 0.36 * 2) / 5, places=3)


class Writing(unittest.TestCase):
    def test_writer_emits_tracking_plus_ladder_compression(self):
        from exactdoc.docxout import write_docx
        lay = DocLayout()
        r = Run(text="SUMMARY", font="Arial", size=9.5, color="#000000",
                tracking=1.5, char_spacing=-0.25)
        lay.pages = [PageLayout(number=1, chunks=[Chunk(elements=[
            Para(runs=[r])])])]
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            write_docx(lay, path)
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode()
        finally:
            os.unlink(path)
        self.assertIn('<w:spacing w:val="25"/>', xml)   # (1.5 - 0.25) * 20

    def test_ladder_widths_include_tracking(self):
        from exactdoc.ladder import _seg_width
        from exactdoc.metrics import get_metrics
        m = get_metrics()
        plain = Run(text="SUMMARY", font="Helvetica", size=10.0, color="#000000")
        tracked = Run(text="SUMMARY", font="Helvetica", size=10.0,
                      color="#000000", tracking=1.5)
        w0 = _seg_width([plain], {}, m)
        w1 = _seg_width([tracked], {}, m)
        if w0 < 0:
            self.skipTest("no shaper for Helvetica in this install")
        self.assertAlmostEqual(w1 - w0, 7 * 1.5, places=3)


if __name__ == "__main__":
    unittest.main()
