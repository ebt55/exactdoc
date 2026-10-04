"""Writer contracts from live Google Docs pass 8 (2026-10-04).

Pass 8 failed three ordinary documents that pass 7 had cleared. Each defect
was bisected to a commit and its fix verified on Google's own export; these
tests pin the OOXML each fix depends on.

- 04_exec_brief / c1_whitepaper: the gdocs row pin (trHeight atLeast = source
  height) belongs to DATA tables. On a cover band or a stat-card row the pads
  already sum to the source height and the pin moved the page 6-11pt (dy_p50
  13.24 / 11.56 against pass 7's 2.43 / 5.56).
- c6_long: a heading at the bottom of a source page keeps-with-next onto a
  paragraph that opens the next page with pageBreakBefore, so the keep strands
  the heading on a page of its own (7 -> 8 pages, word recall 0.82).
- 04_exec_brief: a quote block narrower than its column wraps at its own right
  edge, not the column's (one line too few, dy_p90 38pt).
"""
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from exactdoc.docxout import write_docx
from exactdoc.layout import Cell, Chunk, DocLayout, PageLayout, Para, Run, TableEl


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _run(text, size=11.0):
    return Run(text=text, font="Helvetica", size=size, color="#000000")


def _doc(path, lay, profile="gdocs"):
    write_docx(lay, str(path), output_profile=profile)
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read("word/document.xml"))


def _one_page(*elements):
    return DocLayout(pages=[PageLayout(1, [Chunk(elements=list(elements))])])


def _table(role, height=60.0):
    return TableEl(rows=[[Cell(paras=[Para(runs=[_run("73%")])],
                               pad=(20.0, 4.0, 20.0, 4.0))]],
                   col_widths=[150.0], row_heights=[height], role=role)


class RowPinIsForDataTables(unittest.TestCase):
    def _pins(self, role):
        with tempfile.TemporaryDirectory() as td:
            root = _doc(Path(td) / "t.docx", _one_page(_table(role)))
        return root.findall(".//" + W + "trHeight")

    def test_a_data_table_row_is_pinned(self):
        self.assertEqual(len(self._pins("table")), 1)

    def test_band_and_card_rows_are_content_driven(self):
        for role in ("band", "cards"):
            self.assertEqual(self._pins(role), [], role)

    def test_standard_profile_never_pins_a_text_row(self):
        with tempfile.TemporaryDirectory() as td:
            root = _doc(Path(td) / "t.docx", _one_page(_table("table")),
                        profile="standard")
        self.assertEqual(root.findall(".//" + W + "trHeight"), [])


class KeepIsReleasedBeforeASeam(unittest.TestCase):
    def _layout(self):
        heading = Para(runs=[_run("12. Section heading", 14.0)], heading=2)
        body1 = Para(runs=[_run("body on page one")])
        body2 = Para(runs=[_run("body on page two")])
        return DocLayout(pages=[PageLayout(1, [Chunk(elements=[body1, heading])]),
                                PageLayout(2, [Chunk(elements=[body2])])])

    def test_the_heading_before_a_page_break_does_not_keep_with_next(self):
        for profile in ("gdocs", "standard"):
            with tempfile.TemporaryDirectory() as td:
                root = _doc(Path(td) / "k.docx", self._layout(), profile)
            paras = root.find(W + "body").findall(W + "p")
            seam = [i for i, p in enumerate(paras)
                    if p.find(".//" + W + "pageBreakBefore") is not None]
            self.assertTrue(seam, profile)
            before = paras[seam[0] - 1]
            keep = before.find(".//" + W + "keepNext")
            self.assertIsNotNone(keep, profile)
            self.assertEqual(keep.get(W + "val"), "0", profile)

    def test_a_keep_away_from_seams_is_untouched(self):
        heading = Para(runs=[_run("Heading", 14.0)], heading=2)
        body = Para(runs=[_run("its body")])
        with tempfile.TemporaryDirectory() as td:
            root = _doc(Path(td) / "k.docx", _one_page(heading, body))
        for keep in root.iter(W + "keepNext"):
            self.assertNotEqual(keep.get(W + "val"), "0")


class QuoteWrapsAtItsOwnEdge(unittest.TestCase):
    def test_a_narrow_quote_carries_its_right_inset(self):
        quote = TableEl(rows=[[Cell(paras=[Para(runs=[_run("quoted text")])],
                                    pad=(0.5, 14.0, 0.5, 2.0),
                                    borders={"left": (1.5, "#7c3aed")})]],
                        col_widths=[400.0], row_heights=[None], role="quote")
        lay = _one_page(quote)
        lay.page_w, lay.margin_l, lay.margin_r = 612.0, 72.0, 72.0
        with tempfile.TemporaryDirectory() as td:
            root = _doc(Path(td) / "q.docx", lay)
        ind = root.find(".//" + W + "p/" + W + "pPr/" + W + "ind")
        self.assertIsNotNone(ind)
        # column 468pt, block 400pt, right pad 2pt -> 70pt = 1400 twips
        self.assertEqual(int(ind.get(W + "right")), 1400)


if __name__ == "__main__":
    unittest.main()
