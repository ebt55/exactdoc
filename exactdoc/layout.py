"""Semantic layout model produced by inference, consumed by the DOCX writer."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

from .model import BBox, LinkDest


@dataclass
class Run:
    text: str
    font: str          # raw PDF font (writer maps it)
    size: float
    color: str
    bold: bool = False
    italic: bool = False
    mono: bool = False
    serif: bool = False
    link: Optional[str] = None        # external URI
    dest: Optional[LinkDest] = None   # internal destination; see model.LinkDest
    is_tab: bool = False
    underline: bool = False
    superscript: bool = False
    field: Optional[str] = None  # 'PAGE' | 'NUMPAGES'
    # Per-character tracking in points, emitted as w:spacing on rPr. Negative
    # values compress a line that TeX fitted by shrinking inter-word glue --
    # something Word's line breaker cannot do on its own.
    char_spacing: float = 0.0
    # Horizontal scale the writer emits as w:w (1.0 = none; 0.0 = not set) so
    # the run occupies the width the source drew it at -- see
    # metrics.apply_width_scale. The ladder shapes with it too.
    width_scale: float = 0.0
    # The SOURCE's letter-spacing in points (model.Span.tracking), kept apart
    # from the ladder's compression above so that neither overwrites the other;
    # the writer emits their sum. It ADDS space after each glyph, where
    # width_scale scales the glyphs themselves; the two compose.
    tracking: float = 0.0
    # A body run that IS a footnote reference mark: the index of its note in
    # DocLayout.footnotes. The text stays the source's mark, so a writer without
    # the footnotes capability prints exactly what it always printed.
    footnote: Optional[int] = None
    # Inside a footnote's own paragraphs: the run that is the note's mark at
    # the head of the note text (w:footnoteRef, or the literal custom mark).
    footnote_mark: bool = False


# Number formats a list level can carry, named as OOXML's ST_NumberFormat does.
LIST_FORMATS = ("bullet", "decimal", "lowerLetter", "upperLetter",
                "lowerRoman", "upperRoman")


@dataclass
class ListItem:
    """A paragraph's place in a real list (w:numPr), as inference read it.

    The paragraph's runs keep the TYPED marker ("•", tab, text / "1. text"), so
    a profile without the numbering capability writes what it always wrote.
    `marker` is the marker's text exactly as typed and `sep` what separated it
    from the item text ("tab": a tab run; "space": a typed space); a numbering
    writer removes both and lets the list level draw them -- except under
    "nothing", where the typed space stays text (lists.assign_lists says why).
    """
    list_id: int                 # index into DocLayout.lists
    level: int                   # 0-based ilvl
    fmt: str                     # one of LIST_FORMATS
    marker: str                  # typed marker text: "•", "1.", "(a)", "iv)"
    sep: str = "tab"             # 'tab' | 'space' | 'nothing' (space kept as text)
    value: int = 0               # the ordinal this item shows; 0 for bullets


@dataclass
class ListLevel:
    """One level of a list: what Word's w:lvl says, from measured items."""
    fmt: str
    start: int = 1
    text: str = ""               # w:lvlText: "%1." / "(%2)" / the bullet glyph
    sep: str = "tab"             # w:suff
    left: float = 0.0            # w:ind left, container-relative pt
    hanging: float = 0.0         # w:ind hanging, pt (marker sits at left - hanging)
    marker_run: Optional[Run] = None   # the marker's typography (w:lvl/w:rPr)


@dataclass
class ListDef:
    """One list instance: one w:num over its own w:abstractNum."""
    list_id: int
    levels: Dict[int, ListLevel] = field(default_factory=dict)


@dataclass
class Para:
    runs: List[Run] = field(default_factory=list)
    align: str = "left"          # left|center|right|justify
    leading: float = 0.0         # exact line height in pt (0 = auto)
    space_before: float = 0.0
    space_after: float = 0.0
    left_indent: float = 0.0     # relative to container left
    right_indent: float = 0.0
    first_indent: float = 0.0    # relative to left_indent (can be negative = hanging)
    heading: int = 0             # 0 = body, 1..6 outline level
    # (pos_pt, align) or (pos_pt, align, leader); leader is "dot" for a
    # contents line's dot leader. Positions are from the container's left edge.
    tab_stops: List[Tuple] = field(default_factory=list)
    line_breaks: bool = False    # True: runs contain '\n' to keep as soft breaks
    bbox: Optional[BBox] = None  # source position (debug/audit)
    # How many visual lines this paragraph occupied in the source, and how wide
    # each one was. The quality ladder needs the source truth to compare a
    # predicted re-wrap against; without it, "did this paragraph change height?"
    # can only be guessed from bbox/leading arithmetic.
    src_lines: int = 0
    src_widths: List[float] = field(default_factory=list)
    fidelity: str = "flow"       # 'flow' | 'line-locked' (see ladder.py)
    # A rare row-like group can be indistinguishable from a justified paragraph
    # until its inferred inset is narrower than a source row.  Keep the source
    # rows as an alternate, target-specific serialization; standard DOCX keeps
    # its existing flow form while the Google Docs profile can preserve them.
    gdocs_rows: List[List[Run]] = field(default_factory=list)
    # A contents line's leader as the source typed it ("....."), kept beside
    # the dot-leader tab stop that replaces it: Google Docs draws no tab
    # leaders, so that profile types these dots instead (docxout).
    leader_text: str = ""
    # Membership of a real list; None for every other paragraph. See ListItem.
    numbering: Optional[ListItem] = None
    # "" for ordinary flow. "footnote": this paragraph is the source's footnote
    # text at the page bottom, carried by DocLayout.footnotes as a real note --
    # a writer with the footnotes capability leaves it out of the body flow.
    role: str = ""
    # (x, y, width) on the page, points: the paragraph is page-locked at the
    # position the source drew it (w:framePr), out of the flow. Set only on a
    # slide (infer._lock_slide); None for every flowing paragraph.
    frame: Optional[Tuple[float, float, float]] = None
    # A right-to-left paragraph (Hebrew, Arabic): its runs are in logical
    # order, and `align`, `left_indent`, `right_indent`, `first_indent` and
    # `tab_stops` are in START/END terms -- "left" is the start, which is the
    # right edge -- exactly as OOXML reads them in a w:bidi paragraph.
    rtl: bool = False

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class Cell:
    paras: List[Para] = field(default_factory=list)
    shading: Optional[str] = None
    borders: Dict[str, Optional[Tuple[float, str]]] = field(default_factory=dict)
    # borders keys: top/bottom/left/right -> (width_pt, color) or None
    pad: Tuple[float, float, float, float] = (2, 4, 2, 4)  # top,left,bottom,right? see writer
    valign: str = "top"
    # A merged cell: the grid columns and rows it covers from its own
    # position (TableEl.rows is always full-width, one entry per grid column;
    # the positions a span covers hold None). Written as w:gridSpan and
    # w:vMerge.
    col_span: int = 1
    row_span: int = 1
    # A LAYOUT cell (TableEl.role "layout": one column of a side-by-side page
    # region) holds a column's whole flow -- paragraphs, rules, pictures and
    # boxes -- in order. When set, the writer writes these instead of `paras`;
    # `paras` then lists the Para members of `blocks` (the same objects), so
    # every pass that reads cell paragraphs still sees them.
    blocks: List[Any] = field(default_factory=list)


@dataclass
class TableEl:
    # Full-width rows: rows[r][c] is the cell whose top-left grid position is
    # (r, c), or None where a merged cell (col_span/row_span) covers it.
    rows: List[List[Optional[Cell]]] = field(default_factory=list)
    col_widths: List[float] = field(default_factory=list)
    row_heights: List[Optional[float]] = field(default_factory=list)
    left_indent: float = 0.0     # from container left edge
    space_before: float = 0.0
    space_after: float = 0.0
    bbox: Optional[BBox] = None
    role: str = "table"          # table|box|code|band|cards|quote
    # How far the table's drawn left edge stands LEFT of its column while its
    # text starts at the column: the hanging border Word itself draws, by the
    # first cell's left margin (5.4pt by default). `left_indent` stays clamped
    # at the column; the standard profile's writer places the edge here
    # (`write_table`), the gdocs profile does not read it.
    hang_left: float = 0.0
    # True when the column boundaries were READ FROM DRAWN EDGES (grid
    # lines), rather than inferred from text clustering. A drawn edge is
    # the author's own statement of where the column is; text clustering is
    # an estimate that `_fit_col_widths` exists to correct. Consumers use
    # this to decide whether a line wider than its column is a measurement
    # of real need (clustering put the edge in the wrong place) or a parse
    # artefact (the parser joined two cells into one line).
    col_edges_drawn: bool = False
    # Number of leading rows that were actually repeated in the source.  This
    # is deliberately evidence, not a writer preference: most PDF tables do
    # not repeat their headers on continuation pages.
    repeat_header_rows: int = 0


@dataclass
class FigureEl:
    page_no: int                 # 1-based source page
    clip: BBox                   # region to rasterize
    width: float                 # display width pt
    height: float
    align: str = "center"
    left_indent: float = 0.0
    space_before: float = 0.0
    space_after: float = 0.0


@dataclass
class ImageEl:
    data: bytes
    ext: str
    width: float
    height: float
    align: str = "center"
    left_indent: float = 0.0
    space_before: float = 0.0
    space_after: float = 0.0


@dataclass
class RuleEl:
    width_pct: float             # of content width
    thickness: float
    color: str
    length: float = 0.0          # absolute length in pt (preferred over pct)
    left_indent: float = 0.0
    space_before: float = 0.0
    space_after: float = 0.0
    role: str = ""               # "footnote": the note separator (see Para.role)
    frame: Optional[Tuple[float, float, float]] = None   # see Para.frame


@dataclass
class Footnote:
    """A source footnote: its mark and its text, moved out of the body flow.

    `paras` are built from the note's own lines; the one run with
    `footnote_mark` set is the mark at the head of the note. `auto` says the
    renderer's own footnote counter reproduces `mark` at this note's position
    in the document (see notes.number_footnotes); a note it would misnumber
    keeps the source's mark verbatim as a custom mark.
    """
    fid: int                     # index in DocLayout.footnotes
    page: int                    # 1-based source page
    mark: str                    # "1", "12", "*", "†"
    value: int = 0               # numeric value of a digit mark, else 0
    auto: bool = True
    paras: List["Para"] = field(default_factory=list)
    # True when the note runs on into the next page's note area in the
    # source, and its paragraphs carry that page's lines too.
    continued: bool = False


@dataclass
class NoteArea:
    """Where a page's footnotes stood in the source, for the page-fit model.

    `top` is the zone's top (its separator, or its first note); `bottom` the
    baseline-model bottom of its last note line (baseline + 0.21 x size, the
    box model of THEORY §3.1); `height` the exact-leading height of every
    note line the page carries, continuation lines included. `runs_on`: the
    page's last note continues on the next page.
    """
    top: float
    bottom: float
    height: float
    runs_on: bool = False


@dataclass
class FloatEl:
    """A graphic placed at its source position on the page, out of the flow.

    Inference uses it only where the page is a slide (infer._deck_pages): a
    slide is graphics positioned over and beside its text, which a flow can
    only stack, so each one stood a page-height of pictures on top of the
    text. Anchored to the page (wp:anchor) a graphic spends no flow height and
    the text flows exactly as it would without it.
    """
    el: Any                      # ImageEl | FigureEl
    bbox: BBox                   # where the source drew it, page points
    behind: bool = False         # under text it overlaps (slide text sits on it)
    # The text wraps around it (wp:wrapSquare) keeping this clearance, points
    # (left, top, right, bottom); None for no wrap. Set where the source wraps
    # a paragraph around a picture (infer._wrapped_by_text).
    wrap: Optional[Tuple[float, float, float, float]] = None


class ColBreak:
    pass


class PageBreak:
    pass


@dataclass
class Chunk:
    """A vertical region of a page with a uniform column count."""
    n_cols: int = 1
    col_gap: float = 24.0
    pre_gap: float = 0.0   # vertical gap to emit BEFORE entering this chunk's section
    elements: List[Any] = field(default_factory=list)
    # The columns' own widths in pt, left to right, when they are not equal (a
    # sidebar beside a main column); empty means equal widths. The gap between
    # them is `col_gap`.
    col_widths: List[float] = field(default_factory=list)


@dataclass
class PageLayout:
    number: int
    chunks: List[Chunk] = field(default_factory=list)
    # Set only after adjacent, verified table segments have been coalesced.
    # The writer may then omit this source-page break and let Word paginate the
    # one logical table naturally.
    continuation_only: bool = False
    # A page whose size differs from page 1's carries its own geometry: paper
    # size and (left, right, top, bottom) margins measured on the pages of
    # that size. None means the document's (DocLayout.page_w/h, margin_*).
    # The writer opens a section wherever the geometry changes.
    page_w: Optional[float] = None
    page_h: Optional[float] = None
    margins: Optional[Tuple[float, float, float, float]] = None
    # This page's footnotes, when they were read as real notes (notes.py).
    note_area: Optional["NoteArea"] = None
    # True: the seam in front of this page may carry its page break on the
    # first element itself, which keeps a non-paragraph first element's
    # page-top gap in LibreOffice (B23; see the seam in docxout._write_docx).
    # Only the refine loop sets it -- from docxout._stack_fits, once, before
    # it moves any gap, so the form cannot flip under its own corrections.
    # None (every open-loop write) keeps the 1pt carrier.
    top_gap_fits: Optional[bool] = None
    # Graphics anchored to this page out of the flow (FloatEl); empty unless
    # inference read the page as a slide with a profile that anchors.
    floats: List[Any] = field(default_factory=list)
    # Points the refine loop has pushed this page's content down by, each push
    # no more than the room its render measured at the page foot
    # (refine._apply). The writer's open-loop spill planner plans the page as
    # it was before the pushes and adds them back (docxout._absorb_page_spill).
    # Never set by an open-loop write.
    loop_push_pt: float = 0.0
    # Points the refine loop lifts this page's real footnotes by, above the
    # foot of the body box where a renderer stacks them, toward where the
    # source's notes ended (notes.footnote_lifts, refine._apply). Each lift
    # is no more than the room its render measured between the body and the
    # notes. Never set by an open-loop write.
    note_lift_pt: float = 0.0


@dataclass
class HFPart:
    """Header or footer content."""
    elements: List[Any] = field(default_factory=list)  # Para | TableEl | RuleEl
    distance: float = 36.0       # from page edge


@dataclass
class HFSection:
    """A run of source pages with its own page numbering.

    The writer opens a NEW_PAGE section at `start_page` (1-based source page)
    and states the numbering on it as `w:pgNumType`: `num_start` is the number
    the source prints on that page, `num_fmt` its format ('decimal',
    'lowerRoman', 'upperRoman'). Both None: the section continues numbering.
    `blank`: the section's pages carry no running furniture in the source (a
    cover and title page ahead of numbered front matter), so its header and
    footer are written empty and the next section restates the document's.
    The first entry always has start_page 1.
    """
    start_page: int
    num_start: Optional[int] = None
    num_fmt: Optional[str] = None
    blank: bool = False
    # Running-head parts this section states itself, because the source's
    # varying furniture changes here (a new chapter title in the head). Keys
    # 'header', 'footer', 'header_even', 'footer_even', 'header_first',
    # 'footer_first'; None (the attribute) = inherit the previous section's.
    parts: Optional[Dict[str, Optional["HFPart"]]] = None
    # The section's first page is a chapter opener without the running head.
    title_pg: bool = False


@dataclass
class DocLayout:
    page_w: float = 612.0
    page_h: float = 792.0
    margin_l: float = 72.0
    margin_r: float = 72.0
    margin_t: float = 72.0
    margin_b: float = 72.0
    header_default: Optional[HFPart] = None
    header_first: Optional[HFPart] = None
    footer_default: Optional[HFPart] = None
    footer_first: Optional[HFPart] = None
    different_first: bool = False
    # Verso/recto furniture: when set, `header_default`/`footer_default` are the
    # odd-page parts and these the even-page ones (None = same as default).
    even_odd: bool = False
    header_even: Optional[HFPart] = None
    footer_even: Optional[HFPart] = None
    # Page-numbering sections; empty when the document numbers 1..n in arabic.
    hf_sections: List[HFSection] = field(default_factory=list)
    hyphenated: bool = False               # source uses hyphenated justification
    cover_band: Optional[TableEl] = None   # page-1 full-width band (own section, small top margin)
    cover_top: float = 0.0                 # top margin for the cover section
    pages: List[PageLayout] = field(default_factory=list)
    src_path: str = ""
    ladder_report: dict = field(default_factory=dict)  # see ladder.py
    # The source's own glyph advances, {font: {char: em}}, carried from
    # DocIR.font_advances for metrics.apply_width_scale.
    font_advances: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # Real lists (Para.numbering points here by list_id) and real footnotes
    # (Run.footnote points here by fid). Both are inference's reading of the
    # source; whether a profile serialises them is the writer's capability.
    lists: List[ListDef] = field(default_factory=list)
    footnotes: List[Footnote] = field(default_factory=list)
    # How the source numbers its notes: "continuous" from footnote_start, or
    # "eachPage" (every page restarts at 1). Custom marks are outside both.
    footnote_restart: str = "continuous"
    footnote_start: int = 1

    @property
    def content_w(self) -> float:
        return self.page_w - self.margin_l - self.margin_r


def iter_paras(lay: DocLayout):
    """Every Para a written document will contain: body, table cells, the
    cover band, headers and footers. `gdocs_rows` are alternate serialisations
    of a Para's own runs, not paragraphs, and are not yielded."""
    def walk(el):
        if isinstance(el, Para):
            yield el
        elif isinstance(el, TableEl):
            for row in el.rows:
                for cell in row:
                    if isinstance(cell, Cell):
                        if cell.blocks:
                            for b in cell.blocks:
                                yield from walk(b)
                        else:
                            yield from cell.paras
    for page in lay.pages:
        for chunk in page.chunks:
            for el in chunk.elements:
                yield from walk(el)
    if lay.cover_band is not None:
        yield from walk(lay.cover_band)
    for part in (lay.header_default, lay.header_first,
                 lay.footer_default, lay.footer_first):
        if part is not None:
            for el in part.elements:
                yield from walk(el)
    # A footnote's own paragraphs, written into footnotes.xml by a profile with
    # the footnotes capability (their typed twins are in the body above).
    for note in lay.footnotes:
        yield from note.paras

def page_sequences(pg):
    """A page's element sequences in reading order: each chunk's elements, and
    each column of a layout table (infer._layout_table), whose paragraphs are
    the page's flow as much as any chunk's -- headings, lists and list hangs
    read them too."""
    for ch in pg.chunks:
        els = [e for e in ch.elements if not isinstance(e, ColBreak)]
        yield els
        for el in els:
            if isinstance(el, TableEl) and el.role == "layout":
                for row in el.rows:
                    for c in row:
                        if c is not None and c.blocks:
                            yield list(c.blocks)
