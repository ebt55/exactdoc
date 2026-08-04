"""exactdoc command-line interface.

The single console entry point. Its defaults are not written here -- they come
from `exactdoc.options.PRODUCT`, so `exactdoc file.pdf`, `convert(file)` and
the CI product lane all run the same configuration. They used to run three.
"""
import argparse
import sys

from .errors import ExactdocError
from .options import BACKENDS, ORACLES, OUTPUT_PROFILES, PRODUCT, TARGETS
from .scan import MAX_PAGES_PER_DOCUMENT

# Stable, documented exit codes. A script that branches on exit status is an API
# whether or not anyone called it one, so these are part of the contract and do
# not get renumbered casually.
#
# 0  success
# 1  an unclassified exactdoc failure
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
}


def build_parser():
    ap = argparse.ArgumentParser(
        prog="exactdoc",
        description="High-fidelity PDF -> DOCX converter. Output uses only "
                    "Google Docs-safe constructs.")
    ap.add_argument("pdf", nargs="*", help="input PDF file(s)")
    ap.add_argument("-o", "--out", help="output .docx path (single input only)")
    ap.add_argument("--dpi", type=int, default=PRODUCT.dpi,
                    help="raster DPI for vector figure regions (default %(default)s)")
    ap.add_argument("--output-profile", default=PRODUCT.output_profile,
                    choices=list(OUTPUT_PROFILES),
                    help="how the DOCX is written. 'gdocs' emits line heights "
                         "Google Docs does not mistranslate. This is pure "
                         "serialisation: offline, deterministic, no network and "
                         "no credentials (default: %(default)s)")
    ap.add_argument("--oracle", default=PRODUCT.oracle, choices=list(ORACLES),
                    help="what renders the DOCX during refinement, and only "
                         "used when --refine > 0. A layout tuned for "
                         "LibreOffice is measurably not tuned for Google Docs. "
                         "'gdocs' uploads to Drive and needs "
                         "--allow-cloud-upload (default: %(default)s)")
    ap.add_argument("--allow-cloud-upload", action="store_true",
                    help="permit an oracle that sends the document to a third "
                         "party. Required for --oracle gdocs, which uploads the "
                         "DOCX to Google Drive, converts it, exports a PDF and "
                         "deletes the temporary copy. Never implied by "
                         "--output-profile gdocs, and no environment variable "
                         "can grant it")
    ap.add_argument("--target", default=None, choices=list(TARGETS),
                    help=argparse.SUPPRESS)      # deprecated; see options.py
    ap.add_argument("--backend", default=PRODUCT.backend, choices=list(BACKENDS),
                    help="PDF parser (default: %(default)s). Overrides "
                         "EXACTDOC_BACKEND")
    ap.add_argument("--refine", type=int, default=PRODUCT.refine_rounds,
                    metavar="N",
                    help="closed-loop correction passes: render the DOCX back "
                         "and correct page overflow and per-page offsets "
                         "against what actually rendered (0 disables, "
                         "default %(default)s -- the profile every published "
                         "number is measured on)")
    ap.add_argument("--max-pages", type=int, default=None, metavar="N",
                    help="page cap for a single conversion (default: %d, the "
                         "same limit batch mode enforces). A longer document is "
                         "refused rather than converted; pass a larger N to "
                         "agree to it, or 0 to remove the cap"
                         % MAX_PAGES_PER_DOCUMENT)
    ap.add_argument("--verify", action="store_true",
                    help="render the DOCX back to PDF (needs LibreOffice) and "
                         "report per-page visual similarity + text coverage")
    ap.add_argument("--report-dir", default=None,
                    help="directory for side-by-side comparison images")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--input-dir", help="directory of PDFs to convert")
    ap.add_argument("--out-dir", help="batch output directory")
    ap.add_argument("--recursive", action="store_true", help="discover PDFs recursively")
    ap.add_argument("--workers", type=int, default=None,
                    help="batch workers (currently 1; reserved range 1-4)")
    ap.add_argument("--continue-on-error", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--result-json", help="write a privacy-safe batch result report")
    ap.add_argument("--scan-only", action="store_true", help="classify PDFs without writing DOCX")
    return ap


def main(argv=None):
    """Entry point. Turns a typed failure into a message and an exit code.

    An uncaught ExactdocError used to reach the user as a traceback, which is
    the right output for a bug and the wrong one for "you asked for refinement
    without a renderer" -- an ordinary, recoverable, user-fixable situation. A
    traceback also buries the actionable sentence under a stack.
    """
    try:
        return _run(build_parser(), argv)
    except ExactdocError as e:
        code = EXIT_CODES.get(e.code, 1)
        print("error: %s" % e.message, file=sys.stderr)
        if e.detail:
            print("  %s" % e.detail, file=sys.stderr)
        return code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def _run(ap, argv):
    args = ap.parse_args(argv)
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
        from .batch import make_items, run
        items = make_items(args.input_dir, args.out_dir, recursive=args.recursive)
        report = run(items, backend=args.backend, dpi=args.dpi,
                     refine_rounds=args.refine, output_profile=args.output_profile,
                     oracle=args.oracle, allow_cloud_upload=args.allow_cloud_upload,
                     workers=1 if args.workers is None else args.workers,
                     continue_on_error=args.continue_on_error,
                     overwrite=args.overwrite, scan_only=args.scan_only,
                     verbose=args.verbose, result_json=args.result_json,
                     recursive=args.recursive)
        for item in report["items"]:
            print("%s %s" % (item["status"], item["input"]))
        return 18 if report["counts"]["failed"] or report["counts"]["ocr_required"] else 0
    if not args.pdf:
        ap.error("provide a PDF or --input-dir")
    batch_only = (args.out_dir, args.recursive, args.workers is not None,
                  args.continue_on_error, args.overwrite, args.result_json)
    if any(batch_only):
        ap.error("batch options require --input-dir")
    if args.scan_only:
        if len(args.pdf) != 1:
            ap.error("--scan-only accepts one PDF or --input-dir")
        from .convert import _select_backend
        from .scan import inspect_pdf, page_cap, refusal
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

    from .convert import convert
    for p in args.pdf:
        # A legacy --target wins over the new pair only when the new pair was
        # left at its default, so `--target gdocs --oracle none` is a conflict
        # rather than a silent override. options.replace() raises on that.
        legacy = {"target": args.target} if args.target else {
            "output_profile": args.output_profile, "oracle": args.oracle}
        out = convert(p, args.out, dpi=args.dpi, refine_rounds=args.refine,
                      backend=args.backend, verbose=args.verbose,
                      allow_cloud_upload=args.allow_cloud_upload or None,
                      max_pages=args.max_pages, **legacy)
        print("wrote", out)
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


if __name__ == "__main__":
    sys.exit(main())
