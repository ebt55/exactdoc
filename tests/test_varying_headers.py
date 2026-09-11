"""Varying running furniture: consumed by geometry, not by text.

The text-signature pass consumes a line only when position AND text repeat
on >= 60% of pages -- per-chapter headers never reach the bar. A geometry
holding exactly one line on >= 60% of pages inside the furniture zone is
furniture by construction (real content starts below the zone), and is
consumed without emission: a varying header cannot be stated by the
representative-page machinery, and a source page number is wrong in the
DOCX once pagination differs.
"""
import unittest

from exactdoc.infer import detect_hf
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock

TOPZ, BOTZ = 62.0, 64.0


def _page(number, top_texts, bottom_texts=(), height=792.0):
    spans_lines = []
    for i, t in enumerate(top_texts):
        s = Span(t, "Helvetica", 11.0, "#000000", False, False, False,
                 False, False, (72.0, 30.0, 300.0, 41.0), (72.0, 40.0))
        spans_lines.append(Line([s], s.bbox))
    for t in bottom_texts:
        s = Span(t, "Helvetica", 9.0, "#000000", False, False, False,
                 False, False, (72.0, height - 50.0, 300.0, height - 41.0),
                 (72.0, height - 42.0))
        spans_lines.append(Line([s], s.bbox))
    # one body line well below the furniture zone
    b = Span("body text", "Helvetica", 10.0, "#000000", False, False,
             False, False, False, (72.0, 100.0, 300.0, 111.0), (72.0, 110.0))
    spans_lines.append(Line([b], b.bbox))
    blk = TextBlock(spans_lines, (72.0, 30.0, 300.0, 111.0))
    return PageIR(number=number, width=612.0, height=height, blocks=[blk])


def _ir(pages):
    return DocIR(path="x.pdf", pages=pages)


class VaryingFurniture(unittest.TestCase):
    def test_varying_top_line_on_most_pages_is_consumed(self):
        pages = [_page(1, [])]
        chapters = ["Intro", "Options", "Options", "Templates",
                    "Templates", "Variables", "Variables", "Last"]
        pages += [_page(i + 2, [t]) for i, t in enumerate(chapters)]
        res = detect_hf(_ir(pages))
        consumed = sum(len(v) for k, v in res["consumed_text"].items()
                       if k != 1)
        # all 8 furniture lines consumed (pages 2-9); page 1 has no top line
        self.assertEqual(consumed, 8)
        self.assertFalse(res["rep_lines"],
                         "consumed without emission: no representative part")

    def test_rare_geometry_is_not_furniture(self):
        # the same geometry on only 2 of 8 pages: real content, untouched
        pages = [_page(1, [])] + \
                [_page(i + 2, ["Options"] if i in (2, 5) else [])
                 for i in range(8)]
        res = detect_hf(_ir(pages))
        self.assertEqual(sum(len(v) for v in res["consumed_text"].values()),
                         0)

    def test_two_lines_at_the_geometry_do_not_qualify(self):
        # a geometry carrying TWO lines on a page is not the single-line
        # furniture signature; none of it is consumed. Both lines vary, so
        # the fixed-text rule cannot consume them either.
        pages = [_page(1, [])]
        words = ["Intro", "Options", "Output", "Templates", "Variables",
                 "Citations", "Filters", "Epilogue"]
        pages += [_page(i + 2, ["Chapter " + w, "section " + w])
                  for i, w in enumerate(words)]
        res = detect_hf(_ir(pages))
        self.assertEqual(sum(len(v) for v in res["consumed_text"].values()),
                         0)

    def test_fixed_text_header_still_emits_as_before(self):
        # the pre-existing path: same text on >= 60% of pages becomes a
        # real representative header part, not silent consumption
        pages = [_page(1, [])] + \
                [_page(i + 2, ["Running Head"]) for i in range(8)]
        res = detect_hf(_ir(pages))
        self.assertTrue(res["rep_lines"],
                        "fixed furniture still reaches the representative "
                        "machinery and is emitted")


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
