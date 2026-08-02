"""Bounded batch and conservative OCR-required contracts."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from exactdoc.batch import BatchItem, discover, make_items, run
from exactdoc.convert import convert
from exactdoc.errors import (ConfigurationError, OcrRequiredError, ParseError,
                             ResourceLimitError)
from exactdoc.model import DocIR, ImageObj, PageIR
from exactdoc.options import RAW
from exactdoc.scan import ScanReport, classify_ir, inspect_pdf

ROOT = Path(__file__).resolve().parents[1]


class _Backend:
    name = "pdfium"

    def __init__(self, ir): self.ir = ir
    def parse_pdf(self, _path, keep_image_data=False): return self.ir


def _page(text="", image_box=None):
    from exactdoc.model import Line, Span, TextBlock
    blocks = []
    if text:
        span = Span(text, "Arial", 10, "#000000", False, False, False, False,
                    False, (0, 0, 10, 10), (0, 8))
        blocks = [TextBlock([Line([span], (0, 0, 10, 10))], (0, 0, 10, 10))]
    images = [ImageObj(image_box, 1, 100, 100)] if image_box else []
    return PageIR(1, 100, 100, blocks=blocks, images=images)


class ScanUnitTests(unittest.TestCase):
    def test_conservative_classes_and_tiny_logo(self):
        cases = {
            "ocr_required": [_page("x", (0, 0, 100, 100))],
            "blank": [_page()],
            "digital": [_page("short", (0, 0, 10, 10))],
            "mixed": [_page("ordinary digital document with enough text"),
                      _page("", (0, 0, 100, 100))],
        }
        for expected, pages in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(classify_ir(DocIR("private.pdf", pages)).classification,
                                 expected)


class BatchTests(unittest.TestCase):
    def test_discovery_is_root_only_without_recursive_and_excludes_nested_out(self):
        with tempfile.TemporaryDirectory() as td:
            root, output = Path(td) / "in", Path(td) / "in" / "out"
            (root / "nested").mkdir(parents=True); output.mkdir()
            (root / "Z.PDF").write_bytes(b"%PDF")
            (root / "nested" / "a.pdf").write_bytes(b"%PDF")
            (output / "old.pdf").write_bytes(b"%PDF")
            self.assertEqual([p.name for p in discover(root, output, False)], ["Z.PDF"])
            self.assertEqual([p.name for p in discover(root, output, True)], ["a.pdf", "Z.PDF"])

    def test_output_ancestor_does_not_hide_input_children(self):
        with tempfile.TemporaryDirectory() as td:
            out, root = Path(td) / "out", Path(td) / "out" / "in"
            (root / "nested").mkdir(parents=True)
            (root / "nested" / "a.pdf").write_bytes(b"%PDF")
            self.assertEqual([p.name for p in discover(root, out, True)], ["a.pdf"])

    def test_symlinked_directory_is_not_followed_when_supported(self):
        with tempfile.TemporaryDirectory() as td:
            root, outside, out = Path(td) / "in", Path(td) / "outside", Path(td) / "out"
            root.mkdir(); outside.mkdir()
            (outside / "hidden.pdf").write_bytes(b"%PDF")
            try:
                (root / "linked").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable in this environment")
            self.assertEqual(discover(root, out, True), [])

    def test_empty_batch_and_workers_are_clear_configuration_errors(self):
        with tempfile.TemporaryDirectory() as td:
            root, out = Path(td) / "in", Path(td) / "out"
            root.mkdir()
            with self.assertRaises(ConfigurationError): make_items(root, out)
            source = Path(td) / "a.pdf"; source.write_bytes(b"%PDF")
            item = BatchItem(source, "a.pdf", out / "a.docx", "a.docx")
            with self.assertRaises(ConfigurationError):
                run([item], backend="pdfium", dpi=72, refine_rounds=0,
                    output_profile="gdocs", oracle="none", workers=2)

    def test_casefold_output_collision_is_rejected_before_work(self):
        with tempfile.TemporaryDirectory() as td:
            root, out = Path(td) / "in", Path(td) / "out"; root.mkdir()
            with mock.patch("exactdoc.batch.discover",
                            return_value=[root / "a.pdf", root / "A.PDF"]):
                with self.assertRaises(ConfigurationError):
                    make_items(root, out)

    def test_ocr_failure_stops_or_continues_and_scan_output_is_null(self):
        with tempfile.TemporaryDirectory() as td:
            root, out = Path(td) / "in", Path(td) / "out"; root.mkdir()
            for name in ("a.pdf", "b.pdf"): (root / name).write_bytes(b"%PDF")
            items = make_items(root, out)
            reports = [ScanReport("ocr_required", 1, 1), ScanReport("digital", 1, 100)]
            with mock.patch("exactdoc.batch.inspect_pdf", side_effect=reports):
                stopped = run(items, backend="pdfium", dpi=72, refine_rounds=0,
                              output_profile="gdocs", oracle="none", scan_only=True)
            self.assertEqual([r["status"] for r in stopped["items"]], ["ocr_required", "skipped"])
            self.assertIsNone(stopped["items"][0]["output"])
            self.assertIsNone(stopped["items"][1]["output"])
            with mock.patch("exactdoc.batch.inspect_pdf", side_effect=reports):
                continued = run(items, backend="pdfium", dpi=72, refine_rounds=0,
                                output_profile="gdocs", oracle="none", scan_only=True,
                                continue_on_error=True)
            self.assertEqual([r["status"] for r in continued["items"]], ["ocr_required", "would_convert"])

    def test_failed_json_is_relative_and_valid(self):
        with tempfile.TemporaryDirectory() as td:
            root, out = Path(td) / "in", Path(td) / "out"; root.mkdir()
            (root / "a.pdf").write_bytes(b"%PDF")
            result = Path(td) / "result.json"
            with mock.patch("exactdoc.batch.inspect_pdf", side_effect=ParseError("bad PDF")):
                report = run(make_items(root, out), backend="pdfium", dpi=72,
                             refine_rounds=0, output_profile="gdocs", oracle="none",
                             scan_only=True, result_json=result)
            saved = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(saved, report)
            self.assertEqual(saved["items"][0]["status"], "failed")
            self.assertNotIn(str(root), result.read_text(encoding="utf-8"))

    def test_result_report_cannot_replace_source_or_output(self):
        with tempfile.TemporaryDirectory() as td:
            root, out = Path(td) / "in", Path(td) / "out"; root.mkdir(); out.mkdir()
            source = root / "a.pdf"; source.write_bytes(b"source bytes")
            output = out / "a.docx"; output.write_bytes(b"output bytes")
            item = BatchItem(source, "a.pdf", output, "a.docx")
            for report in (source, output):
                with self.subTest(report=report.name):
                    before = report.read_bytes()
                    with self.assertRaises(ConfigurationError):
                        run([item], backend="pdfium", dpi=72, refine_rounds=0,
                            output_profile="gdocs", oracle="none", scan_only=True,
                            result_json=report)
                    self.assertEqual(report.read_bytes(), before)

    def test_cli_rejects_batch_flags_without_input_dir(self):
        proc = subprocess.run([sys.executable, "-m", "exactdoc.cli", "x.pdf", "--workers", "2"],
                              cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("batch options require --input-dir", proc.stderr)

    def test_cheap_size_limit_is_preflighted_and_page_limit_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root, out = Path(td) / "in", Path(td) / "out"; root.mkdir()
            source = root / "a.pdf"; source.write_bytes(b"%PDF")
            item = make_items(root, out)[0]
            with mock.patch("exactdoc.batch.MAX_BYTES_PER_DOCUMENT", 1):
                with self.assertRaises(ResourceLimitError) as raised:
                    run([item], backend="pdfium", dpi=72, refine_rounds=0,
                        output_profile="gdocs", oracle="none", scan_only=True)
                self.assertEqual(getattr(raised.exception, "code", None), "resource-limit")
            with mock.patch("exactdoc.batch.inspect_pdf",
                            return_value=ScanReport("digital", 251, 100)):
                report = run([item], backend="pdfium", dpi=72, refine_rounds=0,
                             output_profile="gdocs", oracle="none", scan_only=True)
            self.assertEqual(report["items"][0]["error"]["code"], "resource-limit")


@unittest.skipUnless(importlib.util.find_spec("reportlab") and
                     importlib.util.find_spec("pypdfium2"),
                     "reportlab and PDFium are optional test dependencies")
class RealPdfiumScanTests(unittest.TestCase):
    def _files(self):
        from PIL import Image
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen.canvas import Canvas
        td = tempfile.TemporaryDirectory(); root = Path(td.name)
        image = root / "scan.png"; Image.new("RGB", (200, 200), "black").save(image)
        def make(name, draw):
            path = root / name; c = Canvas(str(path), pagesize=(200, 200)); draw(c); c.showPage(); c.save(); return path
        blank = make("blank.pdf", lambda c: None)
        digital = make("digital.pdf", lambda c: c.drawString(20, 100, "ordinary digital PDF text"))
        scan = make("scan.pdf", lambda c: c.drawImage(ImageReader(str(image)), 0, 0, 200, 200))
        def mixed_draw(c):
            c.drawString(20, 100, "ordinary digital PDF text sufficient for this page"); c.showPage()
            c.drawImage(ImageReader(str(image)), 0, 0, 200, 200)
        mixed = make("mixed.pdf", mixed_draw)
        return td, {"blank": blank, "digital": digital, "ocr_required": scan, "mixed": mixed}

    def test_pdfium_integration_and_normal_conversion_refusal(self):
        td, paths = self._files()
        try:
            from exactdoc.backend import get_backend
            backend = get_backend("pdfium")
            for expected, path in paths.items():
                with self.subTest(expected=expected):
                    self.assertEqual(inspect_pdf(backend, str(path)).classification, expected)
            destination = Path(td.name) / "scan.docx"
            with self.assertRaises(OcrRequiredError):
                convert(str(paths["ocr_required"]), str(destination),
                        options=RAW.replace(backend="pdfium"))
            self.assertFalse(destination.exists())
        finally:
            td.cleanup()

    def test_cli_exit_17_and_batch_partial_18(self):
        td, paths = self._files()
        try:
            command = [sys.executable, "-m", "exactdoc.cli", str(paths["ocr_required"]),
                       "--backend", "pdfium", "--refine", "0"]
            self.assertEqual(subprocess.run(command, cwd=ROOT, capture_output=True).returncode, 17)
            self.assertEqual(subprocess.run(command + ["--scan-only"], cwd=ROOT,
                                            capture_output=True).returncode, 17)
            directory, output = Path(td.name) / "batch", Path(td.name) / "out"
            directory.mkdir(); (directory / "scan.pdf").write_bytes(paths["ocr_required"].read_bytes())
            (directory / "digital.pdf").write_bytes(paths["digital"].read_bytes())
            proc = subprocess.run([sys.executable, "-m", "exactdoc.cli", "--input-dir", str(directory),
                                   "--out-dir", str(output), "--backend", "pdfium", "--scan-only",
                                   "--continue-on-error"], cwd=ROOT, capture_output=True)
            self.assertEqual(proc.returncode, 18, proc.stderr)
        finally:
            td.cleanup()

    def test_frozen_corpus_has_no_ocr_required_false_positive(self):
        from exactdoc.backend import get_backend
        backend = get_backend("pdfium")
        for source in sorted((ROOT / "testkit" / "fixtures").glob("*.pdf")):
            with self.subTest(source=source.name):
                self.assertNotEqual(inspect_pdf(backend, str(source)).classification,
                                    "ocr_required")


if __name__ == "__main__":
    unittest.main()
