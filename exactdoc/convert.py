"""End-to-end conversion API.

One entry point, one profile. Every default this function applies comes from
`exactdoc.options.PRODUCT`, so the API, the CLI, the CI lanes and the published
numbers cannot describe three different configurations again (see
options.py for what that cost).
"""
import os
from typing import Optional

from .dialect import normalize
from .infer import infer
from .input import parse as parse_input
from .options import ConversionOptions, resolve
from .scan import classify_ir, preflight, refusal


def _select_backend(name: str):
    """The backend, chosen once per conversion.

    `EXACTDOC_BACKEND` still works, but it is now the lowest-priority source:
    an explicit `backend=` argument wins, because a gate that selects a parser
    has to be able to say so in its own call rather than by mutating the
    environment of the process it shares with everything else.
    """
    from .backend import get_backend
    return get_backend(name)


def convert(pdf_path: str, out_path: Optional[str] = None,
            dpi: Optional[int] = None, refine_rounds: Optional[int] = None,
            target: Optional[str] = None, backend: Optional[str] = None,
            ladder: Optional[bool] = None, verbose: Optional[bool] = None,
            output_profile: Optional[str] = None,
            oracle: Optional[str] = None,
            allow_cloud_upload: Optional[bool] = None,
            max_pages: Optional[int] = None,
            options: Optional[ConversionOptions] = None) -> str:
    """Convert a PDF to DOCX. Returns the output path.

    `convert_result` takes the same arguments and returns the
    `ConversionResult` -- requested and resolved options side by side, the
    refine rounds, and every warning -- for a caller that needs to know
    whether what ran is what it asked for.
    """
    return convert_result(
        pdf_path, out_path, dpi=dpi, refine_rounds=refine_rounds,
        target=target, backend=backend, ladder=ladder, verbose=verbose,
        output_profile=output_profile, oracle=oracle,
        allow_cloud_upload=allow_cloud_upload, max_pages=max_pages,
        options=options).output_path


def convert_result(pdf_path: str, out_path: Optional[str] = None,
                   dpi: Optional[int] = None,
                   refine_rounds: Optional[int] = None,
                   target: Optional[str] = None,
                   backend: Optional[str] = None,
                   ladder: Optional[bool] = None,
                   verbose: Optional[bool] = None,
                   output_profile: Optional[str] = None,
                   oracle: Optional[str] = None,
                   allow_cloud_upload: Optional[bool] = None,
                   max_pages: Optional[int] = None,
                   options: Optional[ConversionOptions] = None):
    """Convert a PDF to DOCX. Returns a `ConversionResult`.

    Defaults come from `options.PRODUCT`: its PDFium backend, standard output
    profile, and three-round LibreOffice refinement loop. Pass
    `options=` to supply a whole profile, or individual keywords to override
    parts of it. A `None` keyword means "take the profile's value", never
    "zero".

    **Backend precedence is explicit keyword > supplied `options` > environment >
    PRODUCT**, and the middle two used to be the wrong way round. `EXACTDOC_BACKEND`
    outranked an explicitly-passed profile, which meant an exported variable could
    silently redirect a caller that had named its backend in code -- including the
    parity gate, whose entire job is to run one named backend against another. A
    gate that an environment variable can redirect is not a gate. The environment
    is now consulted only when the caller expressed no preference at all.

    `refine_rounds` > 0 enables the closed-loop pass: render the DOCX back and
    correct page overflow and per-page offsets against what actually rendered.

    `output_profile` and `oracle` are independent, and used to be one field.
    `output_profile` decides how the OOXML is written -- "gdocs" emits line
    heights Google Docs does not mistranslate, entirely offline. `oracle`
    decides what renders the result during refinement, and only matters when
    `refine_rounds > 0`. A layout tuned for LibreOffice is measurably not tuned
    for Google Docs, so the pair is a real choice rather than a detail.

    **A requested oracle that is unavailable is now an error.** It used to fall
    through to an open-loop conversion, printing a line only under `verbose`, so
    a caller who asked for refinement could receive an unrefined document and a
    success exit code.

    `target=` is accepted for one alpha cycle and maps onto the pair. Note that
    `target="gdocs"` now selects the Google-safe *profile* without authorising
    an upload; the cloud oracle needs `allow_cloud_upload=True`.

    **Three classes of document are refused rather than converted**: image-only
    scans (`OcrRequiredError`), interactive forms (`InteractiveFormError`), and
    documents longer than `max_pages` (`PageLimitError`, the only one of the
    three the caller can lift). The form and page checks run before the parse, so
    a refusal costs an annotation walk rather than a full extraction.

    **An oracle that fails mid-run degrades the conversion; it does not fail
    it.** The best DOCX produced so far is published, `OracleDegradedWarning`
    is raised (escalate it to make the failure fatal and leave the destination
    untouched), and the result says so twice: an `oracle-degraded` entry in
    `warnings`, and `resolved_options` carrying the rounds that actually ran,
    so `degraded` is True. An oracle that is not installed at all is still
    `OracleUnavailableError` -- see `exactdoc.errors.OracleDegradedWarning`
    for where that line is drawn, and why.
    """
    import time
    from .result import ConversionResult, ConversionWarning, OracleRun, \
        sha256_file
    started = time.monotonic()
    if backend is None and options is None:
        backend = os.environ.get("EXACTDOC_BACKEND", "").strip() or None
    # Consent is never read from the environment. An exported variable must not
    # be able to authorise sending somebody's document to a third party.
    opts = resolve(options, backend=backend, target=target, dpi=dpi,
                   refine_rounds=refine_rounds, ladder=ladder, verbose=verbose,
                   output_profile=output_profile, oracle=oracle,
                   allow_cloud_upload=allow_cloud_upload, max_pages=max_pages)
    if out_path is None:
        out_path = os.path.splitext(pdf_path)[0] + ".docx"

    bk = _select_backend(opts.backend)
    # Refuse what we can see cheaply, before spending a full extraction on it.
    # This is also the first call to touch the file, so it goes through the same
    # input boundary and reports a password-protected PDF as such.
    widgets = preflight(bk, pdf_path, max_pages=opts.max_pages)
    # Keep the backend-native reader boundary here.  Known password and format
    # statuses become stable public errors before any output can be published;
    # unrelated exceptions deliberately propagate as bugs.
    ir = parse_input(bk, pdf_path)
    # ``parse_input`` always returns a DocIR in production.  The attribute
    # guard keeps the historical lightweight writer-test seam usable: those
    # tests deliberately substitute an opaque layout sentinel, not a parser IR.
    if hasattr(ir, "pages"):
        # Re-run the whole policy against the parsed document: the OCR class
        # needs text, and a backend without a census reaches the page cap only
        # here.  Nothing is refused twice -- `preflight` already returned.
        error = refusal(classify_ir(ir, widgets=widgets), max_pages=opts.max_pages)
        if error is not None:
            raise error
    ir = normalize(ir)
    lay = infer(ir)
    if opts.ladder:
        from .ladder import apply_ladder, summarise
        from .metrics import get_metrics
        # The ladder predicts a re-wrap, so it has to shape text. This asked for
        # `get_metrics("mupdf")` by name, which meant the ladder only ran where
        # the AGPL extra was installed -- so the shipped default and the
        # measured configuration were different products. It now takes the
        # default shaper, which every install has and which needs no extra.
        rep = apply_ladder(lay, metrics=get_metrics())
        lay.ladder_report = rep
        if opts.verbose:
            print("  ladder: " + summarise(rep))
    # The writer's honest-degradation ledger: which extracted rasters went in as
    # they were, which had to be re-encoded, and which could not be embedded at
    # all.  An image exactdoc cannot embed never fails the document -- but a
    # silent drop would be a lie, so the write counts them and this reports them.
    image_report = {}
    refine_report = {}
    resolved_opts = opts
    if opts.refine_rounds > 0:
        from .refine import refine
        from .targets import get_renderer
        # Raises OracleUnavailableError if the named renderer is absent. There
        # is deliberately no `else` falling through to an open-loop write: that
        # branch is what turned "refine against LibreOffice" into "do not
        # refine" without changing the exit code.
        render, resolved = get_renderer(opts.oracle)
        if opts.verbose:
            print("  refining against: %s" % resolved)
        refine(lay, pdf_path, out_path, dpi=opts.dpi,
               rounds=opts.refine_rounds, verbose=opts.verbose,
               render=render, output_profile=opts.output_profile,
               backend=bk, image_report=image_report, report=refine_report)
        failure = refine_report.get("oracle_failure")
        if failure is not None:
            # What actually ran: the correction rounds measured before the
            # failure, and no oracle at all if not even round 0 was measured.
            done = refine_report.get("published_round")
            resolved_opts = opts.replace(refine_rounds=done or 0) \
                if done is not None else \
                opts.replace(refine_rounds=0, oracle="none",
                             allow_cloud_upload=False)
    else:
        from .docxout import write_docx
        # The writer serialises a ZIP incrementally.  Never point it at the
        # public destination: if an image, disk, or Python failure interrupts
        # it, preserve the caller's existing document byte-for-byte and
        # publish only a validated complete result.  ``publish`` deliberately
        # writes beside ``out_path`` so its final replacement is an atomic
        # same-filesystem operation.
        from .io import publish
        publish(lambda tmp: write_docx(lay, tmp, dpi=opts.dpi,
                                       output_profile=opts.output_profile,
                                       backend=bk, image_report=image_report),
                out_path)
    _report_images(image_report, opts.verbose)

    found = []
    failure = refine_report.get("oracle_failure")
    if failure is not None:
        found.append(ConversionWarning(
            code="oracle-degraded", stage="refine",
            message="the %s oracle failed in refine round %d; the published "
                    "DOCX is %s" % (
                        opts.oracle, failure["round"],
                        ("refine round %d, the best measured before the "
                         "failure" % refine_report["published_round"])
                        if refine_report.get("published_round") is not None
                        else "the open-loop conversion, unrefined"),
            detail=failure.get("reason")))
    if image_report.get("dropped"):
        found.append(ConversionWarning(
            code="image-dropped", stage="write",
            message="%d image(s) could not be embedded and were omitted"
                    % image_report["dropped"]))
    runs = tuple(
        OracleRun(oracle=opts.oracle, ok="measure_ms" in row,
                  round_index=row["round"],
                  duration_ms=int(row.get("render_ms", 0)),
                  stage_failed=None if "measure_ms" in row else "render")
        for row in refine_report.get("rounds", ()))
    timings = {"total": int((time.monotonic() - started) * 1000)}
    for key in ("write_ms", "render_ms", "measure_ms"):
        tot = sum(r.get(key, 0) for r in refine_report.get("rounds", ()))
        if tot:
            timings["refine_" + key[:-3]] = tot
    return ConversionResult(
        output_path=out_path, output_sha256=sha256_file(out_path),
        requested_options=opts, resolved_options=resolved_opts,
        refine_rounds_completed=max(0, sum(1 for r in runs if r.ok) - 1),
        oracle_runs=runs, warnings=tuple(found), timings_ms=timings,
        refine=dict(refine_report))


def _report_images(report, verbose):
    """Say out loud when a raster did not survive the write.

    Only under `verbose` for a re-encode -- that is a container change with
    identical pixels, and nothing was lost. A *drop* is content the caller asked
    for and did not get, so it is reported either way.
    """
    if not report:
        return
    dropped = report.get("dropped", 0)
    if dropped:
        print("  warning: %d image(s) could not be embedded and were omitted"
              % dropped)
    if verbose and report.get("reencoded"):
        print("  images: %d re-encoded to PNG (format the writer cannot embed "
              "as extracted)" % report["reencoded"])


def main(argv=None):
    """Deprecated alias. The console entry point is `exactdoc.cli:main`."""
    from .cli import main as _main
    return _main(argv)


if __name__ == "__main__":
    main()
