"""A stray shape grown into a page-sized picture (WP68).

`infer.build_figure` grows a stray drawing's picture over the lines and images
it touches. Lines grew it under a budget; images grew it without one. One
drawn logo touching a page's full-page background picture became a picture of
the whole sheet, every line on the page rasterised into it, standing in the
flow (holdout-3's NSF transmittal: its "At a Glance" page). The same growth
took a report's pages one by one from a thumb tab at the paper's edge (Peace
Corps OIG: 50 pages became 109), and a cover band's stripe, pictured on its
own, stood 372pt tall in the flow before the cover (HUD OIG: page 1 blank).

* `image_budget`: an image grows the picture under the budget lines have; a
  photograph with a headline on it that a small mark stands on is the
  exception (`_cover_art`, y06's cover), and keeps its old reading.
* `margin_strip`: a text-free full-height strip standing half in a side
  margin is furniture, as a shape wholly in the margin already is.
* `box_bar`: a tall narrow bar inside a built box that would take no text is
  the box's decoration.
* `image_shadow`: a one-colour raster under a photograph it holds is the
  photograph's drop shadow (freed from the pictures above, each stood in the
  flow as a grey box).

Every reading is the standard profile's (`_wp68`, keyed on the gdocs
profile's `tab_layouts=False`), each with its switch in `infer.WP68_RULES`.

    python -m unittest tests.test_wp68_figures
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from exactdoc import infer as I                                 # noqa: E402
from exactdoc.layout import FigureEl, ImageEl, Para, TableEl    # noqa: E402

import wp68_fixtures as F                                       # noqa: E402

W, H = F.W, F.H


def _infer(pdf, tab_layouts=True):
    from exactdoc.backend import get_backend
    from exactdoc.dialect import normalize
    from exactdoc.input import parse as parse_input
    return I.infer(normalize(parse_input(get_backend("pdfium"), pdf)),
                   anchored=True, anchor_pictures=True, tab_layouts=tab_layouts)


class _Rules:
    """`with _Rules(False):` -- every WP68 switch (or `names`) set, for a test."""

    def __init__(self, on, names=None):
        self.on, self.names = on, names or list(I.WP68_RULES)

    def __enter__(self):
        self.saved = dict(I.WP68_RULES)
        for n in self.names:
            I.WP68_RULES[n] = self.on

    def __exit__(self, *exc):
        I.WP68_RULES.clear()
        I.WP68_RULES.update(self.saved)


def _els(pg):
    return [el for ch in pg.chunks for el in ch.elements]


def _figs(pg):
    return [e for e in _els(pg) if isinstance(e, FigureEl)]


def _text(pg):
    return " ".join(e.text for e in _els(pg) if isinstance(e, Para))


def _sig(lay):
    """What each page reads as: element kinds, boxes, text; floats too."""
    out = []
    for pg in lay.pages:
        row = []
        for e in _els(pg) + [f.el for f in pg.floats]:
            bb = getattr(e, "clip", None) or getattr(e, "bbox", None) or \
                getattr(e, "_bbox", None) or ()
            row.append((type(e).__name__, tuple(round(v) for v in bb),
                        (getattr(e, "text", "") or "")[:40]))
        out.append(row)
    return out


@unittest.skipUnless(F.available(), "needs reportlab and Pillow")
class _Fixture(unittest.TestCase):
    builder = None

    @classmethod
    def setUpClass(cls):
        if cls.builder is None:
            raise unittest.SkipTest("base class")
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = getattr(F, cls.builder)(os.path.join(cls._dir.name, cls.builder + ".pdf"))
        cls.lay = _infer(cls.pdf)
        with _Rules(False):
            cls.off = _infer(cls.pdf)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()


class APageBackground(_Fixture):
    builder = "page_background"

    def test_the_page_stays_text(self):
        pg = self.lay.pages[1]
        self.assertIn("At a Glance", _text(pg))
        self.assertGreaterEqual(sum(isinstance(e, Para) for e in _els(pg)), 2)
        for f in _figs(pg):
            self.assertLess((f.clip[2] - f.clip[0]) * (f.clip[3] - f.clip[1]),
                            I.MAX_FIG_PAGE_FRAC * W * H, "the logo stays a logo")

    def test_the_background_is_the_writers_full_page_picture(self):
        ims = [e for e in _els(self.lay.pages[1]) if isinstance(e, ImageEl)]
        self.assertTrue(any(I._fills_page(e._bbox, W, H) for e in ims))

    def test_without_the_rule_the_page_is_one_picture(self):
        pg = self.off.pages[1]
        self.assertNotIn("At a Glance", _text(pg))
        self.assertTrue(any(I._fills_page(f.clip, W, H) for f in _figs(pg)))

    def test_the_gdocs_profile_keeps_its_reading(self):
        self.assertEqual(_sig(_infer(self.pdf, tab_layouts=False)),
                         _sig(_infer_off(self.pdf, tab_layouts=False)))


def _infer_off(pdf, tab_layouts=True):
    with _Rules(False):
        return _infer(pdf, tab_layouts=tab_layouts)


class ACoverBandStripe(_Fixture):
    builder = "cover_band_stripe"

    def test_no_stripe_stands_in_the_flow(self):
        for f in _figs(self.lay.pages[0]):
            self.assertLess(f.clip[3] - f.clip[1], I.BOX_BAR_MIN_H_FRAC * H)
        self.assertTrue([e for e in _els(self.lay.pages[0])
                         if isinstance(e, TableEl) and e.role == "box"])

    def test_without_the_rule_it_does(self):
        self.assertTrue([f for f in _figs(self.off.pages[0])
                         if f.clip[3] - f.clip[1] > 0.4 * H])


class AThumbTab(_Fixture):
    builder = "thumb_tab"

    def test_every_page_stays_text(self):
        for pg in self.lay.pages:
            self.assertFalse([f for f in _figs(pg) if f.clip[3] - f.clip[1] > 0.5 * H])
            self.assertGreater(len(_text(pg)), 1000)

    def test_without_the_rule_each_page_is_a_picture(self):
        for pg in self.off.pages:
            self.assertTrue([f for f in _figs(pg) if f.clip[3] - f.clip[1] > 0.9 * H])

    def test_a_tab_is_judged_by_its_own_geometry(self):
        from exactdoc.model import DrawCmd, PageIR
        page = PageIR(number=1, width=W, height=H)

        def tab(x0, x1, y0=0.0, y1=H, fill="#dce3e6"):
            return DrawCmd(kind="fill", shape="rect", bbox=(x0, y0, x1, y1),
                           fill=fill, stroke=None, width=0.0, opacity=1.0, n_items=1)
        self.assertTrue(I._margin_strip([tab(534, 590)], page, [], 72.0, 72.0))
        self.assertTrue(I._margin_strip([tab(20, 77)], page, [], 72.0, 72.0))
        # half of it in the column: a column's panel, not a tab
        self.assertFalse(I._margin_strip([tab(500, 556)], page, [], 72.0, 72.0))
        # half the page tall at most: a sidebar rule, not the paper's height
        self.assertFalse(I._margin_strip([tab(534, 590, 200, 500)], page, [], 72.0, 72.0))
        # a margin panel wider than a tab
        self.assertFalse(I._margin_strip([tab(0, 140)], page, [], 72.0, 72.0))
        self.assertFalse(I._margin_strip([tab(534, 590, fill=None)], page, [], 72.0, 72.0))


class APhotoShadow(_Fixture):
    builder = "photo_shadow"

    def test_one_picture_not_a_grey_box_and_a_photograph(self):
        ims = [e for e in _els(self.lay.pages[0]) if isinstance(e, ImageEl)]
        self.assertEqual(len(ims), 1)
        self.assertEqual([round(v) for v in ims[0]._bbox], [98, 239, 549, 577])

    def test_without_the_rule_the_shadow_stands_too(self):
        ims = [e for e in _els(self.off.pages[0]) if isinstance(e, ImageEl)]
        self.assertEqual(len(ims), 2)


class _Control(_Fixture):
    """A look-alike the rules must leave exactly as it was."""
    builder = None

    def test_the_rules_leave_it_as_it_was(self):
        self.assertEqual(_sig(self.lay), _sig(self.off))


class ACoverPhotograph(_Control):
    """y06's cover: the mark's picture takes the photograph and its headline."""
    builder = "cover_photo"

    def test_the_cover_is_one_picture_with_its_headline(self):
        figs = _figs(self.lay.pages[0])
        self.assertTrue(figs)
        self.assertGreater(figs[0].clip[3] - figs[0].clip[1], 500)
        self.assertNotIn("Instructions for the Year", _text(self.lay.pages[0]))


class ATextStrip(_Control):
    builder = "text_strip"


class AChartInACard(_Control):
    builder = "card_chart"


class TwoPhotographs(_Control):
    builder = "two_photos"


class APhotographWithoutShadow(_Control):
    builder = "photo_shadow"

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = F.photo_shadow(os.path.join(cls._dir.name, "p.pdf"), shadow=False)
        cls.lay = _infer(cls.pdf)
        with _Rules(False):
            cls.off = _infer(cls.pdf)


class TheSwitches(unittest.TestCase):
    def test_each_reading_has_its_switch(self):
        for rule in ("image_budget", "margin_strip", "box_bar", "image_shadow"):
            self.assertIn(rule, I.WP68_RULES)
            self.assertTrue(I.WP68_RULES[rule])

    def test_off_under_the_gdocs_profile(self):
        tok = I._TAB_LAYOUTS.set(False)
        try:
            self.assertFalse(any(I._wp68(r) for r in I.WP68_RULES))
        finally:
            I._TAB_LAYOUTS.reset(tok)


if __name__ == "__main__":
    unittest.main()
