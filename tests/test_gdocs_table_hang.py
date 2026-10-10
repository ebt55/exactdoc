"""A table that hangs keeps its hang under the gdocs profile.

Word draws a table with its border out in the margin by the first cell's left
margin and its text on the column; inference records that as
`TableEl.hang_left`. The standard profile places the edge so; the gdocs
profile set the edge on the column, and in Google Docs every such table's
text landed the hang to the right (c3_tables +7.00pt on every line, x04, 01,
03, l1 likewise). Docs honours a negative table indent to the point, so the
gdocs table now stands at `left_indent - hang_left` (`_gdocs_table_hang`).

    python -m unittest tests.test_gdocs_table_hang
"""
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from docx import Document  # noqa: E402

from exactdoc.docxout import WriteCtx, _gdocs_table_hang, write_table  # noqa: E402
from exactdoc.layout import Cell, Para, Run, TableEl  # noqa: E402


def _table(hang=0.0, left=0.0):
    cell = lambda t: Cell(paras=[Para(runs=[Run(text=t, font="Helvetica", size=10.0,  # noqa: E731
                                                color="#000000")])], pad=(2.0, 7.0, 2.0, 7.0))
    t = TableEl(rows=[[cell("Region"), cell("Q1")], [cell("North"), cell("412")]],
                col_widths=[200.0, 100.0], left_indent=left, bbox=(61.5, 100, 361.5, 140))
    t.hang_left = hang
    return t


def _tbl_ind(t, profile):
    doc = Document()
    write_table(doc, t, 468.0, ctx=WriteCtx(output_profile=profile))
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.docx")
        doc.save(path)
        x = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    m = re.search(r'<w:tblInd w:w="(-?\d+)"', x)
    return int(m.group(1)) / 20 if m else None


class Hang(unittest.TestCase):
    def test_gdocs_table_hangs_by_its_hang(self):
        self.assertEqual(_tbl_ind(_table(hang=7.0), "gdocs"), -7.0)

    def test_an_indented_table_hangs_from_its_indent(self):
        self.assertEqual(_tbl_ind(_table(hang=5.5, left=36.0), "gdocs"), 30.5)

    def test_a_table_that_does_not_hang_keeps_its_place(self):
        self.assertIsNone(_tbl_ind(_table(), "gdocs"))
        self.assertEqual(_tbl_ind(_table(left=36.0), "gdocs"), 36.0)

    def test_only_the_gdocs_profile_reads_it(self):
        self.assertEqual(_gdocs_table_hang(_table(hang=7.0), WriteCtx()), 0.0)
        self.assertEqual(_gdocs_table_hang(_table(hang=7.0), WriteCtx(output_profile="gdocs")), 7.0)
        # the standard profile keeps its own edge (_lead_pad): the hang less the
        # 7pt lead pad that becomes its default cell margin, so no indent here
        self.assertIsNone(_tbl_ind(_table(hang=7.0), "standard"))


if __name__ == "__main__":
    unittest.main()
