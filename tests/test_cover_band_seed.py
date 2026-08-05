"""The cover-band seed separates two measured populations, and both are pinned.

`infer.detect_hf.top_bands` decides whether a page-leading full-width fill is a COVER
BAND. That one predicate gates both of `docxout.has_cover`'s treatments -- the
zero side margin that makes a band bleed, and the Google Docs vertical
compensation -- so a band that fails it is mispositioned twice.

It used to require the fill to start at y0 <= 2.5, which is "flush, allowing for
rounding" rather than a measured bound. c1_whitepaper's band starts at 7.16 and
was not recognised; Google's own export from live pass 6 put it 54.52pt right of
source, overflowing a 612pt page to 660.60, and 17.38pt low against the +14.55
both recognised bands measured in the same run.

The threshold is now `COVER_BAND_SEED_PT`. These tests pin the populations it
separates rather than the number itself, so a future change has to move a
document, not just a constant:

    must seed      01 and 04 at y0 0.00, c1 at 7.16
    must not seed  a fill at 130.0, the height of 04's own accent stripe and the
                   nearest full-width fill in either corpus that is not a band

    python -m unittest tests.test_cover_band_seed
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from exactdoc import infer as I                               # noqa: E402
from exactdoc.backend import get_backend                      # noqa: E402
from exactdoc.dialect import normalize                        # noqa: E402
from exactdoc.input import parse as parse_input               # noqa: E402
from exactdoc.model import DocIR, DrawCmd, PageIR             # noqa: E402

FIX = os.path.join(ROOT, "testkit", "fixtures")

#: Measured over all 45 committed fixtures with no y0 cap, 2026-08-06.
REAL_BANDS = {"01_whitepaper_market": 0.00,
              "04_exec_brief": 0.00,
              "c1_whitepaper": 7.16}
#: The nearest full-width page-1 fill in either corpus that is NOT a band.
NEAREST_NON_BAND_Y0 = 130.0


def _band_page(y0, height, page_w=612.0, page_h=792.0):
    """A page carrying one full-width fill at y0. Nothing else."""
    p = PageIR(number=1, width=page_w, height=page_h)
    p.drawings = [DrawCmd(kind="fill", shape="rect",
                          bbox=(0.0, y0, page_w, y0 + height),
                          fill="#123a5e", stroke=None, width=0.0,
                          opacity=1.0, n_items=1, seqno=0)]
    return p


def seeds(y0, height=112.0):
    """Does a fill at this y0 seed the cover-band group?"""
    ir = DocIR(path="synthetic", meta={})
    ir.pages = [_band_page(y0, height)]
    res = I.detect_hf(ir)
    return bool(res["band_first"])


class TheThreshold(unittest.TestCase):
    def test_it_is_a_named_constant_not_a_literal(self):
        self.assertTrue(hasattr(I, "COVER_BAND_SEED_PT"))
        self.assertIsInstance(I.COVER_BAND_SEED_PT, float)

    def test_it_sits_between_the_two_measured_populations(self):
        """The gap argument, as an assertion.

        Not "the constant is 36.0" -- that would pin the answer. This pins the
        property that makes any value defensible: above every real band, below
        the nearest fill that must not become one.
        """
        worst_real_inset = max(REAL_BANDS.values())
        self.assertGreater(
            I.COVER_BAND_SEED_PT, worst_real_inset,
            "the seed must admit c1_whitepaper's band at y0 %.2f"
            % worst_real_inset)
        self.assertLess(
            I.COVER_BAND_SEED_PT, NEAREST_NON_BAND_Y0,
            "the seed must not admit a fill at y0 %.1f, which is 04_exec_brief's "
            "accent stripe and the nearest full-width page-1 fill in either "
            "corpus that is not a band" % NEAREST_NON_BAND_Y0)

    def test_the_margin_is_real_in_both_directions(self):
        """A threshold wedged against either population is one measurement from
        being wrong. Both gaps are asserted as ratios."""
        self.assertGreaterEqual(I.COVER_BAND_SEED_PT / max(REAL_BANDS.values()),
                                3.0, "less than 3x above the worst real inset")
        self.assertGreaterEqual(NEAREST_NON_BAND_Y0 / I.COVER_BAND_SEED_PT,
                                3.0, "less than 3x below the nearest non-band")


class TheSyntheticPopulations(unittest.TestCase):
    """Driven through `detect_hf` on synthetic pages, so the boundary is exercised
    directly rather than only where a fixture happens to sit."""

    def test_a_flush_fill_seeds(self):
        self.assertTrue(seeds(0.0))

    def test_c1s_measured_inset_seeds(self):
        self.assertTrue(seeds(7.16),
                        "c1_whitepaper's band must be recognised")

    def test_the_nearest_non_band_does_not_seed(self):
        self.assertFalse(seeds(NEAREST_NON_BAND_Y0),
                         "a fill at 130.0 must not become a cover band")

    def test_the_boundary_is_where_the_constant_says(self):
        self.assertTrue(seeds(I.COVER_BAND_SEED_PT - 0.5))
        self.assertFalse(seeds(I.COVER_BAND_SEED_PT + 0.5))

    def test_a_short_fill_still_does_not_become_a_band(self):
        """Seeding is necessary, not sufficient: `b1_h > 45` still applies, so
        an accent stripe flush to the page top is not a cover band either."""
        self.assertFalse(seeds(0.0, height=8.0))


class TheCorpusIsUnmoved(unittest.TestCase):
    """The populations above are abstractions; these are the documents."""

    def _cover_band(self, name):
        lay = _layout(name)
        return getattr(lay, "cover_band", None)

    def test_the_two_already_recognised_bands_are_unchanged(self):
        for name in ("01_whitepaper_market", "04_exec_brief"):
            self.assertIsNotNone(self._cover_band(name),
                                 "%s lost its cover band" % name)

    def test_c1_is_now_recognised(self):
        self.assertIsNotNone(
            self._cover_band("c1_whitepaper"),
            "c1_whitepaper's band at y0 7.16 must now be a cover band; this is "
            "the whole point of the change")

    def test_no_other_gated_document_gained_one(self):
        """The blast radius, asserted. Measured as exactly one document."""
        gained = []
        for f in sorted(os.listdir(FIX)):
            if not f.endswith(".pdf"):
                continue
            name = f[:-4]
            if name in ("01_whitepaper_market", "04_exec_brief",
                        "c1_whitepaper"):
                continue
            if self._cover_band(name) is not None:
                gained.append(name)
        self.assertEqual(gained, [],
                         "these documents gained a cover band: %s" % gained)


_CACHE = {}


def _layout(name):
    if name not in _CACHE:
        from exactdoc.infer import infer
        _CACHE[name] = infer(normalize(parse_input(
            get_backend("pdfium"), os.path.join(FIX, name + ".pdf"))))
    return _CACHE[name]


if __name__ == "__main__":
    unittest.main()
