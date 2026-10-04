"""Real lists: which typed-marker paragraphs form numbered and bulleted lists.

Inference has always recognised list items -- a marker run and a tab
(`infer._marker_split_idx`) or a marker typed inside the item's own text
(`infer._inline_list_starts`) -- and emitted the marker as TEXT. A typed "3."
does not renumber when a reader inserts an item above it, and a typed bullet
carries no list semantics into Word or Docs. The benchmark counted 0 `w:numPr`
in every output of every tool, exactdoc's included (design audit finding 9).

This module reads those items as LISTS: which items belong together, at what
level, in what number format, from what start value. It decides nothing about
serialisation -- the paragraph keeps its typed marker runs, and whether a
profile writes `w:numPr` instead is a writer capability
(`options.PROFILE_CAPABILITIES`).

The rules, and the evidence each one stands on:

* A level is a marker column. Items whose marker starts at the same x (within
  `X_TOL`) are siblings; a marker further right opens a deeper level. Right-
  aligned labels ("9." / "10.") start at different x but share their TEXT
  column, so items with the same hanging text column are siblings too.
* A sequence is checked, never assumed. Lists are built by simulating the
  renderers' own counters -- a level counts up from its start, and an item at
  a higher level restarts every deeper one -- and an item whose source number
  is not what that simulation would print starts a new list at its own value.
  So the renderer prints exactly the source's numbers, or the list is split
  until it does: x03's "4." after a heading continues the list it belongs to,
  and its sub-level that keeps counting under a new parent ("3." where Word
  would print "1.") opens a list of its own.
* An ordinal marker alone is weak evidence. "v." opening a SCOTUS citation line
  ("v.<tab>Hillery, 474 U. S.") parses as roman five; "5." opens c6's section
  headings. A number becomes numbering only with a sibling at n-1 or n+1 in the
  same column and style, and never on a heading-sized line.
* Glyph bullets are unambiguous; a dash or asterisk needs a sibling, exactly as
  `infer._inline_list_starts` already requires for the typed form.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .layout import DocLayout, ListDef, ListItem, ListLevel, Para, Run

# Glyphs that are bullets wherever they stand. The union of infer.BULLET_CHARS
# and infer._INLINE_GLYPHS, minus the dashes, which need a sibling.
BULLET_GLYPHS = frozenset("•◦▪‣●○■□➤►♦❖➢✓✔∙⁃·")
DASH_BULLETS = frozenset("-–—*")
# Symbol/Wingdings bullets that reach the IR as private-use code points (the
# dialect already maps OpenSymbol's U+F0B7). The numbering level carries the
# Unicode glyph in an ordinary face, so no reader needs the symbol font.
PUA_BULLETS = {"": "•", "": "▪", "": "➢", "": "❖",
               "": "✓", "": "■"}

# Same marker column. The measured jitter between sibling markers is a few
# tenths of a point (x03: 18.0 throughout; y28: 35.9 vs 36.0 on one list); 2pt
# is the tolerance `infer._INLINE_X_TOL` already uses for the same question.
X_TOL = 2.0
# Right-aligned labels: siblings whose markers start apart by at most this,
# because the label widths differ ("9." vs "10." at 10-12pt is 5-7pt), share
# their text column.
LABEL_WIDTH_TOL = 12.0
# A list item set this much larger than the body is a numbered heading
# ("1. Executive summary" at 12.4pt over 9.3pt body on c1; c6's 14pt section
# heads over 10.5pt). Ordinary list text sits at body size (ratio 1.00 on every
# list measured: x03, x09, c1, c6, y28, y30).
HEADING_SIZE_RATIO = 1.2
MAX_LEVELS = 9                    # OOXML's w:ilvl range
# How far a tab-separated item's text column may sit from its level's before
# the level's tab stop would visibly move its text (see `_accepts`).
TAB_COL_TOL = 0.5

_ORD_RE = re.compile(r"^(\(?)(\d{1,3}|[ivxlcdm]{1,7}|[IVXLCDM]{1,7}|[a-zA-Z])"
                     r"(\.|\)|:)$")
_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman(tok: str) -> Optional[int]:
    """Value of a canonical roman numeral, else None ("iiii", "vx" are not)."""
    t = tok.lower()
    if not t or any(c not in _ROMAN for c in t):
        return None
    vals = [_ROMAN[c] for c in t]
    n = sum(-v if i + 1 < len(vals) and vals[i + 1] > v else v
            for i, v in enumerate(vals))
    return n if n > 0 and _to_roman(n) == t else None


def _to_roman(n: int) -> str:
    out = []
    for v, s in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"),
                 (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"),
                 (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


@dataclass
class Marker:
    kind: str                       # 'bullet' | 'dash' | 'ordinal'
    glyph: str = ""                 # bullet/dash glyph (Unicode)
    prefix: str = ""
    suffix: str = ""
    cands: Tuple[Tuple[str, int], ...] = ()   # (fmt, value) readings of an ordinal

    def family(self):
        """What must agree between siblings: kind, punctuation and letter case."""
        if self.kind != "ordinal":
            return (self.kind, self.glyph)
        case = "num" if self.cands[0][0] == "decimal" else \
            ("upper" if self.cands[0][0].startswith("upper") else "lower")
        return (self.kind, self.prefix, self.suffix, case)


def parse_marker(text: str) -> Optional[Marker]:
    """The list marker `text` spells, or None."""
    t = (text or "").strip()
    if not t:
        return None
    if len(t) == 1:
        g = PUA_BULLETS.get(t, t)
        if g in BULLET_GLYPHS:
            return Marker("bullet", glyph=g)
        if g in DASH_BULLETS:
            return Marker("dash", glyph=g)
    m = _ORD_RE.match(t)
    if not m:
        return None
    pre, tok, suf = m.groups()
    if pre and suf != ")":
        return None                 # "(1." is not a marker
    cands = []
    if tok.isdigit():
        cands.append(("decimal", int(tok)))
    else:
        upper = tok.isupper()
        if len(tok) == 1:
            cands.append(("upperLetter" if upper else "lowerLetter",
                          ord(tok.lower()) - 96))
        r = _roman(tok)
        if r is not None:
            cands.append(("upperRoman" if upper else "lowerRoman", r))
    if not cands:
        return None
    return Marker("ordinal", prefix=pre, suffix=suf, cands=tuple(cands))


@dataclass
class _Item:
    p: Para
    page: int
    marker_text: str
    sep: str
    mk: Marker
    run: Run
    mx: float                        # marker x, container-relative
    tx: Optional[float]              # text column of a hanging item
    style: tuple
    pi: int = 0                      # index in the document's flow paragraphs
    fmt: str = ""
    value: int = 0


def _style_key(r: Run):
    return (r.font, round(r.size * 2) / 2, r.bold, r.italic, r.color,
            r.superscript)


def typed_marker(p: Para):
    """(marker_text, sep, marker_run) of a paragraph that opens with a typed
    list marker, else None.

    Two forms reach here. A marker drawn as its own span arrives as marker
    run(s) and a tab run (`infer.para_from_lines`' split). A marker typed in
    the item's own text arrives inside the first run ("• Rebuilt…",
    "1. Install…") and is trusted only where `infer._inline_list_starts`
    already found list evidence for it (the `_list_item` flag).
    """
    runs = p.runs
    if not runs:
        return None
    for k in range(1, min(4, len(runs))):
        if runs[k].is_tab:
            mt = "".join(r.text for r in runs[:k])
            if mt.strip() and not any(r.is_tab for r in runs[:k]) and \
                    parse_marker(mt) is not None:
                return mt.strip(), "tab", runs[0]
            break
    if getattr(p, "_list_item", False):
        head = ""
        for r in runs[:3]:
            if r.is_tab or r.footnote is not None:
                break
            head += r.text
        m = re.match(r"^\s*(\S{1,8}?)[  ]+\S", head)
        if m and parse_marker(m.group(1)) is not None:
            return m.group(1), "space", runs[0]
    return None


def _dominant_size(p: Para) -> float:
    w = Counter()
    for r in p.runs:
        if r.text.strip() and not r.is_tab:
            w[r.size] += len(r.text)
    return max(w, key=w.get) if w else 0.0


def _collect(lay: DocLayout, body_size: float):
    """-> (items, lefts): the candidate items in document order, and the left
    edge of every flow paragraph, indexed by `_Item.pi`."""
    items, lefts = [], []
    for pg in lay.pages:
        for ch in pg.chunks:
            for el in ch.elements:
                if not isinstance(el, Para) or el.role:
                    continue
                pi = len(lefts)
                lefts.append(el.left_indent + min(0.0, el.first_indent))
                if el.heading or el.line_breaks or el.align in ("center", "right"):
                    continue            # headings, verbatim blocks, centred lines
                tm = typed_marker(el)
                if tm is None:
                    continue
                mtext, sep, run = tm
                if body_size > 0 and _dominant_size(el) >= HEADING_SIZE_RATIO * body_size:
                    continue
                mk = parse_marker(mtext)
                mx = el.left_indent + min(0.0, el.first_indent)
                tx = el.left_indent if el.first_indent < -1.0 else None
                items.append(_Item(el, pg.number, mtext, sep, mk, run, mx, tx,
                                   _style_key(run), pi=pi))
    return items, lefts


def _same_column(a: float, a_tx, b: float, b_tx) -> bool:
    if abs(a - b) <= X_TOL:
        return True
    return a_tx is not None and b_tx is not None and abs(a_tx - b_tx) <= X_TOL \
        and abs(a - b) <= LABEL_WIDTH_TOL


def _resolve_formats(items: List[_Item]) -> List[_Item]:
    """Keep the items with sibling evidence; fix each ordinal's format.

    An ordinal needs a sibling in the same column and family whose value is
    one away under the SAME format reading. That reading is the item's format:
    "i" next to "ii" is roman one, next to "h" or "j" the ninth letter.
    """
    keep = []
    by_family: Dict[tuple, List[_Item]] = {}
    for it in items:
        by_family.setdefault(it.mk.family(), []).append(it)
    for it in items:
        if it.mk.kind == "bullet":
            it.fmt = "bullet"
            keep.append(it)
            continue
        peers = [o for o in by_family[it.mk.family()] if o is not it
                 and _same_column(it.mx, it.tx, o.mx, o.tx)]
        if it.mk.kind == "dash":
            if peers:
                it.fmt = "bullet"
                keep.append(it)
            continue
        best = None
        for fmt, v in it.mk.cands:
            for o in peers:
                if any(f2 == fmt and abs(v2 - v) == 1 for f2, v2 in o.mk.cands):
                    # roman over letter when both readings have a sibling:
                    # "i ii iii" outnumbers "h i j" in every list measured
                    if best is None or fmt.endswith("Roman"):
                        best = (fmt, v)
                    break
        if best is not None:
            it.fmt, it.value = best
            keep.append(it)
    return keep


@dataclass
class _Level:
    mx: float
    tx: Optional[float]
    fmt: str = ""                    # "" until an item defines the level
    family: tuple = ()
    style: tuple = ()
    sep: str = ""
    start: int = 0
    counter: Optional[int] = None
    left: float = 0.0                # text column of the level's first item


@dataclass
class _List:
    levels: List[_Level] = field(default_factory=list)
    items: List[Tuple[_Item, int]] = field(default_factory=list)


def _level_of(lst: _List, it: _Item) -> Optional[int]:
    for k, lv in enumerate(lst.levels):
        if _same_column(it.mx, it.tx, lv.mx, lv.tx):
            return k
    return None


def _accepts(lv: _Level, it: _Item) -> bool:
    if not lv.fmt:
        return True
    if lv.fmt != it.fmt or lv.family != it.mk.family() or lv.style != it.style \
            or lv.sep != it.sep:
        return False
    # A tab after the marker goes to the LEVEL's tab stop in LibreOffice, not
    # to the paragraph's own indent or its own num tab: an item at 38.7pt in a
    # level set at 36.0 rendered its text 2.9pt short (y28 p36). Such an item
    # belongs to a list of its own.
    if it.sep == "tab" and abs(it.p.left_indent - lv.left) > TAB_COL_TOL:
        return False
    if it.fmt == "bullet":
        return True
    expected = lv.start if lv.counter is None else lv.counter + 1
    return it.value == expected


def _place(lst: _List, k: int, it: _Item):
    lv = lst.levels[k]
    if not lv.fmt:
        lv.fmt, lv.family, lv.style, lv.sep = it.fmt, it.mk.family(), it.style, it.sep
        lv.start = it.value if it.fmt != "bullet" else 1
        lv.left = it.p.left_indent
    lv.counter = it.value if it.fmt != "bullet" else (lv.counter or 0) + 1
    for deeper in lst.levels[k + 1:]:
        deeper.counter = None       # restarted by this parent item
    lst.items.append((it, k))


def _may_nest(lst: _List, it: _Item, lefts: List[float]) -> bool:
    """May `it` open a level below `lst`'s deepest one?

    A sub-list follows its parent item, with at most the parent's own
    continuation paragraphs between -- text set at the parent's text column.
    Anything set further left in between means the list ended there, and an
    indented list that comes later is a list of its own, not a level of this
    one.
    """
    prev = lst.items[-1][0]
    between = lefts[prev.pi + 1:it.pi]
    if not between:
        return True
    deep = lst.levels[-1]
    ref = deep.tx if deep.tx is not None else deep.mx + X_TOL
    return min(between) >= ref - X_TOL


def _build(items: List[_Item], lefts: List[float]) -> List[_List]:
    lists: List[_List] = []
    cur: Optional[_List] = None
    for it in items:
        if cur is not None:
            k = _level_of(cur, it)
            if k is not None:
                if _accepts(cur.levels[k], it):
                    _place(cur, k, it)
                    continue
                # The renderer would print something else here, so a new list
                # starts at this item -- always at ITS level 0. A list that
                # opens below level 0 is where the two renderers part: on
                # x03, LibreOffice counted the unused level 0 as started and
                # printed the next parent item one higher ("6." for "5."),
                # and it printed a level whose w:lvlRestart said 0 as
                # restarted ("1." for "3."). Lists that open at level 0 and
                # restart sub-levels under each parent print the same in both.
            elif it.mx > cur.levels[-1].mx + X_TOL and len(cur.levels) < MAX_LEVELS \
                    and _may_nest(cur, it, lefts):
                cur.levels.append(_Level(it.mx, it.tx))
                _place(cur, len(cur.levels) - 1, it)
                continue
        cur = _List(levels=[_Level(it.mx, it.tx)])
        lists.append(cur)
        _place(cur, 0, it)
    return [l for l in lists if l.items]


def _lvl_text(it: _Item, level: int) -> str:
    if it.fmt == "bullet":
        return it.mk.glyph
    return "%s%%%d%s" % (it.mk.prefix, level + 1, it.mk.suffix)


def assign_lists(lay: DocLayout, body_size: float = 0.0) -> int:
    """Read the document's typed-marker items as lists. Returns how many items
    were given a list; sets `Para.numbering` and fills `lay.lists`."""
    cands, lefts = _collect(lay, body_size)
    items = _resolve_formats(cands)
    lay.lists = []
    n = 0
    for lst in _build(items, lefts):
        lid = len(lay.lists)
        ld = ListDef(list_id=lid)
        by_level: Dict[int, List[_Item]] = {}
        for it, k in lst.items:
            by_level.setdefault(k, []).append(it)
        seps = {}
        for k, its in sorted(by_level.items()):
            lv = lst.levels[k]
            geo = Counter((round(i.p.left_indent, 1), round(-i.p.first_indent, 1))
                          for i in its)
            (left, hang), _n = geo.most_common(1)[0]
            # A typed space after the marker is an inter-word space, and in a
            # justified line it stretches with the others; the space a level's
            # w:suff draws does not, so every word after it sat up to 4pt left
            # of the typed form on y24's justified bullets. Such a level draws
            # nothing after its marker and the space stays in the text.
            sep = lv.sep
            if sep == "space" and any(i.p.align == "justify" for i in its):
                sep = "nothing"
            seps[k] = sep
            ld.levels[k] = ListLevel(fmt=lv.fmt, start=lv.start,
                                     text=_lvl_text(its[0], k), sep=sep,
                                     left=left, hanging=hang,
                                     marker_run=its[0].run)
        for it, k in lst.items:
            it.p.numbering = ListItem(list_id=lid, level=k, fmt=it.fmt,
                                      marker=it.marker_text, sep=seps[k],
                                      value=it.value)
            n += 1
        lay.lists.append(ld)
    return n
