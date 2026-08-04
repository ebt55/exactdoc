"""The continuous section break's own paragraph, and who pays for it.

A continuous section break is carried by a real paragraph, and that paragraph
occupies flow height the source page never spent. Measured on c2_paper2col
through the canonical LibreOffice: its advance is exactly its w:line with a
floor near 1pt -- raising w:line from 20 twips to 400 moved every following
line down by 19.00pt, and dropping it to 1 twip moved nothing. It cannot be
removed, so the gap hoisted ahead of it is emitted that much shorter instead.

The compensation is gdocs-only, and that is a deliberate scoping rather than a
convenience. The standard profile ships with the LibreOffice correction loop,
which has already absorbed this 1pt empirically: correcting it at source as
well made the loop over-correct, measurably -- c2's product-lane mean_ssim fell
0.824 -> 0.793 and its dy_p50 went 0.85 -> 1.75. The gdocs profile ships with
no loop and is the static-translation layer for exactly this kind of
correction.

So these tests assert both halves: the delta appears under gdocs, and standard
is untouched.
"""
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from exactdoc.docxout import (SECT_BREAK_PARA_PT, SECT_BREAK_PARA_TWIPS,
                              WriteCtx, _sect_break_comp, write_docx)
from exactdoc.layout import Chunk, ColBreak, DocLayout, PageLayout, Para, Run

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PRE_GAP = 13.7


def _run(text, size=12.0):
    return Run(text=text, font="Helvetica", size=size, color="#000000")


def _two_column_layout():
    """A one-column lead followed by a two-column chunk with a hoisted gap."""
    lead = Chunk(n_cols=1, elements=[Para(runs=[_run("Abstract text")])])
    cols = Chunk(n_cols=2, col_gap=24.0, pre_gap=PRE_GAP,
                 elements=[Para(runs=[_run("1 Introduction")]),
                           ColBreak(),
                           Para(runs=[_run("second column")])])
    return DocLayout(pages=[PageLayout(1, [lead, cols])])


def _spacers_before_section_breaks(path):
    """Exact line heights (pt) of paragraphs that immediately precede a sectPr."""
    with zipfile.ZipFile(path) as z:
        body = ET.fromstring(z.read("word/document.xml")).find(W + "body")
    paras = body.findall(W + "p")
    out = []
    for i, p in enumerate(paras):
        ppr = p.find(W + "pPr")
        if ppr is None or ppr.find(W + "sectPr") is None or i == 0:
            continue
        prev_ppr = paras[i - 1].find(W + "pPr")
        if prev_ppr is None:
            continue
        sp = prev_ppr.find(W + "spacing")
        if sp is not None and sp.get(W + "lineRule") == "exact" and sp.get(W + "line"):
            out.append(int(sp.get(W + "line")) / 20.0)
    return out


def _section_break_line_heights(path):
    """Exact line heights (pt) of the section-break paragraphs themselves."""
    with zipfile.ZipFile(path) as z:
        body = ET.fromstring(z.read("word/document.xml")).find(W + "body")
    out = []
    for p in body.findall(W + "p"):
        ppr = p.find(W + "pPr")
        if ppr is None or ppr.find(W + "sectPr") is None:
            continue
        sp = ppr.find(W + "spacing")
        if sp is not None and sp.get(W + "line"):
            out.append(int(sp.get(W + "line")) / 20.0)
    return out


def _write_both():
    td = tempfile.mkdtemp()
    std = Path(td) / "standard.docx"
    gd = Path(td) / "gdocs.docx"
    write_docx(_two_column_layout(), str(std), output_profile="standard")
    write_docx(_two_column_layout(), str(gd), output_profile="gdocs")
    return std, gd


class Compensation(unittest.TestCase):
    def test_gdocs_shortens_the_hoisted_gap_by_one_paragraph(self):
        std, gd = _write_both()
        self.assertEqual(_spacers_before_section_breaks(std), [PRE_GAP])
        self.assertEqual(_spacers_before_section_breaks(gd),
                         [round(PRE_GAP - SECT_BREAK_PARA_PT, 1)])

    def test_the_delta_is_exactly_the_section_break_paragraph(self):
        std, gd = _write_both()
        delta = _spacers_before_section_breaks(std)[0] - \
            _spacers_before_section_breaks(gd)[0]
        self.assertAlmostEqual(delta, SECT_BREAK_PARA_PT, places=6)
        self.assertAlmostEqual(delta, 1.0, places=6)

    def test_standard_is_untouched(self):
        std, _ = _write_both()
        self.assertEqual(_spacers_before_section_breaks(std), [PRE_GAP],
                         "the shipping profile's loop already absorbs this 1pt; "
                         "correcting it here too made the loop over-correct")


class SectionBreakParagraph(unittest.TestCase):
    def test_it_is_emitted_at_the_measured_floor_in_both_profiles(self):
        std, gd = _write_both()
        for path in (std, gd):
            self.assertEqual(_section_break_line_heights(path),
                             [SECT_BREAK_PARA_PT])

    def test_the_constant_and_the_emitted_twips_agree(self):
        # the compensation and the paragraph it compensates for must not drift
        self.assertAlmostEqual(SECT_BREAK_PARA_PT,
                               SECT_BREAK_PARA_TWIPS / 20.0, places=6)


class Scoping(unittest.TestCase):
    def test_only_the_gdocs_profile_compensates(self):
        self.assertEqual(_sect_break_comp(WriteCtx(output_profile="gdocs")),
                         SECT_BREAK_PARA_PT)
        self.assertEqual(_sect_break_comp(WriteCtx(output_profile="standard")),
                         0.0)

    def test_an_unknown_profile_does_not_compensate(self):
        self.assertEqual(_sect_break_comp(WriteCtx(output_profile="")), 0.0)


if __name__ == "__main__":
    unittest.main()
