"""Public conversion publication is transactional, including refinement.

These tests deliberately fail after writing bytes.  A mock that fails before a
writer receives a path would not exercise the property users need: an existing
DOCX must survive a half-written replacement and refinement candidates must not
escape beside it.
"""
import os
import tempfile
import unittest
import warnings
import zipfile
from unittest import mock

from exactdoc.convert import convert
from exactdoc.errors import (OracleCleanupError, OracleDegradedWarning,
                             OracleExportError, OutputWriteError)
from exactdoc.layout import DocLayout
from exactdoc.options import RAW
from exactdoc.refine import refine


def _write_docx(path, body=b"replacement"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("_rels/.rels", "<Relationships/>")
        archive.writestr("word/document.xml", b"<w:document>" + body + b"</w:document>")


class _Backend:
    name = "pdfium"


class AtomicConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.temp.name, "existing.docx")
        with open(self.dest, "wb") as fh:
            fh.write(b"previous destination bytes")
        with open(self.dest, "rb") as fh:
            self.before = fh.read()

    def tearDown(self):
        self.temp.cleanup()

    def _assert_untouched(self):
        with open(self.dest, "rb") as fh:
            self.assertEqual(fh.read(), self.before)
        self.assertEqual(
            [name for name in os.listdir(self.temp.name)
             if name.startswith(".exactdoc-") or name.endswith(".best")],
            [],
        )

    def _convert_open_loop(self, writer):
        # A real (empty) layout, not a bare object: the shipping profile runs
        # the quality ladder, which walks `lay.pages`. These tests are about
        # atomic replacement and must not double as a pin on that default.
        lay = DocLayout()
        with mock.patch("exactdoc.convert._select_backend", return_value=_Backend()), \
             mock.patch("exactdoc.convert.parse_input", return_value=object()), \
             mock.patch("exactdoc.convert.normalize", return_value=object()), \
             mock.patch("exactdoc.convert.infer", return_value=lay), \
             mock.patch("exactdoc.docxout.write_docx", side_effect=writer):
            return convert("input.pdf", self.dest,
                           options=RAW.replace(backend="pdfium"))

    def test_open_loop_writer_failure_after_partial_write_preserves_destination(self):
        def broken_writer(_lay, path, **_kwargs):
            with open(path, "wb") as fh:
                fh.write(b"PK\x03\x04 incomplete document")
            raise RuntimeError("raster image failed")

        with self.assertRaises(OutputWriteError):
            self._convert_open_loop(broken_writer)
        self._assert_untouched()

    def test_open_loop_success_replaces_only_after_complete_docx_and_returns_requested_path(self):
        def writer(_lay, path, **_kwargs):
            _write_docx(path)
            return path

        returned = self._convert_open_loop(writer)
        self.assertEqual(returned, self.dest)
        with open(self.dest, "rb") as fh:
            self.assertNotEqual(fh.read(), self.before)
        self._assert_no_public_artifacts()

    def test_refinement_writer_failure_after_partial_write_preserves_destination(self):
        def broken_writer(_lay, path, **_kwargs):
            with open(path, "wb") as fh:
                fh.write(b"PK\x03\x04 incomplete candidate")
            raise RuntimeError("writer failed mid-candidate")

        with mock.patch("exactdoc.docxout.write_docx", side_effect=broken_writer):
            with self.assertRaisesRegex(RuntimeError, "mid-candidate"):
                refine(object(), "input.pdf", self.dest, rounds=1,
                       render=lambda _candidate, _scratch: None,
                       backend=_Backend())
        self._assert_untouched()

    def test_refiner_failure_after_candidate_write_preserves_destination(self):
        def writer(_lay, path, **_kwargs):
            _write_docx(path, body=b"candidate")
            return path

        def broken_render(_candidate, _scratch):
            raise RuntimeError("oracle failed after candidate write")

        with mock.patch("exactdoc.docxout.write_docx", side_effect=writer):
            with self.assertRaisesRegex(RuntimeError, "oracle failed"):
                refine(object(), "input.pdf", self.dest, rounds=1,
                       render=broken_render, backend=_Backend())
        self._assert_untouched()

    def test_refiner_none_output_escalated_is_failure_and_preserves_destination(self):
        # The all-or-nothing contract, now opt-in: a caller that escalates
        # OracleDegradedWarning gets an exception and an untouched destination,
        # because the warning is raised BEFORE anything is published.
        def writer(_lay, path, **_kwargs):
            _write_docx(path, body=b"unmeasured candidate")
            return path

        with mock.patch("exactdoc.docxout.write_docx", side_effect=writer):
            with warnings.catch_warnings():
                warnings.simplefilter("error", OracleDegradedWarning)
                with self.assertRaisesRegex(OracleDegradedWarning,
                                            "produced no output"):
                    refine(object(), "input.pdf", self.dest, rounds=1,
                           render=lambda _candidate, _scratch: None,
                           backend=_Backend())
        self._assert_untouched()

    def test_refiner_none_output_publishes_open_loop_candidate_and_warns(self):
        # The default: an installed oracle that writes nothing must not cost
        # the user the DOCX that round 0 already produced.
        def writer(_lay, path, **_kwargs):
            _write_docx(path, body=b"round zero")
            return path

        report = {}
        with mock.patch("exactdoc.docxout.write_docx", side_effect=writer):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                returned = refine(object(), "input.pdf", self.dest, rounds=3,
                                  render=lambda _candidate, _scratch: None,
                                  backend=_Backend(), report=report)
        self.assertEqual(returned, self.dest)
        with zipfile.ZipFile(self.dest) as z:
            self.assertIn(b"round zero", z.read("word/document.xml"))
        degraded = [w for w in caught
                    if issubclass(w.category, OracleDegradedWarning)]
        self.assertEqual(len(degraded), 1)
        self.assertEqual(degraded[0].message.code, "oracle-degraded")
        self.assertIsNone(degraded[0].message.published_round)
        self.assertEqual(report["oracle_failure"]["round"], 0)
        self.assertEqual(report["stopped"], "oracle-failed")
        self._assert_no_public_artifacts()

    def test_refiner_failure_after_a_measured_round_publishes_that_round(self):
        # Round 0 renders and measures (with a spill, so the loop goes on);
        # round 1's render raises an OracleError. The measured round is what
        # gets published, not the failed round's candidate.
        rounds = []

        def writer(_lay, path, **_kwargs):
            rounds.append(path)
            _write_docx(path, body=b"round %d" % (len(rounds) - 1))
            return path

        def render(candidate, scratch):
            if "candidate-0" in candidate:
                return os.path.join(scratch, "r0.pdf")
            raise OracleExportError("export failed")

        measurement = {"out_pages": 2, "src_pages": 1, "spill": [1],
                       "offset": [0.0], "need": [None]}
        report = {}
        with mock.patch("exactdoc.docxout.write_docx", side_effect=writer), \
             mock.patch("exactdoc.refine._measure", return_value=measurement), \
             mock.patch("exactdoc.refine._apply", return_value=True):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                refine(object(), "input.pdf", self.dest, rounds=3,
                       render=render, backend=_Backend(), report=report)
        with zipfile.ZipFile(self.dest) as z:
            self.assertIn(b"round 0", z.read("word/document.xml"))
        self.assertEqual(report["published_round"], 0)
        self.assertEqual(report["oracle_failure"]["round"], 1)
        self.assertIn("OracleExportError", report["oracle_failure"]["reason"])
        self.assertTrue(any(issubclass(w.category, OracleDegradedWarning)
                            for w in caught))

    def test_cleanup_failure_is_never_degraded(self):
        # A cloud oracle that could not delete its copy has left the user's
        # document in somebody else's storage. That stays an error.
        def writer(_lay, path, **_kwargs):
            _write_docx(path)
            return path

        def render(_candidate, _scratch):
            raise OracleCleanupError("could not delete the temporary copy")

        with mock.patch("exactdoc.docxout.write_docx", side_effect=writer):
            with self.assertRaises(OracleCleanupError):
                refine(object(), "input.pdf", self.dest, rounds=1,
                       render=render, backend=_Backend())
        self._assert_untouched()

    def test_a_renderer_with_close_is_closed_whatever_happens(self):
        def writer(_lay, path, **_kwargs):
            _write_docx(path)
            return path

        class Renderer:
            closed = 0

            def __call__(self, _candidate, _scratch):
                raise RuntimeError("bug in a custom oracle")

            def close(self):
                Renderer.closed += 1

        with mock.patch("exactdoc.docxout.write_docx", side_effect=writer):
            with self.assertRaises(RuntimeError):
                refine(object(), "input.pdf", self.dest, rounds=1,
                       render=Renderer(), backend=_Backend())
        self.assertEqual(Renderer.closed, 1)
        self._assert_untouched()

    def test_refinement_success_publishes_measured_candidate_without_best_side_file(self):
        def writer(_lay, path, **_kwargs):
            _write_docx(path, body=b"refined")
            return path

        measurement = {"out_pages": 1, "src_pages": 1,
                       "spill": [0], "offset": [0.0]}
        with mock.patch("exactdoc.docxout.write_docx", side_effect=writer), \
             mock.patch("exactdoc.refine._measure", return_value=measurement):
            returned = refine(
                object(), "input.pdf", self.dest, rounds=1,
                render=lambda _candidate, scratch: os.path.join(scratch,
                                                                 "rendered.pdf"),
                backend=_Backend())
        self.assertEqual(returned, self.dest)
        with open(self.dest, "rb") as fh:
            self.assertNotEqual(fh.read(), self.before)
        self._assert_no_public_artifacts()

    def _assert_no_public_artifacts(self):
        self.assertEqual(
            [name for name in os.listdir(self.temp.name)
             if name.startswith(".exactdoc-") or name.endswith(".best")],
            [],
        )


if __name__ == "__main__":
    unittest.main()
