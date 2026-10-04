"""Tables that are right: merged cells, real borders, the right partition.

Defect catalogue #13 and audit finding 8 / B24, in their measured forms:

  * a cell boundary exists only where the author drew one. NIST SP 800-171's
    mapping tables have a 'Security Requirement' cell spanning up to twenty
    rows; the lattice-only builder split its text over the rows its lines
    sat in and its words over the neighbouring columns. Missing internal
    edges are merges, written as w:gridSpan / w:vMerge.
  * each cell carries the borders drawn on its own sides, not one style on
    all four.
  * a table drawn as grey cells with WHITE gridlines (FIPS 180 Fig. 1) has no
    rule on its outer edge; the outer columns and header row are cells of
    the same table, found from their fills.
  * a fill-tiled table (ReportLab/HTML idiom) arrives as separate row bands
    with unshaded text rows between them; c3_tables' merged-header table was
    rasterised and its nested table flattened.
  * LibreOffice sizes a table row as max(top pads) + max(content) +
    max(bottom pads) over its cells, and adds the row's border width; the
    writer emits one top and one bottom pad per row and subtracts the border.

    python tests/test_table_merges.py
"""
import os
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.docxout import (_row_border_allowance, _span_cover,  # noqa: E402
                              _uniform_row_pads, write_docx)
from exactdoc.infer import (_grid_regions, _seg_cover, _tile_bands,  # noqa: E402
                            _clusters, build_grid_table, infer)
from exactdoc.layout import (Cell, Chunk, DocLayout, PageLayout,  # noqa: E402
                             Para, Run, TableEl)
from exactdoc.model import (DocIR, DrawCmd, Line, PageIR, Span,  # noqa: E402
                            TextBlock)

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None

W, H = 612.0, 792.0
WNS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _span(text, x0, top, size=9.0, x1=None):
    x1 = x1 if x1 is not None else x0 + 0.5 * size * len(text)
    bb = (x0, top, x1, top + size * 1.2)
    return Span(text=text, font="Helvetica", size=size, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=bb, origin=(x0, top + size))


def _line(*spans):
    bb = (min(s.bbox[0] for s in spans), min(s.bbox[1] for s in spans),
          max(s.bbox[2] for s in spans), max(s.bbox[3] for s in spans))
    return Line(spans=list(spans), bbox=bb)


def _bar(x0, y0, x1, y1, colour="#000000"):
    """A Word-style border: a 0.5pt filled bar per cell side."""
    shape = "hline" if (x1 - x0) >= (y1 - y0) else "vline"
    return DrawCmd(kind="fill", shape=shape, bbox=(x0, y0, x1, y1), fill=colour,
                   stroke=None, width=0.75, opacity=1.0, n_items=1)


def _tile(x0, y0, x1, y1, colour):
    return DrawCmd(kind="fill", shape="rect", bbox=(x0, y0, x1, y1), fill=colour,
                   stroke=None, width=0.0, opacity=1.0, n_items=1)


def _hseg(y, x0, x1, colour="#000000"):
    return _bar(x0, y - 0.25, x1, y + 0.25, colour)


def _vseg(x, y0, y1, colour="#000000"):
    return _bar(x - 0.25, y0, x + 0.25, y1, colour)


def _cl(draws):
    return list(enumerate(draws))


def _blocks(lines):
    return [TextBlock(lines=[ln], bbox=ln.bbox) for ln in lines]


def _texts(tbl):
    return [[(" / ".join(p.text for p in c.paras) if c else None) for c in row]
            for row in tbl.rows]


# A 3-column, 4-row Word-style grid (x 100/200/300/400, y 100/120/140/160/180):
#   row 0: a header cell spanning columns 1-2 (no segment at x=300, row 0)
#   rows 1-3: column 0 is one cell spanning all three (no segments at
#             y=140 and y=160 in column 0)
XS = (100.0, 200.0, 300.0, 400.0)
YS = (100.0, 120.0, 140.0, 160.0, 180.0)


def _merged_grid(missing=()):
    draws = []
    for i, y in enumerate(YS):
        for j in range(3):
            if (y in (140.0, 160.0) and j == 0) or ("h", i, j) in missing:
                continue
            draws.append(_hseg(y, XS[j], XS[j + 1]))
    for j, x in enumerate(XS):
        for i in range(4):
            if (x == 300.0 and i == 0) or ("v", i, j) in missing:
                continue
            draws.append(_vseg(x, YS[i], YS[i + 1]))
    return draws


def _merged_lines():
    return [
        _line(_span("Name", 105, 104)),
        _line(_span("Relevant controls", 210, 104, x1=330)),   # crosses x=300
        _line(_span("3.1.1 Limit system", 105, 124)),
        _line(_span("access to users", 105, 144)),
        _line(_span("and devices.", 105, 164)),
        _line(_span("AC-2", 205, 124), _span("Account", 305, 124)),
        _line(_span("AC-3", 205, 144), _span("Access", 305, 144)),
        _line(_span("AC-17", 205, 164), _span("Remote", 305, 164)),
    ]


class GridMerges(unittest.TestCase):
    def _build(self, draws, lines):
        consumed = set()
        return build_grid_table(_cl(draws), _blocks(lines), consumed)

    def test_missing_edges_are_merges(self):
        t = self._build(_merged_grid(), _merged_lines())
        self.assertIsNotNone(t)
        self.assertEqual(len(t.col_widths), 3)
        self.assertEqual(len(t.rows), 4)
        head = t.rows[0][1]
        self.assertEqual((head.col_span, head.row_span), (2, 1))
        self.assertIsNone(t.rows[0][2])
        self.assertEqual(head.paras[0].text.strip(), "Relevant controls")
        req = t.rows[1][0]
        self.assertEqual((req.col_span, req.row_span), (1, 3))
        self.assertIsNone(t.rows[2][0])
        self.assertIsNone(t.rows[3][0])
        # the merged cell holds all three lines of its text, nothing else
        self.assertIn("3.1.1 Limit system", " ".join(p.text for p in req.paras))
        self.assertIn("and devices.", " ".join(p.text for p in req.paras))
        self.assertEqual(t.rows[3][1].paras[0].text.strip(), "AC-17")
        self.assertEqual(t.rows[3][2].paras[0].text.strip(), "Remote")

    def test_every_lattice_cell_is_covered_once(self):
        t = self._build(_merged_grid(), _merged_lines())
        covered = {}
        for r, row in enumerate(t.rows):
            for c, cell in enumerate(row):
                if cell is None:
                    continue
                for rr in range(r, r + cell.row_span):
                    for cc in range(c, c + cell.col_span):
                        self.assertNotIn((rr, cc), covered)
                        covered[(rr, cc)] = True
        self.assertEqual(len(covered), 12)

    def test_a_fully_ruled_grid_has_no_merges(self):
        draws = []
        for y in YS:
            draws.append(_hseg(y, 100, 400))
        for x in XS:
            draws.append(_vseg(x, 100, 180))
        lines = [_line(_span("r%dc%d" % (i, j), XS[j] + 5, YS[i] + 4))
                 for i in range(4) for j in range(3)]
        t = self._build(draws, lines)
        self.assertTrue(all(c is not None and c.col_span == 1 and c.row_span == 1
                            for row in t.rows for c in row))
        self.assertEqual(_texts(t)[2], ["r2c0", "r2c1", "r2c2"])

    def test_unruled_columns_with_text_either_side_stay_columns(self):
        # verticals drawn only in the header row: the body columns are real,
        # the text says so (text both sides of x=200, nothing crossing it)
        draws = [_hseg(y, 100, 300) for y in (100.0, 120.0, 140.0, 160.0)]
        draws += [_vseg(x, 100, 120) for x in (100.0, 200.0, 300.0)]
        draws += [_vseg(x, 120, 160) for x in (100.0, 300.0)]
        lines = [_line(_span("A", 105, 104)), _line(_span("B", 205, 104)),
                 _line(_span("a1", 105, 124)), _line(_span("b1", 205, 124)),
                 _line(_span("a2", 105, 144)), _line(_span("b2", 205, 144))]
        t = self._build(draws, lines)
        self.assertEqual(_texts(t)[1], ["a1", "b1"])
        self.assertEqual(_texts(t)[2], ["a2", "b2"])

    def test_link_underline_inside_a_cell_is_not_a_row(self):
        # y01 p1: a 314pt underline under a link inside the value cell
        draws = []
        for y in (100.0, 130.0, 160.0):
            draws.append(_hseg(y, 100, 400))
        for x in (100.0, 200.0, 400.0):
            draws.append(_vseg(x, 100, 160))
        draws.append(_hseg(115.0, 210, 390, "#0000ff"))
        lines = [_line(_span("Related", 105, 104)),
                 _line(_span("https://example.org/a/long/link", 210, 104, x1=390)),
                 _line(_span("continued-link-text", 210, 116)),
                 _line(_span("Next", 105, 134)), _line(_span("value", 210, 134))]
        t = self._build(draws, lines)
        self.assertEqual(len(t.rows), 2)
        self.assertIn("continued-link-text", t.rows[0][1].paras[-1].text)


class PerEdgeBorders(unittest.TestCase):
    def test_borders_follow_the_drawn_sides(self):
        # an outer frame in red 1pt, inner lines black 0.5pt, and the
        # bottom-right cell's right side not drawn at all
        draws = []
        red = "#ff0000"
        draws.append(_bar(100, 99.5, 300, 100.5, red))       # top, 1pt
        draws.append(_bar(100, 159.5, 300, 160.5, red))      # bottom, 1pt
        draws.append(_bar(99.5, 100, 100.5, 160, red))       # left, 1pt
        draws.append(_vseg(300, 100, 130))                   # right, upper only
        draws.append(_hseg(130, 100, 300))
        draws.append(_vseg(200, 100, 160))
        lines = [_line(_span("x%d" % k, 105 + 100 * (k % 2), 104 + 30 * (k // 2)))
                 for k in range(4)]
        t = build_grid_table(_cl(draws), _blocks(lines), set())
        tl, br = t.rows[0][0], t.rows[1][1]
        self.assertEqual(tl.borders["top"][1], red)
        self.assertAlmostEqual(tl.borders["top"][0], 1.0, places=1)
        self.assertEqual(tl.borders["right"][1], "#000000")
        self.assertAlmostEqual(tl.borders["right"][0], 0.5, places=1)
        self.assertNotIn("right", br.borders)
        self.assertEqual(br.borders["bottom"][1], red)

    def test_dominant_ink_is_length_times_thickness(self):
        # FIPS 180: a 2.2pt white bar between two 0.1pt grey hairlines
        segs = [(100.0, 0, 50, 0.1, "#bfbfbf"), (101.1, 0, 50, 2.2, "#ffffff"),
                (102.2, 0, 50, 0.1, "#bfbfbf")]
        frac, style = _seg_cover(segs, 101.1, 0, 50)
        self.assertGreater(frac, 0.99)
        self.assertEqual(style[1], "#ffffff")


class TileExtension(unittest.TestCase):
    def test_white_gridlines_on_grey_cells_keep_the_outer_columns(self):
        grey, white = "#bfbfbf", "#ffffff"
        xs = (60.0, 180.0, 260.0, 340.0, 460.0)
        ys = (100.0, 130.0, 150.0, 170.0, 190.0)
        draws = []
        for i in range(4):
            for j in range(4):
                draws.append(_tile(xs[j] + 1.1, ys[i] + 1.1, xs[j + 1] - 1.1,
                                   ys[i + 1] - 1.1, grey))
        # white bars only BETWEEN cells: no outer rule anywhere
        for x in xs[1:-1]:
            draws.append(DrawCmd(kind="fill", shape="vline", bbox=(x - 1.1, ys[0], x + 1.1, ys[-1]),
                                 fill=white, stroke=None, width=0.75, opacity=1.0, n_items=1))
        for y in ys[1:-1]:
            draws.append(DrawCmd(kind="fill", shape="hline", bbox=(xs[0], y - 1.1, xs[-1], y + 1.1),
                                 fill=white, stroke=None, width=0.75, opacity=1.0, n_items=1))
        lines = [_line(_span("c%d%d" % (i, j), xs[j] + 6, ys[i] + 6))
                 for i in range(4) for j in range(4)]
        t = build_grid_table(_cl(draws), _blocks(lines), set())
        self.assertEqual(len(t.col_widths), 4)
        self.assertEqual(len(t.rows), 4)
        self.assertEqual(_texts(t)[0], ["c00", "c01", "c02", "c03"])
        self.assertEqual(_texts(t)[3], ["c30", "c31", "c32", "c33"])
        # the outer edge of the table is undrawn; the inner one is white
        self.assertNotIn("left", t.rows[1][0].borders)
        self.assertEqual(t.rows[1][0].borders["right"][1], white)
        self.assertEqual(t.rows[1][1].shading, grey)

    def test_an_empty_panel_beside_a_table_is_not_a_column(self):
        # y65: white boxes flush with a label table carry no text
        draws = []
        for y in (100.0, 115.0, 130.0, 145.0):
            draws.append(_hseg(y, 50, 185))
        for x in (50.0, 95.0, 185.0):
            draws.append(_vseg(x, 100, 145))
        draws.append(_tile(185.0, 100.0, 275.0, 145.0, "#eeeeee"))
        lines = [_line(_span("k%d" % i, 55, 103 + 15 * i)) for i in range(3)]
        t = build_grid_table(_cl(draws), _blocks(lines), set())
        self.assertEqual(len(t.col_widths), 2)


class Regions(unittest.TestCase):
    def test_an_l_shape_stays_rectangles(self):
        # 2x2 with only the boundary between (0,0)-(0,1) and (0,0)-(1,0)
        # missing: an L that gridSpan/vMerge cannot express
        v = [[True, False, True], [True, True, True]]
        h = [[True, True], [False, True], [True, True]]
        regions = _grid_regions(2, 2, v, h)
        cells = set()
        for (r0, c0), (r1, c1) in regions.items():
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    self.assertNotIn((r, c), cells)
                    cells.add((r, c))
        self.assertEqual(len(cells), 4)
        self.assertEqual(regions[(0, 0)], (0, 1))     # the horizontal run wins


class TiledBands(unittest.TestCase):
    def test_header_and_zebra_bands_join_through_text_rows(self):
        # c3_tables: a 2-row 'Region' tile beside 1-row tiles, then zebra rows
        # separated by unshaded text rows; no vertical rules anywhere
        dark, zebra = "#123a5e", "#f2f5f8"
        xs = (60.0, 200.0, 280.0, 360.0)
        draws = [_tile(60, 100, 200, 140, dark), _tile(200, 100, 360, 120, dark),
                 _tile(200, 120, 280, 140, dark), _tile(280, 120, 360, 140, dark)]
        for y0 in (160.0, 200.0):
            for j in range(3):
                draws.append(_tile(xs[j], y0, xs[j + 1], y0 + 20, zebra))
                draws.append(_hseg(y0, xs[j], xs[j + 1], "#d8dee5"))
                draws.append(_hseg(y0 + 20, xs[j], xs[j + 1], "#d8dee5"))
        lines = [_line(_span("Region", 65, 113)), _line(_span("Revenue", 205, 104)),
                 _line(_span("Q1", 205, 124)), _line(_span("Q2", 285, 124))]
        for k, y in enumerate((144.0, 164.0, 184.0, 204.0)):
            lines.append(_line(_span("row%d" % k, 65, y), _span("%d.1" % k, 205, y),
                               _span("%d.2" % k, 285, y)))
        page = PageIR(number=1, width=W, height=H)
        page.blocks = _blocks(lines)
        page.drawings = draws
        bands = _tile_bands(_clusters(list(enumerate(draws))), page.blocks, set())
        self.assertEqual(len(bands), 1)
        lay = infer(DocIR(path="x.pdf", pages=[page]))
        tables = [el for ch in lay.pages[0].chunks for el in ch.elements
                  if isinstance(el, TableEl)]
        self.assertEqual(len(tables), 1)
        t = tables[0]
        self.assertEqual((t.rows[0][0].row_span, t.rows[0][0].col_span), (2, 1))
        self.assertEqual((t.rows[0][1].row_span, t.rows[0][1].col_span), (1, 2))
        body = [r for r in _texts(t) if r[0] and r[0].startswith("row")]
        self.assertEqual([r[0] for r in body], ["row0", "row1", "row2", "row3"])
        self.assertEqual(body[2], ["row2", "2.1", "2.2"])

    def test_separate_boxes_of_one_column_do_not_join(self):
        draws = [_tile(60, 100, 360, 130, "#eef7f1"), _tile(60, 150, 360, 180, "#fdf1e8")]
        lines = [_line(_span("first box", 65, 110)), _line(_span("between", 65, 135)),
                 _line(_span("second box", 65, 160))]
        self.assertEqual(_tile_bands(_clusters(list(enumerate(draws))),
                                     _blocks(lines), set()), [])


class ChartsAreNotTables(unittest.TestCase):
    def test_a_framed_bar_chart_is_refused(self):
        # y60's MMWR chart: stroked bars on one baseline inside a gridded
        # frame -- a lattice with almost no text in it
        draws = [DrawCmd(kind="stroke", shape="rect", bbox=(100, 100, 400, 300),
                         fill=None, stroke="#000000", width=0.5, opacity=1.0, n_items=1)]
        for y in (140.0, 180.0, 220.0, 260.0):
            draws.append(_hseg(y, 100, 400, "#cccccc"))
        for k, h in enumerate((60.0, 120.0, 90.0, 150.0, 40.0)):
            x0 = 120 + 55 * k
            draws.append(DrawCmd(kind="fillstroke", shape="rect", bbox=(x0, 300 - h, x0 + 30, 300),
                                 fill="#3366cc", stroke="#000000", width=0.5,
                                 opacity=1.0, n_items=1))
        lines = [_line(_span("2018", 300, 110))]
        consumed = set()
        self.assertIsNone(build_grid_table(_cl(draws), _blocks(lines), consumed))
        self.assertEqual(consumed, set())          # nothing claimed on refusal


class HeadedTables(unittest.TestCase):
    def _page(self, number, lines, draws=()):
        pg = PageIR(number=number, width=W, height=H)
        pg.blocks = _blocks(lines)
        pg.drawings = list(draws)
        return pg

    def test_shaded_header_over_unruled_rows_is_one_table(self):
        # x04/x10 'Table 3': a grey header of abutting tiles, body rows of
        # bare text at the same pitch -- and the last row on the next page
        grey = "#d9d9d9"
        xs = (60.0, 180.0, 290.0, 450.0, 550.0)
        tiles = [_tile(xs[j], 650.0, xs[j + 1], 672.5, grey) for j in range(4)]
        head = [_line(_span(t, xs[j] + 6, 655.0, size=10.0))
                for j, t in enumerate(("Period", "On time", "Within", "Missed"))]
        body = []
        for k, (m, a, b, c) in enumerate((("January", "88.2%", "96.1%", "0.4%"),
                                          ("February", "86.9%", "95.4%", "0.6%"))):
            y = 677.5 + 22.5 * k
            body += [_line(_span(m, 66, y, size=10.0)), _line(_span(a, 255, y, size=10.0)),
                     _line(_span(b, 420, y, size=10.0)), _line(_span(c, 527, y, size=10.0))]
        p1 = self._page(1, [_line(_span("Table 3. Punctuality", 60, 620.0, size=12.0))]
                        + head + body, tiles)
        p2 = self._page(2, [_line(_span(t, x, 70.0, size=10.0)) for t, x in
                            (("March", 66), ("89.5%", 255), ("97.0%", 420), ("0.3%", 527))]
                        + [_line(_span("The recommendation is therefore to proceed with it.",
                                       60, 110.0, size=11.0, x1=520))])
        lay = infer(DocIR(path="x.pdf", pages=[p1, p2]))
        t1 = [el for ch in lay.pages[0].chunks for el in ch.elements if isinstance(el, TableEl)]
        self.assertEqual(len(t1), 1)
        self.assertEqual(_texts(t1[0])[0], ["Period", "On time", "Within", "Missed"])
        self.assertEqual(_texts(t1[0])[2], ["February", "86.9%", "95.4%", "0.6%"])
        self.assertEqual(t1[0].rows[0][0].shading, grey)
        t2 = [el for ch in lay.pages[1].chunks for el in ch.elements if isinstance(el, TableEl)]
        self.assertEqual(len(t2), 1)
        self.assertEqual(_texts(t2[0]), [["March", "89.5%", "97.0%", "0.3%"]])

    def test_a_card_row_over_a_paragraph_stays_cards(self):
        tiles = [_tile(60, 100, 300, 140, "#eeeeee"), _tile(300, 100, 540, 140, "#dddddd")]
        lines = [_line(_span("42%", 70, 110)), _line(_span("17 days", 310, 110)),
                 _line(_span("A paragraph that runs across both of the cards above.",
                             60, 150, x1=530))]
        lay = infer(DocIR(path="x.pdf", pages=[self._page(1, lines, tiles)]))
        tables = [el for ch in lay.pages[0].chunks for el in ch.elements
                  if isinstance(el, TableEl)]
        self.assertEqual(len(tables), 1)
        self.assertEqual(len(tables[0].rows), 1)


class RulesTablesCutApart(unittest.TestCase):
    def test_one_line_per_row_is_cut_into_its_cells(self):
        # BLS (XPP): 'occupations....... 70,548 72,168 1.9' arrives as ONE
        # line; the parser now gives each cell its own span
        rules = [DrawCmd(kind="stroke", shape="hline", bbox=(36, y, 575, y), fill=None,
                         stroke="#231f20", width=0.6, opacity=1.0, n_items=1)
                 for y in (66.6, 110.0, 200.0)]
        lines = [_line(_span("Employed", 300, 80, size=8.0, x1=336)),
                 _line(_span("Apr.", 285, 92, size=8.0, x1=300),
                       _span("Apr.", 337, 92, size=8.0, x1=351))]
        for k, (lab, a, b) in enumerate((("Total, 16 years and over....", "161,590 ", "164,043"),
                                         ("Management occupations.......", "70,548 ", "72,168"),
                                         ("Service occupations..........", "26,430 ", "27,286"))):
            y = 118 + 11 * k
            lines.append(_line(_span(lab, 38, y, size=8.0, x1=263), _span(a, 279, y, size=8.0, x1=307),
                               _span(b, 330, y, size=8.0, x1=358)))
        from exactdoc.infer import build_rules_table
        consumed = set()
        t = build_rules_table(rules, _blocks(lines), consumed)
        self.assertIsNotNone(t)
        self.assertEqual(len(t.col_widths), 3)
        texts = _texts(t)
        self.assertEqual([x.strip() if x else x for x in texts[-1]],
                         ["Service occupations..........", "26,430", "27,286"])
        # the group label centred over both figure columns spans them
        head = t.rows[0][1]
        self.assertEqual(head.col_span, 2)
        self.assertEqual(head.paras[0].text.strip(), "Employed")


class FiguresInNarrowColumns(unittest.TestCase):
    def test_flush_right_figures_are_right_aligned_and_keep_their_lines(self):
        from exactdoc.infer import _fit_grid_cells
        from exactdoc.infer import _cell_from_lines
        rect = (100.0, 100.0, 129.5, 140.0)
        lines = [_line(_span(v, 129.5 - 3.0 - w, 102 + 7.3 * i, size=6.5, x1=129.5 - 3.0))
                 for i, (v, w) in enumerate((("1,205", 14.2), ("52", 6.0), ("1,217", 14.2)))]
        cell = _cell_from_lines(lines, rect)
        _fit_grid_cells([(cell, lines, rect)])
        self.assertTrue(all(p.align == "right" for p in cell.paras))
        self.assertEqual(cell.pad[1], 1.0)
        self.assertAlmostEqual(cell.pad[3], 3.0, places=1)
        self.assertIn("\n", "".join(p.text for p in cell.paras))

    def test_left_aligned_words_stay_left(self):
        from exactdoc.infer import _fit_grid_cells
        from exactdoc.infer import _cell_from_lines
        rect = (100.0, 100.0, 300.0, 140.0)
        lines = [_line(_span("Account Management", 105, 102)),
                 _line(_span("Remote Access", 105, 113))]
        cell = _cell_from_lines(lines, rect)
        before = cell.pad
        _fit_grid_cells([(cell, lines, rect)])
        self.assertEqual(cell.pad, before)
        self.assertTrue(all(p.align != "right" for p in cell.paras))


class WideSpaceSplitsTheSpan(unittest.TestCase):
    def test_a_space_boxed_across_a_gap_ends_the_span(self):
        from exactdoc.parse_pdfium import _Char, _build_lines

        def ch(u, x0, x1, gen=False):
            c = _Char()
            c.u, c.x0, c.x1, c.y0, c.y1 = u, x0, x1, 100.0, 108.0
            c.ox, c.oy, c.size, c.font, c.flags, c.color, c.gen = \
                x0, 106.0, 8.0, "Helvetica", 0, "#000000", gen
            return c
        chars, x = [], 50.0
        for u in "occupations":
            chars.append(ch(u, x, x + 4.0))
            x += 4.0
        # PDFium's synthesised space, boxed from the last ink to the next word
        chars.append(ch(" ", x, 282.6, gen=True))
        x = 282.6
        for u in "70,548":
            chars.append(ch(u, x, x + 4.0))
            x += 4.0
        lines = _build_lines(chars)
        self.assertEqual(len(lines), 1)
        spans = lines[0].spans
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0].text.strip(), "occupations")
        self.assertAlmostEqual(spans[0].bbox[2], 94.0, places=1)   # the space is not ink
        self.assertAlmostEqual(spans[1].bbox[0], 282.6, places=1)
        self.assertEqual(lines[0].text.replace(" ", ""), "occupations70,548")


def _para(text, lead=11.0, n=1):
    p = Para(runs=[Run(text, "Helvetica", 9.0, "#000000")], leading=lead)
    p.src_lines = n
    return p


def _c(text, pad, n=1, rs=1, cs=1, borders=None):
    c = Cell(paras=[_para(text, n=n)] if text else [], pad=pad,
             borders=borders if borders is not None else {})
    c.row_span, c.col_span = rs, cs
    return c


class WriterRowPads(unittest.TestCase):
    def test_one_top_and_one_bottom_pad_per_row(self):
        # the measured y02 row: a 2-line cell (0.7/2.0) beside 1-line cells
        # whose bottom pads carry the row's height (1.3/12.8)
        row = [_c("Physical Access Authorizations", (0.7, 5.4, 2.0, 2.0), n=2),
               _c("PE-2", (1.3, 5.4, 12.8, 2.0)), _c(None, (2.0, 4.0, 2.0, 4.0))]
        out = _uniform_row_pads([row], 3)[0]
        self.assertEqual({c.pad[0] for c in out}, {0.7})
        self.assertEqual({c.pad[2] for c in out}, {2.0})
        # the 1-line cell keeps its text where it was: 0.6pt lifted into
        # space-before; the source cell is untouched
        self.assertAlmostEqual(out[1].paras[0].space_before, 0.6, places=2)
        self.assertEqual(row[1].pad, (1.3, 5.4, 12.8, 2.0))

    def test_merged_down_cells_give_up_their_bottom_pad(self):
        row = [_c("spans rows", (1.0, 5.0, 2.0, 2.0), n=3, rs=3),
               _c("one", (1.0, 5.0, 3.0, 2.0))]
        out = _uniform_row_pads([row], 2)[0]
        self.assertEqual(out[0].pad[2], 0.0)
        self.assertEqual(out[1].pad[2], 3.0)

    def test_border_allowance_comes_off_the_bottom_pad(self):
        b = {k: (0.5, "#000000") for k in ("top", "bottom", "left", "right")}
        row = [_c("a", (1.3, 5.4, 1.7, 2.0), borders=b), _c("b", (1.3, 5.4, 1.7, 2.0), borders=b)]
        self.assertAlmostEqual(_row_border_allowance(row), 0.5)
        out = _uniform_row_pads([row], 2)[0]
        self.assertAlmostEqual(out[0].pad[2], 1.2)


class WriterSpans(unittest.TestCase):
    def _write(self, t):
        lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[t])])])
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "t.docx")
            write_docx(lay, path, output_profile="standard")
            with zipfile.ZipFile(path) as z:
                return ET.fromstring(z.read("word/document.xml"))

    def _table(self):
        b = {k: (0.5, "#000000") for k in ("top", "bottom", "left", "right")}
        t = TableEl(col_widths=[100.0, 100.0, 100.0], row_heights=[20.0, 20.0, 20.0])
        t.rows = [
            [_c("head", (1, 4, 2, 2), borders=b), _c("wide", (1, 4, 2, 2), cs=2, borders=b), None],
            [_c("tall", (1, 4, 2, 2), n=2, rs=2, borders=b), _c("x", (1, 4, 2, 2), borders=b),
             _c("y", (1, 4, 2, 2), borders=b)],
            [None, _c("z", (1, 4, 2, 2), borders=b), _c("w", (1, 4, 2, 2), borders=b)],
        ]
        return t

    def test_gridspan_and_vmerge_are_written(self):
        root = self._write(self._table())
        tbl = root.find(".//" + WNS + "tbl")
        rows = tbl.findall(WNS + "tr")
        self.assertEqual([len(r.findall(WNS + "tc")) for r in rows], [2, 3, 3])
        span = rows[0].findall(WNS + "tc")[1].find(WNS + "tcPr/" + WNS + "gridSpan")
        self.assertEqual(span.get(WNS + "val"), "2")
        tcw = rows[0].findall(WNS + "tc")[1].find(WNS + "tcPr/" + WNS + "tcW")
        self.assertEqual(tcw.get(WNS + "w"), "4000")
        restart = rows[1].findall(WNS + "tc")[0].find(WNS + "tcPr/" + WNS + "vMerge")
        self.assertEqual(restart.get(WNS + "val"), "restart")
        cont = rows[2].findall(WNS + "tc")[0].find(WNS + "tcPr/" + WNS + "vMerge")
        self.assertIsNotNone(cont)
        self.assertIsNone(cont.get(WNS + "val"))
        # schema order inside tcPr: tcW, gridSpan, vMerge, tcBorders, ...
        tags = [e.tag.split("}")[1] for e in rows[1].findall(WNS + "tc")[0].find(WNS + "tcPr")]
        self.assertLess(tags.index("vMerge"), tags.index("tcBorders"))
        # no rule across the inside of the merge
        bottom = rows[1].findall(WNS + "tc")[0].find(
            WNS + "tcPr/" + WNS + "tcBorders/" + WNS + "bottom")
        self.assertEqual(bottom.get(WNS + "val"), "nil")

    def test_span_cover_maps_every_covered_position(self):
        t = self._table()
        cover = _span_cover(t, 3, 3)
        self.assertEqual(set(cover), {(0, 2), (2, 0)})


@unittest.skipIf(_canvas is None, "reportlab not installed")
class ParserSpanSplit(unittest.TestCase):
    def test_a_forgiven_wide_gap_still_ends_the_span(self):
        # Word ends every cell line with a literal space; the next cell's
        # text on the same baseline sits a column away. One line (the
        # justification exemption), two spans with their own boxes.
        from exactdoc.parse_pdfium import parse_pdf
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "gap.pdf")
            c = _canvas.Canvas(path, pagesize=(W, H))
            c.setFont("Helvetica", 9)
            c.drawString(124.2, 700, "authorized users, processes ")
            c.drawString(438.5, 700, "de-registration")
            c.save()
            ir = parse_pdf(path, keep_image_data=False)
        lines = [ln for b in ir.pages[0].blocks for ln in b.lines]
        hit = [ln for ln in lines if "processes" in ln.text]
        self.assertEqual(len(hit), 1)
        spans = [s for s in hit[0].spans if s.text.strip()]
        texts = [s.text.strip() for s in spans]
        self.assertIn("de-registration", texts[-1])
        self.assertGreater(len(spans), 1)
        self.assertLess(spans[0].bbox[2], 300)
        self.assertGreater(spans[-1].bbox[0], 430)


if __name__ == "__main__":
    unittest.main()
