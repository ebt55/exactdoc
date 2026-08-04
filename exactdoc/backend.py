"""The parser seam: what exactdoc requires of a PDF backend.

exactdoc's declared project license remains AGPL-3.0-or-later. PyMuPDF is the
measured shipping parser; pypdfium2 is an optional candidate evaluated through
this seam. Licensing is decided separately from this code path.

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
clustering ourselves means we *control* the grouping.

**What "correct" means here, and what it does not.** The port is correct when
`testkit/backend_parity.py` finds it no worse than PyMuPDF on the rendered
output. It is NOT "reproduce the frozen golden IR" -- that was the target for a
while, and it is the wrong finish line for three measured reasons:

  - This backend deliberately refuses to reproduce three PyMuPDF behaviours
    because they are bugs: RTL returned in visual order (renders Arabic
    backwards), gradients dropped (white text left invisible on white), and
    Calibri reported as serif.
  - PyMuPDF's grouping is not stable across its own releases. Measured:
    1.24.14 and 1.26.0 put page 2 of 02_research_paper in 4 blocks, 1.28.0
    puts it in 7. A target that moves with a dependency version cannot be a
    specification.
  - The golden is regenerated from a corpus that is itself regenerated, so it
    describes an environment as much as a parser (hence the manifest it now
    carries).

The golden IR is a **microscope**: a fast, oracle-free, per-document diff for
finding *where* two parsers disagree. The parity gate is the **contract**. When
they disagree, the parity gate wins.

Candidate changes remain isolated behind this seam so their parity can be
measured without altering the shipping parser.

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

    page_lines(path) -> [[(text, y_top, y_baseline, y_bottom), ...], ...]
        Text lines with their vertical anchors, per page. What the closed loop needs
        to map source pages onto rendered ones and measure the offset between them.
        A distinct operation rather than a full parse on purpose: the loop runs it
        on every round, over a document it has just written, and it wants none of
        the drawings, images, links or style flags that `parse_pdf` builds.

        Both anchors are reported because which one the loop should use is a
        measured question with a counter-intuitive answer, and the measurement is
        worth keeping available. The loop subtracts a source y from a rendered y
        over two differently-typeset documents, so a line-box TOP carries a
        per-font metric convention that does not cancel, while a BASELINE is a
        number in the content stream and does. Baselines are therefore the
        physically correct anchor, and the writer's own vertical model is
        baseline-anchored (THEORY 3.1).

        Measured anyway, on the canonical corpus: switching the loop to baselines
        took the incumbent's mean within-2pt from **0.511 to 0.478**. It fixed the
        two documents that the box-top anchor cost under PDFium and broke others
        -- 05_memo 0.64 -> 0.48, r1_reportlab_report 0.60 -> 0.32, while
        04_exec_brief gained 0.22 -> 0.44. This is the *same* result as the
        line-box escalation in STATUS D2, in a second location: the `space_before`
        chain the offsets are fed into is itself calibrated against a box-top
        origin, so moving the anchor alone desynchronises the correction from the
        thing it corrects. Both must move together, which is a project rather than
        a patch. The loop uses box tops.

The IR contract itself is exactdoc/model.py; this module names the operations
so a second implementation has somewhere to live.
"""
from typing import List, Optional, Protocol, Tuple

from .model import DocIR

BBox = Tuple[float, float, float, float]
# (text, y_top, y_baseline, y_bottom)
PageLines = List[List[Tuple[str, float, float, float]]]


class Backend(Protocol):
    """Structural interface. One shipping and one candidate implementation.

    Selected once per conversion, by name, from `ConversionOptions.backend` --
    not by an environment variable read at an arbitrary depth, and not by
    assigning over a module global. `EXACTDOC_BACKEND` still works and is now the
    lowest-priority source.

    The seam covers parsing and rendering. The writer, refiner and verifier
    receive the selected backend instead of importing `fitz` themselves, so the
    PDFium candidate can run without importing the PyMuPDF shipping backend.
    """

    name: str

    def parse_pdf(self, path: str, keep_image_data: bool = True) -> DocIR:
        ...

    def render_clip(self, path: str, page_no: int, clip: BBox,
                    dpi: int = 240) -> Optional[bytes]:
        ...

    def render_page(self, path: str, page_no: int, dpi: int = 110) -> Optional[bytes]:
        ...

    def page_lines(self, path: str) -> PageLines:
        ...

    def form_widgets(self, path: str) -> List[int]:
        """Interactive form widget annotations per page, in page order.

        A census, not a parse. It exists in the seam rather than on the IR
        because `DocIR` carries what the *layout* needs -- text, paths, images,
        links -- and a widget contributes none of that; adding it to the IR would
        make every backend reproduce an annotation model that nothing downstream
        reads. The preflight layer wants one integer per page and nothing else.

        Backends predating this operation are tolerated: a missing
        `form_widgets` means form detection did not run, and the scan report says
        so (`census_available=False`) instead of recording a census of zero that
        nobody took.
        """
        ...


class PyMuPDFBackend:
    """Measured shipping backend, provided by the core PyMuPDF dependency."""

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

    def page_lines(self, path: str) -> PageLines:
        import fitz
        doc = fitz.open(path)
        try:
            out = []
            for page in doc:
                lines = []
                for b in page.get_text("dict")["blocks"]:
                    if b.get("type") != 0:
                        continue
                    for ln in b["lines"]:
                        if not ln["spans"]:
                            continue
                        t = "".join(s["text"] for s in ln["spans"])
                        if t.strip():
                            lines.append((t, ln["bbox"][1],
                                          ln["spans"][0]["origin"][1],
                                          ln["bbox"][3]))
                out.append(lines)
            return out
        finally:
            doc.close()

    def form_widgets(self, path: str) -> List[int]:
        import fitz
        from .errors import UnsupportedInputError
        doc = fitz.open(path)
        try:
            # Same documented status check `parse.parse_pdf` makes, for the same
            # reason and now at the same boundary: PyMuPDF opens an encrypted
            # document successfully and rejects every operation on it with a
            # generic ValueError. This census runs *before* the parse, so it is
            # the first call to touch the file and must not let a password-
            # protected PDF escape as an untranslated reader diagnostic.
            if doc.needs_pass:
                raise UnsupportedInputError(
                    "password-protected PDFs are not supported")
            return [sum(1 for _ in page.widgets()) for page in doc]
        finally:
            doc.close()


class PDFiumBackend:
    """Explicit PDFium candidate, provided by the optional ``pdfium`` extra.

    pypdfium2 is Apache-2.0/BSD-3. Selecting this candidate does not by itself
    change exactdoc's project license. Extraction and placement remain measured
    compatibility concerns.

    Extraction, vs PyMuPDF (testkit/backend_geom.py, 8 documents, 4734
    matched lines):
        baselines           identical on 4734 of 4734
        leadings            identical on 99-100% of pairs
        font size           within 0.005pt (the OOXML quantum is 0.5pt)
        font names          identical on all 494 sampled lines
        vector paths        1.00x on every document, exactly
        text content        character-identical once whitespace is stripped
        block grouping      35% agreement            <-- the gap that matters

    Every quantity that reaches the writer's vertical model is exact. What
    differs is *grouping*, and inference reads grouping: block boundaries decide
    paragraph assembly, and line boundaries decide which text a figure or table
    region absorbs. A cluster classified differently rasterises a page.

    End-to-end that cost 15 regressions before block convergence, then 9 before
    the serif-flag fix, then 7. Any current verdict comes from a parity policy
    bound to the selected full profile; legacy measurements cannot authorize a
    swap. testkit/exp_regroup.py grafts PyMuPDF's block boundaries onto
    this backend's geometry and showed the cost was bimodal: grouping was the
    entire cause on c6_long (0.23 -> 0.73) and c8_toc_links (0.63 -> 1.00), and
    none of it on c7_code or r1_reportlab_report, which did not move.

    `superscript` is still hardcoded False, and measurement says leave it that
    way: testkit/backend_superscript.py shows the writer never sees this flag --
    `dialect` and `infer` recover superscript from geometry, and all 16 corpus
    documents agree at the layout level, including the one that has any.

    This remains candidate work until its full profile is measured and reviewed.
    """

    name = "pdfium"
    license = "Apache-2.0"
    experimental = True

    def parse_pdf(self, path: str, keep_image_data: bool = True) -> DocIR:
        from .parse_pdfium import parse_pdf
        return parse_pdf(path, keep_image_data=keep_image_data)

    # Every native handle below is closed on the way out, in reverse order of
    # acquisition. It was not: a parity run over 16 documents ended with pypdfium2
    # printing "The following objects are still open and will now be closed" and
    # listing 16 documents, 18 pages and 9 text pages. The interpreter's exit
    # happened to collect them, which is not a resource policy -- a long-running
    # process converting a queue of PDFs would hold every one of them until it
    # died.
    @staticmethod
    def _png(bitmap) -> bytes:
        """PIL image -> PNG bytes, releasing the native bitmap.

        `PdfBitmap.to_pil()` returns a view backed by the bitmap's buffer, so the
        bitmap must outlive the encode and must then be closed. Neither happened:
        the bitmap was a temporary whose handle nothing released, one per rendered
        page and per figure clip.
        """
        import io
        try:
            buf = io.BytesIO()
            bitmap.to_pil().save(buf, format="PNG")
            return buf.getvalue()
        finally:
            bitmap.close()

    def render_clip(self, path: str, page_no: int, clip: BBox,
                    dpi: int = 240) -> Optional[bytes]:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(path)
        try:
            page = doc[page_no - 1]
            try:
                h = page.get_height()
                return self._png(page.render(
                    scale=dpi / 72.0,
                    crop=(clip[0], h - clip[3],
                          page.get_width() - clip[2], clip[1])))
            finally:
                page.close()
        finally:
            doc.close()

    def render_page(self, path: str, page_no: int, dpi: int = 110) -> Optional[bytes]:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(path)
        try:
            page = doc[page_no - 1]
            try:
                return self._png(page.render(scale=dpi / 72.0))
            finally:
                page.close()
        finally:
            doc.close()

    def page_lines(self, path: str) -> PageLines:
        import pypdfium2 as pdfium
        from .parse_pdfium import _build_lines, _page_chars
        doc = pdfium.PdfDocument(path)
        try:
            out = []
            for i in range(len(doc)):
                page = doc[i]
                try:
                    textpage = page.get_textpage()
                    try:
                        chars = _page_chars(textpage, page.get_height())
                    finally:
                        textpage.close()
                    lines = [(ln.text, ln.bbox[1], ln.baseline, ln.bbox[3])
                             for ln in _build_lines(chars) if ln.text.strip()]
                finally:
                    page.close()
                out.append(lines)
            return out
        finally:
            doc.close()

    def form_widgets(self, path: str) -> List[int]:
        # pypdfium2's object layer has no annotation wrapper, so this counts
        # through the documented raw calls. Every annotation handle acquired is
        # closed on the way out: `FPDFPage_GetAnnot` allocates, and a census over
        # a 199-widget document would otherwise leak 199 handles per run.
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
        doc = pdfium.PdfDocument(path)
        try:
            counts = []
            for i in range(len(doc)):
                page = doc[i]
                try:
                    n = 0
                    for j in range(raw.FPDFPage_GetAnnotCount(page)):
                        annot = raw.FPDFPage_GetAnnot(page, j)
                        if not annot:
                            continue
                        try:
                            if raw.FPDFAnnot_GetSubtype(annot) == raw.FPDF_ANNOT_WIDGET:
                                n += 1
                        finally:
                            raw.FPDFPage_CloseAnnot(annot)
                    counts.append(n)
                finally:
                    page.close()
            return counts
        finally:
            doc.close()


_IMPLEMENTATIONS = {"pymupdf": PyMuPDFBackend, "pdfium": PDFiumBackend}
_EXPERIMENTAL = {}


class FunctionBackend:
    """A backend built from a `parse_pdf` callable, for experiments.

    The instruments in `testkit/` need to convert the corpus through a parse
    function that is neither named backend -- PDFium geometry with PyMuPDF's
    block boundaries grafted on (`exp_regroup.py`), or PyMuPDF with the Chromium
    bullet fix applied (`exp_chromefix.py`). They did it by assigning
    `exactdoc.convert.parse_pdf`, which worked only because `convert` happened to
    hold the parser as a module global. The moment the backend was selected
    through the seam instead, that assignment became a no-op that set an
    attribute nobody read -- and an experiment that silently measures the default
    is worse than one that crashes, because it produces a number.

    So the seam takes registrations. Rendering falls through to a real backend,
    because an experiment on grouping has no opinion about rasterising a clip.
    """

    experimental = True

    def __init__(self, name, parse, renderer=None, license=None):
        self.name = name
        self._parse = parse
        self._renderer = renderer or PyMuPDFBackend()
        self.license = license

    def parse_pdf(self, path: str, keep_image_data: bool = True) -> DocIR:
        return self._parse(path, keep_image_data=keep_image_data)

    def render_clip(self, path, page_no, clip, dpi: int = 240):
        return self._renderer.render_clip(path, page_no, clip, dpi=dpi)

    def render_page(self, path, page_no, dpi: int = 110):
        return self._renderer.render_page(path, page_no, dpi=dpi)

    def form_widgets(self, path: str):
        # An experiment on block grouping has no opinion about annotations
        # either, so the census falls through with the rendering.
        return self._renderer.form_widgets(path)


def register_backend(name: str, parse, renderer=None) -> str:
    """Make `parse` selectable as `backend=name`. Returns the name.

    For instruments and experiments only. Nothing in the package registers
    anything, and a registered name is never a default.
    """
    if name in _IMPLEMENTATIONS:
        raise ValueError("%r is a named backend; pick another name" % name)
    _EXPERIMENTAL[name] = FunctionBackend(name, parse, renderer=renderer)
    return name


def get_backend(name: str = None) -> Backend:
    """Instantiate a backend by name. Aliases resolve in options.py.

    Name resolution lives in one place on purpose: an unrecognised backend name
    that quietly fell back to the default would report numbers for a parser
    nobody selected.
    """
    from .options import DEFAULT_BACKEND, canonical_backend
    if name in _EXPERIMENTAL:
        return _EXPERIMENTAL[name]
    return _IMPLEMENTATIONS[canonical_backend(name or DEFAULT_BACKEND)]()
