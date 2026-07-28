"""Semantic layout model produced by inference, consumed by the DOCX writer."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

from .model import BBox


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
    link: Optional[str] = None
    is_tab: bool = False
    underline: bool = False
    superscript: bool = False
    field: Optional[str] = None  # 'PAGE' | 'NUMPAGES'


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
    tab_stops: List[Tuple[float, str]] = field(default_factory=list)  # (pos_pt, align)
    line_breaks: bool = False    # True: runs contain '\n' to keep as soft breaks
    bbox: Optional[BBox] = None  # source position (debug/audit)

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
    col_span: int = 1


@dataclass
class TableEl:
    rows: List[List[Optional[Cell]]] = field(default_factory=list)  # None = covered by span
    col_widths: List[float] = field(default_factory=list)
    row_heights: List[Optional[float]] = field(default_factory=list)
    left_indent: float = 0.0     # from container left edge
    space_before: float = 0.0
    space_after: float = 0.0
    bbox: Optional[BBox] = None
    role: str = "table"          # table|box|code|band|cards|quote


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


@dataclass
class PageLayout:
    number: int
    chunks: List[Chunk] = field(default_factory=list)


@dataclass
class HFPart:
    """Header or footer content."""
    elements: List[Any] = field(default_factory=list)  # Para | TableEl | RuleEl
    distance: float = 36.0       # from page edge


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
    hyphenated: bool = False               # source uses hyphenated justification
    cover_band: Optional[TableEl] = None   # page-1 full-width band (own section, small top margin)
    cover_top: float = 0.0                 # top margin for the cover section
    pages: List[PageLayout] = field(default_factory=list)
    src_path: str = ""

    @property
    def content_w(self) -> float:
        return self.page_w - self.margin_l - self.margin_r
