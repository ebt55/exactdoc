"""Intermediate representation (IR) for exactdoc.

Everything is measured in PDF points (72/inch), origin top-left of page.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

BBox = Tuple[float, float, float, float]  # x0, y0, x1, y1 (top-left origin)

# XML 1.0 (§2.2) permits #x9, #xA, #xD and #x20-and-up in a text node, and
# nothing else below #x20. Probed rather than assumed: lxml refuses exactly
# 0x0-0x8, 0xb-0xc, 0xe-0x1f and 0xfffe-0xffff, and ACCEPTS 0x7f-0x9f -- so
# stripping the C1 block as well would delete characters the format allows.
# Lone surrogates are added because they are legal in a Python str and cannot
# be encoded to UTF-8 at save time.
_XML_ILLEGAL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff"
                             "￾￿]")


def xml_safe_text(text: str) -> str:
    """Text with the characters XML cannot carry removed.

    THE CONTRACT: every `Span.text` in the IR is serialisable. This is enforced
    where Spans are built -- in the two parsers -- and not in the writer, and
    that choice is deliberate:

      * the characters are an extraction artifact of one backend, not content.
        PDFium returns the raw character code for a glyph whose font gives it no
        usable ToUnicode mapping; PyMuPDF resolves the same glyph. Measured over
        the 45-document corpus, PyMuPDF produces ZERO such characters and PDFium
        produces them in 13 documents.
      * they are overwhelmingly NOT in link text. On y01, 31 spans carry one and
        only 3 of those are links; y10, y13 and y03 have affected spans and no
        affected links at all. Sanitising inside the writer's hyperlink helper
        -- where the crash surfaced -- would leave the same ValueError waiting
        at `par.add_run()` for eight of the thirteen documents.
      * the writer has six text-assignment sites and every one of them takes
        text that came from a Span. One normalisation point covers all six; six
        sanitisers would be six chances to miss one.
      * scoring reads `Span.text` too. Sanitising only on the way out would
        leave the IR carrying characters the DOCX does not, so live-text and
        word-recall would be measured against text that was never written.

    Removal, not substitution: what the glyph depicted is not recoverable from
    the code point, and inventing a character would be a guess about content.
    See parse_pdfium._page_chars for the measured consequence (end-of-line
    hyphens on Adobe PDFMaker output arrive as U+0002 and are lost with it).
    """
    if not text:
        return text
    return _XML_ILLEGAL_RE.sub("", text)


def xml_safe_uri(uri: Optional[str]) -> Optional[str]:
    """A URI usable as an OOXML relationship target, or None.

    Relationship targets end up in document.xml.rels, so the same XML rule
    applies -- but a URI is defined over octets (RFC 3986 §2.1), and the
    spelling for an octet that cannot appear literally is percent-encoding, not
    deletion. Returns None when nothing usable is left, so the caller writes
    plain text rather than a broken relationship.
    """
    if not uri:
        return None
    safe = _XML_ILLEGAL_RE.sub(
        lambda m: "".join("%%%02X" % b for b in m.group(0).encode("utf-8")),
        uri)
    return safe or None


def ink_extent(span) -> Tuple[float, float]:
    """A span's horizontal extent without its leading and trailing spaces.

    A span's box covers its spaces too, and an OCR layer pads each line with
    leading spaces back to the text block's edge (y56: every line's box starts
    at x 23 whatever its first word), so two words on one baseline looked as
    if they overprinted each other. Apportioned by character count -- the box
    holds no per-glyph positions -- which is enough to tell a word from the
    run of blanks before it.
    """
    x0, x1 = span.bbox[0], span.bbox[2]
    t = span.text or ""
    n = len(t)
    if n == 0 or not t.strip():
        return x0, x1
    lead = n - len(t.lstrip())
    trail = n - len(t.rstrip())
    per = (x1 - x0) / n
    return x0 + lead * per, x1 - trail * per


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
    # Always XML-serialisable: the parsers pass it through xml_safe_text.
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
    # Set when the parser measured uniform letter-spacing across this run. It is
    # a typographic fact about the source, not a writer instruction: nothing
    # emits tracking from it. Inference uses it as a paragraph boundary, because
    # a letter-spaced line among un-letter-spaced ones is a heading.
    tracked: bool = False
    # The letter-spacing itself, in points: the extra advance the producer put
    # after each glyph beyond the font's own. 0.0 when the run carries none that
    # the parser could measure consistently (see parse_pdfium._span_tracking).
    tracking: float = 0.0
    # The run is a word set as spaced capitals (`O V E R V I E W`): the spaces
    # in `text` stand for tracking wider than a space, not for word breaks.
    # Inference decides whether to close them up (it has the vocabulary).
    spaced_letters: bool = False


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
    # The path is a rectangle with rounded corners (see rounded_rect_bbox):
    # the parser reports it as shape 'rect', because that is what it is to
    # every consumer, and keeps this as the evidence it was drawn with curves.
    rounded: bool = False


# A path whose straight edges are all axis-aligned and which fills at least
# this share of its bounding box is a box, whatever its corners do. The two
# populations it separates: a rounded panel or card fills 1 - (4 - pi) r^2 / wh
# of its box -- 0.998 for y58_ssa_statement's 265x183pt panels (r ~ 10pt),
# 0.97 for c1_whitepaper's 154x57pt stat cards -- and a pill of radius h/2 at
# least 2.15x as wide as it is tall clears it too. A disc or an ellipse fills
# pi/4 = 0.785 of its box and never does, nor does any shape whose straight
# edges are diagonal (a speech-bubble tail, an arrow tag, a rotated square).
ROUNDED_FILL_MIN = 0.90
# ...and is more than this many points across in both directions. Anything
# smaller is a glyph or a list marker, which dialect.normalize reads from
# curves of that size (BULLET_MAX) and inference ignores (GLYPH_MAX).
ROUNDED_MIN_SIDE = 9.0


def rounded_rect_bbox(segs) -> Optional[BBox]:
    """The box of a path that is a rectangle with rounded corners, or None.

    `segs` is the path as ('m', (x, y)), ('l', (x, y)) and
    ('c', (x1, y1), (x2, y2), (x, y)) tuples in page space. The path must be
    ONE subpath with at least one curve, every straight segment must run
    along an axis, and its area -- the curves sampled -- must fill
    ROUNDED_FILL_MIN of its box. The box is taken from all points, control
    points included: a corner arc's control points lie on the edges it joins,
    so that is the geometric box and not the stroke-inflated ink envelope.

    Producers draw every rounded panel, card and pill this way (InDesign,
    Chromium, WeasyPrint, ReportLab's roundRect), and before this test each
    one was a 'complex' path -- artwork -- so the region it backed was
    rasterised with every paragraph inside it.
    """
    if not segs or segs[0][0] != "m":
        return None
    if sum(1 for s in segs if s[0] == "m") != 1 or not any(s[0] == "c" for s in segs):
        return None
    pts = [p for s in segs for p in s[1:]]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    w, h = x1 - x0, y1 - y0
    if w <= ROUNDED_MIN_SIDE or h <= ROUNDED_MIN_SIDE:
        return None
    tol = max(0.5, 0.02 * min(w, h))
    poly = [segs[0][1]]
    cur = segs[0][1]
    for s in segs[1:]:
        if s[0] == "l":
            p = s[1]
            if abs(p[0] - cur[0]) > tol and abs(p[1] - cur[1]) > tol:
                return None                     # a diagonal edge: not a box
            poly.append(p)
            cur = p
        elif s[0] == "c":
            (ax, ay), (bx, by), (cx, cy) = s[1], s[2], s[3]
            px, py = cur
            for k in range(1, 9):
                t = k / 8.0
                u = 1.0 - t
                poly.append((u * u * u * px + 3 * u * u * t * ax + 3 * u * t * t * bx
                             + t * t * t * cx,
                             u * u * u * py + 3 * u * u * t * ay + 3 * u * t * t * by
                             + t * t * t * cy))
            cur = (cx, cy)
        else:
            return None
    area = 0.0
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        area += ax * by - bx * ay
    if abs(area) / 2.0 < ROUNDED_FILL_MIN * w * h:
        return None
    return (x0, y0, x1, y1)


@dataclass
class UndecodedGlyph:
    """A glyph the parser saw drawn but could not decode to a character.

    PDFium's text page omits a glyph whose font offers it no usable charcode --
    not as U+0000, not as a PUA value, but by leaving it out of the page's
    character list entirely. The page-object layer still reports that something
    was drawn: where, at what size, in what colour, and nothing else.

    That is too little to put in `blocks` (there is no text) and it is not a
    path, so it is deliberately not put in `drawings` either -- inference reads
    `drawings` to find rules, table borders and figure regions, and a stream of
    positionless ink would corrupt all three. It travels here instead, where
    only `dialect` looks for it, and only to answer one question: is this a list
    marker? Everything that cannot be answered stays dropped.
    """
    origin: Tuple[float, float]   # baseline origin, top-left page coordinates
    size: float
    color: str                    # '#rrggbb'
    font: str = ""


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
    # Ink whose character the parser could not recover. See UndecodedGlyph.
    undecoded: List[UndecodedGlyph] = field(default_factory=list)
    # Characters the page's content stream shows but a reader does not see,
    # by reason ('offpage', 'tiny', 'invisible', 'clipped', 'background'), and
    # left out of `blocks`. Evidence, not content: nothing downstream reads
    # text from it.
    hidden_chars: Dict[str, int] = field(default_factory=dict)
    # Non-space characters in an OCR layer (invisible text over the page's
    # scan). Nonzero whether the layer became `blocks` or was left under its
    # image, so `scan` can tell a scan WITH text from one without.
    ocr_chars: int = 0
    # Placed images the parser could not extract. Counted so the conversion's
    # image report says what it lost instead of the drop being silent.
    images_dropped: int = 0


@dataclass
class DocIR:
    path: str
    pages: List[PageIR] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    # {font name: {character: advance in em}}, measured from the PDF's own
    # glyph advances (the PDFium backend fills it; see parse_pdfium
    # `_collect_advances`). Empty means unmeasured, never zero width.
    font_advances: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def summary(self) -> str:
        out = [f"{self.path}: {len(self.pages)} pages"]
        for p in self.pages:
            nspan = sum(len(l.spans) for b in p.blocks for l in b.lines)
            out.append(
                f"  p{p.number} {p.width:.0f}x{p.height:.0f}: "
                f"{len(p.blocks)} blocks / {nspan} spans, "
                f"{len(p.drawings)} drawings, {len(p.images)} images, {len(p.links)} links")
        return "\n".join(out)
