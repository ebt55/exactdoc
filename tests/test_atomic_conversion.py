"""Public conversion publication is transactional, including refinement.

These tests deliberately fail after writing bytes.  A mock that fails before a
writer receives a path would not exercise the property users need: an existing
DOCX must survive a half-written replacement and refinement candidates must not
escape beside it.
"""
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from exactdoc.convert import convert
from exactdoc.errors import OracleError, OutputWriteError
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

    def test_refiner_none_output_is_failure_and_preserves_destination(self):
        def writer(_lay, path, **_kwargs):
            _write_docx(path, body=b"unmeasured candidate")
            return path

        with mock.patch("exactdoc.docxout.write_docx", side_effect=writer):
            with self.assertRaisesRegex(OracleError, "produced no output"):
                refine(object(), "input.pdf", self.dest, rounds=1,
                       render=lambda _candidate, _scratch: None,
                       backend=_Backend())
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
