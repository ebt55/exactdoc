"""A one-row table drawn as fills is a table, not a picture (WP27, y33).

y33 (Kofax Power PDF, NZ MBIE discussion paper) sets each consultation question
as a teal badge holding its number, flush against a tinted panel holding the
question. Two questions stacked on one band were already read as a fill-tiled
table; a question standing alone was classified a figure, and the figure,
grown from the panel's 454pt-wide seed, rasterised the body lines above it --
on 20 of 60 pages, footnote references with them, so those pages' notes could
not bind and spilled as typed text (LibreOffice raw 62 pages for 60, word
recall 0.49).

    python tests/test_question_panels.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.infer import infer                                  # noqa: E402
from exactdoc.layout import FigureEl, Para, TableEl               # noqa: E402
from exactdoc.model import DocIR, DrawCmd, Line, PageIR, Span, TextBlock  # noqa: E402

WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo "
         "lima mike november oscar papa quebec romeo sierra tango uniform "
         "victor whiskey xray yankee zulu").split()
TEAL, TINT = "#006272", "#b3d0d5"


def _span(text, x0, base, size=11.0, x1=None, sup=False):
    x1 = x1 if x1 is not None else x0 + 0.48 * size * len(text)
    top = base - (0.95 * size if not sup else 0.95 * size + 3.0)
    return Span(text, "Calibri", size, "#000000", False, False, False, False, sup,
                (x0, top, x1, base + 0.27 * size), (x0, base))


def _line(*spans):
    bb = (min(s.bbox[0] for s in spans), min(s.bbox[1] for s in spans),
          max(s.bbox[2] for s in spans), max(s.bbox[3] for s in spans))
    return Line(list(spans), bb)


def _words(seed, n=14):
    return " ".join(WORDS[(seed * 5 + k) % len(WORDS)] for k in range(n))


def _fill(x0, y0, x1, y1, color):
    return DrawCmd("fill", "rect", (x0, y0, x1, y1), color, None, 0.1, 1.0, 5)


def _block(lines):
    bb = (min(l.bbox[0] for l in lines), min(l.bbox[1] for l in lines),
          max(l.bbox[2] for l in lines), max(l.bbox[3] for l in lines))
    return TextBlock(list(lines), bb)


def _question_page(gutter=0.0, badge_text="8", notes=True, after=True):
    """y33 p22 in miniature: body paragraphs, the last carrying reference
    "18"; a badge + panel question under it; a note zone at the foot."""
    body = [_line(_span(_words(i), 70.9, 100.0 + 15.5 * i, x1=524.0))
            for i in range(24)]
    ref = _line(_span("2017.", 70.9, 485.0, x1=96.1),
                _span("18", 96.1, 482.0, size=6.96, x1=103.0, sup=True))
    px0 = 97.4 + gutter
    draws = [_fill(70.9, 500.6, 97.4, 526.1, TEAL),          # the badge
             _fill(76.3, 506.6, 92.0, 520.1, TEAL),          # its inset
             _fill(px0, 500.6, 524.4, 526.1, TINT),          # the panel
             _fill(px0 + 5.4, 500.6, 519.0, 526.1, TINT)]    # its inset
    blocks = [_block(body), _block([ref])]
    if badge_text:
        blocks.append(_block([_line(_span(badge_text, 81.0, 517.0, x1=87.0))]))
    blocks.append(_block([_line(_span("Do you have any comments on the customer data?",
                                      px0 + 5.4, 517.0, x1=420.0))]))
    if after:
        blocks.append(_block([_line(_span(_words(30 + i), 70.9, 560.0 + 15.5 * i,
                                          x1=524.0)) for i in range(5)]))
    else:
        # the badge's white hairline under the table, as y33 p32 draws it
        draws.append(DrawCmd("fill", "hline", (70.2, 527.0, 97.4, 527.5), "#ffffff",
                             None, 0.1, 1.0, 5))
    if notes:
        draws.append(_fill(70.9, 708.2, 214.9, 709.0, "#000000"))   # separator
        blocks.append(_block([
            _line(_span("18", 70.9, 731.0, size=6.48, x1=77.4, sup=True),
                  _span(" https://example.org/historic-records", 77.4, 735.0,
                        size=9.96, x1=300.0))]))
    return PageIR(number=1, width=595.2, height=842.0, blocks=blocks,
                  drawings=draws)


def _elements(lay):
    return [e for ch in lay.pages[0].chunks for e in ch.elements]


class LoneQuestionPanel(unittest.TestCase):

    def test_badge_and_panel_are_one_row_table_and_the_prose_stays_text(self):
        lay = infer(DocIR(path="q.pdf", pages=[_question_page()]))
        els = _elements(lay)
        self.assertFalse([e for e in els if isinstance(e, FigureEl)])
        tabs = [e for e in els if isinstance(e, TableEl)]
        self.assertEqual(len(tabs), 1)
        self.assertEqual(len(tabs[0].rows), 1)
        cells = [c for c in tabs[0].rows[0] if c is not None]
        self.assertEqual(len(cells), 2)
        self.assertEqual(cells[0].shading, TEAL)
        text = " ".join("".join(r.text for r in e.runs) for e in els
                        if isinstance(e, Para))
        self.assertIn("2017.", text)          # the line above the panel is live
        self.assertIn(_words(23), text)

    def test_its_reference_binds_the_note(self):
        lay = infer(DocIR(path="q.pdf", pages=[_question_page()]))
        self.assertEqual([f.mark for f in lay.footnotes], ["18"])

    def test_the_separator_is_the_rule_nearest_the_notes(self):
        # y33 p32/p40: a table's text is not flow text, so a short hairline
        # under the table qualified as the separator too; taken first, it
        # opened the zone over the table and the notes stayed typed.
        lay = infer(DocIR(path="q.pdf", pages=[_question_page(after=False)]))
        self.assertEqual([f.mark for f in lay.footnotes], ["18"])
        self.assertAlmostEqual(lay.pages[0].note_area.top, 708.2, places=1)

    def test_cards_with_a_gutter_are_not_this_rule(self):
        # A row of cards keeps its gutters (c1: 9.3pt): no tiled band.
        from exactdoc.infer import _clusters, _tile_bands
        page = _question_page(gutter=9.3, notes=False)
        draws = list(enumerate(page.drawings))
        self.assertEqual(_tile_bands(_clusters(draws), page.blocks, set()), [])

    def test_an_empty_tile_is_decoration(self):
        from exactdoc.infer import _clusters, _tile_bands
        page = _question_page(badge_text=None, notes=False)
        draws = list(enumerate(page.drawings))
        self.assertEqual(_tile_bands(_clusters(draws), page.blocks, set()), [])

    def test_the_tiles_alone_make_the_band(self):
        from exactdoc.infer import _clusters, _tile_bands
        page = _question_page(notes=False)
        draws = list(enumerate(page.drawings))
        self.assertEqual(len(_tile_bands(_clusters(draws), page.blocks, set())), 1)


if __name__ == "__main__":
    unittest.main()
