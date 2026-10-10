"""The refine loop measures a page's offset at the baseline (WP39).

A line's top is its baseline less the ascent the PDF's copy of the font
declares, so two documents set in different fonts disagree about tops where
their text agrees: Word embeds Times New Roman declaring a box top 1.040 em
above the baseline, and LibreOffice draws it as Liberation Serif at 0.891 em.
Measured at tops, a render whose every baseline matched the source read
0.149 em "low", and the loop moved the page up by that much -- y01_nist_sp80063b
came out of the product profile 1.7pt above its source baselines. These tests
pin the measurement on synthetic page lines: equal baselines read no offset
whatever the fonts' ascents, and a real offset still reads as itself.

    python -m unittest tests.test_refine_anchor
"""
import unittest

from exactdoc import refine as R

SIZE = 11.0
BODY = ["section %d of the synthetic page, distinct text" % k for k in range(8)]


def _lines(asc_em, shift=0.0, first=100.0, pitch=13.2):
    """page_lines rows (text, top, baseline, bottom) for BODY, set in a font
    whose box top is `asc_em` above the baseline."""
    out = []
    for k, t in enumerate(BODY):
        base = first + k * pitch + shift
        out.append((t, base - asc_em * SIZE, base, base + 0.216 * SIZE))
    return out


class _Backend:
    name = "fake"

    def __init__(self, pages):
        self.pages = pages

    def page_lines(self, path):
        return self.pages[path]


def _offset(src, out):
    return R._measure("s", "r", _Backend({"s": [src], "r": [out]}))["offset"][0]


class BaselineAnchor(unittest.TestCase):
    def test_the_loop_anchors_at_the_baseline(self):
        self.assertEqual(R.ANCHOR, R.ANCHOR_BASELINE)

    def test_equal_baselines_in_fonts_of_different_ascent_read_no_offset(self):
        # Word's embedded Times New Roman (1.040 em) against Liberation Serif
        # (0.891 em), every baseline where the source has it
        self.assertEqual(_offset(_lines(1.040), _lines(0.891)), 0.0)
        # the top anchor reads the ascent difference as an offset to correct
        top = R._lines_from_page_lines([_lines(1.040)], R.ANCHOR_TOP)[0]
        top_out = R._lines_from_page_lines([_lines(0.891)], R.ANCHOR_TOP)[0]
        ds = sorted(o[1] - s[1] for s, o in zip(top, top_out))
        self.assertAlmostEqual(ds[len(ds) // 2], 0.149 * SIZE, places=6)

    def test_a_real_offset_is_still_measured(self):
        self.assertAlmostEqual(_offset(_lines(1.040), _lines(0.891, shift=3.0)), 3.0)
        self.assertAlmostEqual(_offset(_lines(0.905), _lines(0.905, shift=-2.5)), -2.5)

    def test_the_overflow_band_still_reads_line_bottoms(self):
        # `need` and `room` come from line bottoms; the anchor only places a
        # line in the body band, and a body line's baseline is inside it
        src, out = _lines(1.040), _lines(0.891)
        m = R._measure("s", "r", _Backend({"s": [src], "r": [out]}),
                       geom=(792.0, 72.0, 720.0))
        self.assertAlmostEqual(m["room"][0], 720.0 - out[-1][3])


class PushedPagesAreTheRendersToAnswer(unittest.TestCase):
    """A page the loop moved down within its measured room is planned by the
    writer's open-loop spill prediction as it was before the push, and the
    push is added back. Re-planned with the push, y44_cv_rendercv_typst p1
    took the push back (34pt high); not planned at all (WP39's first guard),
    y18_eurlex_ai_act p15 lost the cuts its measured render had and spilled
    (WP39b)."""

    def _page(self, gap=10.0):
        from exactdoc.layout import Chunk, PageLayout, Para, Run
        els = [Para(runs=[Run(text="x", font="Helvetica", size=10.0,
                              color="#000000")],
                    leading=12.0, src_lines=4, space_before=gap)
               for _ in range(6)]
        return PageLayout(number=1, chunks=[Chunk(elements=els)]), els

    def test_a_push_records_its_points(self):
        from exactdoc.layout import DocLayout
        pg, els = self._page()
        self.assertEqual(pg.loop_push_pt, 0.0)
        lay = DocLayout(pages=[pg])
        R._apply(lay, {"spill": [0], "offset": [-6.0], "need": [None], "room": [40.0]})
        self.assertAlmostEqual(els[0].space_before, 16.0)
        self.assertAlmostEqual(pg.loop_push_pt, 6.0)
        R._apply(lay, {"spill": [0], "offset": [-2.0], "need": [None], "room": [30.0]})
        self.assertAlmostEqual(pg.loop_push_pt, 8.0)

    def test_a_pull_or_a_spill_does_not(self):
        from exactdoc.layout import DocLayout
        pulled, _ = self._page()
        R._apply(DocLayout(pages=[pulled]), {"spill": [0], "offset": [5.0],
                                             "need": [None], "room": [40.0]})
        self.assertEqual(pulled.loop_push_pt, 0.0)
        spilled, _ = self._page()
        R._apply(DocLayout(pages=[spilled]), {"spill": [1], "offset": [0.0],
                                              "need": [None], "room": [None]})
        self.assertEqual(spilled.loop_push_pt, 0.0)

    def _model(self, base_over):
        """A spill prediction that reads the first gap: `base_over` points over
        at the unpushed 10pt, plus whatever the first gap gained."""
        def spill(pg, *_a, **_k):
            first = pg.chunks[0].elements[0]
            over = base_over + (first.space_before - 10.0)
            return (over, 2 if over > 0 else 0)
        return spill

    def test_a_push_is_not_taken_back(self):
        # y44 p1: unpushed the page fits by the model, so nothing is planned;
        # a 30pt push must not read as 30pt over
        from unittest import mock
        from exactdoc import docxout
        from exactdoc.layout import DocLayout
        pg, els = self._page()
        lay = DocLayout(pages=[pg])
        els[0].space_before, pg.loop_push_pt = 40.0, 30.0
        with mock.patch.object(docxout, "_page_spill", side_effect=self._model(-1.6)):
            self.assertEqual(docxout._absorb_page_spill(pg, 468.0, lay), {})
        self.assertEqual(els[0].space_before, 40.0)          # restored

    def test_the_cuts_the_render_was_measured_with_stay(self):
        # y18 p15: unpushed the model plans cuts the round-0 render fitted
        # with; after a push the same cuts are planned, the push on top
        from unittest import mock
        from exactdoc import docxout
        from exactdoc.layout import DocLayout
        pg, els = self._page()
        lay = DocLayout(pages=[pg])
        with mock.patch.object(docxout, "_page_spill", side_effect=self._model(5.0)):
            before = docxout._absorb_page_spill(pg, 468.0, lay)
            self.assertTrue(before)
            els[0].space_before, pg.loop_push_pt = 14.7, 4.7
            after = docxout._absorb_page_spill(pg, 468.0, lay)
        self.assertEqual(set(after), set(before))
        for el in els[1:]:
            if id(el) in before:
                self.assertEqual(after[id(el)], before[id(el)])
        if id(els[0]) in before:
            self.assertAlmostEqual(after[id(els[0])], before[id(els[0])] + 4.7, places=1)
        self.assertEqual(els[0].space_before, 14.7)


if __name__ == "__main__":
    unittest.main()
