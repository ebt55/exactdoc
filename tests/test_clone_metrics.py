"""Calibri and Cambria are shaped with their own widths, not Helvetica's (B15).

`ladder._B14` used to put "carlito" on the base-14 Helvetica faces. Measured
from the font files over fonts.METRIC_REFERENCE, Calibri is 0.415097em per
character against Arial/Helvetica's 0.450660 -- 8.6% narrower -- and Calibri
Bold 0.424772 against Helvetica-Bold's 0.487401, 14.7% narrower. Every
`predict_lines` on a Calibri document over-predicted its line count, and the
ladder, the column-break test and the page-spill absorber acted on lines that
would never be rendered.

    python -m unittest tests.test_clone_metrics
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from exactdoc import _clone_widths as C                       # noqa: E402
from exactdoc import ladder                                    # noqa: E402
from exactdoc.fonts import METRIC_REFERENCE                    # noqa: E402
from exactdoc.layout import Para, Run                          # noqa: E402
from exactdoc.metrics import Base14Metrics, get_metrics        # noqa: E402


def _avg(family, bold=False, italic=False):
    m = Base14Metrics()
    return m.text_width(METRIC_REFERENCE, family, 1.0, bold=bold,
                        italic=italic) / len(METRIC_REFERENCE)


class Provenance(unittest.TestCase):
    def test_the_committed_file_is_what_the_generator_produces(self):
        """Byte for byte, wherever Carlito and Caladea are installed."""
        sys.path.insert(0, os.path.join(ROOT, "testkit"))
        import gen_clone_widths as gen
        d = gen.find_dir(os.environ.get("EXACTDOC_CLONE_FONTS"))
        if d is None:
            self.skipTest("Carlito/Caladea font files not installed here")
        with open(C.__file__, encoding="utf-8") as fh:
            shipped = fh.read()
        self.assertEqual(shipped, gen.render(gen.faces_from(d)),
                         "re-run testkit/gen_clone_widths.py rather than "
                         "editing exactdoc/_clone_widths.py")

    def test_every_source_is_recorded_with_its_digest(self):
        self.assertEqual(sorted(C.SOURCES), sorted(C.WIDTHS))
        for key, (fname, sha) in C.SOURCES.items():
            self.assertTrue(fname.startswith(("Carlito-", "Caladea-")), key)
            self.assertEqual(len(sha), 64, key)

    def test_repertoire_is_winansi_and_fallback_is_the_space(self):
        for key, table in C.WIDTHS.items():
            for cp in table:
                chr(cp).encode("cp1252")          # raises if outside WinAnsi
            self.assertEqual(C.FALLBACK[key], table[0x20], key)


class MeasuredWidths(unittest.TestCase):
    """The averages the audit measured with the font files, reproduced."""

    def test_calibri_is_narrower_than_helvetica_by_the_measured_amount(self):
        self.assertAlmostEqual(_avg("Calibri"), 0.415097, places=5)
        self.assertAlmostEqual(_avg("Calibri", bold=True), 0.424772, places=5)
        self.assertAlmostEqual(_avg("Arial"), 0.450660, delta=0.002)
        self.assertLess(_avg("Calibri") / _avg("Arial"), 0.93)

    def test_carlito_and_calibri_are_one_table(self):
        for b, i in ((False, False), (True, False), (False, True), (True, True)):
            self.assertEqual(_avg("Calibri", b, i), _avg("Carlito", b, i))

    def test_cambria(self):
        self.assertAlmostEqual(_avg("Cambria"), 0.434915, places=5)
        self.assertEqual(_avg("Cambria"), _avg("Caladea"))

    def test_arithmetic_is_additive_and_linear(self):
        m = Base14Metrics()
        s = "Hamburgefonstiv, 0123 — “quoted”"
        whole = m.text_width(s, "Calibri", 11.0)
        self.assertAlmostEqual(whole, sum(m.text_width(c, "Calibri", 11.0)
                                          for c in s), places=6)
        self.assertAlmostEqual(m.text_width(s, "Calibri", 22.0), 2 * whole,
                               places=6)

    def test_a_family_with_no_table_is_still_unmeasurable(self):
        m = Base14Metrics()
        self.assertIsNone(m.text_width("hello", "Calibri Light", 11.0))
        self.assertIsNone(m.text_width("hello", "Georgia", 11.0))


class LadderUsesTheRealWidths(unittest.TestCase):
    def _para(self, font, text):
        return Para(runs=[Run(text=text, font=font, size=11.0, color="#000000")],
                    src_lines=1)

    def test_calibri_is_predictable_and_its_lines_are_its_own(self):
        text = ("Federal agencies protect controlled unclassified information "
                "in nonfederal systems")
        m = get_metrics()
        cal = m.text_width(text, "Calibri", 11.0)
        ari = m.text_width(text, "Arial", 11.0)
        avail = cal + 2.0            # fits in Calibri, not in Helvetica widths
        self.assertGreater(ari, avail)
        p = self._para("Calibri", text)
        self.assertTrue(ladder._predictable(p))
        self.assertEqual(ladder.predict_lines(p, avail, m), 1)
        # what the old Helvetica-faced table predicted for the same text
        self.assertEqual(ladder.predict_lines(self._para("Helvetica", text),
                                              avail, m), 2)

    def test_the_mupdf_archive_path_stays_base14_only(self):
        self.assertIsNone(ladder._b14("Calibri", False, False))
        self.assertEqual(ladder._face("Calibri", True, False), "carlito-b")
        self.assertEqual(ladder._face("Arial", False, False), "helv")


if __name__ == "__main__":
    unittest.main()
