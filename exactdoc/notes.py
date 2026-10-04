"""Real footnotes: page-bottom note text matched 1:1 to its reference marks.

A PDF footnote is two pieces of ink with nothing joining them: a small raised
mark in the text and, at the foot of the page, smaller type that opens with the
same mark -- usually under a short rule. Every converter measured in the
benchmark left the second piece in the body flow (SCOTUS: 0 footnotes in every
tool's output), so a note did not move with its reference and an edit above it
shoved the note text mid-page.

This module finds the pairing and refuses to guess it:

* The NOTE ZONE is the run of lines at the bottom of a page set smaller than
  the body (`NOTE_SIZE_RATIO`), with no body-size line below it. It opens at a
  separator -- a short rule, or a typed line of dashes or underscores -- or at
  its first note.
* A NOTE opens with its mark, in one of the three forms the corpus uses:
  a superscript span at the head of the line (EUR-Lex: "(", "¹", ")", tab);
  a separate small raised fragment just left of the line (SCOTUS, LibreOffice:
  the parser returns "5" at 6pt as a line of its own, 2.5pt above and 1.1pt
  left of the note's first line); or a plain mark followed by a space.
* A REFERENCE is a superscript span outside the zone that reads as a mark
  (digits, or one of `SYMBOL_MARKS`).
* The page is accepted only if every note's mark has EXACTLY ONE reference on
  the page. Two candidate references for a mark -- "2" as a footnote and "2"
  as an exponent -- is ambiguous, and an ambiguous page keeps its typed form.
  Superscripts that match no note are left alone: they are exponents.

What is accepted is recorded twice, on purpose. The body flow keeps the zone's
paragraphs (marked `role="footnote"`) and the reference keeps its text, so a
profile without the footnotes capability writes exactly what it always wrote;
`DocLayout.footnotes` carries the same notes as real notes for the profile that
writes them.
"""
import dataclasses
import re
from typing import Dict, List, Optional, Tuple

from .layout import (ColBreak, DocLayout, Footnote, NoteArea, Para,
                     PageLayout, RuleEl, Run)
from .model import Line, bbox_union

SYMBOL_MARKS = "*†‡§¶‖#"
MARK_RE = re.compile(r"^(\d{1,3}|[%s]{1,3})$" % re.escape(SYMBOL_MARKS))
# Note text is set smaller than the body. Measured note/body size ratios:
# SCOTUS 9.0/11.0 = 0.82, EUR-Lex 8.5/9.6 = 0.885, LibreOffice 8.5/11 = 0.77,
# IEEEtran 8/10 = 0.80. 0.92 separates all of them from body text, whose
# size jitter is a few hundredths.
NOTE_SIZE_RATIO = 0.92
# A typed separator: a line of nothing but these, at least this long
# (SCOTUS "——————", LibreOffice "______..." x34).
SEPARATOR_CHARS = frozenset("—–‒―-_")
SEPARATOR_MIN_CHARS = 5
# A drawn separator is a short rule: wider than a stray tick, narrower than a
# full-measure rule (EUR-Lex 51pt and LibreOffice 118pt on 468-482pt columns;
# LaTeX's \footnoterule is 0.4 of the column), starting at the column edge.
SEP_RULE_MIN_W = 20.0
SEP_RULE_MAX_FRAC = 0.6
SEP_RULE_X_TOL = 12.0
# Largest gap between two consecutive zone lines, in ems of the larger.
ZONE_GAP_EM = 2.0
# A mark fragment sits just left of its line (measured gaps 0.0 and 1.1pt) and
# raised above its baseline (2.5pt, 3.15pt) by less than its line's size.
MARK_GAP_MAX_EM = 0.6
# The footnote area's own height beyond its notes, in the canonical
# LibreOffice: 0.1cm above the rule, the 0.5pt rule, 0.1cm below it. Measured
# by filling a page with 12pt lines plus one spacer under a 2-line note
# (scratch probe fn_probe2): an 8pt spacer fit, 10pt spilled, so the overhead
# is in (6, 8]pt, and the rule and the note's first line box read off the
# render put it at 6.2pt.
FOOTNOTE_AREA_OVERHEAD_PT = 6.2


@dataclasses.dataclass
class _Note:
    mark: str
    start: Line                  # the note's first line, mark merged in
    lines: List[Line]            # all its lines, first included
    form: str                    # 'sup' | 'frag' | 'plain'


@dataclasses.dataclass
class PageNotes:
    """One page's accepted footnote evidence, before the flow exists."""
    zone_top: float
    zone_bottom: float
    zone_lines: set              # id(Line) of every line in the zone
    notes: List[_Note]
    continuation: List[Line]     # lines continuing the previous page's last note
    sep_rule: Optional[Tuple[float, float, float, float]] = None


def _size(ln: Line) -> float:
    """The line's text size: its largest non-superscript span."""
    sz = [s.size for s in ln.spans if s.text.strip() and not s.superscript]
    return max(sz) if sz else max((s.size for s in ln.spans), default=0.0)


def _is_separator_text(ln: Line) -> bool:
    t = ln.text.strip()
    return len(t) >= SEPARATOR_MIN_CHARS and set(t) <= SEPARATOR_CHARS


def _lead_mark(ln: Line) -> Optional[Tuple[str, str]]:
    """(mark, form) when the line itself opens with a note mark."""
    spans = [s for s in ln.spans if s.text.strip()]
    if not spans:
        return None
    k = 0
    if spans[0].text.strip() == "(" and len(spans) > 1:
        k = 1                    # EUR-Lex: "(" "¹" ")"
    s = spans[k]
    if s.superscript and MARK_RE.match(s.text.strip()):
        return s.text.strip(), "sup"
    if k == 0:
        m = re.match(r"^\s*(\d{1,3}|[%s])\s+\S" % re.escape(SYMBOL_MARKS),
                     ln.text)
        if m and len(spans) and not spans[0].superscript:
            return m.group(1), "plain"
    return None


def _frag_host(frag: Line, lines: List[Line]) -> Optional[Line]:
    """The line a lone small raised mark fragment belongs to, if any."""
    t = frag.text.strip()
    if not MARK_RE.match(t) or len(frag.spans) != 1:
        return None
    best = None
    for ln in lines:
        if ln is frag or _is_separator_text(ln) or not ln.text.strip():
            continue
        hs = _size(ln)
        if frag.spans[0].size >= 0.92 * hs:
            continue             # same size: not a raised mark
        rise = ln.baseline - frag.baseline
        if not (0.05 * hs < rise < 0.75 * hs):
            continue
        gap = ln.bbox[0] - frag.bbox[2]
        if not (-0.5 <= gap <= MARK_GAP_MAX_EM * hs):
            continue
        if best is None or abs(gap) < abs(best.bbox[0] - frag.bbox[2]):
            best = ln
    return best


def _merge_frag(frag: Line, host: Line) -> Line:
    """The host line with the mark fragment as a leading superscript span.

    Copies: the original Lines still build the typed form untouched. The
    mark takes the host's baseline -- `Line.baseline` is its first span's, and
    the raise is what `superscript` says -- or the note's measured leading
    would carry the 2.5pt rise (SCOTUS: 13.4pt for a 10.8pt pitch)."""
    f0 = frag.spans[0]
    ms = dataclasses.replace(f0, superscript=True, text=f0.text.strip(),
                             origin=(f0.origin[0], host.baseline))
    spans = [ms] + [dataclasses.replace(s) for s in host.spans]
    return Line(spans=spans, bbox=bbox_union(frag.bbox, host.bbox),
                dir=host.dir)


def find_page_notes(flow_lines: List[Line], drawings, body_size: float,
                    col_l: float, col_r: float,
                    can_continue: bool) -> Optional[PageNotes]:
    """The page's footnote zone and notes, or None when there is no zone or
    it fails any test. `can_continue`: the previous page ended with an
    accepted note that unmarked lines at the top of this zone may continue.
    """
    lines = [l for l in flow_lines if l.horizontal and l.spans and l.text.strip()]
    if not lines or body_size <= 0:
        return None
    small_max = NOTE_SIZE_RATIO * body_size
    lines.sort(key=lambda l: (l.baseline, l.bbox[0]))
    # Walk up from the bottom while the type stays small.
    run = []
    for ln in reversed(lines):
        if _size(ln) <= small_max or _is_separator_text(ln):
            run.append(ln)
            continue
        break
    if not run:
        return None
    run.reverse()
    run_ids = {id(l) for l in run}
    body = [l for l in lines if id(l) not in run_ids]
    body_bottom = max((l.bbox[3] for l in body), default=0.0)
    # Note starts inside the run, mark fragments resolved to their hosts.
    frags = {}
    for ln in run:
        h = _frag_host(ln, run)
        if h is not None:
            frags[id(ln)] = h
    starts = {}
    for ln in run:
        if id(ln) in frags:
            continue
        hosts = [f for f, h in frags.items() if h is ln]
        if hosts:
            frag = next(l for l in run if id(l) == hosts[0])
            starts[id(ln)] = (frag.text.strip(), "frag", _merge_frag(frag, ln))
            continue
        lm = _lead_mark(ln)
        if lm is not None:
            starts[id(ln)] = (lm[0], lm[1], ln)
    # A plain digit at the head of a small line is the weakest form: a note's
    # continuation line can open "21 May 2024" (EUR-Lex) or "85 F. 4th"
    # (SCOTUS). It opens a note only on a page whose notes all use that form
    # and when a superscript reference with its value stands in the body.
    body_sups = set()
    for ln in body:
        for s in ln.spans:
            if s.superscript and MARK_RE.match(s.text.strip()):
                body_sups.add(s.text.strip())
    strong = any(st[1] != "plain" for st in starts.values())
    for k in [k for k, st in starts.items() if st[1] == "plain"]:
        if strong or starts[k][0] not in body_sups:
            del starts[k]
    if not starts:
        return None
    first_i = min(i for i, ln in enumerate(run) if id(ln) in starts)
    # The separator: a typed line inside the run above the first note, or a
    # short rule between the body and the run.
    sep_i = None
    for i in range(first_i - 1, -1, -1):
        if _is_separator_text(run[i]):
            sep_i = i
            break
    sep_rule = None
    zone_first_top = run[first_i].bbox[1] if sep_i is None else run[sep_i].bbox[3]
    for d in drawings or ():
        w = d.bbox[2] - d.bbox[0]
        if d.shape in ("hline", "rect") and (d.bbox[3] - d.bbox[1]) <= 1.5 \
                and SEP_RULE_MIN_W <= w <= SEP_RULE_MAX_FRAC * (col_r - col_l) \
                and abs(d.bbox[0] - col_l) <= SEP_RULE_X_TOL \
                and body_bottom - 1.0 <= d.bbox[1] <= zone_first_top + 1.0:
            sep_rule = d.bbox
            break
    # Lines between the separator and the first note continue a note from
    # the previous page; without a separator they are small BODY text (a
    # table note, a caption) and stay out of the zone.
    if sep_i is not None:
        zone = run[sep_i:]
        cont = [l for l in run[sep_i + 1:first_i] if id(l) not in frags]
    elif sep_rule is not None:
        above = [l for l in run[:first_i] if l.bbox[1] >= sep_rule[3] - 1.0]
        zone = above + run[first_i:]
        cont = [l for l in above if id(l) not in frags]
    else:
        zone = run[first_i:]
        cont = []
    if cont and not can_continue:
        return None
    # A note zone is one compact block. A wide gap inside it means the small
    # type below is something else -- y60's QuickStats page has a chart note
    # ("†") 47pt above 9pt body text, and taking that text for the note's
    # continuation would have lifted it out of the page. The widest gap
    # between notes measured is LibreOffice's 11.8pt at 8.5pt type (1.4x).
    tops = sorted(zone, key=lambda l: l.bbox[1])
    for a, b in zip(tops, tops[1:]):
        if b.bbox[1] - a.bbox[3] > ZONE_GAP_EM * max(_size(a), _size(b)):
            return None
    # Every zone line inside the column.
    if any(l.bbox[0] < col_l - 3.0 or l.bbox[2] > col_r + 3.0 for l in zone):
        return None
    notes: List[_Note] = []
    for ln in zone:
        if id(ln) in frags or _is_separator_text(ln):
            continue
        if id(ln) in starts:
            mark, form, merged = starts[id(ln)]
            notes.append(_Note(mark, merged, [merged], form))
        elif notes:
            notes[-1].lines.append(ln)
    if not notes:
        return None
    marks = [n.mark for n in notes]
    if len(set(marks)) != len(marks):
        return None              # two notes with one mark: unmatchable
    top = sep_rule[1] if sep_rule is not None else min(l.bbox[1] for l in zone)
    return PageNotes(zone_top=top, zone_bottom=max(l.bbox[3] for l in zone),
                     zone_lines={id(l) for l in zone}, notes=notes,
                     continuation=cont, sep_rule=sep_rule)


def _el_box(el):
    if isinstance(el, Para):
        return el.bbox
    if isinstance(el, RuleEl):
        return getattr(el, "_bbox", None)
    return getattr(el, "bbox", None) or getattr(el, "clip", None)


def _zone_elements(pl: PageLayout, pn: PageNotes):
    """The page's flow elements that ARE the zone, or None when the zone does
    not stand cleanly at the end of a one-column flow."""
    seq = [(ch, el) for ch in pl.chunks for el in ch.elements]
    zone, seen_zone = [], False
    for ch, el in seq:
        bb = _el_box(el)
        inside = bb is not None and bb[1] >= pn.zone_top - 1.0 \
            and bb[3] <= pn.zone_bottom + 1.0
        # A rule BELOW the notes is page furniture the header/footer pass did
        # not lift (EUR-Lex draws its footer rule in two segments, 1.6pt
        # under the last note line on every page). It cannot stay in the body
        # once the notes leave it -- it would land between the text and the
        # footnote area -- so it goes with the zone.
        below = isinstance(el, RuleEl) and bb is not None and \
            bb[1] >= pn.zone_bottom - 1.0
        if (inside or below) and isinstance(el, (Para, RuleEl)):
            if ch.n_cols != 1:
                return None      # notes in a column flow: not modelled
            zone.append(el)
            seen_zone = True
            continue
        if seen_zone:
            return None          # something follows the notes on this page
        if bb is not None and bb[3] > pn.zone_top + 1.0 and \
                not isinstance(el, ColBreak):
            return None          # an element straddles the zone's top
    return zone or None


def _split_run(runs: List[Run], i: int, mark: str) -> int:
    """Isolate `mark` inside runs[i] (padding whitespace split off). Returns
    the index of the run that is exactly the mark."""
    r = runs[i]
    t = r.text
    k = t.find(mark)
    if k < 0:
        raise ValueError("run %r does not hold mark %r" % (t, mark))
    pre, post = t[:k], t[k + len(mark):]
    parts = []
    if pre:
        parts.append(dataclasses.replace(r, text=pre))
    parts.append(dataclasses.replace(r, text=mark))
    if post:
        parts.append(dataclasses.replace(r, text=post))
    runs[i:i + 1] = parts
    return i + (1 if pre else 0)


def _tag_refs(pl: PageLayout, zone_ids: set, marks: List[str]):
    """{mark: (para, run)} for each mark's unique reference run, or None when
    any mark has no reference run or more than one.

    The RUN, not its index: two references in one paragraph are split one
    after the other, and the first split shifts every index after it -- an
    index kept from here pointed the second split at the wrong run, which
    duplicated text on y28 ("payment2payments2")."""
    found = {m: [] for m in marks}
    for ch in pl.chunks:
        for el in ch.elements:
            if not isinstance(el, Para) or id(el) in zone_ids:
                continue
            for r in el.runs:
                t = r.text.strip()
                if r.superscript and t in found and r.footnote is None:
                    found[t].append((el, r))
    if any(len(v) != 1 for v in found.values()):
        return None
    return {m: v[0] for m, v in found.items()}


def _note_paras(lines: List[Line], col_l: float, col_r: float) -> List[Para]:
    """The note's paragraphs, built as any body paragraph is.

    One correction: a one-line paragraph takes its height from its first
    span's size (`para_from_lines`), and a note's first span is its mark --
    4.6pt over 8.5pt text on the LibreOffice note, which made a 5.3pt line.
    The text's own size is the one that sets the line.
    """
    from .infer import paras_from_line_list
    paras = paras_from_line_list(lines, col_l, col_r)
    for p in paras:
        sz = max((r.size for r in p.runs if r.text.strip() and not r.superscript
                  and not r.is_tab), default=0.0)
        if sz <= 0:
            continue
        p._size1 = sz
        # ... and no line is shorter than its type: lshort's "LuaTEX" logo
        # drops its E below the line, the parser returns two "lines" 1.9pt
        # apart, and an exact 1.9pt line would print the note on top of itself.
        if p.src_lines <= 1 or p.leading < sz:
            p.leading = round(max(sz * 1.16, 4.0), 2)
    return paras


def _gap_chain(paras: List[Para], first_gap: float = 0.0):
    """space_before for note paragraphs from their own baselines (the same
    baseline-anchored box model as the body; THEORY §3.1)."""
    prev_bottom = None
    for p in paras:
        lead = p.leading or 0.0
        size1 = getattr(p, "_size1", 0.0) or 0.0
        b1 = getattr(p, "_b1", None)
        n = getattr(p, "_vis_lines", None) or max(1, p.src_lines)
        if b1 is None or lead <= 0:
            p.space_before = 0.0
            continue
        top = b1 - (lead - 0.21 * size1)
        p.space_before = first_gap if prev_bottom is None else \
            round(max(0.0, top - prev_bottom), 1)
        prev_bottom = top + n * lead


def _mark_run(p: Para, mark: str) -> bool:
    """Flag the note's own mark at the head of its first paragraph.

    The note's own mark must OPEN the note: a renderer prints its number at
    the head of the note and LibreOffice prints any w:footnoteRef that is not
    first as a second copy -- EUR-Lex's "(¹)" came out "⁶(⁶)". So parentheses
    wrapping the mark are dropped from the note (they stay at the reference
    in the text, where they are ordinary characters).
    """
    for i, r in enumerate(p.runs[:4]):
        if r.is_tab:
            continue
        t = r.text.strip()
        if t == mark or (t.startswith(mark) and not r.superscript):
            j = _split_run(p.runs, i, mark)
            p.runs[j].footnote_mark = True
            if j > 0 and p.runs[j - 1].text.strip() == "(":
                del p.runs[j - 1]
                j -= 1
            if j + 1 < len(p.runs) and p.runs[j + 1].text.startswith(")"):
                rest = p.runs[j + 1].text[1:]
                if rest:
                    p.runs[j + 1] = dataclasses.replace(p.runs[j + 1], text=rest)
                else:
                    del p.runs[j + 1]
            del p.runs[:j]            # nothing may precede the mark
            return True
        if t and t != "(":
            return False
    return False


def bind_page_notes(lay: DocLayout, pl: PageLayout, pn: PageNotes,
                    col_l: float, col_r: float) -> int:
    """Turn a page's accepted evidence into Footnotes once its flow exists.

    Returns the number of notes bound; 0 leaves the page exactly as built.
    """
    zone = _zone_elements(pl, pn)
    if zone is None:
        return 0
    zone_ids = {id(e) for e in zone}
    marks = [n.mark for n in pn.notes]
    refs = _tag_refs(pl, zone_ids, marks)
    if refs is None:
        return 0
    built = []
    for n in pn.notes:
        paras = _note_paras(n.lines, col_l, col_r)
        if not paras or not _mark_run(paras[0], n.mark):
            return 0
        built.append(paras)
    cont = _note_paras(pn.continuation, col_l, col_r) if pn.continuation else []
    if pn.continuation and not lay.footnotes:
        return 0
    # Accepted: from here on the page is committed.
    all_paras = [p for paras in built for p in paras]
    _gap_chain(cont + all_paras)
    last = all_paras[-1]
    pl.note_area = NoteArea(
        top=pn.zone_top,
        bottom=(getattr(last, "_b1", 0.0) or 0.0)
        + (max(1, last.src_lines) - 1) * (last.leading or 0.0)
        + 0.21 * (getattr(last, "_size1", 0.0) or 0.0),
        height=sum(p.space_before + max(1, p.src_lines) * (p.leading or 0.0)
                   for p in cont + all_paras))
    if cont:
        prev = lay.footnotes[-1]
        prev.continued = True
        prev_page = next((q for q in reversed(lay.pages)
                          if q.number == prev.page), None)
        if prev_page is not None and prev_page.note_area is not None:
            prev_page.note_area.runs_on = True
        cont[0].space_before = 0.0
        last = prev.paras[-1] if prev.paras else None
        if last is not None and abs(cont[0].first_indent) <= 1.0 \
                and not last.line_breaks and not cont[0].line_breaks:
            # The source broke one paragraph across the page: it is one
            # paragraph again, as the renderer will split it where it must.
            from .infer import _soft_join
            _soft_join(last.runs, cont[0].text)
            last.runs.extend(cont[0].runs)
            last.src_lines += cont[0].src_lines
            last.src_widths = list(last.src_widths) + list(cont[0].src_widths)
            cont = cont[1:]
        prev.paras.extend(cont)
    if all_paras:
        all_paras[0].space_before = 0.0     # first under the rule
    for n, paras in zip(pn.notes, built):
        fid = len(lay.footnotes)
        el, run = refs[n.mark]
        i = next(k for k, r in enumerate(el.runs) if r is run)
        j = _split_run(el.runs, i, n.mark)
        el.runs[j].footnote = fid
        value = int(n.mark) if n.mark.isdigit() else 0
        lay.footnotes.append(Footnote(fid=fid, page=pl.number, mark=n.mark,
                                      value=value, paras=paras))
    for e in zone:
        e.role = "footnote"
    return len(pn.notes)


def footnote_areas(lay: DocLayout, body_bottom) -> Dict[int, float]:
    """{page: footnote-area height} for the pages whose notes are written as
    notes. `body_bottom(page_layout)` is the y where that page's body box ends
    in the renderer -- the footnote area's foot.

    A renderer stacks a page's notes at the foot of the body box under its own
    rule (`FOOTNOTE_AREA_OVERHEAD_PT`), and the body gets what is left above.
    The notes are not lifted to their source height: a space after the last
    note -- the obvious lever -- is not honoured at the foot of LibreOffice's
    footnote area (measured: 248pt asked, 0 moved), so the page model charges
    only what the renderer actually draws.

    A page whose last note runs on to the next page is charged everything
    below the source zone's top: its notes fill the page to its foot, and the
    renderer splits the note where the source did.
    """
    out: Dict[int, float] = {}
    for pl in lay.pages:
        na = pl.note_area
        if na is None:
            continue
        if na.runs_on:
            out[pl.number] = max(0.0, body_bottom(pl) - na.top)
        else:
            out[pl.number] = na.height + FOOTNOTE_AREA_OVERHEAD_PT
    return out


def number_footnotes(lay: DocLayout) -> None:
    """Decide which notes the renderer's own counter numbers correctly.

    Word and LibreOffice number footnotes by their order in the document, from
    `numStart`, optionally restarting on each page; a note with a custom mark
    is outside the count. A note gets the automatic number only where that
    count reproduces its source mark; anywhere else (symbols, a restart the
    count cannot express such as a SCOTUS dissent starting again at 1, a gap
    left by a page whose notes stayed typed) it keeps the source's mark as a
    custom mark. The numbers a reader sees are the source's either way.
    """
    fns = lay.footnotes
    if not fns:
        return
    digits = [f for f in fns if f.mark.isdigit()]
    for f in fns:
        f.auto = False
    if not digits:
        return
    pages = {}
    for f in digits:
        pages.setdefault(f.page, []).append(f.value)
    restarts = sum(1 for vals in pages.values() if vals and vals[0] == 1)
    per_page = len(pages) >= 2 and restarts >= 2 and all(
        vals == list(range(1, len(vals) + 1)) for vals in pages.values())
    if per_page:
        lay.footnote_restart, lay.footnote_start = "eachPage", 1
        for f in digits:
            f.auto = True
        return
    lay.footnote_restart = "continuous"
    lay.footnote_start = digits[0].value
    counter = digits[0].value
    for f in digits:
        if f.value == counter:
            f.auto = True
            counter += 1
