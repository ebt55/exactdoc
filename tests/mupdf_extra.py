"""Is the optional `mupdf` extra installed? One answer, asked one way.

**Why this module exists, and why the obvious guard stopped working.**

Tests that compare the two parsers, or that exercise the quality ladder, need
PyMuPDF. Before the licence migration they guarded on the import:

    try:
        from exactdoc.parse import parse_pdf as parse_pymupdf
    except ImportError:
        parse_pymupdf = None

That worked only because `exactdoc/parse.py` carried a top-level `import fitz`.
The migration made it lazy -- `parse.require_fitz()`, called at parse time -- so
the module now imports perfectly well on an install without the extra and raises
`BackendUnavailableError` when you use it. Every one of those guards silently
became a no-op: they bound a live function and the failure moved to the
assertion, where it read as a product defect. Measured on the clean base wheel:
ten such tests failed rather than skipped.

So the question is asked by *probing the capability*, not by importing a module.
`require_fitz()` is the same door the product uses, which is the point -- a guard
that tests a different condition than the code is a guard that can disagree with
it.

This module deliberately does not live in `testkit/`: `testkit/harness.py` has
its own top-level `import fitz` and is part of the measurement toolkit that
requires the extra by design. `tests/` is on `sys.path` both under
`unittest discover -s tests` and when a test file is run directly, so `import
mupdf_extra` needs no path manipulation. The name does not match `test*.py`, so
discovery does not try to collect it.

    import mupdf_extra
    ...
    @mupdf_extra.needs_extra
    def test_both_backends_agree(self): ...
"""
import unittest

#: Named once. Every skip message points at the same install command.
EXTRA = "mupdf"
REASON = ("needs the optional `%s` extra (PyMuPDF, AGPL-3.0): "
          "pip install exactdoc[%s]" % (EXTRA, EXTRA))


def available():
    """True when PyMuPDF can actually be used, not merely imported.

    Asked through `parse.require_fitz` so this cannot drift from the product's
    own definition of "the pymupdf backend is available".
    """
    try:
        from exactdoc.parse import require_fitz
    except ImportError:                                    # pragma: no cover
        return False
    try:
        require_fitz()
    except Exception:                                      # noqa: BLE001
        return False
    return True


AVAILABLE = available()

#: For `@mupdf_extra.needs_extra` on a test method or a TestCase class.
needs_extra = unittest.skipUnless(AVAILABLE, REASON)


def parse_pymupdf():
    """The PyMuPDF parser, or None when the extra is absent.

    A drop-in for the `try: import ... except ImportError: = None` idiom the
    comparison tests used, with the difference that it is actually true.
    """
    if not AVAILABLE:
        return None
    from exactdoc.parse import parse_pdf
    return parse_pdf


def metrics():
    """MuPDF base-14 text metrics, or None when the extra is absent.

    The ladder cannot shape text without these, so a ladder test given `None`
    is not testing a weaker version of the ladder -- it is testing nothing, and
    must skip rather than assert against an inert one.
    """
    from exactdoc.metrics import get_metrics
    got = get_metrics("mupdf")
    return got if got.name == "mupdf" else None
