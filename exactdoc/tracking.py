"""Source advance scale: text the producer set wider than its font's own advances.

The writer maps every font onto a metric-compatible family (Liberation Serif ->
Times New Roman, Liberation Sans -> Arial) so that the renderer's line breaks
land where the source's did. That bargain assumes the SOURCE used the font's
natural advances. Chromium on Linux does not: with hinting on (the default for
headless print), every glyph advance is rounded on the pixel grid, and the
rounding is biased wide. Measured on the five Chromium expansion fixtures that
carry enough body text, Liberation Serif 11pt is set **6.2-6.6% wider** than
its own advances, line after line -- the interquartile range is under 0.6% --
while the gated `c*` fixtures, printed with hinting off, measure 0.999 on the
same face, and the LibreOffice-produced `x0*` fixtures 0.999 as well.

A renderer given the same text at natural advances fits ~6% more of it on a
line, so a four-line paragraph re-wraps into three and every element below it
drifts up by a line per paragraph. That one effect was the whole of
x08_chrome_print_default's dy_p50 of 27.7pt.

The source's own measurement is the remedy: the extra advance is reproduced as
the run's letter-spacing (`Run.tracking`, which the writer emits as `w:spacing`
on rPr), sized per run from the scale measured for its family and size. The
text stays live and editable; it is simply set at the width the source set it.

The parser measures letter-spacing too, per span, from the gaps between its
glyphs (`parse_pdfium._span_tracking`), and on these documents it finds the
same thing -- 0.291pt against this module's 0.286pt on x07's body. It needs six
gaps in one span, so a fragment too short for that (x07's one- and two-letter
pieces of a word split by a style change, x11's page numbers) goes without.
This module works per face and size over the whole document and fills exactly
those runs. A run the parser COULD measure keeps the parser's answer, zero
included: x17's bold role lines and its first bullet item measure untracked
there, and this module is not the better judge of a run the parser saw.

What this deliberately does NOT do:

  * **Read a justified line as evidence.** Justification stretches inter-word
    space, so a justified line measures wide for a reason that has nothing to
    do with the font. A line flush with its block's widest line does not vote;
    a block's ragged last line still does.
  * **Read a substituted typeface as a bias.** Only source faces that ARE the
    emitted family's metrics vote -- the Liberation/Tinos/Arimo/Cousine clones,
    the Microsoft and Adobe originals, URW's Nimbus. HelveticaNeue mapped to
    Arial, or Palatino to Times New Roman, differ because they are different
    typefaces; that is `fonts.metric_fit`'s problem, and letter-spacing the
    substitute to hide it would be visible.
  * **Read bold or italic as evidence.** The published AFM tables are Adobe's
    Times/Helvetica; their REGULAR advances match the Microsoft faces the
    writer emits (TimesNewRomanPSMT 12pt on y08 measures 0.9998 over 807
    lines), but the bold ones do not (TimesNewRomanPS-BoldMT 12pt: 1.023, with
    no rendering bias present). The scale is measured on the regular face and
    applied to every style of the same family at the same size, which is what
    a pixel-grid bias is a property of.
  * **Narrow anything.** A scale below 1 is not a hinting signature in any
    document measured.
  * **Touch the Google Docs profile.** Docs discards run tracking on import
    (fonts.GDOCS_HONOURS_RUN_TRACKING); the caller skips this there.

Everything is keyed on page evidence -- measured widths against published
metrics -- never on the producer string.
"""
import statistics
from typing import Dict, Tuple

from .fonts import family_keys, map_font
from .layout import DocLayout, Para, TableEl
from .model import DocIR
from .parse_pdfium import TRACK_EMIT_MIN_GAPS

# Source faces whose advances are, by design, the emitted family's.
_CLONES = {
    "liberationserif", "liberationsans", "liberationmono", "tinos", "arimo",
    "cousine", "timesnewroman", "times", "timesroman", "arial", "helvetica",
    "couriernew", "courier", "nimbusroman", "nimbussans", "nimbusmono",
    "nimbusmonops",
}
_EXACT_FAMILIES = ("arial", "times new roman", "courier new")

# A span must carry this many measurable non-space characters to vote. Short
# spans are dominated by one or two glyphs' rounding.
MIN_SPAN_CHARS = 16
# ...and a family/size needs this many voting spans before its scale is
# believed. x17's body (9.7pt) has 12.
MIN_SPANS = 5
# The band a rendering bias lives in. 1.5% is clear of the 0.1% the
# LibreOffice-produced fixtures measure and of the ~1% half-point size
# quantisation the writer already absorbs; 12% is roughly double the largest
# hinting widening measured (6.6%).
SCALE_MIN = 1.015
SCALE_MAX = 1.12
# A bias is uniform. Measured interquartile ranges: the Chromium fixtures
# 0.4-0.6% (x17's mixed résumé lines 2.1%); evidence contaminated by stretched
# lines is far wider (c2_paper2col with every line voting: p10 0.999, p90
# 1.172).
MAX_IQR = 0.025
# A line within this of its block's widest line is treated as possibly
# justified and does not vote (in a ragged block that only drops the widest
# line, which costs nothing).
FLUSH_TOL = 1.5

Key = Tuple[str, float]


def _key(font: str, size: float) -> Key:
    keys = family_keys(font)
    return (keys[-1] if keys else "", round(size, 2))


def _clone(font: str) -> bool:
    return any(k in _CLONES for k in family_keys(font))


def _measurable(text: str) -> bool:
    try:
        text.encode("cp1252")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _family(font: str, mono: bool, serif: bool):
    fam = map_font(font, mono=mono, serif=serif)
    return fam if (fam or "").lower() in _EXACT_FAMILIES else None


def advance_votes(ir: DocIR, metrics) -> Dict[Key, list]:
    """Per family/size, the measured/natural width ratio of each voting span."""
    votes: Dict[Key, list] = {}
    for page in ir.pages:
        for block in page.blocks:
            lines = [ln for ln in block.lines if ln.horizontal and ln.spans]
            if not lines:
                continue
            right = max(ln.bbox[2] for ln in lines)
            for ln in lines:
                if len(lines) >= 2 and ln.bbox[2] >= right - FLUSH_TOL:
                    continue                   # possibly justified: no vote
                for s in ln.spans:
                    if s.bold or s.italic or s.superscript or \
                            not _clone(s.font):
                        continue
                    t = s.text.strip()
                    if len(t.replace(" ", "")) < MIN_SPAN_CHARS or \
                            not _measurable(t):
                        continue
                    fam = _family(s.font, s.mono, s.serif)
                    if fam is None:
                        continue
                    w = metrics.text_width(t, fam, s.size)
                    if not w:
                        continue
                    votes.setdefault(_key(s.font, s.size), []).append(
                        (s.bbox[2] - s.bbox[0]) / w)
    return votes


def measure_advance_scales(ir: DocIR, metrics) -> Dict[Key, float]:
    """{(family, size): scale} for faces the source set measurably wide."""
    scales = {}
    for k, v in advance_votes(ir, metrics).items():
        if len(v) < MIN_SPANS:
            continue
        v = sorted(v)
        q1, q3 = v[len(v) // 4], v[(3 * len(v)) // 4]
        if q3 - q1 > MAX_IQR:
            continue
        med = statistics.median(v)
        if SCALE_MIN <= med <= SCALE_MAX:
            scales[k] = med
    return scales


def _runs(lay: DocLayout):
    for part in (lay.header_default, lay.header_first, lay.footer_default,
                 lay.footer_first):
        if part is not None:
            for el in part.elements:
                yield from _el_runs(el)
    if lay.cover_band is not None:
        yield from _el_runs(lay.cover_band)
    for pg in lay.pages:
        for ch in pg.chunks:
            for el in ch.elements:
                yield from _el_runs(el)


def _el_runs(el):
    if isinstance(el, Para):
        yield from el.runs
        for row in getattr(el, "gdocs_rows", ()) or ():
            yield from row
    elif isinstance(el, TableEl):
        for row in el.rows:
            for cell in row:
                if cell is not None:
                    for p in cell.paras:
                        yield from _el_runs(p)


def _glyph_gaps(text: str) -> int:
    """Gaps between adjacent glyphs of one word, summed over the words."""
    return sum(max(0, len(w) - 1) for w in text.split())


def apply_advance_tracking(lay: DocLayout, scales: Dict[Key, float],
                           metrics) -> int:
    """Give every run of a widened face the tracking that restores its width.

    Per run, not per face: the extra advance is proportional to the glyphs
    actually in the run, so it is sized from the run's own natural width. A run
    whose text the base-14 tables cannot see (Cyrillic in a Latin face) takes
    the per-glyph average of the characters that can be measured. Returns the
    number of runs changed.

    Only the BIAS is restored here. The half-point quantisation of the size
    (x17's 9.7pt body is written at 9.5pt, 2.1% narrow) is
    `metrics.apply_width_scale`'s, which states it as the run's w:w; the w:w
    brings the glyphs back to the font's natural width at the source size, and
    this tracking adds the source's own extra advance on top. The ladder sees
    both (`metrics.shaped_size` plus `Run.tracking`).

    A run the parser could measure is skipped (see the module docstring):
    the same extra advance, restored twice, would set it 6% too wide.
    """
    if not scales:
        return 0
    n = 0
    seen = set()
    for r in _runs(lay):
        if id(r) in seen or r.is_tab or r.field or not r.text or r.tracking:
            continue
        seen.add(id(r))
        if _glyph_gaps(r.text) >= TRACK_EMIT_MIN_GAPS:
            continue                    # the parser measured it: its answer
        sc = scales.get(_key(r.font, r.size))
        if sc is None:
            continue
        fam = _family(r.font, r.mono, r.serif)
        if fam is None:
            continue
        meas = "".join(c for c in r.text if c != "\n" and _measurable(c))
        if not meas:
            continue
        w = metrics.text_width(meas, fam, r.size, bold=r.bold, italic=r.italic)
        if not w:
            continue
        r.tracking = round((sc - 1.0) * w / len(meas), 3)
        n += 1
    return n
