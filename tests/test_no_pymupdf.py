"""The permissive runtime boundary: convert with PyMuPDF physically absent.

This is the test the Apache alpha rests on, and it is deliberately hostile: it
does not check that `fitz` *is not used*, it makes importing it **impossible** and
then converts real documents. A check that trusts the code to avoid an import is a
check that passes the moment someone adds one back.

The mechanism is a `sys.meta_path` finder that raises ImportError for `fitz` and
`pymupdf`, plus eviction of anything already imported. That is stricter than a
clean virtualenv without the package, because it also catches a module that has
already been imported by something else in the same interpreter.

Why this test exists at all: the wheel was described as one dependency-metadata
change away from Apache-2.0. It was not. `docxout` imported `fitz` at module
scope, so a wheel installed without PyMuPDF failed while importing the *writer* --
before any backend selection could happen -- and MuPDF was additionally reached
for table text metrics, figure rasterisation, refinement text extraction, verifier
rasterisation and the quality ladder. "Mechanical" was five stages out of date.

    python tests/test_no_pymupdf.py                # needs pypdfium2
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BLOCKED = ("fitz", "pymupdf", "fitz_new", "pymupdf.mupdf")
FAILED = []


class _Blocker:
    """Refuse to import PyMuPDF, however it is spelled."""

    def find_module(self, name, path=None):            # py2-style, still consulted
        return self if self._blocked(name) else None

    def find_spec(self, name, path=None, target=None):
        if self._blocked(name):
            raise ImportError(
                "PyMuPDF is deliberately unavailable in this test: %r must not be "
                "on the default runtime path (tests/test_no_pymupdf.py)" % name)
        return None

    @staticmethod
    def _blocked(name):
        return name in BLOCKED or name.split(".")[0] in ("fitz", "pymupdf")

    def load_module(self, name):
        raise ImportError(name)


def check(name, cond, detail=""):
    print("  %-4s %s%s" % ("ok" if cond else "FAIL", name,
                           "" if cond else "   <-- " + detail))
    if not cond:
        FAILED.append(name)


def block_pymupdf():
    for mod in list(sys.modules):
        if _Blocker._blocked(mod):
            del sys.modules[mod]
    sys.meta_path.insert(0, _Blocker())


def _fixture_dirs():
    """Whatever corpus this machine has. The fixtures are not regenerated here."""
    out = []
    for d in ("testkit/adv", "corpus/pdfs"):
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            out.append(p)
    return out


def representative_fixtures():
    """One document per capability the plan names, when the corpus has it.

    Skipping absent documents rather than failing: this test can run on a clean
    machine with no generators installed, and its subject is the import boundary,
    not the corpus. The corpus manifest is what makes corpus completeness a
    failure, in the gate where that belongs.
    """
    want = {
        "05_memo.pdf": "text only",
        "c3_tables.pdf": "grid and ruled tables",
        "04_exec_brief.pdf": "inline image",
        "c5_graphics.pdf": "vector region rasterised as a figure clip",
        "c6_long.pdf": "multi-page, exercises refinement",
        "c2_paper2col.pdf": "multi-column sections",
        "01_whitepaper_market.pdf": "cover band, callouts, charts",
    }
    found = []
    for d in _fixture_dirs():
        for name in sorted(os.listdir(d)):
            if name in want:
                found.append((name, want[name], os.path.join(d, name)))
    return found


def main():
    print("permissive runtime boundary: PyMuPDF made unimportable\n")
    block_pymupdf()

    try:
        import fitz            # noqa: F401
        check("fitz is unimportable", False, "the blocker did not engage")
        return 1
    except ImportError:
        check("fitz is unimportable", True)

    try:
        import pypdfium2       # noqa: F401
    except ImportError:
        print("\npypdfium2 is not installed -- this test needs the permissive "
              "backend it is about. Install the [pdfium] extra.")
        return 2

    # 1. import surface
    import exactdoc
    check("import exactdoc", True)
    check("exactdoc.__version__ resolves", bool(exactdoc.__version__),
          repr(exactdoc.__version__))
    from exactdoc.convert import convert                       # noqa: F401
    check("import exactdoc.convert", True)
    from exactdoc import docxout                               # noqa: F401
    check("import exactdoc.docxout", True)
    from exactdoc import refine, verify, infer, dialect        # noqa: F401
    check("import refine/verify/infer/dialect", True)
    check("fitz never entered sys.modules", "fitz" not in sys.modules)

    # 2. the writer must not be carrying a MuPDF text-metric dependency
    from exactdoc.metrics import NullMetrics, get_metrics
    check("metrics default is permissive", get_metrics().name == "none")
    check("mupdf metrics degrade rather than raise",
          isinstance(get_metrics("mupdf"), NullMetrics))

    # 3. real conversions through the permissive path
    from exactdoc.options import PRODUCT, RAW
    fixtures = representative_fixtures()
    if not fixtures:
        print("\nno corpus documents found -- generate them to exercise "
              "conversion. The import boundary above still held.")
        return 1 if FAILED else 0

    opts = RAW.replace(backend="pdfium", target="none")
    with tempfile.TemporaryDirectory() as td:
        for name, why, path in fixtures:
            out = os.path.join(td, name.replace(".pdf", ".docx"))
            try:
                convert(path, out, options=opts)
                ok = os.path.exists(out) and os.path.getsize(out) > 1000
                check("convert %-26s (%s)" % (name, why), ok,
                      "no output" if not ok else "")
            except Exception as e:
                check("convert %-26s (%s)" % (name, why), False,
                      "%s: %s" % (type(e).__name__, e))

        # 4. refinement through the permissive path, if an oracle is present
        from exactdoc.verify import SOFFICE
        multi = [f for f in fixtures if f[0] == "c6_long.pdf"] or fixtures[:1]
        if SOFFICE and multi:
            name, _, path = multi[0]
            out = os.path.join(td, "refined.docx")
            try:
                convert(path, out, options=PRODUCT.replace(backend="pdfium"))
                check("refine %s through the permissive path" % name,
                      os.path.exists(out) and os.path.getsize(out) > 1000)
            except Exception as e:
                check("refine %s through the permissive path" % name, False,
                      "%s: %s" % (type(e).__name__, e))
        else:
            print("  --   refinement skipped: no LibreOffice on this machine")

        # 5. the Google-Docs-safe static profile is a writer path, not an oracle
        name, _, path = fixtures[0]
        try:
            convert(path, os.path.join(td, "gdocs.docx"),
                    options=RAW.replace(backend="pdfium", target="gdocs"))
            check("gdocs static profile writes", True)
        except Exception as e:
            check("gdocs static profile writes", False,
                  "%s: %s" % (type(e).__name__, e))

    check("fitz still absent after converting", "fitz" not in sys.modules)
    if FAILED:
        print("\n%d FAILED: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    from exactdoc.options import PRODUCT
    print("\nall clear -- every code path runs without PyMuPDF.\n"
          "NOTE: the shipped default backend is still %r and `pymupdf` is still a\n"
          "hard runtime dependency in pyproject.toml. What this test proves is\n"
          "that the licence flip is now a dependency-and-default change rather\n"
          "than a rewrite -- not that the default artifact is already permissive."
          % PRODUCT.backend)
    return 0


if __name__ == "__main__":
    sys.exit(main())
