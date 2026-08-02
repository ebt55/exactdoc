"""Structure inference: PageIR -> DocLayout (semantic, writer-ready)."""
import re
from collections import Counter, defaultdict
from statistics import median
from typing import List, Optional, Tuple, Dict, Any

from .model import (DocIR, PageIR, TextBlock, Line, Span, DrawCmd, ImageObj,
                    BBox, bbox_union, bbox_overlap, bbox_area, contains)
from .layout import (Run, Para, Cell, TableEl, FigureEl, ImageEl, RuleEl,
                     ColBreak, Chunk, PageLayout, HFPart, DocLayout)

BULLET_CHARS = set("•◦▪‣·-–—*➤►○●♦")
NUM_RE = re.compile(r"^\(?(\d{1,3}|[a-zA-Z]|[ivxlIVXL]{1,5})[\.\)\:]$")

# --- figure-detection budget ----------------------------------------------
# A figure region is rasterised, so anything it swallows stops being editable
# text. These caps make that trade explicit and bounded.
GLYPH_MAX = 9.0            # pt; shapes this small are glyphs, not artwork
RULE_THICK = 2.5           # pt; thinner than this is a rule, not a shape
MAX_FIG_GROWTH = 4.0       # a figure may not exceed 4x its seed area
MAX_FIG_PAGE_FRAC = 0.55   # ...nor 55% of the page
MAX_FIG_TEXT_FRAC = 0.35   # ...nor swallow more than 35% of a page's text


def _thin(d: DrawCmd) -> bool:
    x0, y0, x1, y1 = d.bbox
    return min(x1 - x0, y1 - y0) <= RULE_THICK


def _mode(vals, nd=1):
    if not vals:
        return 0.0
    c = Counter(round(v, nd) for v in vals)
    return c.most_common(1)[0][0]


def _cluster(vals: List[float], tol: float) -> List[float]:
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(c) / len(c) for c in out]


def _margin_cluster(vals: List[float], left=True) -> Optional[float]:
    if not vals:
        return None
    cl = _cluster(vals, 2.5)
    n = len(vals)
    good = []
    for c in cl:
        cnt = sum(1 for v in vals if abs(v - c) <= 2.5)
        if cnt >= max(3, 0.08 * n):
            good.append(c)
    if not good:
        return None
    return (min(good) if left else max(good))


# ------------------------------------------------------------------ runs/paras
def _soft_join(runs: List[Run], next_text: str):
    """Append a joiner between wrapped lines: space normally, dehyphenate
    when the previous line ends with a hyphenated word break."""
    if not runs:
        return
    last = runs[-1].text
    nxt = next_text.lstrip()[:1]
    if last.endswith("-") and len(last) >= 2 and last[-2].isalpha() and nxt.islower():
        runs[-1].text = last[:-1]
    elif not last.endswith((" ", "-")):
        runs[-1].text += " "


def runs_from_spans(spans: List[Span]) -> List[Run]:
    runs: List[Run] = []
    for s in spans:
        # justified text extracts stretched word gaps as doubled spaces;
        # collapse them (except in monospace) so re-wrap matches the source
        txt = s.text if s.mono else re.sub(r" {2,}", " ", s.text)
        r = Run(text=txt, font=s.font, size=s.size, color=s.color,
                bold=s.bold, italic=s.italic, mono=s.mono, serif=s.serif,
                link=s.link, underline=bool(getattr(s, "_ul", False)),
                superscript=s.superscript)
        if runs:
            p = runs[-1]
            if (p.font == r.font and abs(p.size - r.size) < 0.05 and p.color == r.color
                    and p.bold == r.bold and p.italic == r.italic and p.link == r.link
                    and p.underline == r.underline and p.superscript == r.superscript):
                if not p.mono and p.text.endswith(" ") and r.text.startswith(" "):
                    p.text += r.text.lstrip(" ")
                else:
                    p.text += r.text
                continue
            if not r.mono and runs[-1].text.endswith(" ") and r.text.startswith(" "):
                r.text = r.text.lstrip(" ") or r.text
        runs.append(r)
    return runs


def _line_size(ln: Line) -> float:
    return max((s.size for s in ln.spans), default=10.0)


def _merge_row_lines(lines: List[Line]) -> List[Line]:
    """Merge Line fragments that share a baseline into single visual rows.

    PDF producers split lines at link/style boundaries; alignment analysis
    needs whole visual rows.

    Grouping is by BASELINE, not by bbox top. Tops disagree whenever glyph
    heights disagree -- a fragment reading "R^{d x d}" is far taller than one
    reading "i" even though both sit on the same baseline -- so top-grouping
    silently split every line of inline maths into separate rows, and each
    fragment then became its own single-line paragraph. One measured pdfTeX
    page turned two source lines into eight paragraphs; each consumed a full
    line, the page overflowed, and since every source page ends in a hard
    break the overflow cost a whole page. That was the bulk of LaTeX page
    inflation.

    A second pass then absorbs true super/subscripts: smaller fragments whose
    baseline is shifted but which still sit inside the host row's em box.
    """
    rows: List[List[Line]] = []
    for ln in sorted(lines, key=lambda l: (round(l.baseline, 1), l.bbox[0])):
        placed = False
        for row in rows:
            tol = max(1.2, 0.18 * _line_size(row[0]))
            if abs(ln.baseline - row[0].baseline) < tol:
                row.append(ln)
                placed = True
                break
        if not placed:
            rows.append([ln])

    # absorb raised/lowered script fragments into the row they belong to
    rows.sort(key=lambda r: min(l.baseline for l in r))
    merged = True
    while merged:
        merged = False
        for i, frag in enumerate(rows):
            if len(frag) != 1:
                continue
            f = frag[0]
            fsz = _line_size(f)
            for j, host in enumerate(rows):
                if i == j or not host:
                    continue
                hsz = max(_line_size(l) for l in host)
                if fsz >= 0.92 * hsz:
                    continue                      # same size: a real line
                hb = host[0].baseline
                if abs(f.baseline - hb) > 0.75 * hsz:
                    continue                      # outside the em box
                hx0 = min(l.bbox[0] for l in host)
                hx1 = max(l.bbox[2] for l in host)
                if f.bbox[0] < hx0 - 2.0 or f.bbox[0] > hx1 + 0.5 * hsz:
                    continue                      # not adjacent horizontally
                for s in f.spans:
                    if f.baseline < hb - 0.12 * hsz:
                        s.superscript = True
                host.append(f)
                rows.pop(i)
                merged = True
                break
            if merged:
                break

    out = []
    for row in rows:
        row.sort(key=lambda l: l.bbox[0])
        if len(row) == 1:
            out.append(row[0])
            continue
        spans = []
        for i, ln in enumerate(row):
            if i > 0 and spans:
                gap = ln.bbox[0] - row[i - 1].bbox[2]
                if gap > 0.25 * (spans[-1].size or 10) and \
                        not spans[-1].text.endswith(" "):
                    spans[-1].text += " "
            spans.extend(ln.spans)
        bb = None
        for ln in row:
            bb = bbox_union(bb, ln.bbox)
        out.append(Line(spans=spans, bbox=bb, dir=row[0].dir))
    out.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
    return out


def _marker_split_idx(spans) -> Optional[int]:
    """Index k such that spans[:k+1] form a list marker followed by item text.

    Separation counts if there is a real gap OR the marker span carries its
    own trailing space (WeasyPrint markers sit flush against the text box).
    """
    for j in range(min(3, len(spans) - 1)):
        prefix = "".join(s.text for s in spans[:j + 1])
        sep = (spans[j + 1].bbox[0] - spans[j].bbox[2] >= 2.0) or \
            prefix.endswith(" ")
        m = prefix.strip()
        if sep and m and (m in BULLET_CHARS or NUM_RE.match(m)):
            return j
        if len(m) > 4:
            return None
    return None


def _line_starts_with_marker(ln: Line) -> bool:
    if len(ln.spans) < 2:
        return False
    return _marker_split_idx(ln.spans) is not None


def _split_lines_to_paras(lines: List[Line]) -> List[List[Line]]:
    """Group a flat list of lines into paragraphs on large baseline gaps,
    dominant-size jumps, or list-marker starts."""
    lines = _merge_row_lines(lines)
    if len(lines) <= 1:
        return [lines] if lines else []
    deltas = [b.bbox[1] - a.bbox[1] for a, b in zip(lines, lines[1:])]
    pos = [d for d in deltas if d > 0.5]
    lead = sorted(pos)[len(pos) // 2] if pos else 12.0

    def dom_size(ln):
        best, n = 10.0, 0
        for s in ln.spans:
            if len(s.text) > n:
                best, n = s.size, len(s.text)
        return best

    groups, cur = [], [lines[0]]
    for i, ln in enumerate(lines[1:]):
        sz_prev = dom_size(cur[-1])
        sz_new = dom_size(ln)
        size_jump = max(sz_prev, sz_new) > 1.3 * max(0.1, min(sz_prev, sz_new))
        if deltas[i] > max(lead * 1.55, lead + 4.0) or size_jump \
                or _line_starts_with_marker(ln):
            groups.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    groups.append(cur)
    return groups


def para_from_lines(lines: List[Line], col_l: float, col_r: float) -> Para:
    lines = _merge_row_lines(lines)
    bbox = None
    for ln in lines:
        bbox = bbox_union(bbox, ln.bbox)
    p = Para(bbox=bbox)
    p._vis_lines = len(lines)
    first_sz = lines[0].spans[0].size if lines[0].spans else 10.0
    p._b1 = lines[0].baseline
    p._size1 = first_sz
    if len(lines) >= 2:
        base = [ln.baseline for ln in lines]
        diffs = [b2 - b1 for b1, b2 in zip(base, base[1:]) if b2 > b1]
        p.leading = round(sorted(diffs)[len(diffs) // 2], 2) if diffs else 0.0
    else:
        # exact single-line height: a hair above natural so nothing clips
        p.leading = round(max(first_sz * 1.16, 4.0), 2)
    xs0 = [ln.bbox[0] for ln in lines]
    xs1 = [ln.bbox[2] for ln in lines]
    ccx = (col_l + col_r) / 2
    if len(lines) >= 2:
        left_flush = all(abs(x - xs0[0]) < 1.5 for x in xs0)
        # a paragraph may justify against an inset right edge (e.g. an
        # indented abstract); detect the consistent edge and pin it with a
        # right indent so the wrap width matches exactly
        edge = max(xs1[:-1]) if len(xs1) > 1 else xs1[0]
        right_flush = all(abs(x - edge) < 3.0 for x in xs1[:-1])
        centered = all(abs((a + b) / 2 - ccx) < 2.5 for a, b in zip(xs0, xs1))
        if centered and not (left_flush and abs(xs0[0] - col_l) < 2):
            p.align = "center"
        elif left_flush and right_flush and len(lines) >= 3:
            p.align = "justify"
            if col_r - edge > 4.0:
                p.right_indent = round(col_r - edge, 1)
        elif left_flush and right_flush and abs(edge - col_r) < 3.0:
            p.align = "justify"
        elif all(abs(x - col_r) < 2.5 for x in xs1) and xs0[0] - col_l > 6:
            p.align = "right"
        else:
            p.align = "left"
    else:
        x0, x1 = xs0[0], xs1[0]
        if abs((x0 + x1) / 2 - ccx) < 2.5 and x0 - col_l > 8 and col_r - x1 > 8:
            p.align = "center"
        elif col_r - x1 < 2.5 and x0 - col_l > 10:
            p.align = "right"
    minx = min(xs0)
    p.left_indent = max(0.0, round(minx - col_l, 1))
    if p.align in ("left", "justify"):
        fi = round(lines[0].bbox[0] - minx, 1)
        if abs(fi) > 1.0:
            p.first_indent = fi
    if p.align == "center":
        p.left_indent = 0.0
    p.runs = []
    p.src_lines = len(lines)
    p.src_widths = [round(ln.bbox[2] - ln.bbox[0], 1) for ln in lines]
    for i, ln in enumerate(lines):
        p.runs.extend(runs_from_spans(ln.spans))
        if i < len(lines) - 1:
            _soft_join(p.runs, lines[i + 1].text)
    # ``right_flush`` deliberately ignores the final source line: that is how
    # a normal justified paragraph has a ragged last line.  A short metadata
    # block can look the same to that heuristic, except its final row is wider
    # than the inferred inset.  Serialising that as one justified paragraph
    # gives it an impossible wrap width (the memo's Date row then wraps in
    # Google Docs).  Record its source rows only when the geometry proves the
    # inset cannot contain the longest row.  Ordinary narrow justified prose
    # still has a longest source row that fits its inferred width and remains
    # reflowable.
    inferred_w = col_r - col_l - p.left_indent - p.right_indent
    if p.align == "justify" and p.right_indent > 0.05 and len(lines) >= 2 and \
            p.src_widths and max(p.src_widths) > inferred_w + 1.0:
        # This is deliberately not a global layout mutation: standard DOCX
        # preserves its long-standing flowing paragraph, while the Google Docs
        # writer consumes these rows as soft breaks at a usable width.
        p.gdocs_rows = [runs_from_spans(ln.spans) for ln in lines]
    # bullet / numbered list detection
    spans0 = lines[0].spans
    if len(spans0) >= 2:
        k = _marker_split_idx(spans0)
        if k is not None:
            text_x = spans0[k + 1].bbox[0]
            p.left_indent = max(0.0, round(text_x - col_l, 1))
            p.first_indent = round(spans0[0].bbox[0] - text_x, 1)
            p.tab_stops = [(p.left_indent, "left")]
            mruns = runs_from_spans(spans0[:k + 1])
            for mr in mruns:
                mr.text = mr.text.rstrip(" ")
            runs = [m for m in mruns if m.text]
            runs.append(Run(text="\t", font=spans0[0].font, size=spans0[0].size,
                            color=spans0[0].color, is_tab=True))
            runs += runs_from_spans(spans0[k + 1:])
            for ln in lines[1:]:
                _soft_join(runs, ln.text)
                runs.extend(runs_from_spans(ln.spans))
            p.runs = runs
    return p


def paras_from_line_list(lines: List[Line], col_l: float, col_r: float) -> List[Para]:
    out = []
    ccx = (col_l + col_r) / 2
    for grp in _split_lines_to_paras(lines):
        if not grp:
            continue
        # centered short lines with strongly varying widths are separate
        # paragraphs (title/author blocks), not one wrapped paragraph
        if len(grp) >= 2:
            centered = all(abs((l.bbox[0] + l.bbox[2]) / 2 - ccx) < 3.5 and
                           l.bbox[0] - col_l > 8 for l in grp)
            if centered:
                ws = [l.bbox[2] - l.bbox[0] for l in grp[:-1]]
                if ws and (max(ws) - min(ws)) > 0.3 * max(ws):
                    for l in grp:
                        out.append(para_from_lines([l], col_l, col_r))
                    continue
        out.append(para_from_lines(grp, col_l, col_r))
    return out


# ------------------------------------------------------------------ HF detect
def _norm_text(t: str) -> str:
    return re.sub(r"\d+", "#", t.strip())


def detect_hf(ir: DocIR):
    n = len(ir.pages)
    H = ir.pages[0].height if ir.pages else 792
    W = ir.pages[0].width if ir.pages else 612
    res = {
        "consumed_text": defaultdict(set), "consumed_draw": defaultdict(set),
        "band_first": None, "band_def": None, "rep_lines": defaultdict(list),
        "rep_draws": defaultdict(list), "line_roles": {},
    }
    if n == 0:
        return res

    def top_bands(p: PageIR):
        cands = []
        for i, d in enumerate(p.drawings):
            x0, y0, x1, y1 = d.bbox
            if d.fill and (x1 - x0) >= 0.95 * W and (y1 - y0) >= 2.5 and y0 <= 220:
                cands.append((i, d))
        cands.sort(key=lambda t: t[1].bbox[1])
        grp, last_y1 = [], None
        for i, d in cands:
            if last_y1 is None:
                if d.bbox[1] <= 2.5:
                    grp.append((i, d))
                    last_y1 = d.bbox[3]
            elif d.bbox[1] - last_y1 <= 3.0:
                grp.append((i, d))
                last_y1 = max(last_y1, d.bbox[3])
        return grp

    b1 = top_bands(ir.pages[0])
    b1_h = max((d.bbox[3] for _, d in b1), default=0)
    later = [top_bands(p) for p in ir.pages[1:]]
    later_h = [max((d.bbox[3] for _, d in g), default=0) for g in later]
    strip_h = _mode([h for h in later_h if h > 0]) if any(later_h) else 0
    have_strip = n >= 2 and sum(
        1 for h in later_h if h > 0 and abs(h - strip_h) < 3) >= max(1, int(0.6 * (n - 1)))

    if b1 and b1_h > 45:
        res["band_first"] = b1
        for i, _ in b1:
            res["consumed_draw"][1].add(i)
    elif b1 and have_strip and abs(b1_h - strip_h) < 3:
        res["band_def"] = b1  # same strip everywhere
    if have_strip:
        if res["band_def"] is None:
            res["band_def"] = later[0] or None
        for pi, g in enumerate(later, start=2):
            for i, _ in g:
                res["consumed_draw"][pi].add(i)
        if b1 and b1_h <= 45 and abs(b1_h - strip_h) < 3:
            for i, _ in b1:
                res["consumed_draw"][1].add(i)

    band1_bb = None
    if res["band_first"]:
        for _, d in res["band_first"]:
            band1_bb = bbox_union(band1_bb, d.bbox)

    TOPZ, BOTZ = 62.0, 64.0
    sigs = defaultdict(list)
    for p in ir.pages:
        band_h = b1_h if (p.number == 1 and res["band_first"]) else \
            (strip_h if have_strip else 0)
        for bi, blk in enumerate(p.blocks):
            for ln in blk.lines:
                y0, y1 = ln.bbox[1], ln.bbox[3]
                zone = None
                if y1 <= max(TOPZ, band_h + 2) and p.number != 1:
                    zone = "top"
                elif p.number == 1 and y1 <= TOPZ and not res["band_first"]:
                    zone = "top"
                elif y0 >= p.height - BOTZ:
                    zone = "bot"
                if zone:
                    sig = (zone, round(ln.bbox[1] / 3), _norm_text(ln.text)[:40])
                    sigs[sig].append((p.number, bi, ln))
    need = max(2, int(round(0.6 * n)))
    for sig, occ in sigs.items():
        pages = {o[0] for o in occ}
        strip_case = sig[0] == "top" and (res["band_first"] is not None or have_strip)
        need_here = max(2, int(round(0.6 * (n - 1)))) if strip_case else need
        if len(pages) >= need_here:
            # digit roles across pages
            per_page = {}
            for pg, bi, ln in occ:
                per_page.setdefault(pg, re.findall(r"\d+", ln.text))
            lens = {len(v) for v in per_page.values()}
            roles = None
            if len(lens) == 1 and lens != {0}:
                k = lens.pop()
                roles = []
                for idx in range(k):
                    vals = {pg: int(v[idx]) for pg, v in per_page.items()}
                    if len(vals) >= 2 and all(v == pg for pg, v in vals.items()):
                        roles.append("PAGE")
                    elif len(set(vals.values())) == 1 and list(vals.values())[0] == n:
                        roles.append("NUMPAGES?")  # context-checked later
                    else:
                        roles.append("LIT")
            for pg, bi, ln in occ:
                res["rep_lines"][pg].append((sig[0], bi, ln))
                res["consumed_text"][pg].add((bi, id(ln)))
                if roles:
                    res["line_roles"][id(ln)] = roles

    # page-1 band text
    if band1_bb is not None:
        for bi, blk in enumerate(ir.pages[0].blocks):
            for ln in blk.lines:
                if contains(band1_bb, ln.bbox, pad=3):
                    res["rep_lines"][1].append(("band1", bi, ln))
                    res["consumed_text"][1].add((bi, id(ln)))
    # strip band text on later pages (inside strip bbox)
    if have_strip:
        for pi, g in enumerate(later, start=2):
            bb = None
            for _, d in g:
                bb = bbox_union(bb, d.bbox)
            if bb is None:
                continue
            for bi, blk in enumerate(ir.pages[pi - 1].blocks):
                for ln in blk.lines:
                    if contains(bb, ln.bbox, pad=3) and \
                            (bi, id(ln)) not in res["consumed_text"][pi]:
                        res["rep_lines"][pi].append(("top", bi, ln))
                        res["consumed_text"][pi].add((bi, id(ln)))

    # repeating zone drawings
    dsigs = defaultdict(list)
    for p in ir.pages:
        for di, d in enumerate(p.drawings):
            if di in res["consumed_draw"][p.number]:
                continue
            y0, y1 = d.bbox[1], d.bbox[3]
            zone = "top" if y1 <= TOPZ else ("bot" if y0 >= p.height - BOTZ else None)
            if zone and d.shape in ("hline", "vline", "rect", "line"):
                sig = (zone, round(y0 / 3), round(d.bbox[0] / 5), d.shape, d.fill, d.stroke)
                dsigs[sig].append((p.number, di, d))
    for sig, occ in dsigs.items():
        if len({o[0] for o in occ}) >= need:
            for pg, di, d in occ:
                res["rep_draws"][pg].append((sig[0], di, d))
                res["consumed_draw"][pg].add(di)
    return res


def _pagefields(runs: List[Run], roles_for_line: Optional[List[str]],
                context: List[str]) -> List[Run]:
    if not roles_for_line:
        return runs
    out = []
    ri = [0]

    def next_role():
        r = roles_for_line[ri[0]] if ri[0] < len(roles_for_line) else "LIT"
        ri[0] += 1
        return r

    for r in runs:
        if r.is_tab or r.field:
            out.append(r)
            context.append(r.text)
            continue
        parts = re.split(r"(\d+)", r.text)
        for part in parts:
            if part == "":
                continue
            nr = Run(text=part, font=r.font, size=r.size, color=r.color,
                     bold=r.bold, italic=r.italic, mono=r.mono, link=r.link,
                     underline=r.underline)
            if part.isdigit():
                role = next_role()
                if role == "PAGE":
                    nr.field, nr.text = "PAGE", ""
                elif role == "NUMPAGES?":
                    prev = "".join(context)[-8:].strip().lower()
                    if prev.endswith(("/", "of", "de", "von", "sur")):
                        nr.field, nr.text = "NUMPAGES", ""
            out.append(nr)
            context.append(part)
    return out


def _group_lines_by_row(lines: List[Line]) -> List[List[Line]]:
    rows = []
    for ln in sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])):
        if rows and abs(ln.bbox[1] - rows[-1][0].bbox[1]) < 3.5:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    for r in rows:
        r.sort(key=lambda l: l.bbox[0])
    return rows


def _hf_row_para(row: List[Line], margin_l: float, content_w: float,
                 line_roles: Dict[int, List[str]]) -> Para:
    p = Para()
    bbox = None
    for ln in row:
        bbox = bbox_union(bbox, ln.bbox)
    p.bbox = bbox
    p._vis_lines = 1
    if row and row[0].spans:
        p._b1 = row[0].baseline
        p._size1 = row[0].spans[0].size
        p.leading = round(max(p._size1 * 1.16, 4.0), 2)
    center_x = margin_l + content_w / 2
    right_edge = margin_l + content_w
    context: List[str] = []

    def seg_runs(ln):
        return _pagefields(runs_from_spans(ln.spans), line_roles.get(id(ln)), context)

    if len(row) == 1:
        bb, ln = row[0].bbox, row[0]
        cx = (bb[0] + bb[2]) / 2
        p.runs = seg_runs(ln)
        if abs(cx - center_x) < 8 and bb[0] - margin_l > 8:
            p.align = "center"
        elif right_edge - bb[2] < 6 and bb[0] - margin_l > 10:
            p.align = "right"
        else:
            p.left_indent = max(0.0, round(bb[0] - margin_l, 1))
        return p
    runs: List[Run] = []
    tabs = []
    for i, ln in enumerate(row):
        bb = ln.bbox
        rr = seg_runs(ln)
        cx = (bb[0] + bb[2]) / 2
        if i == 0:
            if bb[0] - margin_l >= 6:
                p.left_indent = round(bb[0] - margin_l, 1)
            runs += rr
            continue
        if abs(cx - center_x) < 8:
            tabs.append((content_w / 2, "center"))
        elif right_edge - bb[2] < 8:
            tabs.append((content_w, "right"))
        else:
            tabs.append((round(bb[0] - margin_l, 1), "left"))
        runs.append(Run(text="\t", font=rr[0].font if rr else "Helvetica",
                        size=rr[0].size if rr else 9, color=rr[0].color if rr else "#000000",
                        is_tab=True))
        runs += rr
    p.runs = runs
    p.tab_stops = tabs
    return p


def build_band_table(band, band_lines: List[Line], margin_l, content_w,
                     line_roles) -> TableEl:
    band_bb = None
    for _, d in band:
        band_bb = bbox_union(band_bb, d.bbox)
    main = max((d for _, d in band), key=lambda d: bbox_area(d.bbox))
    accents = [d for _, d in band if d is not main]
    cell = Cell(shading=main.fill, borders={})
    binner = sorted(band_lines, key=lambda l: l.bbox[1])
    pad_left = max(0.0, round(min((l.bbox[0] for l in binner), default=margin_l)
                              - margin_l, 1))
    for rowlines in _group_lines_by_row(binner):
        pp = _hf_row_para(rowlines, margin_l + pad_left, content_w - pad_left, line_roles)
        cell.paras.append(pp)
    if not cell.paras:
        cell.paras = [Para(runs=[Run(text="", font="Helvetica", size=2,
                                     color="#000000")], leading=2.0)]
    cursor = _space_paras(cell.paras, band_bb[1])
    pad_bot = max(0.0, round(band_bb[3] - cursor, 1))
    cell.pad = (0.0, pad_left, pad_bot, 0.0)
    for a in accents:
        if a.bbox[1] >= main.bbox[3] - 1:
            cell.borders["bottom"] = (max(1.0, a.bbox[3] - a.bbox[1]),
                                      a.fill or "#000000")
        elif a.bbox[3] <= main.bbox[1] + 1:
            cell.borders["top"] = (max(1.0, a.bbox[3] - a.bbox[1]), a.fill or "#000000")
    return TableEl(rows=[[cell]], col_widths=[content_w],
                   row_heights=[band_bb[3] - band_bb[1]], role="band", bbox=band_bb)


def build_hf_part(zone_items, zone_draws, page: PageIR, margin_l, margin_r,
                  line_roles, band=None) -> Optional[HFPart]:
    if not zone_items and not zone_draws and not band:
        return None
    W = page.width
    content_w = W - margin_l - margin_r
    part = HFPart(elements=[])

    band_bb = None
    if band:
        for _, d in band:
            band_bb = bbox_union(band_bb, d.bbox)

    if band_bb is not None:
        blines = [ln for (_, _, ln) in zone_items if ln.bbox[3] <= band_bb[3] + 2]
        part.elements.append(build_band_table(band, blines, margin_l, content_w,
                                              line_roles))
        part.distance = 0.0
        rest = [(z, b, l) for (z, b, l) in zone_items if l.bbox[3] > band_bb[3] + 2]
    else:
        rest = list(zone_items)

    rules = [d for (_, _, d) in zone_draws if d.shape in ("hline", "line")]
    text_paras = []
    for rowlines in _group_lines_by_row([ln for (_, _, ln) in rest]):
        pp = _hf_row_para(rowlines, margin_l, content_w, line_roles)
        y0 = min(l.bbox[1] for l in rowlines)
        y1 = max(l.bbox[3] for l in rowlines)
        for rl in rules:
            ry = (rl.bbox[1] + rl.bbox[3]) / 2
            th = max(0.5, rl.width or (rl.bbox[3] - rl.bbox[1]))
            colr = rl.stroke or rl.fill or "#000000"
            if 0 < y0 - ry < 18:
                pp.border_top = (th, colr, round(y0 - ry, 1))
            elif 0 < ry - y1 < 18:
                pp.border_bottom = (th, colr, round(ry - y1, 1))
        text_paras.append((y0, y1, pp))
    text_paras.sort(key=lambda t: t[0])
    cursor = None
    for y0, y1, pp in text_paras:
        if cursor is not None:
            pp.space_before = max(0.0, round(y0 - cursor, 1))
        cursor = y1
        part.elements.append(pp)

    if not part.elements:
        return None
    if band_bb is None:
        ys0 = [t[0] for t in text_paras]
        ys1 = [t[1] for t in text_paras]
        if ys0:
            if min(ys0) < page.height / 2:
                part.distance = round(min(ys0), 1)
            else:
                part.distance = round(page.height - max(ys1), 1)
    return part


# ------------------------------------------------------------------ clustering
class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _expand(b: BBox, d: float) -> BBox:
    return (b[0] - d, b[1] - d, b[2] + d, b[3] + d)


def _touches(a: BBox, b: BBox, d: float = 6.0) -> bool:
    ea = _expand(a, d)
    return not (ea[2] < b[0] or b[2] < ea[0] or ea[3] < b[1] or b[3] < ea[1])


def _clusters(draws):
    n = len(draws)
    uf = _UF(n)
    for i in range(n):
        for j in range(i + 1, n):
            if _touches(draws[i][1].bbox, draws[j][1].bbox):
                uf.union(i, j)
    groups = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(draws[i])
    return list(groups.values())


def _edges_of(d: DrawCmd):
    x0, y0, x1, y1 = d.bbox
    hs, vs = [], []
    if d.shape == "hline":
        hs.append(((y0 + y1) / 2, x0, x1, d))
    elif d.shape == "vline":
        vs.append((((x0 + x1) / 2), y0, y1, d))
    elif d.shape == "rect" and d.kind in ("stroke", "fillstroke"):
        hs += [(y0, x0, x1, d), (y1, x0, x1, d)]
        vs += [(x0, y0, y1, d), (x1, y0, y1, d)]
    return hs, vs


def _is_glyphlike(d: DrawCmd) -> bool:
    """Tiny solid shape: a drawn bullet, tick or dingbat, not artwork.

    dialect.normalize() converts the ones that label a text line into real
    markers; the survivors are ornaments and must not be able to promote a
    whole cluster to 'figure'."""
    x0, y0, x1, y1 = d.bbox
    return (x1 - x0) <= GLYPH_MAX and (y1 - y0) <= GLYPH_MAX


def _classify_cluster(cl) -> str:
    ds = [d for _, d in cl]
    art = [d for d in ds if d.shape in ("curve", "complex", "line")
           and not _is_glyphlike(d)]
    # A rule is a rule at any length; on its own it is never a figure.
    if art and not all(d.shape == "line" and _thin(d) for d in art):
        return "figure"
    fills = [d for d in ds if d.fill and d.shape == "rect"]
    if len(fills) >= 3:
        bots = _cluster([f.bbox[3] for f in fills], 2.5)
        for b in bots:
            grp = [f for f in fills if abs(f.bbox[3] - b) <= 2.5]
            if len(grp) >= 3:
                hts = [f.bbox[3] - f.bbox[1] for f in grp]
                if max(hts) > 1.3 * max(1e-6, min(hts)):
                    return "figure"
    hs, vs = [], []
    for d in ds:
        h, v = _edges_of(d)
        hs += h
        vs += v
    hys = _cluster([h[0] for h in hs if h[2] - h[1] > 40], 2.0)
    vxs = _cluster([v[0] for v in vs if v[2] - v[1] > 6], 2.0)
    if len(hys) >= 2 and len(vxs) >= 2 and (len(hys) >= 3 or len(vxs) >= 3):
        return "grid"
    if len(fills) >= 2:
        y0s = _cluster([f.bbox[1] for f in fills], 3.0)
        y1s = _cluster([f.bbox[3] for f in fills], 3.0)
        if len(y0s) == 1 and len(y1s) == 1:
            xs = sorted(fills, key=lambda f: f.bbox[0])
            if all(xs[i + 1].bbox[0] - xs[i].bbox[2] <= 4 for i in range(len(xs) - 1)) \
                    and all(f.bbox[2] - f.bbox[0] >= 40 for f in xs):
                return "cards"
        x0s = _cluster([f.bbox[0] for f in fills], 3.0)
        x1s = _cluster([f.bbox[2] for f in fills], 3.0)
        if len(x0s) == 1 and len(x1s) == 1:
            return "stripes"
    if len(fills) == 1:
        return "boxlike"
    # "lots of primitives" only implies artwork when the primitives are
    # substantial. Four hairline rules are a ruled table, not a chart.
    substantial = [d for d in ds if not _is_glyphlike(d) and not _thin(d)]
    if len(substantial) >= 4:
        return "figure"
    return "loose"


# ------------------------------------------------------------------ tables
def _all_lines(blocks: List[TextBlock]):
    for b in blocks:
        for ln in b.lines:
            yield ln


def _take_lines_in(blocks, rect: BBox, consumed: set, mode="center") -> List[Line]:
    out = []
    for ln in _all_lines(blocks):
        if id(ln) in consumed:
            continue
        lb = ln.bbox
        if mode == "center":
            cx, cy = (lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2
            ok = rect[0] - 1 <= cx <= rect[2] + 1 and rect[1] - 1 <= cy <= rect[3] + 1
        else:
            ok = bbox_overlap(lb, rect) > 0.55 * max(1e-6, bbox_area(lb))
        if ok:
            out.append(ln)
            consumed.add(id(ln))
    return out


def _space_paras(paras: List[Para], top: float):
    """Assign baseline-anchored space_before within a container."""
    cursor = top
    for p in paras:
        t, h = _para_box(p)
        p.space_before = max(0.0, round(t - cursor, 1))
        p.space_after = 0.0
        cursor = t + h
    return cursor


def _cell_from_lines(lines: List[Line], rect: BBox, pad_extra=(2.0, 2.0)) -> Cell:
    cell = Cell(borders={})
    if lines:
        minx = min(l.bbox[0] for l in lines)
        cell.paras = paras_from_line_list(lines, rect[0], rect[2] - 2)
        t0 = _para_box(cell.paras[0])[0] if cell.paras else rect[1]
        pad_top = max(0.0, round(t0 - rect[1], 1))
        end = _space_paras(cell.paras, rect[1] + pad_top)
        pad_bot = max(pad_extra[0], round(rect[3] - end, 1))
        cell.pad = (pad_top, round(max(0, minx - rect[0]), 1),
                    pad_bot, pad_extra[1])
        for p in cell.paras:
            p.left_indent = max(0.0, round((p.bbox[0] if p.bbox else minx) - rect[0]
                                           - cell.pad[1], 1)) \
                if p.align in ("left", "justify") else p.left_indent
    return cell


def _striped_row_tiles(draws: List[Tuple[int, DrawCmd]]):
    """Return full-width filled row candidates without claiming any content.

    A regular table often paints only alternating rows.  Its fill is therefore
    represented as several adjacent rectangles, not one large rectangle.  This
    collector is intentionally stricter than the old ``stripes`` cluster: all
    tiles in a row must share top/bottom edges and be contiguous.
    """
    by_y = defaultdict(list)
    for di, d in draws:
        if not (d.fill and d.shape == "rect"):
            continue
        if d.bbox[2] - d.bbox[0] < 12 or d.bbox[3] - d.bbox[1] < 8:
            continue
        by_y[(round(d.bbox[1] * 2), round(d.bbox[3] * 2))].append((di, d))
    out = []
    for group in by_y.values():
        group.sort(key=lambda item: item[1].bbox[0])
        # A row may be emitted as two adjacent rectangles due to a merged
        # producer path, but it must still form a contiguous tiled band.
        runs, run = [], [group[0]]
        for item in group[1:]:
            if item[1].bbox[0] - run[-1][1].bbox[2] <= 1.25:
                run.append(item)
            else:
                runs.append(run)
                run = [item]
        runs.append(run)
        for run in runs:
            if len(run) < 2:
                continue
            x0, x1 = run[0][1].bbox[0], run[-1][1].bbox[2]
            if x1 - x0 < 80:
                continue
            bounds = [x0] + [d.bbox[2] for _, d in run]
            out.append((run, bounds))
    return out


def _regular_striped_table_segment(draws: List[Tuple[int, DrawCmd]], blocks,
                                   consumed: set) -> Optional[Tuple[TableEl, set]]:
    """Recognise a conservative, row-regular striped table on one page.

    This is intentionally a *segment* detector.  It validates all geometry
    and text ownership using a probe set before it consumes lines/drawings, so
    cards, callouts, mixed dashboard regions, and wrapped cells retain the
    established inference path.
    """
    tile_rows = _striped_row_tiles(draws)
    if len(tile_rows) < 3:
        return None

    # Find a repeated column signature among the painted row bands.  Rounded
    # half-point coordinates survive both PyMuPDF and PDFium extraction.
    signatures = defaultdict(list)
    for run, bounds in tile_rows:
        sig = tuple(round(v / 2.0) * 2.0 for v in bounds)
        if len(sig) >= 3:
            signatures[sig].append((run, bounds))
    ranked = sorted(signatures.values(), key=len, reverse=True)
    if not ranked or len(ranked[0]) < 3:
        return None
    rows = ranked[0]
    sample_bounds = rows[0][1]
    n_cols = len(sample_bounds) - 1
    if n_cols < 2 or n_cols > 8:
        return None
    x0, x1 = sample_bounds[0], sample_bounds[-1]
    if any(abs(a - b) > 2.0 for _, bounds in rows for a, b in zip(bounds, sample_bounds)):
        return None

    # Boundaries are supplied by the alternating fill rectangles and by the
    # horizontal rules on unfilled rows.  A usable rule must tile the same
    # width, not merely cross one card.
    y_boundaries = []
    for run, _ in rows:
        y_boundaries.extend((run[0][1].bbox[1], run[0][1].bbox[3]))
    hgroups = defaultdict(list)
    for di, d in draws:
        if d.shape != "hline" or d.bbox[2] - d.bbox[0] < 12:
            continue
        cy = (d.bbox[1] + d.bbox[3]) / 2
        hgroups[round(cy * 2)].append((di, d))
    boundary_draws_by_y = {}
    for group in hgroups.values():
        group.sort(key=lambda item: item[1].bbox[0])
        cursor = x0
        used = []
        for item in group:
            d = item[1]
            if d.bbox[2] < cursor - 1.5 or d.bbox[0] > x1 + 1.5:
                continue
            if d.bbox[0] > cursor + 1.5:
                break
            cursor = max(cursor, d.bbox[2])
            used.append(item[0])
        if cursor >= x1 - 1.5:
            y = sum((d.bbox[1] + d.bbox[3]) / 2 for di, d in group
                    if di in used) / max(1, len(used))
            y_boundaries.append(y)
            boundary_draws_by_y[y] = set(used)
    ys = _cluster(y_boundaries, 1.5)
    if len(ys) < 4:
        return None
    # Split unrelated regions at gaps larger than a regular row plus a small
    # tolerance.  Choose the largest valid run, never bridge dashboard bands.
    intervals = [b - a for a, b in zip(ys, ys[1:])]
    pitches = [v for v in intervals if 10.0 <= v <= 40.0]
    if len(pitches) < 3:
        return None
    pitch = median(pitches)
    runs, current = [], [ys[0]]
    for a, b in zip(ys, ys[1:]):
        if abs((b - a) - pitch) <= 2.25:
            current.append(b)
        else:
            if len(current) >= 4:
                runs.append(current)
            current = [b]
    if len(current) >= 4:
        runs.append(current)
    if not runs:
        return None
    row_ys = max(runs, key=len)
    if len(row_ys) - 1 < 3:
        return None

    # At least three alternating bands must lie within this exact regular run;
    # this prevents a short striped note above an unrelated table from winning.
    full_fills = 0
    draw_ids = set()
    for y, ids in boundary_draws_by_y.items():
        if any(abs(y - ry) <= 1.5 for ry in row_ys):
            draw_ids.update(ids)
    for run, bounds in rows:
        top, bot = run[0][1].bbox[1], run[0][1].bbox[3]
        if any(abs(top - row_ys[i]) <= 1.5 and abs(bot - row_ys[i + 1]) <= 1.5
               for i in range(len(row_ys) - 1)):
            full_fills += 1
            draw_ids.update(di for di, _ in run)
    if full_fills < 3:
        return None

    probe = set(consumed)
    cell_lines = defaultdict(list)
    all_candidate = []
    for ln in _all_lines(blocks):
        if id(ln) in probe or not ln.horizontal:
            continue
        cx, cy = (ln.bbox[0] + ln.bbox[2]) / 2, (ln.bbox[1] + ln.bbox[3]) / 2
        if not (x0 - 1 <= cx <= x1 + 1 and row_ys[0] - 1 <= cy <= row_ys[-1] + 1):
            continue
        ri = next((i for i in range(len(row_ys) - 1)
                   if row_ys[i] - 1 <= cy <= row_ys[i + 1] + 1), None)
        ci = next((j for j in range(n_cols)
                   if sample_bounds[j] - 1 <= cx <= sample_bounds[j + 1] + 1), None)
        if ri is None or ci is None:
            return None                    # text straddles/escapes a cell
        cell_lines[(ri, ci)].append(ln)
        all_candidate.append(ln)
    expected = (len(row_ys) - 1) * n_cols
    occupied = sum(1 for vals in cell_lines.values() if len(vals) == 1)
    if occupied < 0.80 * expected or len(all_candidate) != occupied:
        return None                        # missing or wrapped/multiline cells
    if any(sum(1 for ci in range(n_cols) if (ri, ci) in cell_lines) < n_cols
           for ri in range(len(row_ys) - 1)):
        return None

    tbl = TableEl(role="striped-table", bbox=(x0, row_ys[0], x1, row_ys[-1]))
    tbl.col_widths = [sample_bounds[i + 1] - sample_bounds[i] for i in range(n_cols)]
    tbl.row_heights = [row_ys[i + 1] - row_ys[i] for i in range(len(row_ys) - 1)]
    for ri, (top, bot) in enumerate(zip(row_ys, row_ys[1:])):
        row = []
        for ci in range(n_cols):
            rect = (sample_bounds[ci], top, sample_bounds[ci + 1], bot)
            ln = cell_lines[(ri, ci)][0]
            cell = _cell_from_lines([ln], rect, pad_extra=(1.5, 1.5))
            # Preserve the source's row band and each horizontal rule.  There
            # are no vertical strokes in this ordinary striped-table dialect.
            fill = next((d.fill for _, d in draws if d.fill and d.shape == "rect" and
                         bbox_overlap(d.bbox, rect) > 0.85 * bbox_area(rect)), None)
            if fill:
                cell.shading = fill
            cell.borders = {"top": (0.5, "#d8dee5"), "bottom": (0.5, "#d8dee5")}
            row.append(cell)
        tbl.rows.append(row)
    # All probes succeeded.  This is the sole point at which this detector is
    # allowed to claim text; failures above leave the normal flow untouched.
    consumed.update(id(ln) for ln in all_candidate)
    return tbl, draw_ids


def _row_signature(row: List[Optional[Cell]]):
    """Text/style evidence used only for repeated source table headers."""
    return tuple((_norm_text(" ".join(p.text for p in c.paras)),
                  tuple((round(r.size, 1), r.bold, r.italic)
                        for p in c.paras for r in p.runs))
                 if c else ("", ()) for c in row)


def _coalesce_striped_table_segments(lay: DocLayout):
    """Merge only adjacent continuation-only striped-table page segments."""
    leader = None
    header = None
    previous = None
    previous_is_final = False
    for pi, page in enumerate(lay.pages):
        elements = [el for chunk in page.chunks for el in chunk.elements]
        segments = [el for el in elements if isinstance(el, TableEl) and
                    el.role == "striped-table"]
        if len(segments) != 1:
            leader = header = previous = None
            previous_is_final = False
            continue
        segment = segments[0]
        if leader is None:
            leader, header, previous = segment, segment.rows[0] if segment.rows else None, segment
            previous_is_final = bool(elements and elements[-1] is segment)
            continue
        # A continuation page must contain *only* this verified table.  This
        # is what makes dropping its explicit source-page break safe.
        # PDF body baselines routinely stop 8--14pt above the nominal bottom
        # margin; use the conventional 72pt reserve as a floor rather than
        # requiring the last painted rule to touch it.
        if len(elements) != 1 or len(segment.col_widths) != len(leader.col_widths) or \
                any(abs(a - b) > 2.0 for a, b in zip(segment.col_widths, leader.col_widths)) or \
                previous is None or previous.bbox is None or segment.bbox is None or \
                not previous_is_final or \
                abs(previous.bbox[0] - segment.bbox[0]) > 2.0 or \
                abs(previous.bbox[2] - segment.bbox[2]) > 2.0 or \
                previous.bbox[3] < lay.page_h - max(72.0, lay.margin_b) - 8.0 or \
                segment.bbox[1] > lay.margin_t + 12.0:
            leader, header, previous = segment, segment.rows[0] if segment.rows else None, segment
            previous_is_final = bool(elements and elements[-1] is segment)
            continue
        if header and segment.rows and _row_signature(segment.rows[0]) == _row_signature(header):
            segment.rows.pop(0)
            if segment.row_heights:
                segment.row_heights.pop(0)
            leader.repeat_header_rows = max(leader.repeat_header_rows, 1)
        leader.rows.extend(segment.rows)
        leader.row_heights.extend(segment.row_heights)
        for chunk in page.chunks:
            chunk.elements = [el for el in chunk.elements if el is not segment]
        page.continuation_only = True
        previous = segment
        previous_is_final = True


def build_grid_table(cl, blocks, consumed) -> Optional[TableEl]:
    ds = [d for _, d in cl]
    hs, vs = [], []
    for d in ds:
        h, v = _edges_of(d)
        hs += h
        vs += v
    row_ys = _cluster([h[0] for h in hs if h[2] - h[1] > 40], 2.0)
    col_xs = _cluster([v[0] for v in vs if v[2] - v[1] > 6], 2.0)
    if len(row_ys) < 2 or len(col_xs) < 2 or (len(row_ys) < 3 and len(col_xs) < 3):
        return None
    fills = [d for d in ds if d.fill and d.shape == "rect"]
    strokes = [d for d in ds if d.stroke]
    bw = _mode([d.width for d in strokes if d.width > 0], 2) or 0.5
    bcol = Counter(d.stroke for d in strokes if d.stroke).most_common(1)
    bcol = bcol[0][0] if bcol else "#000000"
    tbl = TableEl(role="table")
    tbl.bbox = (col_xs[0], row_ys[0], col_xs[-1], row_ys[-1])
    tbl.col_widths = [col_xs[i + 1] - col_xs[i] for i in range(len(col_xs) - 1)]
    tbl.row_heights = [row_ys[i + 1] - row_ys[i] for i in range(len(row_ys) - 1)]
    cell_lines = defaultdict(list)
    for ln in _all_lines(blocks):
        if id(ln) in consumed:
            continue
        cx = (ln.bbox[0] + ln.bbox[2]) / 2
        cy = (ln.bbox[1] + ln.bbox[3]) / 2
        if not (tbl.bbox[0] - 1 <= cx <= tbl.bbox[2] + 1 and
                tbl.bbox[1] - 1 <= cy <= tbl.bbox[3] + 1):
            continue
        ri = next((i for i in range(len(row_ys) - 1)
                   if row_ys[i] - 1 <= cy <= row_ys[i + 1] + 1), None)
        ci = next((j for j in range(len(col_xs) - 1)
                   if col_xs[j] - 1 <= cx <= col_xs[j + 1] + 1), None)
        if ri is None or ci is None:
            continue
        cell_lines[(ri, ci)].append(ln)
        consumed.add(id(ln))
    for ri in range(len(row_ys) - 1):
        row = []
        for ci in range(len(col_xs) - 1):
            rect = (col_xs[ci], row_ys[ri], col_xs[ci + 1], row_ys[ri + 1])
            cell = _cell_from_lines(sorted(cell_lines.get((ri, ci), []),
                                           key=lambda l: (l.bbox[1], l.bbox[0])), rect)
            cell.borders = {k: (bw, bcol) for k in ("top", "bottom", "left", "right")}
            for f in fills:
                if bbox_overlap(f.bbox, rect) > 0.6 * bbox_area(rect):
                    cell.shading = f.fill
                    break
            row.append(cell)
        tbl.rows.append(row)
    return tbl


def build_cards_table(cl, blocks, consumed) -> Optional[TableEl]:
    fills = sorted([d for _, d in cl if d.fill and d.shape == "rect"],
                   key=lambda f: f.bbox[0])
    if not fills:
        return None
    y0 = min(f.bbox[1] for f in fills)
    y1 = max(f.bbox[3] for f in fills)
    tbl = TableEl(role="cards", bbox=(fills[0].bbox[0], y0, fills[-1].bbox[2], y1))
    tbl.col_widths = [f.bbox[2] - f.bbox[0] for f in fills]
    tbl.row_heights = [y1 - y0]
    row = []
    for f in fills:
        lines = _take_lines_in(blocks, f.bbox, consumed)
        cell = _cell_from_lines(sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])), f.bbox,
                                pad_extra=(4.0, 4.0))
        cell.shading = f.fill
        row.append(cell)
    tbl.rows.append(row)
    return tbl


def build_stripes_table(cl, blocks, consumed) -> Optional[TableEl]:
    fills = sorted([d for _, d in cl if d.fill and d.shape == "rect"],
                   key=lambda f: f.bbox[1])
    if not fills:
        return None
    x0 = min(f.bbox[0] for f in fills)
    x1 = max(f.bbox[2] for f in fills)
    region = (x0, fills[0].bbox[1], x1, fills[-1].bbox[3])
    col_lefts = _text_columns(blocks, region, consumed)
    if len(col_lefts) < 2:
        return None
    bounds = list(col_lefts) + [x1]
    tbl = TableEl(role="table", bbox=region)
    tbl.col_widths = [bounds[i + 1] - bounds[i] for i in range(len(col_lefts))]
    for f in fills:
        row = []
        for ci in range(len(col_lefts)):
            rect = (bounds[ci], f.bbox[1], bounds[ci + 1], f.bbox[3])
            lines = _take_lines_in(blocks, rect, consumed)
            cell = _cell_from_lines(sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])), rect)
            cell.shading = f.fill
            row.append(cell)
        tbl.rows.append(row)
        tbl.row_heights.append(f.bbox[3] - f.bbox[1])
    return tbl


def _text_columns(blocks, rect: BBox, consumed) -> List[float]:
    xs = []
    for ln in _all_lines(blocks):
        if id(ln) in consumed:
            continue
        lb = ln.bbox
        cx, cy = (lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2
        if rect[0] - 1 <= cx <= rect[2] + 1 and rect[1] - 1 <= cy <= rect[3] + 1:
            for row in [ln]:
                xs.append(lb[0])
    return _cluster(xs, 7.0)


def build_rules_table(hgroup: List[DrawCmd], blocks, consumed) -> Optional[TableEl]:
    hgroup = sorted(hgroup, key=lambda d: d.bbox[1])
    x0 = min(d.bbox[0] for d in hgroup)
    x1 = max(d.bbox[2] for d in hgroup)
    top, bot = hgroup[0].bbox[1], hgroup[-1].bbox[3]
    region = (x0 - 2, top - 1, x1 + 2, bot + 1)
    probe = set(consumed)
    lines = _take_lines_in(blocks, region, probe)
    if not lines:
        return None
    rows = _group_lines_by_row(lines)
    if len(rows) < 2:
        return None
    multi = sum(1 for r in rows if len(r) >= 2)
    if multi < max(2, int(0.6 * len(rows))):
        return None
    col_lefts = _cluster([ln.bbox[0] for ln in lines], 7.0)
    if len(col_lefts) < 2:
        return None
    consumed.update(id(l) for l in lines)
    bounds = [x0]
    for i in range(1, len(col_lefts)):
        prev_right = max([l.bbox[2] for l in lines if l.bbox[0] < col_lefts[i] - 7]
                         or [col_lefts[i] - 10])
        bounds.append(min(col_lefts[i] - 2, max(prev_right + 2,
                                                (prev_right + col_lefts[i]) / 2)))
    bounds.append(x1)
    tbl = TableEl(role="table", bbox=(x0, top, x1, bot))
    tbl.col_widths = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
    row_tops = [top]
    for i in range(1, len(rows)):
        prev_b = max(l.bbox[3] for l in rows[i - 1])
        cur_t = min(l.bbox[1] for l in rows[i])
        mid = (prev_b + cur_t) / 2
        for d in hgroup[1:-1]:
            dy = (d.bbox[1] + d.bbox[3]) / 2
            if prev_b - 1 <= dy <= cur_t + 1:
                mid = dy
        row_tops.append(mid)
    row_tops.append(bot)
    rule_ys = [((d.bbox[1] + d.bbox[3]) / 2, max(0.4, d.width or (d.bbox[3] - d.bbox[1])),
                d.stroke or d.fill or "#000000") for d in hgroup]
    for ri in range(len(rows)):
        rowcells = []
        for ci in range(len(tbl.col_widths)):
            rect = (bounds[ci], row_tops[ri], bounds[ci + 1], row_tops[ri + 1])
            rl = [l for l in rows[ri] if rect[0] - 1 <= (l.bbox[0] + l.bbox[2]) / 2 <= rect[2] + 1]
            cell = _cell_from_lines(sorted(rl, key=lambda l: l.bbox[0]), rect,
                                    pad_extra=(1.5, 1.0))
            for ry, rw, rc in rule_ys:
                if abs(ry - row_tops[ri]) < 2.5:
                    cell.borders["top"] = (rw, rc)
                if abs(ry - row_tops[ri + 1]) < 2.5:
                    cell.borders["bottom"] = (rw, rc)
            rowcells.append(cell)
        tbl.rows.append(rowcells)
        tbl.row_heights.append(row_tops[ri + 1] - row_tops[ri])
    return tbl


def build_box(cl, blocks, consumed) -> Optional[TableEl]:
    ds = [d for _, d in cl]
    fill_rect = next((d for d in ds if d.fill and d.shape == "rect"), None)
    stroke_rect = next((d for d in ds if d.stroke and d.shape == "rect"
                        and d.kind in ("stroke", "fillstroke")), None)
    accent = next((d for d in ds if d.shape == "vline"), None)
    base = fill_rect or stroke_rect
    if base is None:
        return None
    rect = base.bbox
    probe = set(consumed)
    lines = _take_lines_in(blocks, rect, probe, mode="overlap")
    if not lines:
        return None
    consumed.update(id(l) for l in lines)
    lines.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
    mono_chars = sum(len(s.text) for l in lines for s in l.spans if s.mono)
    tot = sum(len(s.text) for l in lines for s in l.spans) or 1
    is_code = mono_chars / tot > 0.7
    cell = Cell(borders={}, shading=fill_rect.fill if fill_rect else None)
    if stroke_rect is not None:
        w = max(0.4, stroke_rect.width)
        c = stroke_rect.stroke or "#000000"
        cell.borders = {k: (w, c) for k in ("top", "bottom", "left", "right")}
    if accent is not None and accent.bbox[0] <= rect[0] + 4:
        aw = max(1.0, (accent.bbox[2] - accent.bbox[0]) if accent.fill else accent.width)
        cell.borders["left"] = (aw, accent.fill or accent.stroke or "#000000")
    minx = min(l.bbox[0] for l in lines)
    cell.pad = (0.0, round(max(0, minx - rect[0]), 1), 0.0, 4.0)
    if is_code:
        p = Para(line_breaks=True)
        lines = _merge_row_lines(lines)
        bb = None
        for l in lines:
            bb = bbox_union(bb, l.bbox)
        p.bbox = bb
        base_y = [l.baseline for l in lines]
        diffs = [b2 - b1 for b1, b2 in zip(base_y, base_y[1:]) if b2 > b1]
        # smallest gap cluster = true leading (larger gaps hide blank lines)
        lead = min(_cluster(diffs, 0.8)) if diffs else 11.0
        p.leading = round(lead, 2)
        p._b1 = base_y[0] if base_y else None
        p._size1 = lines[0].spans[0].size if lines and lines[0].spans else 9.0
        runs = []
        total_lines = 1
        for i, ln in enumerate(lines):
            runs.extend(runs_from_spans(ln.spans))
            if i < len(lines) - 1:
                n_breaks = max(1, int(round((base_y[i + 1] - base_y[i]) / max(1.0, lead))))
                runs.append(Run(text="\n" * n_breaks, font=ln.spans[0].font,
                                size=ln.spans[0].size, color=ln.spans[0].color))
                total_lines += n_breaks
        p.runs = runs
        p._vis_lines = total_lines
        cell.paras = [p]
        t0, hh = _para_box(p)
        pad_top = max(0.0, round(t0 - rect[1], 1))
        p.space_before = 0.0
        cell.pad = (pad_top, cell.pad[1],
                    max(0.0, round(rect[3] - (t0 + hh), 1)), cell.pad[3])
    else:
        cell.paras = paras_from_line_list(lines, minx, rect[2] - 4)
        t0 = _para_box(cell.paras[0])[0] if cell.paras else rect[1]
        pad_top = max(0.0, round(t0 - rect[1], 1))
        end = _space_paras(cell.paras, rect[1] + pad_top)
        cell.pad = (pad_top, cell.pad[1], max(0.0, round(rect[3] - end, 1)),
                    cell.pad[3])
        for p in cell.paras:
            if p.align in ("left", "justify"):
                p.left_indent = max(0.0, round((p.bbox[0] if p.bbox else minx) - minx, 1))
    role = "code" if is_code else ("box" if fill_rect else "quote")
    return TableEl(rows=[[cell]], col_widths=[rect[2] - rect[0]],
                   row_heights=[rect[3] - rect[1]], role=role, bbox=rect)


def build_figure(cl_ds: List[DrawCmd], blocks, images, consumed, page: PageIR) -> FigureEl:
    bb = None
    for d in cl_ds:
        bb = bbox_union(bb, d.bbox)
    # Absorption thresholds are frozen against the SEED geometry. Deriving them
    # from `bb` while `bb` is being grown is positive feedback: absorbing a line
    # widens the box, which loosens the test, which absorbs more lines. That
    # loop was measured growing a 490x2pt seed to 103x its area.
    seed = bb
    seed_w = max(1.0, seed[2] - seed[0])
    seed_area = max(1.0, bbox_area(seed))
    page_area = max(1.0, page.width * page.height)
    max_area = min(MAX_FIG_GROWTH * seed_area, MAX_FIG_PAGE_FRAC * page_area)
    for _ in range(6):
        changed = False
        ex = _expand(bb, 14)
        for ln in _all_lines(blocks):
            if id(ln) in consumed:
                continue
            lb = ln.bbox
            if bbox_overlap(lb, ex) > 0:
                inside = bbox_overlap(lb, bb) > 0.8 * max(1e-6, bbox_area(lb))
                small = (lb[3] - lb[1]) <= 45 and \
                    (lb[2] - lb[0]) <= max(1.06 * seed_w, 60)
                if inside or small:
                    cand = bbox_union(bb, lb)
                    if not inside and bbox_area(cand) > max_area:
                        continue          # refuse to grow past the budget
                    bb = cand
                    consumed.add(id(ln))
                    changed = True
        for im in images:
            if getattr(im, "_consumed", False):
                continue
            if bbox_overlap(im.bbox, _expand(bb, 6)) > 0:
                bb = bbox_union(bb, im.bbox)
                im._consumed = True
                changed = True
        if not changed:
            break
    bb = (max(0, bb[0] - 2), max(0, bb[1] - 2),
          min(page.width, bb[2] + 2), min(page.height, bb[3] + 2))
    return FigureEl(page_no=page.number, clip=bb,
                    width=bb[2] - bb[0], height=bb[3] - bb[1])


def _figure_in_budget(cl_ds, blocks, images, consumed, page, text_area):
    """build_figure, rolled back if it would rasterise too much of the page.

    Rasterising is the only irreversible decision in the pipeline: whatever a
    figure swallows stops being editable text, and no downstream stage can
    recover it. When a figure would eat more than MAX_FIG_TEXT_FRAC of a page's
    text, the classification is far likelier to be wrong than the page is to be
    genuinely that graphical -- so back it out and let the text flow.
    """
    before = set(consumed)
    before_img = [im for im in images if getattr(im, "_consumed", False)]
    fig = build_figure(cl_ds, blocks, images, consumed, page)
    eaten = sum(bbox_area(l.bbox) for l in _all_lines(blocks)
                if id(l) in consumed and id(l) not in before)
    if eaten > MAX_FIG_TEXT_FRAC * text_area:
        consumed.clear()
        consumed.update(before)
        keep = {id(i) for i in before_img}
        for im in images:
            if getattr(im, "_consumed", False) and id(im) not in keep:
                im._consumed = False
        return None
    return fig


# ------------------------------------------------------------------ main
def infer(ir: DocIR) -> DocLayout:
    lay = DocLayout(src_path=ir.path)
    if not ir.pages:
        return lay
    p0 = ir.pages[0]
    lay.page_w, lay.page_h = p0.width, p0.height
    n_pages = len(ir.pages)
    hf = detect_hf(ir)

    # ---------- margins
    body_lines = []
    for p in ir.pages:
        ct = hf["consumed_text"][p.number]
        for bi, b in enumerate(p.blocks):
            for l in b.lines:
                if (bi, id(l)) not in ct:
                    body_lines.append((p.number, l))
    ml = _margin_cluster([l.bbox[0] for _, l in body_lines
                          if l.bbox[0] < 0.35 * lay.page_w], left=True)
    lay.margin_l = float(ml) if ml else 72.0
    wide_x1 = [l.bbox[2] for _, l in body_lines
               if (l.bbox[2] - l.bbox[0]) >= 0.45 * lay.page_w and
               l.bbox[2] > 0.6 * lay.page_w]
    mr = _margin_cluster(wide_x1, left=False)
    lay.margin_r = round(lay.page_w - mr, 1) if mr else lay.margin_l
    lay.margin_r = max(14.0, lay.margin_r)

    band1_h = max((d.bbox[3] for _, d in hf["band_first"]), default=0) \
        if hf["band_first"] else 0
    tops, bots = [], []
    for p in ir.pages:
        ct = hf["consumed_text"][p.number]
        cd = hf["consumed_draw"][p.number]
        ys = [l.bbox[1] for bi, b in enumerate(p.blocks) for l in b.lines
              if (bi, id(l)) not in ct]
        ye = [l.bbox[3] for bi, b in enumerate(p.blocks) for l in b.lines
              if (bi, id(l)) not in ct]
        ys += [d.bbox[1] for di, d in enumerate(p.drawings) if di not in cd]
        ye += [d.bbox[3] for di, d in enumerate(p.drawings) if di not in cd]
        if ys and not (p.number == 1 and band1_h > 45):
            tops.append(min(ys))
        if ye:
            bots.append(max(ye))
    lay.margin_t = round(max(10.0, min(min(tops) if tops else 54.0, 120.0)), 1)
    max_bot = max(bots) if bots else lay.page_h - 54
    lay.margin_b = round(max(14.0, min(72.0, lay.page_h - max_bot - 16.0)), 1)

    # hyphenated justification? (line ends with letter-hyphen, next starts lower)
    hyph = 0
    for p in ir.pages:
        for b in p.blocks:
            for l1, l2 in zip(b.lines, b.lines[1:]):
                t1, t2 = l1.text.rstrip(), l2.text.lstrip()
                if t1.endswith("-") and len(t1) >= 2 and t1[-2].isalpha() \
                        and t2[:1].islower():
                    hyph += 1
    lay.hyphenated = hyph >= 6

    # ---------- headers/footers
    rl, rd = hf["rep_lines"], hf["rep_draws"]
    roles = hf["line_roles"]

    def zs(pg, zone):
        zones = (zone, "band1") if zone == "top" else (zone,)
        a = [(z, b, l) for (z, b, l) in rl.get(pg, []) if z in zones]
        b = [(z, d_i, d) for (z, d_i, d) in rd.get(pg, []) if z == zone]
        return a, b

    repr_pg = 2 if n_pages >= 2 else 1
    if n_pages >= 2:
        tl, td = zs(repr_pg, "top")
        lay.header_default = build_hf_part(tl, td, ir.pages[repr_pg - 1],
                                           lay.margin_l, lay.margin_r, roles,
                                           band=hf["band_def"])
        bl, bd = zs(repr_pg, "bot")
        lay.footer_default = build_hf_part(bl, bd, ir.pages[repr_pg - 1],
                                           lay.margin_l, lay.margin_r, roles)
    tl1, td1 = zs(1, "top")
    bl1, bd1 = zs(1, "bot")
    # cover band becomes BODY content in its own section (deterministic in
    # both Word and Google Docs; header push behavior varies across renderers)
    if hf["band_first"]:
        band_bb = None
        for _, d in hf["band_first"]:
            band_bb = bbox_union(band_bb, d.bbox)
        blines = [ln for (z, _, ln) in tl1 if z == "band1" or ln.bbox[3] <= band_bb[3] + 2]
        lay.cover_band = build_band_table(hf["band_first"], blines, lay.margin_l,
                                          lay.content_w, roles)
        lay.cover_top = round(max(0.0, band_bb[1]), 1)
        tl1 = [(z, b, l) for (z, b, l) in tl1 if l.bbox[3] > band_bb[3] + 2]
    hdr1 = build_hf_part(tl1, td1, ir.pages[0], lay.margin_l, lay.margin_r, roles)
    ftr1 = build_hf_part(bl1, bd1, ir.pages[0], lay.margin_l, lay.margin_r, roles)

    def sig(part):
        if part is None:
            return None
        s = []
        for el in part.elements:
            if isinstance(el, Para):
                s.append(("p", _norm_text(el.text)))
            elif isinstance(el, TableEl):
                s.append(("t", _norm_text(" ".join(
                    p.text for row in el.rows for c in row if c for p in c.paras))))
        return tuple(s)

    if n_pages >= 2:
        if sig(hdr1) != sig(lay.header_default) or sig(ftr1) != sig(lay.footer_default):
            lay.different_first = True
            lay.header_first = hdr1
            lay.footer_first = ftr1 if ftr1 is not None else lay.footer_default
    else:
        lay.header_default = hdr1
        lay.footer_default = ftr1

    # ---------- per-page content
    body_size = _body_font_size(ir, hf)
    content_w = lay.content_w
    for p in ir.pages:
        pl = PageLayout(number=p.number)
        ct = hf["consumed_text"][p.number]
        cd = set(hf["consumed_draw"][p.number])

        blocks: List[TextBlock] = []
        for bi, b in enumerate(p.blocks):
            keep = [l for l in b.lines if (bi, id(l)) not in ct]
            if keep:
                bb = None
                for l in keep:
                    bb = bbox_union(bb, l.bbox)
                blocks.append(TextBlock(lines=keep, bbox=bb))

        consumed: set = set()

        # underline pre-pass: thin short hlines hugging a text baseline
        for di, d in enumerate(p.drawings):
            if di in cd or d.shape != "hline":
                continue
            if (d.bbox[3] - d.bbox[1]) > 2.2 or (d.bbox[2] - d.bbox[0]) > 0.6 * content_w:
                continue
            hit = False
            for ln in _all_lines(blocks):
                for s in ln.spans:
                    if s.bbox[0] - 2.5 <= d.bbox[0] and d.bbox[2] <= s.bbox[2] + 2.5 \
                            and -1.0 <= d.bbox[1] - s.origin[1] <= 3.5:
                        s._ul = True
                        hit = True
            if hit:
                cd.add(di)

        elements: List[Any] = []
        draws = [(i, d) for i, d in enumerate(p.drawings)
                 if i not in cd and d.opacity > 0.05]
        # This runs before drawing clustering because a row-regular table is
        # otherwise split into alternating filled-card clusters and bare flow
        # paragraphs.  It has no side effects until the entire segment passes.
        striped = _regular_striped_table_segment(draws, blocks, consumed)
        if striped is not None:
            striped_table, striped_draws = striped
            elements.append(striped_table)
            cd.update(striped_draws)
            draws = [(i, d) for i, d in draws if i not in striped_draws]
        leftover = []
        page_text_area = sum(bbox_area(l.bbox) for l in _all_lines(blocks)) or 1.0
        for cl in _clusters(draws):
            if len(cl) == 1:
                leftover.append(cl[0])
                continue
            kind = _classify_cluster(cl)
            el = None

            def _fig():
                return _figure_in_budget([d for _, d in cl], blocks, p.images,
                                         consumed, p, page_text_area)

            if kind == "figure":
                el = _fig()
            elif kind == "grid":
                el = build_grid_table(cl, blocks, consumed) or _fig()
            elif kind == "cards":
                el = build_cards_table(cl, blocks, consumed)
            elif kind == "stripes":
                el = build_stripes_table(cl, blocks, consumed) or _fig()
            elif kind == "boxlike":
                el = build_box(cl, blocks, consumed)
                if el is None and len(cl) >= 4:
                    el = _fig()
            else:
                leftover.extend(cl)
            if el is not None:
                elements.append(el)
            elif kind != "loose":
                leftover.extend(cl)   # budget refused it: fall back to flow

        # booktabs groups among leftover long hlines
        hl = [(i, d) for i, d in leftover if d.shape == "hline"
              and (d.bbox[2] - d.bbox[0]) >= 60]
        groups = defaultdict(list)
        for i, d in hl:
            groups[(round(d.bbox[0] / 8), round(d.bbox[2] / 8))].append((i, d))
        used = set()
        for key, grp in groups.items():
            if len(grp) >= 2:
                ys = sorted(d.bbox[1] for _, d in grp)
                if ys[-1] - ys[0] < 320:
                    t = build_rules_table([d for _, d in grp], blocks, consumed)
                    if t is not None:
                        elements.append(t)
                        used.update(i for i, _ in grp)
        leftover = [(i, d) for i, d in leftover if i not in used]

        still = []
        for i, d in leftover:
            if d.fill and d.shape == "rect" and (d.bbox[2] - d.bbox[0]) > 30 and \
                    (d.bbox[3] - d.bbox[1]) > 10:
                el = build_box([(i, d)], blocks, consumed)
                if el is not None:
                    elements.append(el)
                    continue
            still.append((i, d))
        leftover = still

        for i, d in leftover:
            if d.shape == "vline" and (d.bbox[3] - d.bbox[1]) >= 16 and \
                    max(d.width, d.bbox[2] - d.bbox[0]) >= 1.8:
                zone = (d.bbox[2], d.bbox[1] - 2,
                        d.bbox[2] + min(0.9 * content_w, 500), d.bbox[3] + 2)
                probe = set(consumed)
                lines = _take_lines_in(blocks, zone, probe, mode="overlap")
                if lines:
                    consumed.update(id(l) for l in lines)
                    bb = d.bbox
                    for l in lines:
                        bb = bbox_union(bb, l.bbox)
                    minx = min(l.bbox[0] for l in lines)
                    cell = _cell_from_lines(sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])),
                                            (d.bbox[0], bb[1], bb[2], bb[3]))
                    cell.borders = {"left": (max(1.5, d.bbox[2] - d.bbox[0]),
                                             d.fill or d.stroke or "#000000")}
                    cell.pad = (0.5, round(minx - d.bbox[2], 1), 0.5, 2.0)
                    elements.append(TableEl(rows=[[cell]], col_widths=[bb[2] - d.bbox[0]],
                                            row_heights=[None], role="quote", bbox=bb))
                    continue
            if d.shape == "hline" and (d.bbox[2] - d.bbox[0]) >= 0.3 * content_w:
                r = RuleEl(width_pct=min(100.0, 100 * (d.bbox[2] - d.bbox[0]) / content_w),
                           thickness=max(0.5, d.width or (d.bbox[3] - d.bbox[1])),
                           color=d.stroke or d.fill or "#000000",
                           length=round(d.bbox[2] - d.bbox[0], 1),
                           left_indent=max(0.0, round(d.bbox[0] - lay.margin_l, 1)))
                r._bbox = d.bbox
                elements.append(r)
                continue
            if _is_glyphlike(d):
                continue        # stray ornament: not worth rasterising a region for
            if d.shape in ("curve", "complex", "line") or (
                    d.fill and bbox_area(d.bbox) > 400):
                elements.append(build_figure([d], blocks, p.images, consumed, p))

        for im in p.images:
            if getattr(im, "_consumed", False) or im.data is None:
                continue
            el = ImageEl(data=im.data, ext=im.ext,
                         width=im.bbox[2] - im.bbox[0], height=im.bbox[3] - im.bbox[1])
            el._bbox = im.bbox
            elements.append(el)

        elements = _merge_figures(elements)

        # rebuild flow blocks from unconsumed lines (contiguous runs)
        flow_blocks = []
        for b in blocks:
            cur = []
            for l in b.lines:
                if id(l) in consumed:
                    if cur:
                        flow_blocks.append(_mk_block(cur))
                        cur = []
                else:
                    cur.append(l)
            if cur:
                flow_blocks.append(_mk_block(cur))

        page_top = lay.margin_t
        if p.number == 1 and lay.cover_band is not None and lay.cover_band.bbox:
            page_top = lay.cover_band.bbox[3]
        pl.chunks = _assemble_chunks(elements, flow_blocks, lay, p, page_top)
        lay.pages.append(pl)

    _coalesce_striped_table_segments(lay)
    _mark_headings(lay, body_size)
    if _can_relax_bottom_margin(lay):
        # DOCX flow has no equivalent of PDF's last-baseline fit.  With a hard
        # source-page break, LibreOffice moving even one final line below the
        # inferred bottom reserve produces a mostly empty extra page. Give plain
        # flow documents the conventional 0.2in minimum reserve instead. This
        # is deliberately withheld when a header/footer, cover section, or a
        # figure-flow overlay could occupy the same physical bottom area.
        lay.margin_b = min(lay.margin_b, 14.0)
    return lay


def _mk_block(lines):
    bb = None
    for l in lines:
        bb = bbox_union(bb, l.bbox)
    return TextBlock(lines=list(lines), bbox=bb)


def _can_relax_bottom_margin(lay: DocLayout) -> bool:
    """Whether a document can safely use the ordinary 14pt bottom reserve.

    A footer or cover has its own vertical coordinate system, and graphic text
    that overlaps a figure cannot be represented as overlapping DOCX flow. Both
    make a global bottom-margin change an unsafe way to recover ordinary text
    overflow. The check is geometric and deliberately says nothing about fixture
    names or parser backends.
    """
    if lay.cover_band is not None:
        return False
    if any((lay.header_default, lay.footer_default, lay.header_first,
            lay.footer_first)):
        return False
    for page in lay.pages:
        elements = [el for chunk in page.chunks for el in chunk.elements]
        figures = [el for el in elements if isinstance(el, FigureEl)]
        for figure in figures:
            for element in elements:
                if element is figure or not isinstance(
                        element, (Para, TableEl, ImageEl, RuleEl)):
                    continue
                bbox = _el_bbox(element)
                if bbox is None:
                    continue
                # Include nearby axis labels: they can sit just outside a chart
                # while sharing its vertical band, and DOCX cannot overlap them
                # with an inline image the way the PDF does.
                if bbox[1] < figure.clip[3] and bbox[3] > figure.clip[1] and \
                        bbox[0] < figure.clip[2] + 36 and \
                        bbox[2] > figure.clip[0] - 36:
                    return False
    return True


def _merge_figures(elements):
    figs = [e for e in elements if isinstance(e, FigureEl)]
    other = [e for e in elements if not isinstance(e, FigureEl)]
    merged = True
    while merged:
        merged = False
        out = []
        for f in figs:
            hit = None
            for g in out:
                if bbox_overlap(_expand(f.clip, 4), g.clip) > 0:
                    hit = g
                    break
            if hit:
                nb = bbox_union(hit.clip, f.clip)
                hit.clip = nb
                hit.width, hit.height = nb[2] - nb[0], nb[3] - nb[1]
                merged = True
            else:
                out.append(f)
        figs = out
    return other + figs


def _el_bbox(e):
    if isinstance(e, Para):
        return e.bbox
    if isinstance(e, TableEl):
        return e.bbox
    if isinstance(e, FigureEl):
        return e.clip
    if isinstance(e, (ImageEl, RuleEl)):
        return getattr(e, "_bbox", None)
    return None


def _to_flow(items, col_l, col_r):
    out = []
    for kind, bb, o in sorted(items, key=lambda t: (t[1][1], t[1][0])):
        if kind == "blk":
            out.extend(paras_from_line_list(list(o.lines), col_l, col_r))
        else:
            el = o
            if isinstance(el, TableEl):
                el.left_indent = max(0.0, round((el.bbox[0] if el.bbox else col_l) - col_l, 1))
            elif isinstance(el, (FigureEl, ImageEl)):
                bbx = _el_bbox(el)
                if bbx:
                    cx = (bbx[0] + bbx[2]) / 2
                    if abs(cx - (col_l + col_r) / 2) < 8:
                        el.align = "center"
                    else:
                        el.align = "left"
                        el.left_indent = max(0.0, round(bbx[0] - col_l, 1))
            out.append(el)
    return out


def _mergeable(a: Para, b: Para) -> bool:
    if a.heading or b.heading:
        return False
    if any(r.is_tab for r in a.runs) or any(r.is_tab for r in b.runs):
        return False
    if a.align in ("center", "right") or b.align in ("center", "right"):
        return False
    if not a.bbox or not b.bbox:
        return False
    gap = b.bbox[1] - a.bbox[3]
    if not (-2.0 <= gap <= 3.2):
        return False
    if abs(b.bbox[0] - a.bbox[0]) > 2.5:
        return False
    sa = max((r.size for r in a.runs if r.text.strip()), default=0)
    sb = max((r.size for r in b.runs if r.text.strip()), default=0)
    return abs(sa - sb) < 0.6


def _merge_flow_paras(seq, col_r):
    out = []
    for el in seq:
        if out and isinstance(el, Para) and isinstance(out[-1], Para) \
                and _mergeable(out[-1], el):
            a = out[-1]
            if getattr(a, "_vis_lines", 1) == 1 and el.bbox and a.bbox:
                delta = round(el.bbox[1] - a.bbox[1], 2)
                if delta > 2:
                    a.leading = delta
            _soft_join(a.runs, el.text)
            was_flush = abs(a.bbox[2] - col_r) < 3.0
            a.runs += el.runs
            a.bbox = bbox_union(a.bbox, el.bbox)
            a._vis_lines = getattr(a, "_vis_lines", 1) + getattr(el, "_vis_lines", 1)
            if was_flush and a.align == "left":
                a.align = "justify"
            continue
        out.append(el)
    return out


def _is_marker_line(ln: Line) -> bool:
    t = ln.text.strip()
    return (ln.bbox[2] - ln.bbox[0]) < 44 and bool(
        t in BULLET_CHARS or NUM_RE.match(t))


def _merge_list_markers(flow_blocks):
    """Some producers (WeasyPrint) emit list markers as separate blocks —
    sometimes several markers stacked in ONE block. Glue each marker line back
    onto the item text line that shares its baseline."""
    marker_lines = []
    for b in flow_blocks:
        if all(_is_marker_line(l) or not l.text.strip() for l in b.lines):
            marker_lines.extend((l, b) for l in b.lines if _is_marker_line(l))
    marker_ids = {id(l) for l, _ in marker_lines}
    consumed = set()
    for ln, b in marker_lines:
        best = None  # (gap, line, block)
        for c in flow_blocks:
            for fl in c.lines:
                if id(fl) in marker_ids or id(fl) in consumed or not fl.spans:
                    continue
                gap = fl.bbox[0] - ln.bbox[2]
                if abs(fl.baseline - ln.baseline) < 2.5 and -1.0 < gap < 60:
                    if best is None or gap < best[0]:
                        best = (gap, fl, c)
        if best is not None:
            _, fl, c = best
            fl.spans[0:0] = list(ln.spans)
            fl.bbox = bbox_union(fl.bbox, ln.bbox)
            c.bbox = bbox_union(c.bbox, ln.bbox)
            consumed.add(id(ln))
    if not consumed:
        return flow_blocks
    out = []
    for b in flow_blocks:
        keep = [l for l in b.lines if id(l) not in consumed]
        if not keep:
            continue
        if len(keep) == len(b.lines):
            out.append(b)
            continue
        bb = None
        for l in keep:
            bb = bbox_union(bb, l.bbox)
        out.append(TextBlock(lines=keep, bbox=bb))
    return out


def _assemble_chunks(elements, flow_blocks, lay: DocLayout, page: PageIR,
                     page_top: Optional[float] = None) -> List[Chunk]:
    content_l, content_r = lay.margin_l, lay.page_w - lay.margin_r
    content_w = content_r - content_l
    flow_blocks = _merge_list_markers(flow_blocks)

    narrow = [b for b in flow_blocks if (b.bbox[2] - b.bbox[0]) <= 0.62 * content_w]
    twocol, col_split, col_y0 = False, None, None
    if narrow:
        lefts = _cluster([b.bbox[0] for b in narrow], 12.0)
        right_cands = [c for c in lefts if c >= content_l + 0.35 * content_w]
        if lefts and abs(lefts[0] - content_l) < 10 and right_cands:
            # dominant right-column cluster (by block count)
            def csize(c):
                return sum(1 for b in narrow if abs(b.bbox[0] - c) < 12)
            rc = max(right_cands, key=csize)
            c1 = [b for b in narrow if abs(b.bbox[0] - lefts[0]) < 12]
            c2 = [b for b in narrow if abs(b.bbox[0] - rc) < 12]
            h1 = sum(b.bbox[3] - b.bbox[1] for b in c1)
            h2 = sum(b.bbox[3] - b.bbox[1] for b in c2)
            if h1 > 60 and h2 > 60 and len(c2) >= 2:
                col_split = float(_mode([b.bbox[0] for b in c2], 0))
                ys1 = sorted(b.bbox[1] for b in c1)
                ys2 = sorted(b.bbox[1] for b in c2)
                cands = [y for y in ys1 if any(abs(y2 - y) < 160 for y2 in ys2)]
                cands += [y for y in ys2 if any(abs(y1_ - y) < 160 for y1_ in ys1)]
                if cands:
                    twocol = True
                    col_y0 = min(cands) - 4

    items = [("blk", b.bbox, b) for b in flow_blocks]
    for e in elements:
        bb = _el_bbox(e)
        items.append(("el", bb or (content_l, 0, content_r, 0), e))
    items.sort(key=lambda t: (t[1][1], t[1][0]))

    chunks: List[Chunk] = []
    if not twocol:
        ch = Chunk(n_cols=1)
        ch.elements = _merge_flow_paras(_to_flow(items, content_l, content_r), content_r)
        chunks.append(ch)
    else:
        # gutter between the columns (approximate)
        gut_r = col_split - 2
        gut_l = col_split - 26

        def is_lead(t):
            bb = t[1]
            if bb[3] > col_y0 + 4:
                return False
            w = bb[2] - bb[0]
            if w > 0.62 * content_w:
                return True
            # crosses the gutter (e.g. centered title parts) -> lead;
            # fits entirely inside one column -> belongs to the columns
            return not (bb[2] <= gut_l + 2 or bb[0] >= gut_r)

        lead = [t for t in items if is_lead(t)]
        rest = [t for t in items if not is_lead(t)]
        wide_tail = [t for t in rest if (t[1][2] - t[1][0]) > 0.62 * content_w]
        colitems = [t for t in rest if t not in wide_tail]
        if lead:
            ch = Chunk(n_cols=1)
            ch.elements = _merge_flow_paras(_to_flow(lead, content_l, content_r), content_r)
            chunks.append(ch)
        colL = [t for t in colitems if t[1][0] < col_split - 20]
        colR = [t for t in colitems if t[1][0] >= col_split - 20]
        gap = col_split - max((t[1][2] for t in colL), default=col_split - 24)
        gap = max(10.0, round(gap, 1))
        ch = Chunk(n_cols=2, col_gap=gap)
        colr_edge = col_split - gap
        left_flow = _merge_flow_paras(_to_flow(colL, content_l, colr_edge), colr_edge)
        right_flow = _merge_flow_paras(_to_flow(colR, col_split, content_r), content_r)
        ch.elements = left_flow + [ColBreak()] + right_flow
        chunks.append(ch)
        if wide_tail:
            ch2 = Chunk(n_cols=1)
            ch2.elements = _merge_flow_paras(_to_flow(wide_tail, content_l, content_r),
                                             content_r)
            chunks.append(ch2)

    base = page_top if page_top is not None else lay.margin_t
    for ch in chunks:
        top = base
        if ch.n_cols > 1:
            # columns must START at the first content top: renderers apply the
            # first paragraph's space-before to the whole column region, so we
            # hoist the common gap out of the columns into a pre-section spacer
            firsts = []
            take_next = True
            for el in ch.elements:
                if isinstance(el, ColBreak):
                    take_next = True
                    continue
                if take_next and _el_bbox(el) is not None:
                    t = _para_box(el)[0] if isinstance(el, Para) else _el_bbox(el)[1]
                    firsts.append(t)
                    take_next = False
            if firsts:
                target = min(firsts)
                ch.pre_gap = max(0.0, round(target - base, 1))
                top = base + ch.pre_gap
        cursor = top
        maxy = top
        for el in ch.elements:
            if isinstance(el, ColBreak):
                cursor = top
                continue
            bb = _el_bbox(el)
            if bb is None:
                continue
            if isinstance(el, Para):
                t, h = _para_box(el)
                el.space_before = max(0.0, round(t - cursor, 1))
                cursor = t + h
            else:
                el.space_before = max(0.0, round(bb[1] - cursor, 1))
                cursor = bb[3]
            maxy = max(maxy, cursor)
        base = maxy
    return chunks


def _body_font_size(ir: DocIR, hf) -> float:
    counter = Counter()
    for p in ir.pages:
        ct = hf["consumed_text"][p.number]
        for bi, b in enumerate(p.blocks):
            for l in b.lines:
                if (bi, id(l)) in ct:
                    continue
                for s in l.spans:
                    counter[round(s.size * 2) / 2] += len(s.text)
    return counter.most_common(1)[0][0] if counter else 10.5


def _n_lines(p: Para) -> int:
    return 1 + sum(r.text.count("\n") for r in p.runs)


def _para_box(p: Para):
    """(top, height) the paragraph occupies in Word terms, baseline-anchored.

    Word puts the baseline at (line_height - descent) from the line top when
    line spacing is 'exactly'. Anchoring on baselines keeps the vertical
    rhythm identical across renderers regardless of font bbox differences.
    """
    n = getattr(p, "_vis_lines", None) or _n_lines(p)
    L = p.leading or 0.0
    b1 = getattr(p, "_b1", None)
    if not L or b1 is None:
        bb = p.bbox or (0, 0, 0, 0)
        return bb[1], bb[3] - bb[1]
    desc = 0.21 * getattr(p, "_size1", 10.0)
    top = b1 - (L - desc)
    return top, n * L


def _mark_headings(lay: DocLayout, body_size: float):
    sizes = set()

    def candidates():
        for pg in lay.pages:
            for ch in pg.chunks:
                for el in ch.elements:
                    if isinstance(el, Para) and el.runs:
                        yield el

    for el in candidates():
        mx = max((r.size for r in el.runs if r.text.strip()), default=0)
        boldn = sum(len(r.text) for r in el.runs if r.bold)
        totn = max(1, sum(len(r.text) for r in el.runs))
        if mx >= body_size * 1.12 and boldn >= 0.6 * totn and _n_lines(el) <= 3 \
                and len(el.text) < 200:
            sizes.add(round(mx * 2) / 2)
    ranked = sorted(sizes, reverse=True)
    for el in candidates():
        mx = max((r.size for r in el.runs if r.text.strip()), default=0)
        boldn = sum(len(r.text) for r in el.runs if r.bold)
        totn = max(1, sum(len(r.text) for r in el.runs))
        key = round(mx * 2) / 2
        if key in ranked and boldn >= 0.6 * totn and _n_lines(el) <= 3 and len(el.text) < 200:
            el.heading = min(6, ranked.index(key) + 1)
