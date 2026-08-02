"""Public failures for password-protected and unrecoverably bad PDFs.

The fixtures are written into the test directory from fixed bytes.  The
encrypted one is a one-page, password-protected PDF; it contains no document
text and its password is deliberately never supplied to the converter.
"""
import base64
import gc
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.convert import convert                    # noqa: E402
from exactdoc.errors import ParseError, UnsupportedInputError  # noqa: E402
from exactdoc.options import RAW                         # noqa: E402


# Generated once with pypdf's one-page writer, then embedded so
# these tests need no fixture-generation dependency.  It is PDF 1.3 with the
# standard security handler and a user password; readers must report password
# required before attempting content extraction.
ENCRYPTED_PDF = base64.b64decode(
    "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgPGQzMDBmNGViZDE+"
    "Cj4+CmVuZG9iagoyIDAgb2JqCjw8Ci9UeXBlIC9QYWdlcwovQ291bnQgMQovS2lk"
    "cyBbIDQgMCBSIF0KPj4KZW5kb2JqCjMgMCBvYmoKPDwKL1R5cGUgL0NhdGFsb2cK"
    "L1BhZ2VzIDIgMCBSCj4+CmVuZG9iago0IDAgb2JqCjw8Ci9UeXBlIC9QYWdlCi9S"
    "ZXNvdXJjZXMgPDwKPj4KL01lZGlhQm94IFsgMC4wIDAuMCA3MiA3MiBdCi9QYXJl"
    "bnQgMiAwIFIKPj4KZW5kb2JqCjUgMCBvYmoKPDwKL1YgMgovUiAzCi9MZW5ndGgg"
    "MTI4Ci9QIDQyOTQ5NjcyOTIKL0ZpbHRlciAvU3RhbmRhcmQKL08gPGNlNjllNDRm"
    "ZDQ3MTc1ODIwNzZiODEwOTE0ODI5ZTU3NzE1MmMzMTEwZWU1ODFkNjVlNTNjNjRh"
    "NGU4ZjU3OGQ+Ci9VIDxiYmI4NWZiYjczNzFiYjg4MWVkNDZhOGUyOTI4NTBiNjI4"
    "YmY0ZTVlNGU3NThhNDE2NDAwNGU1NmZmZmEwMTA4Pgo+PgplbmRvYmoKeHJlZgow"
    "IDYKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDE1IDAwMDAwIG4gCjAwMDAw"
    "MDAwNTkgMDAwMDAgbiAKMDAwMDAwMDExOCAwMDAwMCBuIAowMDAwMDAwMTY3IDAw"
    "MDAwIG4gCjAwMDAwMDAyNTkgMDAwMDAgbiAKdHJhaWxlcgo8PAovU2l6ZSA2Ci9S"
    "b290IDMgMCBSCi9JbmZvIDEgMCBSCi9JRCBbIDw2NDY2NjM2MTY2MzUzNDMyMzcz"
    "OTMwMzMzMjMwMzY2NDY0MzEzMTM0MzQzMTY0MzA2MjM1NjI2MTM5MzYzMTYyPiA8"
    "NjQ2NjYzNjE2NjM1MzQzMjM3MzkzMDMzMzIzMDM2NjQ2NDMxMzEzNDM0MzE2NDMw"
    "NjIzNTYyNjEzOTM2MzE2Mj4gXQovRW5jcnlwdCA1IDAgUgo+PgpzdGFydHhyZWYK"
    "NDc0CiUlRU9GCg=="
)

# This has a PDF header but no recoverable body, xref table, or trailer.  Both
# readers report their documented format-error status, rather than repairing it.
TRUNCATED_PDF = b"%PDF-1.7\n"


def available_backends():
    backends = []
    if importlib.util.find_spec("pypdfium2"):
        backends.append("pdfium")
    if importlib.util.find_spec("fitz"):
        backends.append("pymupdf")
    return backends


class InputErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not available_backends():
            raise unittest.SkipTest("no shipped PDF backend is installed")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.encrypted = self._fixture("encrypted.pdf", ENCRYPTED_PDF)
        self.truncated = self._fixture("truncated.pdf", TRUNCATED_PDF)
        self.dest = os.path.join(self.temp.name, "existing.docx")
        with open(self.dest, "wb") as fh:
            fh.write(b"known-good destination bytes")
        with open(self.dest, "rb") as fh:
            self.before = fh.read()

    def tearDown(self):
        # PyMuPDF may retain a native stream through the chained FileDataError
        # until its cycle is collected.  Collect before Windows unlinks the
        # generated malformed input, so the test itself leaves no fixture file.
        gc.collect()
        self.temp.cleanup()

    def _fixture(self, name, data):
        path = os.path.join(self.temp.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def _convert(self, backend, path):
        return convert(path, self.dest, options=RAW.replace(backend=backend))

    def _assert_destination_unchanged(self):
        with open(self.dest, "rb") as fh:
            self.assertEqual(fh.read(), self.before)
        self.assertEqual(
            [n for n in os.listdir(self.temp.name) if n.startswith(".exactdoc-")],
            [],
        )

    def test_api_uses_safe_typed_errors_before_publication(self):
        cases = ((self.encrypted, UnsupportedInputError, "unsupported-input"),
                 (self.truncated, ParseError, "parse"))
        for backend in available_backends():
            for path, error_type, code in cases:
                with self.subTest(backend=backend, source=os.path.basename(path)):
                    with self.assertRaises(error_type) as raised:
                        self._convert(backend, path)
                    error = raised.exception
                    self.assertEqual(error.code, code)
                    self.assertIsNone(error.detail)
                    self.assertNotIn(path, error.message)
                    self.assertNotIn("pdfium", error.message.lower())
                    self.assertNotIn("fitz", error.message.lower())
                    self.assertNotIn("user", error.message.lower())
                    self._assert_destination_unchanged()

    def test_cli_has_stable_exit_codes_without_tracebacks(self):
        cases = ((self.encrypted, 5), (self.truncated, 6))
        for backend in available_backends():
            for path, code in cases:
                with self.subTest(backend=backend, source=os.path.basename(path)):
                    proc = subprocess.run(
                        [sys.executable, "-m", "exactdoc.cli", path,
                         "--backend", backend, "--refine", "0", "-o", self.dest],
                        cwd=ROOT, text=True, capture_output=True, check=False,
                    )
                    self.assertEqual(proc.returncode, code, proc.stderr)
                    self.assertIn("error:", proc.stderr)
                    self.assertNotIn("Traceback", proc.stderr)
                    self.assertNotIn(path, proc.stderr)
                    self._assert_destination_unchanged()

    def test_unexpected_parser_errors_are_not_reclassified(self):
        class BrokenBackend:
            name = "pdfium"

            def parse_pdf(self, path, keep_image_data=True):
                raise ValueError("programmer defect")

        with mock.patch("exactdoc.convert._select_backend",
                        return_value=BrokenBackend()):
            with self.assertRaisesRegex(ValueError, "programmer defect"):
                self._convert("pdfium", self.truncated)
        self._assert_destination_unchanged()


if __name__ == "__main__":
    unittest.main()
