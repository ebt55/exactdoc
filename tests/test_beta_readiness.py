"""testkit/beta_readiness.py reads measurements honestly.

Synthetic inputs only: a two-document corpus, sweeps written to a temp folder,
a rows.jsonl and a pair of lane verdicts. What is pinned is the reading -- a
missing input is UNKNOWN and never PASS, a typed refusal is not a crash, an
upload failure is not the converter's, the speed rule only applies under the
page threshold -- not the bar's numbers, which the owner has yet to ratify.

    python -m unittest tests.test_beta_readiness
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import beta_readiness as B                                     # noqa: E402

TIERS = {"a.pdf": "ordinary_digital", "b.pdf": "ordinary_digital",
         "c.pdf": "designed_stress", "form.pdf": "unsupported"}


def _row(doc, src, out, conv=1.0, recall=0.99, **kw):
    r = {"document": doc, "tier": TIERS.get(doc), "src_pages": src,
         "out_pages": out, "page_ratio": out / src, "convert_s": conv,
         "char_recall": recall}
    r.update(kw)
    return r


class Reading(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _sweep(self, name, profile, rows):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"schema": "exactdoc.quality-sweep.v1", "profile": profile,
                       "corpus": "both", "documents": rows}, fh)
        return path

    def _gate(self, raw_ok=True):
        for lane, ok in (("raw", raw_ok), ("product", True)):
            d = os.path.join(self.dir, "run.batch", "lane_%s" % lane)
            os.makedirs(d)
            with open(os.path.join(d, "verdict.json"), "w") as fh:
                json.dump({"lane": lane, "ok": ok, "failures": [] if ok else ["x"],
                           "notes": ["16 document(s) measured, 16 expected"]}, fh)

    def _status(self, result, prefix):
        hits = [c for c in result["criteria"] if c["criterion"].startswith(prefix)]
        self.assertTrue(hits, prefix)
        return [c["status"] for c in hits]

    def test_everything_missing_is_unknown_not_pass(self):
        res = B.evaluate(TIERS, {}, None, None)
        self.assertEqual(res["verdict"], "INCOMPLETE")
        self.assertNotIn("PASS", [c["status"] for c in res["criteria"]])

    def test_a_full_reading(self):
        self._sweep("r.sweep.json", "pdfium/standard/none/refine0@240dpi",
                    [_row("a.pdf", 3, 3), _row("b.pdf", 2, 2),
                     _row("c.pdf", 120, 130, conv=200.0)])
        self._sweep("p.sweep.json", "pdfium/standard/libreoffice/refine3@240dpi",
                    [_row("a.pdf", 3, 3, conv=61.0), _row("b.pdf", 2, 2),
                     _row("c.pdf", 120, 121, conv=900.0)])
        with open(os.path.join(self.dir, "rows.jsonl"), "w") as fh:
            for r in ({"doc": "a.pdf", "src_pages": 3, "out_pages": 3,
                       "page_match": True, "char_recall": 0.99},
                      {"doc": "b.pdf", "error": "RoundtripError: upload"},
                      {"doc": "form.pdf", "error": "InteractiveFormError: no"},
                      {"doc": "x.pdf", "src_pages": 1, "out_pages": 9}):
                fh.write(json.dumps(r) + "\n")
        self._gate()
        sweeps = B.find_sweeps([self.dir], TIERS)
        self.assertEqual(sorted(sweeps), ["product", "raw"])
        gdocs = B.find_gdocs_rows([self.dir], TIERS)
        gate = B.find_gate([self.dir])
        res = B.evaluate(TIERS, sweeps, gdocs, gate)

        crashes = [c for c in res["criteria"] if c["criterion"] == "no crashes"][0]
        self.assertEqual(crashes["status"], "PASS")
        self.assertIn("1 measurement/upload failure(s) not counted", crashes["detail"])
        # c.pdf is 120 pages: over the speed rule's page threshold, so its 900s
        # does not count; a.pdf's 61s under the product profile does.
        self.assertEqual(self._status(res, "no conversion over 60s under 100 pages (raw)"),
                         ["PASS"])
        prod = [c for c in res["criteria"] if c["criterion"].endswith("(product)")][0]
        self.assertEqual(prod["status"], "FAIL")
        self.assertEqual(prod["misses"], ["a.pdf 61s, 3 pages"])
        # the designed tier and the probe document outside the corpus are not read
        self.assertEqual(self._status(res, "ordinary_digital page-exact"),
                         ["PASS", "PASS"])
        self.assertEqual(self._status(res, "the gated 16"), ["PASS"])
        self.assertEqual(self._status(res, "Word measured"), ["UNKNOWN"])
        self.assertEqual(res["verdict"], "NOT READY")
        text = B.render(res)
        self.assertIn("PROPOSED bar, not ratified", text)
        self.assertIn("verdict: NOT READY", text)

    def test_a_crash_and_a_failed_lane_fail(self):
        path = self._sweep("r.sweep.json", "pdfium/standard/none/refine0@240dpi",
                           [_row("a.pdf", 3, 4, recall=0.5),
                            {"document": "b.pdf", "error": "KeyError: 'x'"}])
        self._gate(raw_ok=False)
        res = B.evaluate(TIERS, {"raw": (path, B.load_sweep(path))}, None,
                         B.find_gate([self.dir]))
        self.assertEqual(self._status(res, "no crashes"), ["FAIL"])
        self.assertEqual(self._status(res, "the gated 16"), ["FAIL"])
        self.assertEqual(self._status(res, "ordinary_digital page-exact"),
                         ["FAIL", "UNKNOWN"])

    def test_a_targeted_sweep_is_not_a_reading_of_the_product(self):
        self._sweep("only.sweep.json", "pdfium/standard/none/refine0@240dpi",
                    [_row("a.pdf", 3, 3)])
        many = dict(TIERS, **{"d%d.pdf" % i: "ordinary_digital" for i in range(20)})
        self.assertEqual(B.find_sweeps([self.dir], many), {})

    def test_profile_kinds(self):
        self.assertEqual(B._profile_kind("pdfium/standard/none/refine0@240dpi"), "raw")
        self.assertEqual(B._profile_kind("pdfium/standard/libreoffice/refine3@240dpi"),
                         "product")
        self.assertEqual(B._profile_kind("pdfium/gdocs/none/refine0@240dpi"), "gdocs-lo")
        self.assertIsNone(B._profile_kind("nonsense"))


if __name__ == "__main__":
    unittest.main()
