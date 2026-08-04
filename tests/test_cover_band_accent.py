"""A cover block's accent stripe, and the construct each target needs.

01_whitepaper's cover block is two fills: navy 0..170 and a 4pt orange rule
flush beneath it. Inference records the thin one as a bottom border on the band
cell, which is faithful -- LibreOffice renders it at the right colour and
thickness. Google Docs does not: the stripe is absent from every Docs render
across live passes 2, 3 and 4, while the navy block above it -- `w:shd` cell
shading on the same cell -- comes back every time.

So the border stays as the representation, and the gdocs writer re-expresses it
as a second shaded row, trading a construct Docs drops for one it demonstrably
honours. The standard profile keeps the border and is byte-identical.

The thresholds refuse a second SUBSTANTIAL fill, which is a second band rather
than a stripe. The absolute bound comes from the format: OOXML stores border
width in eighths of a point capped at 96, so a stripe over 12pt cannot be a
border at all. The corpus's only two real accents are 4.0pt (2.4% of its band)
and 8.0pt (6.2%), so 8pt is a genuine accent and the rule has to admit it.
"""
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from exactdoc.docxout import (WriteCtx, _band_accent_as_row, write_docx,
                              write_table)
from exactdoc.infer import ACCENT_MAX_FRAC, ACCENT_MAX_PT, build_band_table
from exactdoc.layout import Cell, Chunk, DocLayout, PageLayout, Para, Run, TableEl
from exactdoc.model import DrawCmd

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NAVY, ORANGE = "#1e3a5f", "#f59e0b"


def _fill(y0, y1, color, x0=0.0, x1=612.0):
    return DrawCmd(kind="fill", shape="rect", bbox=(x0, y0, x1, y1), fill=color,
                   stroke=None, width=0.0, opacity=1.0, n_items=1)


def _band(*fills):
    return list(enumerate(fills))


def _borders_for(*fills):
    t = build_band_table(_band(*fills), [], 0.0, 612.0, {})
    return t.rows[0][0].borders


class AccentRule(unittest.TestCase):
    def test_thin_fill_flush_below_becomes_a_bottom_stripe(self):
        b = _borders_for(_fill(0, 170, NAVY), _fill(170, 174, ORANGE))
        self.assertEqual(b.get("bottom"), (4.0, ORANGE))

    def test_thin_fill_flush_above_becomes_a_top_stripe(self):
        b = _borders_for(_fill(4, 174, NAVY), _fill(0, 4, ORANGE))
        self.assertEqual(b.get("top"), (4.0, ORANGE))

    def test_an_eight_point_stripe_is_still_an_accent(self):
        # 04_exec_brief's real geometry: 8.0pt against a 130pt band
        b = _borders_for(_fill(0, 130, NAVY), _fill(130, 138, ORANGE))
        self.assertEqual(b.get("bottom"), (8.0, ORANGE))


class AccentRefusals(unittest.TestCase):
    def test_a_second_large_fill_is_not_a_stripe(self):
        # 60pt against a 170pt band is 35%, over ACCENT_MAX_FRAC
        b = _borders_for(_fill(0, 170, NAVY), _fill(170, 230, ORANGE))
        self.assertEqual(b, {})

    def test_a_stripe_too_thick_to_be_a_border_is_refused(self):
        # 14pt passes the fraction test against a 600pt band but cannot be
        # expressed: OOXML caps border width at 96 eighths, i.e. 12pt
        self.assertLess(14.0 / 600.0, ACCENT_MAX_FRAC)
        b = _borders_for(_fill(0, 600, NAVY), _fill(600, 614, ORANGE))
        self.assertEqual(b, {})

    def test_the_absolute_bound_matches_the_ooxml_cap(self):
        self.assertLessEqual(ACCENT_MAX_PT, 96 / 8.0)

    def test_a_fill_that_is_not_flush_is_not_a_stripe(self):
        # sitting well inside the band, not against either edge
        b = _borders_for(_fill(0, 170, NAVY), _fill(80, 84, ORANGE))
        self.assertEqual(b, {})


def _band_table(thickness=4.0, color=ORANGE, height=174.0):
    cell = Cell(shading=NAVY, borders={"bottom": (thickness, color)},
                paras=[Para(runs=[Run(text="Title", font="Helvetica", size=20,
                                      color="#ffffff")])])
    return TableEl(rows=[[cell]], col_widths=[612.0], row_heights=[height],
                   role="band")


class AccentAsRow(unittest.TestCase):
    def test_border_becomes_a_shaded_row(self):
        out = _band_accent_as_row(_band_table())
        self.assertEqual(len(out.rows), 2)
        self.assertEqual(out.rows[1][0].shading, ORANGE)
        self.assertEqual(out.row_heights, [170.0, 4.0])

    def test_the_border_is_dropped_so_it_cannot_render_twice(self):
        out = _band_accent_as_row(_band_table())
        self.assertNotIn("bottom", out.rows[0][0].borders)

    def test_a_band_without_an_accent_is_untouched(self):
        t = TableEl(rows=[[Cell(shading=NAVY, borders={})]], col_widths=[612.0],
                    row_heights=[174.0], role="band")
        self.assertIs(_band_accent_as_row(t), t)

    def test_a_multi_row_table_is_untouched(self):
        t = TableEl(rows=[[Cell(shading=NAVY, borders={"bottom": (4.0, ORANGE)})],
                          [Cell(shading=NAVY, borders={})]],
                    col_widths=[612.0], row_heights=[100.0, 74.0], role="band")
        self.assertIs(_band_accent_as_row(t), t)


def _cover_layout():
    band = _band_table()
    return DocLayout(cover_band=band, cover_top=0.0,
                     pages=[PageLayout(1, [Chunk(elements=[
                         Para(runs=[Run(text="body", font="Helvetica", size=10,
                                        color="#000000")])])])])


def _rows_of(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    tbl = root.find(".//" + W + "tbl")
    out = []
    for tr in tbl.findall(W + "tr"):
        tc = tr.find(W + "tc")
        shd = tc.find(".//" + W + "shd")
        bord = tc.find(".//" + W + "tcBorders")
        bottom = None
        if bord is not None:
            b = bord.find(W + "bottom")
            if b is not None and b.get(W + "val") != "nil":
                bottom = (b.get(W + "sz"), b.get(W + "color"))
        out.append((shd.get(W + "fill") if shd is not None else None, bottom))
    return out


class ProfileScoping(unittest.TestCase):
    def test_gdocs_emits_the_stripe_as_a_row_and_standard_keeps_the_border(self):
        with tempfile.TemporaryDirectory() as td:
            std = Path(td) / "standard.docx"
            gd = Path(td) / "gdocs.docx"
            write_docx(_cover_layout(), str(std), output_profile="standard")
            write_docx(_cover_layout(), str(gd), output_profile="gdocs")

            std_rows = _rows_of(std)
            self.assertEqual(len(std_rows), 1)
            self.assertEqual(std_rows[0][1], ("32", "F59E0B"))  # 32/8 = 4.0pt

            gd_rows = _rows_of(gd)
            self.assertEqual(len(gd_rows), 2)
            self.assertIsNone(gd_rows[0][1], "gdocs must not keep the border")
            self.assertEqual(gd_rows[1][0], "F59E0B")

    def test_an_ordinary_band_is_not_given_the_cover_treatment(self):
        # write_table only splits when told this is the cover band
        t = _band_table()
        with tempfile.TemporaryDirectory() as td:
            from docx import Document
            doc = Document()
            write_table(doc, t, 612.0, ctx=WriteCtx(output_profile="gdocs"),
                        cover_band=False)
            path = Path(td) / "plain.docx"
            doc.save(str(path))
            self.assertEqual(len(_rows_of(path)), 1)


if __name__ == "__main__":
    unittest.main()
