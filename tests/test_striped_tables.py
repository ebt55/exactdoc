"""Contracts for the deliberately narrow regular striped-table assembler."""
import copy
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from exactdoc.backend import get_backend
from exactdoc.dialect import normalize
from exactdoc.docxout import write_docx
from exactdoc.infer import (_coalesce_striped_table_segments,
                            _regular_striped_table_segment, infer)
from exactdoc.layout import Cell, Chunk, DocLayout, PageLayout, Para, Run, TableEl
from exactdoc.model import DrawCmd, Line, Span, TextBlock


ROOT = Path(__file__).resolve().parents[1]
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _text(cell):
    return " ".join(p.text for p in cell.paras)


def _cell(text, bold=False):
    return Cell(paras=[Para(runs=[Run(text, "Helvetica", 10.0, "#000000", bold=bold)])])


def _table(rows, bbox=None):
    return TableEl(rows=rows, col_widths=[80.0, 120.0],
                   row_heights=[22.5] * len(rows), role="striped-table", bbox=bbox)


def _xml(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read("word/document.xml"))


def _frozen_c3_is_one_editable_table_and_continuations_are_suppressed():
    # This is the permissive PDFium candidate's Google Docs path, not a
    # PyMuPDF-only success.  The shipping parser shares the same inference.
    ir = get_backend("pdfium").parse_pdf(str(ROOT / "testkit/fixtures/c3_tables.pdf"),
                                          keep_image_data=True)
    lay = infer(normalize(ir))
    tables = [el for page in lay.pages for chunk in page.chunks
              for el in chunk.elements if isinstance(el, TableEl) and el.role == "striped-table"]
    assert len(tables) == 1
    table = tables[0]
    assert len(table.col_widths) == 4
    assert len(table.rows) == 46
    assert [_text(row[0]) for row in table.rows] == ["#"] + [str(i) for i in range(1, 46)]
    assert table.repeat_header_rows == 0
    assert all(row[0].shading is not None for row in table.rows[1::2])
    assert all(cell.borders.get("top") and cell.borders.get("bottom")
               for row in table.rows for cell in row)
    assert lay.pages[1].continuation_only and lay.pages[2].continuation_only
    # The regional/nested content that precedes the long table remains distinct.
    first_page_tables = [el for ch in lay.pages[0].chunks for el in ch.elements
                         if isinstance(el, TableEl)]
    assert len(first_page_tables) > 1

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "c3.docx"
        write_docx(lay, str(path), output_profile="standard")
        root = _xml(path)
        long_tables = [tbl for tbl in root.findall(".//" + W + "tbl")
                       if len(tbl.findall(W + "tr")) == 46]
        assert len(long_tables) == 1
        assert not long_tables[0].findall(".//" + W + "tblHeader")
        assert not root.findall(".//" + W + "br[@" + W + "type='page']")


def _only_an_actual_repeated_source_header_emits_tblheader():
    header = [_cell("ID", bold=True), _cell("Description", bold=True)]
    first = _table([header, [_cell("1"), _cell("first")]], (60.0, 700.0, 260.0, 750.0))
    second = _table([[copy.deepcopy(c) for c in header], [_cell("2"), _cell("second")]],
                    (60.0, 64.0, 260.0, 114.0))
    lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[first])]),
                           PageLayout(2, [Chunk(elements=[second])])])
    _coalesce_striped_table_segments(lay)
    assert lay.pages[1].continuation_only
    assert len(first.rows) == 3
    assert first.repeat_header_rows == 1
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "header.docx"
        write_docx(lay, str(path), output_profile="gdocs")
        root = _xml(path)
        headers = root.findall(".//" + W + "tblHeader")
        assert len(headers) == 1


def _line(text, x, y):
    span = Span(text, "Helvetica", 10.0, "#000000", False, False, False, False,
                False, (x, y, x + 12, y + 10), (x, y + 8))
    return Line([span], span.bbox)


def _regular_inputs(multiline=False, gapped=False):
    draws, lines = [], []
    x0, xmid, x1 = 60.0, 160.0, 260.0
    for ri in range(3):
        top, bottom = ri * 22.5, (ri + 1) * 22.5
        right = x1 + 8 if gapped else x1
        # Gapped tile rows model dashboard cards rather than a table.
        draws.extend([
            (len(draws), DrawCmd("fill", "rect", (x0, top, xmid, bottom), "#eef2f5", None, 0, 1, 1)),
            (len(draws) + 1, DrawCmd("fill", "rect", (xmid + (8 if gapped else 0), top, right, bottom), "#eef2f5", None, 0, 1, 1)),
        ])
        for x, text in ((x0 + 5, str(ri)), (xmid + 5, "value")):
            lines.append(_line(text, x, top + 5))
        if multiline and ri == 1:
            lines.append(_line("extra", x0 + 5, top + 12))
    for y in (0.0, 22.5, 45.0, 67.5):
        draws.append((len(draws), DrawCmd("fill", "hline", (x0, y, xmid, y + .5), "#d8dee5", None, 0, 1, 1)))
        draws.append((len(draws), DrawCmd("fill", "hline", (xmid, y, x1, y + .5), "#d8dee5", None, 0, 1, 1)))
    return draws, [TextBlock(lines, (x0, 0, x1, 67.5))]


def _ambiguous_multiline_cards_and_mismatched_continuations_are_not_claimed():
    good_draws, blocks = _regular_inputs(multiline=True)
    assert _regular_striped_table_segment(good_draws, blocks, set()) is None
    card_draws, blocks = _regular_inputs(gapped=True)
    assert _regular_striped_table_segment(card_draws, blocks, set()) is None
    # Three one-column callout bands are not a table, even when regular.
    callouts = [(i, DrawCmd("fill", "rect", (60.0, i * 22.5, 260.0, (i + 1) * 22.5),
                            "#eef2f5", None, 0, 1, 1)) for i in range(3)]
    assert _regular_striped_table_segment(callouts, blocks, set()) is None
    # A shifted continuation may be independently table-like, but never joins
    # the predecessor or suppresses a source-page break.
    first = _table([[_cell("1"), _cell("first")]], (60.0, 200.0, 260.0, 222.5))
    shifted = _table([[_cell("2"), _cell("second")]], (64.0, 64.0, 264.0, 86.5))
    shifted.col_widths = [84.0, 120.0]
    lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[first])]),
                           PageLayout(2, [Chunk(elements=[shifted])])])
    _coalesce_striped_table_segments(lay)
    assert not lay.pages[1].continuation_only
    assert len(first.rows) == 1 and len(shifted.rows) == 1
    # Same widths and x boundaries alone are insufficient: two independent
    # tables that do not run to the prior page's bottom must keep their break.
    independent = _table([[_cell("3"), _cell("unrelated")]], (60.0, 64.0, 260.0, 86.5))
    lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[first])]),
                           PageLayout(2, [Chunk(elements=[independent])])])
    _coalesce_striped_table_segments(lay)
    assert not lay.pages[1].continuation_only
    assert len(first.rows) == 1 and len(independent.rows) == 1


class StripedTableAssemblerTests(unittest.TestCase):
    def test_frozen_c3_is_one_editable_table_and_continuations_are_suppressed(self):
        _frozen_c3_is_one_editable_table_and_continuations_are_suppressed()

    def test_only_an_actual_repeated_source_header_emits_tblheader(self):
        _only_an_actual_repeated_source_header_emits_tblheader()

    def test_ambiguous_multiline_cards_and_mismatched_continuations_are_not_claimed(self):
        _ambiguous_multiline_cards_and_mismatched_continuations_are_not_claimed()


if __name__ == "__main__":
    unittest.main()
