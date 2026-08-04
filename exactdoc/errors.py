"""What went wrong, as a type a caller can branch on.

Every failure in this package used to surface as whatever the layer beneath
happened to raise: `ValueError: document closed or encrypted` for a password-
protected PDF, a `KeyError` from deep inside the writer for a malformed one, and
-- worst of the three -- nothing at all when a requested renderer was missing,
because the conversion silently ran open-loop and returned a DOCX that had never
been through the feedback loop the caller asked for.

The last one is why this module leads with a distinction rather than a list.
**A missing oracle is not a degraded success.** `convert(..., oracle="gdocs")`
that quietly produces an unrefined file has not done the job; it has done a
different job and reported the same exit code. So `OracleUnavailableError` is an
error, and callers who genuinely want best-effort ask for it explicitly.

The hierarchy is shallow on purpose. A caller usually wants one of three
questions answered:

    is this my input's fault?      UnsupportedInputError, ParseError
    is this my configuration?      ConfigurationError, BackendUnavailableError
    is this the environment?       OracleError, OutputWriteError, ResourceLimitError

Everything else is detail hung off those. `ExactdocError` catches the lot, and
nothing in this package raises a bare Exception subclass that is not rooted here.

CLI exit codes live in `exactdoc.cli` and map onto these; the mapping is stable
and documented, because a script that branches on exit status is an API whether
or not anyone called it one.
"""


class ExactdocError(Exception):
    """Root of every error this package raises deliberately.

    Carries an optional `detail` that is safe to log: no source text, no
    credentials, no remote identifiers, no absolute paths from the caller's
    machine. Telemetry that leaks the document it failed on is a privacy
    incident wearing a stack trace.
    """

    #: Short stable slug for machine consumers and `--json`. Subclasses set it.
    code = "error"

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def as_dict(self):
        out = {"code": self.code, "error": type(self).__name__,
               "message": self.message}
        if self.detail:
            out["detail"] = self.detail
        return out


# --- configuration -----------------------------------------------------------

class ConfigurationError(ExactdocError):
    """The request cannot be satisfied as asked, and the caller can fix it.

    Raised BEFORE any output is created. An invalid combination that is only
    discovered halfway through has already overwritten the destination.
    """
    code = "config"


class CloudConsentRequiredError(ConfigurationError):
    """A cloud oracle was requested without explicit per-call consent.

    Deliberately a configuration error rather than an oracle error: nothing has
    been attempted, nothing has been uploaded, and the fix is in the call. It
    exists because "the target is gdocs" must never on its own mean "you may
    upload this document to a third party" -- `target="gdocs"` is a *formatting*
    choice, and conflating the two is the privacy-dangerous ambiguity the
    profile/oracle split exists to remove.
    """
    code = "cloud-consent-required"


# --- input -------------------------------------------------------------------

class UnsupportedInputError(ExactdocError):
    """A real PDF this build cannot convert: encrypted, or a class out of scope.

    Distinct from ParseError. "I will not" and "I could not" are different
    answers, and only one of them is a bug report.
    """
    code = "unsupported-input"


class ParseError(ExactdocError):
    """The document is malformed or truncated past what the backend can recover."""
    code = "parse"


# --- backends ----------------------------------------------------------------

class BackendUnavailableError(ConfigurationError):
    """A named parser backend is not installed.

    A configuration error because the resolution is `pip install`, and because
    falling back to the other backend would silently change which parser
    produced every number -- the exact substitution the parity gate exists to
    detect.
    """
    code = "backend-unavailable"


# --- output ------------------------------------------------------------------

class OutputWriteError(ExactdocError):
    """The DOCX could not be published to its destination.

    Raised only after the destination has been left untouched. Publication is
    atomic: a conversion that fails at this point must leave any previously
    valid file exactly as it was, byte for byte.
    """
    code = "output-write"


class ResourceLimitError(ExactdocError):
    """A configured bound was exceeded: bytes, pages, pixels, or wall clock.

    Typed rather than a generic failure so a host can distinguish "this input is
    hostile or too big" from "this converter is broken", and can preserve any
    existing output either way.
    """
    code = "resource-limit"


class PageLimitError(ResourceLimitError):
    """The document has more pages than the configured cap allows.

    Its own code rather than a bare `resource-limit` because it is the one
    resource refusal the caller can *answer*: every other bound in this family
    means the input is hostile or the machine is too small, while this one means
    "confirm you meant to convert a document this long" and is lifted by
    `max_pages`. A script cannot tell those apart from exit code 9 alone.
    """
    code = "page-limit"


class OcrRequiredError(UnsupportedInputError):
    """The PDF appears to be an image-only scan and needs an OCR stage.

    This is deliberately a high-confidence refusal, not a promise that an OCR
    engine is available.  Exactdoc currently preserves digital-PDF text; it
    does not invent text for a scan.
    """
    code = "ocr-required"


class InteractiveFormError(UnsupportedInputError):
    """The PDF is a fillable AcroForm, and its content lives in the fields.

    A refusal for the same reason `OcrRequiredError` is one: the thing the
    document is *for* is not something this converter preserves. Widget values,
    field names, tab order and validation have no DOCX equivalent here, and the
    field boxes are drawn by annotation appearance streams the text extractor
    never sees. The result is not a lossy conversion of a form, it is a
    convincing-looking non-form -- measured at 0.085 SSIM on IRS Form 1040,
    which is worse than useless because it still exits zero.

    Deliberately narrow: this is "the form dominates", not "the document
    contains a widget". See `exactdoc.scan` for the threshold and its evidence.
    """
    code = "interactive-form"


# --- oracles -----------------------------------------------------------------

class OracleError(ExactdocError):
    """Something in the render-feedback loop failed.

    The subclasses exist so that a failure can be attributed to a *stage*. A
    single OracleError tells you the loop broke; it does not tell you whether
    the document reached a third party, which is the question that matters when
    the oracle is somebody else's cloud.
    """
    code = "oracle"


class OracleUnavailableError(OracleError):
    """An explicitly requested renderer is not present.

    Not a warning, and not a fallback to open-loop conversion. Producing an
    unrefined DOCX when refinement was requested is a different product, and it
    used to be reported as success.
    """
    code = "oracle-unavailable"


class OracleAuthenticationError(OracleError):
    """Credentials are missing, expired, or refused. Never retried blindly."""
    code = "oracle-auth"


class OracleUploadError(OracleError):
    """The document could not be sent to the remote oracle."""
    code = "oracle-upload"


class OracleImportError(OracleError):
    """The remote accepted the file but never produced a readable document."""
    code = "oracle-import"


class OracleExportError(OracleError):
    """The rendered result could not be retrieved, or came back unusable.

    Includes the documented Google Workspace export size limit, which must be
    detected rather than mistaken for a successful empty response.
    """
    code = "oracle-export"


class OracleCleanupError(OracleError):
    """A temporary remote document could not be deleted.

    **This is a privacy failure, not a tidiness one.** The caller's content is
    still sitting in somebody else's storage. It exits non-zero, it names the
    stage without logging the remote identifier, and the identifier goes to a
    local orphan ledger so it can be cleaned up later. Qualification cannot pass
    while any tagged orphan remains.
    """
    code = "oracle-cleanup"


#: Every concrete error, by slug. Used by the CLI's exit-code table and by the
#: tests that assert the table covers the hierarchy -- a new error class with no
#: exit code would otherwise fall through to a generic failure.
BY_CODE = {}


def _register(cls):
    for sub in cls.__subclasses__():
        BY_CODE[sub.code] = sub
        _register(sub)


BY_CODE[ExactdocError.code] = ExactdocError
_register(ExactdocError)
