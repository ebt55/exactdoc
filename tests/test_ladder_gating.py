"""A prediction that exists is not a prediction that is right.

Turning the ladder on globally was measured over the gated sixteen and shipped;
the expansion corpus then found what sixteen documents could not see. Two
distinct failures, both of them locks the ladder was confident about:

**It cut text it cannot measure.** `_predictable` checked that the FONT FAMILY
maps to a base-14 name and never that the CHARACTERS are in that font's WinAnsi
repertoire. Measured with `fitz.get_text_length` at 11pt, the base-14 metrics
resolve Latin glyph by glyph -- "aaaaaaaaaa" 48.84pt against "mmmmmmmmmm"
85.58pt -- and return an IDENTICAL 13.75pt for narrow and wide Cyrillic. They
are not approximating those scripts, they are not seeing them.

The rule is not representability, though, because c4_i18n's CJK is equally
invisible and locking it moved within2pt 0.1966 -> 0.5043. CJK is written
without spaces: the renderer breaks it wherever its own measurement lands and
cannot reproduce the source's break by luck, and the metric error is uniform
across the run so a width fraction still maps onto the right character.
Cyrillic and Greek break at spaces exactly like Latin, so the renderer already
reproduces the source wrap and a lock can only disturb it -- x06_lo_euro_scripts
went dy_p50 1.5 -> 13.0 and within2pt 0.6165 -> 0.2184.

**It spent page height the page had not got.** A lock pins the source's line
count; where the renderer would have used fewer lines, that is taller. In a
table cell the row height is declared by the source and restoring it is the
whole point (c1_whitepaper's cover band). In free flow it pushes pages over:
x10_chrome_tables_plain went 2/2 -> 2/3 and word recall 0.9963 -> 0.8657 even
though the same locks improved its dy_p50 17.2 -> 1.65.
"""
import unittest

from exactdoc import ladder
from exactdoc.ladder import (PAGE_SLACK_FRAC, UNMEASURED_MAX_FRAC,
                             _continuum_frac, _lockable_text, _measurable,
                             apply_ladder)
from exactdoc.layout import Cell, Chunk, DocLayout, PageLayout, Para, Run, TableEl
from exactdoc.metrics import get_metrics

LAT = "The depot replacement programme was approved on the fourteenth"
CYR = "Замещающие автобусы курсируют в течение всего периода работ"
GRK = "Τα λεωφορεία αντικατάστασης λειτουργούν καθ ολη τη διαρκεια"
CJK = "検索品質はコーパスが埋め込みモデルの較正点を超えて大きくなると非線形に低下します"


def _para(text, src_lines=2, size=11.0, leading=13.0, widths=None):
    p = Para(runs=[Run(text=text, font="LiberationSerif", size=size,
                       color="#000000")], leading=leading)
    p.src_lines = src_lines
    p.src_widths = widths or [400.0] * src_lines
    return p


class MetricRepertoire(unittest.TestCase):
    def test_latin_is_measurable(self):
        self.assertTrue(all(_measurable(c) for c in LAT))

    def test_latin1_accents_are_measurable(self):
        # cp1252 covers these; the ladder must not refuse ordinary French.
        self.assertTrue(all(_measurable(c) for c in "café naïve Ünter Straße"))

    def test_cyrillic_and_greek_are_not(self):
        self.assertFalse(any(_measurable(c) for c in CYR if not c.isspace()))
        self.assertFalse(any(_measurable(c) for c in GRK if not c.isspace()))

    def test_cjk_is_not(self):
        self.assertFalse(any(_measurable(c) for c in CJK))


class LockableText(unittest.TestCase):
    def test_plain_latin_is_lockable(self):
        self.assertTrue(_lockable_text(LAT))

    def test_a_script_continuum_is_lockable_though_unmeasured(self):
        # c4_i18n. Unmeasured but uniform, and the renderer cannot reproduce a
        # break it chooses arbitrarily.
        self.assertTrue(_lockable_text(CJK))
        self.assertGreaterEqual(_continuum_frac(CJK), 0.5)

    def test_space_delimited_unmeasured_text_is_refused(self):
        # x06/x12. The renderer already wraps these correctly on its own.
        self.assertFalse(_lockable_text(CYR))
        self.assertFalse(_lockable_text(GRK))

    def test_a_latin_label_on_a_cyrillic_body_is_refused(self):
        # x06's exact shape: LibreOffice merged the heading into the paragraph.
        self.assertFalse(_lockable_text("Cyrillic " + CYR))

    def test_a_stray_symbol_glyph_does_not_veto_a_latin_paragraph(self):
        # l1_word_native carries two U+F0B7 Wingdings bullets among ~200 Latin
        # characters. Vetoing on one character cost it word_recall 1.0 -> 0.9931.
        text = "Risks  Index rebuild window is contended.  " + LAT * 2
        frac = sum(1 for c in text if not c.isspace() and not _measurable(c)) \
            / sum(1 for c in text if not c.isspace())
        self.assertLess(frac, UNMEASURED_MAX_FRAC)
        self.assertTrue(_lockable_text(text))

    def test_the_tolerance_is_a_fraction_not_a_count(self):
        # Two unmeasured characters in a SHORT paragraph is a script change.
        self.assertFalse(_lockable_text("аб cd"))


def _layout(elements, used_filler=0.0, page_h=792.0, margin=36.0):
    lay = DocLayout(page_w=612.0, page_h=page_h, margin_l=72.0, margin_r=72.0,
                    margin_t=margin, margin_b=margin)
    ch = Chunk(n_cols=1, elements=list(elements))
    if used_filler:
        filler = _para("x", src_lines=1, leading=used_filler)
        filler.src_lines = 1
        ch.elements.insert(0, filler)
    lay.pages = [PageLayout(number=1, chunks=[ch])]
    return lay


class PageHeightBudget(unittest.TestCase):
    """A flow lock may add lines only while the page stays a quarter empty."""

    def _one_flow_lock(self, filler):
        # src 4 lines that the metrics predict will fit in fewer: short text,
        # wide source lines. The lock therefore ADDS height.
        p = _para(LAT, src_lines=4, widths=[400.0, 400.0, 400.0, 60.0])
        lay = _layout([p], used_filler=filler)
        rep = apply_ladder(lay, metrics=get_metrics("mupdf"))
        return rep, p

    def test_an_empty_page_accepts_a_height_adding_lock(self):
        rep, p = self._one_flow_lock(filler=0.0)
        self.assertEqual(rep["no_page_room"], 0)
        self.assertEqual(rep["line-locked"], 1)
        self.assertTrue(p.line_breaks)

    def test_a_nearly_full_page_refuses_it(self):
        rep, p = self._one_flow_lock(filler=700.0)
        self.assertEqual(rep["line-locked"], 0)
        self.assertEqual(rep["no_page_room"], 1)
        self.assertFalse(p.line_breaks)
        self.assertEqual(p.fidelity, "flow")

    def test_a_table_cell_is_exempt_because_its_height_is_declared(self):
        # c1_whitepaper's cover band: the row height comes from the source and
        # the lock restores it rather than inventing it, so a full page must not
        # veto it.
        cp = _para(LAT, src_lines=4, widths=[400.0, 400.0, 400.0, 60.0])
        tbl = TableEl(rows=[[Cell(paras=[cp])]], col_widths=[460.0],
                      row_heights=[60.0], bbox=(72.0, 10.0, 532.0, 70.0))
        lay = _layout([tbl], used_filler=700.0)
        rep = apply_ladder(lay, metrics=get_metrics("mupdf"))
        self.assertEqual(rep["no_page_room"], 0)
        self.assertEqual(rep["line-locked"], 1)
        self.assertTrue(cp.line_breaks)

    def test_the_budget_is_checked_after_the_lock_not_before(self):
        # Several candidates on one page must not fill it one at a time. With
        # the check applied before the lock, each sees room the previous one
        # already spent.
        paras = [_para(LAT, src_lines=4, widths=[400.0, 400.0, 400.0, 60.0])
                 for _ in range(12)]
        lay = _layout(paras)
        rep = apply_ladder(lay, metrics=get_metrics("mupdf"))
        cap = ladder._page_capacity(lay, 0)
        used = sum(ladder._el_height(e, 468.0, get_metrics("mupdf"))
                   for e in lay.pages[0].chunks[0].elements)
        self.assertGreaterEqual(cap - used, PAGE_SLACK_FRAC * cap)
        self.assertGreater(rep["no_page_room"], 0,
                           "the page must stop accepting before it fills")

    def test_a_lock_that_removes_lines_is_never_refused_for_room(self):
        # pred > src_lines shrinks the paragraph, so page height cannot be the
        # objection and the budget must not be consulted.
        p = _para(LAT * 6, src_lines=2, widths=[400.0, 400.0])
        lay = _layout([p], used_filler=700.0)
        rep = apply_ladder(lay, metrics=get_metrics("mupdf"))
        self.assertEqual(rep["no_page_room"], 0)


class ReportAccounting(unittest.TestCase):
    def test_refusals_are_named_in_the_report(self):
        lay = _layout([_para("Cyrillic " + CYR, src_lines=2)])
        rep = apply_ladder(lay, metrics=get_metrics("mupdf"))
        self.assertEqual(rep["unmeasured_script"], 1)
        self.assertEqual(rep["line-locked"], 0)

    def test_a_disabled_ladder_still_reports_its_keys(self):
        rep = apply_ladder(_layout([_para(LAT)]), enabled=False,
                           metrics=get_metrics("mupdf"))
        self.assertEqual(rep["line-locked"], 0)
        self.assertIn("unmeasured_script", rep)
        self.assertIn("no_page_room", rep)


if __name__ == "__main__":
    unittest.main()
