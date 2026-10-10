"""The Google Docs drift sentinel (WP43): frozen, flown first, compared tightly.

testkit/fixtures_sentinel holds a one-page source PDF and the gdocs-candidate
DOCX made from it once, pinned by SHA-256 in sentinel.json. Every live run
(scripts/dev/gdsweep.py, scripts/dev/flypairs.py) flies that DOCX first and
compares the export with the row recorded the first time; DRIFT is printed
loudly and recorded in the row, and the run goes on. Google is replaced here
by a stand-in round trip that "exports" a chosen PDF.

    python -m unittest tests.test_docs_sentinel
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))
sys.path.insert(0, os.path.join(ROOT, "tests"))               # mupdf_extra

import mupdf_extra  # noqa: E402

if not mupdf_extra.AVAILABLE:                                  # pragma: no cover
    raise unittest.SkipTest(mupdf_extra.REASON)

import fitz  # noqa: E402
import docs_sentinel as S  # noqa: E402
import gdocs_oracle as go  # noqa: E402


class TheFixture(unittest.TestCase):
    def test_frozen_and_pinned(self):
        spec = S.load()
        self.assertEqual(spec["schema"], "exactdoc.docs-sentinel.v1")
        self.assertEqual(S.verify(spec), [])
        self.assertEqual(spec["docx"]["profile"], "pdfium/gdocs/none/refine0@240dpi")
        with fitz.open(S.SOURCE) as doc:
            self.assertEqual(doc.page_count, 1)

    def test_a_changed_fixture_is_named(self):
        spec = dict(S.load(), docx={"file": "x", "sha256": "0" * 64})
        self.assertTrue(S.verify(spec)[0].startswith("docx sentinel.gdocs.docx"))


class Flying(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name
        self.spec_path = os.path.join(self.dir, "sentinel.json")
        shutil.copyfile(S.SPEC, self.spec_path)

    def tearDown(self):
        self._td.cleanup()

    def _fly(self, exported):
        """One flight whose 'export' is `exported` (a PDF path)."""
        def roundtrip(svc, docx, pdf, **kw):
            self.assertEqual(os.path.abspath(docx), os.path.abspath(S.DOCX))
            shutil.copyfile(exported, pdf)
        lines = []
        with mock.patch.object(go, "roundtrip", side_effect=roundtrip), \
                mock.patch.object(S, "SPEC", self.spec_path):
            row = S.first(object(), os.path.join(self.dir, "out"), say=lines.append)
        return row, lines

    def _two_pages(self):
        path = os.path.join(self.dir, "two.pdf")
        with fitz.open(S.SOURCE) as doc:
            doc.new_page(width=612, height=792)
            doc.save(path)
        return path

    def test_unrecorded_then_recorded_then_ok(self):
        row, lines = self._fly(S.SOURCE)
        self.assertEqual((row["sentinel"], row["drift"]), ("unrecorded", []))
        self.assertRegex(row["utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIn("no expected row recorded", lines[0])
        S.record(row, path=self.spec_path)
        expected = S.load(self.spec_path)["expected"]
        self.assertEqual(expected["out_pages"], 1)
        row, lines = self._fly(S.SOURCE)
        self.assertEqual(row["sentinel"], "ok")

    def test_drift_is_loud_recorded_and_not_fatal(self):
        row, _ = self._fly(S.SOURCE)
        S.record(row, path=self.spec_path)
        row, lines = self._fly(self._two_pages())
        self.assertEqual(row["sentinel"], "DRIFT")
        self.assertIn("out_pages 1 -> 2 (tolerance 0)", row["drift"])
        self.assertTrue(any(l.startswith("DRIFT: Google Docs no longer renders") for l in lines))
        self.assertTrue(any("this run continues" in l for l in lines))

    def test_tolerances(self):
        spec = {"expected": {"out_pages": 1, "word_recall": 0.95, "within2pt": 0.50,
                             "dy_p50": 2.0}, "tolerance": dict(S.TOLERANCE)}
        ok = {"out_pages": 1, "word_recall": 0.954, "within2pt": 0.515, "dy_p50": 2.4}
        self.assertEqual(S.compare(ok, spec), ("ok", []))
        for key, value in (("word_recall", 0.944), ("within2pt", 0.47), ("dy_p50", 2.6),
                           ("out_pages", 2)):
            status, drift = S.compare(dict(ok, **{key: value}), spec)
            self.assertEqual(status, "DRIFT", key)
            self.assertTrue(drift[0].startswith(key), drift)
        self.assertEqual(S.compare({"error": "x"}, spec)[0], "error")

    def test_a_failed_flight_is_not_recorded(self):
        with self.assertRaises(SystemExit):
            S.record({"doc": S.DOC, "error": "RoundtripError: upload"}, path=self.spec_path)

    def test_check_reads_a_runs_rows(self):
        row, _ = self._fly(S.SOURCE)
        S.record(row, path=self.spec_path)
        rows = os.path.join(self.dir, "rows.jsonl")
        drifted, _ = self._fly(self._two_pages())
        with open(rows, "w") as fh:
            fh.write(json.dumps({"doc": "y01.pdf"}) + "\n")
            fh.write(json.dumps(dict(drifted, sentinel=None, drift=None)) + "\n")
        with mock.patch.object(S, "SPEC", self.spec_path), \
                mock.patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(S.main(["check", rows]), 1)


class TheLiveRuns(unittest.TestCase):
    def test_gdsweep_and_flypairs_fly_it_first_and_stamp_rows(self):
        for script in ("gdsweep.py", "flypairs.py"):
            with open(os.path.join(ROOT, "scripts", "dev", script), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("docs_sentinel.first(svc", text, script)
            self.assertIn('"utc": docs_sentinel.utc_now()', text, script)
            # the sentinel flies before the first document does
            self.assertLess(text.index("docs_sentinel.first("),
                            text.index("go.roundtrip(svc, docx"), script)


if __name__ == "__main__":
    unittest.main()
