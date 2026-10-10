"""Measurements say what they were made from, and the scorecard checks (WP43).

The measurement containers get a copy of the tree without .git, so a sweep or
a gate could not say which commit it measured. sweep.sh and gate_full.sh now
read the commit on the host and pass it in (EXACTDOC_GIT_COMMIT, with
EXACTDOC_GATE_IMAGE_ID); quality_sweep payloads and the gate's batch record
`provenance` (commit, image id, canonical fingerprint, reading); and
beta_readiness prints it and refuses (INCOMPLETE) lanes made from different
commits unless --allow-mixed-commits.

    python -m unittest tests.test_provenance
"""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import beta_readiness as B  # noqa: E402
import evidence  # noqa: E402

PROD = "pdfium/standard/libreoffice/refine3@240dpi"
RAW = "pdfium/standard/none/refine0@240dpi"
C1, C2 = "1" * 40, "2" * 40
DOCS = {d: {"tier": "ordinary_digital", "pages": 2, "promised": True, "gated": False}
        for d in ("a.pdf", "b.pdf")}


class TheCommitFromTheHost(unittest.TestCase):
    def test_no_git_here_reads_the_host_commit(self):
        with mock.patch.object(evidence, "_run", return_value=""), \
                mock.patch.dict(os.environ, {"EXACTDOC_GIT_COMMIT": C1,
                                             "EXACTDOC_GIT_DIRTY": "1",
                                             "EXACTDOC_GIT_BRANCH": "wp43"}):
            g = evidence.git_state()
        self.assertEqual((g["available"], g["commit"], g["short"], g["dirty"], g["branch"]),
                         (True, C1, C1[:7], True, "wp43"))
        self.assertIn("EXACTDOC_GIT_COMMIT", g["source"])

    def test_no_git_and_no_host_commit_is_unavailable(self):
        with mock.patch.object(evidence, "_run", return_value=""), \
                mock.patch.dict(os.environ, {"EXACTDOC_GIT_COMMIT": ""}):
            self.assertFalse(evidence.git_state()["available"])
        # a malformed value is not a commit
        with mock.patch.object(evidence, "_run", return_value=""), \
                mock.patch.dict(os.environ, {"EXACTDOC_GIT_COMMIT": "HEAD"}):
            self.assertFalse(evidence.git_state()["available"])

    def test_provenance_carries_commit_image_fingerprint_and_reading(self):
        with mock.patch.object(evidence, "_run", return_value=""), \
                mock.patch.dict(os.environ, {"EXACTDOC_GIT_COMMIT": C1,
                                             "EXACTDOC_GATE_IMAGE_ID": "sha256:abc",
                                             "EXACTDOC_GATE_IMAGE_REF": "exactdoc-gate:boot"}):
            p = evidence.provenance(env={"fingerprint": "9cb0bc17", "canonical": True},
                                    reading={"scorer": "wp29", "source": "x"})
        self.assertEqual((p["git_commit"], p["image_id"], p["image_ref"],
                          p["environment_fingerprint"], p["reading"]["scorer"]),
                         (C1, "sha256:abc", "exactdoc-gate:boot", "9cb0bc17", "wp29"))

    def test_the_scripts_pass_it_in(self):
        for script in ("sweep.sh", "gate_full.sh"):
            with open(os.path.join(ROOT, "scripts", "dev", script), encoding="utf-8") as fh:
                text = fh.read()
            for var in ("EXACTDOC_GIT_COMMIT=", "EXACTDOC_GATE_IMAGE_ID=", "rev-parse HEAD",
                        "docker image inspect"):
                self.assertIn(var, text, (script, var))
            self.assertIn("$PROV", text, script)


class TheScorecard(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _sweep(self, name, profile, commit):
        rows = [{"document": d, "src_pages": 2, "out_pages": 2, "convert_s": 1.0,
                 "word_recall": 0.99, "char_recall": 0.99} for d in DOCS]
        payload = {"schema": "exactdoc.quality-sweep.v1", "profile": profile,
                   "documents": rows}
        if commit:
            payload["provenance"] = {"git_commit": commit, "image_id": "sha256:" + "b" * 64,
                                     "environment_fingerprint": "9cb0bc17aaaa",
                                     "reading": {"scorer": "wp29"}}
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def _main(self, raw_commit, prod_commit, *extra):
        out = os.path.join(self.dir, "res.json")
        argv = ["--raw", self._sweep("r.sweep.json", RAW, raw_commit),
                "--product", self._sweep("p.sweep.json", PROD, prod_commit),
                "--json", out, "--runs", os.path.join(self.dir, "none")] + list(extra)
        with mock.patch("sys.stdout", new=io.StringIO()) as printed, \
                mock.patch.object(B, "corpus", return_value=DOCS):
            B.main(argv)
        with open(out, encoding="utf-8") as fh:
            return json.load(fh), printed.getvalue()

    def test_one_commit_is_read_and_printed(self):
        res, text = self._main(C1, C1)
        self.assertEqual(res["blockers"], [])
        self.assertIn("commit 111111111111, image bbbbbbbbbbbb, environment 9cb0bc17, "
                      "reading wp29", text)

    def test_mixed_commits_are_refused(self):
        res, text = self._main(C1, C2)
        self.assertEqual(res["verdict"], "INCOMPLETE")
        self.assertIn("different commits", res["blockers"][0])
        self.assertIn("inputs refused", text)

    def test_the_flag_reads_them_anyway(self):
        res, text = self._main(C1, C2, "--allow-mixed-commits")
        self.assertEqual(res["blockers"], [])
        self.assertIn("ALLOWED BY FLAG: --allow-mixed-commits", text)

    def test_an_unrecorded_commit_is_shown_not_compared(self):
        res, text = self._main(C1, None)
        self.assertEqual(res["blockers"], [])
        self.assertIn("provenance unrecorded", text)

    def test_the_gate_provenance_is_read_from_its_batch(self):
        d = os.path.join(self.dir, "batch")
        os.makedirs(d)
        with open(os.path.join(d, "provenance.json"), "w") as fh:
            json.dump({"git_commit": C2}, fh)
        self.assertEqual(B.load_gate_provenance(d)["git_commit"], C2)
        self.assertIsNone(B.load_gate_provenance(self.dir))
        self.assertIn("gate from 222222222222",
                      B.mixed_commits([("raw sweep", C1), ("gate", C2), ("x", None)]))


if __name__ == "__main__":
    unittest.main()
