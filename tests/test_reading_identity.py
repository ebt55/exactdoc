"""Sweeps record the harness reading they were scored in (WP41c).

Amendment 4 (a) of the beta bar: criterion 8 compares two sweeps only when
they are read the same way. For that to be automatic the reading has to be
recorded by the tools that score, taken from the harness itself:
`harness.HARNESS_READING` (bumped by each amendment that changes the reading)
and a hash of the reading code. Pinned here: the hash ignores comments and
docstrings but not code; every part it names exists; quality_sweep.py and
rescore.py write `reading`; and beta_readiness warns, without blocking, when a
side records none, and when the code differs under the same name.

    python -m unittest tests.test_reading_identity
"""
import io
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))
sys.path.insert(0, os.path.join(ROOT, "tests"))               # mupdf_extra

import mupdf_extra  # noqa: E402

if not mupdf_extra.AVAILABLE:                                  # pragma: no cover
    raise unittest.SkipTest(mupdf_extra.REASON)

import beta_readiness as B  # noqa: E402
import harness  # noqa: E402

HARNESS = os.path.join(ROOT, "testkit", "harness.py")
PROD = "pdfium/standard/libreoffice/refine3@240dpi"


class TheReading(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _variant(self, old, new):
        path = os.path.join(self.dir, "harness_variant.py")
        with open(HARNESS, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(old, text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new, 1))
        return harness._reading_source_hash(path)

    def test_the_reading_is_named_and_hashed(self):
        r = harness.reading()
        self.assertEqual(r["scorer"], harness.HARNESS_READING)
        self.assertEqual(r["scorer"], "wp42")
        self.assertRegex(r["source"], r"^[0-9a-f]{12}$")
        self.assertEqual(r["source"], harness._reading_source_hash(HARNESS))

    def test_the_recorded_reading_is_pinned(self):
        # Computed on Windows' Python 3.12 and checked by the gate on the
        # container's: the hash must not depend on the interpreter. Change the
        # reading code, and this fails until HARNESS_READING is bumped (when
        # the reading changed) and the pin is updated in the same commit.
        self.assertEqual(harness.reading(), {"scorer": "wp42", "source": "ca563181d6ad"},
                         "the reading code changed: bump harness.HARNESS_READING if "
                         "the reading did, and re-pin here")

    def test_every_part_of_the_reading_exists(self):
        for name in harness._READING_PARTS:
            self.assertTrue(hasattr(harness, name), name)

    def test_comments_and_docstrings_do_not_move_the_hash_code_does(self):
        base = harness._reading_source_hash(HARNESS)
        self.assertEqual(self._variant(
            "    drifts = []\n", "    # a comment\n    drifts = []\n"), base)
        self.assertEqual(self._variant(
            '    """Per page, [(text, x0, y0, x1, y1, y)] in reading order:',
            '    """Per page, [(text, x0, y0, x1, y1, y)], reading order:'), base)
        self.assertNotEqual(self._variant("_LEADER_MIN = 3", "_LEADER_MIN = 4"), base)
        # code outside the reading (pixels, SSIM) is not part of it
        self.assertEqual(self._variant("C1, C2 = (0.01 * 255) ** 2",
                                       "C1, C2 = (0.02 * 255) ** 2"), base)


class TheWriters(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def test_quality_sweep_records_the_reading(self):
        import evidence
        import quality_sweep as qs
        row = {"document": "a.pdf", "refused": "PageLimitError"}      # no scoring needed
        out = os.path.join(self.dir, "s.sweep.json")
        with mock.patch.object(qs, "select", return_value=[("a.pdf", "a.pdf", "x", "y")]), \
                mock.patch.object(qs, "_work", return_value=row), \
                mock.patch.object(qs, "ProcessPoolExecutor", ThreadPoolExecutor), \
                mock.patch.object(evidence, "environment",
                                  return_value={"fingerprint": "f" * 64, "canonical": True}), \
                mock.patch.dict(os.environ, {"EXACTDOC_GATE_IMAGE_ID": "sha256:abc"}), \
                mock.patch("sys.stdout", new=io.StringIO()):
            qs.main(["--out", self.dir, "--json", out, "--jobs", "1"])
        with open(out, encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["reading"], harness.reading())
        self.assertEqual(B.sweep_reading(payload), harness.HARNESS_READING)
        # WP43: and what it was made from
        prov = payload["provenance"]
        self.assertEqual((prov["image_id"], prov["environment_fingerprint"], prov["reading"]),
                         ("sha256:abc", "f" * 64, harness.reading()))
        self.assertIn("git_commit", prov)

    def test_rescore_records_the_reading_it_re_read_in(self):
        import rescore
        src = os.path.join(self.dir, "in.sweep.json")
        with open(src, "w", encoding="utf-8") as fh:
            json.dump({"schema": "exactdoc.quality-sweep.v1", "profile": PROD,
                       "reading": {"scorer": "old", "source": "0" * 12},
                       "documents": [{"document": "a.pdf"}]}, fh)
        out = os.path.join(self.dir, "out.sweep.json")
        with mock.patch.object(rescore, "_rescore_all", side_effect=lambda items, jobs: [
                dict(r, scorer=harness.HARNESS_READING) for r, *_ in items]), \
                mock.patch.object(rescore, "source_of", return_value="a.pdf"):
            data = rescore.rescore_sweep(src, self.dir, out)
        self.assertEqual(data["reading"], harness.reading())
        self.assertEqual(data["rescored"]["scorer"], harness.HARNESS_READING)


class TheScorecard(unittest.TestCase):
    """Criterion 8 reads the recorded readings: different -> UNMEASURED;
    missing on a side -> compared, with a non-blocking warning; same name,
    different code -> compared, with a warning."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _c8(self, acc_reading, cur_reading):
        rows = [{"document": d, "src_pages": 2, "out_pages": 2, "word_recall": 0.99,
                 "doc_recall": 0.99, "live_text_cov": 0.99, "within2pt": 0.5,
                 "dy_p50": 1.0} for d in ("short.pdf", "short2.pdf", "long.pdf", "paper.pdf")]
        paths = []
        for name, reading in (("acc.sweep.json", acc_reading), ("cur.sweep.json", cur_reading)):
            payload = {"schema": "exactdoc.quality-sweep.v1", "profile": PROD,
                       "documents": rows}
            if reading:
                payload["reading"] = reading
            path = os.path.join(self.dir, name)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            paths.append(path)
        docs = {d: {"tier": "ordinary_digital", "pages": 2, "promised": True, "gated": False}
                for d in ("short.pdf", "short2.pdf", "long.pdf", "paper.pdf")}
        res = B.evaluate(docs, {"product": (paths[1], B.load_sweep(paths[1]))},
                         {"lo": None, "word": None, "docs": None}, None,
                         accepted=(paths[0], B.load_sweep(paths[0])))
        return {c["key"]: c for c in res["criteria"]}["regression"]

    def test_recorded_and_equal(self):
        c = self._c8(harness.reading(), harness.reading())
        self.assertEqual((c["status"], c["readings"]["warnings"]), ("PASS", []))

    def test_recorded_and_different_is_unmeasured(self):
        c = self._c8({"scorer": "wp29", "source": "a" * 12},
                     {"scorer": "wp42", "source": "b" * 12})
        self.assertEqual(c["status"], "UNMEASURED")
        self.assertIn("mixed reading", c["detail"])

    def test_unrecorded_is_a_warning_not_a_match(self):
        for acc, cur, side in ((None, harness.reading(), "accepted"),
                               (harness.reading(), None, "current")):
            c = self._c8(acc, cur)
            self.assertEqual(c["status"], "PASS")
            self.assertIn("WARNING: reading unrecorded", c["detail"])
            self.assertTrue(any(m.startswith("(warning) reading unrecorded: the %s sweep"
                                             % side) for m in c["misses"]))

    def test_same_name_different_code_is_a_warning(self):
        c = self._c8({"scorer": "wp29", "source": "a" * 12},
                     {"scorer": "wp29", "source": "b" * 12})
        self.assertEqual(c["status"], "PASS")
        self.assertIn("reading code differs under the one name wp29",
                      c["readings"]["warnings"][0])


if __name__ == "__main__":
    unittest.main()
