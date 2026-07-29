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
from .options import ConversionOptions, resolve


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
            options: Optional[ConversionOptions] = None) -> str:
    """Convert a PDF to DOCX. Returns the output path.

    Defaults come from `options.PRODUCT`: the pdfium/PyMuPDF backend it names,
    the LibreOffice target, and its refine round count. Pass `options=` to
    supply a whole profile, or individual keywords to override parts of it. A
    `None` keyword means "take the profile's value", never "zero".

    `refine_rounds` > 0 enables the closed-loop pass: render the DOCX back and
    correct page overflow and per-page offsets against what actually rendered.

    `target` chooses which renderer that loop optimises for -- "gdocs",
    "libreoffice" or "none". This is a real choice, not a detail: a layout
    tuned for LibreOffice is measurably not tuned for Google Docs. If the
    chosen oracle is unavailable the conversion still succeeds, open-loop.
    """
    if backend is None:
        env = os.environ.get("EXACTDOC_BACKEND", "").strip()
        backend = env or None
    opts = resolve(options, backend=backend, target=target, dpi=dpi,
                   refine_rounds=refine_rounds, ladder=ladder, verbose=verbose)
    if out_path is None:
        out_path = os.path.splitext(pdf_path)[0] + ".docx"

    bk = _select_backend(opts.backend)
    ir = normalize(bk.parse_pdf(pdf_path))
    lay = infer(ir)
    if opts.ladder:
        from .ladder import apply_ladder, summarise
        rep = apply_ladder(lay)
        lay.ladder_report = rep
        if opts.verbose:
            print("  ladder: " + summarise(rep))
    if opts.refine_rounds > 0:
        from .refine import refine
        from .targets import get_renderer
        render, resolved = get_renderer(opts.target)
        if render is not None:
            if opts.verbose:
                print("  refining against: %s" % resolved)
            return refine(lay, pdf_path, out_path, dpi=opts.dpi,
                          rounds=opts.refine_rounds, verbose=opts.verbose,
                          render=render, target=opts.target)
    from .docxout import write_docx
    return write_docx(lay, out_path, dpi=opts.dpi, target=opts.target)


def main(argv=None):
    """Deprecated alias. The console entry point is `exactdoc.cli:main`."""
    from .cli import main as _main
    return _main(argv)


if __name__ == "__main__":
    main()
