"""exactdoc command-line interface.

The single console entry point. Its defaults are not written here -- they come
from `exactdoc.options.PRODUCT`, so `exactdoc file.pdf`, `convert(file)` and
the CI product lane all run the same configuration. They used to run three.
"""
import argparse

from .options import BACKENDS, PRODUCT, TARGETS


def build_parser():
    ap = argparse.ArgumentParser(
        prog="exactdoc",
        description="High-fidelity PDF -> DOCX converter. Output uses only "
                    "Google Docs-safe constructs.")
    ap.add_argument("pdf", nargs="+", help="input PDF file(s)")
    ap.add_argument("-o", "--out", help="output .docx path (single input only)")
    ap.add_argument("--dpi", type=int, default=PRODUCT.dpi,
                    help="raster DPI for vector figure regions (default %(default)s)")
    ap.add_argument("--target", default=PRODUCT.target, choices=list(TARGETS),
                    help="which program the output should look right in. The "
                         "closed loop optimises for this renderer, and the "
                         "choice matters: a layout tuned for LibreOffice is "
                         "measurably not tuned for Google Docs. 'gdocs' needs "
                         "Drive credentials (default: %(default)s)")
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
    ap.add_argument("--verify", action="store_true",
                    help="render the DOCX back to PDF (needs LibreOffice) and "
                         "report per-page visual similarity + text coverage")
    ap.add_argument("--report-dir", default=None,
                    help="directory for side-by-side comparison images")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.out and len(args.pdf) > 1:
        ap.error("-o works with a single input")

    from .convert import convert
    for p in args.pdf:
        out = convert(p, args.out, dpi=args.dpi, refine_rounds=args.refine,
                      target=args.target, backend=args.backend,
                      verbose=args.verbose)
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
    main()
