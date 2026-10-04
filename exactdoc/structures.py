"""Real Word structures: lists as numbering.xml, footnotes as footnotes.xml.

Serialisation only. Which paragraphs form which list, and which page-bottom
text is which note, is inference's call (`lists.assign_lists`,
`notes.detect_footnotes`); whether a profile writes them at all is
`options.PROFILE_CAPABILITIES`. This module turns the layout's `ListDef`s and
`Footnote`s into OOXML and does nothing else.

Every structure here is written to land where the typed form it replaces
landed, so that turning the capability on is an editability change and not a
fidelity one:

* A list level's `w:ind` is the indent the typed paragraph carried, its
  `w:suff` is the separator the source typed (a tab to the hanging indent, or
  a space), and its `w:rPr` is the typed marker's own typography. A paragraph
  whose indents match its level carries no direct `w:ind` -- that is what lets
  Word re-indent it when a reader changes its level.
* A footnote reference run is styled exactly like the superscript run it
  replaces; the note's paragraphs are written by the same paragraph writer as
  any body paragraph.
"""
import dataclasses
from typing import Dict, List, Optional

from docx.oxml import OxmlElement
from docx.oxml.ns import qn, nsdecls

from .fonts import map_font
from .layout import DocLayout, ListDef, ListItem, ListLevel, Para, Run

_SPACES = "  "


def _tw(pt: float) -> str:
    return str(int(round(pt * 20)))


# --------------------------------------------------------------------- lists
def strip_marker(runs: List[Run], item: ListItem) -> Optional[List[Run]]:
    """`runs` without the typed marker and its separator, or None when the
    runs do not open with `item.marker` (the caller then keeps the typed form).

    Never mutates `runs`: the layout is written once per refine round.
    """
    out = list(runs)
    i = 0
    while i < len(out) and not out[i].is_tab and not out[i].text.strip():
        i += 1
    need, pos = item.marker, 0
    while pos < len(need):
        if i >= len(out) or out[i].is_tab or out[i].footnote is not None:
            return None
        t = out[i].text.lstrip(_SPACES) if pos == 0 else out[i].text
        take = min(len(t), len(need) - pos)
        if take <= 0 or t[:take] != need[pos:pos + take]:
            return None
        pos += take
        rest = t[take:]
        if rest:
            out[i] = dataclasses.replace(out[i], text=rest)
        else:
            i += 1
    if item.sep == "nothing":
        return out[i:]           # the typed space stays text: see lists.py
    # the separator the level's w:suff now draws
    if i < len(out) and out[i].is_tab:
        i += 1
    else:
        while i < len(out) and not out[i].is_tab:
            t = out[i].text.lstrip(_SPACES)
            if t:
                if t != out[i].text:
                    out[i] = dataclasses.replace(out[i], text=t)
                break
            i += 1
    return out[i:]


def numbering_plan(lay: DocLayout) -> Dict[int, ListDef]:
    """{list_id: ListDef} for the lists every item of which can be written.

    A list is all or nothing: if one item's runs no longer open with its
    marker, the renderer's counter would skip that item and misnumber every
    item after it, so the whole list keeps its typed form.
    """
    ok = {ld.list_id: ld for ld in lay.lists}
    for pg in lay.pages:
        for ch in pg.chunks:
            for el in ch.elements:
                if isinstance(el, Para) and el.numbering is not None and \
                        el.numbering.list_id in ok and \
                        strip_marker(el.runs, el.numbering) is None:
                    del ok[el.numbering.list_id]
    return ok


def _marker_rpr(run: Optional[Run], profile: str):
    rpr = OxmlElement("w:rPr")
    if run is None:
        return rpr
    fam = map_font(run.font, mono=run.mono, serif=run.serif, profile=profile)
    rf = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(attr), fam)
    rf.set(qn("w:hint"), "default")
    rpr.append(rf)
    # schema order: rFonts, b, i, color, sz, szCs, vertAlign
    for on, tag in ((run.bold, "w:b"), (run.italic, "w:i")):
        el = OxmlElement(tag)
        if not on:
            el.set(qn("w:val"), "0")
        rpr.append(el)
    col = OxmlElement("w:color")
    col.set(qn("w:val"), (run.color or "#000000").lstrip("#").upper())
    rpr.append(col)
    # The typed marker carried its run's letter-spacing and width scale (WP10's
    # source tracking, the ladder's compression, metrics.run_width_scale), so
    # the label must too: without them x17's item text sat 0.58pt left and
    # x09's 0.90pt. Same rules as the writer's own run styling.
    spacing = (run.char_spacing or 0.0) + (getattr(run, "tracking", 0.0) or 0.0)
    if abs(spacing) > 0.004:
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:val"), str(int(round(spacing * 20))))
        rpr.append(sp)
    ws = run.width_scale or 0.0
    if ws > 0 and abs(ws - 1.0) > 0.004 and profile == "standard":
        w = OxmlElement("w:w")
        w.set(qn("w:val"), str(int(round(ws * 100))))
        rpr.append(w)
    hp = str(int(round(round(run.size * 2) / 2 * 2)))
    for tag in ("w:sz", "w:szCs"):
        el = OxmlElement(tag)
        el.set(qn("w:val"), hp)
        rpr.append(el)
    if run.superscript:
        va = OxmlElement("w:vertAlign")
        va.set(qn("w:val"), "superscript")
        rpr.append(va)
    return rpr


def _lvl(k: int, lvl: ListLevel, profile: str):
    el = OxmlElement("w:lvl")
    el.set(qn("w:ilvl"), str(k))

    def child(tag, val):
        c = OxmlElement(tag)
        c.set(qn("w:val"), str(val))
        el.append(c)
    child("w:start", max(0, lvl.start))
    child("w:numFmt", lvl.fmt)
    child("w:suff", lvl.sep if lvl.sep in ("space", "nothing") else "tab")
    child("w:lvlText", lvl.text)
    child("w:lvlJc", "left")
    ppr = OxmlElement("w:pPr")
    if lvl.sep == "tab":
        tabs = OxmlElement("w:tabs")
        tab = OxmlElement("w:tab")
        tab.set(qn("w:val"), "num")
        tab.set(qn("w:pos"), _tw(lvl.left))
        tabs.append(tab)
        ppr.append(tabs)
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), _tw(lvl.left))
    if lvl.hanging >= 0:
        ind.set(qn("w:hanging"), _tw(lvl.hanging))
    else:
        ind.set(qn("w:firstLine"), _tw(-lvl.hanging))
    ppr.append(ind)
    el.append(ppr)
    el.append(_marker_rpr(lvl.marker_run, profile))
    return el


# Indent step for the levels a source never used, so that demoting an item in
# Word still moves it right. 18pt is a quarter inch, the step every measured
# nested list used (x03: 18/36/54; x09: 22/44/66 is the CSS 40px).
_LEVEL_STEP_PT = 18.0


def _all_levels(ld: ListDef) -> Dict[int, ListLevel]:
    """Levels 0-8: the measured ones, and plausible ones around them."""
    have = dict(ld.levels)
    out = {}
    for k in range(9):
        if k in have:
            out[k] = have[k]
            continue
        below = [j for j in have if j < k]
        above = [j for j in have if j > k]
        ref = have[max(below)] if below else have[min(above)]
        step = (k - max(below)) if below else (k - min(above))
        out[k] = ListLevel(
            fmt=ref.fmt if ref.fmt == "bullet" else "decimal",
            start=1,
            text=ref.text if ref.fmt == "bullet" else "%%%d." % (k + 1),
            sep=ref.sep, left=max(0.0, ref.left + step * _LEVEL_STEP_PT),
            hanging=ref.hanging, marker_run=ref.marker_run)
    return out


def numbering_base(doc) -> int:
    """First id free in BOTH w:abstractNumId and w:numId.

    python-docx's template already defines nine lists for its built-in
    List Bullet / List Number styles (numId 1-9 over abstractNum 0-8); a list
    written as numId 1 would silently be the template's "%1." at 90pt.
    """
    root = doc.part.numbering_part.element
    used = [0]
    for tag, attr in (("w:abstractNum", "w:abstractNumId"), ("w:num", "w:numId")):
        for el in root.findall(qn(tag)):
            try:
                used.append(int(el.get(qn(attr))))
            except (TypeError, ValueError):
                pass
    return max(used) + 1


def write_numbering(doc, list_defs: Dict[int, ListDef], profile: str,
                    base: int) -> None:
    """One w:abstractNum and one w:num per list, both numbered base + list_id.

    One abstractNum per num on purpose: Word shares a level counter between
    every num that points at the same abstractNum, so two lists sharing one
    definition would count as one.
    """
    if not list_defs:
        return
    root = doc.part.numbering_part.element
    first_num = root.find(qn("w:num"))
    for lid in sorted(list_defs):
        ld = list_defs[lid]
        an = OxmlElement("w:abstractNum")
        an.set(qn("w:abstractNumId"), str(base + lid))
        mlt = OxmlElement("w:multiLevelType")
        mlt.set(qn("w:val"), "multilevel")
        an.append(mlt)
        for k, lvl in sorted(_all_levels(ld).items()):
            an.append(_lvl(k, lvl, profile))
        # schema: every abstractNum precedes every num
        if first_num is not None:
            first_num.addprevious(an)
        else:
            root.append(an)
    for lid in sorted(list_defs):
        num = OxmlElement("w:num")
        num.set(qn("w:numId"), str(base + lid))
        ref = OxmlElement("w:abstractNumId")
        ref.set(qn("w:val"), str(base + lid))
        num.append(ref)
        root.append(num)


def level_carries_indent(p: Para, lvl: ListLevel) -> bool:
    """Do the level's indents already say what this paragraph needs?"""
    return round(p.left_indent, 1) == round(lvl.left, 1) and \
        round(-p.first_indent, 1) == round(lvl.hanging, 1)


def num_tab_override(par, level_pos: float, pos: float) -> None:
    """Replace the level's num tab stop with one at `pos` for this paragraph:
    w:tab clear at the level's stop, w:tab num at the paragraph's indent.
    Word's form; LibreOffice keeps the level's stop regardless (measured)."""
    tabs = par._p.get_or_add_pPr().get_or_add_tabs()
    want = []
    if abs(level_pos - pos) >= 0.05:
        want.append(("clear", level_pos))
    want.append(("num", pos))
    for val, at in want:
        t = OxmlElement("w:tab")
        t.set(qn("w:val"), val)
        t.set(qn("w:pos"), _tw(at))
        nxt = None
        for old in tabs.findall(qn("w:tab")):
            if int(old.get(qn("w:pos"), "0")) > int(_tw(at)):
                nxt = old
                break
        if nxt is not None:
            nxt.addprevious(t)
        else:
            tabs.append(t)


def apply_numpr(par, item: ListItem, base: int) -> None:
    ppr = par._p.get_or_add_pPr()
    numpr = ppr.get_or_add_numPr()
    numpr.get_or_add_ilvl().val = item.level
    numpr.get_or_add_numId().val = base + item.list_id


# ------------------------------------------------------------------ footnotes
def add_footnote_reference(par, run: Run, wid: int, custom: bool, style_run):
    """A w:footnoteReference run, styled as the source mark's run.

    `style_run(r, run)` is the writer's own run styling, so the reference sits
    exactly where the typed superscript sat. A custom mark carries the
    source's mark text after the reference, as Word itself writes one.
    """
    r = par.add_run()
    style_run(r, run)
    _set_style(r._r, "w:rPr", "w:rStyle", "FootnoteReference")
    ref = OxmlElement("w:footnoteReference")
    if custom:
        ref.set(qn("w:customMarkFollows"), "1")
    ref.set(qn("w:id"), str(wid))
    r._r.append(ref)
    if custom:
        t = OxmlElement("w:t")
        t.text = run.text.strip()
        r._r.append(t)
    return r


def add_footnote_ref_mark(par, run: Run, custom: bool, style_run):
    """The note's own mark at the head of its text: w:footnoteRef, or the
    custom mark as text (which is how Word stores one, and which the
    character style tells LibreOffice not to print a second time)."""
    if custom:
        r = par.add_run(run.text.strip())
    else:
        r = par.add_run()
    style_run(r, run)
    _set_style(r._r, "w:rPr", "w:rStyle", "FootnoteReference")
    if not custom:
        r._r.append(OxmlElement("w:footnoteRef"))
    return r


FOOTNOTES_CT = ("application/vnd.openxmlformats-officedocument."
                "wordprocessingml.footnotes+xml")
FOOTNOTES_RT = ("http://schemas.openxmlformats.org/officeDocument/2006/"
                "relationships/footnotes")


def _separator_note(wid: int, kind: str):
    """Word requires the separator (-1) and continuation separator (0) notes.

    The paragraph is pinned to an exact line rather than the template's
    Normal line, because in Word the separator's height comes out of the page
    body. LibreOffice ignores it and draws its own rule with 0.1cm either
    side (measured: separators of 1pt, 6pt and the template default render
    identically) -- `notes.FOOTNOTE_AREA_OVERHEAD_PT` -- and the exact line is
    set to that overhead so Word's area is the same height. Unmeasured in
    Word.
    """
    fn = OxmlElement("w:footnote")
    fn.set(qn("w:type"), kind)
    fn.set(qn("w:id"), str(wid))
    p = OxmlElement("w:p")
    ppr = OxmlElement("w:pPr")
    sp = OxmlElement("w:spacing")
    sp.set(qn("w:before"), "0")
    sp.set(qn("w:after"), "0")
    sp.set(qn("w:line"), _tw(SEPARATOR_LINE_PT))
    sp.set(qn("w:lineRule"), "exact")
    ppr.append(sp)
    p.append(ppr)
    r = OxmlElement("w:r")
    r.append(OxmlElement("w:" + kind))
    p.append(r)
    fn.append(p)
    return fn


# Height of the separator paragraph (Word); see _separator_note.
SEPARATOR_LINE_PT = 6.0


def new_footnotes_root():
    root = OxmlElement("w:footnotes")
    root.append(_separator_note(-1, "separator"))
    root.append(_separator_note(0, "continuationSeparator"))
    return root


def attach_footnotes_part(doc, root) -> None:
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from lxml import etree
    blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                          standalone=True)
    part = Part(PackURI("/word/footnotes.xml"), FOOTNOTES_CT, blob,
                doc.part.package)
    doc.part.relate_to(part, FOOTNOTES_RT)


def footnote_plan(lay: DocLayout) -> Dict[int, tuple]:
    """{fid: (w:id, custom_mark)} for the notes to write, or {} for none.

    All or nothing, like a list: a note whose reference run did not survive
    to the writer would be a note with no anchor, and its text -- already
    left out of the body -- would vanish. So every note must have exactly one
    reference run in the flow, or the document is written typed.
    """
    if not lay.footnotes:
        return {}
    refs = {}
    for pg in lay.pages:
        for ch in pg.chunks:
            for el in ch.elements:
                if isinstance(el, Para) and el.role != "footnote":
                    for r in el.runs:
                        if r.footnote is not None:
                            refs[r.footnote] = refs.get(r.footnote, 0) + 1
    if any(refs.get(f.fid, 0) != 1 for f in lay.footnotes) or \
            len(refs) != len(lay.footnotes):
        return {}
    return {f.fid: (f.fid + 1, not f.auto) for f in lay.footnotes}


# Word's built-in names. LibreOffice maps them onto its own footnote styles,
# and that mapping is what makes its footnote-area label come out raised and
# small (measured: 11.0pt upright without the character style, 6.4pt
# superscript with it) and what stops it printing a custom mark twice (once
# as its label, once as the literal text Word stores after it).
_FN_TEXT_STYLE = (
    '<w:style %s w:type="paragraph" w:styleId="FootnoteText">'
    '<w:name w:val="footnote text"/><w:basedOn w:val="Normal"/>'
    '<w:uiPriority w:val="99"/><w:unhideWhenUsed/>'
    '<w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
    '<w:rPr><w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr></w:style>')
_FN_REF_STYLE = (
    '<w:style %s w:type="character" w:styleId="FootnoteReference">'
    '<w:name w:val="footnote reference"/><w:basedOn w:val="DefaultParagraphFont"/>'
    '<w:uiPriority w:val="99"/><w:unhideWhenUsed/>'
    '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style>')


def _ensure_footnote_styles(doc, note_size: float) -> None:
    from docx.oxml import parse_xml
    styles = doc.styles.element
    have = {s.get(qn("w:styleId")) for s in styles.findall(qn("w:style"))}
    hp = int(round(round(note_size * 2) / 2 * 2)) or 20
    if "FootnoteText" not in have:
        styles.append(parse_xml(_FN_TEXT_STYLE % (nsdecls("w"), hp, hp)))
    if "FootnoteReference" not in have:
        styles.append(parse_xml(_FN_REF_STYLE % nsdecls("w")))


def _set_style(el, tag_pr: str, tag_style: str, val: str):
    pr = el.find(qn(tag_pr))
    if pr is None:
        pr = OxmlElement(tag_pr)
        el.insert(0, pr)
    st = pr.find(qn(tag_style))
    if st is None:
        st = OxmlElement(tag_style)
        pr.insert(0, st)
    st.set(qn("w:val"), val)


def write_footnotes(doc, lay: DocLayout, ctx, write_para) -> None:
    """footnotes.xml from `lay.footnotes`, the references already written.

    Each note's paragraphs go through the body's own paragraph writer -- into
    the document body, then moved into their w:footnote -- so they carry the
    same exact leading, indents and runs as everywhere else. External links
    are written as plain text: a footnote part has its own relationships, and
    a body-part r:id inside it would point nowhere.
    """
    from collections import Counter
    sizes = Counter()
    for f in lay.footnotes:
        for p in f.paras:
            for r in p.runs:
                if r.text.strip() and not r.footnote_mark:
                    sizes[round(r.size * 2) / 2] += len(r.text)
    _ensure_footnote_styles(doc, sizes.most_common(1)[0][0] if sizes else 10.0)
    root = new_footnotes_root()
    content_w = lay.content_w
    for f in lay.footnotes:
        wid, custom = ctx.note_ids[f.fid]
        fn = OxmlElement("w:footnote")
        fn.set(qn("w:id"), str(wid))
        nctx = dataclasses.replace(ctx, note_ids={}, list_defs={},
                                   note_mark_custom=custom)
        for p in f.paras:
            q = dataclasses.replace(
                p, runs=[dataclasses.replace(r, link=None) for r in p.runs])
            par = write_para(doc, q, content_w, ctx=nctx)
            _set_style(par._p, "w:pPr", "w:pStyle", "FootnoteText")
            fn.append(par._p)        # moves the paragraph out of the body
        root.append(fn)
    attach_footnotes_part(doc, root)
    footnote_settings(doc, lay.footnote_restart, lay.footnote_start)


def footnote_settings(doc, restart: str, start: int) -> None:
    """Document-level w:footnotePr: the separators Word looks up by id, and
    the numbering when it is not the default (continuous from 1).

    Also stamped on every section, because LibreOffice reads numbering from
    the section and every section here starts a page of the same document.
    """
    st = doc.settings.element
    fp = OxmlElement("w:footnotePr")

    def numbering(into):
        if start != 1:
            ns = OxmlElement("w:numStart")
            ns.set(qn("w:val"), str(start))
            into.append(ns)
        if restart != "continuous":
            nr = OxmlElement("w:numRestart")
            nr.set(qn("w:val"), restart)
            into.append(nr)
    numbering(fp)
    for wid in (-1, 0):
        f = OxmlElement("w:footnote")
        f.set(qn("w:id"), str(wid))
        fp.append(f)
    # schema: footnotePr precedes compat (and everything after it)
    anchor = None
    for tag in ("w:endnotePr", "w:compat", "w:docVars", "w:rsids"):
        anchor = st.find(qn(tag))
        if anchor is not None:
            break
    if anchor is not None:
        anchor.addprevious(fp)
    else:
        st.append(fp)
    if start == 1 and restart == "continuous":
        return
    body = doc.element.body
    for sp in body.iter(qn("w:sectPr")):
        sfp = OxmlElement("w:footnotePr")
        numbering(sfp)
        # sectPr: header/footerReference*, footnotePr, endnotePr, type, ...
        refs = [c for c in sp if c.tag in (qn("w:headerReference"),
                                           qn("w:footerReference"))]
        if refs:
            refs[-1].addnext(sfp)
        else:
            sp.insert(0, sfp)
