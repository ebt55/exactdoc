"""The shipping PDFium path works with PyMuPDF physically absent.

This isolation test is deliberately hostile: it does not check that `fitz` *is
not used*, it makes importing it **impossible** and then converts real
documents. A check that trusts the code to avoid an import is a check that
passes the moment someone adds one back.

The mechanism is a `sys.meta_path` finder that raises ImportError for `fitz` and
`pymupdf`, plus eviction of anything already imported. That is stricter than a
clean virtualenv without the package, because it also catches a module that has
already been imported by something else in the same interpreter.

It guards the backend seam end to end: writer imports, text metrics, figure
rasterisation, refinement text extraction, verifier rasterisation and the quality
ladder must all honor the PDFium path.

**This is not the base-wheel proof, and section 1c says so in an assertion
rather than a comment.** Blocking an import inside an interpreter that still has
PyMuPDF on disk is strictly weaker than installing without it. The real proof --
a wheel installed into a virtualenv where no AGPL package exists at all -- is
`docs/evidence/base-wheel-proof-2026-08-06.json`. What this test adds on top is
the hostility: it also catches PyMuPDF arriving transitively through some other
package in an environment that never asked for it.

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


# **The seam is now EMPTY.** Not one module in the package needs PyMuPDF to
# import. Every reference is lazy -- inside a function, on the PyMuPDF backend's
# own code path -- which is what makes a PyMuPDF-free install able to import the
# writer at all. `docxout` carried a top-level `import fitz` once and a wheel
# without PyMuPDF failed while *importing the writer*, before any conversion was
# attempted.
#
# This was `{"parse"}` until the licence migration. `exactdoc/parse.py` is the
# PyMuPDF parser and carried the one remaining top-level `import fitz`; it is now
# `parse.require_fitz()`, called at parse time, which both empties this set and
# turns "PyMuPDF is missing" into a typed `BackendUnavailableError` naming the
# extra instead of an ImportError from a module the caller never mentioned.
#
# The rule below is a SUBSET rule, not equality, and the asymmetry is
# deliberate: shrinking the seam must not need a test edit, while growing it by
# one module is red immediately. At an empty seam the subset rule and equality
# coincide, which is the strongest form this check can take.
PYMUPDF_SEAM = set()


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
          % (", ".join(sorted(PYMUPDF_SEAM)) or "the empty set"),
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

    # 1c. The declaration that makes a PyMuPDF-free install POSSIBLE. This check
    # used to assert the opposite -- "PyMuPDF is still core, so this test is not
    # the base-wheel proof" -- because while it was core, a PyMuPDF-free install
    # could not exist by construction and no amount of import-blocking would
    # have made it exist. That state is over; what is asserted now is the
    # declaration that ended it.
    #
    # This still is not the base-wheel proof, and nothing here should be read as
    # one: it checks a *declaration*, in an interpreter that has PyMuPDF on
    # disk. The proof that the wheel installs and converts with no AGPL package
    # present is docs/evidence/base-wheel-proof-2026-08-06.json, measured in a
    # fresh virtualenv in the canonical container.
    core = declared_core_dependencies()
    check("pyproject declares a core dependency list", core is not None,
          "could not find [project].dependencies in pyproject.toml")
    check("PyMuPDF is not a core dependency",
          bool(core) and "pymupdf" not in core,
          "pymupdf is a declared core dependency again, so `pip install "
          "exactdoc` carries AGPL code. This test's isolation would still pass "
          "-- it blocks an import, it does not read the declaration -- which is "
          "exactly why the declaration is checked here too. See "
          "tests/test_packaging_metadata.py and docs/license-audit.md.")
    check("pypdfium2 is a core dependency",
          bool(core) and "pypdfium2" in core,
          "the shipping parser is not declared core, so a bare `pip install "
          "exactdoc` would install no PDF backend at all and every conversion "
          "would fail on a missing pypdfium2.")

    # 1d. Asking for the absent backend by name must be a typed, actionable
    # error. `backend.PyMuPDFBackend` imports `fitz` lazily inside its methods,
    # so before this the failure mode of a base wheel was an ImportError
    # traceback out of a module the caller never mentioned -- recorded as an
    # open item in docs/license-audit.md §8. It names the extra now.
    from exactdoc.convert import convert as _convert
    from exactdoc.errors import BackendUnavailableError
    from exactdoc.backend import get_backend
    for surface, call in (
            ("get_backend('pymupdf').parse_pdf",
             lambda: get_backend("pymupdf").parse_pdf("does-not-matter.pdf")),
            ("get_backend('pymupdf').form_widgets",
             lambda: get_backend("pymupdf").form_widgets("does-not-matter.pdf")),
            ("get_backend('pymupdf').render_page",
             lambda: get_backend("pymupdf").render_page("does-not-matter.pdf", 1)),
            ("convert(backend='pymupdf')",
             lambda: _convert("does-not-matter.pdf", "out.docx",
                              backend="pymupdf")),
    ):
        try:
            call()
            check("%s raises rather than succeeding" % surface, False,
                  "it returned normally with PyMuPDF unimportable")
        except BackendUnavailableError as exc:
            names_extra = "mupdf" in ("%s %s" % (exc.message, exc.detail or ""))
            check("%s -> BackendUnavailableError naming the extra" % surface,
                  names_extra,
                  "raised the right type but did not name the `mupdf` extra: "
                  "%r / %r" % (exc.message, exc.detail))
        except Exception as exc:                       # noqa: BLE001
            check("%s -> BackendUnavailableError naming the extra" % surface,
                  False,
                  "raised %s instead: %s" % (type(exc).__name__, exc))

    # 2. Text metrics. This block used to assert that the default MEASURES
    # NOTHING -- `get_metrics().name == "none"` -- which was true and was the
    # defect: the quality ladder needs to shape text, so a PyMuPDF-free install
    # ran an inert ladder and produced worse output than the measured
    # configuration. The default is now a real shaper that needs no extra, so
    # what is asserted is that it WORKS here rather than that it declines.
    from exactdoc.metrics import Base14Metrics, get_metrics
    default = get_metrics()
    check("the default shaper needs no extra", default.name == "base14",
          "get_metrics() returned %r" % default.name)
    check("and actually measures", default.text_width("Hi", "Arial", 11.0) > 0)
    check("mupdf metrics degrade to the permissive shaper, not to nothing",
          isinstance(get_metrics("mupdf"), Base14Metrics),
          "a missing extra must be a difference in provenance, not capability")
    # The em dash is the worked example of where the two deliberately differ:
    # MuPDF charges Helvetica's space width (278), the AFM says 1000.
    check("the AFM width is used for glyphs MuPDF cannot see",
          abs(default.text_width("—", "Arial", 1000.0) - 1000.0) < 0.01,
          "em dash measured %s" % default.text_width("—", "Arial", 1000.0))

    # 3. Shipping defaults stay quality-first, and the shipping parser is the
    # permissive one. This block is the reason a base wheel is *usable* rather
    # than merely importable: every check above would still pass if the default
    # backend were PyMuPDF and every conversion raised.
    from exactdoc.cli import build_parser
    from exactdoc.options import (ConversionOptions, PDFIUM_GDOCS_CANDIDATE,
                                  PDFIUM_GDOCS_CANDIDATE_REFINED, PRODUCT, RAW,
                                  canonical_backend)
    defaults = {a.dest: a.default for a in build_parser()._actions}
    expected = {"backend": "pdfium", "output_profile": "standard",
                "oracle": "libreoffice", "refine_rounds": 3}
    actual = {name: getattr(PRODUCT, name) for name in expected}
    check("default API profile is pdfium/standard/libreoffice/refine3",
          actual == expected,
          repr(actual))
    check("bare ConversionOptions validates as PRODUCT", ConversionOptions() == PRODUCT)
    check("backend='default' resolves to the shipped backend",
          canonical_backend("default") == PRODUCT.backend)
    check("the shipped backend is the permissively licensed one",
          get_backend(PRODUCT.backend).license == "Apache-2.0",
          "PRODUCT.backend is %r, licensed %r"
          % (PRODUCT.backend, get_backend(PRODUCT.backend).license))
    check("CLI and API defaults share the exact profile",
          all(defaults[{"refine_rounds": "refine"}.get(name, name)] == value
              for name, value in expected.items()), repr(defaults))
    check("raw is the shipping open-loop control",
          RAW == PRODUCT.replace(oracle="none", refine_rounds=0))
    check("the Google-safe diagnostic profile is independently named",
          PDFIUM_GDOCS_CANDIDATE.profile_id()
          == "pdfium/gdocs/none/refine0@240dpi")
    check("and is NOT the shipping profile",
          PDFIUM_GDOCS_CANDIDATE.profile_id() != PRODUCT.profile_id(),
          "sharing the parser is not sharing the profile; the output profile "
          "and the correction loop still differ")

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

    # Converted through RAW -- the SHIPPING profile with only the oracle
    # removed -- and not through the Google-safe diagnostic one. The two use
    # different writer paths, and it was the diagnostic path that was being
    # proven here while the product shipped a parser this test never exercised.
    # Now that the shipping parser is the permissive one, the shipping
    # serialisation path is the thing worth proving PyMuPDF-free; the gdocs
    # writer keeps its own check in section 6. `oracle="none"` because
    # LibreOffice is an environment fact and this test must not need one.
    converted = 0
    with tempfile.TemporaryDirectory() as td:
        for name, why, path in fixtures:
            out = os.path.join(td, name.replace(".pdf", ".docx"))
            try:
                convert(path, out, options=RAW)
                ok = os.path.exists(out) and os.path.getsize(out) > 1000
                check("convert %-26s (%s)" % (name, why), ok,
                      "no output" if not ok else "")
                converted += ok
            except Exception as e:
                check("convert %-26s (%s)" % (name, why), False,
                      "%s: %s" % (type(e).__name__, e))

        # 5. refinement, if an oracle is present
        from exactdoc.verify import SOFFICE
        multi = [f for f in fixtures if f[0] == "c6_long.pdf"] or fixtures[:1]
        if SOFFICE and multi:
            name, _, path = multi[0]
            out = os.path.join(td, "refined.docx")
            try:
                convert(path, out, options=PDFIUM_GDOCS_CANDIDATE_REFINED.replace(
                    refine_rounds=1))
                check("refine %s without PyMuPDF" % name,
                      os.path.exists(out) and os.path.getsize(out) > 1000)
            except Exception as e:
                check("refine %s without PyMuPDF" % name, False,
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
    print("\nall clear -- the SHIPPING profile %s runs without PyMuPDF, and\n"
          "asking for the pymupdf backend anyway names the `mupdf` extra.\n"
          "This proves isolation, not installability: the base-wheel proof is\n"
          "docs/evidence/base-wheel-proof-2026-08-06.json."
          % PRODUCT.profile_id())
    return 0


if __name__ == "__main__":
    sys.exit(main())
