"""A row of cards is a row, and a paragraph that loses a line moves the page.

Two defects on `c1_whitepaper` -- the gated fixture standing in for the exact
document class this converter exists for -- were cancelling each other, and each
one alone measured within2pt 0.0000 in BOTH parser arms.

D-A, shared by both arms. c1's cover band is a Chromium full-bleed fill inset to
y0=7.16, past `detect_hf.top_bands`' `y0 <= 2.5` seed gate, so it ships as an
ordinary in-flow `box` table. Its cell holds ONE paragraph carrying two source
lines -- a 9.77pt title and an 8.0pt subtitle -- because
`_split_lines_to_paras` splits on a size ratio over 1.3 (9.77/8.00 = 1.221) or a
baseline gap over max(lead*1.55, lead+4) = 26.3pt (the gap is 16.94pt). Neither
fires. The renderer sets both runs on one line, the row renders 98.15pt against
a declared 112.68pt, and every element below inherits -11.7pt. Measured on the
first body line: -11.87. The quality ladder fixes exactly this and was switched
off by default, so it never ran.

D-B, PyMuPDF only. The three stat cards share an exact y-extent and sit in
9.33pt gutters; after `build_figure`'s +/-2pt clip padding the gap is 5.3pt,
which a 4pt merge expansion missed. Three stacked block figures cost 171pt of
flow against the source's 57pt: a +115pt step at the card row, and page 1
overflowing onto a third page. PDFium merged the row on its own and showed no
step -- the arms disagreeing was the evidence that the row is one figure.

The cancellation is the point. Fixing D-A alone measured c1's raw-lane dy_p50
101 -> 116.2, because the -11.7pt had been partly hiding the +115pt. The two
land together or not at all, and these tests pin both halves so neither can be
reverted quietly.
"""
import unittest

import mupdf_extra

from exactdoc import ladder
from exactdoc.infer import FIG_MERGE_GAP, _merge_figures, _split_lines_to_paras
from exactdoc.layout import FigureEl, Para, Run
from exactdoc.metrics import get_metrics
from exactdoc.model import Line, Span
from exactdoc.options import PRODUCT, RAW, ConversionOptions

# c1_whitepaper page 1, as the parser reports it.
CARD_CLIPS = [(59.8, 222.2, 220.5, 279.5),
              (225.8, 222.2, 387.2, 279.5),
              (392.5, 222.2, 553.2, 279.5)]
BAND_TITLE_Y = (68.32, 79.24)
BAND_SUB_Y = (85.26, 94.20)


def _fig(clip):
    return FigureEl(page_no=1, clip=clip, width=clip[2] - clip[0],
                    height=clip[3] - clip[1])


def _line(text, y0, y1, size, x0=59.4, x1=None):
    x1 = x1 if x1 is not None else x0 + 6.0 * len(text)
    sp = Span(text=text, font="LiberationSans", size=size, color="#ffffff",
              bold=False, italic=False, mono=False, serif=False,
              superscript=False, bbox=(x0, y0, x1, y1),
              origin=(x0, y1 - 2.0))
    return Line(spans=[sp], bbox=(x0, y0, x1, y1))


class LadderDefault(unittest.TestCase):
    """The ladder is on. It was off, and c1 is why that changed."""

    def test_the_shipping_profile_runs_the_ladder(self):
        self.assertTrue(PRODUCT.ladder)

    def test_the_open_loop_control_runs_the_ladder_too(self):
        # RAW differs from PRODUCT only in feedback; if the ladder were off
        # here the gate's control lane would measure a different converter.
        self.assertTrue(RAW.ladder)

    def test_the_dataclass_default_is_on(self):
        self.assertTrue(ConversionOptions().ladder)

    def test_a_caller_can_still_turn_it_off(self):
        self.assertFalse(ConversionOptions(ladder=False).ladder)


class BandParagraphKeepsItsLines(unittest.TestCase):
    """The title/subtitle pair the splitter cannot separate, the ladder must."""

    def _band_para(self):
        title = _line("oduction RAG degrades quietly - and what to measure "
                      "instead ", BAND_TITLE_Y[0], BAND_TITLE_Y[1], 9.77,
                      x0=59.4, x1=335.3)
        sub = _line(" Whitepaper - July 2026", BAND_SUB_Y[0], BAND_SUB_Y[1],
                    8.00, x0=61.8, x1=146.3)
        return title, sub

    def test_the_splitter_still_merges_them(self):
        # Not a wish -- a record of why the ladder has to be the one to fix it.
        # Ratio 9.77/8.00 = 1.221 < 1.3; gap 16.94 < 26.3.
        title, sub = self._band_para()
        groups = _split_lines_to_paras([title, sub])
        self.assertEqual(len(groups), 1,
                         "if this ever splits, re-derive the ladder's necessity")

    @mupdf_extra.needs_extra
    def test_the_ladder_locks_a_paragraph_the_renderer_would_unwrap(self):
        # The one test in this class that needs the extra, and it is worth
        # saying why rather than skipping quietly: this IS the c1 defect, and
        # without base-14 metrics `predict_lines` returns None, so a default
        # install does not get this fix. That is not a gap in the test -- it is
        # a measured product difference, quantified per document in
        # docs/evidence/base-wheel-proof-2026-08-06.json (c1 raw-lane dy_p50
        # 13.49 without the extra against 2.00 with it).
        p = Para(runs=[Run(text="oduction RAG degrades quietly - and what to "
                                "measure instead ", font="LiberationSans",
                           size=9.77, color="#ffffff"),
                       Run(text=" Whitepaper - July 2026",
                           font="LiberationSans", size=8.00, color="#ffffff")],
                 leading=15.33)
        p.src_lines = 2
        p.src_widths = [275.9, 84.5]
        avail = 591.36                      # c1's band cell, 599.36 less padding
        metrics = get_metrics("mupdf")
        self.assertEqual(ladder.predict_lines(p, avail, metrics), 1,
                         "the whole defect: two source lines re-wrap to one")
        self.assertTrue(ladder._lock(p, avail, metrics))
        self.assertTrue(p.line_breaks)
        self.assertEqual(p.fidelity, "line-locked")
        self.assertIn("\n", "".join(r.text for r in p.runs))


class CardRowIsOneFigure(unittest.TestCase):
    """Side-by-side regions merge; a stack of them is 114pt of invented flow."""

    def test_the_three_stat_cards_become_one_row(self):
        out = _merge_figures([_fig(c) for c in CARD_CLIPS])
        figs = [e for e in out if isinstance(e, FigureEl)]
        self.assertEqual(len(figs), 1)
        self.assertAlmostEqual(figs[0].clip[0], 59.8, places=2)
        self.assertAlmostEqual(figs[0].clip[2], 553.2, places=2)

    def test_the_merged_row_keeps_the_source_row_height(self):
        figs = [e for e in _merge_figures([_fig(c) for c in CARD_CLIPS])
                if isinstance(e, FigureEl)]
        # 57.3pt of flow, not 3 x 57.3. This is the +115pt step, prevented.
        self.assertAlmostEqual(figs[0].height, 57.3, places=1)
        self.assertAlmostEqual(figs[0].width, 493.4, places=1)

    def test_the_gap_clears_c1s_padded_gutter_with_margin(self):
        gap = CARD_CLIPS[1][0] - CARD_CLIPS[0][2]      # 5.3pt
        self.assertGreater(FIG_MERGE_GAP, gap)
        self.assertLess(FIG_MERGE_GAP, 9.33,           # the raw source gutter
                        "must not reach across a gutter the source meant")

    def test_figures_a_source_genuinely_separated_stay_separate(self):
        far = [(59.8, 222.2, 220.5, 279.5), (240.0, 222.2, 400.0, 279.5)]
        figs = [e for e in _merge_figures([_fig(c) for c in far])
                if isinstance(e, FigureEl)]
        self.assertEqual(len(figs), 2)

    def test_vertically_stacked_figures_still_merge_when_touching(self):
        # The rule is proximity in any direction and always was; widening it
        # must not have made it directional.
        stacked = [(59.8, 222.2, 220.5, 279.5), (59.8, 283.0, 220.5, 330.0)]
        figs = [e for e in _merge_figures([_fig(c) for c in stacked])
                if isinstance(e, FigureEl)]
        self.assertEqual(len(figs), 1)

    def test_a_non_figure_element_is_returned_untouched(self):
        p = Para(runs=[Run(text="body", font="Times", size=10.0,
                           color="#000000")])
        out = _merge_figures([_fig(CARD_CLIPS[0]), p, _fig(CARD_CLIPS[1])])
        self.assertIn(p, out)
        self.assertEqual(len([e for e in out if isinstance(e, FigureEl)]), 1)


if __name__ == "__main__":
    unittest.main()
