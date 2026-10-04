"""A refined page seam keeps the page-top gap of a non-paragraph element (B23).

Every source page ends in a hard break. A paragraph carries it as
pageBreakBefore; anything else gets a 1pt `w:br type=page` carrier in front of
it. LibreOffice drops the space_before of the first paragraph after such a
carrier and keeps it under pageBreakBefore -- the audit's probe put a marker at
83.2pt after a carrier against 183.2 under pageBreakBefore, and the canonical
container reproduces it through this writer (a rule opening page 2 with a
100pt gap: marker 84.6pt with the carrier, 184.6 with the break on the rule).
So the whole page sat one gap too high, and the refine loop could not correct
it: the gap it added was the very property being dropped.

Figures, images and rules are paragraphs, and a table with a page-top gap opens
with a spacer paragraph, so the break can ride on that paragraph. Whether it
does is `PageLayout.top_gap_fits`, which only the refine loop sets: open-loop,
the dropped gap measured as slack covering inflation elsewhere (y17 +3 pages,
y27 +2, y03 +3 when kept), so an open-loop write keeps the carrier exactly as
it shipped. A table with no leading gap keeps it too -- nothing to drop -- and
so does a page whose own stack does not fit its box with the gap.
"""
import os
import re
import tempfile
import unittest
import zipfile

from exactdoc.docxout import write_docx
from exactdoc.layout import (Cell, Chunk, DocLayout, FigureEl, PageLayout,
                             Para, RuleEl, Run, TableEl)
from exactdoc.refine import _freeze_seams


def _para(text, before=0.0):
    return Para(runs=[Run(text=text, font="Helvetica", size=11.0,
                          color="#000000")],
                leading=14.0, space_before=before, src_lines=1)


def _lay(first_el):
    return DocLayout(pages=[
        PageLayout(number=1, chunks=[Chunk(elements=[_para("Page one")])]),
        PageLayout(number=2, chunks=[Chunk(elements=[
            first_el, _para("MARKER second page", 6.0)])])])


def _write(lay):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "o.docx")
        write_docx(lay, path)
        with zipfile.ZipFile(path) as z:
            return z.read("word/document.xml").decode("utf-8")


def _xml(first_el, refined=True):
    """The document XML; `refined` applies the loop's seam decision first."""
    lay = _lay(first_el)
    if refined:
        _freeze_seams(lay)
    return _write(lay)


def _rule(gap=100.0):
    return RuleEl(width_pct=100.0, thickness=1.0, color="#000000",
                  space_before=gap)


def _paragraphs(xml):
    return re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S)


class PageTopSeamTests(unittest.TestCase):
    def test_a_rule_carries_the_break_itself(self):
        xml = _xml(_rule())
        self.assertNotIn('w:type="page"', xml)
        rule = [p for p in _paragraphs(xml) if "w:pBdr" in p][0]
        self.assertIn("<w:pageBreakBefore", rule)
        self.assertIn('w:before="2000"', rule)

    def test_an_open_loop_write_keeps_the_shipped_carrier(self):
        xml = _xml(_rule(), refined=False)
        self.assertEqual(xml.count('w:type="page"'), 1)
        self.assertNotIn("<w:pageBreakBefore", xml)

    def test_a_table_with_a_gap_puts_the_break_on_its_spacer(self):
        xml = _xml(TableEl(rows=[[Cell(paras=[_para("CELL text")])]],
                           col_widths=[200.0], space_before=100.0,
                           bbox=(72.0, 172.0, 272.0, 190.0)))
        self.assertNotIn('w:type="page"', xml)
        before_table = xml[:xml.index("<w:tbl>")]
        spacer = _paragraphs(before_table)[-1]
        self.assertIn("<w:pageBreakBefore", spacer)
        self.assertIn('w:line="2000"', spacer)

    def test_a_table_without_a_gap_keeps_the_carrier(self):
        xml = _xml(TableEl(rows=[[Cell(paras=[_para("CELL text")])]],
                           col_widths=[200.0], space_before=0.0,
                           bbox=(72.0, 72.0, 272.0, 90.0)))
        self.assertEqual(xml.count('w:type="page"'), 1)
        self.assertNotIn("<w:pageBreakBefore", xml)

    def test_a_page_whose_stack_overflows_its_box_keeps_the_carrier(self):
        # A page-top gap the page has no room for is a layout that does not
        # fit itself (overlapping inferred elements -- y03's figures). There
        # the carrier stays, and with it LibreOffice's dropping of the gap,
        # which is all that kept such a page on one page.
        lay = _lay(_rule(700.0))
        _freeze_seams(lay)
        self.assertEqual([p.top_gap_fits for p in lay.pages], [True, False])
        xml = _write(lay)
        self.assertEqual(xml.count('w:type="page"'), 1)
        self.assertNotIn("<w:pageBreakBefore", xml)

    def test_the_decision_is_made_once_and_then_obeyed(self):
        # The refine loop moves gaps between writes; the seam form must not
        # flip under it. Once set, `top_gap_fits` is what the writer obeys,
        # and freezing again does not revisit it.
        lay = _lay(_rule())
        _freeze_seams(lay)
        self.assertTrue(lay.pages[1].top_gap_fits)
        lay.pages[1].chunks[0].elements[0].space_before = 700.0
        _freeze_seams(lay)
        self.assertTrue(lay.pages[1].top_gap_fits)
        lay.pages[1].top_gap_fits = False
        self.assertEqual(_write(lay).count('w:type="page"'), 1)

    def test_a_figure_that_cannot_be_drawn_passes_the_break_on(self):
        # No backend, so the figure is omitted; the break must not vanish
        # with it -- the next paragraph takes it.
        xml = _xml(FigureEl(page_no=2, clip=(0, 0, 100, 100), width=100.0,
                            height=100.0, space_before=40.0))
        self.assertNotIn('w:type="page"', xml)
        marker = [p for p in _paragraphs(xml) if "MARKER" in p][0]
        self.assertIn("<w:pageBreakBefore", marker)


if __name__ == "__main__":
    unittest.main()
