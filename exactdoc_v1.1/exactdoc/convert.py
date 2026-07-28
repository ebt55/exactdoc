"""End-to-end conversion API + CLI."""
import os
import sys
import argparse

from .parse import parse_pdf
from .dialect import normalize
from .infer import infer
from .docxout import write_docx


def convert(pdf_path: str, out_path: str = None, dpi: int = 240,
            refine_rounds: int = 0, verbose: bool = False) -> str:
    """Convert a PDF to DOCX.

    `refine_rounds` > 0 enables the closed-loop pass: render the DOCX back and
    correct page overflow and per-page offsets against what actually rendered.
    It needs LibreOffice and costs one render per round; without LibreOffice it
    degrades silently to the ordinary single write.
    """
    if out_path is None:
        out_path = os.path.splitext(pdf_path)[0] + ".docx"
    ir = normalize(parse_pdf(pdf_path))
    lay = infer(ir)
    if refine_rounds > 0:
        from .refine import refine
        return refine(lay, pdf_path, out_path, dpi=dpi,
                      rounds=refine_rounds, verbose=verbose)
    return write_docx(lay, out_path, dpi=dpi)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="exactdoc",
        description="High-fidelity PDF -> DOCX converter (Google Docs-safe output)")
    ap.add_argument("pdf", nargs="+", help="input PDF file(s)")
    ap.add_argument("-o", "--out", help="output .docx (single input only)")
    ap.add_argument("--dpi", type=int, default=240,
                    help="raster DPI for vector figure regions (default 240)")
    args = ap.parse_args(argv)
    if args.out and len(args.pdf) > 1:
        ap.error("-o works with a single input")
    for p in args.pdf:
        out = convert(p, args.out, dpi=args.dpi)
        print("wrote", out)


if __name__ == "__main__":
    main()
