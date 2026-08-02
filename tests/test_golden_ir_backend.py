"""Hermetic contract tests for backend-namespaced parser goldens.

    python tests/test_golden_ir_backend.py
"""
import inspect
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import golden_ir  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print("  %-4s %s%s" % ("ok" if cond else "FAIL", name,
                           "" if cond else "   <-- " + detail))
    if not cond:
        FAILED.append(name)


def _with_gold(callback):
    old_gold, old_corpus, old_digest = golden_ir.GOLD, golden_ir.corpus, golden_ir.digest
    with tempfile.TemporaryDirectory() as root:
        golden_ir.GOLD = root
        golden_ir.corpus = lambda backend: [os.path.join(root, "case.pdf")]
        try:
            return callback(root)
        finally:
            golden_ir.GOLD, golden_ir.corpus, golden_ir.digest = old_gold, old_corpus, old_digest


def test_default_uses_product_backend_and_records_its_package():
    from exactdoc.options import PRODUCT
    manifest = golden_ir.manifest()
    check("default backend is PRODUCT.backend",
          golden_ir.selected_backend() == PRODUCT.backend)
    check("manifest names selected backend", manifest["backend"] == PRODUCT.backend)
    check("manifest includes selected backend package",
          golden_ir.BACKEND_PACKAGES[PRODUCT.backend] in manifest, repr(manifest))


def test_shipping_mupdf_uses_legacy_flat_path_and_candidate_is_namespaced():
    def run(root):
        check("shipping PyMuPDF uses flat golden",
              golden_ir.golden_path("case", "pymupdf")
              == os.path.join(root, "case.json"))
        check("PDFium candidate is namespaced",
              golden_ir.golden_path("case", "pdfium")
              == os.path.join(root, "pdfium", "case.json"))
    _with_gold(run)


def test_verification_refuses_cross_backend_golden():
    def run(root):
        path = golden_ir.golden_path("case", "pdfium")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"backend": "pymupdf", "manifest": {}, "pages": []}, f)
        called = []
        golden_ir.digest = lambda *a, **kw: called.append((a, kw))
        status = golden_ir.verify("pdfium")
        check("cross-backend golden fails", status == 1, str(status))
        check("mismatch does not compare parser output", not called, repr(called))
    _with_gold(run)


def test_legacy_mupdf_files_are_not_silently_reused_for_pdfium():
    def run(root):
        with open(os.path.join(root, "case.json"), "w") as f:
            json.dump({"backend": "pymupdf"}, f)
        golden_ir.digest = lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("missing PDFium golden must not digest"))
        check("legacy MuPDF file cannot satisfy PDFium verify",
              golden_ir.verify("pdfium") == 1)
    _with_gold(run)


def test_legacy_flat_golden_requires_matching_pymupdf_identity():
    def run(root):
        with open(os.path.join(root, "case.json"), "w") as f:
            json.dump({"backend": "pymupdf",
                       "manifest": {"pymupdf": "definitely-not-installed"},
                       "pages": []}, f)
        called = []
        golden_ir.digest = lambda *a, **kw: called.append((a, kw))
        check("extractor package mismatch fails",
              golden_ir.verify("pymupdf") == 1)
        check("identity mismatch is rejected before parsing", not called,
              repr(called))
    _with_gold(run)


def test_tool_uses_backend_seam_not_hard_mupdf_imports():
    src = inspect.getsource(golden_ir)
    check("golden tool imports the backend seam", "from exactdoc.backend import get_backend" in src)
    check("golden tool does not import exactdoc.parse", "from exactdoc.parse import" not in src)
    check("golden tool has no direct fitz import", "import fitz" not in src)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print("golden backend tests (%d)" % len(tests))
    for test in tests:
        print("\n%s" % test.__name__)
        test()
    print("\n%s" % ("all clear" if not FAILED else "%d FAILED: %s" %
                       (len(FAILED), ", ".join(FAILED))))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
