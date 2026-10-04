"""exactdoc command-line interface.

The single console entry point. Its defaults are not written here -- they come
from `exactdoc.options.PRODUCT`, so `exactdoc file.pdf`, `convert(file)` and
the CI product lane all run the same configuration. They used to run three.

**One deliberate difference from the API, and it is announced.** A bare
`exactdoc file.pdf` on a machine without LibreOffice converts in one pass (as
`--refine 0` would) and prints a note saying what was skipped and how to get
it, instead of exiting 11 before writing anything. A first-time user who has
not installed an optional office suite is not misconfigured; they are the
commonest case. The strict behaviour stays wherever refinement was asked for
by name -- an explicit `--refine N` or `--oracle libreoffice` is still exit 11
-- and `convert()` is unchanged, so a script that wants the old contract has
it. The fallback is never silent: the note goes to stderr every time.
"""
import argparse
import os
import shutil
import sys
import threading
import time

from .errors import ConfigurationError, ExactdocError
from .options import (BACKENDS, OCR_LAYERS, ORACLES, OUTPUT_PROFILES, PRODUCT,
                      TARGETS)
from .scan import MAX_PAGES_PER_DOCUMENT

# Stable, documented exit codes. A script that branches on exit status is an API
# whether or not anyone called it one, so these are part of the contract and do
# not get renumbered casually.
#
# 0  success -- including a conversion whose render oracle failed mid-run: the
#    best DOCX produced so far is written and a `warning: the libreoffice
#    oracle failed ...` line goes to stderr (OracleDegradedWarning). An oracle
#    that is not installed at all is still exit 11 before anything is written
#    when refinement was asked for by name; see the module docstring.
# 1  an unclassified exactdoc failure (a bug: the CLI says so and asks for a
#    report)
# 2  argparse usage error (argparse's own convention; not ours to change)
EXIT_CODES = {
    "config": 3,
    "cloud-consent-required": 4,
    "unsupported-input": 5,
    "parse": 6,
    "backend-unavailable": 7,
    "output-write": 8,
    "resource-limit": 9,
    "oracle": 10,
    "oracle-unavailable": 11,
    "oracle-auth": 12,
    "oracle-upload": 13,
    "oracle-import": 14,
    "oracle-export": 15,
    "oracle-cleanup": 16,
    "ocr-required": 17,
    "batch-partial": 18,
    "interactive-form": 19,
    "page-limit": 20,
    "input-not-found": 21,
}

ISSUES_URL = "https://github.com/ebt55/exactdoc/issues"
USAGE_URL = "https://github.com/ebt55/exactdoc/blob/main/docs/usage.md"
LIBREOFFICE_URL = "https://www.libreoffice.org/download/"

# A second line under the error, for the failures a first-time user can fix
# without reading the documentation. Keyed by error code; absent = no hint.
HINTS = {
    "unsupported-input": "open it with its password and save an unprotected "
                         "copy (or run `qpdf --decrypt`), then convert that",
    "ocr-required": "run it through an OCR tool first (for example OCRmyPDF), "
                    "then convert the result",
    "oracle-unavailable": "install LibreOffice (%s), or pass --refine 0 to "
                          "convert without the layout check" % LIBREOFFICE_URL,
    "parse": "if it opens in a PDF viewer, save a fresh copy from there (or "
             "download it again) and convert that",
}

USAGE = ("exactdoc [options] input.pdf [-o output.docx]\n"
         "       exactdoc --input-dir FOLDER --out-dir FOLDER [options]\n"
         "       exactdoc --diagnose input.pdf")

DESCRIPTION = (
    "Convert a PDF into a Word document (DOCX) that looks like the original "
    "and can be edited: real headings, paragraphs, lists and tables. "
    "Everything runs on this computer; nothing is uploaded.")

EPILOG = """\
examples:
  exactdoc report.pdf                  writes report.docx next to the PDF
  exactdoc report.pdf -o out/new.docx  chooses the output name
  exactdoc report.pdf --output-profile gdocs
                                       a DOCX for Google Docs (still offline)
  exactdoc --input-dir pdfs --out-dir docx --recursive
                                       converts a folder of PDFs
  exactdoc --diagnose report.pdf       a summary without any of the text,
                                       to paste into a bug report

LibreOffice is optional. When it is installed, exactdoc renders its own DOCX
with it and corrects page breaks and spacing (--refine, 3 rounds by default;
slower on long documents). Without it, exactdoc converts in one pass and says
so. --refine 0 skips the check on purpose.

exit codes: 0 converted, 2 wrong command line, 3 bad option or output already
exists, 5 password-protected, 6 not a readable PDF, 8 cannot write the output,
11 LibreOffice asked for but missing, 17 scanned without text (needs OCR),
19 fillable form, 20 over the page limit, 21 input file not found.
Every option and code: %s
Report a bad conversion: %s
""" % (USAGE_URL, ISSUES_URL)


class _Explicit(argparse.Action):
    """Store the value and remember that the user typed the option.

    The LibreOffice fallback applies only to options left at their defaults,
    and argparse cannot otherwise tell `--refine 3` from no `--refine` at all.
    The default itself stays PRODUCT's, which tests/test_gate_mutations.py
    pins.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        explicit = set(getattr(namespace, "explicit_options", None) or ())
        explicit.add(self.dest)
        namespace.explicit_options = explicit


def _version():
    from . import __version__
    return "exactdoc %s" % __version__


def build_parser():
    ap = argparse.ArgumentParser(
        prog="exactdoc", usage=USAGE, description=DESCRIPTION, epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="*", help="the PDF file(s) to convert")
    ap.add_argument("-o", "--out", metavar="OUTPUT.docx",
                    help="where to write the DOCX (one input only). Default: "
                         "the PDF's name with .docx, in the same folder; an "
                         "existing file of that name is kept unless you pass "
                         "--overwrite")
    ap.add_argument("--version", action="version", version=_version())

    q = ap.add_argument_group("quality and speed")
    q.add_argument("--refine", type=int, default=PRODUCT.refine_rounds,
                   metavar="N", action=_Explicit,
                   help="layout-check rounds: render the DOCX with LibreOffice "
                        "and correct page overflow and offsets against what "
                        "actually rendered. 0 disables it and is much faster "
                        "on long documents (default %(default)s, the profile "
                        "every published number is measured on; without "
                        "LibreOffice the default becomes 0, with a note)")
    q.add_argument("--output-profile", default=PRODUCT.output_profile,
                   choices=list(OUTPUT_PROFILES),
                   help="how the DOCX is written. 'gdocs' emits line heights "
                        "Google Docs does not mistranslate. This is pure "
                        "serialisation: offline, deterministic, no network and "
                        "no credentials (default: %(default)s)")
    q.add_argument("--oracle", default=PRODUCT.oracle, choices=list(ORACLES),
                   action=_Explicit,
                   help="what renders the DOCX during refinement, and only "
                        "used when --refine > 0. A layout tuned for "
                        "LibreOffice is measurably not tuned for Google Docs. "
                        "'gdocs' uploads to Drive and needs "
                        "--allow-cloud-upload (default: %(default)s)")
    q.add_argument("--allow-cloud-upload", action="store_true",
                   help="permit an oracle that sends the document to a third "
                        "party. Required for --oracle gdocs, which uploads the "
                        "DOCX to Google Drive, converts it, exports a PDF and "
                        "deletes the temporary copy. Never implied by "
                        "--output-profile gdocs, and no environment variable "
                        "can grant it")
    q.add_argument("--dpi", type=int, default=PRODUCT.dpi,
                   help="raster DPI for vector figure regions (default "
                        "%(default)s)")
    q.add_argument("--max-pages", type=int, default=None, metavar="N",
                   help="page cap for a single conversion (default: %d, the "
                        "same limit batch mode enforces). A longer document is "
                        "refused rather than converted; pass a larger N to "
                        "agree to it, or 0 to remove the cap"
                        % MAX_PAGES_PER_DOCUMENT)
    q.add_argument("--ocr-layer", default=PRODUCT.ocr_layer,
                   choices=list(OCR_LAYERS),
                   help="for a scanned page carrying an invisible OCR text "
                        "layer: 'text' converts the layer into editable text "
                        "and leaves out the scan it duplicates; 'image' keeps "
                        "the scan as a picture and drops the layer "
                        "(default: %(default)s)")
    q.add_argument("--backend", default=PRODUCT.backend, choices=list(BACKENDS),
                   help="PDF parser (default: %(default)s). Overrides "
                        "EXACTDOC_BACKEND")
    q.add_argument("--target", default=None, choices=list(TARGETS),
                   help=argparse.SUPPRESS)      # deprecated; see options.py

    c = ap.add_argument_group("checking and reporting")
    c.add_argument("--diagnose", action="store_true",
                   help="print a summary of one PDF for a bug report -- "
                        "producer, page sizes, fonts, what exactdoc detected -- "
                        "with none of its text, and write nothing")
    c.add_argument("--verify", action="store_true",
                   help="render the DOCX back to PDF (needs LibreOffice) and "
                        "report per-page visual similarity + text coverage")
    c.add_argument("--report-dir", default=None,
                   help="directory for side-by-side comparison images")
    c.add_argument("-v", "--verbose", action="store_true",
                   help="print what each stage decided")

    b = ap.add_argument_group("folders (batch mode)")
    b.add_argument("--input-dir", help="directory of PDFs to convert")
    b.add_argument("--out-dir", help="batch output directory")
    b.add_argument("--recursive", action="store_true",
                   help="discover PDFs recursively")
    b.add_argument("--workers", type=int, default=None,
                   help="batch workers (currently 1; reserved range 1-4)")
    b.add_argument("--continue-on-error", action="store_true")
    b.add_argument("--overwrite", action="store_true",
                   help="replace DOCX files that already exist: every output "
                        "in batch mode, or the default-named DOCX next to a "
                        "single PDF (an explicit -o always replaces)")
    b.add_argument("--result-json",
                   help="write a privacy-safe batch result report")
    b.add_argument("--scan-only", action="store_true",
                   help="classify PDFs without writing DOCX")
    return ap


def main(argv=None):
    """Entry point. Turns a typed failure into a message and an exit code.

    An uncaught ExactdocError used to reach the user as a traceback, which is
    the right output for a bug and the wrong one for "you asked for refinement
    without a renderer" -- an ordinary, recoverable, user-fixable situation. A
    traceback also buries the actionable sentence under a stack.

    Anything else IS a bug. The traceback is kept -- it is what makes the
    report useful -- and followed by one line saying so and where to send it.
    """
    try:
        return _run(build_parser(), argv)
    except ExactdocError as e:
        code = EXIT_CODES.get(e.code, 1)
        print("error: %s" % e.message, file=sys.stderr)
        if e.detail:
            print("  %s" % e.detail, file=sys.stderr)
        if HINTS.get(e.code):
            print("  hint: %s" % HINTS[e.code], file=sys.stderr)
        return code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception:
        import traceback
        traceback.print_exc()
        print("error: exactdoc hit an internal error. This is a bug, not a "
              "problem with how you ran it.\n  Please report it at %s with the "
              "lines above and the output of `exactdoc --diagnose` on the "
              "same PDF (do not attach a confidential PDF)." % ISSUES_URL,
              file=sys.stderr)
        return 1


# ----------------------------------------------------------------- helpers
def _fmt_s(seconds):
    if seconds < 60:
        return "%.1fs" % seconds
    return "%dm%02ds" % divmod(int(round(seconds)), 60)


def _isatty(stream):
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


class _Progress:
    """A one-line status on an interactive stderr: the stage and elapsed time.

    Conversion is silent until it finishes, and on a long document that is
    minutes: y06 (126 pages) measured 2m03s open-loop and 6m49s through the
    default refine loop on a Windows desktop (2026-10-05), and a user cannot
    tell either from a hang. Drawn only on a terminal (a
    log or a pipe gets the final "wrote" line and nothing else) and only once
    a stage has run for a second, so short documents print nothing extra.
    """

    def __init__(self, name, stream=None, enabled=None):
        self.stream = stream or sys.stderr
        self.enabled = _isatty(self.stream) if enabled is None else enabled
        self.name = name
        self.pages = None
        self.stage = "starting"
        self.t0 = time.monotonic()
        self._stop = threading.Event()
        self._thread = None
        self._width = 0

    def __call__(self, stage, info):
        if info.get("pages"):
            self.pages = info["pages"]
        n = "%d pages" % self.pages if self.pages else "the pages"
        if stage == "read":
            self.stage = "reading %s" % n
        elif stage == "layout":
            self.stage = "working out the layout of %s" % n
        elif stage == "write":
            self.stage = "writing the DOCX"
        elif stage == "refine":
            self.stage = ("checking the layout in LibreOffice, pass %d of at "
                          "most %d" % (info.get("round", 0) + 1,
                                       info.get("rounds", 1)))
        else:
            self.stage = stage
        if self.enabled and self._thread is None:
            self._thread = threading.Thread(target=self._tick, daemon=True)
            self._thread.start()

    def _tick(self):
        while not self._stop.wait(0.5):
            elapsed = time.monotonic() - self.t0
            if elapsed >= 1.0:
                self._draw("%s: %s ... %s" % (self.name, self.stage,
                                              _fmt_s(elapsed)))

    def _draw(self, line):
        cols = shutil.get_terminal_size((80, 20)).columns
        line = line[:max(10, cols - 1)]
        self.stream.write("\r" + line + " " * max(0, self._width - len(line)))
        self.stream.flush()
        self._width = len(line)

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2.0)
        if self._width:
            self.stream.write("\r" + " " * self._width + "\r")
            self.stream.flush()
            self._width = 0


def _libreoffice_fallback(args):
    """-> (refine_rounds, oracle, fell_back) for this run.

    Falls back only when nothing about refinement was typed: a default
    `--refine` against the default LibreOffice oracle, no deprecated
    `--target`, and no soffice on the machine.
    """
    from .options import canonical_oracle
    explicit = getattr(args, "explicit_options", None) or set()
    if (args.refine > 0 and not args.target and
            not ({"refine", "oracle"} & explicit) and
            canonical_oracle(args.oracle) == "libreoffice"):
        from .verify import SOFFICE
        if SOFFICE is None:
            return 0, "none", True
    return args.refine, args.oracle, False


FALLBACK_NOTE = (
    "note: LibreOffice was not found, so exactdoc is converting without its\n"
    "  layout check (the same as --refine 0). The DOCX is complete. With\n"
    "  LibreOffice installed, exactdoc also corrects page breaks and spacing\n"
    "  against a real render: %s\n"
    "  Pass --refine 0 to hide this note." % LIBREOFFICE_URL)


def _default_out(pdf):
    return os.path.splitext(pdf)[0] + ".docx"


def _same_file(a, b):
    try:
        return os.path.exists(b) and os.path.samefile(a, b)
    except OSError:
        return os.path.abspath(a) == os.path.abspath(b)


def _check_jobs(args):
    """Every input and output problem we can see, before converting anything.

    A typo in the third of three file names, an unwritable folder, or a
    default name that would replace the user's own Word document all used to
    surface after the conversions before them had run -- or, for the last one,
    not at all. Returns [(pdf, out)].
    """
    from .input import check_input_path
    from .io import check_writable
    jobs = []
    for pdf in args.pdf:
        check_input_path(pdf)
        out = args.out or _default_out(pdf)
        if _same_file(pdf, out):
            raise ConfigurationError(
                "the output would replace the input PDF; choose another name "
                "with -o")
        if not args.out and os.path.exists(out) and not args.overwrite:
            # The case this guards: report.docx exported to report.pdf, then
            # `exactdoc report.pdf` -- which used to overwrite the original
            # Word document without a word.
            raise ConfigurationError(
                "%s already exists; choose another name with -o, or pass "
                "--overwrite to replace it" % os.path.basename(out))
        check_writable(out)
        jobs.append((pdf, out))
    return jobs


# --------------------------------------------------------------------- run
def _run(ap, argv):
    args = ap.parse_args(argv)
    if args.diagnose:
        if len(args.pdf) != 1 or args.input_dir:
            ap.error("--diagnose takes exactly one PDF")
        if args.out or args.verify or args.report_dir or args.scan_only:
            ap.error("--diagnose writes nothing; it cannot be combined with "
                     "-o, --verify, --report-dir or --scan-only")
        from .diagnose import main as diagnose_main
        return diagnose_main(args.pdf[0], backend_name=args.backend)
    if args.input_dir:
        if args.pdf:
            ap.error("--input-dir cannot be combined with PDF arguments")
        if not args.out_dir:
            ap.error("--input-dir requires --out-dir")
        if args.target:
            ap.error("--target is not supported for batch conversion")
        if args.max_pages is not None:
            # Raising the cap is a judgement about one document. Applying it to
            # a whole directory would lift it for every member sight unseen.
            ap.error("--max-pages is not supported for batch conversion")
        if args.out or args.verify or args.report_dir:
            ap.error("-o, --verify, and --report-dir are not supported for batch conversion")
        refine, oracle, fell_back = _libreoffice_fallback(args)
        if fell_back and not args.scan_only:
            print(FALLBACK_NOTE, file=sys.stderr)
        from .batch import make_items, run
        items = make_items(args.input_dir, args.out_dir, recursive=args.recursive)
        report = run(items, backend=args.backend, dpi=args.dpi,
                     refine_rounds=refine, output_profile=args.output_profile,
                     oracle=oracle, allow_cloud_upload=args.allow_cloud_upload,
                     workers=1 if args.workers is None else args.workers,
                     continue_on_error=args.continue_on_error,
                     overwrite=args.overwrite, scan_only=args.scan_only,
                     verbose=args.verbose, result_json=args.result_json,
                     recursive=args.recursive)
        for item in report["items"]:
            print("%s %s" % (item["status"], item["input"]))
        return 18 if report["counts"]["failed"] or report["counts"]["ocr_required"] else 0
    if not args.pdf:
        ap.error("give a PDF to convert, or --input-dir for a folder "
                 "(exactdoc --help lists every option)")
    batch_only = (args.out_dir, args.recursive, args.workers is not None,
                  args.continue_on_error, args.result_json)
    if any(batch_only):
        ap.error("batch options require --input-dir")
    if args.scan_only:
        if len(args.pdf) != 1:
            ap.error("--scan-only accepts one PDF or --input-dir")
        from .convert import _select_backend
        from .input import check_input_path
        from .scan import inspect_pdf, page_cap, refusal
        check_input_path(args.pdf[0])
        report = inspect_pdf(_select_backend(args.backend), args.pdf[0])
        print(report.classification)
        # Report every condition, then exit on the first. A document can be both
        # a form and over the cap, and a scan that named only the one it happened
        # to check first would send the caller round the loop twice.
        print("  pages: %d%s" % (report.page_count,
                                 "  (over the page cap)"
                                 if report.over_page_cap(args.max_pages) else ""))
        if report.census_available:
            print("  form widgets: %d over %d form page(s)%s"
                  % (report.widget_count, report.form_pages,
                     "  (interactive form)" if report.classification == "form" else ""))
        cap = page_cap(args.max_pages)
        print("  page cap: %s" % ("none" if cap is None else cap))
        error = refusal(report, max_pages=args.max_pages)
        if error is not None:
            raise error
        return 0
    if args.out and len(args.pdf) > 1:
        ap.error("-o works with a single input")

    jobs = _check_jobs(args)
    refine, oracle, fell_back = _libreoffice_fallback(args)
    if fell_back:
        print(FALLBACK_NOTE, file=sys.stderr)

    import warnings
    from .convert import convert_result
    from .errors import OracleDegradedWarning
    for p, out_path in jobs:
        # A legacy --target wins over the new pair only when the new pair was
        # left at its default, so `--target gdocs --oracle none` is a conflict
        # rather than a silent override. options.replace() raises on that.
        legacy = {"target": args.target} if args.target else {
            "output_profile": args.output_profile, "oracle": oracle}
        progress = _Progress(os.path.basename(p),
                             enabled=False if args.verbose else None)
        try:
            with warnings.catch_warnings():
                # Reported below from the result, once, in the CLI's own words.
                warnings.simplefilter("ignore", OracleDegradedWarning)
                res = convert_result(
                    p, out_path, dpi=args.dpi, refine_rounds=refine,
                    backend=args.backend, verbose=args.verbose,
                    allow_cloud_upload=args.allow_cloud_upload or None,
                    max_pages=args.max_pages, ocr_layer=args.ocr_layer,
                    progress=progress, **legacy)
        finally:
            progress.close()
        out = res.output_path
        facts = []
        if progress.pages:
            facts.append("%d page%s" % (progress.pages,
                                        "" if progress.pages == 1 else "s"))
        total_ms = (getattr(res, "timings_ms", None) or {}).get("total")
        if total_ms is not None:
            facts.append(_fmt_s(total_ms / 1000.0))
        print("wrote %s%s" % (out, "  (%s)" % ", ".join(facts) if facts else ""))
        for w in res.warnings:
            if w.code == "image-dropped":
                continue             # already printed by the conversion
            print("warning: %s" % w.message, file=sys.stderr)
            if w.detail:
                print("  %s" % w.detail, file=sys.stderr)
        if args.verify:
            from .verify import verify, audit
            a = audit(p, out)
            print("  text coverage: %.1f%%  (%d src chars -> %d docx chars)" %
                  (100 * a["text_coverage"], a["src_chars"], a["docx_chars"]))
            rep = verify(p, out, out_dir=args.report_dir)
            if rep.get("available"):
                print("  visual similarity (SSIM, LibreOffice render): mean %.3f" %
                      rep["mean_ssim"])
                for r in rep["rows"]:
                    print("    page %d: %.3f" % (r["page"], r.get("ssim", 0)))
            else:
                print("  (LibreOffice not found: visual check skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
