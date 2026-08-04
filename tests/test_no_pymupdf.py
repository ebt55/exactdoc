"""The explicit PDFium candidate works with PyMuPDF physically absent.

This candidate-isolation test is deliberately hostile: it
does not check that `fitz` *is not used*, it makes importing it **impossible** and
then converts real documents. A check that trusts the code to avoid an import is a
check that passes the moment someone adds one back.

The mechanism is a `sys.meta_path` finder that raises ImportError for `fitz` and
`pymupdf`, plus eviction of anything already imported. That is stricter than a
clean virtualenv without the package, because it also catches a module that has
already been imported by something else in the same interpreter.

It guards the backend seam end to end: writer imports, text metrics, figure
rasterisation, refinement text extraction, verifier rasterisation and the quality
ladder must all honor the explicitly selected PDFium candidate.

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
                "on the explicit candidate path (tests/test_no_pymupdf.py)" % name)
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


# The only module allowed to need PyMuPDF: the shipping parser itself. Every
# other reference in the package is lazy -- inside a function, on the PyMuPDF
# backend's own code path -- which is what makes a PyMuPDF-free install able to
# import the writer at all. `docxout` carried a top-level `import fitz` once and
# a wheel without PyMuPDF failed while *importing the writer*, before any
# conversion was attempted.
#
# The rule below is a SUBSET rule, not equality, and the asymmetry is
# deliberate: shrinking the seam is progress toward the Apache-2.0 target and
# must not need a test edit, while growing it by one module is red immediately.
PYMUPDF_SEAM = {"parse"}


def package_modules():
    """Every module in the package, enumerated rather than listed by hand.

    A hardcoded list goes stale the moment someone adds a module -- and the
    module nobody remembered to add is exactly where a stray top-level
    `import fitz` would sit unnoticed.
    """
    pkg = os.path.join(ROOT, "exactdoc")
    return sorted(f[:-3] for f in os.listdir(pkg)
                  if f.endswith(".py") and f != "__init__.py")


def _blames_pymupdf(exc):
    return any(root in str(exc).lower() for root in ("fitz", "pymupdf"))


def declared_core_dependencies():
    """The `[project].dependencies` block, as text, or None.

    Read as text rather than through `tomllib`: the package declares
    `requires-python = ">=3.9"` and this test has to run wherever the package
    does, which is three releases before tomllib existed.
    """
    try:
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    start = text.find("\ndependencies = [")
    if start == -1:
        return None
    end = text.find("]", start)
    return text[start:end] if end != -1 else None


def block_pymupdf():
    for mod in list(sys.modules):
        if _Blocker._blocked(mod):
            del sys.modules[mod]
    sys.meta_path.insert(0, _Blocker())


# One document per capability that has to survive the candidate path. Every one
# of these is a COMMITTED fixture in testkit/fixtures/, so "absent" means the
# checkout is broken, not that the machine lacks generators.
CAPABILITIES = {
    "05_memo.pdf": "text only",
    "c3_tables.pdf": "grid and ruled tables",
    "04_exec_brief.pdf": "inline image",
    "c5_graphics.pdf": "vector region rasterised as a figure clip",
    "c6_long.pdf": "multi-page, exercises refinement",
    "c2_paper2col.pdf": "multi-column sections",
    "c4_i18n.pdf": "CJK, Arabic and Hebrew",
    "01_whitepaper_market.pdf": "cover band, callouts, charts",
}


def _fixture_dirs():
    """Where the committed corpus lives, most authoritative first.

    `testkit/fixtures/` was missing from this list, and that was the whole bug:
    it is the only directory that exists in a clean checkout. `testkit/adv/` and
    `corpus/pdfs/` are *generated* and are both gitignored, so on CI and on any
    fresh clone this function returned an empty list -- and the caller then
    reported success having converted nothing.
    """
    out = []
    for d in ("testkit/fixtures", "testkit/adv", "corpus/pdfs"):
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            out.append(p)
    return out


def representative_fixtures():
    """One document per capability, resolved against the committed fixtures.

    Deduplicated by filename with the earliest directory winning, so a stale
    generated copy in `testkit/adv/` cannot shadow the frozen, SHA-256-pinned
    input the manifest describes.
    """
    found, seen = [], set()
    for d in _fixture_dirs():
        for name in sorted(os.listdir(d)):
            if name in CAPABILITIES and name not in seen:
                seen.add(name)
                found.append((name, CAPABILITIES[name], os.path.join(d, name)))
    return sorted(found)


def missing_capabilities(found):
    return sorted(set(CAPABILITIES) - {name for name, _, _ in found})


def main():
    print("explicit PDFium candidate: PyMuPDF made unimportable\n")
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
        print("\npypdfium2 is not installed -- install the optional pdfium "
              "extra for this candidate test.")
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
    check("pymupdf never entered sys.modules either",
          "pymupdf" not in sys.modules,
          "the package is importable under two names and blocking one is not "
          "blocking the dependency")

    # 1b. The seam, measured across the WHOLE package rather than the handful of
    # modules this test happens to reach. The checks above import ten modules by
    # name; a top-level `import fitz` in any of the other fourteen would not be
    # noticed here, and would break a PyMuPDF-free install at import time.
    import importlib
    clean, blocked, broken = [], [], []
    for name in package_modules():
        try:
            importlib.import_module("exactdoc." + name)
            clean.append(name)
        except ImportError as exc:
            (blocked if _blames_pymupdf(exc) else broken).append((name, exc))
        except Exception as exc:                       # noqa: BLE001
            broken.append((name, exc))
    blocked_names = {name for name, _ in blocked}
    check("the whole package was enumerated", len(package_modules()) > 10,
          "found %d modules" % len(package_modules()))
    check("the PyMuPDF seam has not grown beyond %s"
          % ", ".join(sorted(PYMUPDF_SEAM)),
          blocked_names <= PYMUPDF_SEAM,
          "these modules need PyMuPDF to import and are not the declared seam: "
          "%s. A top-level PyMuPDF import outside the parser breaks a "
          "PyMuPDF-free install before any conversion is attempted."
          % ", ".join(sorted(blocked_names - PYMUPDF_SEAM)))
    check("no module failed to import for a non-PyMuPDF reason", not broken,
          "; ".join("%s: %s: %s" % (n, type(e).__name__, e) for n, e in broken))
    print("     %d of %d modules import with PyMuPDF unimportable; seam = %s"
          % (len(clean), len(package_modules()),
             ", ".join(sorted(blocked_names)) or "none"))

    # 1c. What this test does NOT prove, stated so nobody mistakes it for the
    # base-wheel proof. Blocking an import inside an interpreter that still has
    # PyMuPDF on disk is not the same as installing without it -- and today it
    # cannot be, because PyMuPDF is a hard core dependency, so a PyMuPDF-free
    # install is impossible by construction. See docs/license-audit.md gate (c).
    core = declared_core_dependencies()
    check("pyproject declares a core dependency list", core is not None,
          "could not find [project].dependencies in pyproject.toml")
    check("PyMuPDF is still core, so this test is not the base-wheel proof",
          bool(core) and "pymupdf" in core,
          "pymupdf is no longer a declared core dependency, so a PyMuPDF-free "
          "INSTALL is now possible -- and this test cannot prove it works, "
          "because it only blocks the import in an interpreter that still has "
          "the package on disk. Replace this check with the real proof: install "
          "the wheel with only the [pdfium] extra into an environment where "
          "PyMuPDF is absent, and convert the corpus there.")

    # 2. the writer must not be carrying a MuPDF text-metric dependency
    from exactdoc.metrics import NullMetrics, get_metrics
    check("metrics default is backend-neutral", get_metrics().name == "none")
    check("mupdf metrics degrade rather than raise",
          isinstance(get_metrics("mupdf"), NullMetrics))

    # 3. Shipping defaults stay quality-first; the candidate is independently named.
    from exactdoc.cli import build_parser
    from exactdoc.options import (ConversionOptions, PDFIUM_GDOCS_CANDIDATE,
                                  PDFIUM_GDOCS_CANDIDATE_REFINED, PRODUCT, RAW,
                                  canonical_backend)
    defaults = {a.dest: a.default for a in build_parser()._actions}
    expected = {"backend": "pymupdf", "output_profile": "standard",
                "oracle": "libreoffice", "refine_rounds": 3}
    actual = {name: getattr(PRODUCT, name) for name in expected}
    check("default API profile is pymupdf/standard/libreoffice/refine3",
          actual == expected,
          repr(actual))
    check("bare ConversionOptions validates as PRODUCT", ConversionOptions() == PRODUCT)
    check("backend='default' resolves to the shipped backend",
          canonical_backend("default") == PRODUCT.backend)
    check("CLI and API defaults share the exact profile",
          all(defaults[{"refine_rounds": "refine"}.get(name, name)] == value
              for name, value in expected.items()), repr(defaults))
    check("raw is the shipping open-loop control",
          RAW == PRODUCT.replace(oracle="none", refine_rounds=0))
    check("PDFium candidate is independently named",
          PDFIUM_GDOCS_CANDIDATE.profile_id()
          == "pdfium/gdocs/none/refine0@240dpi")

    # 4. real conversions through the explicitly selected candidate path
    fixtures = representative_fixtures()

    # Zero inputs is a FAILURE, not a skip. This returned 0 having converted
    # nothing: it searched only `testkit/adv/` and `corpus/pdfs/`, which are both
    # generated and both gitignored, so on CI and on any clean clone it found no
    # documents, printed a note, and reported candidate isolation as proven
    # without running a conversion.
    #
    # The fixtures are committed and pinned by SHA-256, so absence means a broken
    # checkout. There is no legitimate configuration in which this test has
    # nothing to convert.
    check("committed fixtures were found", bool(fixtures),
          "searched %s -- testkit/fixtures/ holds the 16 frozen inputs and is the "
          "only corpus directory present in a clean checkout"
          % (", ".join(os.path.relpath(d, ROOT) for d in _fixture_dirs())
             or "no corpus directory at all"))
    absent = missing_capabilities(fixtures)
    check("every capability category is present", not absent,
          "missing %s -- a capability this test cannot exercise is a capability "
          "nobody has shown survives without PyMuPDF" % ", ".join(absent))
    if not fixtures:
        print("\n%d FAILED: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1

    converted = 0
    with tempfile.TemporaryDirectory() as td:
        for name, why, path in fixtures:
            out = os.path.join(td, name.replace(".pdf", ".docx"))
            try:
                convert(path, out, options=PDFIUM_GDOCS_CANDIDATE)
                ok = os.path.exists(out) and os.path.getsize(out) > 1000
                check("convert %-26s (%s)" % (name, why), ok,
                      "no output" if not ok else "")
                converted += ok
            except Exception as e:
                check("convert %-26s (%s)" % (name, why), False,
                      "%s: %s" % (type(e).__name__, e))

        # 5. candidate refinement, if an oracle is present
        from exactdoc.verify import SOFFICE
        multi = [f for f in fixtures if f[0] == "c6_long.pdf"] or fixtures[:1]
        if SOFFICE and multi:
            name, _, path = multi[0]
            out = os.path.join(td, "refined.docx")
            try:
                convert(path, out, options=PDFIUM_GDOCS_CANDIDATE_REFINED.replace(
                    refine_rounds=1))
                check("refine %s through the PDFium candidate" % name,
                      os.path.exists(out) and os.path.getsize(out) > 1000)
            except Exception as e:
                check("refine %s through the PDFium candidate" % name, False,
                      "%s: %s" % (type(e).__name__, e))
        else:
            print("  --   refinement skipped: no LibreOffice on this machine")

        # 6. the Google-Docs-safe static profile is a writer path, not an oracle
        name, _, path = fixtures[0]
        try:
            convert(path, os.path.join(td, "gdocs.docx"),
                    options=PDFIUM_GDOCS_CANDIDATE)
            check("gdocs static profile writes", True)
        except Exception as e:
            check("gdocs static profile writes", False,
                  "%s: %s" % (type(e).__name__, e))

    check("fitz still absent after converting", "fitz" not in sys.modules)
    check("pymupdf still absent after converting", "pymupdf" not in sys.modules)
    # The count, asserted rather than assumed. A loop over an empty list is a
    # loop that reports nothing wrong, and that is precisely how this test used
    # to pass.
    check("every capability fixture actually converted",
          converted == len(CAPABILITIES),
          "%d of %d converted" % (converted, len(CAPABILITIES)))
    if FAILED:
        print("\n%d FAILED: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("\nall clear -- the explicit %s candidate runs without PyMuPDF.\n"
          "The shipping default remains %s."
          % (PDFIUM_GDOCS_CANDIDATE.profile_id(), PRODUCT.profile_id()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
