"""Translate known PDF-reader failures into stable public input errors.

Parser libraries expose their own exception hierarchies and, worse, sometimes
include the source path or a reader-specific diagnostic in the exception text.
This module is deliberately a *small* boundary around parser acquisition.  It
only translates statuses the readers document as a password requirement or a
bad PDF, and the operating system's own "no such file / not allowed" when it
opens the input; all other exceptions remain visible as bugs.
"""

import os

from .errors import InputNotFoundError, ParseError, UnsupportedInputError


def check_input_path(path):
    """Raise InputNotFoundError unless `path` names an existing regular file.

    The CLI calls this for every input before converting any of them, so a
    typo in the third of three names fails in a second instead of after two
    conversions. The message names the file, never the folder it was looked
    for in (see `ExactdocError`).
    """
    name = os.path.basename(os.path.normpath(path)) or path
    if os.path.isdir(path):
        raise InputNotFoundError(
            "%s is a folder, not a PDF file (to convert every PDF in a folder, "
            "use --input-dir with --out-dir)" % name)
    if not os.path.exists(path):
        raise InputNotFoundError("no such file: %s" % name)
    if not os.path.isfile(path):
        raise InputNotFoundError("%s is not a regular file" % name)


def _os_error(path, exc):
    """A public error for the OS refusing to open the input, or None.

    PDFium raises the built-in `FileNotFoundError` -- carrying the caller's
    absolute path -- for a missing file and for a folder alike, and it surfaced
    as a traceback from inside the form census, the first call that opens the
    file.
    """
    if isinstance(exc, (FileNotFoundError, IsADirectoryError,
                        NotADirectoryError)):
        try:
            check_input_path(path)
        except InputNotFoundError as err:
            return err
        return InputNotFoundError("the input file could not be opened")
    if isinstance(exc, PermissionError):
        return InputNotFoundError(
            "%s could not be read (permission denied)"
            % (os.path.basename(path) or "the input file"))
    return None


def _format_error(path):
    """Which kind of unreadable the file is, for the one-line error.

    "malformed or truncated" was the only answer, and it is the wrong one for
    the commonest case a first-time user hits: a file that is not a PDF at all
    (a web page or a Word document saved under a .pdf name). Readers accept a
    header anywhere in the first 1024 bytes (PDF 32000-1 annex H), so that is
    the window searched.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(1024)
    except OSError:
        head = None
    if head is not None and not head.strip():
        return ParseError("the file is empty, so it is not a readable PDF")
    if head is not None and b"%PDF-" not in head:
        return ParseError(
            "the file is not a PDF: it has no PDF header (is it another kind of "
            "document saved with a .pdf name?)")
    return ParseError("the PDF is malformed or truncated")


def parse(backend, path, keep_image_data=True, ocr_layer="text"):
    """Parse ``path`` and translate only documented input-status failures.

    Chaining retains the native exception for developers, while callers see a
    stable message containing neither source paths nor backend diagnostics.
    The boundary is before layout and DOCX publication, so input failures cannot
    replace an existing destination.

    ``ocr_layer`` is forwarded only when it asks for something other than the
    default, so a backend that predates the keyword keeps working.
    """
    kw = {} if ocr_layer == "text" else {"ocr_layer": ocr_layer}
    try:
        return backend.parse_pdf(path, keep_image_data=keep_image_data, **kw)
    except (UnsupportedInputError, ParseError, InputNotFoundError):
        raise
    except Exception as exc:
        translated = _translate(backend, exc, path)
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
    except (UnsupportedInputError, ParseError, InputNotFoundError):
        raise
    except Exception as exc:
        translated = _translate(backend, exc, path)
        if translated is not None:
            raise translated from exc
        raise


def _translate(backend, exc, path=None):
    """Return a public error for a documented backend input status, or None."""
    if path is not None and isinstance(exc, OSError):
        translated = _os_error(path, exc)
        if translated is not None:
            return translated
    if backend.name == "pdfium":
        translated = _pdfium_error(exc)
    elif backend.name == "pymupdf":
        translated = _pymupdf_error(exc)
    else:
        return None
    if isinstance(translated, ParseError) and path is not None:
        # Same status, a more useful sentence: say whether it is a PDF at all.
        return _format_error(path)
    return translated


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
    if exc.err_code == raw.FPDF_ERR_FILE:
        # "File not found or could not be opened" (fpdfview.h): the reader
        # could not open what the OS reported as present -- locked, or
        # unreadable to this user.
        return InputNotFoundError("the input file could not be opened")
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
