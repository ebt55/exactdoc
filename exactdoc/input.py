"""Translate known PDF-reader failures into stable public input errors.

Parser libraries expose their own exception hierarchies and, worse, sometimes
include the source path or a reader-specific diagnostic in the exception text.
This module is deliberately a *small* boundary around parser acquisition.  It
only translates statuses the readers document as a password requirement or a
bad PDF; all other exceptions remain visible as bugs.
"""

from .errors import ParseError, UnsupportedInputError


def parse(backend, path, keep_image_data=True):
    """Parse ``path`` and translate only documented input-status failures.

    Chaining retains the native exception for developers, while callers see a
    stable message containing neither source paths nor backend diagnostics.
    The boundary is before layout and DOCX publication, so input failures cannot
    replace an existing destination.
    """
    try:
        return backend.parse_pdf(path, keep_image_data=keep_image_data)
    except (UnsupportedInputError, ParseError):
        raise
    except Exception as exc:
        translated = _translate(backend, exc)
        if translated is not None:
            raise translated from exc
        raise


def form_widgets(backend, path):
    """Per-page interactive-widget census, through the same input boundary.

    Returns None when the backend offers no census -- meaning "not measured",
    which `scan` is careful not to read as "no widgets".

    It goes through this module for the same reason `parse` does: the preflight
    refusals run *before* the parse, so this is now the first call that opens the
    caller's file, and a password-protected PDF must still surface as
    `UnsupportedInputError` rather than as whatever the reader raises while
    counting annotations.
    """
    census = getattr(backend, "form_widgets", None)
    if census is None:
        return None
    try:
        return census(path)
    except (UnsupportedInputError, ParseError):
        raise
    except Exception as exc:
        translated = _translate(backend, exc)
        if translated is not None:
            raise translated from exc
        raise


def _translate(backend, exc):
    """Return a public error for a documented backend input status, or None."""
    if backend.name == "pdfium":
        return _pdfium_error(exc)
    if backend.name == "pymupdf":
        return _pymupdf_error(exc)
    return None


def _pdfium_error(exc):
    # `PdfiumError.err_code` is the supported way to distinguish a bad PDF
    # from an unavailable file or an arbitrary failure in client code.  Do not
    # inspect the exception message: it is backend/version-dependent and may
    # include unsafe source information in a future release.
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
    except ImportError:
        return None
    if not isinstance(exc, pdfium.PdfiumError):
        return None
    if exc.err_code == raw.FPDF_ERR_PASSWORD:
        return UnsupportedInputError(
            "password-protected PDFs are not supported")
    if exc.err_code == raw.FPDF_ERR_FORMAT:
        return ParseError("the PDF is malformed or truncated")
    return None


def _pymupdf_error(exc):
    # PyMuPDF's open failures have a dedicated exception family.  Restricting
    # this to FileDataError/EmptyFileError avoids turning a programming error in
    # the parser into a misleading claim about the user's document.
    try:
        import fitz
    except ImportError:
        return None
    error_types = tuple(
        cls for cls in (getattr(fitz, "FileDataError", None),
                        getattr(fitz, "EmptyFileError", None))
        if isinstance(cls, type)
    )
    if error_types and isinstance(exc, error_types):
        return ParseError("the PDF is malformed or truncated")
    return None
