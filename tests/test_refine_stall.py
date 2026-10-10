"""The refine loop stops on a stalled spill whose offsets have stopped moving.

y21 (World Development Report 2024, wp33's column split) sat at 49 pages with
one spill for three rounds while the offsets moved 1.5% and then 0.4%, and
each round cost ~10s: its product conversion ran 77s against a 72s limit. A
round that is the best so far, with the same pages and the same spill as the
best before it and an offset total less than STALL_MIN_GAIN smaller, ends the
loop (`refine._stalled`). A stalled round that is NO better keeps the old
behaviour -- the gap step can still close the spill (x11; y42 closed a page
on the round after a worse one).
"""
import os
import tempfile
import unittest
from unittest import mock

from exactdoc import refine as R
from tests.test_refine_loop import _FakeBackend, _Writer, _m


class Stalled(unittest.TestCase):
    def test_a_stalled_best_with_a_small_gain_is_stalled(self):
        self.assertTrue(R._stalled((1, 1, 1152.0), (1, 1, 1135.0)))   # 1.5%

    def test_a_real_gain_is_not(self):
        self.assertFalse(R._stalled((1, 1, 1000.0), (1, 1, 950.0)))    # 5%

    def test_a_spill_that_moved_is_not(self):
        self.assertFalse(R._stalled((1, 2, 1000.0), (1, 1, 999.0)))

    def test_nothing_spilling_is_not_a_stall(self):
        self.assertFalse(R._stalled((0, 0, 10.0), (0, 0, 9.99)))

    def test_no_best_yet_is_not_a_stall(self):
        self.assertFalse(R._stalled(None, (1, 1, 10.0)))


class Loop(unittest.TestCase):
    def _run(self, ms):
        renders = []

        def render(candidate, scratch):
            renders.append(candidate)
            return os.path.join(scratch, "r.pdf")

        report = {}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("exactdoc.docxout.write_docx", side_effect=_Writer()), \
                mock.patch("exactdoc.refine._measure", side_effect=ms), \
                mock.patch("exactdoc.refine._apply", return_value=True):
            R.refine(object(), "in.pdf", os.path.join(d, "o.docx"), rounds=3,
                     render=render, backend=_FakeBackend({}), report=report)
        return renders, report

    def test_y21s_shape_stops_after_the_first_stalled_round(self):
        renders, report = self._run([_m(4, [3, 1], [600.0, 600.0]),
                                     _m(3, [1, 0], [576.0, 576.0]),
                                     _m(3, [1, 0], [568.0, 567.0])])
        self.assertEqual(len(renders), 3)          # not 4
        self.assertEqual(report["stopped"], "stalled")
        self.assertEqual(report["published_round"], 2)

    def test_a_stalled_spill_still_gaining_goes_on(self):
        renders, report = self._run([_m(3, [1, 0], [100.0, 0.0]),
                                     _m(3, [1, 0], [90.0, 0.0]),
                                     _m(3, [1, 0], [80.0, 0.0]),
                                     _m(3, [1, 0], [70.0, 0.0])])
        self.assertEqual(len(renders), 4)
        self.assertEqual(report["stopped"], "max-rounds")

    def test_a_candidate_that_did_not_change_is_not_rendered(self):
        import zipfile
        renders = []

        def same(_lay, path, **_kw):
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("[Content_Types].xml", "<Types/>")
                z.writestr("_rels/.rels", "<Relationships/>")
                z.writestr("word/document.xml", "<w:document>same</w:document>")
                z.writestr("docProps/core.xml", "<t>%d</t>" % len(renders))
            return path

        def render(candidate, scratch):
            renders.append(candidate)
            return os.path.join(scratch, "r.pdf")

        report = {}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("exactdoc.docxout.write_docx", side_effect=same), \
                mock.patch("exactdoc.refine._measure",
                           side_effect=[_m(3, [1, 0], [9.0, 0.0])] * 4), \
                mock.patch("exactdoc.refine._apply", return_value=True):
            R.refine(object(), "in.pdf", os.path.join(d, "o.docx"), rounds=3,
                     render=render, backend=_FakeBackend({}), report=report)
        self.assertEqual(len(renders), 1)
        self.assertEqual(report["stopped"], "unchanged")
        self.assertEqual(report["published_round"], 0)

    def test_a_worse_stalled_round_still_gets_its_remaining_rounds(self):
        renders, report = self._run([_m(3, [1, 0], [0.0, 0.0]),
                                     _m(3, [1, 0], [5.0, 0.0]),
                                     _m(2, [0, 0], [0.0, 0.0])])
        self.assertEqual(len(renders), 3)
        self.assertEqual(report["stopped"], "converged")


if __name__ == "__main__":
    unittest.main()
