"""How wide will this text be? -- the one question the writer needed MuPDF for.

Three places asked it: table column fitting (`docxout._cell_text_width`), and the
quality ladder's line prediction and segment widths (`ladder.py`). All three
called `fitz.get_text_length(text, fontname=<base-14 name>, fontsize=size)`, which
reads MuPDF's own base-14 metric tables. That single call is why a wheel installed
without PyMuPDF cannot write a DOCX, and it is not a parser concern at all, so the
backend seam never covered it.

**The first answer is not to shape the text.** The source PDF already measured it:
`Para.src_widths` carries the width of every visual line as the producer laid it
out, in points, recorded by `infer` from the line bboxes. For "is this column too
narrow for its own single-line content", that is a better answer than re-shaping
in a substitute font -- it is what actually happened rather than a prediction of
what will happen, and the writer maps fonts metric-compatibly (Helvetica->Arial,
Times->Times New Roman) precisely so the two stay close.

Where a caller genuinely needs to shape text that has no source line -- the
ladder's greedy first-fit over words, predicting a re-wrap that by definition did
not occur in the source -- there is no permissive answer available in this tree.
MuPDF's base-14 tables are not copied here: they are AGPL, they are measurably
version-dependent (STATUS §5), and vendoring them would defeat the point of the
licence work. So `NullMetrics` reports "unmeasurable", every caller already has
that path because a non-base-14 font always produced it, and they degrade to
doing nothing rather than to guessing.

That is a real, stated limitation and not a silent one: with the permissive
backend and no `[mupdf]` extra installed, the quality ladder cannot run. It is
off by default and has been since it was measured and left switched off, so the
shipped product is unaffected -- but `--ladder` needs the extra until a permissive
shaper lands here.
"""
from typing import Optional, Protocol


class TextMetrics(Protocol):
    """Text measurement, in points.

    `None` means *unmeasurable*, never zero. The distinction matters: a width of
    0 says "this text takes no space" and would shrink a column to nothing,
    whereas unmeasurable says "do not act on this", which is what every caller
    here should do when it cannot know.
    """

    name: str

    def text_width(self, text: str, font: str, size: float, bold: bool = False,
                   italic: bool = False) -> Optional[float]:
        ...


class NullMetrics:
    """Measures nothing, and says so. The permissive default.

    Not a failure mode -- a declared capability boundary. Callers already handle
    it, because a font with no base-14 equivalent has always produced exactly
    this answer.
    """

    name = "none"

    def text_width(self, text, font, size, bold=False, italic=False):
        return None


class MuPDFMetrics:
    """Base-14 shaping via MuPDF. Requires the `[mupdf]` extra.

    Kept because it is what every published ladder measurement was taken with,
    so archiving it would make those numbers unreproducible. Never the default:
    selecting it is what makes the combination AGPL-governed for distribution.
    """

    name = "mupdf"

    def __init__(self):
        import fitz                                    # noqa: F401
        self._fitz = fitz

    def text_width(self, text, font, size, bold=False, italic=False):
        from .ladder import _b14
        fn = _b14(font, bold, italic)
        if fn is None:
            return None
        try:
            return self._fitz.get_text_length(text, fontname=fn, fontsize=size)
        except Exception:
            return None


def get_metrics(name: Optional[str] = None) -> TextMetrics:
    """`None` or 'none' -> NullMetrics; 'mupdf' -> MuPDFMetrics if importable.

    Asking for MuPDF metrics on an installation without PyMuPDF degrades to
    NullMetrics rather than raising: the caller's contract is already "act only
    on a measurement you got", and a missing optional extra is not a conversion
    failure.
    """
    if name in (None, "", "none"):
        return NullMetrics()
    if name in ("mupdf", "pymupdf", "fitz"):
        try:
            return MuPDFMetrics()
        except ImportError:
            return NullMetrics()
    raise ValueError("unknown text metrics %r (choose 'none' or 'mupdf')" % name)


# ------------------------------------------------------------ the IR's own facts
def source_line_width(para) -> Optional[float]:
    """The widest source line of a paragraph that occupied exactly one.

    `None` when the paragraph wrapped in the source (its width is then a column
    width, not a content width, and says nothing about what the content needs) or
    when `infer` recorded no widths for it -- some cells are built by a path that
    does not set them, and an absent fact must not be read as a measurement of
    zero.
    """
    if para.src_lines != 1 or not para.src_widths:
        return None
    w = para.src_widths[0]
    return w if w > 0 else None
