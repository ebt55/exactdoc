"""Intermediate representation (IR) for exactdoc.

Everything is measured in PDF points (72/inch), origin top-left of page.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

BBox = Tuple[float, float, float, float]  # x0, y0, x1, y1 (top-left origin)


def bbox_union(a: Optional[BBox], b: Optional[BBox]) -> Optional[BBox]:
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def bbox_area(b: BBox) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def bbox_overlap(a: BBox, b: BBox) -> float:
    """Area of intersection."""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def contains(outer: BBox, inner: BBox, pad: float = 2.0) -> bool:
    return (inner[0] >= outer[0] - pad and inner[1] >= outer[1] - pad and
            inner[2] <= outer[2] + pad and inner[3] <= outer[3] + pad)


@dataclass(frozen=True)
class LinkDest:
    """Where an internal (GoTo) link lands: a point in THIS document.

    Frozen and hashable on purpose: the writer groups runs by destination and
    keys its bookmark table on one of these, so two runs pointing at the same
    place must compare equal and hash alike.

    `page` is a 0-based page index, which is what both backends report and what
    PDF's own destination arrays carry. `x`/`y` are page points in the IR's
    top-left origin, like every bbox in this module -- NOT the PDF's bottom-up
    user space. Both parsers normalise into this, and they have to, because
    neither library hands it over ready to use: PDFium's
    FPDFDest_GetLocationInPage always reports raw bottom-up y, while PyMuPDF
    reports a direct /Dest array already flipped and a NAMED destination raw.
    Measured on the same two files, before normalisation: PDFium 646.5 and
    600.0, PyMuPDF 646.5 and 192.0, for destinations that are 145.5 and 192.0
    in this coordinate system.

    A consumer tells the two link kinds apart by which field is set, never by
    inspecting the string: `Span.link` is an external URI, `Span.dest` is an
    internal destination. They are mutually exclusive.
    """
    page: int
    x: float
    y: float


@dataclass
class Span:
    text: str
    font: str            # raw PDF font name, subset prefix stripped
    size: float
    color: str           # '#rrggbb'
    bold: bool
    italic: bool
    mono: bool
    serif: bool
    superscript: bool
    bbox: BBox
    origin: Tuple[float, float]  # baseline origin
    link: Optional[str] = None   # external uri if inside a URI link rect
    dest: Optional[LinkDest] = None  # internal target if inside a GoTo rect


@dataclass
class Line:
    spans: List[Span]
    bbox: BBox
    dir: Tuple[float, float] = (1.0, 0.0)   # writing direction (cos, sin)

    @property
    def horizontal(self) -> bool:
        return abs(self.dir[1]) < 0.08

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def baseline(self) -> float:
        return self.spans[0].origin[1] if self.spans else self.bbox[3]


@dataclass
class TextBlock:
    lines: List[Line]
    bbox: BBox

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)


@dataclass
class DrawCmd:
    """One vector drawing (path) from the PDF content stream."""
    kind: str              # 'fill' | 'stroke' | 'fillstroke'
    shape: str             # 'rect' | 'hline' | 'vline' | 'line' | 'curve' | 'complex'
    bbox: BBox
    fill: Optional[str]    # '#rrggbb' or None
    stroke: Optional[str]
    width: float           # stroke width
    opacity: float
    n_items: int
    seqno: int = 0


@dataclass
class ImageObj:
    bbox: BBox
    xref: int
    width: int
    height: int
    data: Optional[bytes] = None
    ext: str = "png"


@dataclass
class PageIR:
    number: int            # 1-based
    width: float
    height: float
    blocks: List[TextBlock] = field(default_factory=list)
    drawings: List[DrawCmd] = field(default_factory=list)
    images: List[ImageObj] = field(default_factory=list)
    # one of {'bbox':..., 'uri': str} or {'bbox':..., 'dest': LinkDest}
    links: List[Dict[str, Any]] = field(default_factory=list)
    rotated: List[Line] = field(default_factory=list)  # non-horizontal, out of flow


@dataclass
class DocIR:
    path: str
    pages: List[PageIR] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        out = [f"{self.path}: {len(self.pages)} pages"]
        for p in self.pages:
            nspan = sum(len(l.spans) for b in p.blocks for l in b.lines)
            out.append(
                f"  p{p.number} {p.width:.0f}x{p.height:.0f}: "
                f"{len(p.blocks)} blocks / {nspan} spans, "
                f"{len(p.drawings)} drawings, {len(p.images)} images, {len(p.links)} links")
        return "\n".join(out)
