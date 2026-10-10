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
    """A page the loop moved down within its measured room is not re-planned
    by the writer's open-loop spill prediction (y44_cv_rendercv_typst p1: the
    prediction planned 34.2pt of cuts against a 30.6pt push the render had
    room for, and the page came out 34pt high)."""

    def _page(self, gap=10.0):
        from exactdoc.layout import Chunk, PageLayout, Para, Run
        els = [Para(runs=[Run(text="x", font="Helvetica", size=10.0,
                              color="#000000")],
                    leading=12.0, src_lines=4, space_before=gap)
               for _ in range(6)]
        return PageLayout(number=1, chunks=[Chunk(elements=els)]), els

    def test_a_push_marks_the_page(self):
        from exactdoc.layout import DocLayout
        pg, els = self._page()
        self.assertFalse(pg.loop_pushed)
        R._apply(DocLayout(pages=[pg]), {"spill": [0], "offset": [-6.0],
                                         "need": [None], "room": [40.0]})
        self.assertAlmostEqual(els[0].space_before, 16.0)
        self.assertTrue(pg.loop_pushed)

    def test_a_pull_or_a_spill_does_not(self):
        from exactdoc.layout import DocLayout
        pulled, _ = self._page()
        R._apply(DocLayout(pages=[pulled]), {"spill": [0], "offset": [5.0],
                                             "need": [None], "room": [40.0]})
        self.assertFalse(pulled.loop_pushed)
        spilled, _ = self._page()
        R._apply(DocLayout(pages=[spilled]), {"spill": [1], "offset": [0.0],
                                              "need": [None], "room": [None]})
        self.assertFalse(spilled.loop_pushed)

    def test_the_writer_leaves_a_pushed_page_alone(self):
        from unittest import mock
        from exactdoc import docxout
        from exactdoc.layout import DocLayout
        pg, _ = self._page()
        lay = DocLayout(pages=[pg])
        # whatever the prediction says: two lines stranded, 20pt over
        with mock.patch.object(docxout, "_page_spill", return_value=(20.0, 2)):
            self.assertTrue(docxout._absorb_page_spill(pg, 468.0, lay))
            pg.loop_pushed = True
            self.assertEqual(docxout._absorb_page_spill(pg, 468.0, lay), {})


if __name__ == "__main__":
    unittest.main()
