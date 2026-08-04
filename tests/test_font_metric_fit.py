"""Contracts for font-family mapping and the Google Docs metric fit.

Run with ``python tests/test_font_metric_fit.py``.
"""
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from docx import Document

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.docxout import WriteCtx, write_docx, write_para          # noqa: E402
from exactdoc.fonts import (FAMILY_METRICS, METRIC_SUBSTITUTE_DEV,     # noqa: E402
                            METRIC_TRACK_DEV, family_keys, family_metrics,
                            map_font, metric_fit)
from exactdoc.gdocs_metrics import apply_metric_fit, iter_runs         # noqa: E402
from exactdoc.layout import (Cell, Chunk, DocLayout, HFPart, PageLayout,  # noqa: E402
                             Para, Run, TableEl)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _run(text="body", font="DejaVuSerif", size=11.0, **kw):
    return Run(text=text, font=font, size=size, color="#000000", **kw)


def _xml(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read("word/document.xml"))


class FamilyMappingTests(unittest.TestCase):
    def test_times_new_roman_no_longer_maps_to_a_sans_face(self):
        """The regression this fix exists for.

        `base_family` strips trailing style tokens, and `roman` is one of them
        -- right for "Times-Roman", wrong for "Times New Roman". The name
        reduced to "TimesNew", missed `_MAP`, and fell through to the heuristic,
        which returns Arial unless the span happens to carry a serif flag. Five
        NIST/IRS documents in the expansion corpus rendered serif body text in
        Arial because of it.
        """
        for name in ("TimesNewRomanPSMT", "Times New Roman", "TimesNewRoman",
                     "TimesNewRomanPS-BoldMT"):
            self.assertEqual(map_font(name, serif=False), "Times New Roman",
                             "%s must not fall through to the sans heuristic" % name)

    def test_the_map_entries_that_were_unreachable_are_reachable(self):
        # every key in the table must be findable from a name spelled that way
        for key in ("timesnewroman", "timesnewromanpsmt", "timesroman",
                    "arialmt", "couriernewpsmt"):
            self.assertIn(key, family_keys(key))

    def test_progressive_keys_go_specific_to_general(self):
        keys = family_keys("TimesNewRomanPS-BoldMT")
        self.assertEqual(keys[0], "timesnewromanpsboldmt")
        self.assertIn("timesnewroman", keys)
        self.assertLess(keys.index("timesnewromanpsboldmt"),
                        keys.index("timesnewroman"))

    def test_existing_mappings_are_untouched(self):
        # the corpus's families must map exactly as before the fix
        for name, mono, serif, want in (
                ("Helvetica", False, False, "Arial"),
                ("Times-Roman", False, True, "Times New Roman"),
                ("LiberationSerif", False, True, "Times New Roman"),
                ("LiberationMono", True, False, "Courier New"),
                ("DejaVuSerif", False, True, "Times New Roman"),
                ("DejaVuSans-Bold", False, False, "Arial"),
                ("ArialMT", False, False, "Arial"),
                ("CourierNewPSMT", True, False, "Courier New"),
                ("Calibri", False, False, "Carlito"),
                ("OpenSymbol", False, False, "Arial")):
            self.assertEqual(map_font(name, mono=mono, serif=serif), want, name)

    def test_a_substituted_family_maps_to_itself(self):
        # apply_metric_fit rewrites Run.font, and the writer maps it again
        for fam in ("Noto Serif", "Verdana", "Georgia", "Noto Sans",
                    "Times New Roman", "Arial", "Courier New"):
            self.assertEqual(map_font(fam), fam)


class MetricFitTests(unittest.TestCase):
    def test_the_measured_clones_are_exactly_equal(self):
        """Liberation faces are metric clones by design; the table must show it.

        If these ever drift apart the rule would start 'fixing' 13 corpus
        documents that are already correct.
        """
        for a, b in (("liberationserif", "timesnewroman"),
                     ("liberationsans", "arial"),
                     ("liberationmono", "couriernew")):
            self.assertEqual(FAMILY_METRICS[a][0], FAMILY_METRICS[b][0])

    def test_dejavu_serif_is_substituted_and_tracked(self):
        family, track = metric_fit("DejaVuSerif", serif=True)
        self.assertEqual(family, "Noto Serif")
        # residual is the measured gap per point of font size
        expected = FAMILY_METRICS["dejavuserif"][0] - FAMILY_METRICS["notoserif"][0]
        self.assertAlmostEqual(track, expected, places=6)
        self.assertAlmostEqual(track * 11.0, 0.360, places=3)

    def test_dejavu_sans_is_substituted_but_needs_no_tracking(self):
        # Verdana measures +0.2% against DejaVu Sans -- inside the track floor
        family, track = metric_fit("DejaVuSans", serif=False)
        self.assertEqual(family, "Verdana")
        self.assertEqual(track, 0.0)

    def test_a_metric_compatible_mapping_is_left_alone(self):
        for name, mono, serif in (("LiberationSerif", False, True),
                                  ("LiberationSans", False, False),
                                  ("LiberationMono", True, False),
                                  ("DejaVuSansMono", True, False)):
            family, track = metric_fit(name, mono=mono, serif=serif)
            self.assertEqual(family, map_font(name, mono=mono, serif=serif), name)
            self.assertEqual(track, 0.0, name)

    def test_an_unmeasured_family_is_never_guessed_at(self):
        """Absent measurement is not deviation zero -- it is 'do not act'."""
        for name in ("Helvetica", "Times-Roman", "Calibri", "OpenSymbol",
                     "HelveticaNeueLTStd-Roman", "SomeFoundryFont"):
            self.assertIsNone(family_metrics(name), name)
            family, track = metric_fit(name, serif=True)
            self.assertEqual(family, map_font(name, serif=True), name)
            self.assertEqual(track, 0.0, name)

    def test_thresholds_are_ordered_and_respected(self):
        self.assertLess(METRIC_TRACK_DEV, METRIC_SUBSTITUTE_DEV)
        src = FAMILY_METRICS["dejavusans"][0]
        # the chosen sans candidate is inside the track floor ...
        self.assertLess(abs(FAMILY_METRICS["verdana"][0] / src - 1),
                        METRIC_TRACK_DEV)
        # ... while the one it replaced was past the substitution threshold
        self.assertGreater(abs(FAMILY_METRICS["arial"][0] / src - 1),
                           METRIC_SUBSTITUTE_DEV)

    def test_substitution_always_moves_closer_to_the_source(self):
        for name, mono, serif in (("DejaVuSerif", False, True),
                                  ("DejaVuSans", False, False)):
            src = family_metrics(name)[0]
            before = family_metrics(map_font(name, mono=mono, serif=serif))[0]
            family, _ = metric_fit(name, mono=mono, serif=serif)
            after = family_metrics(family)[0]
            self.assertLess(abs(after / src - 1), abs(before / src - 1), name)


class LayoutWalkTests(unittest.TestCase):
    def _layout(self):
        body = Para(runs=[_run("body")])
        cell = Cell(paras=[Para(runs=[_run("cell")])])
        table = TableEl(rows=[[cell]], col_widths=[100.0])
        band = TableEl(rows=[[Cell(paras=[Para(runs=[_run("band")])])]],
                       col_widths=[300.0], role="band")
        rows_para = Para(runs=[_run("flow")],
                         gdocs_rows=[[_run("r1")], [_run("r2")]])
        header = HFPart(elements=[Para(runs=[_run("header")])])
        footer = HFPart(elements=[Para(runs=[_run("footer")])])
        return DocLayout(
            pages=[PageLayout(1, [Chunk(elements=[body, table, rows_para])])],
            cover_band=band, header_default=header, footer_default=footer)

    def test_every_container_is_reached(self):
        lay = self._layout()
        texts = sorted(r.text for r in iter_runs(lay))
        self.assertEqual(texts, ["band", "body", "cell", "flow", "footer",
                                 "header", "r1", "r2"])

    def test_apply_rewrites_font_and_tracking_everywhere(self):
        lay = self._layout()
        moved = apply_metric_fit(lay)
        self.assertEqual(moved, 8)
        for run in iter_runs(lay):
            self.assertEqual(run.font, "Noto Serif", run.text)
            self.assertAlmostEqual(run.char_spacing, 0.360, places=3)

    def test_existing_tracking_is_added_to_not_replaced(self):
        # inference sets char_spacing to reproduce TeX's inter-word shrink; the
        # two corrections describe different things and must compose.
        lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[
            Para(runs=[_run("x", char_spacing=-0.5)])])])])
        apply_metric_fit(lay)
        run = lay.pages[0].chunks[0].elements[0].runs[0]
        self.assertAlmostEqual(run.char_spacing, -0.5 + 0.360, places=3)

    def test_tabs_and_empty_runs_are_skipped(self):
        lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[
            Para(runs=[Run(text="", font="DejaVuSerif", size=11.0,
                           color="#000000", is_tab=True)])])])])
        self.assertEqual(apply_metric_fit(lay), 0)
        self.assertEqual(lay.pages[0].chunks[0].elements[0].runs[0].font,
                         "DejaVuSerif")


class WriterIntegrationTests(unittest.TestCase):
    def _layout(self):
        return DocLayout(pages=[PageLayout(1, [Chunk(elements=[
            Para(runs=[_run("Retrieval quality degrades non-linearly")])])])])

    def _fonts_and_spacing(self, path):
        root = _xml(path)
        fonts = sorted({rf.get(W + "ascii")
                        for rf in root.iter(W + "rFonts")
                        if rf.get(W + "ascii")})
        spacing = [sp.get(W + "val") for rpr in root.iter(W + "rPr")
                   for sp in rpr.findall(W + "spacing")]
        return fonts, spacing

    def test_gdocs_substitutes_and_tracks_while_standard_does_not(self):
        with tempfile.TemporaryDirectory() as td:
            std = Path(td) / "standard.docx"
            gd = Path(td) / "gdocs.docx"
            write_docx(self._layout(), str(std), output_profile="standard")
            write_docx(self._layout(), str(gd), output_profile="gdocs")

            fonts, spacing = self._fonts_and_spacing(std)
            self.assertEqual(fonts, ["Times New Roman"])
            self.assertEqual(spacing, [])

            fonts, spacing = self._fonts_and_spacing(gd)
            self.assertEqual(fonts, ["Noto Serif"])
            # 0.3603pt at 11pt, in integer twentieths of a point
            self.assertEqual(spacing, ["7"])

    def test_writing_twice_does_not_compound_the_tracking(self):
        """The failure mode this codebase has already paid for once.

        `apply_metric_fit` adds to `char_spacing`, so a writer that mutated the
        caller's layout would double the tracking on the second write -- and
        only on documents the rule acts on, which is why it would survive.
        """
        lay = self._layout()
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "a.docx"
            second = Path(td) / "b.docx"
            write_docx(lay, str(first), output_profile="gdocs")
            write_docx(lay, str(second), output_profile="gdocs")
            self.assertEqual(self._fonts_and_spacing(first),
                             self._fonts_and_spacing(second))
            self.assertEqual(lay.pages[0].chunks[0].elements[0].runs[0].font,
                             "DejaVuSerif")

    def test_an_unmeasured_font_is_written_unchanged_in_both_profiles(self):
        lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=[
            Para(runs=[_run("memo", font="Helvetica")])])])])
        with tempfile.TemporaryDirectory() as td:
            gd = Path(td) / "gdocs.docx"
            write_docx(lay, str(gd), output_profile="gdocs")
            fonts, spacing = self._fonts_and_spacing(gd)
            self.assertEqual(fonts, ["Arial"])
            self.assertEqual(spacing, [])


if __name__ == "__main__":
    unittest.main()
