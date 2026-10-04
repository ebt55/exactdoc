"""Google Docs discards run tracking, so nothing written for it may rely on it.

Live pass 2 measured Docs dropping w:spacing; on 2026-10-04 x10's DOCX exported
identical PDFs with its tracking as written, removed, and multiplied by ten.
The ladder used to fit locked lines by compressing them with negative tracking
under every profile -- under gdocs that was "locking without fitting", the
case the ladder's own notes measure as worse than flow (24 -> 27 pages). Under
gdocs the ladder now shapes text at its natural advances and refuses a lock
that only compression would make fit; the standard profile is unchanged.
"""
import unittest

from exactdoc import ladder
from exactdoc.fonts import GDOCS_HONOURS_RUN_TRACKING
from exactdoc.layout import Para, Run
from exactdoc.metrics import (RendererMetrics, for_profile, get_metrics,
                              honours_tracking)


def _para(text, tracking=0.0, src_widths=None, size=10.0):
    p = Para(runs=[Run(text=text, font="Helvetica", size=size, color="#000000",
                       tracking=tracking)])
    if src_widths:
        p.src_lines = len(src_widths)
        p.src_widths = list(src_widths)
    return p


class ForProfile(unittest.TestCase):
    def test_gdocs_metrics_say_tracking_is_not_honoured(self):
        self.assertFalse(GDOCS_HONOURS_RUN_TRACKING)
        base = get_metrics()
        gd = for_profile(base, "gdocs")
        self.assertIsInstance(gd, RendererMetrics)
        self.assertFalse(honours_tracking(gd))
        self.assertEqual(gd.text_width("abc", "Arial", 10.0),
                         base.text_width("abc", "Arial", 10.0))
        self.assertEqual(gd.name, base.name)

    def test_standard_metrics_are_returned_as_they_are(self):
        base = get_metrics()
        self.assertIs(for_profile(base, "standard"), base)
        self.assertTrue(honours_tracking(base))
        self.assertIsNone(for_profile(None, "gdocs"))


class Prediction(unittest.TestCase):
    def test_tracking_counts_only_where_the_renderer_honours_it(self):
        text = "word " * 16
        base = get_metrics()
        natural = base.text_width(text.strip(), "Arial", 10.0)
        avail = natural + 10.0                 # fits on one line untracked
        p = _para(text.strip(), tracking=1.0)  # +79pt of tracking: two lines
        self.assertEqual(ladder.predict_lines(p, avail, base), 2)
        self.assertEqual(ladder.predict_lines(p, avail, for_profile(base, "gdocs")), 1)


class Locking(unittest.TestCase):
    def _overflowing_two_liner(self):
        # Two source lines, the first slightly wider than the column at
        # natural spacing: only compression would make the lock fit.
        first = "alpha bravo charlie delta echo foxtrot golf hotel"
        second = "india juliet"
        base = get_metrics()
        w1 = base.text_width(first, "Arial", 10.0)
        w2 = base.text_width(second, "Arial", 10.0)
        p = _para(first + " " + second, src_widths=[w1, w2])
        return p, w1 - 2.0                     # column 2pt short of line one

    def test_standard_fits_the_lock_by_compressing_it(self):
        p, avail = self._overflowing_two_liner()
        self.assertTrue(ladder._lock(p, avail, get_metrics()))
        self.assertEqual(p.fidelity, "line-locked")
        self.assertLess(p.runs[0].char_spacing, 0.0)

    def test_gdocs_refuses_a_lock_only_compression_would_fit(self):
        p, avail = self._overflowing_two_liner()
        self.assertFalse(ladder._lock(p, avail, for_profile(get_metrics(), "gdocs")))
        self.assertEqual(p.fidelity, "flow")
        self.assertEqual(p.runs[0].char_spacing, 0.0)

    def test_gdocs_still_locks_a_line_that_fits_naturally(self):
        p, avail = self._overflowing_two_liner()
        self.assertTrue(ladder._lock(p, avail + 12.0,
                                     for_profile(get_metrics(), "gdocs")))
        self.assertTrue(all(r.char_spacing == 0.0 for r in p.runs))


if __name__ == "__main__":
    unittest.main()
