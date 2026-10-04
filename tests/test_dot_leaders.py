"""Contents lines: dot leaders become a right tab stop with a dot leader.

Two producer idioms, one canonical form. LibreOffice and Word draw a leader
tab's dots as "." glyphs; Chromium draws a CSS `border-bottom: dotted` as
hundreds of 0.75pt squares (x11_chrome_toc_headings). Left as drawings, the
squares nearest each page number were promoted to bullets, those bullets read
as a right-hand column, and a single-column report was split into two columns
and rendered on four pages instead of two. Left as text, LibreOffice's nine
entries welded into one justified paragraph whose 24.5pt pitch could not fit
above its first line (x02_lo_report_toc: the contents block 7.8pt low).
"""
import unittest

from exactdoc.dialect import normalize, _drawn_leaders_to_text, _drop_offpage
from exactdoc.infer import infer
from exactdoc.layout import Para
from exactdoc.model import DocIR, DrawCmd, Line, PageIR, Span, TextBlock


def _span(text, x0, x1, base, size=11.0, color="#111111"):
    return Span(text=text, font="LiberationSerif", size=size, color=color,
                bold=False, italic=False, mono=False, serif=True,
                superscript=False, bbox=(x0, base - 9.8, x1, base + 2.4),
                origin=(x0, base))


def _blk(*spans):
    ln = Line(spans=list(spans), bbox=(min(s.bbox[0] for s in spans),
                                       min(s.bbox[1] for s in spans),
                                       max(s.bbox[2] for s in spans),
                                       max(s.bbox[3] for s in spans)))
    return TextBlock(lines=[ln], bbox=ln.bbox)


def _dots(x0, x1, cy, pitch=1.5, size=0.75):
    out, x = [], x0
    while x + size <= x1:
        out.append(DrawCmd(kind="fill", shape="rect",
                           bbox=(x, cy - size / 2, x + size, cy + size / 2),
                           fill="#999999", stroke=None, width=0.75,
                           opacity=1.0, n_items=5))
        x += pitch
    return out


def _body(y0, n=4):
    """A few full-width body lines so the page has a measurable column."""
    out = []
    for i in range(n):
        base = y0 + 15.8 * i
        out.append(_blk(_span("The depot replacement programme was approved on "
                              "the understanding that service levels", 58.0,
                              550.0 if i < n - 1 else 300.0, base)))
    return out


ENTRIES = [("1. Introduction", 127.0, "1"), ("2. Method", 105.2, "1"),
           ("2.1 Data sources", 135.5, "2"), ("3. Results", 103.3, "2")]


def _chrome_toc_page():
    blocks, draws = _body(111.0), []
    for i, (label, x1, num) in enumerate(ENTRIES):
        base = 213.0 + 19.6 * i
        blocks.append(_blk(_span(label, 57.8, x1, base, color="#14417a")))
        blocks.append(_blk(_span(num, 549.0, 554.5, base)))
        draws += _dots(x1 + 4.0, 545.2, base - 2.4)
    blocks += _body(320.0)
    return PageIR(1, 612.0, 792.0, blocks=blocks, drawings=draws)


class DrawnLeaders(unittest.TestCase):
    def test_a_dotted_border_between_title_and_number_becomes_text_dots(self):
        page = _chrome_toc_page()
        self.assertEqual(_drawn_leaders_to_text(page), len(ENTRIES))
        self.assertEqual(page.drawings, [])
        dots = [ln for b in page.blocks for ln in b.lines
                if set(ln.text) == {"."}]
        self.assertEqual(len(dots), len(ENTRIES))
        for ln in dots:          # on the TITLE's baseline, not the dots' own y
            self.assertIn(round(ln.baseline, 1),
                          [round(213.0 + 19.6 * i, 1) for i in range(4)])

    def test_dots_with_nothing_to_lead_stay_drawings(self):
        # a dotted rule under a heading: no text on either side
        page = PageIR(1, 612.0, 792.0, blocks=_body(111.0),
                      drawings=_dots(58.0, 550.0, 200.0))
        self.assertEqual(_drawn_leaders_to_text(page), 0)
        self.assertTrue(page.drawings)

    def test_no_leader_dot_is_promoted_to_a_bullet(self):
        ir = normalize(DocIR(path="t.pdf", pages=[_chrome_toc_page()]))
        texts = [ln.text for b in ir.pages[0].blocks for ln in b.lines]
        self.assertFalse(any("•" in t for t in texts), texts)


class LeaderParagraphs(unittest.TestCase):
    def _paras(self, page):
        lay = infer(normalize(DocIR(path="t.pdf", pages=[page])))
        return [e for pg in lay.pages for ch in pg.chunks for e in ch.elements
                if isinstance(e, Para)], lay

    def test_each_entry_is_title_tab_number_against_a_dot_leader_stop(self):
        paras, lay = self._paras(_chrome_toc_page())
        toc = [p for p in paras if p.tab_stops and len(p.tab_stops[0]) == 3]
        self.assertEqual(len(toc), len(ENTRIES))
        for p, (label, _x1, num) in zip(toc, ENTRIES):
            self.assertEqual(p.text, label + "\t" + num)
            pos, align, leader = p.tab_stops[0]
            self.assertEqual((align, leader), ("right", "dot"))
            self.assertAlmostEqual(pos + lay.margin_l, 554.5, delta=1.0)
        # and the page stays one column: the numbers are not a column
        self.assertTrue(all(ch.n_cols == 1 for pg in lay.pages
                            for ch in pg.chunks))

    def test_text_dots_at_a_shared_edge_are_a_tab_leader(self):
        # LibreOffice's form: the dots are glyphs, the numbers right-aligned
        blocks = _body(80.0)
        for i, (label, _x, num) in enumerate(ENTRIES):
            base = 160.0 + 24.5 * i
            blocks.append(_blk(_span(label + "." * 60 + num, 64.9, 532.9, base)))
        paras, lay = self._paras(PageIR(1, 612.0, 792.0, blocks=blocks))
        toc = [p for p in paras if p.tab_stops]
        self.assertEqual([p.text for p in toc],
                         [l + "\t" + n for l, _x, n in ENTRIES])
        # one paragraph per entry: never welded into one justified block
        self.assertTrue(all(p.src_lines == 1 for p in toc))

    def test_spaced_leaders_stay_text(self):
        # TeX / Typst / Texinfo: ". . . ." -- a Word dot leader would redraw
        # them dense, and every dot is a word to the reader of the text
        blocks = _body(80.0)
        for i, (label, _x, num) in enumerate(ENTRIES):
            base = 160.0 + 15.7 * i
            blocks.append(_blk(_span(label + " " + ". " * 40 + num, 141.6,
                                     510.2, base)))
        paras, _ = self._paras(PageIR(1, 612.0, 792.0, blocks=blocks))
        self.assertFalse(any(p.tab_stops for p in paras))

    def test_fixed_dot_runs_with_ragged_numbers_stay_text(self):
        # x15_rl_handbook_toc: 60 dots after each title, numbers at 278.6,
        # 300.1, 293.1 -- literal text, not a tab stop
        blocks = _body(80.0)
        for i, (label, x1, num) in enumerate(ENTRIES):
            base = 160.0 + 21.0 * i
            blocks.append(_blk(_span(label + " " + "." * 60 + " " + num, 74.4,
                                     x1 + 165.0, base)))
        paras, _ = self._paras(PageIR(1, 612.0, 792.0, blocks=blocks))
        self.assertFalse(any(p.tab_stops for p in paras))


class WriterLeader(unittest.TestCase):
    def test_writer_emits_a_dot_leader_tab(self):
        import os
        import tempfile
        import zipfile
        from exactdoc.docxout import write_docx
        lay = infer(normalize(DocIR(path="t.pdf", pages=[_chrome_toc_page()])))
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "t.docx")
            write_docx(lay, out)
            xml = zipfile.ZipFile(out).read("word/document.xml").decode()
        self.assertIn('w:leader="dot"', xml)
        self.assertEqual(xml.count('w:leader="dot"'), len(ENTRIES))


class OffPage(unittest.TestCase):
    def test_drawings_wholly_off_the_page_are_dropped(self):
        # Chromium repeats page 1's leaders in page 2's stream at y < 0
        page = PageIR(2, 612.0, 792.0, blocks=[],
                      drawings=_dots(110.0, 545.0, -453.0) +
                      _dots(110.0, 545.0, 200.0))
        n_on = len(_dots(110.0, 545.0, 200.0))
        dropped = _drop_offpage(page)
        self.assertEqual(len(page.drawings), n_on)
        self.assertEqual(dropped, n_on)


if __name__ == "__main__":
    unittest.main()
