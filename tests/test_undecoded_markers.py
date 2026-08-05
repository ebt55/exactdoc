"""Undecodable glyphs at a list-marker slot become bullets; nothing else does.

LibreOffice writes its bullets as a symbol-font glyph PDFium cannot map to any
character. It does not arrive as U+0000 and it does not arrive as a private-use
codepoint -- the text page leaves it out altogether, so on x03_lo_lists_nested
PDFium reports 1320 characters and not one of them is a bullet, while PyMuPDF
reports U+F0B7 thirteen times. The page-object layer still shows the glyphs, as
text objects with empty text and bounds collapsed to a point.

`parse_pdfium` records those points and nothing more, because that is all it
knows. This file pins the half that matters for safety: `dialect` turns a point
into a bullet only where the geometry of a list marker is present, and the same
producer emits identically-shaped points for trailing whitespace, which must
stay dropped.

    python tests/test_undecoded_markers.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.dialect import _undecoded_markers_to_text      # noqa: E402
from exactdoc.model import (Line, PageIR, Span, TextBlock,   # noqa: E402
                            UndecodedGlyph)

X03 = os.path.join(ROOT, "testkit", "fixtures_expansion",
                   "x03_lo_lists_nested.pdf")


def _line(text, x0, y0, x1, y1, size=11.0):
    bb = (x0, y0, x1, y1)
    sp = Span(text=text, font="LiberationSerif", size=size, color="#000000",
              bold=False, italic=False, mono=False, serif=True,
              superscript=False, bbox=bb, origin=(x0, y1))
    return Line(spans=[sp], bbox=bb)


def _page(lines, marks):
    page = PageIR(number=1, width=612.0, height=792.0)
    page.blocks = [TextBlock(lines=[ln], bbox=ln.bbox) for ln in lines]
    page.undecoded = list(marks)
    return page


def _bullets(page):
    return [b for b in page.blocks if b.text.strip() == "•"]


class RecoversAMarkerSlot(unittest.TestCase):
    def test_two_marks_left_of_their_items_become_bullets(self):
        page = _page(
            [_line("Site preparation", 82.9, 191.3, 152.8, 203.5),
             _line("Utilities", 82.9, 279.3, 118.3, 291.5)],
            [UndecodedGlyph(origin=(64.9, 201.2), size=11.0, color="#000000"),
             UndecodedGlyph(origin=(64.9, 289.1), size=11.0, color="#000000")])
        self.assertEqual(_undecoded_markers_to_text(page), 2)
        self.assertEqual(len(_bullets(page)), 2)
        # Consumed: a recovered mark must not stay a candidate.
        self.assertEqual(page.undecoded, [])

    def test_recovered_bullet_sits_left_of_the_item_on_its_baseline(self):
        page = _page(
            [_line("Site preparation", 82.9, 191.3, 152.8, 203.5),
             _line("Utilities", 82.9, 279.3, 118.3, 291.5)],
            [UndecodedGlyph(origin=(64.9, 201.2), size=11.0, color="#000000"),
             UndecodedGlyph(origin=(64.9, 289.1), size=11.0, color="#000000")])
        _undecoded_markers_to_text(page)
        bb = _bullets(page)[0].bbox
        self.assertAlmostEqual(bb[0], 64.9, places=1)
        self.assertLess(bb[2], 82.9)          # ends before the item text starts
        self.assertAlmostEqual(bb[3], 201.2, places=1)   # on the item baseline


class RefusesEverythingElse(unittest.TestCase):
    def test_a_mark_past_the_end_of_a_line_is_not_a_bullet(self):
        """x03 page 1 carries one at x=147.4, just past 'binding constraint.'

        Same collapsed bounds as a bullet, same empty text, and no list
        anywhere near it. Trailing whitespace is not a marker.
        """
        page = _page(
            [_line("binding constraint.", 64.9, 150.4, 147.3, 162.6),
             _line("Bulleted, three levels", 64.9, 174.5, 179.7, 190.1)],
            [UndecodedGlyph(origin=(147.4, 160.3), size=11.0, color="#000000"),
             UndecodedGlyph(origin=(147.4, 160.3), size=11.0, color="#000000")])
        self.assertEqual(_undecoded_markers_to_text(page), 0)
        self.assertEqual(_bullets(page), [])

    def test_a_lone_mark_is_refused_even_at_a_marker_slot(self):
        """A list repeats. One mark is not corroboration, so it is dropped --
        the same bar `_markers_to_text` sets for a drawn marker."""
        page = _page(
            [_line("Site preparation", 82.9, 191.3, 152.8, 203.5)],
            [UndecodedGlyph(origin=(64.9, 201.2), size=11.0, color="#000000")])
        self.assertEqual(_undecoded_markers_to_text(page), 0)
        self.assertEqual(_bullets(page), [])

    def test_a_mark_too_far_from_its_line_is_refused(self):
        """Beyond BULLET_GAP the glyph is not labelling that text."""
        page = _page(
            [_line("Site preparation", 300.0, 191.3, 380.0, 203.5),
             _line("Utilities", 300.0, 279.3, 340.0, 291.5)],
            [UndecodedGlyph(origin=(64.9, 201.2), size=11.0, color="#000000"),
             UndecodedGlyph(origin=(64.9, 289.1), size=11.0, color="#000000")])
        self.assertEqual(_undecoded_markers_to_text(page), 0)

    def test_a_mark_on_no_line_s_baseline_is_refused(self):
        page = _page(
            [_line("Site preparation", 82.9, 191.3, 152.8, 203.5),
             _line("Utilities", 82.9, 279.3, 118.3, 291.5)],
            [UndecodedGlyph(origin=(64.9, 240.0), size=11.0, color="#000000"),
             UndecodedGlyph(origin=(64.9, 250.0), size=11.0, color="#000000")])
        self.assertEqual(_undecoded_markers_to_text(page), 0)

    def test_a_page_with_no_marks_is_untouched(self):
        page = _page([_line("Site preparation", 82.9, 191.3, 152.8, 203.5)], [])
        self.assertEqual(_undecoded_markers_to_text(page), 0)


class RefusesWhatTheCorpusCaught(unittest.TestCase):
    """The three guards the expansion corpus forced, each with its own case.

    The first form of this rule tested position only. It promoted 345 marks on
    y01 and 623 on y03 against 12 on x03, and sampling showed essentially none
    were markers.
    """

    def test_a_mark_with_text_to_its_left_is_inside_a_line(self):
        """y03's S-box tables: '63 7c 77 7b' with a mark in every column gap.

        The mark finds the next cell to its right and looks like a marker until
        you notice the previous cell ends on the same baseline just to its left.
        """
        page = _page(
            [_line("Character 0", 120.0, 430.0, 195.3, 442.0),
             _line("1", 229.2, 430.0, 236.4, 442.0),
             _line("Character 8", 120.0, 462.0, 195.3, 474.0),
             _line("9", 229.1, 462.0, 236.3, 474.0)],
            [UndecodedGlyph(origin=(195.3, 439.9), size=11.0, color="#000000"),
             UndecodedGlyph(origin=(195.3, 471.1), size=11.0, color="#000000")])
        self.assertEqual(_undecoded_markers_to_text(page), 0)
        self.assertEqual(_bullets(page), [])

    def test_a_one_point_glyph_is_a_positioning_artifact_not_ink(self):
        """Every one of y01's 345 and y03's 623 reported 1.0pt against ~10pt
        body text -- PDF's default size on an object whose font size was never
        set. Nobody can see a 1pt bullet."""
        page = _page(
            [_line("Authenticator Assurance Level 1", 127.0, 176.0, 300.0, 188.0),
             _line("Authenticator Assurance Level 2", 127.0, 295.0, 300.0, 307.0)],
            [UndecodedGlyph(origin=(115.9, 182.2), size=1.0, color="#000000"),
             UndecodedGlyph(origin=(115.9, 301.0), size=1.0, color="#000000")])
        self.assertEqual(_undecoded_markers_to_text(page), 0)

    def test_a_mark_at_the_item_s_own_scale_still_passes(self):
        """The size guard must not be a blanket refusal: same geometry, real
        size, and it is a marker again."""
        page = _page(
            [_line("Authenticator Assurance Level 1", 127.0, 176.0, 300.0, 188.0),
             _line("Authenticator Assurance Level 2", 127.0, 295.0, 300.0, 307.0)],
            [UndecodedGlyph(origin=(115.9, 182.2), size=11.0, color="#000000"),
             UndecodedGlyph(origin=(115.9, 301.0), size=11.0, color="#000000")])
        self.assertEqual(_undecoded_markers_to_text(page), 2)

    def test_a_bullet_in_front_of_a_bullet_is_a_duplicate(self):
        """y01's metadata rows put a mark before a line that already starts
        with a real bullet. Two markers on one item is not a list."""
        page = _page(
            [_line("• Series/Number", 179.5, 240.0, 300.0, 252.0),
             _line("• Publication Date", 179.5, 268.0, 300.0, 280.0)],
            [UndecodedGlyph(origin=(142.3, 245.7), size=11.0, color="#000000"),
             UndecodedGlyph(origin=(159.8, 273.5), size=11.0, color="#000000")])
        self.assertEqual(_undecoded_markers_to_text(page), 0)

    def test_an_unmeasurable_host_is_not_a_licence_to_promote(self):
        page = PageIR(number=1, width=612.0, height=792.0)
        blank = _line("", 82.9, 191.3, 152.8, 203.5)
        blank2 = _line("", 82.9, 279.3, 118.3, 291.5)
        page.blocks = [TextBlock(lines=[blank], bbox=blank.bbox),
                       TextBlock(lines=[blank2], bbox=blank2.bbox)]
        page.undecoded = [
            UndecodedGlyph(origin=(64.9, 201.2), size=11.0, color="#000000"),
            UndecodedGlyph(origin=(64.9, 289.1), size=11.0, color="#000000")]
        self.assertEqual(_undecoded_markers_to_text(page), 0)


class OnTheRealDocument(unittest.TestCase):
    """The end-to-end shape, against the reference the other arm reports."""

    def setUp(self):
        try:
            import pypdfium2  # noqa: F401
        except ImportError:
            self.skipTest("pypdfium2 not installed")
        if not os.path.exists(X03):
            self.skipTest("x03 fixture not present")

    def test_page_one_recovers_the_twelve_bullets_pymupdf_reports(self):
        from exactdoc.dialect import normalize
        from exactdoc.parse_pdfium import parse_pdf

        ir = normalize(parse_pdf(X03))
        got = len(_bullets(ir.pages[0]))
        self.assertEqual(got, 12, "page 1 carries 12 bullets, recovered %d" % got)

    def test_the_trailing_whitespace_mark_is_left_refused(self):
        from exactdoc.dialect import normalize
        from exactdoc.parse_pdfium import parse_pdf

        ir = normalize(parse_pdf(X03))
        left = [m.origin for m in ir.pages[0].undecoded]
        self.assertEqual([(round(x, 1), round(y, 1)) for x, y in left],
                         [(147.4, 160.2)])

    def test_pymupdf_sees_no_undecoded_glyphs_at_all(self):
        """The side channel is PDFium-only: the reference arm cannot move."""
        try:
            from exactdoc.parse import parse_pdf as parse_mupdf
        except ImportError:
            self.skipTest("pymupdf not installed")
        from exactdoc.dialect import normalize

        ir = normalize(parse_mupdf(X03))
        self.assertEqual([len(p.undecoded) for p in ir.pages], [0, 0])
        self.assertEqual(ir.meta["_normalized"]["undecoded_markers"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
