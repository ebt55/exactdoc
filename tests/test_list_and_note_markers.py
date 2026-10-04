"""List and note markers the browser and word-processor dialects hide.

Four small defects, each measured on an expansion fixture:

* Chromium draws `list-style: circle` as a STROKED bezier circle; the drawn-
  marker rewrite only took filled shapes, so every second-level item of
  x09_chrome_lists_nested lost its marker.
* A nested numbered item whose number is in the same span as its text
  ("1. Mark the bay positions") was welded to the line above it, three levels
  into one paragraph that re-wrapped as prose (-15pt per weld on x09); the
  typed-marker sequence evidence now splits them.
* A footnote's own number (x05_lo_quotes_notes: 4.6pt, raised 3.1pt against
  its 8.5pt note) became a 5pt paragraph after its note.
* An undecodable glyph INSIDE a line (the space between "2." and "Method") was
  promoted to a bullet once text started within 46pt to its right.
"""
import unittest

from exactdoc.dialect import _markers_to_text, _undecoded_markers_to_text
from exactdoc.infer import infer, _inline_list_starts, _split_lines_to_paras
from exactdoc.layout import Para
from exactdoc.model import (DocIR, DrawCmd, Line, PageIR, Span, TextBlock,
                            UndecodedGlyph)


def _line(text, x0, x1, base, size=11.0):
    sp = Span(text=text, font="LiberationSerif", size=size, color="#111111",
              bold=False, italic=False, mono=False, serif=True,
              superscript=False, bbox=(x0, base - 0.85 * size, x1, base + 0.2 * size),
              origin=(x0, base))
    return Line(spans=[sp], bbox=sp.bbox)


def _circle(x0, cy, d=4.9, filled=False):
    return DrawCmd(kind="fill" if filled else "stroke", shape="complex",
                   bbox=(x0, cy - d / 2, x0 + d, cy + d / 2),
                   fill="#111111" if filled else None,
                   stroke=None if filled else "#111111", width=0.75,
                   opacity=1.0, n_items=49)


class HollowMarkers(unittest.TestCase):
    def test_outlined_circles_before_items_become_white_bullets(self):
        lines = [_line("Confirm the hoarding line", 101.7, 300.0, 228.8),
                 _line("Photograph the boundary", 101.7, 290.0, 247.5)]
        page = PageIR(1, 612.0, 792.0,
                      blocks=[TextBlock(lines=[l], bbox=l.bbox) for l in lines],
                      drawings=[_circle(89.8, 225.7), _circle(89.8, 244.5)])
        self.assertEqual(_markers_to_text(page), 2)
        marks = [b.text for b in page.blocks if b.text in ("◦", "•")]
        self.assertEqual(marks, ["◦", "◦"])

    def test_an_outlined_square_is_a_checkbox_not_a_bullet(self):
        lines = [_line("I agree", 101.7, 200.0, 228.8),
                 _line("I do not", 101.7, 200.0, 247.5)]
        boxes = [DrawCmd(kind="stroke", shape="rect",
                         bbox=(89.8, cy - 2.5, 94.8, cy + 2.5), fill=None,
                         stroke="#000000", width=0.75, opacity=1.0, n_items=5)
                 for cy in (225.7, 244.5)]
        page = PageIR(1, 612.0, 792.0,
                      blocks=[TextBlock(lines=[l], bbox=l.bbox) for l in lines],
                      drawings=boxes)
        self.assertEqual(_markers_to_text(page), 0)


class NestedNumberedItems(unittest.TestCase):
    """x09's three numbered levels, the number in each item's own span.

    The typed-marker evidence (`_inline_list_starts`: a neighbour in sequence
    at the same x) is what splits them; this pins x09's shape against it.
    """

    def test_each_level_is_its_own_paragraph(self):
        lines = [_line("1. Establish the temporary layover", 67.7, 228.2, 458.2),
                 _line("1. Mark the bay positions", 89.7, 208.8, 474.0),
                 _line("1. Set the stop lines two metres back", 111.7, 346.9, 489.8),
                 _line("2. Check the swept path with a vehicle", 111.7, 343.9, 508.5),
                 _line("2. Install the driver information board", 89.7, 265.5, 531.8),
                 _line("2. Revise the running board", 67.7, 197.7, 555.8)]
        starts = _inline_list_starts([lines])
        self.assertEqual(len(_split_lines_to_paras(lines, starts)), 6)

    def test_prose_wrapping_onto_a_number_is_not_split(self):
        # same left edge: a wrapped line that happens to start "1."
        lines = [_line("the figures in table", 58.0, 540.0, 100.0),
                 _line("1. are reported as drawn from the counters", 58.0, 400.0,
                       115.8)]
        starts = _inline_list_starts([lines])
        self.assertEqual(len(_split_lines_to_paras(lines, starts)), 1)


class FootnoteNumbers(unittest.TestCase):
    def test_a_raised_note_number_joins_its_note_as_a_superscript(self):
        body = [_line("The full consultation text is published at the site and "
                      "responses may be sent to the office", 64.9, 547.0,
                      120.0 + 14.5 * i) for i in range(3)]
        note = _line(" Costed at the framework rate current at the date of this "
                     "response", 67.2, 416.4, 506.9, size=8.5)
        num = _line("1", 64.9, 67.2, 503.8, size=4.6)
        blocks = [TextBlock(lines=[l], bbox=l.bbox) for l in body + [note, num]]
        lay = infer(DocIR(path="t.pdf", pages=[PageIR(1, 612.0, 792.0,
                                                      blocks=blocks)]))
        paras = [e for pg in lay.pages for ch in pg.chunks for e in ch.elements
                 if isinstance(e, Para)]
        notes = [p for p in paras if "Costed" in p.text]
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].text.startswith("1"))
        self.assertTrue(notes[0].runs[0].superscript)
        self.assertFalse(any(p.text.strip() == "1" for p in paras))
        # anchored on the NOTE's baseline, not the raised number's
        self.assertAlmostEqual(notes[0]._b1, 506.9, delta=0.01)


class UndecodedInsideALine(unittest.TestCase):
    def test_a_space_inside_a_line_is_not_a_bullet(self):
        # "2. Method" spans the mark at x=66.8; dots begin 43pt to its right
        lines = [_line("2. Method", 57.8, 105.2, 233.2),
                 _line("." * 40, 109.5, 545.2, 233.2),
                 _line("3. Results", 57.8, 103.3, 291.8),
                 _line("." * 40, 107.2, 545.2, 291.8)]
        page = PageIR(1, 612.0, 792.0,
                      blocks=[TextBlock(lines=[l], bbox=l.bbox) for l in lines])
        page.undecoded = [UndecodedGlyph(origin=(66.8, 233.2), size=14.7,
                                         color="#111111"),
                          UndecodedGlyph(origin=(66.8, 291.8), size=14.7,
                                         color="#111111")]
        self.assertEqual(_undecoded_markers_to_text(page), 0)


if __name__ == "__main__":
    unittest.main()
