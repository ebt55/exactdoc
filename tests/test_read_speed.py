"""Reading text lines faster changes no answer (WP20c).

Three shortcuts, each against the path it replaces:

  * parse_pdf(measure_lines=True) hands the refine loop the source's
    page_lines from the parse's own PDFium reading;
  * a long render is read by worker processes, a slice each (_pagelines_pool);
  * (the faster LibreOffice export is in tests/test_soffice_session.py).

The corpus-wide proof is docs/evidence/refine-speed-2026-10-05c.json.

    python -m unittest tests.test_read_speed
"""
import os
import pickle
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import _pagelines_pool as P                      # noqa: E402
from exactdoc import parse_pdfium as PP                        # noqa: E402

FIX = os.path.join(ROOT, "testkit", "fixtures")
DOCS = ("c1_whitepaper.pdf", "03_tech_report_code.pdf", "c6_long.pdf")


def _ir_state(ir):
    d = dict(ir.__dict__)
    d.pop("page_lines", None)
    return pickle.dumps(d, 4)


class SourceLinesFromTheParse(unittest.TestCase):
    def test_the_parse_gives_page_lines_and_an_unchanged_ir(self):
        for doc in DOCS:
            path = os.path.join(FIX, doc)
            with self.subTest(doc=doc):
                plain = PP.parse_pdf(path, keep_image_data=False)
                meas = PP.parse_pdf(path, keep_image_data=False, measure_lines=True)
                self.assertEqual(meas.page_lines, PP.page_lines_range(path))
                self.assertEqual(_ir_state(plain), _ir_state(meas))
                self.assertIsNone(plain.page_lines)

    def test_not_for_the_image_ocr_mode(self):
        ir = PP.parse_pdf(os.path.join(FIX, DOCS[0]), keep_image_data=False,
                          ocr_layer="image", measure_lines=True)
        self.assertIsNone(ir.page_lines)

    def test_copied_characters_keep_their_unset_slots_unset(self):
        c = PP._Char()
        c.u, c.x0 = "a", 1.5
        (n,) = PP._copy_chars([c])
        self.assertIsNot(n, c)
        self.assertEqual((n.u, n.x0, n.sup, n.vi), ("a", 1.5, False, -1))
        self.assertFalse(hasattr(n, "ix0"))
        self.assertFalse(hasattr(n, "y0"))

    def test_convert_hands_the_lines_to_the_refine_loop(self):
        from exactdoc.convert import convert_result
        from exactdoc.options import PRODUCT, RAW
        seen = {}

        def fake_refine(lay, src, out, **kw):
            seen.update(kw)
            raise SystemExit(0)

        path = os.path.join(FIX, DOCS[0])
        with mock.patch("exactdoc.refine.refine", side_effect=fake_refine), \
                mock.patch("exactdoc.targets.get_renderer",
                           return_value=(object(), "libreoffice")):
            with self.assertRaises(SystemExit):
                convert_result(path, os.path.join(ROOT, "unused.docx"),
                               options=PRODUCT)
        self.assertEqual(seen["src_page_lines"], PP.page_lines_range(path))
        # open-loop: nothing extra is read
        with mock.patch.object(PP, "_copy_chars", side_effect=AssertionError):
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                convert_result(path, os.path.join(d, "o.docx"), options=RAW)

    def test_the_loop_does_not_read_the_source_again(self):
        from exactdoc import refine as R
        calls = []

        class Bk:
            name = "pdfium"

            def page_lines(self, p):
                calls.append(p)
                return [[("Rendered heading line", 10.0, 20.0, 22.0)]]

        src = [[("Rendered heading line", 10.0, 20.0, 22.0)]]
        cache = {"lines": R._lines_from_page_lines(src)}
        m = R._measure("source.pdf", "render.pdf", Bk(), src_cache=cache)
        self.assertEqual(calls, ["render.pdf"])
        self.assertEqual(m["out_pages"], 1)


class WorkerPool(unittest.TestCase):
    def test_slices_cover_every_page_once_in_order(self):
        for pages in (1, 7, 16, 57, 165):
            for workers in (1, 2, 3, 4):
                s = P._slices(pages, workers)
                flat = [i for a, b in s for i in range(a, b)]
                self.assertEqual(flat, list(range(pages)), (pages, workers))

    def test_worker_count(self):
        with mock.patch.dict(os.environ, {"EXACTDOC_READ_WORKERS": ""}), \
                mock.patch.object(P.os, "cpu_count", return_value=8):
            self.assertEqual(P.read_workers(10), 1)
            self.assertEqual(P.read_workers(20), 2)
            self.assertEqual(P.read_workers(200), 4)
        with mock.patch.object(P.os, "cpu_count", return_value=2), \
                mock.patch.dict(os.environ, {"EXACTDOC_READ_WORKERS": ""}):
            self.assertEqual(P.read_workers(200), 1)
        with mock.patch.dict(os.environ, {"EXACTDOC_READ_WORKERS": "1"}):
            self.assertEqual(P.read_workers(500), 1)
        with mock.patch.dict(os.environ, {"EXACTDOC_READ_WORKERS": "3"}):
            self.assertEqual(P.read_workers(5), 3)

    def test_pooled_lines_are_the_serial_lines(self):
        path = os.path.join(FIX, "c6_long.pdf")
        n = P._page_count(path)
        self.assertGreaterEqual(n, 3)
        self.assertEqual(P.page_lines_parallel(path, n, 3), PP.page_lines_range(path))

    def test_a_failing_worker_falls_back_to_the_serial_read(self):
        path = os.path.join(FIX, "c6_long.pdf")
        with mock.patch.object(P.sys, "executable", os.path.join(ROOT, "no-python")), \
                mock.patch.dict(os.environ, {"EXACTDOC_READ_WORKERS": "2"}):
            self.assertIsNone(P.page_lines_parallel(path, P._page_count(path), 2))
            self.assertEqual(P.page_lines(path), PP.page_lines_range(path))


if __name__ == "__main__":
    unittest.main()
