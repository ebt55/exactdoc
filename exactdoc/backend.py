"""The parser seam: what exactdoc requires of a PDF backend.

exactdoc links PyMuPDF, which is AGPL-3.0, so exactdoc is AGPL-3.0 too. That
is inherited, not chosen, and it costs adoption -- many organisations refuse
AGPL dependencies outright, and a permissive project cannot embed an AGPL one.
Moving to a permissive parser would allow relicensing.

The obstacle is not the API surface -- that is about eighteen calls. It is
that every threshold downstream was calibrated against the *shape* of what
`page.get_text("dict")` returns, above all its grouping of glyphs into spans,
lines and blocks. Inference rebuilds paragraphs from blocks, so a backend that
groups differently invalidates the tuning rather than merely relocating it.

Measured (testkit/backend_probe.py, 20 documents, ratio to PyMuPDF):

    axis     median   range        note
    chars     1.00    0.84 - 1.00  pdfminer loses up to 16% of text on LaTeX
    lines     0.98    0.73 - 1.79
    blocks    1.39    0.55 - 3.67  the paragraph foundation; diverges wildly
    drawings  1.00    0.04 - 1.12  pdfminer sees 4% of paths on arXiv papers

So pdfminer.six is not a drop-in: it is materially worse on the dialect that
is already weakest. pypdfium2 (Apache-2.0) extracts text and paths but offers
no line or block grouping at all, which means writing that clustering here.

That is the actual plan, and it is why this seam exists. Writing the
clustering ourselves means we *control* the grouping, so the existing tuning
stops being a liability and becomes the specification: the port is correct
when it reproduces the frozen golden IR (testkit/golden_ir.py). A verifiable
port, not a rewrite.

Until then: **do not accept external contributions to parse.py.** Relicensing
needs every contributor's consent, and the swap is confined to this one
module -- contributions anywhere else cost nothing.

A backend must provide:

    parse_pdf(path, keep_image_data=True) -> DocIR
        Text as spans carrying font name, size, colour, bold/italic/mono/serif
        flags, bbox and *baseline origin*; spans grouped into visual lines and
        lines into blocks; vector paths with fill/stroke colour, width and
        item list; placed images with bbox and bytes; link rectangles + URIs.
        Coordinates in points, origin top-left.

    render_clip(path, page_no, clip, dpi) -> PNG bytes
        Used for figure regions.

    render_page(path, page_no, dpi) -> PNG bytes
        Used by the verification loop.

The IR contract itself is exactdoc/model.py; this module names the operations
so a second implementation has somewhere to live.
"""
from typing import Optional, Protocol, Tuple

from .model import DocIR

BBox = Tuple[float, float, float, float]


class Backend(Protocol):
    """Structural interface. PyMuPDF is the only implementation today."""

    name: str

    def parse_pdf(self, path: str, keep_image_data: bool = True) -> DocIR:
        ...

    def render_clip(self, path: str, page_no: int, clip: BBox,
                    dpi: int = 240) -> Optional[bytes]:
        ...

    def render_page(self, path: str, page_no: int, dpi: int = 110) -> Optional[bytes]:
        ...


class PyMuPDFBackend:
    """The current backend. AGPL-3.0, via PyMuPDF."""

    name = "pymupdf"
    license = "AGPL-3.0"

    def parse_pdf(self, path: str, keep_image_data: bool = True) -> DocIR:
        from .parse import parse_pdf
        return parse_pdf(path, keep_image_data=keep_image_data)

    def render_clip(self, path: str, page_no: int, clip: BBox,
                    dpi: int = 240) -> Optional[bytes]:
        import fitz
        doc = fitz.open(path)
        try:
            page = doc[page_no - 1]
            pix = page.get_pixmap(clip=fitz.Rect(*clip), dpi=dpi, alpha=False)
            return pix.tobytes("png")
        finally:
            doc.close()

    def render_page(self, path: str, page_no: int, dpi: int = 110) -> Optional[bytes]:
        import fitz
        doc = fitz.open(path)
        try:
            return doc[page_no - 1].get_pixmap(dpi=dpi, alpha=False).tobytes("png")
        finally:
            doc.close()


def get_backend(name: str = "pymupdf") -> Backend:
    if name in ("pymupdf", "fitz", "default"):
        return PyMuPDFBackend()
    raise ValueError("unknown backend %r (only 'pymupdf' exists; see the module "
                     "docstring for why, and what a second one must satisfy)" % name)
