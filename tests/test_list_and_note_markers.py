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

from exactdoc.dialect import (_corroborated_markers, _markers_to_text,
                              _undecoded_markers_to_text)
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

    def test_scatter_plot_circles_are_not_bullets(self):
        # y38's figure: open circles strewn around short tick labels, several
        # in front of one label, none in a column
        labels = [_line("0.2", 360.0, 372.0, 345.0), _line("t5", 266.0, 274.0, 262.0)]
        circles = [_circle(347.6, 343.0), _circle(352.0, 341.0),
                   _circle(255.0, 260.0), _circle(258.0, 257.0)]
        page = PageIR(1, 612.0, 792.0,
                      blocks=[TextBlock(lines=[l], bbox=l.bbox) for l in labels],
                      drawings=circles)
        self.assertEqual(_markers_to_text(page), 0)

    def test_a_lone_mark_needs_a_list_elsewhere_not_just_two_marks(self):
        # IEEEtran's end-of-proof square lands before the other column's
        # text, twice on one page, never in a column: no corroboration
        def square(x, cy):
            return DrawCmd(kind="fill", shape="rect",
                           bbox=(x, cy - 2.9, x + 5.8, cy + 2.9), fill="#000000",
                           stroke=None, width=0.0, opacity=1.0, n_items=5)
        p1_lines = [_line("proved with the same strategy as above.", 306.0, 540.0, 636.0),
                    _line("which completes the argument for the bound.", 306.0, 540.0, 400.0)]
        p1 = PageIR(1, 612.0, 792.0,
                    blocks=[TextBlock(lines=[l], bbox=l.bbox) for l in p1_lines],
                    drawings=[square(293.0, 633.0), square(280.0, 397.0)])
        self.assertEqual(_corroborated_markers(DocIR(path="t.pdf", pages=[p1])), set())

    def test_a_square_flush_with_the_column_end_closes_a_proof(self):
        # y41 p5: three end-of-proof squares at x=293-298.8, flush with the
        # left column's justified lines; the right column starts at 306
        def square(cy):
            return DrawCmd(kind="fill", shape="rect",
                           bbox=(293.0, cy - 2.9, 298.8, cy + 2.9), fill="#000000",
                           stroke=None, width=0.0, opacity=1.0, n_items=5)
        left = [_line("the left column is set justified to its edge", 54.0, 298.8,
                      100.0 + 11.0 * i) for i in range(6)]
        right = [_line("In this section we present a numerical evaluation", 306.0,
                       558.0, cy + 2.5) for cy in (216.0, 370.0, 648.0)]
        page = PageIR(1, 612.0, 792.0,
                      blocks=[TextBlock(lines=[l], bbox=l.bbox) for l in left + right],
                      drawings=[square(216.0), square(370.0), square(648.0)])
        self.assertEqual(_corroborated_markers(DocIR(path="t.pdf", pages=[page])),
                         set())
        self.assertEqual(_markers_to_text(page), 0)

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

    @staticmethod
    def _paras(blocks):
        lay = infer(DocIR(path="t.pdf", pages=[PageIR(1, 612.0, 792.0,
                                                      blocks=blocks)]))
        return [e for pg in lay.pages for ch in pg.chunks for e in ch.elements
                if isinstance(e, Para)]

    def test_each_numbered_note_is_its_own_paragraph(self):
        # y50: one-line notes 11.5pt apart, each number a separate block
        body = [_line("The full consultation text is published at the site and "
                      "responses may be sent to the office", 70.0, 547.0,
                      120.0 + 14.5 * i) for i in range(3)]
        notes = ["Text mining", "Sentiment analysis", "Deep learning"]
        blocks = [TextBlock(lines=[l], bbox=l.bbox) for l in body]
        for i, t in enumerate(notes):
            base = 712.0 + 11.5 * i
            ln = _line(t, 77.0, 77.0 + 6.0 * len(t), base, size=10.0)
            num = _line(str(i + 1), 71.0, 74.5, base - 3.5, size=6.5)
            blocks += [TextBlock(lines=[ln], bbox=ln.bbox),
                       TextBlock(lines=[num], bbox=num.bbox)]
        paras = [p for p in self._paras(blocks) if "Costed" not in p.text
                 and p.bbox[1] > 650]
        self.assertEqual([p.text for p in paras],
                         ["1Text mining", "2Sentiment analysis", "3Deep learning"])
        # each note is set at its own 10pt, not at its 6.5pt number's size
        self.assertTrue(all(p.leading >= 11.0 for p in paras))

    def test_a_mark_at_the_left_end_of_a_right_to_left_line_is_a_reference(self):
        # y50's body: the raised "33" closes the second line of a Persian
        # paragraph; it must not cut the paragraph there
        words = "در رویکرد " * 8
        lines = [_line(words, 79.0, 525.0, 120.0 + 20.8 * i, size=13.0)
                 for i in range(3)]
        ref = _line("33", 71.0, 78.5, 120.0 + 20.8 - 4.5, size=7.0)
        blocks = [TextBlock(lines=lines, bbox=(79.0, lines[0].bbox[1], 525.0,
                                               lines[-1].bbox[3])),
                  TextBlock(lines=[ref], bbox=ref.bbox)]
        paras = self._paras(blocks)
        self.assertEqual(len(paras), 1)
        self.assertIn("33", paras[0].text)


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
