"""DocLayout -> .docx writer (Google Docs-safe vocabulary).

Constructs used: styled paragraphs, fixed-layout tables with per-side borders
and cell shading, section geometry + true column sections, inline images,
headers/footers with PAGE/NUMPAGES fields, hyperlinks, tab stops.
No floating text boxes, no embedded fonts, no VML.
"""
import copy
import dataclasses
import io
import math
import re
from typing import Any, Callable, Dict, Optional, List

from docx import Document
from docx.shared import Pt, Emu, RGBColor, Twips
from docx.enum.text import (WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT,
                            WD_TAB_LEADER, WD_BREAK)
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.table import _Cell
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT

from .layout import (DocLayout, Para, Run, Cell, TableEl, FigureEl, ImageEl,
                     RuleEl, ColBreak, HFPart, Chunk, PageLayout)
from .fonts import east_asian_family, font_table_desc, map_font
from .metrics import source_line_width
from .structures import (add_footnote_ref_mark, add_footnote_reference,
                         apply_numpr, level_carries_indent, num_tab_override,
                         strip_marker)


@dataclasses.dataclass(frozen=True)
class WriteCtx:
    """Everything a write needs to know that is not in the DocLayout.

    This replaces a module global. `LINE_MODE` was set by `write_docx` and
    restored in a `finally`, so two conversions running concurrently with
    different targets could each observe the other's line-height encoding --
    silently, and only in the overlap. A frozen object passed down the call tree
    cannot do that.

    `render_clip(page_no, clip, dpi) -> png bytes | None` is how a figure region
    reaches the writer. It used to be an open MuPDF document handed down five
    call levels, which is what put `import fitz` at the top of this module and
    made a wheel without PyMuPDF fail while *importing the writer* -- before any
    backend selection could happen.
    """

    line_mode: str = "exact"
    dpi: int = 240
    render_clip: Optional[Callable] = None
    # Keep the output profile as an explicit writer concern.  `line_mode` is
    # intentionally a lossy rendering choice (another profile may choose the
    # same encoding), while a handful of Google Docs workarounds really are
    # profile-specific.  It comes last to preserve the old positional shape.
    output_profile: str = "standard"
    # Internal-link plumbing, filled in by _write_docx once it has planned the
    # bookmarks. Appended after output_profile so the positional shape above is
    # still the old one. {LinkDest: anchor name} and {anchor name: w:id}.
    dest_anchors: Dict[Any, str] = dataclasses.field(default_factory=dict)
    anchor_ids: Dict[str, int] = dataclasses.field(default_factory=dict)
    #: Optional mutable tally of what happened to each extracted raster:
    #: ``{"embedded": n, "reencoded": n, "dropped": n}``.  A degradation nobody
    #: can observe is indistinguishable from a lie, and dropping an image is a
    #: degradation.  Defaults to None -- the writer keeps no global ledger, so
    #: two concurrent conversions cannot accumulate into each other's counts.
    image_report: Optional[dict] = None
    # Real-structure plumbing, filled in by _write_docx: {list_id: ListDef}
    # for the lists written as w:numPr, and {fid: (w:id, custom_mark)} for
    # the footnotes written as notes. Empty means "write the typed form".
    list_defs: Dict[int, Any] = dataclasses.field(default_factory=dict)
    num_base: int = 1                # w:numId of list_id 0 (structures.numbering_base)
    note_ids: Dict[int, Any] = dataclasses.field(default_factory=dict)
    # Set while a footnote's own paragraphs are written: False for a note the
    # renderer numbers (its mark run becomes w:footnoteRef), True for a note
    # that keeps the source's custom mark. None in the body.
    note_mark_custom: Optional[bool] = None
    # Set when a write found a reference missing and fell back to typed notes
    # (see the check before write_footnotes in _write_docx).
    notes_vetoed: bool = False

    @property
    def numbering(self) -> bool:
        """Does this profile write lists as real numbering? (options.py)"""
        from .options import capabilities
        return "numbering" in capabilities(self.output_profile)

    @property
    def footnotes(self) -> bool:
        """Does this profile write footnotes as real notes? (options.py)"""
        from .options import capabilities
        return "footnotes" in capabilities(self.output_profile)


_DEFAULT_CTX = WriteCtx()

ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
TABAL = {"left": WD_TAB_ALIGNMENT.LEFT, "center": WD_TAB_ALIGNMENT.CENTER,
         "right": WD_TAB_ALIGNMENT.RIGHT}
# A tab stop is (position, alignment) or (position, alignment, leader); the
# leader is how a contents line's dots are drawn by the word processor itself.
TABLEADER = {"dot": WD_TAB_LEADER.DOTS, "hyphen": WD_TAB_LEADER.DASHES,
             "underscore": WD_TAB_LEADER.LINES}


def _shift_tabs(stops, dl: float):
    """Tab stops moved by `dl`, keeping any leader."""
    return [(round(ts[0] + dl, 1),) + tuple(ts[1:]) for ts in stops]


def _hex(c: str) -> str:
    return (c or "#000000").lstrip("#").upper()


def _set_borders(el_pr, borders: dict, tag: str):
    """Apply border dict to tcPr/pPr. tag='w:tcBorders' or 'w:pBdr'."""
    bel = OxmlElement(tag)
    order = ("top", "left", "bottom", "right")
    for side in order:
        spec = borders.get(side)
        b = OxmlElement("w:" + side)
        if spec:
            w, color = spec[0], spec[1]
            b.set(qn("w:val"), "single")
            b.set(qn("w:sz"), str(max(2, int(round(w * 8)))))
            b.set(qn("w:space"), str(int(spec[2])) if len(spec) > 2 else "0")
            b.set(qn("w:color"), _hex(color))
        else:
            b.set(qn("w:val"), "nil")
        bel.append(b)
    el_pr.append(bel)


def _style_run(r, run: Run, profile: str = "standard"):
    f = r.font
    fam = map_font(run.font, mono=run.mono, serif=run.serif, profile=profile)
    f.name = fam
    rpr = r._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(attr), fam)
    # A CJK run names its own face in the East Asian slot (fonts.east_asian_family
    # has the measurement); every other run keeps the Latin family in all four.
    ea = east_asian_family(run.font, run.text, profile)
    if ea:
        rf.set(qn("w:eastAsia"), ea)
    f.size = Pt(round(run.size * 2) / 2)
    f.bold = run.bold
    f.italic = run.italic
    if run.underline:
        f.underline = True
    if run.superscript:
        va = OxmlElement("w:vertAlign")
        va.set(qn("w:val"), "superscript")
        rpr.append(va)
    spacing = getattr(run, "char_spacing", 0.0) + getattr(run, "tracking", 0.0)
    if abs(spacing) > 0.004:
        # w:spacing on rPr is character tracking, in twentieths of a point
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:val"), str(int(round(spacing * 20))))
        rpr.append(sp)
    ws = getattr(run, "width_scale", 0.0) or 0.0
    if ws > 0 and abs(ws - 1.0) > 0.004 and profile == "standard":
        # Horizontal scale, an integer percent, so the run draws at its source
        # width (metrics.run_width_scale). Schema order puts w:w before w:sz.
        wel = OxmlElement("w:w")
        wel.set(qn("w:val"), str(int(round(ws * 100))))
        sz = rpr.find(qn("w:sz"))
        if sz is not None:
            sz.addprevious(wel)
        else:
            rpr.append(wel)
    try:
        f.color.rgb = RGBColor.from_string(_hex(run.color))
    except Exception:
        pass


def _add_field(par, instr: str, sample: str, style_from: Run,
               profile: str = "standard"):
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), " %s " % instr)
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = sample
    r.append(t)
    fld.append(r)
    par._p.append(fld)
    # style the inner run
    from docx.text.run import Run as DRun
    dr = DRun(r, par)
    _style_run(dr, style_from, profile)


def _add_hyperlink(par, url: str, runs_and_styles, profile: str = "standard"):
    part = par.part
    r_id = part.relate_to(url, RT.HYPERLINK, is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), r_id)
    par._p.append(h)
    from docx.text.run import Run as DRun
    for text, style in runs_and_styles:
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = text
        r.append(t)
        h.append(r)
        _style_run(DRun(r, par), style, profile)


def _add_internal_hyperlink(par, anchor: str, runs_and_styles,
                            profile: str = "standard"):
    """A link to a bookmark in this document: w:hyperlink w:anchor.

    Deliberately built the same way as _add_hyperlink rather than through
    python-docx's helper, and deliberately WITHOUT a w:rStyle: the Hyperlink
    character style would repaint the text blue and underline it, and the source
    span already carries the styling the producer chose. c8_toc_links sets its
    table of contents in #123a5e with `text-decoration: none`, so borrowing
    Word's link styling would visibly recolour text that is not blue in the PDF.
    _style_run applies the run's own formatting, exactly as for external links.
    """
    h = OxmlElement("w:hyperlink")
    h.set(qn("w:anchor"), anchor)
    par._p.append(h)
    from docx.text.run import Run as DRun
    for text, style in runs_and_styles:
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = text
        r.append(t)
        h.append(r)
        _style_run(DRun(r, par), style, profile)


def _bookmark_pair(name: str, bid: int):
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bid))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bid))
    return start, end


def _wrap_paragraph_bookmark(par, name: str, bid: int):
    """Bracket a paragraph's content with a bookmark, inside the w:p.

    bookmarkStart has to follow w:pPr -- pPr must be the first child of w:p --
    so this inserts after it rather than at index 0.
    """
    start, end = _bookmark_pair(name, bid)
    p = par._p
    ppr = p.find(qn("w:pPr"))
    p.insert(list(p).index(ppr) + 1 if ppr is not None else 0, start)
    p.append(end)


def _add_block_bookmark(container, name: str, bid: int):
    """A zero-height bookmark between block elements.

    Used when a destination resolves to a table, figure, image or rule rather
    than a paragraph. bookmarkStart/End are range markers and are legal as
    direct children of w:body, so this costs no paragraph and therefore no
    vertical space -- which is the whole reason internal links can be added
    without moving a single measured number.
    """
    start, end = _bookmark_pair(name, bid)
    container.element.body.append(start)
    container.element.body.append(end)


def _el_extent(el):
    """(top, bottom) of a flow element in source page points, or None."""
    if isinstance(el, Para):
        bb = el.bbox
    elif isinstance(el, TableEl):
        bb = el.bbox
    elif isinstance(el, FigureEl):
        bb = el.clip
    else:
        bb = getattr(el, "_bbox", None)
    return (bb[1], bb[3]) if bb else None


def _iter_runs(el):
    if isinstance(el, Para):
        for r in el.runs:
            yield r
        for row in getattr(el, "gdocs_rows", None) or []:
            for r in row:
                yield r
    elif isinstance(el, TableEl):
        for row in el.rows:
            for cell in row:
                if not cell:
                    continue
                for p in cell.paras:
                    for r in p.runs:
                        yield r


def _anchor_name(dest) -> str:
    """Deterministic, collision-free, and a legal Word bookmark name.

    Word bookmark names must begin with a letter and may contain only letters,
    digits and underscores. Two destinations that resolve to the same point get
    the same name on purpose -- they are the same anchor -- and the hundredths
    of a point keep two genuinely different points apart.
    """
    return "exactdoc_dest_p%d_%d" % (int(dest.page), int(round(dest.y * 100)))


def _plan_bookmarks(lay: DocLayout):
    """Resolve every referenced destination to a flow element and name it.

    THE ANCHORING RULE, in order:

      1. the element whose vertical extent CONTAINS the destination y;
      2. otherwise the element whose top edge is nearest at-or-below it;
      3. otherwise (the destination sits below all content) the last element.

    Ties are broken by flow order, earliest first, so the result does not
    depend on dictionary or sort stability.

    Step 1 is not decoration. A /XYZ destination names the point that should
    come to the top of the window, and producers put it at the target's top
    edge -- which lands a hair INSIDE the element once font ascent is taken into
    account, not above it. Measured on a ReportLab file whose destination is the
    baseline of the text it names, "nearest at-or-below" alone skipped that text
    and anchored to the following paragraph; containment gets it right.

    Anchoring is by y only. A destination's x is recorded in the IR but says
    nothing about which paragraph is meant -- /XYZ's `left` is a horizontal
    scroll position, and on this corpus it is 0 for every destination.
    """
    wanted = set()
    for pg in lay.pages:
        for ch in pg.chunks:
            for el in ch.elements:
                for run in _iter_runs(el):
                    if run.dest is not None:
                        wanted.add(run.dest)
    if not wanted:
        return {}, {}

    per_page = {}
    for pi, pg in enumerate(lay.pages):
        seq = []
        for ch in pg.chunks:
            for el in ch.elements:
                ext = _el_extent(el)
                if ext is not None:
                    seq.append((ext[0], ext[1], el))
        per_page[pi] = seq

    dest_anchors, targets, named_element = {}, {}, {}
    for dest in sorted(wanted, key=lambda d: (d.page, d.y, d.x)):
        seq = per_page.get(int(dest.page)) or []
        if not seq:
            continue
        hit = next((el for top, bot, el in seq if top <= dest.y <= bot), None)
        if hit is None:
            below = [(top, el) for top, _, el in seq if top >= dest.y]
            hit = min(below, key=lambda t: t[0])[1] if below else seq[-1][2]
        # ONE bookmark per element, whatever the destination was called. Two
        # destinations a few points apart routinely land on the same paragraph;
        # minting a name each would leave the element carrying only the last of
        # them, and every other anchor pointing at a bookmark never written.
        name = named_element.get(id(hit))
        if name is None:
            name = _anchor_name(dest)
            named_element[id(hit)] = name
            targets[name] = hit
        dest_anchors[dest] = name

    anchor_ids = {name: i + 1 for i, name in enumerate(sorted(targets))}
    for name, el in targets.items():
        el._bookmark = name
    return dest_anchors, anchor_ids


# Half-point wrap correction: implemented and measured, OFF by default.
#
# It works -- line-break agreement on the WeasyPrint sample goes 0.599 -> 0.796,
# and a parameter sweep puts the optimum narrowing at ~1%, exactly the
# 10.0/10.1 size ratio. But restoring the correct line breaks makes paragraphs
# their correct (taller) height, and the writer currently has no way to keep a
# page from overflowing, so that sample goes 10 -> 11 pages and word placement
# drops 0.985 -> 0.706. Net regression, so it stays off.
#
# Turning it on is blocked on overflow control (the closed-loop second pass):
# render, find pages that spilled, shrink discretionary space, re-emit. Enable
# both together, never this alone.
WRAP_CORRECTION = False


# --- line-height encoding, per render target ------------------------------
# Word and LibreOffice honour w:spacing lineRule="exact" literally, and the
# whole fidelity model (THEORY 3.1) is built on it: paragraph height is
# n_lines x leading, exactly.
#
# Google Docs has no "exact" line spacing in its own document model -- only
# multiples -- so its importer must translate, and the translation is wrong in
# a way that scales with font size. Measured (testkit/docs_quirks.py, three
# lines per probe, error vs LibreOffice):
#
#     size/leading      exact      atLeast    multiple
#     10pt / 12.0pt     -2.0pt     -2.0pt     --
#     18pt / 21.0pt    +45.2pt     -1.4pt     -0.3pt
#     22pt / 25.5pt    +84.3pt     -1.1pt     -0.6pt
#
# So a heading with exact leading gains ~28pt in Docs, which is precisely the
# "+28pt after the first heading" that the closed loop had been compensating
# per document. Emitting the same intent as a multiple makes it a static fix.
#
# Natural line height as a fraction of font size, per family, measured in
# Google Docs (testkit/docs_quirks.py h5: four bare 20pt lines, no spacing
# properties; factor = rendered_gap / (4 x 20)). The gdocs translation divides
# by this, so a single constant silently drifts on any document set in a font
# whose metric differs -- Roboto is 4% taller than Arial, which is exactly the
# kind of quiet assumption this project exists to avoid.
NATURAL_FACTORS = {
    # Re-measured live 2026-10-04 (see the Calibri note below for the method):
    # every family here equals its font file's own hhea line, with no offset.
    # The "0.006 below the formula" the older values carried was the bias of
    # the original four-line probe; at 9-16 lines and two sizes the pitch
    # agrees with the formula to four decimals.
    #
    # Arial and Times New Roman measure 1.150 too, and are deliberately left
    # at 1.144: the gdocs profile's other levers (the single-line -0.38pt in
    # write_para among them) were calibrated live against 1.144, and setting
    # the true factor alone moved the gated corpus both ways (pass 12:
    # within-2pt sum 4.29 -> 5.05, 02 0.09 -> 0.59, c2 0.86 -> 0.91, but 01's
    # mean SSIM 0.704 -> 0.680 broke its policy bound, and c6 0.34 -> 0.20).
    # Correcting them needs those levers re-measured with it, in one change.
    "arial": 1.144, "times new roman": 1.144, "courier new": 1.133,
    "georgia": 1.1365, "roboto": 1.200,
    # Added when the metric fit began substituting these families. Docs' live
    # pass 2 rendered l1_word_native in Noto Serif at a 17.48pt pitch where the
    # source used 14.70pt: dividing by the 1.144 default inflated every line by
    # 19%, which is the whole of that document's remaining dy. Deriving the
    # factor back out of that export gives 1.144 * 17.48 / 14.70 = 1.360.
    #
    # The font files agree and explain the whole table. With
    #     (hhea.ascender - hhea.descender + hhea.lineGap) / unitsPerEm
    # Arial reads 1.150, Times New Roman 1.150, Courier New 1.133 and Georgia
    # 1.136 -- each exactly 0.006 above its Docs-measured value here, a constant
    # offset across four independently probed families. Noto Serif reads 1.362
    # by the same formula, so 1.356 predicted against 1.360 observed.
    "noto serif": 1.362, "noto sans": 1.362, "verdana": 1.2155,
    # Vollkorn, measured live the Libre Baskerville way: Docs renders the
    # family natively (verified -- a self-mapped document's wraps came back
    # at the source's own line breaks), but its line box is far taller than
    # the 1.144 default. Emitted 1.2458x at 11pt predicted 15.68pt; Docs'
    # own export rendered 19.10pt (median over 30 consecutive body-line
    # gaps, y20 page 3) -- a natural factor of 1.392. With the default, the
    # document's lines rendered 22% tall and it went 5 pages to 7.
    "vollkorn": 1.393,
    # Consolas, read from the font file by the formula above (hhea
    # 1521/-527/350 over upm 2048 = 1.1709) minus the constant 0.006
    # offset the four probed families showed between that formula and
    # Docs' own pitch. No live probe has confirmed it yet; a
    # probe_font_metrics ride-along is the way to tighten it.
    "consolas": 1.171,
    # Also measured inside Docs rather than from a font file, by
    # testkit/probe_font_metrics.py in live pass 3 -- the family is not
    # installed here. The probe's own controls recovered Noto Serif at 1.362,
    # Times New Roman at 1.150 and Georgia at 1.136 against the 1.360/1.144/
    # 1.130 in this table, so a pitch read this way is good to about 0.006.
    "libre baskerville": 1.240,
    # Calibri and its metric clone Carlito -- the most common family in Word
    # documents -- were missing, so they took the 1.144 default and every line
    # rendered 6.7% tall in Docs (y30 drifted ~1 line per page and spilled).
    # Measured live 2026-10-04: one paragraph per page at 11pt and 9pt, single
    # spacing, pitch = (last - first baseline) / (lines - 1) over 9-12 lines,
    # consistent to four decimals across sizes. The same probe recovered Arial,
    # Times New Roman and Caladea at 1.1500 and Cambria at 1.1724 -- each the
    # font file's own hhea line, with no offset.
    "carlito": 1.221, "calibri": 1.221, "cambria": 1.172, "caladea": 1.150,
}
NATURAL_DEFAULT = 1.144
# The two encodings. Which one is used is a per-write decision carried in
# WriteCtx.line_mode, not a module global -- see WriteCtx.
LINE_MODES = ("exact", "multiple")


def line_mode_for(output_profile: str) -> str:
    """Word and LibreOffice honour lineRule="exact"; Google Docs mistranslates it.

    Keyed on the OUTPUT PROFILE, not on which renderer the refinement loop talks
    to. Those were one field, so "write OOXML that survives Google Docs" was
    inseparable from "upload this document to Google" -- and the offline
    Docs-safe profile, which is what this project intends to ship, could not be
    expressed at all.
    """
    return "multiple" if output_profile == "gdocs" else "exact"

# Floor on compressing a table row's leading to make it fit its source height.
# Below this the text starts to collide with its neighbours, and an honestly
# too-tall row beats an unreadable one.
MIN_ROW_SHRINK = 0.55

# The Google Docs importer rounds every table row box UP to a whole point;
# on the measured 59-row table that rounding alone was +1.27pt/row and the
# rows spilled their pages. The gdocs row target is therefore
# floor(source height) minus this safety -- the rounded-up content can no
# longer exceed the source row. (The paragraph-mark rPr is inert in Docs:
# ceil of the no-mark model reproduced the observed heights exactly; the
# mark is still styled because it is correct for Word.)
GDOCS_ROW_SAFETY_PT = 0.75

# A continuous section break is carried by a real paragraph, and that paragraph
# occupies flow height the source page never spent. The "crush" further down
# used to be described as making it consume none; it does not.
#
# Measured on c2_paper2col through the canonical LibreOffice by putting marker
# text in the paragraph and reading the render back: its advance is exactly its
# w:line, with a floor near 1pt. Raising w:line from 20 twips to 400 moved every
# following line down by 19.00pt -- exactly the 19pt added -- so the height is
# honoured, and 1pt is the least it can be made to cost. Dropping it to 1 twip
# changed nothing, which is the floor showing. Folding the sectPr into the
# preceding paragraph instead does NOT work: that collapses the paragraph's own
# exact height, which cost 13.7pt on c2.
#
# So it cannot be removed, only accounted for -- the gap hoisted ahead of the
# break is emitted that much shorter.
SECT_BREAK_PARA_TWIPS = 20
SECT_BREAK_PARA_PT = SECT_BREAK_PARA_TWIPS / 20.0


def _sect_break_comp(ctx) -> float:
    """How much of the section-break paragraph's height to pre-subtract.

    Deliberately gdocs-only, and scoped by output profile rather than by
    whether the correction loop runs.

    The standard profile ships with the LibreOffice loop (refine3), and that
    loop has already absorbed this 1pt empirically: correcting it at source as
    well makes the loop over-correct, and it was measured doing so --
    c2's product-lane mean_ssim fell 0.824 -> 0.793 and its dy_p50 went
    0.85 -> 1.75. The recorded 0.85 encodes the loop cancelling this bug, and
    unbundling that is not worth a shipping regression.

    The gdocs profile ships with no loop at all (refine0) and exists precisely
    as the static-translation layer for corrections a loop cannot supply there,
    so this is exactly the kind of correction it is for. Scoping on the output
    profile rather than on refine_rounds also leaves the raw gate lane alone --
    raw runs the standard profile open-loop -- so neither gate lane moves.
    """
    return SECT_BREAK_PARA_PT if getattr(ctx, "output_profile", "") == "gdocs" \
        else 0.0


def _natural_factor(family: str) -> float:
    return NATURAL_FACTORS.get((family or "").lower(), NATURAL_DEFAULT)


def _apply_leading(pf, leading: float, size: float, mode: str = "exact",
                   family: str = ""):
    """Encode a line height the way the chosen target actually honours."""
    if mode == "multiple" and size and size > 0.5 and leading > 1.0:
        natural = size * _natural_factor(family)
        pf.line_spacing = max(0.06, leading / natural)   # w:line as a multiple
        return
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(round(leading, 1))


def _quantised_size(sz: float) -> float:
    """OOXML stores font size in half-points (w:sz is in half-points, integer)."""
    return round(sz * 2) / 2


def _wrap_correction(p: Para, content_w: float) -> float:
    """Extra right indent that cancels the half-point font quantisation.

    A 10.1pt source font can only be emitted at 10.0 or 10.5. At 10.0 the
    glyphs are 1% narrow, so ~1% more text fits per line and the paragraph
    re-wraps; at 9.5 (from 9.7) they are 2% narrow the other way. Either way
    the line breaks move, and every paragraph below shifts.

    Line breaking is scale-invariant: shrink every advance by k and the same
    breaks return if the wrap width also shrinks by k. So narrow the column by
    (1 - emitted/source). This is exact for a uniform-size paragraph and a good
    approximation for mixed runs, where the dominant size is used.

    Only applied where it can help and cannot hurt: the paragraph must actually
    wrap (a single-line paragraph has no breaks to preserve) and must be
    left/justified (on centred or right-aligned text a right indent *moves* the
    text instead of only changing where it wraps).
    """
    if not WRAP_CORRECTION:
        return 0.0
    if p.align not in ("left", "justify") or not p.runs:
        return 0.0
    weight = {}
    for r in p.runs:
        if r.text and not r.is_tab:
            weight[r.size] = weight.get(r.size, 0) + len(r.text)
    if not weight:
        return 0.0
    src = max(weight, key=weight.get)
    if src < 1.0:
        return 0.0
    k = _quantised_size(src) / src
    if abs(k - 1.0) < 1e-6:
        return 0.0
    wrap_w = max(1.0, content_w - p.left_indent - p.right_indent)
    # a paragraph that fits on one line has no wrap to preserve
    if p.bbox is not None and (p.bbox[2] - p.bbox[0]) < 0.92 * wrap_w and \
            not p.line_breaks:
        est_lines = sum(len(r.text) for r in p.runs) * 0.5 * src / max(1.0, wrap_w)
        if est_lines < 1.2:
            return 0.0
    return wrap_w * (1.0 - k)


def _page_break_carrier(doc):
    """The 1pt page-break carrier paragraph (standard-profile page seams)."""
    par = doc.add_paragraph()
    pf = par.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(1)
    par.add_run().add_break(WD_BREAK.PAGE)
    return par


# CT_PPrBase's sequence after w:suppressAutoHyphens (ECMA-376 Part 1, 17.3.1.26).
_PPR_AFTER_SUPPRESS_HYPHENS = (
    "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE",
    "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind",
    "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
    "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl",
    "divId", "cnfStyle", "rPr", "sectPr", "pPrChange")


# Google Docs draws no tab leaders: x02's contents page lost every one of its
# 1,277 dots while the right tab still placed the page numbers. Typed dots
# render, so under that profile a contents line carries the source's own dots,
# two short, before a plain right tab that absorbs whatever they leave. Live,
# 2026-10-04: all nine x02 entries kept one line, numbers at the source edge.
_GDOCS_LEADER_SLACK = 2


def _gdocs_typed_leader(p: Para) -> Para:
    """`p` with its dot-leader tab drawn as typed dots (a copy; see above)."""
    if not p.leader_text:
        return p
    i = next((k for k, r in enumerate(p.runs) if r.is_tab), None)
    if i is None:
        return p
    keep = max(0, len(p.leader_text) - _GDOCS_LEADER_SLACK)
    dots = dataclasses.replace(p.runs[i], text=p.leader_text[:keep], is_tab=False)
    stops = [tuple(ts[:2]) if len(ts) > 2 and ts[2] == "dot" else ts
             for ts in p.tab_stops]
    return dataclasses.replace(p, runs=p.runs[:i] + [dots] + p.runs[i:],
                               tab_stops=stops)


def write_para(container, p: Para, content_w: float, par=None, ctx=None,
               space_before: Optional[float] = None,
               page_break_before: bool = False):
    """Write a Para into container (doc/cell/header). Returns the paragraph.

    `space_before` overrides the paragraph's own gap for this write only. It is
    how `_absorb_page_spill` spends a page's slack without touching the layout
    -- see the note below on why nothing here may be mutated.
    """
    ctx = ctx or _DEFAULT_CTX
    if ctx.output_profile == "gdocs":
        p = _gdocs_typed_leader(p)
    if par is None:
        par = container.add_paragraph()
    if page_break_before:
        par.paragraph_format.page_break_before = True
    # NB: local, not `p.right_indent +=`. The refine loop writes the same
    # layout more than once, and mutating it here would compound the
    # correction on every pass.
    gdocs_rows = p.gdocs_rows if ctx.output_profile == "gdocs" else []
    # A real list item: the level draws the marker, so the typed marker and
    # its separator leave the runs (structures.py). `ctx.list_defs` holds only
    # the lists whose every item strips cleanly (structures.numbering_plan).
    num, num_runs, lvl = None, None, None
    if p.numbering is not None and p.numbering.list_id in ctx.list_defs \
            and not gdocs_rows:
        num_runs = strip_marker(p.runs, p.numbering)
        if num_runs is not None:
            num = p.numbering
            lvl = ctx.list_defs[num.list_id].levels.get(num.level)
    ind_from_level = lvl is not None and level_carries_indent(p, lvl)
    right_indent = 0.0 if gdocs_rows else p.right_indent + _wrap_correction(p, content_w)
    pf = par.paragraph_format
    par.alignment = ALIGN.get("left" if gdocs_rows else p.align, WD_ALIGN_PARAGRAPH.LEFT)
    gap = p.space_before if space_before is None else space_before
    if gap > 0.05:
        pf.space_before = Pt(round(gap, 1))
    else:
        pf.space_before = Pt(0)
    pf.space_after = Pt(round(max(0.0, p.space_after), 1))
    if p.leading and p.leading > 1:
        dom, fam = 0.0, ""
        if p.runs:
            w = {}
            for r in p.runs:
                if r.text and not r.is_tab:
                    key = (r.size, map_font(r.font, mono=r.mono, serif=r.serif,
                                            profile=ctx.output_profile))
                    w[key] = w.get(key, 0) + len(r.text)
            if w:
                dom, fam = max(w, key=w.get)
        lead = p.leading
        # Hand-campaign lever [E], single-line half, gdocs profile only:
        # list items and other one-line paragraphs pitch ~0.38pt/line looser
        # in Docs than the source measured (47-line list block, +18pt on
        # one page). A single line's `leading` is the size*1.16 heuristic,
        # not a measured baseline delta, so shaving it is a correction of
        # an estimate, not of a measurement. Multi-line paragraphs keep
        # their measured pitch untouched.
        if ctx.output_profile == "gdocs" and (p.src_lines or 1) == 1 \
                and not p.line_breaks and lead > 0:
            lead = max(dom * 1.0 if dom else 4.0, lead - 0.38)
        _apply_leading(pf, lead, dom, mode=ctx.line_mode, family=fam)
    if num is not None and not ind_from_level:
        # A numbered paragraph inherits its level's indents unless it says
        # otherwise, so a paragraph that differs must say so -- zeros included.
        pf.left_indent = Pt(round(p.left_indent, 1))
        pf.first_line_indent = Pt(round(p.first_indent, 1))
    elif num is None:
        if p.left_indent > 0.05:
            pf.left_indent = Pt(round(p.left_indent, 1))
        if abs(p.first_indent) > 0.05:
            pf.first_line_indent = Pt(round(p.first_indent, 1))
    if right_indent > 0.05:
        pf.right_indent = Pt(round(right_indent, 1))
    for ts in p.tab_stops:
        pos, al = ts[0], ts[1]
        if lvl is not None and lvl.sep == "tab" and al == "left" and                 abs(pos - p.left_indent) < 0.05:
            continue                # the item's own text stop: see below
        leader = TABLEADER.get(ts[2]) if len(ts) > 2 else None
        if leader is None:
            pf.tab_stops.add_tab_stop(Pt(round(pos, 1)),
                                      TABAL.get(al, WD_TAB_ALIGNMENT.LEFT))
        else:
            pf.tab_stops.add_tab_stop(Pt(round(pos, 1)),
                                      TABAL.get(al, WD_TAB_ALIGNMENT.LEFT), leader)
    if num is not None:
        apply_numpr(par, num, ctx.num_base)
        if not ind_from_level and lvl is not None and lvl.sep == "tab":
            # The level's num tab is a tab stop the paragraph inherits, and the
            # marker's tab goes to the first stop past it, so an item whose
            # text sits off its level's stop must move the stop with its
            # indent -- the way Word itself writes a re-indented list item.
            # LibreOffice ignores the override and always uses the level's
            # stop (y28 p36: text at 38.7pt landed at 36.0), which is why
            # `lists._accepts` keeps such an item out of the level; this
            # covers the sub-0.5pt remainder for Word.
            num_tab_override(par, lvl.left, p.left_indent)
    # keep heading with following content
    if p.heading:
        pf.keep_with_next = True
        # Name the style, not just the outline level. `w:outlineLvl` is what
        # Word's navigation pane reads; Google Docs' outline sidebar and its
        # style dropdown key on the paragraph STYLE, and a converted document
        # that carried only outlineLvl showed "Normal text" for every heading
        # and an empty outline. The named stock styles are stripped to pure
        # metadata by `_restyle_outline_styles`, so everything visual still
        # comes from the direct formatting below and nothing moves. Assigned
        # by name so the paragraph resolves it against its own document part.
        try:
            par.style = "Heading %d" % min(6, p.heading)
        except KeyError:
            pass
        ppr = par._p.get_or_add_pPr()
        lvl = OxmlElement("w:outlineLvl")
        lvl.set(qn("w:val"), str(min(8, p.heading - 1)))
        ppr.append(lvl)
    # paragraph borders from header/footer rules
    bt = getattr(p, "border_top", None)
    bb = getattr(p, "border_bottom", None)
    if bt or bb:
        ppr = par._p.get_or_add_pPr()
        bd = {}
        if bt:
            bd["top"] = bt
        if bb:
            bd["bottom"] = bb
        _set_borders(ppr, bd, "w:pBdr")
    if getattr(p, "no_hyphenation", False):
        # Set only in a document that auto-hyphenates; see
        # hyphen.mark_unhyphenated for which paragraphs opt out and why.
        ppr = par._p.get_or_add_pPr()
        if ppr.find(qn("w:suppressAutoHyphens")) is None:
            ppr.insert_element_before(
                OxmlElement("w:suppressAutoHyphens"),
                *("w:" + t for t in _PPR_AFTER_SUPPRESS_HYPHENS))

    i = 0
    if gdocs_rows:
        runs = []
        for row_i, row in enumerate(gdocs_rows):
            runs.extend(row)
            if row_i < len(gdocs_rows) - 1:
                style = row[0] if row else Run(text="", font="Helvetica", size=10,
                                               color="#000000")
                runs.append(Run(text="\n", font=style.font, size=style.size,
                                color=style.color, bold=style.bold, italic=style.italic,
                                mono=style.mono, serif=style.serif))
    else:
        runs = num_runs if num is not None else p.runs
    while i < len(runs):
        run = runs[i]
        if run.footnote is not None and run.footnote in ctx.note_ids:
            wid, custom = ctx.note_ids[run.footnote]
            add_footnote_reference(
                par, run, wid, custom,
                lambda r, src: _style_run(r, src, ctx.output_profile))
            i += 1
            continue
        if run.footnote_mark and ctx.note_mark_custom is not None:
            add_footnote_ref_mark(
                par, run, ctx.note_mark_custom,
                lambda r, src: _style_run(r, src, ctx.output_profile))
            i += 1
            continue
        # A link group ends at a footnote reference: EUR-Lex links "(¹)" to
        # its note, and a reference swallowed into the hyperlink was written
        # as plain text -- 30 of its 58 notes lost their anchors.
        def _grouped(k, key):
            return k < len(runs) and key(runs[k]) and not (
                runs[k].footnote is not None and runs[k].footnote in ctx.note_ids)
        if run.link:
            grp = []
            while _grouped(i, lambda r: r.link == run.link):
                grp.append((runs[i].text, runs[i]))
                i += 1
            _add_hyperlink(par, run.link, grp, ctx.output_profile)
            continue
        if run.dest is not None:
            grp = []
            while _grouped(i, lambda r: r.dest == run.dest):
                grp.append((runs[i].text, runs[i]))
                i += 1
            anchor = ctx.dest_anchors.get(run.dest)
            if anchor:
                _add_internal_hyperlink(par, anchor, grp, ctx.output_profile)
            else:
                # A destination whose page holds no flow element to anchor to
                # (an all-figure page, say). Write the text plainly rather than
                # a hyperlink pointing at a bookmark that was never emitted.
                for text, style in grp:
                    _style_run(par.add_run(text), style, ctx.output_profile)
            continue
        if run.field:
            _add_field(par, run.field, "1", run, ctx.output_profile)
            i += 1
            continue
        if run.is_tab:
            r = par.add_run()
            r.add_tab()
            _style_run(r, run, ctx.output_profile)
            i += 1
            continue
        # split on newlines -> soft breaks
        parts = run.text.split("\n")
        for j, chunk in enumerate(parts):
            if chunk:
                r = par.add_run(chunk)
                _style_run(r, run, ctx.output_profile)
            if j < len(parts) - 1:
                br = par.add_run()
                br.add_break(WD_BREAK.LINE)
                _style_run(br, run, ctx.output_profile)
        i += 1
    bookmark = getattr(p, "_bookmark", None)
    if bookmark and bookmark in ctx.anchor_ids:
        _wrap_paragraph_bookmark(par, bookmark, ctx.anchor_ids[bookmark])
    return par


def _spacer(container, height_pt: float):
    """Tiny exact-height paragraph used as vertical spacing before tables."""
    par = container.add_paragraph()
    pf = par.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(max(1.0, round(height_pt, 1)))
    r = par.add_run("")
    r.font.size = Pt(1)
    return par


def _cell_text_width(cell) -> float:
    """Widest single source line in the cell, in pt. 0 when unmeasurable.

    This used to re-shape the text through MuPDF's base-14 metric tables, and
    that was both the writer's only hard dependency on PyMuPDF and a worse answer
    than the one already in the IR. `infer` records the width of every source line
    from its bbox, so for the question this function exists to answer -- is this
    column too narrow for content that occupied exactly one line in the source? --
    the source's own measurement is what actually happened rather than a
    prediction of what will happen. The font mapping is metric-compatible by
    design (Helvetica->Arial, Times->Times New Roman) precisely so the two agree.

    Unmeasurable still returns 0, and the caller still declines to resize on 0. It
    is reached differently now: not "this font has no base-14 equivalent" but
    "this paragraph wrapped in the source, so its width is the column's and says
    nothing about what the content needs", or "the cell was built by a path that
    records no line widths". An absent fact must not be read as a width of zero,
    which is why `source_line_width` returns None and this converts it here.
    """
    widest = 0.0
    for p in cell.paras:
        if "\n" in p.text:
            continue                     # multi-line in source: allowed to wrap
        w = source_line_width(p)
        if w is not None:
            widest = max(widest, w)
    return widest


def _col_floors(t: TableEl) -> List[float]:
    """Per column, the widest line its own cells actually DREW, plus pads.

    The floor of a column is not a prediction of what will fit; it is what
    the source itself laid out -- `src_widths`, wrapping included. Measured
    on a real report: the verdict column's cells all wrap in the source,
    so every width-from-single-line estimator read it as empty, and both
    the resize and the min-column lift drained it (79.5 -> 48pt) to fund a
    neighbour -- after which the Docs importer re-laid the whole grid and
    broke words mid-word. A floor from drawn lines cannot be wrong about
    what the column held.
    """
    floor = [0.0] * len(t.col_widths)
    drawn = getattr(t, "col_edges_drawn", False)
    for row in t.rows:
        # Rows are full-width (None where a merged cell covers a position).
        # A cell spanning columns floors their SUM, which a per-column floor
        # cannot say -- and on the drawn-edge tables that carry spans the
        # columns are the author's anyway -- so it sets none.
        for ci, cell in enumerate(row):
            if cell is None or max(1, getattr(cell, "col_span", 1)) > 1:
                continue
            if ci < len(floor):
                pads = cell.pad[1] + cell.pad[3] \
                    if len(cell.pad) >= 4 else 8.0
                widest = 0.0
                for p in cell.paras:
                    for w in (p.src_widths or []):
                        widest = max(widest, w)
                if widest > 0:
                    # On a drawn-edge table a line wider than its column is
                    # cross-column ink a split refused (no space at the
                    # boundary): cap it at the column, which by
                    # construction held everything the author drew in it.
                    widest = min(widest, t.col_widths[ci]) if drawn else widest
                    floor[ci] = max(floor[ci], widest + pads)
    return floor


def _absorbable(cell, nb) -> bool:
    """Can `cell` span over its right-hand neighbour `nb` without losing ink?

    `nb` must draw nothing of its own -- no text, fill or span -- and the two
    must agree on their top and bottom rules, with no vertical rule between
    them. A rule running under the whole row (x14's totals) is then drawn by
    the merged cell exactly as the separate cells drew it.
    """
    if nb is None or nb.shading or \
            max(1, getattr(nb, "col_span", 1)) > 1 or \
            max(1, getattr(nb, "row_span", 1)) > 1 or \
            any(p.text.strip() for p in nb.paras):
        return False
    for side in ("top", "bottom"):
        if (cell.borders.get(side) or None) != (nb.borders.get(side) or None):
            return False
    return not cell.borders.get("right") and not nb.borders.get("left")


def _span_into_blank_neighbours(t: TableEl) -> TableEl:
    """`t` with each one-line cell that overflows its column spanning the
    blank cells beside it, instead of widening the column.

    A totals label runs across the empty column next to it: x14's
    "Contingency applied" drew 81.5pt from a 35pt column through the empty
    54.5pt one beside it. Widening its column moved the whole indented table
    48-52pt into the right margin; keeping it wrapped the label. Spanning is
    what the source drew. Clustered-edge tables only: a drawn grid is the
    author's own statement of the columns (see `_fit_col_widths`).
    """
    if getattr(t, "col_edges_drawn", False) or len(t.col_widths) < 2:
        return t
    rows, changed = [], False
    for row in t.rows:
        row = list(row)
        for ci, cell in enumerate(row):
            if cell is None or max(1, getattr(cell, "col_span", 1)) > 1 or \
                    max(1, getattr(cell, "row_span", 1)) > 1:
                continue
            w = _cell_text_width(cell)
            if w <= 0 or ci >= len(t.col_widths):
                continue
            pads = cell.pad[1] + cell.pad[3] if len(cell.pad) >= 4 else 8.0
            need = w + pads + 1.0
            have, span = t.col_widths[ci], 1
            while have < need and ci + span < len(row) and \
                    ci + span < len(t.col_widths) and \
                    _absorbable(cell, row[ci + span]):
                have += t.col_widths[ci + span]
                span += 1
            if span > 1 and have >= need:
                borders = dict(cell.borders)
                outer = row[ci + span - 1].borders.get("right")
                if outer:
                    borders["right"] = outer
                row[ci] = dataclasses.replace(cell, col_span=span,
                                              borders=borders)
                for k in range(ci + 1, ci + span):
                    row[k] = None
                changed = True
        rows.append(row)
    if not changed:
        return t
    out = copy.copy(t)
    out.rows = rows
    return out


def _fit_col_widths(t: TableEl, content_w: float = 0.0) -> List[float]:
    """Widen any column too narrow for its own single-line content, funded by
    columns with slack. Table width is unchanged.

    Column boundaries are inferred from text x-position clustering, and on
    dense numeric tables (booktabs especially) they land tight: measured on an
    arXiv paper, '23.75' needed 22.5pt in a 15.6pt column while column 0 sat
    on 44pt of slack. Every such cell wraps to two lines, the row doubles, and
    a 13-row results table gains ~250pt -- the single largest contributor to
    LaTeX page inflation. A cell that occupied one line in the source must get
    a column wide enough to stay one line.
    """
    n = len(t.col_widths)
    widths = list(t.col_widths)
    if n == 0:
        return widths
    # The requirement must include each cell's OWN pads: pads encode the
    # source x-alignment (left pad = text x minus column boundary) and run
    # 7-8pt on booktabs cells. A flat allowance under-asks, the funded width
    # still wraps, and the fix silently does nothing -- measured exactly so on
    # its first run.
    need = [0.0] * n
    for row in t.rows:
        for ci, cell in enumerate(row):     # full-width rows; see _col_floors
            if cell is None:
                continue
            span = max(1, getattr(cell, "col_span", 1))
            w = _cell_text_width(cell)
            if w > 0 and span == 1 and ci < n:
                # A "single line" wider than its own column on a table
                # whose edges were READ FROM GRID LINES is not a need -- it
                # is two cells the parser joined into one line (measured:
                # a 40pt 'base L0' header over a 28.5pt drawn column drove
                # a redistribution that shaved every neighbour and wrapped
                # the whole table). The drawn edge is authoritative; the
                # straddling line says nothing about the column. On a
                # clustered-edge table the same reading is the original
                # case this resize exists for: the edge itself is the
                # estimate that was wrong.
                if getattr(t, "col_edges_drawn", False) \
                        and w > widths[ci] + 1.0:
                    continue
                pads = cell.pad[1] + cell.pad[3] if len(cell.pad) >= 4 else 8.0
                # A line the author's own grid HELD needs no widening: on
                # drawn-edge tables pads measured within the column would
                # otherwise double-count and manufacture deficits the
                # source never had (measured: a 28.6pt line + 6.6pt pads
                # "needed" 35.2 in a 30.8pt column that contained it).
                ask = w + pads + 1.0
                if getattr(t, "col_edges_drawn", False):
                    ask = min(ask, widths[ci])
                need[ci] = max(need[ci], ask)
    deficit = [max(0.0, need[i] - widths[i]) for i in range(n)]
    # The surplus a column may give up is bounded below by its FLOOR --
    # the widest line its cells actually drew. The old `width - 12` default
    # for no-single-line columns read every source-wrapped column as pure
    # slack: on the measured report the all-wrapping verdict column funded
    # a neighbour's deficit from 79.5 down to 48pt and the importer re-laid
    # the whole grid.
    floors = _col_floors(t)
    surplus = [max(0.0, widths[i] - max(need[i], floors[i]) - 1.0)
               for i in range(n)]
    if sum(deficit) <= 0.01:
        return widths
    # A column must be funded FULLY or not at all: a partially-widened column
    # still wraps, so the width is spent and nothing is fixed. (The first
    # version scaled every deficit proportionally when funds ran short --
    # measured effect: zero.) Funds are the gap up to the container width
    # first -- growing the table costs nothing visually, the source usually
    # leaves room -- then slack shaved from over-wide columns.
    # The free room is what lies to the table's RIGHT: the writer places it at
    # `left_indent` (w:tblInd), so room left of it cannot be grown into. Counted
    # from the container's left edge instead, x14's totals block -- indented
    # 322pt -- "found" 318pt and widened its label column 35 -> 83.5pt, which
    # pushed its amounts 48-52pt into the right margin in LibreOffice and
    # Google Docs alike.
    grow = max(0.0, (content_w or 0.0) - max(0.0, t.left_indent)
               - sum(widths)) if content_w else 0.0
    have = grow + sum(surplus)
    order = sorted((i for i in range(n) if deficit[i] > 0),
                   key=lambda i: deficit[i])
    funded = []
    for i in order:
        if deficit[i] <= have + 0.01:
            funded.append(i)
            have -= deficit[i]
    spend = sum(deficit[i] for i in funded)
    for i in funded:
        widths[i] += deficit[i]
    from_slack = max(0.0, spend - grow)
    tot_sur = sum(surplus)
    if from_slack > 0.01 and tot_sur > 0.01:
        for i in range(n):
            if surplus[i] > 0:
                widths[i] -= from_slack * (surplus[i] / tot_sur)
    return widths


# Google adds ~14.8pt of its own above a page-leading band, and it is an
# ADDITION, not a clamp. Measured by testkit/probe_cover_band.py in live pass 2,
# one variable per page, against a LibreOffice control that honoured all twelve
# variants exactly:
#
#     requested top   0.0    4.0    8.0   14.4   20.0
#     Docs rendered  14.55  18.83  22.83  29.23  34.83
#
# so rendered = requested + ~14.8 throughout, with no value of the section top
# margin reaching the page edge. Asking for a header distance instead lands in
# the same place (header 14.4 with top 0 differs by 0.43pt).
#
# Two consequences. Compensation can only subtract where the source actually
# left 14.8pt or more above the band; below that the remainder is a floor and
# `max(0, ...)` accepts it rather than inventing negative spacing. And a true
# top bleed is UNREACHABLE in Google Docs -- roughly 14.6pt of white above a
# page-one band is a documented limitation of the target, not a defect here.
_GDOCS_COVER_BEFORE_COMP_TWIPS = 296  # 14.8pt, measured above

# ---- Google Docs paragraph boundaries: nothing to compensate --------------
# This profile briefly subtracted 3.0pt of space_before at every flow-element
# boundary, on the theory (testkit/docs_quirks.py) that Docs' importer adds
# ~3pt per boundary. The consented live pass of 2026-08-04 measured the theory
# directly against Google's OWN exported PDFs and it is wrong.
#
# Method: for each pair of consecutive flow elements, compare the gap Google
# rendered with the gap the source had, as
#     gap_delta = dy(first line of el i+1) - dy(last line of el i)
# The file asked for space_before - comp, so Docs' own contribution is
# A = gap_delta + comp. Differencing two dy values cancels the paragraph's
# internal line-height error, which a whole-page regression on cumulative
# compensation cannot do (there the two are collinear and the fit blames the
# boundary for all of it -- that is how 3.0pt survived review).
#
# Measured over 187 single-column boundaries in 12 corpus documents:
#     all boundaries      A = +0.10pt   95% CI [+0.04, +0.21]
#     into a body para    A = +0.04pt   95% CI [-2.47, +0.07]   n=147
#     into a heading      A = +0.75pt                            n= 40
#     into a table        A = +1.04pt   95% CI [+0.49, +1.67]   n= 17
# Boundaries that received the full 3.0pt subtraction rendered a gap 2.90pt
# SMALLER than the source: Docs honoured the subtraction and added nothing.
#
# So the subtraction was pure loss, and it accumulated -- c6_long carries 17.4
# boundaries per page, and its dy_p50 went 25.84pt with every word pulled UP
# (dy is negative in all 16 documents). The earlier ~3pt reading came from
# probes written with lineRule="exact"; this profile already retranslates
# exact leading into a multiple, so compensating again double-counted the same
# height twice.
#
# The heading and table residuals are real but sub-point, and this writer
# already quantises font sizes to the half-point (_quantised_size), which moves
# a baseline by up to ~0.5pt on its own. Encoding a +0.75pt constant would be
# encoding its own noise floor, so they are recorded here and not applied.
# Re-measure them if the corpus ever needs the last point of vertical fidelity.


# --- column-break emission --------------------------------------------------
# An explicit column break says "column one ends HERE". That is right only if
# column one's content actually reaches the bottom of the column and no
# further. Measured on an isolated OOXML matrix at y12_irs_pub15's own
# geometry:
#
#   column 1 content     with the break        without it
#   under-fills          19/66  (correct)      66/28  (columns MERGE)
#   just fits            66/66                 66/66  (identical)
#   OVERFLOWS            66/10  (column 2      66/66  (degrades by lines,
#                               abandoned)            not by a column)
#
# So the break protects the source's split when column one under-fills, and
# destroys a column when it overflows: the spill enters column two, and the
# break then fires from column two and advances to the next page. On
# y12_irs_pub15 that is the whole defect -- 59 source pages rendering as 114
# with every second column empty.
#
# The break is therefore emitted only when column one is predicted NOT to
# overflow. The prediction is `ladder.predict_lines`, the same greedy first-fit
# the quality ladder uses; it returns None when it cannot be trusted (non
# base-14 family, unmeasurable glyph), and None keeps the break, which is the
# behaviour that shipped.
#
# The boundary is biased toward keeping the break: the matrix shows the
# "just fits" case works either way, so the slack costs nothing there and buys
# safety against a prediction that is a line optimistic.
COL_OVERFLOW_SLACK_PT = 6.0


def _line_height(p: Para) -> float:
    """The height one rendered line of this paragraph occupies.

    `leading` is the source's own measured line pitch and is preferred whenever
    it is a real measurement; the 1.15 fallback is Word's default single spacing
    for a paragraph that arrived without one.
    """
    return p.leading if (p.leading and p.leading > 1) else \
        (max((r.size for r in p.runs if r.text), default=10.0) * 1.15)


def _element_height(el, avail_w: float, metrics) -> Optional[float]:
    """How tall `el` is predicted to render, gap included. None = unpredictable.

    A Para is measured by re-wrapping it: `predict_lines` is the greedy
    first-fit Word itself uses, so this is how many lines the WRITER will
    produce, which is the whole point -- the source's own line count is what
    the layout already budgeted for. Anything else is measured by its source
    bbox, which is what it will occupy because the writer pins its size.
    """
    if not isinstance(el, Para):
        bb = getattr(el, "bbox", None) or getattr(el, "clip", None) \
            or getattr(el, "_bbox", None)
        if bb is None:
            return None
        return (el.space_before or 0.0) + (bb[3] - bb[1]) + (el.space_after or 0.0)
    n = predict_lines_for(el, avail_w, metrics)
    if n is None:
        return None
    return el.space_before + n * _line_height(el) + el.space_after


def predict_lines_for(p: Para, avail_w: float, metrics) -> Optional[int]:
    """`ladder.predict_lines` against a positive available width."""
    from .ladder import predict_lines
    if avail_w <= 1.0:
        return None
    return predict_lines(p, avail_w, metrics)


def _text_metrics(output_profile: str = "standard"):
    """Shaping metrics, or None if even constructing them fails.

    This asked for `get_metrics("mupdf")`, so the column-overflow and page-spill
    predictions below ran only where the AGPL extra was installed. They take the
    default shaper now, which needs no extra -- so a base install predicts the
    same re-wraps as the measurement environment instead of declining to
    predict any.

    The `except` stays, and is now genuinely defensive rather than the normal
    path: `None` is the answer a non-base-14 font has always produced and every
    caller here treats it as "do not act".
    """
    try:
        from .metrics import for_profile, get_metrics
        return for_profile(get_metrics(), output_profile)
    except Exception:
        return None


def _column_one_overflows(ch, content_w: float, lay: DocLayout,
                          output_profile: str = "standard") -> bool:
    """Is the first column's content predicted to outgrow its column?"""
    if ch.n_cols < 2:
        return False
    metrics = _text_metrics(output_profile)
    if metrics is None:
        return False
    gap = ch.col_gap or 0.0
    col_w = (content_w - gap * (ch.n_cols - 1)) / ch.n_cols
    if col_w <= 1.0:
        return False
    capacity = lay.page_h - lay.margin_t - lay.margin_b - max(0.0, ch.pre_gap)
    used = 0.0
    for el in ch.elements:
        if isinstance(el, ColBreak):
            break
        if not isinstance(el, Para):
            bb = getattr(el, "bbox", None) or getattr(el, "clip", None) \
                or getattr(el, "_bbox", None)
            used += (bb[3] - bb[1]) if bb else 0.0
            continue
        n = predict_lines_for(el, col_w - el.left_indent - el.right_indent,
                              metrics)
        if n is None:
            return False          # not predictable: leave the break alone
        used += el.space_before + n * _line_height(el) + el.space_after
    return used > capacity + COL_OVERFLOW_SLACK_PT


# --- page-spill absorption ---------------------------------------------------
# Every source page ends in an explicit page break, so the reconstruction has no
# slack at the bottom. When a page's content renders one or two lines taller
# than the page box, those lines flow to a new rendered page -- and the hard
# break then fires and advances again, stranding them there alone. A one-line
# overflow costs a whole page. Measured on the expansion corpus at e5e7f30
# (testkit/probe_thin_pages.py), the excess pages ARE those stranded lines:
#
#     document   arm       page_err  thin  <=2 body lines
#     y02        pymupdf        +59    59             35
#     y02        pdfium         +48    47             30
#     y01        pdfium         +34    40             15
#
# `refine.py` already corrects this from a render -- reclaim the page's gap
# slack, largest gaps first, each keeping a floor. That correction is right and
# arrives too late for the profiles that ship no loop at all (the gdocs profile
# is refine0 by construction). So the same correction is made here from a
# PREDICTION instead of a measurement, spending the same currency by the same
# rule, and it is gated the way `_column_one_overflows` is gated: predict, act
# only on a prediction we trust, and bias the boundary toward doing nothing.
#
# The cap is on the STRANDED LINES, not on the overflow in points, and that
# distinction is the whole design. Measured on y02 source page 20: the flow runs
# 38pt past the page box -- three lines' worth -- yet exactly ONE line is
# stranded, because the last element is a running head sitting behind a 91pt
# gap, and that gap is what carries it over. A gap at the top of a page is
# dropped rather than rendered, so the overflow in points says nothing about how
# much content actually lands on the extra page. Capping on the overflow refused
# that page and 57 others like it on y02 alone; capping on what is stranded
# accepts it, and "stranded lines" is the same quantity
# testkit/probe_thin_pages.py counts on the render -- predicted here, observed
# there, so the fix can be held to the sizing.
#
# Two lines is where the mass is. On y02's reference arm the rendered spill
# pages carry one body line 32 times and two body lines twice; past that a page
# is not spilling, it is a page that genuinely does not fit.
SPILL_MAX_LINES = 2
# Bias at the page boundary, in the spirit of COL_OVERFLOW_SLACK_PT. A line
# poking this far past the bottom is read as fitting, so a prediction that is
# marginally pessimistic finds nothing stranded and the page keeps the
# behaviour that shipped.
SPILL_EDGE_SLACK_PT = 6.0
# Pay slightly more than predicted. Sizes are quantised to the half point and
# gaps to a tenth, so a payment of exactly the predicted overflow lands the page
# on the boundary it was trying to clear.
SPILL_SAFETY_PT = 2.0
# The gap floors are `refine.MIN_GAP_SCALE` and its absolute companion, kept
# numerically identical so the open- and closed-loop corrections cannot crush a
# page to two different depths.
SPILL_MIN_GAP_SCALE = 0.30
SPILL_GAP_FLOOR_PT = 2.0
# The page-break paragraph carries `line_spacing exactly 1pt` and continues onto
# the page it opens, so the body box is that much shorter than the margins say.
PAGE_BREAK_PARA_PT = 1.0


def _hf_height(part) -> float:
    """How much of the margin a header or footer part actually claims."""
    if part is None:
        return 0.0
    h = 0.0
    for el in part.elements:
        if isinstance(el, Para):
            n = max(1, el.src_lines or 1)
            h += (el.space_before or 0.0) + n * _line_height(el) \
                + (el.space_after or 0.0)
            continue
        bb = getattr(el, "bbox", None) or getattr(el, "clip", None) \
            or getattr(el, "_bbox", None)
        h += ((bb[3] - bb[1]) if bb else 0.0) \
            + (getattr(el, "space_before", 0.0) or 0.0)
    return h


def _body_foot(lay: DocLayout) -> float:
    """The y where the body box ends: the footnote area's foot. Same model of
    the bottom margin and footer as `_body_capacity`."""
    fd = lay.footer_default.distance if lay.footer_default else 0.0
    return lay.page_h - max(lay.margin_b, fd + _hf_height(lay.footer_default))


def _body_capacity(lay: DocLayout) -> float:
    """The flow height a page really offers, footer and header included.

    Not `page_h - margin_t - margin_b`. `w:pgMar/@footer` is the distance from
    the bottom of the page to the bottom of the footer, and the footer grows
    upward: when it reaches past the bottom margin the renderer shortens the
    BODY to make room. An inferred bottom margin can easily be smaller than the
    footer distance -- y02 comes out at 14pt against the writer's default 36pt
    -- and a capacity taken from the margins alone would then be some 35pt too
    generous.

    It changes no firing on the four documents measured for this fix: none of
    them ends up with a footer part at all, because inference leaves their
    running heads in the body. It is here because the margins are not the box,
    and a document whose footer IS lifted would otherwise be modelled with a
    page that does not exist.

    The header is the same construct upside down and is modelled the same way.
    """
    hd = lay.header_default.distance if lay.header_default else 0.0
    fd = lay.footer_default.distance if lay.footer_default else 0.0
    top = max(lay.margin_t, hd + _hf_height(lay.header_default))
    bottom = max(lay.margin_b, fd + _hf_height(lay.footer_default))
    return lay.page_h - top - bottom - PAGE_BREAK_PARA_PT


def _stack_fits(pg, lay: DocLayout) -> bool:
    """Does this page, stacked the way the flow stacks it, fit its own box?

    Every gap plus every element's own height -- the source's line budget for
    a paragraph (`src_lines` x leading), the source box for anything else --
    against `_body_capacity`. No re-wrap prediction: this asks whether the
    LAYOUT is self-consistent, not how a renderer will wrap it.

    It decides, for the refine loop, which pages may keep a page-top gap at
    their seam (`PageLayout.top_gap_fits`, see `_write_docx`). Honouring that
    gap is only right when the page has room for it. Where the inferred
    elements overlap in the source -- a figure whose box spans the text drawn
    over it, a diagram whose pieces landed in form space (B7) -- the stack is
    taller than the page, and the gap LibreOffice silently dropped after a
    carrier was the only thing keeping such a page on one page: measured on
    y03, keeping those gaps took its render from 71 pages to 74. A
    multi-column page is not additive and answers False.
    """
    used = 0.0
    for ch in pg.chunks:
        if ch.n_cols > 1:
            return False
        used += max(0.0, ch.pre_gap)
        for el in ch.elements:
            if isinstance(el, ColBreak):
                return False
            if isinstance(el, Para):
                used += (el.space_before or 0.0) \
                    + max(1, el.src_lines or 1) * _line_height(el) \
                    + (el.space_after or 0.0)
                continue
            if isinstance(el, RuleEl):
                h = 2.0                   # write_rule's exact line
            else:
                bb = getattr(el, "bbox", None) or getattr(el, "clip", None)
                h = getattr(el, "height", None)
                if h is None and bb is not None:
                    h = bb[3] - bb[1]
                if h is None:
                    return False
            used += (el.space_before or 0.0) + max(0.0, h) \
                + (getattr(el, "space_after", 0.0) or 0.0)
    return used <= _body_capacity(lay)


def _page_spill(pg, content_w: float, lay: DocLayout, notes_h: float = 0.0,
                output_profile: str = "standard"):
    """-> (overflow_pt, stranded_lines) for one source page, or None.

    `notes_h` is the footnote area this page carries when its notes are
    written as real notes (`notes.footnote_areas`): the renderer stacks it
    at the bottom of the body, so the body has that much less room, and the
    page's `role="footnote"` paragraphs are not in the body at all.

    `overflow_pt` is how far the whole flow runs past the page box -- what the
    page's gaps would have to give up for nothing to be stranded.
    `stranded_lines` is how many rendered lines land past the bottom, which is
    what actually appears on the extra page. The two are different numbers and
    the second is the one that says whether this is a spill: see SPILL_MAX_LINES.

    `None` means the page cannot be predicted and must be left exactly as it is
    written today. Only single-column, non-continuation pages are answered: a
    multi-column page is already governed by `_column_one_overflows`, and two
    predictions correcting the same page against different capacity models is
    how a fix starts fighting itself; a continuation page has had its break
    dropped deliberately and has nothing to strand.
    """
    if getattr(pg, "continuation_only", False) or not pg.chunks:
        return None
    if any(ch.n_cols > 1 for ch in pg.chunks):
        return None
    metrics = _text_metrics(output_profile)
    if metrics is None:
        return None
    capacity = _body_capacity(lay) - notes_h
    bottom = capacity + SPILL_EDGE_SLACK_PT
    used, stranded = 0.0, 0
    for ch in pg.chunks:
        used += max(0.0, ch.pre_gap)
        for el in ch.elements:
            if notes_h > 0 and getattr(el, "role", "") == "footnote":
                continue
            if isinstance(el, ColBreak):
                return None       # a column break on a one-column page: unmodelled
            if not isinstance(el, Para):
                h = _element_height(el, content_w, metrics)
                if h is None:
                    return None   # no box to measure: leave the page alone
                used += h
                if used > bottom:
                    # A block crossing the boundary is not a two-line spill,
                    # and how a renderer splits one is not modelled here.
                    return None
                continue
            n = predict_lines_for(
                el, content_w - el.left_indent - el.right_indent, metrics)
            if n is None:
                return None       # not predictable: leave the page alone
            lead = _line_height(el)
            used += el.space_before
            for _ in range(n):
                used += lead
                if used > bottom:
                    stranded += 1
            used += el.space_after
    return used - capacity, stranded


def _absorb_page_spill(pg, content_w: float, lay: DocLayout,
                       notes_h: float = 0.0,
                       output_profile: str = "standard") -> dict:
    """Plan the gap reductions that keep a small spill on its own page.

    Returns `{id(element): new_space_before}`, empty when the page is to be
    written exactly as it is today. **Nothing is mutated**: the refine loop
    writes the same layout once per round and a correction applied in place
    would compound on every pass, which is the same reason `write_para` keeps
    its wrap correction local.

    Slack is taken from paragraph gaps only. They are the bulk of a text page's
    slack, they are the gaps whose loss the eye forgives, and confining the plan
    to them keeps the whole change inside one writer signature. A page whose
    paragraph gaps cannot cover the overflow in full is left alone: a partial
    payment spends the spacing and still loses the page.
    """
    got = _page_spill(pg, content_w, lay, notes_h, output_profile)
    if got is None:
        return {}
    overflow, stranded = got
    if stranded <= 0 or stranded > SPILL_MAX_LINES or overflow <= 0.0:
        return {}
    paras = [el for ch in pg.chunks for el in ch.elements
             if isinstance(el, Para)
             and not (notes_h > 0 and el.role == "footnote")]
    if not paras:
        return {}
    want = overflow + SPILL_SAFETY_PT
    slack = []
    for p in paras:
        gap = p.space_before or 0.0
        floor = max(SPILL_GAP_FLOOR_PT, gap * SPILL_MIN_GAP_SCALE)
        take = gap - floor
        if take > 0.05:
            slack.append((take, gap, p))
    if sum(t for t, _, _ in slack) < want:
        return {}
    plan = {}
    # Largest gaps first, exactly as `refine._apply` reclaims them: a 40pt
    # section break and a 4pt paragraph gap are not equally elastic, and the eye
    # notices the section break shrinking long after it notices the other.
    for take, gap, p in sorted(slack, key=lambda t: -t[1]):
        if want <= 0.05:
            break
        paid = min(take, want)
        plan[id(p)] = round(gap - paid, 1)
        want -= paid
    return plan


def _band_accent_as_row(t: TableEl) -> TableEl:
    """Re-express a band cell's accent border as a shaded row of its own.

    Inference already records a cover block's accent stripe -- a thin
    full-width fill flush against the block -- as a bottom border on the band
    cell, and that is a faithful representation: LibreOffice renders it at the
    right colour and thickness from `w:tcBorders`.

    Google Docs does not. The 4pt orange stripe on 01_whitepaper is absent from
    every Docs render across live passes 2, 3 and 4, while the navy block above
    it -- which is `w:shd` cell shading on the same cell -- comes back every
    time. So shading is demonstrably honoured by Docs where a thick table
    border is not, and this trades one construct for the other on the profile
    that needs it.

    The stripe becomes a second row of the same table, shaded with the accent
    colour and pinned to the stripe's own height, and the border is dropped so
    the two cannot both render.
    """
    if len(t.rows) != 1 or len(t.rows[0]) != 1 or not t.rows[0][0]:
        return t
    cell = t.rows[0][0]
    spec = (cell.borders or {}).get("bottom")
    if not spec:
        return t
    thickness, color = spec
    if not color or thickness <= 0:
        return t
    main = copy.copy(cell)
    main.borders = {k: v for k, v in (cell.borders or {}).items() if k != "bottom"}
    # The stripe is carved OUT of the band, never added underneath it: the
    # source block is navy 170 + accent 4 = 174 total, not 174 + 4.
    #
    # Reducing row_heights[0] alone does nothing, and that was the bug live
    # pass 5 caught. Row 0 carries the cover text, and the writer deliberately
    # leaves text rows content-driven -- it pins w:trHeight only on rows with
    # no text -- so row_heights[0] is never emitted for this row. The height
    # that actually has to give is the cell's bottom padding, which
    # build_band_table sized against the whole block including the stripe.
    pad = tuple(cell.pad) if len(cell.pad) >= 4 else (0.0, 0.0, 0.0, 0.0)
    main.pad = (pad[0], pad[1], max(0.0, round(pad[2] - thickness, 1)), pad[3])
    stripe = Cell(shading=color, borders={}, pad=(0.0, 0.0, 0.0, 0.0),
                  paras=[Para(runs=[Run(text="", font="Helvetica", size=2,
                                        color="#000000")],
                              leading=max(1.0, thickness))])
    band_h = t.row_heights[0] if t.row_heights else None
    heights = [max(1.0, band_h - thickness) if band_h else None, thickness]
    out = copy.copy(t)
    out.rows = [[main], [stripe]]
    out.row_heights = heights
    return out


# The Google Docs importer drops the boundary of a column narrower than
# roughly the low twenties of points -- measured on a report whose 13.6pt
# "#" column arrived merged into its neighbour in the export, re-flowing
# every cell of every row (the same document's 27.2pt columns survived
# intact). Columns below this are bumped up to it, funded from the widest
# column of the same table, so the table's total width never moves.
GDOCS_MIN_COL_PT = 22.0


def _gdocs_min_col_widths(widths: List[float], t: TableEl = None,
                          minimum: float = GDOCS_MIN_COL_PT) -> List[float]:
    """Lift sub-minimum columns to the import floor, without starving anyone.

    Every column carries a FLOOR: the widest line its own cells actually
    drew (src_widths, wrapping included) plus that cell's pads. Funding may
    never take a column below its floor. Measured on the report that
    motivated the minimum: the verdict column's line sat at 79.4 of
    79.5pt, proportional funding shaved 2.3pt, its content overflowed, and
    the Docs importer re-laid the ENTIRE grid content-driven -- every
    column rebalanced, the verdict column a 48pt remnant breaking words
    mid-word. A floor-less need-aware variant failed the other way (source-
    wrapped cells look like pure slack and were drained); the floor is the
    piece that was missing: it bounds every cell by what it drew, not by
    what a wrap-prediction thinks it needs.

    When floors leave insufficient funds, the table GROWS by the shortfall
    rather than break a floor: a table a few points into the right margin
    beats one whose every column re-flows.
    """
    ws = list(widths)
    if len(ws) < 2:
        return ws
    floor = _col_floors(t) if t is not None else [0.0] * len(ws)
    for i in range(len(ws)):
        deficit = minimum - ws[i]
        if deficit <= 0:
            continue
        room = [max(0.0, ws[j] - max(floor[j], minimum * 0.8))
                for j in range(len(ws))]
        pool = sum(room)
        # fund from room proportionally; grow the table for what is left
        take = min(deficit, pool)
        if take > 0:
            for j in range(len(ws)):
                if j == i or room[j] <= 0:
                    continue
                cut = take * room[j] / pool
                ws[j] -= cut
                room[j] -= cut
            deficit -= take
        ws[i] = minimum           # any residue grows the table, by design
    return ws


def _gdocs_paragraph_form(t: TableEl, ctx) -> bool:
    """True when the gdocs profile writes this table as bordered paragraphs."""
    return getattr(t, "role", "") in ("quote", "box") \
        and ctx.output_profile == "gdocs" \
        and bool(t.rows and t.rows[0] and t.rows[0][0] is not None)


def table_opens_with_spacer(t: TableEl, ctx=None) -> bool:
    """Whether `write_table` starts this table with its `_spacer` paragraph.

    The page-seam code asks, because a spacer is a paragraph and can carry the
    page break itself (see `_write_docx`). One predicate for both, so the seam
    can never put the break on a spacer the writer then declines to emit.
    """
    ctx = ctx or _DEFAULT_CTX
    return bool(t.rows) and bool(t.col_widths) and t.space_before > 0.5 \
        and not _gdocs_paragraph_form(t, ctx)


def write_table(container, t: TableEl, content_w: float, ctx=None,
                cover_band: bool = False, page_break_before: bool = False):
    ctx = ctx or _DEFAULT_CTX
    # A coloured page-one cover band is the one table Google Docs treats
    # differently.  Do not infer this from ``role == 'band'``: header bands
    # share that role and must retain their ordinary table treatment.
    gdocs_cover = cover_band and ctx.output_profile == "gdocs"
    if gdocs_cover:
        t = _band_accent_as_row(t)
    # A quote bar under the gdocs profile is a paragraph BORDER, not a
    # one-cell table.  Measured on Google's own export: inside a table cell
    # every line of the quote renders 1-2pt taller than its source -- ~40
    # lines to a block, the block outgrew its page and the spill cascaded
    # through the document.  As body paragraphs the same lines carry the
    # profile's calibrated line encoding and land where the source put
    # them, and the bar is one continuous left border: pBdr left
    # val=single sz=12 space=7 colour=BBBBBB is the exact form the live
    # campaign verified (Docs draws it 2.0pt wide, quantised, colour
    # exact).  The standard profile keeps its measured table form.
    if _gdocs_paragraph_form(t, ctx) and t.role == "quote":
        return _write_quote_paragraphs(container, t, content_w, ctx,
                                       page_break_before=page_break_before)
    # A callout box likewise: one cell whose four borders belong on the
    # paragraphs it contains -- the table form's cell line inflation is the
    # same measured +1-2pt/line that took the quote blocks out of tables.
    # The four sides split by position: left and right on every paragraph
    # (a continuous rail), top on the first, bottom on the last. This is
    # the live-verified hand-campaign round-6 form (sz=6 #333333, the
    # source's own 0.75pt stroke).
    if _gdocs_paragraph_form(t, ctx) and t.role == "box":
        return _write_box_paragraphs(container, t, content_w, ctx,
                                     page_break_before=page_break_before)
    n_rows = len(t.rows)
    n_cols = len(t.col_widths)
    if n_rows == 0 or n_cols == 0:
        return None
    t = _span_into_blank_neighbours(copy.copy(t))
    t.col_widths = _fit_col_widths(t, content_w)
    # the importer drops sub-minimum columns' boundaries (see the constant);
    # lift them before the grid is written
    if ctx.output_profile == "gdocs":
        t.col_widths = _gdocs_min_col_widths(t.col_widths, t)
    if t.space_before > 0.5:
        sp = _spacer(container, t.space_before)
        if page_break_before:
            sp.paragraph_format.page_break_before = True
    try:
        tbl = container.add_table(rows=n_rows, cols=n_cols)
    except TypeError:  # header/footer/cell containers require a width argument
        tbl = container.add_table(rows=n_rows, cols=n_cols,
                                  width=Emu(int(sum(t.col_widths) * 12700)))
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    tblPr = tbl._tbl.tblPr
    # fixed layout
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)
    for old in tblPr.findall(qn("w:tblW")):
        tblPr.remove(old)
    tw = OxmlElement("w:tblW")
    tw.set(qn("w:w"), str(int(round(sum(t.col_widths) * 20))))
    tw.set(qn("w:type"), "dxa")
    tblPr.append(tw)
    if t.left_indent > 0.5:
        ind = OxmlElement("w:tblInd")
        ind.set(qn("w:w"), str(int(round(t.left_indent * 20))))
        ind.set(qn("w:type"), "dxa")
        tblPr.append(ind)
    # no default borders / spacing; zero default cell margins
    tb = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement("w:" + side)
        b.set(qn("w:val"), "nil")
        tb.append(b)
    tblPr.append(tb)
    mar = OxmlElement("w:tblCellMar")
    for side in ("top", "left", "bottom", "right"):
        m = OxmlElement("w:" + side)
        m.set(qn("w:w"), "0")
        m.set(qn("w:type"), "dxa")
        mar.append(m)
    tblPr.append(mar)
    # grid
    grid = tbl._tbl.find(qn("w:tblGrid"))
    for gc, wpt in zip(grid.findall(qn("w:gridCol")), t.col_widths):
        gc.set(qn("w:w"), str(int(round(wpt * 20))))

    first_cover_text = True
    # Merged cells (infer.build_grid_table): every grid position a span
    # covers, other than the span's own, maps to (cell, r0, c0, cols, rows).
    cover = _span_cover(t, n_rows, n_cols)
    # What each row's cells are WRITTEN with: one top and one bottom pad per
    # row (see _uniform_row_pads). The row-height arithmetic below keeps
    # reading the cells as inferred. Not under the gdocs profile, whose
    # row model was calibrated live on per-cell pads (the round-4 levers
    # below) and has no measurement of Docs' rule yet.
    emit_rows = t.rows if ctx.output_profile == "gdocs" \
        else _uniform_row_pads(t.rows, n_cols)
    for ri, rowspec in enumerate(t.rows):
        row = tbl.rows[ri]
        if ri < t.repeat_header_rows:
            # Only inference backed by a repeated source row may request a
            # Word repeating header.  Inventing one changes ordinary PDFs.
            trPr = row._tr.get_or_add_trPr()
            hdr = OxmlElement("w:tblHeader")
            hdr.set(qn("w:val"), "true")
            trPr.append(hdr)
        h = t.row_heights[ri] if ri < len(t.row_heights) else None
        # A row's height belongs to the cells that live in it alone. A cell
        # merged down over several rows is laid out across all of them
        # (Word, LibreOffice and Docs all grow the LAST row of a merge if
        # its content needs more), so counting its whole text against its
        # first row would compress -- or grow -- that row for content that
        # is not in it.
        own = [c for c in rowspec[:n_cols]
               if c and max(1, getattr(c, "row_span", 1)) == 1]
        # Only pin height on rows with no text: text rows are content-driven
        # (cell pads + exact-leading paragraphs sum to the source height,
        # which renders identically in Word, Google Docs and LibreOffice).
        # A row whose only text is a merged cell's is, for its own height,
        # a row with no text.
        row_has_text = any(any(p.text.strip() for p in c.paras) for c in own)
        if h and not row_has_text:
            trPr = row._tr.get_or_add_trPr()
            th = OxmlElement("w:trHeight")
            # A pinned height is the row's total, borders included (measured
            # on the canonical LibreOffice 24.2: a 40pt pin with 0.5pt rules
            # renders 40.0), unlike a content-driven row; see
            # _row_border_allowance.
            th.set(qn("w:val"), str(int(round(h * 20))))
            th.set(qn("w:hRule"), "atLeast")
            trPr.append(th)
        # The Google Docs importer pads every table row by about 1.9pt on
        # top of its content (measured live, hand campaign round 4, on the
        # same report: a 59-row table ran 1-2pt/row taller than its source
        # and spilled its page). Two levers, both gdocs-profile only since
        # the standard profile's renderer adds no such overhead and its
        # numbers are the gated ones: pin the row's height to the SOURCE
        # row height (atLeast -- empty-headed rows render at it), and let
        # the shrink below target h - overhead so content + overhead lands
        # on the pin instead of past it. Rows land 0 to ~0.1pt under
        # source, which cannot spill.
        #
        # DATA tables only (role "table"), which is what the levers were
        # measured on. Applied to every text row they also pinned cover
        # bands and stat-card rows, whose content-driven pads already sum
        # to the source height: live pass 8 (2026-10-04) put 04_exec_brief
        # at dy_p50 13.24pt against pass 7's 2.43 and c1_whitepaper at
        # 11.56 against 5.56. Bisected to the commit that introduced the
        # pin (d26d7ff); the same DOCX with the band/card pins removed
        # measured 1.95 / 3.82 live.
        gdocs_rowpin = ctx.output_profile == "gdocs" and t.role == "table"
        if gdocs_rowpin and h and row_has_text:
            trPr = row._tr.get_or_add_trPr()
            th = OxmlElement("w:trHeight")
            th.set(qn("w:val"), str(int(round(h * 20))))
            th.set(qn("w:hRule"), "atLeast")
            trPr.append(th)
        # The content-driven model assumes pads + exact-leading paragraphs sum
        # to the source row height. That holds for ordinary tables and fails
        # for maths: a row of stacked sub/superscripts can occupy 5.2pt in the
        # source while its text carries an 11.6pt leading, so the row renders
        # at more than twice its height. Measured on an arXiv paper: a 73.6pt
        # seven-row table rendered 31.4pt (43%) taller, entirely from three
        # such rows. Where the source row is shorter than its own content,
        # the leading is compressed to fit rather than left to overflow.
        row_shrink = 1.0
        if h and row_has_text:
            need = 0.0
            for c in own:
                cell_h = (c.pad[0] + c.pad[2]) if len(c.pad) >= 4 else 0.0
                for p in c.paras:
                    lead = p.leading or (p.runs[0].size * 1.2 if p.runs else 11.0)
                    cell_h += max(1, p.src_lines or 1) * lead
                need = max(need, cell_h)
            # standard profile: compress to the source height, as always.
            # (the gdocs target is set by the round-4 lever [C] below)
            if not gdocs_rowpin and need > h + 0.5:
                row_shrink = max(MIN_ROW_SHRINK, h / need)
        # Round-4 lever [C], gdocs profile: Docs rounds every row box UP to
        # a whole point, and that rounding was the measured +1.27pt/row
        # surplus (the mark rPr is inert there -- ceil of the no-mark model
        # reproduced 24/35 clean rows exactly). Cut the BOTTOM pad first --
        # it is spacing, not text, so readability survives -- and only
        # compress leading if the pad is exhausted. Rows land on
        # floor(source height) minus a safety, which cannot spill.
        pad_cut = 0.0
        if gdocs_rowpin and h and row_has_text:
            target = math.floor(h) - GDOCS_ROW_SAFETY_PT
            if need > target + 0.5:
                avail = max([(c.pad[2] if len(c.pad) >= 4 else 0.0)
                             for c in own] or [0.0])
                pad_cut = min(need - target, max(0.0, avail))
                need -= pad_cut
                if need > target + 0.5:
                    row_shrink = max(MIN_ROW_SHRINK, target / need)
                else:
                    row_shrink = 1.0
        tcs = list(row._tr.tc_lst)
        emitspec = emit_rows[ri]
        for ci in range(n_cols):
            spec = emitspec[ci] if ci < len(emitspec) else None
            covered = cover.get((ri, ci)) if spec is None else None
            if covered is not None and (covered[1] == ri or covered[2] != ci):
                # inside a gridSpan: the spanning w:tc owns this grid column
                row._tr.remove(tcs[ci])
                continue
            tc = tcs[ci]
            cell = _Cell(tc, tbl)
            tcPr = tc.get_or_add_tcPr()
            for old in tcPr.findall(qn("w:tcW")):
                tcPr.remove(old)
            cs = 1 if spec is None else \
                max(1, min(getattr(spec, "col_span", 1), n_cols - ci))
            rs = 1 if spec is None else \
                max(1, min(getattr(spec, "row_span", 1), n_rows - ri))
            if covered is not None:
                spec, r0, _c0, cs, rs = covered
            cw = sum(t.col_widths[ci:ci + cs])
            tcw = OxmlElement("w:tcW")
            tcw.set(qn("w:w"), str(int(round(cw * 20))))
            tcw.set(qn("w:type"), "dxa")
            tcPr.append(tcw)
            # schema order: tcW, gridSpan, vMerge, tcBorders, shd, ...
            if cs > 1:
                gs = OxmlElement("w:gridSpan")
                gs.set(qn("w:val"), str(cs))
                tcPr.append(gs)
            if rs > 1:
                vm = OxmlElement("w:vMerge")
                if covered is None:
                    vm.set(qn("w:val"), "restart")
                tcPr.append(vm)
            if covered is not None:
                # A continuation row of a merged cell: an empty w:tc carrying
                # the merge's shading and its own row's share of the borders
                # (sides, and the bottom only on the merge's last row).
                last = ri == r0 + rs - 1
                if spec.shading:
                    shd = OxmlElement("w:shd")
                    shd.set(qn("w:val"), "clear")
                    shd.set(qn("w:fill"), _hex(spec.shading))
                    tcPr.append(shd)
                _set_borders(tcPr, _merge_part_borders(spec.borders, False, last),
                             "w:tcBorders")
                _blank_cell(cell)
                continue
            if spec is None:
                _blank_cell(cell)
                _set_borders(tcPr, {}, "w:tcBorders")
                continue
            spanning = rs > 1
            if spec.shading:
                shd = OxmlElement("w:shd")
                shd.set(qn("w:val"), "clear")
                shd.set(qn("w:fill"), _hex(spec.shading))
                tcPr.append(shd)
            _set_borders(tcPr, _merge_part_borders(spec.borders, True, not spanning)
                         if spanning else spec.borders, "w:tcBorders")
            tmar = OxmlElement("w:tcMar")
            pads = spec.pad  # (top, left, bottom, right)
            # Google ignores tcMar/left: first measured on the bleed cover
            # table, and the c7_code Google evidence shows the same signature
            # on ordinary cells (dx_p50 ~ the 10.7pt code-cell tcMar left).
            # Under the gdocs profile, move (rather than duplicate) the left
            # padding of EVERY cell to its paragraphs below, so a future
            # importer which starts honouring tcMar does not double it.  The
            # relocation is exact for renderers that do honour tcMar (Word,
            # LibreOffice): tcMar_left + max(0, indent - pad) and
            # max(indent, pad) land text at the same x.
            gdocs_cellpad = ctx.output_profile == "gdocs"
            # Round-4 lever [B], gdocs profile: Docs charges the cell
            # BORDER against the text area -- at sz=6 the wrap boundary sits
            # 0.75pt inside the declared width -- so cells whose source line
            # sat within that of the width wrapped to a new line and the row
            # grew ("INCONCLUSIVE ×5" over a 79.5pt column, measured). Trim
            # the right pad past the loss with margin (their MR_DELTA was
            # 20tw on top of the 0.75pt loss; 1.75pt total). It is
            # monotone-safe: widening the wrap width can only REMOVE a wrap,
            # never add one.
            # (a merged cell's rows were sized without it: no cut, no shrink)
            cell_cut = 0.0 if spanning else pad_cut
            emitted_pads = (pads[0], 0.0, max(0.0, pads[2] - cell_cut),
                            max(0.0, pads[3] - 1.75)) \
                if gdocs_cellpad else pads
            for side, val in zip(("top", "left", "bottom", "right"),
                                  emitted_pads):
                m = OxmlElement("w:" + side)
                m.set(qn("w:w"), str(max(0, int(round(val * 20)))))
                m.set(qn("w:type"), "dxa")
                tmar.append(m)
            tcPr.append(tmar)
            if spec.valign and spec.valign != "top":
                va = OxmlElement("w:vAlign")
                va.set(qn("w:val"), spec.valign)
                tcPr.append(va)
            if spec.paras:
                # Cell paragraphs carry indents measured from the CELL EDGE
                # (text x minus cell x), and the same distance is already
                # emitted as tcMar above -- so an unadjusted indent applies the
                # pad twice and the text area loses it twice. Measured: a
                # 35.8pt column left 14.6pt for '24.6' (17.5pt), so the number
                # wrapped char-by-char and the row doubled. Word indents are
                # measured from the tcMar edge; make the paragraphs agree.
                def _depadded(p, _s=1.0 if spanning else row_shrink):
                    q = copy.copy(p)
                    if gdocs_cellpad:
                        # Standard rendering lands at max(source indent,
                        # tcMar left).  With tcMar moved to zero, carry that
                        # effective position exactly; adding would double the
                        # common case where inference already included the pad.
                        if p.align in ("right", "center"):
                            # The source x-alignment of a right- or centre-
                            # aligned cell line is POSITION, and jc already
                            # places it. Keeping it as w:ind consumes the
                            # wrap width for nothing: measured live, Docs
                            # wrapped '28/60' (22.4pt of Georgia 8) inside a
                            # 29.75pt cell because ind left=254tw left only
                            # 17pt of line -- the mid-token breaks the cw2
                            # class was named for. LibreOffice renders the
                            # same XML unbroken, which is why the gated
                            # lanes never saw it.
                            pos = 0.0
                        else:
                            pos = max(0.0, p.left_indent, pads[1])
                        # The wrap bracket, gdocs: position may never push
                        # the wrap boundary under the text's own width. The
                        # width is the SOURCE's own drawing of the line
                        # (`source_line_width`) -- the same glyphs Docs
                        # renders, measured in the PDF rather than predicted
                        # from a font model -- with the live-measured ~10%
                        # advance gap plus the 1pt border charge on top.
                        # Monotone-safe: a smaller indent can only remove a
                        # wrap. Wrapped-in-source paragraphs read None and
                        # keep their indent: their width IS the column's.
                        if pos > 0.0 and ci < len(t.col_widths):
                            w = source_line_width(p)
                            if w is not None:
                                inner = max(0.0, cw - emitted_pads[3] - 2.0)
                                pos = min(pos, max(
                                    0.0, inner - w * 1.15 - 1.0))
                        q.left_indent = pos
                    else:
                        q.left_indent = max(0.0, p.left_indent - pads[1])
                    q.right_indent = max(0.0, p.right_indent - pads[3])
                    if _s < 0.999 and p.leading:
                        q.leading = max(2.0, p.leading * _s)
                    return q
                first = cell.paragraphs[0]
                for pi, p in enumerate(spec.paras):
                    q = _depadded(p)
                    if gdocs_cover and first_cover_text and p.text.strip():
                        # The extra space is a direct paragraph before-spacing
                        # translation in Google Docs.  Preserve all other
                        # paragraph properties and floor at zero for short bands.
                        q = copy.copy(q)
                        before = max(0, int(round(p.space_before * 20)) -
                                     _GDOCS_COVER_BEFORE_COMP_TWIPS)
                        q.space_before = before / 20.0
                        first_cover_text = False
                    cpar = write_para(cell, q, cw,
                                      par=first if pi == 0 else None, ctx=ctx)
                    _size_mark_to_content(cpar, q)
            else:
                _blank_cell(cell)
    return tbl


def _block_right_gap(t: TableEl, content_w: float) -> float:
    """Distance from a one-cell block's right edge to the column's right edge."""
    width = sum(t.col_widths) if t.col_widths else content_w - t.left_indent
    return max(0.0, content_w - t.left_indent - width)


def _write_quote_paragraphs(container, t: TableEl, content_w: float, ctx=None,
                            page_break_before: bool = False):
    """A quote bar as body paragraphs with a left border (gdocs profile).

    See `write_table` for why the table form is replaced here.  Geometry:
    the table's `left_indent` is the bar's column-relative x; each cell
    paragraph's own indent is measured from the bar.  The border is drawn
    `w:space` points left of the text, so pinning every paragraph's indent
    to the same value and setting space to the bar-to-text distance puts
    the bar exactly where the source drew it, continuously, regardless of
    how the paragraphs inside wrap.
    """
    cell = t.rows[0][0]
    bar = (cell.borders or {}).get("left") or (1.5, "#bbbbbb")
    bar_w, bar_col = bar[0], _hex(bar[1])
    sz_eighths = max(2, int(round(bar_w * 8)))
    # bar-to-text distance: the cell's left pad carries it (text x = bar x
    # + pad), and a paragraph may sit further in still
    pad_left = cell.pad[1] if len(cell.pad) >= 4 else 0.0
    pads = cell.pad if len(cell.pad) >= 4 else (0.0, 0.0, 0.0, 0.0)
    # The table form's cell bounded the wrap on the right; body paragraphs
    # run to the column edge unless the cell's right edge and pad are
    # written onto them as a right indent. Without it 04_exec_brief's quote
    # (a block narrower than its column) ran one line past the source's
    # wrap edge, live pass 8 (2026-10-04) measuring dy_p90 38pt where pass
    # 7's table form measured 6.2. The block's VERTICAL position needs no
    # transfer: adding the table gap and cell pads to the first and last
    # paragraph broke B13's CLEAN 1:1 live (a spill at source page 3), whose
    # quote gaps the paragraphs already carry.
    right_gap = _block_right_gap(t, content_w)
    out = []
    n = len(cell.paras)
    for pi, p in enumerate(cell.paras):
        q = copy.copy(p)
        space = max(0.0, min(31.0, pad_left + q.left_indent))
        q.left_indent = max(0.0, t.left_indent + pad_left + q.left_indent)
        q.right_indent = max(0.0, right_gap + pads[3] + (q.right_indent or 0.0))
        q.first_indent = 0.0
        par = write_para(container, q, content_w, ctx=ctx,
                         page_break_before=page_break_before and pi == 0)
        if par is None:
            continue
        ppr = par._p.get_or_add_pPr()
        bd = ppr.find(qn("w:pBdr"))
        if bd is None:
            bd = OxmlElement("w:pBdr")
            ppr.append(bd)
        left = OxmlElement("w:left")
        left.set(qn("w:val"), "single")
        left.set(qn("w:sz"), str(sz_eighths))
        left.set(qn("w:space"), str(int(round(space))))
        left.set(qn("w:color"), bar_col)
        bd.append(left)
        out.append(par)
    return out[0] if out else None


def _write_box_paragraphs(container, t: TableEl, content_w: float, ctx=None,
                          page_break_before: bool = False):
    """A callout box as body paragraphs carrying a four-side border (gdocs).

    See `write_table` for why the table form is replaced. Geometry follows
    the source's own measurements: the left rail sits `pad_left` from the
    text, the right rail `pad_right` (from the box edge minus the widest
    line), the top border `pads[0]` above the first paragraph, the bottom
    `pads[2]` below the last. w:space is capped at 31pt by the schema.
    """
    cell = t.rows[0][0]
    b = cell.borders or {}
    left = b.get("left") or (0.75, "#333333")
    right = b.get("right") or left
    top = b.get("top") or left
    bot = b.get("bottom") or left
    pads = cell.pad if len(cell.pad) >= 4 else (0.0, 0.0, 0.0, 0.0)
    # measured right inset: box right edge against the widest source line
    text_r = max((p.bbox[2] for p in cell.paras if p.bbox), default=t.bbox[2])
    pad_right = max(0.0, min(31.0, t.bbox[2] - text_r)) if t.bbox else pads[3]
    # top/bottom spaces from the RECT's own edges against the text they
    # bound -- `cell.pad` can over-measure the bottom (it counted 49.9pt
    # where the source rect's own edge sits 9.4pt under the last line)
    text_t = min((p.bbox[1] for p in cell.paras if p.bbox), default=t.bbox[1])
    text_b = max((p.bbox[3] for p in cell.paras if p.bbox), default=t.bbox[3])
    space_top = max(0.0, min(31.0, text_t - t.bbox[1])) if t.bbox else pads[0]
    space_bot = max(0.0, min(31.0, t.bbox[3] - text_b)) if t.bbox else pads[2]
    sz = lambda edge: max(2, int(round(edge[0] * 8)))
    col = lambda edge: _hex(edge[1])
    out = []
    n = len(cell.paras)
    for pi, p in enumerate(cell.paras):
        q = copy.copy(p)
        space_l = max(0.0, min(31.0, pads[1] + q.left_indent))
        q.left_indent = max(0.0, t.left_indent + pads[1] + q.left_indent)
        # measured from the BOX's right edge, not the column's: a box
        # narrower than its column otherwise wraps its text at the column
        q.right_indent = max(0.0, pad_right)
        q.first_indent = 0.0
        par = write_para(container, q, content_w, ctx=ctx,
                         page_break_before=page_break_before and pi == 0)
        if par is None:
            continue
        ppr = par._p.get_or_add_pPr()
        bd = ppr.find(qn("w:pBdr"))
        if bd is None:
            bd = OxmlElement("w:pBdr")
            ppr.append(bd)
        def _side(tag, edge, space):
            el = OxmlElement("w:" + tag)
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), str(sz(edge)))
            el.set(qn("w:space"), str(int(round(space))))
            el.set(qn("w:color"), col(edge))
            bd.append(el)
        # schema order inside w:pBdr is top, left, bottom, right; a reader
        # that validates order (measured: Google Docs drops the whole
        # border when 'left' precedes 'top') renders nothing at all
        if pi == 0:
            _side("top", top, space_top)
        _side("left", left, space_l)
        if pi == n - 1:
            _side("bottom", bot, space_bot)
        _side("right", right, pad_right)
        out.append(par)
    return out[0] if out else None


def _span_cover(t: TableEl, n_rows: int, n_cols: int) -> dict:
    """{(row, col): (cell, r0, c0, col_span, row_span)} for every grid
    position a merged cell covers other than its own top-left one."""
    cover = {}
    for r0, rowspec in enumerate(t.rows[:n_rows]):
        for c0, spec in enumerate(rowspec[:n_cols]):
            if spec is None:
                continue
            cs = max(1, min(getattr(spec, "col_span", 1), n_cols - c0))
            rs = max(1, min(getattr(spec, "row_span", 1), n_rows - r0))
            if cs == 1 and rs == 1:
                continue
            for r in range(r0, r0 + rs):
                for c in range(c0, c0 + cs):
                    if (r, c) != (r0, c0):
                        cover[(r, c)] = (spec, r0, c0, cs, rs)
    return cover


def _row_border_allowance(row) -> float:
    """Height a row's own horizontal borders add to it in the renderer.

    Pads are derived from the source's line CENTRES, so the source row
    pitch already contains its rules. LibreOffice lays the border out on
    top of pads + content: measured (exp/border) a 14.0pt row of pads and
    one line renders at a 14.0 + w pitch for borders of width w on every
    cell, w from 0.25 to 4.0 exactly. Half the top and half the bottom
    border, the widest in the row.
    """
    allow = 0.0
    for c in row:
        if c is None:
            continue
        b = c.borders or {}
        w = sum((b.get(k) or (0.0,))[0] for k in ("top", "bottom")) / 2.0
        allow = max(allow, w)
    return allow


def _uniform_row_pads(rows, n_cols: int):
    """Each row's cells with ONE top and ONE bottom margin; the difference
    moved into the first paragraph's space-before. Returns new rows.

    The content-driven row model (THEORY 3.2) derives every cell's pads from
    its own geometry, so that pads + exact-leading lines sum to the source
    row in each cell. Word sizes a row per cell. LibreOffice does not: it
    measured max(top pads) + max(content) + max(bottom pads) across the row
    (exp/pad3: a two-line cell with pads 0.7/2.0 beside a one-line cell with
    1.3/12.8 renders 36.6pt, not 24.7; a 0/2 cell beside a 12/2 one renders
    36.5, not 25.0). A one-line cell next to a wrapped one always carries a
    large bottom pad -- that is what makes the row's height add up -- so
    every such row grew by about that pad: on NIST SP 800-171's mapping
    tables, +12pt on most rows.

    With every cell sharing the row's smallest top and bottom gaps, and each
    cell's remaining top offset expressed as space-before, both renderers
    compute the same height: the tallest cell's content plus the shared
    pads, which is the source row. Cells merged down from a row (row_span >
    1) give up their bottom pad entirely -- their rows are sized by the
    cells that live in them -- and blank cells take the shared pads so they
    cannot raise the row's maxima.
    """
    out = []
    for rowspec in rows:
        row = list(rowspec)
        live = [c for c in row[:n_cols] if c is not None]
        texted = [c for c in live if max(1, getattr(c, "row_span", 1)) == 1
                  and len(c.pad) >= 4 and any(p.text.strip() for p in c.paras)]
        top = min((c.pad[0] for c in texted), default=0.0)
        bot = max(0.0, min((c.pad[2] for c in texted), default=0.0)
                  - _row_border_allowance(row))
        for ci, c in enumerate(row[:n_cols]):
            if c is None or len(c.pad) < 4:
                continue
            q = copy.copy(c)
            spanning = max(1, getattr(c, "row_span", 1)) > 1
            if c.paras and any(p.text.strip() for p in c.paras):
                lift = max(0.0, c.pad[0] - top)
                if lift > 0.05:
                    first = copy.copy(c.paras[0])
                    first.space_before = round((first.space_before or 0.0) + lift, 2)
                    q.paras = [first] + list(c.paras[1:])
            q.pad = (min(top, c.pad[0]), c.pad[1],
                     0.0 if spanning else min(bot, c.pad[2]), c.pad[3])
            row[ci] = q
        out.append(row)
    return out


def _merge_part_borders(borders: dict, first: bool, last: bool) -> dict:
    """One row's w:tc of a vertically merged cell: its sides, the merge's top
    edge on the first row only, its bottom edge on the last only -- so no
    renderer draws a rule across the inside of the merge."""
    b = dict(borders or {})
    if not first:
        b.pop("top", None)
    if not last:
        b.pop("bottom", None)
    return b


def _blank_cell(cell):
    par = cell.paragraphs[0]
    pf = par.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(2)
    r = par.add_run("")
    r.font.size = Pt(1)


def _size_mark_to_content(par, p):
    """Size a cell paragraph's mark to its content (defect catalogue #7).

    A table cell's last line box is the taller of the content and the
    paragraph MARK's box, and an unstyled mark inherits the template's
    default size -- an 11pt box under a 6.5pt cell value. Google Docs rounds
    every row box up to whole points, so each cell paragraph paid the
    difference and every row of a real report's tables measured 1-2pt
    taller than its source, compounding down a 14-row table until it
    spilled its page. The hand campaign's fitted model on that report was
    `row = 4.50 + (n-1)*10.54 + last-line box`: the mark IS the last-line
    box term. Sizing it to the paragraph's own content makes the last
    line's box the content's box.

    Cell paragraphs only, deliberately. Body paragraphs under the gdocs
    profile encode their line height as a multiple of the natural line,
    and NATURAL_FACTORS was calibrated with the mark at template defaults
    -- resizing body marks would move every line in every document away
    from the measured calibration.
    """
    if par is None:
        return
    size = max((r.size for r in p.runs if r.text and not r.is_tab), default=0)
    if size <= 0:
        return
    half = max(2, int(round(_quantised_size(size) * 2)))
    ppr = par._p.get_or_add_pPr()
    rpr = ppr.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        ppr.append(rpr)      # rPr is the last child pPr's schema allows
    for tag in ("w:sz", "w:szCs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = OxmlElement(tag)
            rpr.append(el)
        el.set(qn("w:val"), str(half))


def write_figure(container, fig: FigureEl, ctx=None, dpi: int = None,
                 page_break_before: bool = False, page=None):
    """Rasterise a figure region through the conversion's backend.

    `ctx.render_clip` replaces an open MuPDF document that used to be threaded
    down from `_write_docx`. A figure clip is a *rendering* operation, which the
    backend seam has always declared (`Backend.render_clip`) and which this writer
    was reaching around.

    Returns None if there is no renderer, and the caller then omits the figure --
    an honest empty space rather than a crash, and a warning once REL-01 lands.
    """
    ctx = ctx or _DEFAULT_CTX
    dpi = ctx.dpi if dpi is None else dpi
    if ctx.render_clip is None:
        return None
    data = ctx.render_clip(fig.page_no, fig.clip, dpi)
    if not data:
        # The renderer was there and produced nothing: a figure the caller
        # asked for and will not get. Tallied with the extracted rasters so
        # the conversion says so (design audit B28) -- it used to vanish. A
        # clip with no area is not one: it is a region built from ink beyond
        # the page (the PyMuPDF arm still reports a printer's slug, and its
        # figures come out inverted, y 0 to -74), and there is nothing to lose.
        x0, y0, x1, y1 = fig.clip
        if ctx.image_report is not None and x1 > x0 and y1 > y0:
            ctx.image_report["dropped"] = ctx.image_report.get("dropped", 0) + 1
        return None
    par = container.add_paragraph()
    pf = par.paragraph_format
    if page_break_before:
        pf.page_break_before = True
    pf.space_before = Pt(round(max(0.0, fig.space_before), 1))
    pf.space_after = Pt(0)
    par.alignment = ALIGN.get(fig.align, WD_ALIGN_PARAGRAPH.CENTER)
    if fig.align == "left" and fig.left_indent > 0.5:
        pf.left_indent = Pt(round(fig.left_indent, 1))
    return _picture_paragraph(par, data, fig.width, fig.height,
                              ctx.output_profile, page)


def _docx_accepts(data: bytes) -> bool:
    """Whether python-docx will embed these bytes, asked without a Document.

    python-docx matches a small signature table (`docx.image.SIGNATURES`) against
    the first 32 bytes and raises `UnrecognizedImageError` for anything outside
    it. Its JPEG entries are JFIF (`FF D8 FF E0`) and Exif (`FF D8 FF E1`) only,
    so an **Adobe APP14 JPEG** -- `FF D8 FF EE`, what Antenna House and the rest
    of the Adobe toolchain emit -- is a perfectly valid JPEG that python-docx
    refuses. `Image.from_blob` runs exactly that check plus the chosen header
    parser, so a truncated header of a *recognised* format is caught here too
    rather than midway through serialising the package.
    """
    from docx.image.image import Image as _DocxImage
    try:
        _DocxImage.from_blob(data)
        return True
    except Exception:
        return False


def _to_png(data: bytes):
    """Re-encode through Pillow to PNG, or None if Pillow cannot read it either.

    PNG rather than a re-saved JPEG on purpose: the source is already lossily
    encoded, and a second lossy pass would quietly degrade the pixels to work
    around a *container* problem. Pillow reads the Adobe-APP14 JPEG above fine;
    only the signature table objected.
    """
    try:
        from PIL import Image as _PILImage
    except ImportError:            # Pillow is not a hard dependency of the writer
        return None
    img = None
    try:
        img = _PILImage.open(io.BytesIO(data))
        img.load()
        if img.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
            # CMYK, I;16 and friends have no PNG representation.
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None
    finally:
        if img is not None:
            try:
                img.close()
            except Exception:
                pass


def _embeddable(data: bytes, report):
    """Bytes python-docx will take, or None -- and record which of the three.

    One image exactdoc cannot embed must never take the document down with it.
    `y06_irs_1040_instructions.pdf` is 126 pages of text carrying two Adobe-APP14
    JPEGs, and `add_picture` raising `UnrecognizedImageError` used to lose all
    126 pages rather than the two images.

    The ladder is: embed as extracted, else re-encode losslessly, else drop --
    and a drop is *counted*, not swallowed.
    """
    outcome, out = "embedded", data
    if not data:
        outcome, out = "dropped", None
    elif not _docx_accepts(data):
        png = _to_png(data)
        if png is not None and _docx_accepts(png):
            outcome, out = "reencoded", png
        else:
            outcome, out = "dropped", None
    if report is not None:
        report[outcome] = report.get(outcome, 0) + 1
    return out


# A picture this close to the paper in both dimensions IS the page (a designed
# cover, a scanned page kept as its image). Written inline it sits inside the
# margins: y28's 612x792 cover landed at (73.5, 39.6) in Google Docs, ran off
# the right and bottom edges, and its overflow pushed a blank page in front of
# the memo (LibreOffice did the same, at (81.1, 38.8)). Anchored behind text at
# the page origin it lands at (0, 0, 612, 792) in both, and the memo is back on
# page 2 (live, 2026-10-04; docs/evidence/gdocs-2026-10-04-cover-picture.json).
_FULL_PAGE_FRAC = 0.97


def _fills_page(w: float, h: float, page) -> bool:
    return page is not None and w >= _FULL_PAGE_FRAC * page[0] and \
        h >= _FULL_PAGE_FRAC * page[1]


def _anchor_behind_text(run, page, w: float, h: float):
    """Turn the run's inline picture into one anchored behind text, centred on
    the paper (a picture as large as the page sits at its origin)."""
    inline = run._r.find(".//" + qn("wp:inline"))
    if inline is None:
        return
    anchor = OxmlElement("wp:anchor")
    for k, v in (("distT", "0"), ("distB", "0"), ("distL", "0"), ("distR", "0"),
                 ("simplePos", "0"), ("relativeHeight", "0"), ("behindDoc", "1"),
                 ("locked", "0"), ("layoutInCell", "1"), ("allowOverlap", "1")):
        anchor.set(k, v)
    sp = OxmlElement("wp:simplePos")
    sp.set("x", "0")
    sp.set("y", "0")
    anchor.append(sp)
    for tag, off in (("wp:positionH", (page[0] - w) / 2.0),
                     ("wp:positionV", (page[1] - h) / 2.0)):
        pos = OxmlElement(tag)
        pos.set("relativeFrom", "page")
        po = OxmlElement("wp:posOffset")
        po.text = str(int(round(off * 12700)))
        pos.append(po)
        anchor.append(pos)
    # schema order after the position: extent, effectExtent?, wrap*, docPr,
    # cNvGraphicFramePr?, graphic
    children = list(inline)
    for ch in children:
        if ch.tag == qn("wp:extent"):
            anchor.append(ch)
    anchor.append(OxmlElement("wp:wrapNone"))
    for ch in children:
        if ch.tag != qn("wp:extent"):
            anchor.append(ch)
    inline.getparent().replace(inline, anchor)


def _picture_paragraph(par, data: bytes, w: float, h: float, profile: str,
                       page=None):
    """Add the picture to `par`, inline -- or, when it fills the page, anchored
    behind text in a paragraph that takes no room of its own."""
    pf = par.paragraph_format
    r = par.add_run()
    r.add_picture(io.BytesIO(data), width=Emu(int(w * 12700)),
                  height=Emu(int(h * 12700)))
    if _fills_page(w, h, page):
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pf.line_spacing = Pt(1)
        _anchor_behind_text(r, page, w, h)
    elif profile != "gdocs":
        # Word/LibreOffice need this guard for a paragraph containing only an
        # inline drawing.  Google Docs reserves the inline drawing itself and
        # treats the duplicate atLeast height as extra page-flow pressure.
        pf.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
        pf.line_spacing = Pt(round(h, 1))
    return par


def write_image(container, im: ImageEl, ctx=None,
                page_break_before: bool = False, page=None):
    """Place an extracted raster. Returns None when the image had to be dropped.

    Returning None so the caller omits the element is `write_figure`'s contract
    for a visual it cannot produce, and this follows it: an honest empty space,
    tallied in `ctx.image_report`, rather than a crash. `page` is the paper
    (w, h) in pt, so a picture that fills it can be placed on it.
    """
    ctx = ctx or _DEFAULT_CTX
    data = _embeddable(im.data, ctx.image_report)
    if data is None:
        return None
    par = container.add_paragraph()
    pf = par.paragraph_format
    if page_break_before:
        pf.page_break_before = True
    pf.space_before = Pt(round(max(0.0, im.space_before), 1))
    pf.space_after = Pt(0)
    par.alignment = ALIGN.get(im.align, WD_ALIGN_PARAGRAPH.CENTER)
    if im.align == "left" and im.left_indent > 0.5:
        pf.left_indent = Pt(round(im.left_indent, 1))
    return _picture_paragraph(par, data, im.width, im.height,
                              ctx.output_profile, page)


def write_rule(container, rule: RuleEl, content_w: float,
               page_break_before: bool = False):
    par = container.add_paragraph()
    pf = par.paragraph_format
    if page_break_before:
        pf.page_break_before = True
    pf.space_before = Pt(round(max(0.0, rule.space_before), 1))
    pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(2)
    length = rule.length or (content_w * rule.width_pct / 100.0)
    if rule.left_indent > 0.5:
        pf.left_indent = Pt(round(rule.left_indent, 1))
    ri = content_w - rule.left_indent - length
    if ri > 0.5:
        pf.right_indent = Pt(round(ri, 1))
    r = par.add_run("")
    r.font.size = Pt(1)
    ppr = par._p.get_or_add_pPr()
    _set_borders(ppr, {"bottom": (rule.thickness, rule.color)}, "w:pBdr")
    return par


# ------------------------------------------------------------------ sections
def _part_distance(lay: DocLayout, side: str) -> float:
    """The w:pgMar header/footer distance: the document's default part's, else
    the first part of that side any section states (a manual whose only head
    is its chapter title has no default part), else Word's 0.5in."""
    parts = [getattr(lay, side + "_default"), getattr(lay, side + "_even")]
    for s in lay.hf_sections:
        if s.parts:
            parts += [s.parts.get(side), s.parts.get(side + "_even")]
    return next((p.distance for p in parts if p is not None), 36.0)


def _config_section(sec, lay: DocLayout, margin_t=None, cols: int = 1,
                    col_gap: float = 24.0, margin_lr=None):
    sec.page_width = Emu(int(lay.page_w * 12700))
    sec.page_height = Emu(int(lay.page_h * 12700))
    # Stated, not inferred from the size: Word prints by w:orient, and a new
    # section inherits the previous one's. Portrait is the schema default and
    # writes no attribute, so a portrait document's sections are unchanged.
    sec.orientation = WD_ORIENT.LANDSCAPE if lay.page_w > lay.page_h \
        else WD_ORIENT.PORTRAIT
    ml = lay.margin_l if margin_lr is None else margin_lr
    mr = lay.margin_r if margin_lr is None else margin_lr
    sec.left_margin = Emu(int(ml * 12700))
    sec.right_margin = Emu(int(mr * 12700))
    sec.top_margin = Emu(int((lay.margin_t if margin_t is None else margin_t) * 12700))
    sec.bottom_margin = Emu(int(lay.margin_b * 12700))
    hd = _part_distance(lay, "header")
    fd = _part_distance(lay, "footer")
    sec.header_distance = Emu(int(max(0.0, hd) * 12700))
    sec.footer_distance = Emu(int(max(0.0, fd) * 12700))
    sectPr = sec._sectPr
    cols_el = sectPr.find(qn("w:cols"))
    if cols_el is None:
        cols_el = OxmlElement("w:cols")
        sectPr.append(cols_el)
    if cols > 1:
        cols_el.set(qn("w:num"), str(cols))
        cols_el.set(qn("w:space"), str(int(round(col_gap * 20))))
        cols_el.set(qn("w:equalWidth"), "1")
    else:
        cols_el.set(qn("w:num"), "1")
        for a in ("w:space", "w:equalWidth"):
            if cols_el.get(qn(a)):
                cols_el.attrib.pop(qn(a))


# w:sectPr children that must FOLLOW w:pgNumType (ECMA-376 CT_SectPr order).
_AFTER_PGNUM = ("w:cols", "w:formProt", "w:vAlign", "w:noEndnote", "w:titlePg",
                "w:textDirection", "w:bidi", "w:rtlGutter", "w:docGrid",
                "w:printerSettings", "w:sectPrChange")


def _set_page_numbering(sec, start: Optional[int], fmt: Optional[str]):
    """State a section's page numbering: `w:pgNumType w:start w:fmt`.

    `start` None continues the count from the previous section. The format is
    always written explicitly once numbering is managed, because python-docx's
    `add_section` clones the previous section's sectPr into the new one, and a
    roman front-matter format would otherwise silently carry into the body.
    """
    sp = sec._sectPr
    el = sp.find(qn("w:pgNumType"))
    if el is None:
        el = OxmlElement("w:pgNumType")
        nxt = next((c for c in sp if c.tag in {qn(t) for t in _AFTER_PGNUM}), None)
        if nxt is not None:
            nxt.addprevious(el)
        else:
            sp.append(el)
    el.set(qn("w:fmt"), fmt or "decimal")
    if start is None:
        el.attrib.pop(qn("w:start"), None)
    else:
        el.set(qn("w:start"), str(int(start)))


def _continue_numbering(sec):
    """A section opened for any other reason (a column change) continues the
    count: drop the restart python-docx's sectPr clone copied from the last one."""
    el = sec._sectPr.find(qn("w:pgNumType"))
    if el is not None:
        el.attrib.pop(qn("w:start"), None)


def _fill_default_parts(sec, lay: DocLayout, ctx, blank: bool = False,
                        always: bool = False):
    """Write a section's own default (and, under evenAndOddHeaders, even)
    header and footer, for the sides the document has. `blank` writes them
    empty; `always` also writes an empty part for a side the document lacks
    (the cover path's historical form, kept byte-identical)."""
    for part, obj in ((lay.header_default, sec.header),
                      (lay.footer_default, sec.footer)):
        if part is None and not always:
            continue
        _fill_hf(obj, None if blank else part, lay, ctx=ctx)
    _fill_even_parts(sec, lay, ctx, blank)


def _fill_even_parts(sec, lay: DocLayout, ctx, blank: bool = False):
    """Even-page parts under w:evenAndOddHeaders, for the sides that have
    furniture at all: an empty even part beside an absent default one is the
    same LibreOffice page-style mismatch `_fill_first_page_parts` avoids."""
    if not lay.even_odd:
        return
    for even, default, obj in ((lay.header_even, lay.header_default,
                                sec.even_page_header),
                               (lay.footer_even, lay.footer_default,
                                sec.even_page_footer)):
        if even is None and default is None:
            continue
        _fill_hf(obj, None if blank else (even or default), lay, ctx=ctx)


def _fill_first_page_parts(sec, lay: DocLayout, ctx):
    """The first-page header and footer under w:titlePg, written so that
    LibreOffice's page styles stay consistent with the default ones.

    Measured in the canonical LibreOffice (probe: 140 exact-12pt lines, a 36pt
    header/footer distance): a first-page footer with NO default footer beside
    it costs every later page two lines -- the body bottom rises from 753.6 to
    729.6 -- and a first-page header with no default header pushes every
    page's body top from 58 to 72pt. A side with neither part therefore gets no
    reference at all (that measured exactly like no footer), and a side whose
    first page states something the other pages do not gets an empty default
    part beside it (one line, not two). Page 1 states its own footer,
    including none: inference no longer substitutes the default footer for a
    folio-less cover page.
    """
    for first, default, first_obj, default_obj in (
            (lay.header_first, lay.header_default,
             sec.first_page_header, sec.header),
            (lay.footer_first, lay.footer_default,
             sec.first_page_footer, sec.footer)):
        if first is None and default is None:
            continue
        _fill_hf(first_obj, first, lay, ctx=ctx)
        if first is not None and default is None:
            _fill_hf(default_obj, None, lay, ctx=ctx)


def _fill_section_parts(sec, lay: DocLayout, ctx, spec):
    """A running-head section's own parts (`HFSection.parts`), written for the
    sides the document has; under w:titlePg its chapter-opener page gets the
    first-page parts. Same page-style rules as section 1: no side the document
    lacks is given a reference, and every first or even part has its default
    beside it."""
    parts = spec.parts or {}
    sides = (("header", sec.header, sec.even_page_header, sec.first_page_header,
              lay.header_default),
             ("footer", sec.footer, sec.even_page_footer, sec.first_page_footer,
              lay.footer_default))
    for name, obj, even_obj, first_obj, doc_default in sides:
        mine = [parts.get(name), parts.get(name + "_even"),
                parts.get(name + "_first")]
        if doc_default is None and all(p is None for p in mine):
            continue
        _fill_hf(obj, parts.get(name), lay, ctx=ctx)
        if lay.even_odd:
            _fill_hf(even_obj, parts.get(name + "_even") or parts.get(name),
                     lay, ctx=ctx)
        if spec.title_pg:
            _fill_hf(first_obj, parts.get(name + "_first"), lay, ctx=ctx)
    if spec.title_pg:
        sec.different_first_page_header_footer = True


def _page_geometry(lay: DocLayout, pg: PageLayout) -> DocLayout:
    """`lay` with a page's own paper and margins, or `lay` itself.

    Inference gives a page whose size differs from page 1's its own geometry
    (PageLayout.page_w/page_h/margins); every page of the document's size
    answers with `lay` itself, so a uniform document writes exactly as before.
    """
    if pg.page_w is None or pg.page_h is None:
        return lay
    out = dataclasses.replace(lay, page_w=pg.page_w, page_h=pg.page_h)
    if pg.margins is not None:
        out.margin_l, out.margin_r, out.margin_t, out.margin_b = pg.margins
    return out


def _geometry_key(lay: DocLayout):
    return tuple(round(v, 1) for v in (lay.page_w, lay.page_h, lay.margin_l,
                                        lay.margin_r, lay.margin_t, lay.margin_b))


def _shifted_part(part: Optional[HFPart], dl: float, dr: float) -> Optional[HFPart]:
    """Clone a header/footer part with indents/tabs shifted (bleed sections)."""
    if part is None:
        return None
    import copy
    np = copy.deepcopy(part)
    for el in np.elements:
        if isinstance(el, Para):
            el.left_indent = round(el.left_indent + dl, 1)
            el.right_indent = round((el.right_indent or 0.0) + dr, 1)
            el.tab_stops = _shift_tabs(el.tab_stops, dl)
        elif isinstance(el, TableEl):
            el.left_indent = round(el.left_indent + dl, 1)
    return np


def _fill_hf(hf_obj, part: Optional[HFPart], lay: DocLayout, ctx=None):
    """Fill a python-docx header/footer object with an HFPart."""
    ctx = ctx or _DEFAULT_CTX
    hf_obj.is_linked_to_previous = False
    # clear default paragraph content
    first = hf_obj.paragraphs[0]
    first.clear()
    if part is None or not part.elements:
        pf = first.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pf.line_spacing = Pt(2)
        return
    used_first = False
    for el in part.elements:
        if isinstance(el, TableEl):
            write_table(hf_obj, el, lay.content_w, ctx=ctx)
        elif isinstance(el, Para):
            if not used_first:
                write_para(hf_obj, el, lay.content_w, par=first, ctx=ctx)
                used_first = True
            else:
                write_para(hf_obj, el, lay.content_w, ctx=ctx)
        elif isinstance(el, RuleEl):
            write_rule(hf_obj, el, lay.content_w)
    if not used_first:
        # first paragraph unused: make it invisible
        pf = first.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pf.line_spacing = Pt(2)


# ------------------------------------------------------------------ main
def write_docx(lay: DocLayout, out_path: str, dpi: int = 240,
               output_profile: str = "standard", backend=None, ctx=None,
               image_report=None, clip_cache=None) -> str:
    """Render a DocLayout to a .docx. Pure: `lay` is never modified.

    `output_profile` selects the line-height encoding: Word and LibreOffice
    honour lineRule="exact", Google Docs mistranslates it in a way that scales
    with font size, so the gdocs profile emits the same intent as a multiple
    instead. That choice now travels in a `WriteCtx` rather than in a module
    global that this function set and restored -- two concurrent conversions with
    different profiles could each observe the other's encoding.

    This is a pure serialisation setting. It writes different bytes; it does not
    contact anything. Choosing the Google-safe profile costs no network, no
    credentials and no upload.

    `backend` supplies figure rasterisation. Pass the same backend the parse used;
    without one, figure regions are omitted rather than rendered through a parser
    nobody selected. This is what removed `import fitz` from the top of this
    module, and with it the reason a wheel installed without PyMuPDF could not
    write a DOCX at all.

    The cover-band path shifts every page-1 element by the bleed delta, and
    those shifts are *accumulating* assignments (`el.left_indent + delta_l`,
    `c.pad[1] + delta_l`). Writing the same layout twice therefore used to
    double-shift the second document — silently, and only on cover-band
    documents, which is why it survived: 2 of 16 corpus documents were not
    reproducible on a second write. Callers must not have to know this, so the
    copy lives here and purity is part of the contract, verified by
    tests/test_purity.py.

    `image_report`, when given, is cleared and refilled with this write's raster
    tally (`embedded`/`reencoded`/`dropped`). Cleared rather than accumulated
    because the refine loop writes the same layout once per round, and a ledger
    that summed over rounds would report four dropped images for one.

    `clip_cache`, when given, is a dict that keeps rasterised figure clips
    between writes. The refine loop writes one layout up to four times and its
    corrections never move a clip, so each figure is rasterised once rather
    than once per round. The bytes are the backend's own output either way.
    """
    if image_report is not None:
        image_report.clear()
    if ctx is not None:
        return _write_docx(lay, out_path, ctx)
    render_clip, session = None, None
    if backend is not None and lay.src_path:
        # One open document for the whole write when the backend offers it
        # (design audit B28: y06 opened its PDF 117 times, once per clip).
        opener = getattr(backend, "clip_renderer", None)
        if opener is not None:
            try:
                session = opener(lay.src_path)
            except Exception:
                session = None

        def render_clip(page_no, clip, at_dpi, _bk=backend, _p=lay.src_path,
                        _s=session):
            # Across refine rounds the same clips are asked for again; the
            # caller's cache answers them without rasterising twice.
            key = (page_no, tuple(clip), at_dpi)
            if clip_cache is not None and key in clip_cache:
                return clip_cache[key]
            try:
                if _s is not None:
                    data = _s.render_clip(page_no, clip, dpi=at_dpi)
                else:
                    data = _bk.render_clip(_p, page_no, clip, dpi=at_dpi)
            except Exception:
                data = None
            if clip_cache is not None:
                clip_cache[key] = data
            return data
    ctx = WriteCtx(output_profile=output_profile,
                   line_mode=line_mode_for(output_profile), dpi=dpi,
                   render_clip=render_clip, image_report=image_report)
    try:
        return _write_docx(lay, out_path, ctx)
    finally:
        if session is not None:
            session.close()


# Families that need something other than the default proportional-serif
# description in the font table. Everything else is described by its class in
# the family table (`fonts.font_table_desc`), and a family the table does not
# know gets `auto`/`variable`, which is what Word itself writes for a family it
# has no metrics opinion about.
_FONT_DESC = {
    "Courier New": ("modern", "fixed"),
    "Consolas": ("modern", "fixed"),
    "Arial": ("swiss", "variable"),
    "Verdana": ("swiss", "variable"),
    "Tahoma": ("swiss", "variable"),
    "Trebuchet MS": ("swiss", "variable"),
    "Times New Roman": ("roman", "variable"),
    "Georgia": ("roman", "variable"),
    "Symbol": ("decorative", "variable"),
}


def _restyle_outline_styles(doc):
    """Strip the stock Heading styles down to pure outline metadata.

    Google Docs' outline sidebar and style dropdown key on the paragraph
    STYLE: a converted document carrying only `w:outlineLvl` showed "Normal
    text" everywhere and an empty outline, whatever Word's navigation pane
    said. So headings are named `Heading 1..6` -- and then the style must
    carry no visual payload of its own, or every heading in every converted
    document would inherit the stock template's blue Cambria look through
    whatever direct formatting happens not to name a property.

    The stock style elements keep `w:name`, `w:styleId`, `w:basedOn` Normal,
    `w:next` and `w:qFormat` -- everything a reader needs to call the
    paragraph a heading -- and their `w:pPr`/`w:rPr` are replaced with an
    explicit zero: spacing 0/0, single line. An ABSENT pPr is not a zero
    pPr: LibreOffice maps the style name "heading 1" onto its own built-in
    style and supplied that style's 0.2in-above default wherever the
    imported definition was silent, which moved a gated document's raw-lane
    dy_p50 6.83 -> 8.43pt through a render whose input differed by nothing
    but the style name. Naming the zeros closes that door; with them, the
    paragraph's direct formatting is the only remaining source of visual
    truth, which is exactly what the measured layout expects.
    """
    for i in range(1, 7):
        try:
            st = doc.styles["Heading %d" % i]
        except KeyError:
            continue
        el = st.element
        for tag in ("w:pPr", "w:rPr"):
            node = el.find(qn(tag))
            if node is not None:
                el.remove(node)
        ppr = OxmlElement("w:pPr")
        # schema order: keepNext precedes spacing
        keep = OxmlElement("w:keepNext")
        ppr.append(keep)
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:before"), "0")
        sp.set(qn("w:after"), "0")
        sp.set(qn("w:line"), "240")
        sp.set(qn("w:lineRule"), "auto")
        ppr.append(sp)
        el.append(ppr)


def _declare_fonts(doc):
    """Declare the families this document actually uses, and stop inheriting Cambria.

    python-docx builds every document from one stock template, and that template's
    `word/fontTable.xml` lists Symbol, Times New Roman, Cambria, Calibri, Courier,
    Arial and two Japanese faces -- a set that has nothing to do with the document
    being written. It is identical in every file this converter has ever produced,
    including the two Japanese faces no fixture uses. Meanwhile `docDefaults`
    carries theme references (`minorHAnsi`), the `Normal` style names no font at
    all, and the theme resolves minor to Cambria and major to Calibri.

    So a converted document could emit a family on 116 runs that the file never
    declares anywhere, over defaults pointing at a font the source never used.
    That was measured on a real resume whose body was Georgia: every run said
    Georgia, the font table did not mention it, and the reader was left to decide.
    The control document in the same pair had a Times New Roman body -- a family
    the stock table happens to list -- and came back visibly better.

    WHAT THIS DOES AND DOES NOT CLAIM. Declaring a family is correct OOXML
    regardless of what any particular reader does with it: a font table that
    contradicts the runs is wrong on its own terms. Whether Google Docs
    substitutes *because* of the missing declaration is a HYPOTHESIS, consistent
    with those two documents and not yet graded by a live contact. It is written
    up as a hypothesis in docs/ and stays one until the next live pass grades it.
    The fix is worth making either way, which is exactly why it should not be sold
    on the strength of the unproven half.
    """
    from lxml import etree

    body = doc.element.body
    used = {}
    east = set()
    for rf in body.iter(qn("w:rFonts")):
        name = rf.get(qn("w:ascii")) or rf.get(qn("w:hAnsi"))
        if name:
            used[name] = used.get(name, 0) + 1
        ea = rf.get(qn("w:eastAsia"))
        if ea and ea != name:
            east.add(ea)
    if not used:
        return
    dominant = max(sorted(used), key=lambda k: used[k])

    pkg = doc.part.package

    def part_named(suffix):
        for p in pkg.iter_parts():
            if str(p.partname).endswith(suffix):
                return p
        return None

    # 1. the font table must name every family the runs name
    ft = part_named("fontTable.xml")
    if ft is not None:
        try:
            root = etree.fromstring(ft.blob)
            have = {f.get(qn("w:name")) for f in root.findall(qn("w:font"))}
            for name in sorted((set(used) | east) - {None} - have):
                # The explicit table first (its entries predate the family
                # table and are byte-stable); otherwise the family's class --
                # a Word reader without the face substitutes by family and
                # pitch, so a missing monospace face is at least replaced by
                # a monospace one.
                fam, pitch, charset = font_table_desc(name)
                if name in _FONT_DESC:
                    fam, pitch = _FONT_DESC[name]
                el = etree.SubElement(root, qn("w:font"))
                el.set(qn("w:name"), name)
                for tag, val in (("w:charset", charset), ("w:family", fam),
                                 ("w:pitch", pitch)):
                    etree.SubElement(el, qn(tag)).set(qn("w:val"), val)
            ft._blob = etree.tostring(root, xml_declaration=True,
                                      encoding="UTF-8", standalone=True)
        except Exception:
            pass

    # 2. the defaults must name a real family rather than a theme slot. Both are
    #    set: docDefaults is what an empty run inherits, and Normal is what every
    #    paragraph style inherits from, and a reader may consult either.
    try:
        styles = doc.styles.element
        dd = styles.find(qn("w:docDefaults"))
        if dd is not None:
            rpr = dd.find(qn("w:rPrDefault"))
            if rpr is not None:
                rp = rpr.find(qn("w:rPr"))
                if rp is not None:
                    rf = rp.find(qn("w:rFonts"))
                    if rf is None:
                        rf = etree.SubElement(rp, qn("w:rFonts"))
                    for themed in ("w:asciiTheme", "w:hAnsiTheme",
                                   "w:eastAsiaTheme", "w:cstheme"):
                        if rf.get(qn(themed)) is not None:
                            del rf.attrib[qn(themed)]
                    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
                        rf.set(qn(attr), dominant)
        for st in styles.findall(qn("w:style")):
            if st.get(qn("w:styleId")) != "Normal":
                continue
            rp = st.find(qn("w:rPr"))
            if rp is None:
                rp = etree.SubElement(st, qn("w:rPr"))
            rf = rp.find(qn("w:rFonts"))
            if rf is None:
                rf = etree.Element(qn("w:rFonts"))
                rp.insert(0, rf)
            for themed in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme",
                           "w:cstheme"):
                if rf.get(qn(themed)) is not None:
                    del rf.attrib[qn(themed)]
            for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
                rf.set(qn(attr), dominant)
    except Exception:
        pass

    # 3. and the theme's own latin faces, so anything still resolving through
    #    minorHAnsi lands on this document's font instead of Cambria
    th = part_named("theme1.xml")
    if th is not None:
        try:
            a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
            root = etree.fromstring(th.blob)
            for which in ("majorFont", "minorFont"):
                el = root.find(".//" + a + which + "/" + a + "latin")
                if el is not None:
                    el.set("typeface", dominant)
            th._blob = etree.tostring(root, xml_declaration=True,
                                      encoding="UTF-8", standalone=True)
        except Exception:
            pass


# Largest gap a joined page may carry into a merged flow (see
# `_merge_grid_page_runs.cap_join_gaps`). A page-RELATIVE offset -- the
# distance from a page's content to its bottom-pinned tail, or from its
# top to its first line -- is not a content relationship.
_JOIN_GAP_CAP_PT = 48.0


# A rigid element (table, figure, image) wider than this cannot live in a
# booklet column (~165pt on a letter-page 3-col grid; 1.5x that is the span
# test's own bar). Paragraphs wrap; these do not.
_RIGID_SPAN_PT = 240.0


def _carries_rigid_spanning_element(pg) -> bool:
    """Does this page hold a table/figure too wide for a booklet column?

    Paragraphs re-wrap inside a column flow, so spanning TEXT is the
    documented, survivable tail trade. A spanning TABLE cannot wrap: joined
    into a run it renders across the neighbouring columns and their text."""
    for c in pg.chunks:
        for el in c.elements:
            if isinstance(el, (Para, ColBreak)):
                continue
            bb = getattr(el, "bbox", None) or getattr(el, "clip", None)
            if bb is not None and (bb[2] - bb[0]) > _RIGID_SPAN_PT:
                return True
    return False


def _is_booklet(pages) -> bool:
    """The booklet signature: the document's pages are dominated by real
    >=3-column grids (>= 10 such pages and >= 35% of the document).

    The scope key for every flow behavior in this module. The gated corpus
    carries no >=3-col page at all, so nothing gated can enter these paths
    -- which is what makes page-seam removal safe to ship: the page-exact
    reconstruction the gate certifies is defined by those seams."""
    if not pages:
        return False
    n3 = sum(1 for pg in pages if any(c.n_cols >= 3 for c in pg.chunks))
    return n3 >= 10 and n3 >= 0.35 * len(pages)


def _merge_grid_page_runs(pages):
    """Merge runs of consecutive same-shape pages into one page each.

    Measured on the IRS booklets: the per-source-page ladder of sections --
    lead(1-col), grid(3-col), tail(1-col) -- costs two to three section
    boxes per source page, and the renderer does not refill the leftover
    space (y06's first map: 123 of 298 export pages carried fewer than 40
    rows while wrapping, pitch and volume were all correct). A run of
    consecutive pages that each carry exactly one multi-column grid of the
    same width becomes ONE synthetic page: the first page's lead keeps its
    own 1-col section, and every later page's lead and the previous page's
    tail join the grid's flow in reading order (tail before the next
    lead). A tail that spans the page renders in column width instead --
    the trade that buys natural page fill, and booklet tails are furniture
    (page pointers, continuation notes), not layout.

    The first attempt at this was a WASH (y06 -24, y13 +4) and was
    reverted -- because at that time the grid detection itself was
    rejecting most of these pages (spanning notes crossing gutters at
    4-7%), so runs never formed: of y06's 126 pages only 9 carried
    detected grids. With the narrow-line gutter scan, 61 do, and the runs
    this merge needs actually exist.

    **The booklet scope, and 1-col runs.** After the grid runs formed, the
    measured residual inflation (y06 still 126 -> 226) was NOT wrapping or
    pitch -- the export carries the same text in FEWER lines (36,090
    against the source's 40,752; dehyphenation packs tighter) at exactly
    the source pitch (11.5pt = 11.5pt) -- it was the pages BETWEEN the
    grid runs: the booklet's 2-col worksheet pages and its sparse 1-col
    pages, each still carrying its own page seam. A document whose pages
    are dominated by >=3-col grids (the booklet signature: >= 10 such
    pages and >= 35% of the document) therefore also merges runs of
    consecutive all-1-col pages into one flowing page. The all-1-col
    content stays in its own 1-col section -- this only drops the page
    seams inside the run, it never feeds full-width content into columns
    (that trade, measured as a disaster, is what killed the 0.62 wide-tail
    threshold). Documents without the booklet signature -- the gated
    corpus carries no >=3-col page at all -- keep every page seam, so the
    page-exact reconstruction the gate certifies is untouched.

    Deliberately NOT merged: pages whose grids differ in column count, and
    any page with more than one multi-column chunk -- their ladders are
    structure, not repetition.
    """
    booklet = _is_booklet(pages)

    def cap_join_gaps(chunks_els):
        """Everything a JOINED page contributes to a run keeps gaps at most
        _JOIN_GAP_CAP_PT. Measured on y06: the fabricated dead space in the
        first merged render was 18,300pt (27 pages' worth) beyond the
        source's own whitespace, and it decomposed exactly into page-
        relative offsets -- the distance from a page's last content to its
        bottom-pinned tail ("Need more information..."), and the page-top
        offset of a joined lead. In the source those distances were
        absorbed by the page break; in a flow they render as gaps. Real
        inter-paragraph gaps never come near the cap; the run's FIRST page
        keeps its own geometry (it starts the section)."""
        for els in chunks_els:
            for el in els:
                sb = getattr(el, "space_before", None)
                if sb is not None and sb > _JOIN_GAP_CAP_PT:
                    el.space_before = _JOIN_GAP_CAP_PT

    def shape_of(pg):
        """1 for an all-1-col page (booklet only), else its single
        multi-col chunk's column count, else None (not a run member)."""
        multis = [c for c in pg.chunks if c.n_cols >= 2]
        if len(multis) > 1 or pg.continuation_only:
            return None
        if multis:
            if booklet and _carries_rigid_spanning_element(pg):
                # A page holding a table or figure wider than a booklet
                # column is STRUCTURE, not repetition: run membership would
                # pull that rigid element into the column flow, and a
                # table cannot wrap -- it renders across the neighbouring
                # columns and their text. Measured on y06's source p99: a
                # 405pt worksheet table spanning a genuinely hybrid page
                # (full-width worksheet over 3-col instructions), colliding
                # with column text on 6 rendered pages.
                return None
            return multis[0].n_cols
        return 1 if booklet else None

    out, i = [], 0
    n = len(pages)
    while i < n:
        pg = pages[i]
        key = shape_of(pg)
        if key is None:
            out.append(pg)
            i += 1
            continue
        run = [pg]
        j = i + 1
        # A run never crosses a change of paper: the writer must open a
        # NEW_PAGE section there (see _page_geometry).
        while j < n and shape_of(pages[j]) == key and                 _paper(pages[j]) == _paper(pg):
            run.append(pages[j])
            j += 1
        if len(run) == 1:
            out.append(pg)
            i = j
            continue
        if key == 1:
            # all-1-col run: one flowing page, chunks concatenated; the
            # dropped page seams are the entire point
            for rp in run[1:]:
                cap_join_gaps([c.elements for c in rp.chunks])
            merged = PageLayout(number=pg.number,
                                chunks=[c for rp in run for c in rp.chunks],
                                page_w=pg.page_w, page_h=pg.page_h,
                                margins=pg.margins)
            out.append(merged)
            i = j
            continue
        grid = next(c for c in pg.chunks if c.n_cols >= 2)
        merged_grid = Chunk(n_cols=grid.n_cols, col_gap=grid.col_gap,
                            pre_gap=grid.pre_gap)
        first_chunks = None
        tail_prev = None
        for rp in run:
            gi = next(k for k, c in enumerate(rp.chunks) if c.n_cols >= 2)
            lead, g, tail = rp.chunks[:gi], rp.chunks[gi], rp.chunks[gi + 1:]
            if first_chunks is None:
                first_chunks = lead          # keeps its own 1-col sections
            else:
                # the seam: previous tail, then this lead, join the flow;
                # both carry page-relative gaps that a flow must not render
                cap_join_gaps([c.elements for c in tail_prev + lead])
                merged_grid.elements.extend(
                    el for c in tail_prev + lead for el in c.elements)
            # Column breaks are dropped in the merge: they encode each
            # source page's own column boundaries, and inside a merged
            # multi-page flow they fire at flow positions instead, one
            # page's drift compounding down the run (the measured y13
            # regression of the first attempt). Natural fill puts each
            # source column's content -- which is a page-height of text --
            # into the corresponding column of the flow.
            merged_grid.elements.extend(
                el for el in g.elements if not isinstance(el, ColBreak))
            tail_prev = tail
        # the final run member's tail joins too, after its grid, under the
        # same cap: its bottom-pinned distance is as page-relative as any
        cap_join_gaps([c.elements for c in tail_prev])
        merged_grid.elements.extend(el for c in tail_prev for el in c.elements)
        new_chunks = list(first_chunks) + [merged_grid]
        out.append(PageLayout(number=run[0].number, chunks=new_chunks,
                              page_w=pg.page_w, page_h=pg.page_h,
                              margins=pg.margins))
        i = j
    return out


def _script_base_sizes(lay: DocLayout) -> int:
    """Give each superscript run the size of the text it is raised against.

    `vertAlign=superscript` means "shrink and raise": Word and LibreOffice
    render the run at roughly 0.6x its own `w:sz` (LibreOffice 58%). Every
    script run carried the size it was DRAWN at, which is already the shrunk
    size, so the renderer shrank it a second time: EUR-Lex footnote markers
    drawn at 4.93pt (0.58 of the body) wrote `sz=10` and rendered near 3pt, a
    dot in brackets; 13 of 32 real documents carried such runs (FIPS 180 939,
    1040 instructions 347, Pub 501 166, lshort 158). This is how Word itself
    writes a superscript: the line's size, with vertAlign doing the shrink.
    Censused, the drawn script/host ratios are 0.58-0.73, so the renderer's
    own ratio lands within a few tenths of a point of the source.

    The host is the nearest non-script run with text, before the script, else
    after it. A script with no host in its paragraph, or one already drawn at
    its host's size, has nothing to be shrunk against: it keeps the size it was
    drawn at and loses only the raise, rather than shrinking to illegibility.
    """
    from .layout import iter_paras

    def inked(r):
        return not r.superscript and not r.is_tab and bool(r.text.strip())
    n = 0
    for p in iter_paras(lay):
        runs = p.runs
        for i, r in enumerate(runs):
            if not r.superscript or not r.text.strip():
                continue
            host = next((h for h in reversed(runs[:i]) if inked(h)), None) or \
                next((h for h in runs[i + 1:] if inked(h)), None)
            if host is not None and host.size > 1.05 * r.size:
                r.size = host.size
            else:
                r.superscript = False
            n += 1
    return n


def _paper(pg: PageLayout):
    """A page's own geometry, as inference recorded it (None: the document's)."""
    return (pg.page_w, pg.page_h, pg.margins)


def _write_docx(lay: DocLayout, out_path: str, ctx: WriteCtx) -> str:
    src_lay = lay
    lay = copy.deepcopy(lay)
    lay.pages = _merge_grid_page_runs(lay.pages)
    # After the deepcopy: the plan marks the elements this function will write.
    dest_anchors, anchor_ids = _plan_bookmarks(lay)
    if dest_anchors or anchor_ids:
        ctx = dataclasses.replace(ctx, dest_anchors=dest_anchors,
                                  anchor_ids=anchor_ids)
    if ctx.output_profile == "gdocs":
        # Substitute fonts whose measured advance width does not match the
        # source's, and track out what remains, so paragraphs wrap where they
        # wrapped in the PDF. Safe here: the layout above is already a copy,
        # and this rewrites run properties only -- never element identity, so
        # the bookmark plan above stays valid.
        from .gdocs_metrics import apply_metric_fit
        apply_metric_fit(lay)
    else:
        # Same safety argument: run properties on the copy only. Not under the
        # gdocs profile -- Google Docs' own superscript ratio is unmeasured,
        # and that profile changes only on live evidence.
        _script_base_sizes(lay)
    # Real lists and real notes, where the profile writes them (options.py).
    # Planned before anything is written: a list or a note that cannot be
    # written whole is written typed, never half-converted.
    from .structures import footnote_plan, numbering_plan
    if ctx.numbering and lay.lists:
        ctx = dataclasses.replace(ctx, list_defs=numbering_plan(
            lay, tab_only=ctx.output_profile == "gdocs"))
    note_ids = footnote_plan(lay) if ctx.footnotes and not ctx.notes_vetoed \
        else {}
    if note_ids:
        ctx = dataclasses.replace(ctx, note_ids=note_ids)
        # A link whose destination was the note text at the page foot (EUR-Lex
        # links every "(¹)" to its note) would point at a bookmark on a
        # paragraph no longer in the body; its text is written plain, beside
        # the footnote reference that now does that job.
        gone = {getattr(el, "_bookmark", None) for pg in lay.pages
                for ch in pg.chunks for el in ch.elements
                if getattr(el, "role", "") == "footnote"} - {None}
        if gone:
            ctx = dataclasses.replace(ctx, dest_anchors={
                d: n for d, n in ctx.dest_anchors.items() if n not in gone})
    # {source page: height of the footnote area its notes occupy}
    notes_h = {}
    if note_ids:
        from .notes import footnote_areas
        notes_h = footnote_areas(
            lay, lambda pl: _body_foot(_page_geometry(lay, pl)))
    doc = Document()
    if ctx.list_defs:
        from .structures import numbering_base
        ctx = dataclasses.replace(ctx, num_base=numbering_base(doc))
    dpi = ctx.dpi
    content_w = lay.content_w

    # neutralize the template's Normal style (1.08 line, 8pt after) so nothing
    # inherits spacing we didn't ask for
    try:
        npf = doc.styles["Normal"].paragraph_format
        npf.space_before = Pt(0)
        npf.space_after = Pt(0)
        npf.line_spacing = 1.0
    except Exception:
        pass
    _restyle_outline_styles(doc)
    if lay.hyphenated:
        # source justifies with hyphenation: let Word/Docs hyphenate too so
        # line packing (and therefore paragraph heights) stay comparable.
        # Placed where CT_Settings puts it -- straight after defaultTabStop;
        # appended at the end it sat after listSeparator, where a strict reader
        # ignores it. doNotHyphenateCaps follows it in the same sequence: no
        # producer in the corpus hyphenates an all-caps word, and LibreOffice
        # did (`AP-PEALS` on the Supreme Court caption).
        st = doc.settings.element
        if st.find(qn("w:autoHyphenation")) is None:
            ah = OxmlElement("w:autoHyphenation")
            ah.set(qn("w:val"), "1")
            caps = OxmlElement("w:doNotHyphenateCaps")
            caps.set(qn("w:val"), "1")
            dts = st.find(qn("w:defaultTabStop"))
            if dts is not None:
                dts.addnext(ah)
                ah.addnext(caps)
            else:
                st.append(ah)
                st.append(caps)

    sec = doc.sections[0]
    has_cover = lay.cover_band is not None
    # Cover-band section side margins. The 4pt was a hedge against renderers
    # refusing a zero margin, and it cost a visible 3.9pt white frame down both
    # edges of every Google cover page -- the source band bleeds to the paper.
    # probe_cover_band's SIDE family measured Docs honouring side margins
    # exactly (requests of 0/2/4/8 tracked one-for-one), so under the gdocs
    # profile it can simply ask for zero and get a true bleed. Other targets
    # keep the hedge, which also keeps the standard profile byte-identical.
    band_bleed = 0.0 if ctx.output_profile == "gdocs" else 4.0
    if has_cover:
        _config_section(sec, lay, margin_t=lay.cover_top, cols=1, margin_lr=band_bleed)
        sec.header_distance = Emu(0)  # body must start flush at the band
    else:
        _config_section(sec, lay, cols=1)

    # A booklet is one flow with no page seams (see below), so it can carry no
    # page-numbering sections either; decided up front because section 1's
    # parts depend on it.
    booklet = _is_booklet(lay.pages)
    num_secs = [] if booklet else list(lay.hf_sections)
    sec1_blank = bool(num_secs) and num_secs[0].blank
    if lay.even_odd:
        doc.settings.odd_and_even_pages_header_footer = True
    if num_secs and num_secs[0].num_fmt:
        _set_page_numbering(sec, num_secs[0].num_start, num_secs[0].num_fmt)

    # headers/footers for section 1 (never create empty parts: an empty header
    # still reserves a line and pushes the body down)
    if has_cover:
        dl = lay.margin_l - band_bleed
        dr = lay.margin_r - band_bleed
        if lay.header_first is not None:
            _fill_hf(sec.header, _shifted_part(lay.header_first, dl, dr), lay,
                     ctx=ctx)
        if (lay.footer_first or lay.footer_default) is not None:
            _fill_hf(sec.footer,
                     _shifted_part(lay.footer_first or lay.footer_default, dl, dr),
                     lay, ctx=ctx)
    else:
        if sec1_blank:
            _fill_default_parts(sec, lay, ctx, blank=True)
        elif num_secs and num_secs[0].parts is not None:
            _fill_section_parts(sec, lay, ctx, num_secs[0])
        else:
            if lay.header_default is not None:
                _fill_hf(sec.header, lay.header_default, lay, ctx=ctx)
            if lay.footer_default is not None:
                _fill_hf(sec.footer, lay.footer_default, lay, ctx=ctx)
            _fill_even_parts(sec, lay, ctx)
        if lay.different_first:
            sec.different_first_page_header_footer = True
            _fill_first_page_parts(sec, lay, ctx)

    cur_cols = 1
    # config of the currently-open section; re-applied after each break because
    # python-docx's add_section clones sectPr elements in ways that can shuffle
    # previously-applied properties between sections
    cur_cfg = {"margin_t": (lay.cover_top if has_cover else None), "cols": 1,
               "gap": 24.0, "margin_lr": (band_bleed if has_cover else None),
               "hdr0": has_cover, "geo": lay}

    def new_section(kind, cols, gap=24.0, margin_t=None, margin_lr=None,
                    geo=None):
        # `geo` is the new section's paper and margins (a DocLayout); a
        # section opened without one keeps the current page's.
        nonlocal sec, cur_cols, cur_cfg
        geo = geo if geo is not None else cur_cfg["geo"]
        doc.add_section(kind)
        # re-apply the finished section's geometry to whatever element now
        # represents it
        fin = doc.sections[-2]
        _config_section(fin, cur_cfg["geo"], margin_t=cur_cfg["margin_t"],
                        cols=cur_cfg["cols"], col_gap=cur_cfg["gap"],
                        margin_lr=cur_cfg["margin_lr"])
        if cur_cfg.get("hdr0"):
            fin.header_distance = Emu(0)
        sec = doc.sections[-1]
        _config_section(sec, geo, margin_t=margin_t, cols=cols, col_gap=gap,
                        margin_lr=margin_lr)
        # `add_section` hands the new section a clone of the last sectPr. A
        # distinct first page belongs to the document's first page only, and a
        # numbering restart to the section that states it: neither may ride
        # along into every later section (a restart copied into a column
        # section would number that page 1 again).
        if sec._sectPr.find(qn("w:titlePg")) is not None:
            sec.different_first_page_header_footer = False
        _continue_numbering(sec)
        cur_cfg = {"margin_t": margin_t, "cols": cols, "gap": gap,
                   "margin_lr": margin_lr, "hdr0": False, "geo": geo}
        cur_cols = cols
        # Shrink section-break paragraphs to the least height a renderer will
        # give them. That is SECT_BREAK_PARA_PT, not zero -- see the constant.
        for p_el in doc.element.body.findall(qn("w:p")):
            ppr = p_el.find(qn("w:pPr"))
            if ppr is not None and ppr.find(qn("w:sectPr")) is not None:
                if ppr.find(qn("w:spacing")) is None:
                    sp = OxmlElement("w:spacing")
                    sp.set(qn("w:before"), "0")
                    sp.set(qn("w:after"), "0")
                    sp.set(qn("w:line"), str(SECT_BREAK_PARA_TWIPS))
                    sp.set(qn("w:lineRule"), "exact")
                    ppr.append(sp)
        return sec

    if has_cover:
        # The whole cover page lives in ONE bleed-margin section (renderers do
        # not honor L/R margin changes at mid-page continuous breaks). The band
        # spans the bleed width; every other page-1 element is shifted right by
        # indents so it keeps its original x-position.
        delta_l = lay.margin_l - band_bleed
        delta_r = lay.margin_r - band_bleed
        band = lay.cover_band
        band.col_widths = [lay.page_w - 2 * band_bleed]
        for c in band.rows[0]:
            if c:
                c.pad = (c.pad[0], round(c.pad[1] + delta_l, 1), c.pad[2], c.pad[3])
        for ch in lay.pages[0].chunks:
            for el in ch.elements:
                if isinstance(el, Para):
                    el.left_indent = round(el.left_indent + delta_l, 1)
                    el.right_indent = round((el.right_indent or 0.0) + delta_r, 1)
                    el.tab_stops = _shift_tabs(el.tab_stops, delta_l)
                elif isinstance(el, TableEl):
                    el.left_indent = round(el.left_indent + delta_l, 1)
                elif isinstance(el, (FigureEl, ImageEl)):
                    if el.align == "left":
                        el.left_indent = round(el.left_indent + delta_l, 1)
                elif isinstance(el, RuleEl):
                    el.left_indent = round(el.left_indent + delta_l, 1)
        write_table(doc, band, lay.page_w - 2 * band_bleed, ctx=ctx,
                    cover_band=True)

    last_el_par = None
    pending_break = [False]
    # A booklet document is ONE flow: the run boundaries the merge left
    # behind cost a NEW_PAGE section each, and a section that starts a page
    # strands the previous page's leftover -- measured at roughly half a
    # page per boundary, ~36 of them on y06. Inside the booklet signature
    # the boundaries therefore cost nothing: a column-shape change is a
    # CONTINUOUS section break emitted by the chunk loop below (columns
    # begin below the preceding content, exactly how a Word author builds
    # mixed-column text), and same-shape pages simply continue. The
    # non-booklet path -- every gated document -- keeps its page seams:
    # they ARE the page-exact reconstruction the gate certifies.
    #
    # Page-numbering sections still to open, in page order. A start page whose
    # seam is not written (a coalesced table continuation) opens its section
    # at the next seam that is.
    pending_secs = num_secs[1:]
    prev_blank = sec1_blank
    for pi, pg in enumerate(lay.pages):
        # This page's paper and margins: `lay` itself unless the page is of
        # another size than page 1 (design audit B9), and then a page break
        # is a NEW_PAGE section carrying the new pgSz/orient/pgMar whatever
        # else the branches below would have done -- a booklet's flow and a
        # coalesced table cannot cross a change of paper.
        glay = _page_geometry(lay, pg)
        geo_change = pi > 0 and \
            _geometry_key(glay) != _geometry_key(cur_cfg["geo"])
        if pi > 0 and (not pg.continuation_only or geo_change):
            # page boundary
            after_cover = has_cover and pi == 1
            next_cols = pg.chunks[0].n_cols if pg.chunks else 1
            num = None
            while pending_secs and pending_secs[0].start_page <= pg.number:
                num = pending_secs.pop(0)
            if after_cover or geo_change or num is not None:
                # The end of a cover, a change of paper (design audit B9), or a
                # numbering restart / change of format / change of running head
                # at this seam: a NEW_PAGE section replaces the page break,
                # carrying the column shape the page needs exactly as a column
                # change does.
                gap = pg.chunks[0].col_gap if pg.chunks else 24.0
                pre = pg.chunks[0].pre_gap if pg.chunks else 0.0
                mt = (glay.margin_t + pre) if (next_cols > 1 and pre > 0.5) else None
                s = new_section(WD_SECTION.NEW_PAGE, next_cols, gap, margin_t=mt,
                                geo=glay)
                if after_cover:
                    spec = num if (num is not None and num.parts is not None) \
                        else (num_secs[0] if num_secs and
                              num_secs[0].parts is not None else None)
                    if spec is not None:
                        # the cover took section 1; its running heads start here
                        _fill_section_parts(s, lay, ctx, spec)
                    else:
                        _fill_default_parts(s, lay, ctx, always=True)
                    prev_blank = False
                elif num is not None and num.parts is not None:
                    _fill_section_parts(s, lay, ctx, num)
                    prev_blank = False
                elif num is not None and prev_blank:
                    # the lead-in section wrote empty parts; restate the
                    # document's own from here on
                    _fill_default_parts(s, lay, ctx)
                    prev_blank = False
                if num is not None and num.num_fmt is not None:
                    _set_page_numbering(s, num.num_start, num.num_fmt)
            elif booklet:
                # the flow continues; a shape difference is handled by the
                # chunk loop as a CONTINUOUS break. The first chunk's
                # pre_gap is a page-top distance -- a page-relative offset
                # under the same cap as every other joined-page gap.
                if pg.chunks and pg.chunks[0].pre_gap > _JOIN_GAP_CAP_PT:
                    pg.chunks[0].pre_gap = _JOIN_GAP_CAP_PT
            elif cur_cols != next_cols:
                gap = pg.chunks[0].col_gap if pg.chunks else 24.0
                pre = pg.chunks[0].pre_gap if pg.chunks else 0.0
                mt = (glay.margin_t + pre) if (next_cols > 1 and pre > 0.5) else None
                new_section(WD_SECTION.NEW_PAGE, next_cols, gap, margin_t=mt,
                            geo=glay)
            else:
                # Defect catalogue #1: a carrier paragraph spills to the
                # next page exactly when the page before it fills exactly,
                # and fires there -- one blank page. A break riding ON the
                # next paragraph as pageBreakBefore is a no-op at the top
                # of a page and so cannot double-fire. Proven live in
                # Google Docs (round 12 of the 2026-09-11 campaign); the
                # lshort drift map then showed the STANDARD profile's
                # blanks were the same mechanism (8 blank pages of its
                # +20), so the form is now every profile's. Non-paragraph
                # followers cannot carry the property and fall back to a
                # carrier before them.
                pending_break[0] = True
        cw_ctx = (lay.page_w - 2 * band_bleed) if (has_cover and pi == 0) \
            else glay.content_w
        # A one- or two-line spill is absorbed into this page rather than
        # stranded on one of its own by the break that follows. The plan is
        # `{id(element): gap}` and is applied at write time only: `lay` is
        # written once per refine round and a gap reduced in place would
        # compound on every pass. The cover page keeps its own bleed geometry
        # and is never asked. See `_absorb_page_spill`.
        spill_plan = {} if (has_cover and pi == 0) \
            else _absorb_page_spill(pg, cw_ctx, glay,
                                    notes_h.get(pg.number, 0.0),
                                    ctx.output_profile)
        for ci, ch in enumerate(pg.chunks):
            if ch.n_cols != cur_cols:
                if ch.pre_gap > 0.5:
                    _spacer(doc, ch.pre_gap - _sect_break_comp(ctx))
                new_section(WD_SECTION.CONTINUOUS, ch.n_cols, ch.col_gap)
            drop_col_break = _column_one_overflows(ch, cw_ctx, glay,
                                                   ctx.output_profile)
            for el in ch.elements:
                if ctx.note_ids and getattr(el, "role", "") == "footnote":
                    continue        # carried by footnotes.xml instead
                if isinstance(el, ColBreak):
                    if drop_col_break:
                        # Column one is predicted to overflow. Forcing the
                        # break here would fire it from column TWO and abandon
                        # that column; letting the content flow costs a few
                        # lines instead of a whole column. See
                        # _column_one_overflows for the matrix.
                        continue
                    par = doc.add_paragraph()
                    pf = par.paragraph_format
                    pf.space_before = Pt(0)
                    pf.space_after = Pt(0)
                    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
                    pf.line_spacing = Pt(1)
                    par.add_run().add_break(WD_BREAK.COLUMN)
                    continue
                if isinstance(el, Para):
                    brk = pending_break[0]
                    pending_break[0] = False
                    write_para(doc, el, cw_ctx, ctx=ctx,
                               space_before=spill_plan.get(id(el)),
                               page_break_before=brk)
                    continue
                bookmark = getattr(el, "_bookmark", None)
                if bookmark and bookmark in ctx.anchor_ids:
                    # Not a paragraph: mark the spot between block elements.
                    _add_block_bookmark(doc, bookmark, ctx.anchor_ids[bookmark])
                # Where a page seam goes in front of a non-paragraph element.
                # A `w:br type=page` carrier before it makes LibreOffice drop
                # the element's page-top space_before; pageBreakBefore on the
                # element's own first paragraph keeps it -- figures, images
                # and rules ARE paragraphs, and a table with a page-top gap
                # opens with a spacer paragraph. probe_pagetop: a marker at
                # 83.2pt after a carrier against 183.2 under pageBreakBefore
                # (100pt asked; B23 / issue #42), reproduced through this
                # writer in the canonical container (84.6 -> 184.6).
                #
                # The page then sits where the source put it -- but whether
                # that is better depends on what else the page carries, and
                # only a render can say. Measured open-loop, the dropped gap
                # was slack covering inflation elsewhere: keeping it took the
                # raw renders of y17 228 -> 231 pages, y27 159 -> 161 and y03
                # 71 -> 74. Measured closed-loop, the kept gap is a lever the
                # refine loop can finally correct -- same page counts, and the
                # per-page offsets it leaves fall 2429 -> 2139pt on y17 and
                # 694 -> 377 on y27. So the form is chosen by
                # `top_gap_fits`, which only the refine loop sets (from
                # `_stack_fits`, once, before it moves any gap): an open-loop
                # write keeps the shipped carrier, page for page.
                #
                # Never where there is no page-top gap to keep (the table
                # spacer's 0.5pt bar): moving the break changes nothing there
                # except what LibreOffice treats as "the top of the page", and
                # on x11 that un-hid a run of degenerate negative-height
                # figures whose compensating 330-450pt gaps it had been
                # suppressing (4 rendered pages -> 5).
                carry = False
                if pending_break[0]:
                    if ((isinstance(el, (FigureEl, ImageEl, RuleEl))
                            and (el.space_before or 0.0) > 0.5) or (
                            isinstance(el, TableEl)
                            and table_opens_with_spacer(el, ctx))) and \
                            getattr(pg, "top_gap_fits", None) is True:
                        carry = True
                    else:
                        _page_break_carrier(doc)
                    pending_break[0] = False
                if isinstance(el, TableEl):
                    # A table in a column flow must be sized to its COLUMN.
                    # The page width is the wrong ruler: the min-column
                    # widening then funds a dot-leader worksheet line at
                    # 300pt inside a 165pt column, and a table cannot wrap
                    # -- it overflows across the neighbouring columns and
                    # their text (measured: 6 colliding pages on y06, where
                    # the source carries these worksheets INSIDE a real
                    # 165pt column). Booklet-scoped: the gated corpus has
                    # no >=3-col flow, and its behaviour is the baseline.
                    tw = cw_ctx
                    if booklet and ch.n_cols > 1:
                        gap = ch.col_gap or 0.0
                        tw = (cw_ctx - gap * (ch.n_cols - 1)) / ch.n_cols
                    write_table(doc, el, tw, ctx=ctx, page_break_before=carry)
                elif isinstance(el, FigureEl):
                    if write_figure(doc, el, ctx=ctx,
                                    page_break_before=carry,
                                    page=(glay.page_w, glay.page_h)) is None:
                        # Nothing was written (no renderer, or the clip
                        # rendered empty): the break waits for the next
                        # element rather than vanishing with this one.
                        pending_break[0] = carry
                elif isinstance(el, ImageEl):
                    if write_image(doc, el, ctx=ctx,
                                   page_break_before=carry,
                                   page=(glay.page_w, glay.page_h)) is None:
                        pending_break[0] = carry
                elif isinstance(el, RuleEl):
                    write_rule(doc, el, cw_ctx, page_break_before=carry)

    # drop the initial empty paragraph python-docx puts in a fresh document
    # (never touch section-break paragraphs: removing one deletes a section)
    body = doc.element.body
    paras = body.findall(qn("w:p"))
    if paras:
        p0 = paras[0]
        has_content = p0.findall(qn("w:r")) or p0.findall(qn("w:hyperlink")) \
            or p0.findall(qn("w:fldSimple"))
        ppr = p0.find(qn("w:pPr"))
        has_sectpr = ppr is not None and ppr.find(qn("w:sectPr")) is not None
        if not has_content and not has_sectpr and len(list(body)) > 2:
            body.remove(p0)

    if ctx.list_defs:
        from .structures import write_numbering
        write_numbering(doc, ctx.list_defs, ctx.output_profile, ctx.num_base)
    if ctx.note_ids:
        # Every note's reference must have reached the body: its text has
        # already been left out of it, and a note with no reference is text
        # no reader will ever see. If one is missing the document is written
        # again with its notes typed -- never with a note dropped.
        written = {int(r.get(qn("w:id")))
                   for r in body.iter(qn("w:footnoteReference"))}
        if written != {wid for wid, _custom in ctx.note_ids.values()}:
            if ctx.image_report is not None:
                ctx.image_report.clear()     # the rewrite counts afresh
            return _write_docx(src_lay, out_path, dataclasses.replace(
                ctx, note_ids={}, notes_vetoed=True))
        from .structures import write_footnotes
        write_footnotes(doc, lay, ctx, write_para)
    _release_keeps_before_seams(body)
    _declare_fonts(doc)
    doc.save(out_path)
    return out_path


def _starts_with_page_break(block) -> bool:
    """Does this body block open with pageBreakBefore (a paragraph's own, or a
    table's first paragraph's)?"""
    p = block
    if block.tag == qn("w:tbl"):
        p = next(block.iter(qn("w:p")), None)
    if p is None or p.tag != qn("w:p"):
        return False
    ppr = p.find(qn("w:pPr"))
    if ppr is None:
        return False
    pbb = ppr.find(qn("w:pageBreakBefore"))
    return pbb is not None and pbb.get(qn("w:val")) not in ("0", "false", "off")


def _release_keeps_before_seams(body) -> None:
    """A paragraph right before a pageBreakBefore seam must not keep-with-next.

    The source put a heading at the very bottom of its page and the body it
    heads at the top of the next (c6_long's "12. Section heading number 12").
    Headings carry keepNext -- directly and through the Heading styles -- and
    the next paragraph opens the next source page with pageBreakBefore, so
    the keep cannot be satisfied on the page the heading is on: the renderer
    moves the heading forward, the forced break then fires after it, and the
    heading sits alone on a page of its own. Measured live in Google Docs
    (pass 8, 2026-10-04): c6_long 7 -> 8 pages, word recall 1.000 -> 0.820,
    bisected to the commit that replaced carrier paragraphs with
    pageBreakBefore seams (07a9a83) -- a carrier paragraph absorbed the keep
    on the heading's own page. The keep is released explicitly (w:val=0, so
    the Heading style's keepNext is overridden too), and only on the one
    paragraph in front of a hard seam, where it never had a satisfiable
    meaning.
    """
    blocks = [b for b in body if b.tag in (qn("w:p"), qn("w:tbl"))]
    for prev, cur in zip(blocks, blocks[1:]):
        if prev.tag != qn("w:p") or not _starts_with_page_break(cur):
            continue
        ppr = prev.find(qn("w:pPr"))
        if ppr is None:
            ppr = OxmlElement("w:pPr")
            prev.insert(0, ppr)
        if ppr.find(qn("w:sectPr")) is not None:
            continue
        for old in ppr.findall(qn("w:keepNext")):
            ppr.remove(old)
        off = OxmlElement("w:keepNext")
        off.set(qn("w:val"), "0")
        # CT_PPr sequence: pStyle, keepNext, ... -- after pStyle if present
        st = ppr.find(qn("w:pStyle"))
        ppr.insert(list(ppr).index(st) + 1 if st is not None else 0, off)
