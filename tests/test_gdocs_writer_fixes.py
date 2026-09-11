"""Narrow OOXML contracts for the Google Docs writer profile."""
import base64
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from docx import Document

from exactdoc.docxout import WriteCtx, write_docx, write_figure, write_para, write_table
from exactdoc.infer import para_from_lines
from exactdoc.layout import (Cell, Chunk, DocLayout, FigureEl, PageLayout,
                             Para, Run, TableEl)
from exactdoc.model import Line, Span


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _xml(docx_path):
    with zipfile.ZipFile(docx_path) as z:
        return ET.fromstring(z.read("word/document.xml"))


def _run(text, size=12.0):
    return Run(text=text, font="Helvetica", size=size, color="#000000")


def _cover_layout():
    band = TableEl(
        rows=[[Cell(paras=[Para(runs=[_run("Cover title")], space_before=20.0,
                                 left_indent=30.0),
                            Para(runs=[_run("Cover subtitle")], space_before=4.0)],
                    pad=(0.0, 30.0, 0.0, 0.0))]],
        col_widths=[604.0], row_heights=[150.0], role="band",
    )
    return DocLayout(cover_band=band, cover_top=0.0,
                     pages=[PageLayout(1, [Chunk(elements=[Para(runs=[_run("body")])])])])


def _first_table_values(docx_path):
    root = _xml(docx_path)
    tbl = root.find(".//" + W + "tbl")
    tc = tbl.find(".//" + W + "tc")
    mar_left = tc.find(".//" + W + "tcMar/" + W + "left").get(W + "w")
    par = tc.find(W + "p")
    spacing = par.find(".//" + W + "spacing")
    ind = par.find(".//" + W + "ind")
    return mar_left, spacing.get(W + "before"), None if ind is None else ind.get(W + "left")


class GoogleDocsWriterFixes(unittest.TestCase):
    def test_gdocs_cover_moves_left_padding_and_compensates_first_before(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            standard = tmp_path / "standard.docx"
            gdocs = tmp_path / "gdocs.docx"
            write_docx(_cover_layout(), str(standard), output_profile="standard")
            write_docx(_cover_layout(), str(gdocs), output_profile="gdocs")

            # Standard preserves the original cell-padding form.  Google Docs receives
            # the same horizontal position as paragraph indentation, less the space
            # Docs adds above a page-leading band.
            #
            # Both gdocs numbers moved when live pass 2 measured the band:
            #   before 400 - 296 = 104 twips.  The compensation was 290 (14.5pt);
            #   the probe measured Docs adding 14.8pt, as an ADDITION at every
            #   requested top margin rather than a clamp.
            #   indent 1960 -> 2040.  The gdocs band now asks for a zero side
            #   margin instead of 4pt, because the probe measured Docs honouring
            #   side margins exactly, so the 4pt white frame down each edge of
            #   every cover page was ours and not Google's.  Page-one elements are
            #   shifted by the full margin to keep their x, hence 80 more twips.
            self.assertEqual(_first_table_values(standard), ("1960", "400", None))
            self.assertEqual(_first_table_values(gdocs), ("0", "104", "2040"))


    def test_gdocs_moves_left_padding_for_ordinary_tables_too(self):
        # Google ignores tcMar/left on ordinary cells as well: the c7_code
        # Google evidence shows dx_p50 tracking the code cell's tcMar left
        # (~10.7pt) while the LibreOffice proxy sits at 0.25pt.  The gdocs
        # profile therefore relocates every cell's left pad to its
        # paragraphs; standard keeps the tcMar form.
        with tempfile.TemporaryDirectory() as td:
            table = TableEl(rows=[[Cell(paras=[Para(runs=[_run("ordinary")], space_before=20.0)],
                                        pad=(0.0, 30.0, 0.0, 0.0))]], col_widths=[200.0])
            doc = Document()
            write_table(doc, table, 200.0, ctx=WriteCtx(output_profile="gdocs"))
            path = Path(td) / "ordinary.docx"
            doc.save(path)
            self.assertEqual(_first_table_values(path), ("0", "400", "600"))

            standard_doc = Document()
            write_table(standard_doc, table, 200.0,
                        ctx=WriteCtx(output_profile="standard"))
            standard_path = Path(td) / "ordinary-standard.docx"
            standard_doc.save(standard_path)
            self.assertEqual(_first_table_values(standard_path),
                             ("600", "400", None))

    def test_gdocs_emits_paragraph_spacing_verbatim(self):
        # Google Docs adds nothing of its own at a paragraph boundary, so the
        # gdocs profile must emit space_before exactly as inferred.
        #
        # This profile used to subtract 3.0pt per boundary here.  Measured
        # against Google's own exports on 2026-08-04, Docs' contribution is
        # A = +0.10pt (95% CI [+0.04, +0.21], n=187 single-column boundaries):
        # it honoured the subtraction and gave nothing back, so the space was
        # simply lost, once per boundary, accumulating down every page --
        # c6_long alone carries 17.4 boundaries per page and drifted 25.84pt
        # upward.  Both profiles now emit the same spacing; see the provenance
        # comment in exactdoc/docxout.py.
        def _layout():
            return DocLayout(pages=[PageLayout(1, [Chunk(elements=[
                Para(runs=[_run("first")], space_before=20.0),
                Para(runs=[_run("second")], space_before=20.0),
                Para(runs=[_run("third")], space_before=1.0),
            ])])])
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            standard = tmp_path / "standard.docx"
            gdocs = tmp_path / "gdocs.docx"
            write_docx(_layout(), str(standard), output_profile="standard")
            write_docx(_layout(), str(gdocs), output_profile="gdocs")

            def befores(path):
                root = _xml(path)
                out = []
                for par in root.findall(".//" + W + "p"):
                    sp = par.find(".//" + W + "spacing")
                    if par.findall(".//" + W + "t"):
                        out.append(None if sp is None else sp.get(W + "before"))
                return out

            self.assertEqual(befores(standard), ["400", "400", "20"])
            self.assertEqual(befores(gdocs), ["400", "400", "20"])

    def test_gdocs_cover_retains_a_source_indent_beyond_cell_padding(self):
        table = TableEl(
            rows=[[Cell(paras=[Para(runs=[_run("offset cover")], left_indent=48.0)],
                        pad=(0.0, 30.0, 0.0, 0.0))]],
            col_widths=[200.0], role="band",
        )
        with tempfile.TemporaryDirectory() as td:
            doc = Document()
            write_table(doc, table, 200.0, ctx=WriteCtx(output_profile="gdocs"),
                        cover_band=True)
            path = Path(td) / "offset-cover.docx"
            doc.save(path)
            _, _, indent = _first_table_values(path)
            self.assertEqual(indent, "960")


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL9xQAAAABJRU5ErkJggg=="
)


def _figure_spacing(tmp_path, profile):
    doc = Document()
    fig = FigureEl(page_no=1, clip=(0, 0, 1, 1), width=20, height=40)
    write_figure(doc, fig, ctx=WriteCtx(output_profile=profile,
                                         render_clip=lambda *_: _PNG))
    path = tmp_path / (profile + ".docx")
    doc.save(path)
    return _xml(path).find(".//" + W + "pPr/" + W + "spacing")


def _line(text, width, baseline):
    span = Span(text=text, font="Helvetica", size=12.0, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=(0.0, baseline - 10, width, baseline),
                origin=(0.0, baseline))
    return Line(spans=[span], bbox=span.bbox)


class GoogleDocsInferenceFixes(unittest.TestCase):
    def test_gdocs_inline_figure_omits_redundant_atleast_height(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            standard = _figure_spacing(tmp_path, "standard")
            gdocs = _figure_spacing(tmp_path, "gdocs")
            self.assertEqual(standard.get(W + "lineRule"), "atLeast")
            self.assertEqual(standard.get(W + "line"), "800")
            self.assertIsNone(gdocs.get(W + "lineRule"))
            self.assertIsNone(gdocs.get(W + "line"))

    def test_metadata_rows_are_preserved_only_when_inset_is_impossible(self):
        metadata = para_from_lines([
            _line("From: Operations", 77.8, 100),
            _line("To: All team leads", 80.0, 115),
            _line("Date: July 21, 2026", 86.2, 130),
        ], 0.0, 500.0)
        # Inference retains the standard flowing form and records a Google-only
        # row representation.  The writer is where that alternate form applies.
        self.assertEqual(metadata.align, "justify")
        self.assertEqual(metadata.right_indent, 420.0)
        self.assertFalse(metadata.line_breaks)
        self.assertEqual(len(metadata.gdocs_rows), 3)
        with tempfile.TemporaryDirectory() as td:
            standard_doc = Document()
            write_para(standard_doc, metadata, 500.0,
                       ctx=WriteCtx(output_profile="standard"))
            standard_path = Path(td) / "metadata-standard.docx"
            standard_doc.save(standard_path)
            standard_xml = _xml(standard_path)
            standard_ppr = standard_xml.find(".//" + W + "pPr")
            self.assertEqual(standard_ppr.find(W + "jc").get(W + "val"), "both")
            self.assertEqual(standard_ppr.find(W + "ind").get(W + "right"), "8400")
            self.assertEqual(len(standard_xml.findall(".//" + W + "br")), 0)

            gdocs_doc = Document()
            write_para(gdocs_doc, metadata, 500.0, ctx=WriteCtx(output_profile="gdocs"))
            gdocs_path = Path(td) / "metadata-gdocs.docx"
            gdocs_doc.save(gdocs_path)
            gdocs_xml = _xml(gdocs_path)
            gdocs_ppr = gdocs_xml.find(".//" + W + "pPr")
            self.assertEqual(gdocs_ppr.find(W + "jc").get(W + "val"), "left")
            self.assertIsNone(gdocs_ppr.find(W + "ind"))
            self.assertEqual(len(gdocs_xml.findall(".//" + W + "br")), 2)

        ordinary = para_from_lines([
            _line("A justified line", 100.0, 100),
            _line("Another justified line", 100.0, 115),
            _line("ragged last line", 60.0, 130),
        ], 0.0, 500.0)
        self.assertEqual(ordinary.align, "justify")
        self.assertEqual(ordinary.right_indent, 400.0)
        self.assertFalse(ordinary.line_breaks)
        self.assertNotIn("\n", ordinary.text)


class RightAlignedCellIndent(unittest.TestCase):
    """A right/centre-aligned cell line's source x is POSITION, and jc
    already places it. Kept as w:ind it consumes wrap width -- measured
    live: Docs wrapped '28/60' (22.4pt Georgia 8) in a 29.75pt cell whose
    paragraph carried ind left=254tw, leaving 17pt of line. The mid-token
    breaks the cw2 class was named for were this double-encoding."""

    def _cell(self, align, indent):
        p = Para(runs=[_run("28/60")], left_indent=indent)
        p.align = align
        return TableEl(rows=[[Cell(paras=[p], pad=(0.0, 0.0, 0.0, 0.25))]],
                       col_widths=[30.0], row_heights=[12.0])

    def _ind_and_jc(self, docx_path):
        root = _xml(docx_path)
        par = root.find(".//" + W + "tbl/" + W + "tr/" + W + "tc/" + W + "p")
        ind = par.find(W + "pPr/" + W + "ind")
        jc = par.find(W + "pPr/" + W + "jc")
        return (None if ind is None else ind.get(W + "left"),
                None if jc is None else jc.get(W + "val"))

    def test_right_aligned_loses_the_positional_indent(self):
        with tempfile.TemporaryDirectory() as td:
            doc = Document()
            write_table(doc, self._cell("right", 12.7), 30.0,
                        ctx=WriteCtx(output_profile="gdocs"))
            path = Path(td) / "r.docx"
            doc.save(path)
            ind, jc = self._ind_and_jc(path)
            self.assertEqual(jc, "right")
            self.assertIn(ind, (None, "0"),
                          "the wrap width must keep the full cell width")

    def test_center_aligned_loses_the_positional_indent(self):
        with tempfile.TemporaryDirectory() as td:
            doc = Document()
            write_table(doc, self._cell("center", 9.0), 30.0,
                        ctx=WriteCtx(output_profile="gdocs"))
            path = Path(td) / "c.docx"
            doc.save(path)
            ind, jc = self._ind_and_jc(path)
            self.assertEqual(jc, "center")
            self.assertIn(ind, (None, "0"))

    def test_left_aligned_keeps_its_indent(self):
        # for jc=left the indent IS the position -- it stays
        with tempfile.TemporaryDirectory() as td:
            doc = Document()
            write_table(doc, self._cell("left", 12.7), 30.0,
                        ctx=WriteCtx(output_profile="gdocs"))
            path = Path(td) / "l.docx"
            doc.save(path)
            ind, _ = self._ind_and_jc(path)
            self.assertEqual(ind, "254")

    def test_standard_profile_keeps_the_indent_everywhere(self):
        # the gated lanes render the indented form fine (LibreOffice does
        # not consume it the way Docs does); their behaviour is untouched
        with tempfile.TemporaryDirectory() as td:
            doc = Document()
            write_table(doc, self._cell("right", 12.7), 30.0,
                        ctx=WriteCtx(output_profile="standard"))
            path = Path(td) / "s.docx"
            doc.save(path)
            ind, _ = self._ind_and_jc(path)
            self.assertEqual(ind, "254",
                             "standard keeps indent - pad (pad is 0 here)")

    def test_left_indent_bracketed_under_the_texts_own_width(self):
        # jc=left keeps its position -- but never past the wrap bracket:
        # '35/60' at ~22.4pt of Georgia in a 30pt cell could not carry its
        # measured 10.4pt source indent (19.35pt of line) without breaking
        # mid-token. The emitted indent caps so the text's own width fits.
        p = Para(runs=[_run("35/60", size=8.0)], left_indent=10.4)
        p.src_lines = 1
        p.src_widths = [21.7]   # the source drew the token 21.7pt wide
        table = TableEl(rows=[[Cell(paras=[p], pad=(0.0, 0.0, 0.0, 0.25))]],
                        col_widths=[30.0], row_heights=[12.0])
        with tempfile.TemporaryDirectory() as td:
            doc = Document()
            write_table(doc, table, 30.0, ctx=WriteCtx(output_profile="gdocs"))
            path = Path(td) / "b.docx"
            doc.save(path)
            ind, _ = self._ind_and_jc(path)
            self.assertLessEqual(int(ind), 75,
                                 "the indent must leave the text's own "
                                 "width (21.7pt x1.15 + 1pt) inside the "
                                 "30pt cell: cap is 3.75pt = 75tw")
            self.assertGreaterEqual(int(ind), 0)
