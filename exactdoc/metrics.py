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
not occur in the source -- there has to be a shaper. `Base14Metrics` is it, and
it is permissive.

**Why there is a table here at all, when the module used to say there could not
be.** The sentence this replaces read "there is no permissive answer available in
this tree", and it was wrong for a reason worth keeping: it conflated *MuPDF's
tables*, which are AGPL, with *the metrics themselves*, which are not. The
advance widths of the 14 standard PostScript faces are published Adobe data,
reproduced in the PDF specification and shipped by every PDF toolkit. What was
unavailable was permission to copy MuPDF's copy. `exactdoc/_base14_widths.py`
takes them from reportlab's BSD-3 tables instead and cross-checks them against a
second implementation, so nothing here descends from AGPL code.

That distinction is the whole fix, and it closed a gap that had become a release
problem. The ladder was switched ON by default at c9d36df because on
`c1_whitepaper` it is half of what takes dy_p50 from 101.0 to 2.0. While the only
shaper needed the `[mupdf]` extra, a default install ran an inert ladder and
produced measurably worse output on exactly the document class this converter
exists for -- `c1_whitepaper` back to within2pt 0.0000, `l1_word_native` dy_p50
3.31 -> 11.04. Measured in `docs/evidence/base-wheel-proof-2026-08-06.json`.
**The extra is no longer a quality axis: both installs shape text with this
module and produce identical output.**

**The shaper is not bug-compatible with MuPDF, and that is deliberate.** MuPDF's
base-14 lookup resolves Latin-1 only: for the 27 WinAnsi codepoints above
U+00FF -- en dash, em dash, curly quotes, bullet, ellipsis, Euro, trademark,
OE/oe, the caron letters -- it silently charges the face's *space* width instead
of the glyph's. An em dash in Helvetica is 1000 units; MuPDF answers 278. This
module answers 1000, because that is what the AFM says and what the renderer will
do. The two agree on every one of the 2190 Latin-1 cells checked, and disagree
on 218 cells that MuPDF was never seeing.

That is not an incidental improvement. `ladder._measurable` gates on
`ch.encode("cp1252")` -- it has always claimed the WinAnsi repertoire is
measurable -- so text carrying an en dash passed the gate and was then mis-shaped
by a tenth of an em per character. It is the same defect commit 6575118 was
written about, in the same function, one repertoire further out: *it returned a
number anyway*. Fixing the shaper makes `_measurable`'s stated contract true
rather than aspirational.

`MuPDFMetrics` is kept and still selectable by name, because every published
ladder measurement before 2026-08-06 was taken with it and archiving it would
make those numbers unreproducible. The product never selects it.
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
    """Measures nothing, and says so.

    Not a failure mode -- a declared capability boundary. Callers already handle
    it, because a font with no base-14 equivalent has always produced exactly
    this answer.

    No longer the default, and no longer what a PyMuPDF-free install gets:
    `Base14Metrics` is. It stays because "measure nothing" remains a real
    configuration -- `get_metrics("none")` is how a caller switches the ladder
    off at the metrics layer rather than at the option -- and because every
    caller's null path is exercised by it.
    """

    name = "none"

    def text_width(self, text, font, size, bold=False, italic=False):
        return None


class Base14Metrics:
    """Base-14 shaping from the published Adobe AFM widths. No dependencies.

    The permissive default, and after 2026-08-06 the only shaper the product
    selects. See the module docstring for provenance and for the one place it
    deliberately disagrees with MuPDF.

    It also shapes Calibri and Cambria, from their metric clones' own advance
    tables (`_clone_widths.py`, generated from the OFL/Apache Carlito and
    Caladea files). They used to be shaped -- Calibri only -- with Helvetica's
    widths, 8.6% too wide; see `ladder._CLONE`. The class keeps its name and
    its `name` because every report and test addresses it that way.

    Width of a string = sum of its glyphs' advances, scaled by size/1000. Two
    properties of the base-14 faces make that exact rather than approximate, and
    both were measured rather than assumed (`tests/test_base14_metrics.py`):
    advances are additive -- no kerning is applied to a simple `Tj`, so
    `width("AV") == width("A") + width("V")` -- and the result is linear in
    size, so one table serves every point size.
    """

    name = "base14"

    def text_width(self, text, font, size, bold=False, italic=False):
        from ._base14_widths import COURIER_WIDTH, FALLBACK, WIDTHS
        from .ladder import _face
        fn = _face(font, bold, italic)
        if fn is None:
            return None
        table = WIDTHS.get(fn, "absent")
        if table == "absent":
            # Calibri and Cambria, shaped from their metric clones' own files
            # (exactdoc/_clone_widths.py). Same arithmetic as the base-14 path
            # -- additive advances, linear in size -- in the face's own units.
            from . import _clone_widths as C
            clone = C.WIDTHS.get(fn)
            if clone is None:
                return None
            fb = C.FALLBACK[fn]
            total = 0
            for ch in text:
                total += clone.get(ord(ch), fb)
            return total * size / float(C.UNITS_PER_EM[fn])
        if table is None:                       # Courier: fixed pitch
            return len(text) * COURIER_WIDTH * size / 1000.0
        fallback = FALLBACK[fn]
        total = 0
        for ch in text:
            total += table.get(ord(ch), fallback)
        return total * size / 1000.0


class MuPDFMetrics:
    """Base-14 shaping via MuPDF. Requires the `[mupdf]` extra.

    **An archive, not a code path.** Nothing in the product selects it: it is
    kept because every published ladder measurement before 2026-08-06 was taken
    with it, and archiving it would make those numbers unreproducible. Asking
    for it by name is how a reader re-derives them.

    It is also the reference the permissive shaper is checked against, which is
    the second reason to keep it installed in the measurement environment and
    nowhere else -- adding the extra is what makes the combination AGPL-governed
    for distribution.
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
    """`None` -> Base14Metrics, the default. 'none' -> NullMetrics.

    **`None` and `"none"` mean different things, and the difference is the whole
    fix.** `None` is "give me the default shaper", which every install now has.
    `"none"` is an explicit request to measure nothing. They used to return the
    same object, because there was no default shaper to return.

    `'mupdf'` still resolves to `MuPDFMetrics` for reproducing pre-2026-08-06
    measurements, and still degrades rather than raising when the extra is
    absent -- but it degrades to `Base14Metrics` now, not to `NullMetrics`. That
    is what makes a missing extra a difference in *provenance* rather than in
    *capability*: the caller asked for base-14 widths and gets base-14 widths
    either way.
    """
    if name is None or name == "base14":
        return Base14Metrics()
    if name == "":
        return Base14Metrics()
    if name == "none":
        return NullMetrics()
    if name in ("mupdf", "pymupdf", "fitz"):
        try:
            return MuPDFMetrics()
        except ImportError:
            return Base14Metrics()
    raise ValueError("unknown text metrics %r (choose 'base14', 'none' or "
                     "'mupdf')" % name)


# ------------------------------------------------- matching the source's widths
# OOXML can only state a font size in half-points and the substitute family is
# rarely the source's own, so a run written as-is draws at a different width
# from the one the PDF drew -- and the paragraph re-wraps. Two residuals, both
# measurable, multiply:
#
#   size    10.125pt (13.5px) can only be written as 10.0 or 10.5; 9.6975 as 9.5.
#           Measured on the owner's resume and paper (defect catalogue #19):
#           every paragraph re-wraps; c1_whitepaper's 9.33pt body is written 9.5
#           (+1.8% wide). Font-independent: s / round(2s)/2.
#   family  the substitute's advances against the source font's own, measured
#           from the PDF (DocIR.font_advances) and the shaper's tables. CMTT10
#           and CMU Typewriter draw at 0.525em; Courier New, the only monospace
#           every renderer has, at 0.600 -- 14% wide, enough to wrap code lines
#           and spill pages: y26 (Bash manual) lost its page alignment at the
#           first case-statement listing (word recall on the right page 0.964 ->
#           0.416) when CMTT10 became Courier New without this.
#
# The writer states the product as w:w, the run's horizontal scale, which Word
# and LibreOffice honour. An integer percent: a residual under half a percent
# rounds to 100 and nothing is written. Standard profile only -- Google Docs is
# not known to honour w:w, and it has already been measured discarding w:spacing
# (fonts.GDOCS_HONOURS_RUN_TRACKING).
#
# The family residual is taken only for monospace-to-monospace, where it keeps
# a character grid that the substitution would break, and is bounded: past
# MONO_SCALE_MAX the glyphs visibly change shape. Proportional family mismatches
# (Computer Modern -> Times New Roman, -10%) are NOT compensated here; that is a
# typeface decision with an editability cost and is left to be measured on its
# own.
MONO_SCALE_MAX = 0.20
# Proportional family residual: 0 = not compensated (see above).
PROP_SCALE_MAX = 0.0


def run_width_scale(run, advances, metrics) -> float:
    """The w:w factor that makes `run` draw at its source width, or 0.0 for none."""
    if run.is_tab or not run.text or run.size < 1.0:
        return 0.0
    from .fonts import font_traits, map_font
    s = run.size
    q = round(s * 2) / 2
    if q <= 0:
        return 0.0
    k = s / q
    fam = map_font(run.font, mono=run.mono, serif=run.serif)
    src_mono = run.mono or font_traits(run.font).cls == "mono"
    tgt_mono = font_traits(fam).cls == "mono"
    table = (advances or {}).get(run.font)
    glyphs = "".join(ch for ch in run.text if not ch.isspace())
    cap = MONO_SCALE_MAX if (src_mono and tgt_mono) else \
        PROP_SCALE_MAX if (not src_mono and not tgt_mono) else 0.0
    if cap > 0 and table and glyphs and all(ch in table for ch in glyphs):
        tgt = metrics.text_width(glyphs, fam, 1.0, bold=run.bold,
                                 italic=run.italic) if metrics else None
        src = sum(table[ch] for ch in glyphs)
        if tgt and tgt > 0 and src > 0 and abs(src / tgt - 1.0) <= cap:
            k *= src / tgt
    pct = int(round(100 * k))
    return 0.0 if pct == 100 else pct / 100.0


def apply_width_scale(lay, metrics=None) -> int:
    """Set `Run.width_scale` on every run of a layout. Returns how many changed.

    Run once, before the ladder: the ladder predicts the re-wrap of exactly the
    widths the writer will emit, so both must see the same scale.
    """
    if metrics is None:
        metrics = get_metrics()
    from .gdocs_metrics import iter_runs
    adv = getattr(lay, "font_advances", None) or {}
    n = 0
    for run in iter_runs(lay):
        k = run_width_scale(run, adv, metrics)
        if k:
            run.width_scale = k
            n += 1
    return n


def shaped_size(run) -> float:
    """The point size a run's text is shaped at, its width scale included.

    Without a scale it is the source size, as the ladder has always used. With
    one, it is what the writer emits -- the half-point size times w:w -- and
    therefore what the renderer draws.
    """
    ws = getattr(run, "width_scale", 0.0) or 0.0
    if ws > 0:
        return (round(run.size * 2) / 2) * ws
    return run.size


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
