"""Producer-dialect normalisation: PDF IR -> canonical IR.

The same visual element is emitted very differently by different PDF
generators. A list bullet, for example:

    ReportLab   a text character, same block as the item, gap >= 4pt
    WeasyPrint  a text character, separate block, butted flush (gap 0)
    Chromium    not text at all -- a filled bezier circle (a vector path)
    pdfTeX      a text character from a math font

`infer.py` reconstructs semantics from geometry. If the geometry it sees
depends on the producer, its thresholds silently encode "how ReportLab draws
things" instead of "what a bullet is". This module removes that coupling by
rewriting producer-specific idioms into one canonical form *before* inference
runs.

Everything here keys off **evidence observed in the page**, never off the
`/Producer` metadata string. Producer strings are absent (fpdf2 writes none),
rewritten by post-processors (Ghostscript, pdftk), and differ across versions
of the same engine. A metadata switch also fails catastrophically on the first
unknown producer, which is exactly the failure mode this module exists to
prevent. The detected fingerprint is recorded on `ir.meta` for diagnostics and
CI, and is deliberately not consulted for decisions.
"""
from typing import List, Optional

from .model import DocIR, PageIR, TextBlock, Line, Span, DrawCmd, bbox_overlap

# --- tunables, all in PDF points ------------------------------------------
BULLET_MAX = 9.0          # a list marker glyph is never larger than this
BULLET_ASPECT = 2.0       # max |w - h| for a marker glyph
BULLET_GAP = 46.0         # max distance from marker to the text it labels
BULLET_VTOL = 1.0         # vertical overlap tolerance, in marker heights
BACKDROP_COVER = 0.60     # page-area fraction that makes a fill a backdrop
BACKDROP_LUMA = 245       # min channel value for "invisible" light backdrop
# em. A producer splitting one visual line leaves fragments almost touching --
# a maths script boundary is ~0.1-0.3em, an inter-word space ~0.25em. Anything
# wider is a real gap, and on a two-column page it may be the gutter: joining
# across it fuses two columns into one enormous line that then re-wraps into
# many. Measured on a two-column paper, 1.6em cost five extra pages.
MAX_FRAGMENT_GAP = 0.55

# These are intentionally pairs, not a general PUA decoder.  A PUA value has
# no portable meaning on its own; it is only safe to translate where a known
# symbol face assigns it to a conventional list marker.
_SYMBOL_LIST_MARKERS = {("opensymbol", "\uf0b7"): "\u2022"}


def _luma_ok(hexcol: Optional[str]) -> bool:
    if not hexcol or len(hexcol) != 7:
        return False
    try:
        r, g, b = (int(hexcol[1:3], 16), int(hexcol[3:5], 16), int(hexcol[5:7], 16))
    except ValueError:
        return False
    return min(r, g, b) >= BACKDROP_LUMA


def _is_backdrop(d: DrawCmd, pw: float, ph: float) -> bool:
    """A page-covering light fill: painted by Chromium (and others) as the
    page background. Invisible on paper, but it touches every other drawing,
    so cluster union-find merges the whole page into one region."""
    if d.shape != "rect" or not d.fill:
        return False
    x0, y0, x1, y1 = d.bbox
    if (x1 - x0) * (y1 - y0) < BACKDROP_COVER * pw * ph:
        return False
    return _luma_ok(d.fill)


def _is_marker_glyph(d: DrawCmd) -> bool:
    """Small, solid, roughly square: the shape of a drawn bullet."""
    if not d.fill:
        return False
    x0, y0, x1, y1 = d.bbox
    w, h = x1 - x0, y1 - y0
    if not (0.4 < w <= BULLET_MAX and 0.4 < h <= BULLET_MAX):
        return False
    return abs(w - h) <= BULLET_ASPECT


def _labelled_line(bbox, lines: List[Line]) -> Optional[Line]:
    """The leftmost text line this glyph plausibly labels, or None.

    Takes a bbox rather than a DrawCmd because the same geometric question is
    asked of two different kinds of evidence: a drawn marker glyph, and a
    position where a glyph was drawn that could not be decoded.
    """
    x0, y0, x1, y1 = bbox
    cy, h = (y0 + y1) / 2, max(1.0, y1 - y0)
    best = None
    for ln in lines:
        lb = ln.bbox
        if lb[0] < x1 - 0.5:                       # text must start to the right
            continue
        if lb[0] - x1 > BULLET_GAP:
            continue
        if lb[1] - BULLET_VTOL * h <= cy <= lb[3] + BULLET_VTOL * h:
            if best is None or lb[0] < best.bbox[0]:
                best = ln
    return best


def _labels_a_line(d: DrawCmd, lines: List[Line]) -> bool:
    """True if this glyph sits just left of a text line it plausibly labels."""
    return _labelled_line(d.bbox, lines) is not None


def _bullet_block(x0: float, baseline: float, size: float,
                  color: Optional[str]) -> TextBlock:
    """The canonical form both marker recoveries produce: a one-span block."""
    bb = (x0, baseline - size * 0.94, x0 + size * 0.5, baseline)
    sp = Span(text="•", font="Arial", size=size,
              color=color or "#000000", bold=False, italic=False,
              mono=False, serif=False, superscript=False,
              bbox=bb, origin=(x0, baseline))
    return TextBlock(lines=[Line(spans=[sp], bbox=bb)], bbox=bb)


def _drop_backdrops(page: PageIR) -> int:
    keep = [d for d in page.drawings if not _is_backdrop(d, page.width, page.height)]
    n = len(page.drawings) - len(keep)
    page.drawings = keep
    return n


def _markers_to_text(page: PageIR) -> int:
    """Rewrite drawn bullet glyphs as one-span text blocks.

    This is deliberately a *translation*, not a special case: it converts the
    Chromium idiom into the separate-marker-box idiom that infer.py already
    reconstructs for WeasyPrint, so list handling has a single code path.
    """
    lines = [l for b in page.blocks for l in b.lines if l.horizontal]
    if not lines:
        return 0
    cand = [d for d in page.drawings if _is_marker_glyph(d)]
    if not cand:
        return 0
    hits = [d for d in cand if _labels_a_line(d, lines)]
    # A real list has repetition. A single small square is more likely to be a
    # decorative dot, so require corroboration before rewriting anything.
    if len(hits) < 2:
        return 0
    hitset = {id(d) for d in hits}
    page.drawings = [d for d in page.drawings if id(d) not in hitset]
    for d in hits:
        x0, y0, x1, y1 = d.bbox
        cy = (y0 + y1) / 2
        size, near = 10.0, None
        for ln in lines:
            lb = ln.bbox
            if lb[0] >= x1 - 0.5 and lb[0] - x1 <= BULLET_GAP and \
                    lb[1] - (y1 - y0) <= cy <= lb[3] + (y1 - y0):
                if near is None or lb[0] < near.bbox[0]:
                    near = ln
        if near is not None and near.spans:
            size = near.spans[0].size
        page.blocks.append(_bullet_block(x0, cy + size * 0.22, size, d.fill))
    page.blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    return len(hits)


# A marker set far smaller than the text it labels is not a marker. Measured
# across the expansion corpus, the two populations do not overlap and do not
# come close to it: every mark x03 promotes is 11.0pt against 11.0pt body text
# (ratio 1.0), while all 345 on y01 and all 623 on y03 report 1.0pt against
# ~10pt body (ratio 0.1). Those are PDF's default text size on an object whose
# font size was never set -- a positioning artifact, not ink anybody sees.
# The threshold sits in the empty middle of that gap.
UNDECODED_MIN_SIZE_RATIO = 0.5

# What a line already starting with a marker looks like. Narrower than
# infer.BULLET_CHARS on purpose: '-' and '*' start ordinary prose and code.
_MARKER_HEADS = set("•◦▪‣·○●♦")


def _line_text_size(ln: Line) -> float:
    """The size of the visible text on a line, 0.0 when there is none."""
    return max((s.size for s in ln.spans if s.text.strip()), default=0.0)


def _starts_with_marker(ln: Line) -> bool:
    head = ln.text.strip()[:1]
    return bool(head) and head in _MARKER_HEADS


def _undecoded_markers_to_text(page: PageIR) -> int:
    """Rewrite undecodable glyphs that sit in a list-marker slot as bullets.

    A glyph PDFium could not decode leaves nothing in `page.blocks` to
    normalise -- the text page does not report it at all -- so the only
    evidence is the position `parse_pdfium` recorded in `page.undecoded`.
    Position alone turned out to be far too weak a test, and the corpus said so
    loudly: on its first form this promoted 345 marks on y01 and 623 on y03,
    against 12 on x03, and sampling every one of them showed essentially none
    were list markers. y03 is the AES specification; its promotions were the
    column gaps of the S-box tables ('63 7c 77 7b f2...'), the operators of
    displayed equations ('= ({02} . s0,c)+({03} . s1,c)...') and matrix
    brackets. y01's were table-of-contents leaders between a section number and
    its title, and label/value separators whose 'item' was an existing bullet.

    So a mark has to bring the evidence a real list marker leaves, and three
    tests carry it. **Nothing may end to its left on its own baseline**: a
    marker's line starts after it, whereas a symbol inside running text has
    text on both sides -- that alone was 85% of the false promotions on both
    documents. **It must be ink at the item's own scale** (see
    UNDECODED_MIN_SIZE_RATIO); the remainder were 1pt artifacts. And **its host
    must be item text rather than another marker**, because a bullet in front
    of a bullet is not a list, it is a duplicate.

    What survives still has to repeat: at least two marks on the page must
    agree, the same corroboration `_markers_to_text` demands of a drawn one.
    Everything else stays dropped, deliberately -- producers emit empty text
    objects for trailing whitespace too, and x03 carries one at x=147.4 just
    past the end of 'binding constraint.' with bounds identical to a bullet's.

    Measured after: x03 unchanged at 12, y01 0, y03 0, y06 68 -> 7,
    c7_code 16 -> 0, x11_chrome_toc_headings 2 -> 0.
    """
    marks = getattr(page, "undecoded", None)
    if not marks:
        return 0
    lines = [l for b in page.blocks for l in b.lines if l.horizontal]
    if not lines:
        return 0
    hits = []
    for m in marks:
        x, y = m.origin
        near = _labelled_line((x, y, x, y), lines)
        if near is None:
            continue
        # A list puts ONE marker in front of an item. Several marks strung
        # along a single baseline are spacing, and on a monospace listing they
        # are unmistakable: c7_code reports 202 marks, in runs 5.1pt apart --
        # exactly one character advance at its 11.3pt Courier -- which is the
        # listing's own indentation. Only the leading mark of such a run has
        # nothing to its left, so the left-text test above passes it and 16
        # bullets used to land inside the code. x11_chrome_toc_headings is the
        # same story with 492. Every one of x03's twelve is alone on its
        # baseline, because that is what a list looks like.
        if sum(1 for o in marks
               if abs(o.origin[1] - y) <= BULLET_VTOL) > 1:
            continue
        # Text to the left on this baseline: the mark is inside a line, not in
        # front of one.
        if any(ln.bbox[2] <= x + 0.5 and
               ln.bbox[1] - BULLET_VTOL <= y <= ln.bbox[3] + BULLET_VTOL
               for ln in lines):
            continue
        host_size = _line_text_size(near)
        # An unmeasurable host is not a licence to promote: absent evidence is
        # not evidence.
        if host_size <= 0 or m.size < UNDECODED_MIN_SIZE_RATIO * host_size:
            continue
        if _starts_with_marker(near):
            continue
        hits.append((m, near))
    if len(hits) < 2:
        return 0
    for m, near in hits:
        size = m.size
        if size <= 0.4 and near.spans:
            size = near.spans[0].size
        page.blocks.append(_bullet_block(m.origin[0], m.origin[1],
                                         size or 10.0, m.color))
    page.blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    page.undecoded = [m for m in marks
                      if all(m is not h for h, _ in hits)]
    return len(hits)


def _symbol_list_marker_candidates(page: PageIR):
    """Find known PUA bullets that have the geometry of an inline marker.

    The font/codepoint pair supplies the semantic evidence; being the first
    ink on a horizontal row, immediately followed by body text, and having a
    small glyph box supplies the layout evidence.  Both are needed: symbol
    fonts also contain decorative glyphs, and PUA text in an ordinary font is
    not portable enough to guess at.
    """
    out = []
    for block in page.blocks:
        for line in block.lines:
            if not line.horizontal or not line.spans:
                continue
            first = next((i for i, span in enumerate(line.spans)
                          if span.text.strip()), None)
            if first is None:
                continue
            marker = line.spans[first]
            key = ("".join(marker.font.lower().split()), marker.text.strip())
            bullet = _SYMBOL_LIST_MARKERS.get(key)
            if bullet is None:
                continue
            body = next((span for span in line.spans[first + 1:]
                         if span.text.strip()), None)
            if body is None or body.bbox[0] < marker.bbox[2] - 0.5:
                continue
            mw, mh = marker.bbox[2] - marker.bbox[0], marker.bbox[3] - marker.bbox[1]
            # A genuine marker is no wider than roughly one em and no taller
            # than its adjacent body run.  This admits OpenSymbol's 11pt
            # bullet while rejecting display-size symbol artwork.
            if mw <= 0.4 or mw > max(2.0, 1.05 * body.size) or \
                    mh <= 0.4 or mh > 1.5 * body.size or \
                    marker.size > 1.2 * body.size:
                continue
            if body.bbox[0] - marker.bbox[2] > BULLET_GAP:
                continue
            out.append((line, marker, body, bullet))
    return out


def _normalize_symbol_list_markers(page: PageIR) -> int:
    """Canonicalise corroborated leading symbol-font PUA list markers."""
    candidates = _symbol_list_marker_candidates(page)
    if len(candidates) < 2:
        return 0

    # A list repeats both its marker edge and its item-text edge.  Requiring a
    # two-row cluster prevents unrelated symbol glyphs elsewhere on the page
    # from gaining list semantics merely because they share a font/codepoint.
    accepted = set()
    for _, marker, body, bullet in candidates:
        x_tol = max(2.0, 0.25 * body.size)
        group = [(ln, m, b, canon) for ln, m, b, canon in candidates
                 if canon == bullet and abs(m.bbox[0] - marker.bbox[0]) <= x_tol
                 and abs(b.bbox[0] - body.bbox[0]) <= x_tol]
        if len(group) >= 2:
            accepted.update(id(m) for _, m, _, _ in group)

    changed = 0
    for _, marker, body, bullet in candidates:
        if id(marker) not in accepted:
            continue
        # Keep any source separator in this span: infer's marker splitter uses
        # it when the text box is flush.  Arial is safe in Google Docs and the
        # following body span remains untouched.
        suffix = marker.text[len(marker.text.rstrip()):]
        marker.text = bullet + suffix
        marker.font = "Arial"
        marker.serif = False
        changed += 1
    return changed


def _split_rotated(page: PageIR) -> int:
    """Move non-horizontal text out of the flow.

    LaTeX/arXiv stamps a rotated identifier down the left margin. Emitted as a
    normal paragraph it becomes a full-width horizontal line that pushes the
    whole page down. Word has no editable rotated-text construct that Google
    Docs imports, so the honest options are 'drop from flow' or 'rasterise';
    we take it out of the flow and record it for the writer.
    """
    moved = 0
    for b in page.blocks:
        rot = [l for l in b.lines if not l.horizontal]
        if not rot:
            continue
        b.lines = [l for l in b.lines if l.horizontal]
        moved += len(rot)
        page.rotated.extend(rot)
    page.blocks = [b for b in page.blocks if b.lines]
    return moved


def _line_size(ln: Line) -> float:
    return max((s.size for s in ln.spans), default=10.0)


def _coalesce_row_fragments(page: PageIR) -> int:
    """Rejoin one visual line that a producer split across several blocks.

    pdfTeX emits inline maths as separate text blocks: the run before the
    script, the script itself, the run after. They share a baseline but sit in
    different blocks, and inference rebuilds its paragraph flow from blocks --
    so each fragment became its own single-line paragraph. One measured page
    turned two source lines into eight paragraphs; every fragment then consumed
    a full line, the page overflowed, and since each source page ends in a hard
    break the overflow cost a whole page. That was the bulk of LaTeX page
    inflation, and none of it was re-wrap.

    Fragments are joined only when they share a baseline AND are horizontally
    close. The proximity test is what keeps two-column layouts intact: those
    also share baselines across the gutter, but are an inch apart.
    """
    flat = [(bi, ln) for bi, b in enumerate(page.blocks) for ln in b.lines
            if ln.horizontal and ln.spans]
    rows = {}
    for bi, ln in flat:
        sz = _line_size(ln)
        key = None
        for base in rows:
            if abs(ln.baseline - base) <= max(1.2, 0.18 * sz):
                key = base
                break
        rows.setdefault(key if key is not None else round(ln.baseline, 2),
                        []).append((bi, ln))

    # Absorb raised/lowered scripts. A subscript sits on its own baseline by
    # definition, so baseline grouping alone leaves it stranded as its own
    # paragraph -- which is most of what is left of the maths problem.
    for base in sorted(rows, key=lambda b: -len(rows[b])):
        host = rows.get(base)
        if not host:
            continue
        hsz = max(_line_size(l) for _, l in host)
        hx0 = min(l.bbox[0] for _, l in host)
        hx1 = max(l.bbox[2] for _, l in host)
        for other in [b for b in list(rows) if b != base]:
            grp = rows.get(other)
            if not grp:
                continue
            if any(_line_size(l) >= 0.92 * hsz for _, l in grp):
                continue                       # full-size: a real line
            # scripts are short. A wide fragment at a nearby baseline is a
            # genuine line of small type (a caption, a footnote), not a script.
            if any((l.bbox[2] - l.bbox[0]) > 0.25 * max(1.0, hx1 - hx0)
                   for _, l in grp):
                continue
            if abs(other - base) > 0.75 * hsz:
                continue                       # outside the em box
            if any(l.bbox[0] < hx0 - 2.0 or l.bbox[0] > hx1 + 0.6 * hsz
                   for _, l in grp):
                continue                       # not adjacent horizontally
            for _, l in grp:
                if l.baseline < base - 0.12 * hsz:
                    for s in l.spans:
                        s.superscript = True
            host.extend(grp)
            del rows[other]

    joined = 0
    for base, items in rows.items():
        if len({bi for bi, _ in items}) < 2:
            continue                       # already one block: nothing to do
        items.sort(key=lambda t: t[1].bbox[0])
        # split into horizontally-contiguous groups
        groups, cur = [], [items[0]]
        for prev, nxt in zip(items, items[1:]):
            gap = nxt[1].bbox[0] - prev[1].bbox[2]
            if gap > MAX_FRAGMENT_GAP * _line_size(prev[1]):
                groups.append(cur)
                cur = [nxt]
            else:
                cur.append(nxt)
        groups.append(cur)
        for grp in groups:
            if len({bi for bi, _ in grp}) < 2:
                continue
            host_bi = grp[0][0]
            spans, bb = [], None
            for k, (bi, ln) in enumerate(grp):
                if k and spans and not spans[-1].text.endswith(" "):
                    gap = ln.bbox[0] - grp[k - 1][1].bbox[2]
                    if gap > 0.22 * _line_size(ln):
                        spans[-1].text += " "
                spans.extend(ln.spans)
                bb = (ln.bbox if bb is None else
                      (min(bb[0], ln.bbox[0]), min(bb[1], ln.bbox[1]),
                       max(bb[2], ln.bbox[2]), max(bb[3], ln.bbox[3])))
            merged = Line(spans=spans, bbox=bb, dir=grp[0][1].dir)
            drop = {id(ln) for _, ln in grp}
            for bi, b in enumerate(page.blocks):
                b.lines = [l for l in b.lines if id(l) not in drop]
            page.blocks[host_bi].lines.append(merged)
            page.blocks[host_bi].lines.sort(key=lambda l: (round(l.baseline, 1),
                                                          l.bbox[0]))
            joined += len(grp) - 1

    page.blocks = [b for b in page.blocks if b.lines]
    for b in page.blocks:
        bb = None
        for l in b.lines:
            bb = (l.bbox if bb is None else
                  (min(bb[0], l.bbox[0]), min(bb[1], l.bbox[1]),
                   max(bb[2], l.bbox[2]), max(bb[3], l.bbox[3])))
        b.bbox = bb
    page.blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    return joined


def _ruled_bands(page: PageIR):
    """Y-bands that look like tables, from the ruling lines.

    Whether two lines sharing a baseline belong together -- cells of one row,
    or unrelated text that merely lines up -- cannot be decided from the text
    alone. Measured over the corpus, the same-baseline gaps inside a table and
    the coincidental ones have identical distributions (median 4.7em for both),
    so no width threshold separates them, and five attempts at one oscillated
    between 3 and 4 regressions instead of converging.

    The ruling lines settle it, and a parser does not have them. This does: a
    band spanned by two or more horizontal rules that overlap in x is a table,
    and inside such a band same-baseline lines are cells and may be joined.
    """
    raw_rules = [d for d in page.drawings
                 if d.shape == "hline" and (d.bbox[2] - d.bbox[0]) > 24]
    if len(raw_rules) < 2:
        return []
    # Merge rules that share a y FIRST. A table's borders are drawn per cell,
    # so several sit side by side on one line; sorted by y, consecutive ones
    # then have zero horizontal overlap and every band breaks at the first
    # pair. One measured page had 70 rules and produced no bands at all.
    raw_rules.sort(key=lambda d: (round(d.bbox[1], 1), d.bbox[0]))
    rules = []
    for d in raw_rules:
        if rules and abs(d.bbox[1] - rules[-1][1]) <= 2.0:
            r = rules[-1]
            rules[-1] = (min(r[0], d.bbox[0]), r[1], max(r[2], d.bbox[2]), r[3])
        else:
            rules.append((d.bbox[0], d.bbox[1], d.bbox[2], d.bbox[3]))
    if len(rules) < 2:
        return []

    bands, cur = [], [rules[0]]
    for prev, r in zip(rules, rules[1:]):
        ox = min(prev[2], r[2]) - max(prev[0], r[0])
        w = max(1.0, min(prev[2] - prev[0], r[2] - r[0]))
        if ox > 0.5 * w and (r[1] - prev[3]) < 220:
            cur.append(r)
        else:
            bands.append(cur)
            cur = [r]
    bands.append(cur)
    out = []
    for grp in bands:
        if len(grp) < 2:
            continue
        out.append((min(d[0] for d in grp) - 6, min(d[1] for d in grp) - 4,
                    max(d[2] for d in grp) + 6, max(d[3] for d in grp) + 4))
    return out


def _join_ruled_rows(page: PageIR) -> int:
    """Inside a ruled band, join blocks whose lines share a baseline."""
    bands = _ruled_bands(page)
    if not bands:
        return 0

    def in_band(ln):
        cx = (ln.bbox[0] + ln.bbox[2]) / 2
        cy = (ln.bbox[1] + ln.bbox[3]) / 2
        for b in bands:
            if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
                return b
        return None

    rows = {}
    for bi, b in enumerate(page.blocks):
        for ln in b.lines:
            if not ln.horizontal or not ln.spans:
                continue
            band = in_band(ln)
            if band is None:
                continue
            key = (id(band) if False else band, round(ln.baseline, 0))
            rows.setdefault(key, []).append((bi, ln))

    joined = 0
    for _, items in rows.items():
        if len({bi for bi, _ in items}) < 2:
            continue
        items.sort(key=lambda t: t[1].bbox[0])
        host = items[0][0]
        drop = {id(ln) for _, ln in items[1:]}
        for b in page.blocks:
            b.lines = [l for l in b.lines if id(l) not in drop]
        for _, ln in items[1:]:
            page.blocks[host].lines.append(ln)
        page.blocks[host].lines.sort(key=lambda l: (round(l.baseline, 1), l.bbox[0]))
        joined += len(items) - 1

    page.blocks = [b for b in page.blocks if b.lines]
    for b in page.blocks:
        bb = None
        for l in b.lines:
            bb = (l.bbox if bb is None else
                  (min(bb[0], l.bbox[0]), min(bb[1], l.bbox[1]),
                   max(bb[2], l.bbox[2]), max(bb[3], l.bbox[3])))
        b.bbox = bb
    page.blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    return joined


def fingerprint(ir: DocIR) -> dict:
    """Observable dialect traits. Diagnostics and CI only -- never a switch."""
    fp = {"producer": (ir.meta or {}).get("producer", "") or "",
          "creator": (ir.meta or {}).get("creator", "") or ""}
    n_curve = n_rect = n_backdrop = n_marker = n_rot = 0
    for p in ir.pages:
        for d in p.drawings:
            if d.shape in ("curve", "complex"):
                n_curve += 1
            if d.shape == "rect":
                n_rect += 1
            if _is_backdrop(d, p.width, p.height):
                n_backdrop += 1
            if _is_marker_glyph(d):
                n_marker += 1
        for b in p.blocks:
            for l in b.lines:
                if not l.horizontal:
                    n_rot += 1
    fp.update({"curves": n_curve, "rects": n_rect, "backdrops": n_backdrop,
               "vector_markers": n_marker, "rotated_lines": n_rot,
               "pages": len(ir.pages)})
    return fp


def normalize(ir: DocIR) -> DocIR:
    """Rewrite producer idioms into canonical form. Mutates and returns `ir`."""
    stats = {"backdrops": 0, "vector_markers": 0, "symbol_markers": 0,
             "undecoded_markers": 0, "rotated": 0, "row_joins": 0,
             "ruled_rows": 0}
    for p in ir.pages:
        if not hasattr(p, "rotated"):
            p.rotated = []
        stats["backdrops"] += _drop_backdrops(p)
        stats["rotated"] += _split_rotated(p)
        stats["vector_markers"] += _markers_to_text(p)
        stats["undecoded_markers"] += _undecoded_markers_to_text(p)
        stats["symbol_markers"] += _normalize_symbol_list_markers(p)
        stats["row_joins"] += _coalesce_row_fragments(p)
        stats["ruled_rows"] += _join_ruled_rows(p)
    ir.meta = dict(ir.meta or {})
    ir.meta["_dialect"] = fingerprint(ir)
    ir.meta["_normalized"] = stats
    return ir
