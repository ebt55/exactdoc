"""The structures that kept six promised documents from their page counts (WP22).

Each case is the smallest reproduction of what a real document does, measured
on that document first:

* a marker item whose first line arrives as a block of its own (EUR-Lex
  recitals, y18) and a run-in numbered paragraph ("2." at the margin, its first
  line indented, the rest back under the number; EUR-Lex articles);
* a rule drawn as abutting segments split at a parity-dependent x, and a head
  rule drawn just past TOPZ (EUR-Lex's foot and head rules);
* a recto running foot that names the current section beside a verso foot
  (LibreOffice Writer Guide, y36);
* a table whose every row is filled, arriving as one drawing cluster; a
  callout band with an icon; a white frame behind a picture; an image placed
  larger than its clip (y36);
* rule-ruled and booktabs tables whose rules share their ends with another
  table on the page (y36, y24);
* a contents page whose page numbers are lines of their own, and index lines
  with spaced leaders (y24, y26);
* grid tables standing side by side on one band (FIPS 197's Appendix B, y03).

    python tests/test_promised_documents.py
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import infer as I                            # noqa: E402
from exactdoc.infer import detect_hf, infer                # noqa: E402
from exactdoc.layout import Cell, ColBreak, Para, TableEl  # noqa: E402
from exactdoc.model import DocIR, DrawCmd, ImageObj, Line, PageIR, Span, TextBlock  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                        # pragma: no cover
    _canvas = None

WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo "
         "lima mike november oscar papa quebec romeo sierra tango uniform "
         "victor whiskey xray yankee zulu").split()


def _span(text, x0, base, size=9.0, x1=None, font="Times-Roman"):
    x1 = x1 if x1 is not None else x0 + 0.5 * size * len(text)
    return Span(text, font, size, "#000000", False, False, False, True, False,
                (x0, base - 0.8 * size, x1, base + 0.25 * size), (x0, base))


def _ln(text, x0, base, size=9.0, x1=None):
    s = _span(text, x0, base, size, x1)
    return Line([s], s.bbox)


def _words(seed, n=10):
    return " ".join(WORDS[(seed * 5 + k) % len(WORDS)] for k in range(n))


def _page(n, blocks, W=595.0, H=842.0, drawings=(), images=()):
    return PageIR(number=n, width=W, height=H,
                  blocks=[TextBlock(list(b), _union(b)) for b in blocks],
                  drawings=list(drawings), images=list(images))


def _union(lines):
    bb = None
    for l in lines:
        bb = l.bbox if bb is None else (min(bb[0], l.bbox[0]), min(bb[1], l.bbox[1]),
                                        max(bb[2], l.bbox[2]), max(bb[3], l.bbox[3]))
    return bb


def _paras(lay, page=1):
    out = []
    for ch in lay.pages[page - 1].chunks:
        for el in ch.elements:
            if isinstance(el, Para):
                out.append(el)
    return out


def _text(p):
    return "".join(r.text for r in p.runs)


def _hline(x0, x1, y, w=0.5):
    return DrawCmd("stroke", "hline", (x0, y - w / 2, x1, y + w / 2), None,
                   "#000000", w, 1.0, 2)


def _fill(x0, y0, x1, y1, color="#ffffff"):
    return DrawCmd("fill", "rect", (x0, y0, x1, y1), color, None, 0.1, 1.0, 5)


class MarkerItemsRunOn(unittest.TestCase):
    """y18: the recital's first line and its other lines are two blocks."""
    L, R = 67.4, 527.9

    def _doc(self, first_end):
        marker = _ln("(4)", self.L, 220.4, x1=76.4)
        first = _ln(_words(1, 14), 93.7, 220.4, x1=first_end)
        rest = [_ln(_words(2 + i, 14), 93.7, 231.0 + 10.5 * i,
                    x1=self.R if i < 2 else 300.0) for i in range(3)]
        lead = [_ln(_words(9 + i, 16), self.L, 120.0 + 10.5 * i, x1=self.R)
                for i in range(4)]
        page = _page(1, [lead, [marker], [first], rest])
        return infer(DocIR(path="y18.pdf", pages=[page]))

    def test_full_first_line_takes_its_continuation(self):
        lay = self._doc(self.R)
        item = next(p for p in _paras(lay) if _text(p).startswith("(4)"))
        self.assertIn(_words(4, 14), _text(item))      # the item's last line
        self.assertEqual(item.src_lines, 4)
        self.assertLess(item.first_indent, -20.0)      # still a hanging item
        self.assertAlmostEqual(item.leading, 10.6, delta=0.15)

    def test_short_first_line_stays_its_own_paragraph(self):
        lay = self._doc(400.0)
        item = next(p for p in _paras(lay) if _text(p).startswith("(4)"))
        self.assertNotIn(_words(2, 14), _text(item))


class RunInNumberedParagraph(unittest.TestCase):
    """y18 p55: '2.' at the margin, the first line indented on its baseline,
    the next line back at the margin -- one block holds '2.' and 'criteria:'."""
    L, R = 67.4, 527.9

    def test_number_opens_one_paragraph_set_back_at_the_margin(self):
        lead = [_ln(_words(9 + i, 16), self.L, 50.0 + 10.5 * i, x1=self.R)
                for i in range(4)]
        num_block = [_ln("2.", self.L, 84.2, x1=74.6),
                     _ln("criteria and the rest", self.L, 94.7, x1=200.0)]
        first = [_ln(_words(3, 15), 89.0, 84.2, x1=self.R)]
        lay = infer(DocIR(path="runin.pdf",
                          pages=[_page(1, [lead, num_block, first])]))
        item = next(p for p in _paras(lay) if _text(p).startswith("2."))
        self.assertIn("criteria and the rest", _text(item))
        self.assertEqual(item.left_indent, 0.0)
        self.assertEqual(item.first_indent, 0.0)
        self.assertEqual(sum(1 for r in item.runs if r.is_tab), 1)
        self.assertAlmostEqual(item.tab_stops[0][0], 21.6, delta=0.2)
        self.assertAlmostEqual(item.leading, 10.5, delta=0.05)


class SegmentedFurnitureRules(unittest.TestCase):
    """y18: the foot rule as two segments split under the folio, at a
    different x on versos and rectos; the head rule 3.5pt past TOPZ."""

    def _doc(self, n=8):
        pages = []
        for pg in range(1, n + 1):
            split = 98.5 if pg % 2 == 0 else 496.7
            draws = [_hline(41.8, 297.6, 64.0), _hline(297.6, 553.4, 64.0),
                     _hline(41.8, split, 806.4), _hline(split, 553.4, 806.4)]
            head = [_ln("OJ L, 12.7.2024", 41.8, 57.9, x1=104.1)]
            foot = [_ln("ELI: http://data.europa.eu/eli/reg/2024/1689/oj", 376.8, 820.2,
                        x1=553.4), _ln("%d/144" % pg, 41.8, 820.2, x1=65.0)]
            body = [_ln(_words(pg * 3 + i, 16), 67.4, 84.0 + 12.0 * i, x1=527.9)
                    for i in range(50)]
            pages.append(_page(pg, [head, body, foot], drawings=draws))
        return DocIR(path="oj.pdf", pages=pages)

    def test_rule_runs_sign_the_whole_rule(self):
        ds = [_hline(41.8, 98.5, 806.4), _hline(98.5, 553.4, 806.4), _hline(41.8, 553.4, 64.0)]
        runs = I._rule_runs(ds)
        self.assertEqual(runs, {0: (41.8, 553.4), 1: (41.8, 553.4)})

    def test_both_halves_of_both_rules_leave_the_body(self):
        hf = detect_hf(self._doc())
        for pg in range(2, 9):
            self.assertEqual(hf["consumed_draw"][pg], {0, 1, 2, 3}, pg)


class RectoSectionFoot(unittest.TestCase):
    """y36: '6 | Chapter 1 Introducing Writer' on versos, '<section> | 5' on
    rectos, 70pt above the foot of A4 -- outside BOTZ."""

    def test_recto_feet_are_consumed_as_varying_furniture(self):
        pages = []
        names = ["Parts of the main window"] * 6 + ["Creating a document"] * 4 + \
            ["Saving a document"] * 4
        for pg in range(1, 15):
            body = [_ln(_words(pg * 7 + i, 14), 51.1, 70.0 + 12.7 * i, x1=520.0)
                    for i in range(40)]
            if pg % 2 == 0:
                foot = _ln("%d | Chapter 1 Introducing Writer" % pg, 51.1, 780.0, x1=195.0)
            else:
                foot = _ln("%s | %d" % (names[pg - 1], pg), 380.0, 780.0, x1=542.0)
            pages.append(_page(pg, [body, [foot]]))
        hf = detect_hf(DocIR(path="writer.pdf", pages=pages))
        for pg in range(3, 15, 2):
            self.assertTrue(any("|" in ln.text for _, _, ln in hf["var_lines"][pg]), pg)


class FilledRowTable(unittest.TestCase):
    """y36 p2: a header row and four body rows, every cell a filled tile,
    the rows touching -- one drawing cluster."""

    def test_one_cluster_of_tile_rows_is_one_table(self):
        xs = [51.0, 181.9, 343.5, 524.8]
        ys = [574.1, 591.3, 620.7, 650.0, 667.3, 684.5]
        draws, cells = [], []
        for r in range(5):
            for c in range(3):
                draws.append(_fill(xs[c], ys[r], xs[c + 1], ys[r + 1],
                                   "#e6e6e6" if r == 0 else "#ffffff"))
                cells.append(_ln("cell %d %d" % (r, c), xs[c] + 5.8,
                                 ys[r] + 12.0, x1=xs[c] + 70.0))
        draws += [_hline(51.0, 524.8, y, 0.1) for y in ys]
        body = [_ln(_words(i, 14), 51.1, 100.0 + 12.7 * i, x1=520.0) for i in range(20)]
        lay = infer(DocIR(path="tiles.pdf",
                          pages=[_page(1, [body] + [[c] for c in cells], drawings=draws)]))
        tabs = [e for ch in lay.pages[0].chunks for e in ch.elements
                if isinstance(e, TableEl)]
        self.assertEqual(len(tabs), 1)
        self.assertEqual(len(tabs[0].rows), 5)
        self.assertEqual(tabs[0].role, "table")


class Ornaments(unittest.TestCase):
    def test_an_icon_on_a_band_does_not_make_it_artwork(self):
        band = _fill(70.8, 467.8, 544.2, 493.5, "#d9e7e2")
        icon = DrawCmd("fill", "complex", (74.0, 470.9, 93.4, 490.4), "#76a797",
                       None, 0.1, 1.0, 40)
        tick = DrawCmd("stroke", "line", (78.5, 476.9, 88.2, 485.2), None,
                       "#ffffff", 3.0, 1.0, 2)
        self.assertEqual(I._classify_cluster([(0, band), (1, icon), (2, tick)]),
                         "boxlike")

    def test_artwork_bigger_than_a_tenth_of_its_fill_still_is(self):
        band = _fill(0, 0, 100, 100, "#d9e7e2")
        art = DrawCmd("fill", "complex", (10, 10, 60, 60), "#76a797", None, 0.1, 1.0, 40)
        self.assertEqual(I._classify_cluster([(0, band), (1, art)]), "figure")

    def test_a_white_frame_behind_a_picture_is_not_a_box(self):
        frame = _fill(131.8, 176.7, 483.4, 459.3)
        pic = ImageObj(bbox=(147.1, 176.7, 442.8, 446.0), xref=0, width=295, height=269)
        self.assertTrue(I._blank_picture_frame(frame, [pic]))
        self.assertFalse(I._blank_picture_frame(_fill(131.8, 176.7, 483.4, 459.3,
                                                      "#cdd5e8"), [pic]))
        self.assertFalse(I._blank_picture_frame(frame, []))


@unittest.skipIf(_canvas is None, "reportlab not installed")
class ClippedImage(unittest.TestCase):
    """y36 p11: a screenshot placed 414pt tall under a clip that shows 269pt."""

    def test_parser_reports_the_visible_part(self):
        from PIL import Image
        from exactdoc.backend import get_backend
        from exactdoc.input import parse
        d = tempfile.mkdtemp()
        png = os.path.join(d, "shot.png")
        im = Image.new("RGB", (100, 140), (200, 30, 30))
        for y in range(70, 140):
            for x in range(100):
                im.putpixel((x, y), (30, 30, 200))
        im.save(png)
        pdf = os.path.join(d, "clip.pdf")
        c = _canvas.Canvas(pdf, pagesize=(595, 842))
        c.saveState()
        p = c.beginPath()
        p.rect(100, 442, 300, 200)                # clip: y 200..400 top-down
        c.clipPath(p, stroke=0, fill=0)
        c.drawImage(png, 100, 200, width=300, height=420)   # placed 222..642
        c.restoreState()
        c.drawString(100, 842 - 700, "caption under the picture")
        c.save()
        ir = parse(get_backend("pdfium"), pdf)
        imgs = ir.pages[0].images
        self.assertEqual(len(imgs), 1)
        x0, y0, x1, y1 = imgs[0].bbox
        self.assertAlmostEqual(y0, 222.0, delta=1.0)
        self.assertAlmostEqual(y1, 400.0, delta=1.0)
        crop = Image.open(__import__("io").BytesIO(imgs[0].data))
        # 178pt of 420 shown, from the top: that share of the pixel rows, red
        self.assertAlmostEqual(crop.size[1], round(140 * 178 / 420.0), delta=1)
        self.assertEqual(crop.convert("RGB").getpixel((50, 0)), (200, 30, 30))


class RuledTables(unittest.TestCase):
    def test_a_rule_under_every_row_makes_rows_of_bands(self):
        """y36 p23: a label centred between its description's two lines."""
        rules = [72.3 + 32.2 * i for i in range(6)]
        blocks = []
        for i in range(5):
            top = rules[i]
            blocks.append([_ln("%d Navigate By" % (i + 1), 84.4, top + 17.0, x1=170.0)])
            blocks.append([_ln("Opens a drop-down list where you can", 235.2, top + 11.0,
                               x1=520.9),
                           _ln("select the element.", 235.2, top + 23.1, x1=330.0)])
        blocks.append([_ln(_words(i, 14), 71.0, 500.0 + 12.7 * i, x1=541.0)
                       for i in range(10)])
        lay = infer(DocIR(path="ruled.pdf", pages=[_page(
            1, blocks, drawings=[_hline(70.9, 544.3, y, 0.5) for y in rules])]))
        tabs = [e for ch in lay.pages[0].chunks for e in ch.elements
                if isinstance(e, TableEl)]
        self.assertEqual(len(tabs), 1)
        self.assertEqual(len(tabs[0].rows), 5)
        self.assertEqual(len(tabs[0].col_widths), 2)

    def test_same_width_tables_split_at_the_prose_between_them(self):
        grp = [(0, _hline(110.9, 537.1, 166.2)), (1, _hline(110.9, 537.1, 187.2)),
               (2, _hline(110.9, 537.1, 248.6)), (3, _hline(110.9, 537.1, 378.7)),
               (4, _hline(110.9, 537.1, 399.7)), (5, _hline(110.9, 537.1, 628.7))]
        prose = [_ln("The value of input-files may be left empty", 107.7, 286.5,
                     x1=539.9)]
        runs = I._rule_runs_by_text(grp, [TextBlock(prose, prose[0].bbox)], set())
        self.assertEqual([[i for i, _ in r] for r in runs], [[0, 1, 2], [3, 4, 5]])
        self.assertTrue(I._booktabs_head([378.7, 399.7, 628.7]))
        self.assertFalse(I._booktabs_head([100.0, 628.7]))
        self.assertTrue(I._ruled_rows([72.3 + 32.2 * i for i in range(6)]))


class ContentsAndIndex(unittest.TestCase):
    def test_contents_numbers_are_row_ends_not_a_column(self):
        """y24 p3: spaced leaders as text, each number a line of its own."""
        entries, nums = [], []
        y = 180.0
        for i in range(24):
            if i % 6 == 0:
                entries.append(_ln("Part %s" % WORDS[i], 72.0, y, x1=130.0))
            else:
                entries.append(_ln("Entry %s . . . . . . . . . . . . . . . ." % WORDS[i],
                                   88.4, y, x1=477.4))
            nums.append(_ln(str(3 + i), 498.5 if i < 7 else 493.1, y, x1=504.0))
            y += 13.6
        lay = infer(DocIR(path="toc.pdf", pages=[_page(
            1, [entries] + [[n] for n in nums], W=612.0, H=792.0)]))
        els = [e for ch in lay.pages[0].chunks for e in ch.elements]
        self.assertFalse(any(isinstance(e, ColBreak) for e in els))
        rows = [p for p in _paras(lay) if any(r.is_tab for r in p.runs)]
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(p.tab_stops[0][1] == "right" for p in rows))

    def test_spaced_leader_lines_are_rows_and_fit_their_column(self):
        """y26's index: 'bg . . . . 126', the dots set by TeX's glue."""
        lines = [_ln("%s . . . . . . . . . . . . . . . . . . . . . %d" % (w, 50 + i),
                     90.0, 350.0 + 10.5 * i, x1=297.0)
                 for i, w in enumerate(["bg", "bind", "break", "builtin"])]
        items = [("blk", lines[0].bbox, lines)]
        found, ids = I._spaced_leader_lines(items)
        self.assertEqual(len(found), 4)
        p = I._spaced_leader_para(lines[0], found[0][1], 90.0, 297.0)
        self.assertEqual(sum(1 for r in p.runs if r.is_tab), 1)
        self.assertEqual(p.runs[-1].text, "50")
        self.assertEqual(p.tab_stops, [(207.0, "right")])
        head = "".join(r.text for r in p.runs[:-2])
        self.assertTrue(head.startswith("bg ."))


class SideBySideTables(unittest.TestCase):
    """y03 p42: five 4x4 state grids on one band, the round number beside."""

    @staticmethod
    def _grid(x0, y0):
        t = TableEl(role="table", bbox=(x0, y0, x0 + 76.0, y0 + 57.6))
        t.col_widths = [19.0] * 4
        t.row_heights = [14.4] * 4
        t.rows = [[Cell(borders={"top": (0.4, "#000000")}) for _ in range(4)]
                  for _ in range(4)]
        return t

    def test_tables_on_one_band_join_with_their_label(self):
        grids = [self._grid(123.3 + 83.0 * i, 344.4) for i in range(5)]
        label = _ln("1", 95.7, 375.0, x1=101.6)
        consumed = set()
        out = I._merge_table_rows(list(grids), [TextBlock([label], label.bbox)], consumed)
        self.assertEqual(len(out), 1)
        t = out[0]
        self.assertEqual(len(t.rows), 4)
        # label column + 5 x 4 columns + 4 gutters
        self.assertEqual(len(t.col_widths), 1 + 20 + 4)
        self.assertIn(id(label), consumed)
        self.assertTrue(any(c.paras for c in (row[0] for row in t.rows)))

    def test_text_in_the_gutter_keeps_the_tables_apart(self):
        grids = [self._grid(123.3, 344.4), self._grid(300.0, 344.4)]
        note = _ln("note", 220.0, 370.0, x1=260.0)
        out = I._merge_table_rows(list(grids), [TextBlock([note], note.bbox)], set())
        self.assertEqual(len(out), 2)


if __name__ == "__main__":
    unittest.main()
