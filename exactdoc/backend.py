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


class PDFiumBackend:
    """Permissive backend, EXPERIMENTAL -- not usable for conversion yet.

    Apache-2.0/BSD-3, via pypdfium2. Reaching parity at the IR level was the
    easy part; the numbers below are why it is not the default.

    Parity achieved (vs PyMuPDF, corpus of 7 stable documents):
        vector paths        1.00x on every document, exactly
        text content        character-identical once whitespace is stripped
        visual lines        0.96 - 1.00x
        blocks              0.70 - 1.62x   <-- the gap that matters

    End-to-end, converting with this backend: **1 of 16 documents** keeps its
    page count and 95% live text. c3_tables drops to 1.1% live text, c7_code to
    0%, c6_long renders 7 source pages as 20. Nothing is wrong with the
    extraction -- the same glyphs and the same paths come out. What differs is
    the *grouping*, and inference reads grouping: block boundaries decide
    paragraph assembly, and line boundaries decide which text a figure or table
    region absorbs. A cluster classified differently rasterises a page.

    So the remaining work is not extraction, it is reproducing PyMuPDF's
    grouping decisions closely enough that the tuning still applies -- plus the
    span flags this backend does not yet derive (superscript is hardcoded
    False). testkit/golden_ir.py is the target to converge on.

    This is the measured cost of relicensing. It is a re-tune, not a rewrite,
    and it is bounded -- but it is not free, and it buys no fidelity.
    """

    name = "pdfium"
    license = "Apache-2.0"
    experimental = True

    def parse_pdf(self, path: str, keep_image_data: bool = True) -> DocIR:
        from .parse_pdfium import parse_pdf
        return parse_pdf(path, keep_image_data=keep_image_data)

    def render_clip(self, path: str, page_no: int, clip: BBox,
                    dpi: int = 240) -> Optional[bytes]:
        import io
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(path)
        page = doc[page_no - 1]
        h = page.get_height()
        scale = dpi / 72.0
        pil = page.render(scale=scale, crop=(clip[0], h - clip[3],
                                             page.get_width() - clip[2],
                                             clip[1])).to_pil()
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()

    def render_page(self, path: str, page_no: int, dpi: int = 110) -> Optional[bytes]:
        import io
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(path)
        pil = doc[page_no - 1].render(scale=dpi / 72.0).to_pil()
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()


def get_backend(name: str = "pymupdf") -> Backend:
    if name in ("pymupdf", "fitz", "default"):
        return PyMuPDFBackend()
    if name in ("pdfium", "pypdfium2"):
        return PDFiumBackend()
    raise ValueError("unknown backend %r (choose 'pymupdf' or the experimental "
                     "'pdfium'; see the module docstring)" % name)
