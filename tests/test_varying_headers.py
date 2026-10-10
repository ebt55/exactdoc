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


def _line(text, y0, y1, size=10.0, x0=38.0, x1=300.0):
    s = Span(text, "Helvetica", size, "#000000", False, False, False,
             False, False, (x0, y0, x1, y1), (x0, y1 - 2.0))
    return Line([s], s.bbox)


def _stack_page(number, rows, height=792.0):
    """A page of (text, y0, y1) lines, one block each."""
    blocks = [TextBlock([_line(t, y0, y1)], (38.0, y0, 300.0, y1))
              for t, y0, y1 in rows]
    return PageIR(number=number, width=612.0, height=height, blocks=blocks)


def _consumed_texts(res, ir):
    out = set()
    for p in ir.pages:
        ct = res["consumed_text"][p.number]
        for bi, blk in enumerate(p.blocks):
            for ln in blk.lines:
                if (bi, id(ln)) in ct:
                    out.add(ln.text)
    return out


class FurnitureClearsTheBody(unittest.TestCase):
    """Geometry alone is not furniture: what it finds must stand clear of the
    body by a line of its own type (GEO_CLEAR_LINES). y64_bls_release_xpp
    sets "HOUSEHOLD DATA" over "Table A-n. ..." at one place and size on 31
    of its 38 later pages, the title 1.4pt above the table: the geometry
    pass consumed both and wrote neither."""

    TABLES = ["Table A-%d. %s" % (i + 1, t) for i, t in enumerate((
        "Employment status by sex", "Employment status by race",
        "Hispanic or Latino population", "Educational attainment",
        "Veterans by period of service", "Persons with a disability",
        "Foreign-born and native-born", "Selected employment indicators",
        "Duration of unemployment"))]

    def _doc(self, rows_for):
        pages = [_stack_page(1, [("Cover", 300.0, 311.0)])]
        pages += [_stack_page(i + 2, rows_for(i, t))
                  for i, t in enumerate(self.TABLES)]
        ir = _ir(pages)
        return ir, detect_hf(ir)

    def test_a_table_title_touching_its_table_is_body(self):
        ir, res = self._doc(lambda i, t: [
            (t, 46.3, 55.8),                       # 1.4pt above the table
            ("[Numbers in thousands]", 57.2, 65.8),
            ("body", 100.0, 110.0)])
        consumed = _consumed_texts(res, ir)
        self.assertFalse(any(t in consumed for t in self.TABLES), consumed)
        self.assertFalse(any(res["var_lines"].values()))

    def test_a_stacked_title_is_measured_from_its_inner_row(self):
        # the row above a candidate that touches the body is not clear of
        # the body either: "HOUSEHOLD DATA" stays with its table title
        ir, res = self._doc(lambda i, t: [
            ("HOUSEHOLD DATA" if i < 5 else "ESTABLISHMENT DATA", 35.3, 44.8),
            (t, 46.3, 55.8),
            ("[Numbers in thousands]", 57.2, 65.8)])
        self.assertEqual(_consumed_texts(res, ir), set())

    def test_a_running_head_clear_of_the_body_is_consumed(self):
        # y24's chapter head clears its page by 19.8pt (1.8 lines at 11pt)
        ir, res = self._doc(lambda i, t: [
            (t, 29.4, 40.3), ("body", 60.1, 71.6)])
        self.assertTrue(set(self.TABLES) <= _consumed_texts(res, ir))
        self.assertEqual(sum(len(v) for v in res["var_lines"].values()),
                         len(self.TABLES))

    def test_a_two_row_head_clear_of_the_body_is_consumed_whole(self):
        # each row varies; the upper row's own neighbour is the lower row,
        # which is furniture too -- the stack clears the body by 40pt
        ir, res = self._doc(lambda i, t: [
            ("Chapter %d" % (i // 2), 20.0, 30.0),
            (t, 32.0, 42.0), ("body", 82.0, 93.0)])
        consumed = _consumed_texts(res, ir)
        self.assertTrue(set(self.TABLES) <= consumed)
        self.assertTrue({"Chapter %d" % k for k in range(4)} <= consumed)

    def test_feet_are_not_held_to_the_bar(self):
        # y18's last EUR-Lex line sits 0.7pt below the line above it, the
        # one inside the foot band (BOTZ), the other just outside it. The
        # census separates it from real feet, but written back it is a line
        # the render has no room for (GEO_CLEAR_LINES): still consumed.
        ir, res = self._doc(lambda i, t: [
            ("body", 718.3, 728.3), (t, 729.0, 739.0)])
        self.assertTrue(set(self.TABLES) <= _consumed_texts(res, ir))

    def test_a_foot_is_measured_like_a_head(self):
        from exactdoc.infer import _furniture_clearance
        from exactdoc.infer import _no_furniture
        page = _stack_page(2, [("body", 718.3, 728.3),
                               ("foot", 729.0, 739.0)])
        ln = page.blocks[1].lines[0]
        clear = _furniture_clearance(
            _ir([page]), _no_furniture(), [(("bot", 243, 10), [(2, 1, ln)])])
        self.assertAlmostEqual(clear[id(ln)], 0.7, places=3)

    def test_a_page_with_no_body_counts_as_clear(self):
        ir, res = self._doc(lambda i, t: [(t, 29.4, 40.3)])
        self.assertTrue(set(self.TABLES) <= _consumed_texts(res, ir))


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
