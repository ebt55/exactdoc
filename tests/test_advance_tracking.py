"""Source advance scale: text a producer set wider than its font's advances.

Chromium on Linux rounds hinted glyph advances on the pixel grid, wide: the
Chromium expansion fixtures set Liberation Serif 11pt 6.2-6.6% wider than its
own AFM advances, with an interquartile range under 0.6%. A renderer given
natural advances fits ~6% more on a line, every 4-line paragraph re-wraps into
3, and x08_chrome_print_default drifted 27.7pt at the median. `tracking.py`
measures the scale on the regular face of metric-clone fonts and restores it
as the run's letter-spacing (`Run.tracking`) wherever the parser measured none
for the run itself; these tests pin both halves and the refusals.
"""
import unittest

from exactdoc import tracking
from exactdoc.ladder import predict_lines
from exactdoc.layout import DocLayout, PageLayout, Chunk, Para, Run
from exactdoc.metrics import get_metrics
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock

M = get_metrics()
WORDS = ("the depot replacement programme was approved on the understanding "
         "that service levels would be maintained throughout construction")


def _span(text, x0, y, *, scale=1.064, font="LiberationSerif", size=11.0,
          bold=False, italic=False):
    fam = "Times New Roman" if "Serif" in font or "Times" in font else "Arial"
    w = M.text_width(text, fam, size, bold=bold, italic=italic) * scale
    return Span(text=text, font=font, size=size, color="#111111", bold=bold,
                italic=italic, mono=False, serif="Serif" in font,
                superscript=False, bbox=(x0, y - 9.0, x0 + w, y + 2.0),
                origin=(x0, y))


def _ragged_doc(scale=1.064, n=8, **kw):
    """Blocks of three ragged lines each: no line is flush with its block."""
    blocks, y = [], 100.0
    words = WORDS.split()
    for b in range(n):
        lines = []
        for k, cut in enumerate((9, 7, 5)):
            sp = _span(" ".join(words[k:k + cut]), 58.0, y, scale=scale, **kw)
            lines.append(Line(spans=[sp], bbox=sp.bbox))
            y += 15.8
        blocks.append(TextBlock(lines=lines, bbox=(58.0, lines[0].bbox[1],
                                                   max(l.bbox[2] for l in lines),
                                                   lines[-1].bbox[3])))
        y += 10.0
    return DocIR(path="t.pdf", pages=[PageIR(1, 612.0, 792.0, blocks=blocks)])


class MeasureScale(unittest.TestCase):
    def test_widened_regular_face_is_measured(self):
        sc = tracking.measure_advance_scales(_ragged_doc(1.064), M)
        self.assertEqual(list(sc), [("liberationserif", 11.0)])
        self.assertAlmostEqual(sc[("liberationserif", 11.0)], 1.064, delta=0.002)

    def test_natural_advances_are_left_alone(self):
        # the LibreOffice and gated Chromium fixtures measure 0.999
        self.assertEqual(tracking.measure_advance_scales(_ragged_doc(0.999), M), {})

    def test_a_different_typeface_is_not_a_bias(self):
        # Palatino mapped to Times New Roman reads 1.11 on y24: substitution,
        # not rendering, and letter-spacing the substitute would be visible
        doc = _ragged_doc(1.064, font="Palatino-Roman")
        self.assertEqual(tracking.measure_advance_scales(doc, M), {})

    def test_bold_does_not_vote(self):
        # Adobe's Times-Bold AFM is not Times New Roman Bold (y08: 1.023 with
        # no bias present), so only the regular face is evidence
        doc = _ragged_doc(1.064, font="LiberationSerif-Bold", bold=True)
        self.assertEqual(tracking.measure_advance_scales(doc, M), {})

    def test_justified_lines_do_not_vote(self):
        # every line flush to one right edge: stretched word space, not font
        doc = _ragged_doc(1.064)
        for b in doc.pages[0].blocks:
            right = max(l.bbox[2] for l in b.lines)
            for ln in b.lines:
                ln.bbox = (ln.bbox[0], ln.bbox[1], right, ln.bbox[3])
        self.assertEqual(tracking.measure_advance_scales(doc, M), {})

    def test_scattered_evidence_is_not_a_bias(self):
        doc = _ragged_doc(1.064)
        for i, b in enumerate(doc.pages[0].blocks):
            if i % 2:
                for ln in b.lines:
                    s = ln.spans[0]
                    w = (s.bbox[2] - s.bbox[0]) * 1.08
                    s.bbox = (s.bbox[0], s.bbox[1], s.bbox[0] + w, s.bbox[3])
        self.assertEqual(tracking.measure_advance_scales(doc, M), {})


def _layout(runs):
    lay = DocLayout()
    p = Para(runs=runs, src_lines=4)
    lay.pages = [PageLayout(number=1, chunks=[Chunk(elements=[p])])]
    return lay, p


class ApplyTracking(unittest.TestCase):
    def test_every_style_of_the_face_gets_its_own_width_back(self):
        # fragments too short for the parser's per-span measurement (six
        # glyph gaps): a link, an italic abbreviation
        runs = [Run(text="Atlas", font="LiberationSerif", size=11.0,
                    color="#000000", serif=True),
                Run(text="et al.", font="LiberationSerif-Italic",
                    size=11.0, color="#000000", italic=True, serif=True),
                Run(text="\t", font="LiberationSerif", size=11.0,
                    color="#000000", is_tab=True)]
        lay, p = _layout(runs)
        n = tracking.apply_advance_tracking(
            lay, {("liberationserif", 11.0): 1.064}, M)
        self.assertEqual(n, 2)
        for r in runs[:2]:
            nat = M.text_width(r.text, "Times New Roman", 11.0, italic=r.italic)
            self.assertAlmostEqual(r.tracking * len(r.text), 0.064 * nat,
                                   delta=0.01)
            self.assertEqual(r.char_spacing, 0.0)       # the ladder's, not ours
        self.assertEqual(runs[2].tracking, 0.0)         # a tab has no glyphs

    def test_a_run_the_parser_measured_keeps_its_own_tracking(self):
        # parse_pdfium measures the same extra advance per span (x07: 0.291pt
        # against this module's 0.286pt); restored twice it would be 6% wide
        runs = [Run(text="Plain words here", font="LiberationSerif", size=11.0,
                    color="#000000", serif=True, tracking=0.29),
                Run(text="a link", font="LiberationSerif", size=11.0,
                    color="#000000", serif=True)]
        lay, _ = _layout(runs)
        self.assertEqual(tracking.apply_advance_tracking(
            lay, {("liberationserif", 11.0): 1.064}, M), 1)
        self.assertEqual(runs[0].tracking, 0.29)
        self.assertGreater(runs[1].tracking, 0.2)

    def test_a_run_the_parser_measured_as_untracked_stays_so(self):
        # long enough for the parser's measurement, which found none (x17's
        # bold role lines): its answer stands
        runs = [Run(text="Senior Backend Engineer", font="LiberationSerif-Bold",
                    size=11.0, color="#000000", bold=True, serif=True)]
        lay, _ = _layout(runs)
        self.assertEqual(tracking.apply_advance_tracking(
            lay, {("liberationserif", 11.0): 1.064}, M), 0)
        self.assertEqual(runs[0].tracking, 0.0)

    def test_other_sizes_are_untouched(self):
        runs = [Run(text="A heading", font="LiberationSerif", size=13.5,
                    color="#000000", serif=True)]
        lay, _ = _layout(runs)
        self.assertEqual(tracking.apply_advance_tracking(
            lay, {("liberationserif", 11.0): 1.064}, M), 0)
        self.assertEqual(runs[0].tracking, 0.0)


class LadderSeesTracking(unittest.TestCase):
    def _para(self):
        text = " ".join([WORDS] * 3)
        run = Run(text=text, font="LiberationSerif", size=11.0,
                  color="#000000", serif=True)
        nat = M.text_width(WORDS, "Times New Roman", 11.0)
        return Para(runs=[run]), run, nat

    def test_prediction_includes_the_source_advance_tracking(self):
        p, run, nat = self._para()
        avail = nat * 1.03          # one source line's worth at natural width
        before = predict_lines(p, avail, M)
        run.tracking = 0.064 * nat / len(WORDS)     # the source's, as measured
        after = predict_lines(p, avail, M)
        self.assertGreater(after, before)

    def test_a_locked_lines_compression_is_not_the_sources_tracking(self):
        # the ladder's own char_spacing (negative, from `_lock`) leaves its
        # open-loop predictions as they were before tracking.py existed
        p, run, nat = self._para()
        avail = nat * 1.03
        before = predict_lines(p, avail, M)
        run.char_spacing = -0.3
        self.assertEqual(predict_lines(p, avail, M), before)


def _tracked_pdf(path, char_space):
    """Ragged Times paragraphs set with uniform extra advance (PDF Tc)."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=(612, 792))
    words = WORDS.split()
    y = 700.0
    for b in range(6):
        for k, cut in enumerate((9, 7, 5)):
            t = c.beginText(72, y)
            t.setFont("Times-Roman", 11)
            t.setCharSpace(char_space)
            t.textLine(" ".join(words[k:k + cut]))
            c.drawText(t)
            y -= 15.8
        y -= 12.0
    c.save()


class EndToEnd(unittest.TestCase):
    def _rpr_spacing(self, docx):
        import re
        import zipfile
        xml = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8")
        return re.findall(r'<w:rPr>(?:(?!</w:rPr>).)*<w:spacing w:val="(-?\d+)"', xml)

    def test_standard_profile_restores_the_width_once(self):
        import os
        import tempfile
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "t.pdf")
            # 0.3pt per glyph on ~4.7pt Times glyphs is the ~6% Chromium bias;
            # the parser and this module both see it, and it is written ONCE
            _tracked_pdf(src, 0.3)
            std = os.path.join(d, "std.docx")
            convert(src, std, options=RAW, max_pages=0)
            vals = self._rpr_spacing(std)
            self.assertTrue(vals, "no tracking emitted in the standard profile")
            self.assertTrue(all(5 <= int(v) <= 7 for v in vals), vals)  # ~0.3pt

    def test_the_gdocs_profile_does_not_measure(self):
        # Docs discards run tracking (fonts.GDOCS_HONOURS_RUN_TRACKING)
        import os
        import tempfile
        from unittest import mock
        from exactdoc.convert import convert
        from exactdoc.options import PDFIUM_GDOCS_CANDIDATE
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "t.pdf")
            _tracked_pdf(src, 0.3)
            with mock.patch.object(tracking, "measure_advance_scales",
                                   side_effect=AssertionError("measured")):
                convert(src, os.path.join(d, "gd.docx"),
                        options=PDFIUM_GDOCS_CANDIDATE, max_pages=0)

    def test_untracked_source_gets_no_tracking(self):
        import os
        import tempfile
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "t.pdf")
            _tracked_pdf(src, 0.0)
            out = os.path.join(d, "o.docx")
            convert(src, out, options=RAW, max_pages=0)
            self.assertEqual(self._rpr_spacing(out), [])


if __name__ == "__main__":
    unittest.main()
