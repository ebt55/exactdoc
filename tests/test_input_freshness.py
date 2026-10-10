"""A stale gating input makes the scorecard INCOMPLETE (WP43).

beta_readiness flagged an input older than the newest by more than 24 h as
[STALE] and read it anyway, so a day-old lane could stand beside today's in
one verdict. Now a stale GATING input (a sweep, a lane, a serial timing, the
gate) makes the verdict INCOMPLETE unless --allow-stale; the accepted sweep is
old by design and never counts.

    python -m unittest tests.test_input_freshness
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import beta_readiness as B  # noqa: E402

PROD = "pdfium/standard/libreoffice/refine3@240dpi"
RAW = "pdfium/standard/none/refine0@240dpi"
DOCS = {d: {"tier": "ordinary_digital", "pages": 2, "promised": True, "gated": False}
        for d in ("a.pdf", "b.pdf")}
DAY = 24 * 3600


class Freshness(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _age(self, path, seconds):
        t = time.time() - seconds
        os.utime(path, (t, t))

    def _sweep(self, name, profile, age=0):
        rows = [{"document": d, "src_pages": 2, "out_pages": 2, "convert_s": 1.0,
                 "word_recall": 0.99, "char_recall": 0.99, "dy_p50": 1.0,
                 "within2pt": 0.5, "doc_recall": 0.99, "live_text_cov": 0.99} for d in DOCS]
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"schema": "exactdoc.quality-sweep.v1", "profile": profile,
                       "documents": rows}, fh)
        self._age(path, age)
        return path

    def _gate(self, age=0):
        d = os.path.join(self.dir, "batch")
        for lane in ("raw", "product"):
            os.makedirs(os.path.join(d, "lane_" + lane), exist_ok=True)
            p = os.path.join(d, "lane_" + lane, "verdict.json")
            with open(p, "w") as fh:
                json.dump({"lane": lane, "ok": True, "failures": [],
                           "notes": ["16 document(s) measured, 16 expected"]}, fh)
            self._age(p, age)
        return d

    def _main(self, raw_age=0, extra=(), gate_age=None, accepted_age=None):
        out = os.path.join(self.dir, "res.json")
        argv = ["--raw", self._sweep("r.sweep.json", RAW, raw_age),
                "--product", self._sweep("p.sweep.json", PROD),
                "--json", out, "--runs", os.path.join(self.dir, "none")] + list(extra)
        if gate_age is not None:
            argv += ["--gate", self._gate(gate_age)]
        if accepted_age is not None:
            argv += ["--accepted", self._sweep("acc.sweep.json", PROD, accepted_age)]
        with mock.patch("sys.stdout", new=io.StringIO()) as printed, \
                mock.patch.object(B, "corpus", return_value=DOCS):
            B.main(argv)
        with open(out, encoding="utf-8") as fh:
            return json.load(fh), printed.getvalue()

    def test_fresh_inputs_are_read(self):
        res, _ = self._main()
        self.assertEqual(res["blockers"], [])

    def test_a_stale_sweep_makes_the_verdict_incomplete(self):
        res, text = self._main(raw_age=2 * DAY)
        self.assertEqual(res["verdict"], "INCOMPLETE")
        self.assertIn("raw sweep", res["blockers"][0])
        self.assertIn("older than the newest input by more than 24 h", res["blockers"][0])
        self.assertIn("[STALE]", text)

    def test_allow_stale_reads_it_and_says_so(self):
        res, text = self._main(raw_age=2 * DAY, extra=["--allow-stale"])
        self.assertEqual(res["blockers"], [])
        self.assertIn("ALLOWED BY FLAG: --allow-stale: gating input(s)", text)

    def test_a_stale_gate_counts(self):
        res, _ = self._main(gate_age=3 * DAY)
        self.assertIn("gate", res["blockers"][0])

    def test_the_accepted_sweep_is_old_by_design(self):
        res, _ = self._main(accepted_age=30 * DAY)
        self.assertEqual(res["blockers"], [])

    def test_the_rule(self):
        rows = [("raw sweep", "p", "", True), ("accepted", "p", "", True),
                ("gdocs-lo sweep", "p", "", True), ("Word lane", None, None, False)]
        self.assertIn(": raw sweep;", B.stale_gating_inputs(rows))
        self.assertIsNone(B.stale_gating_inputs(rows[1:]))


if __name__ == "__main__":
    unittest.main()
