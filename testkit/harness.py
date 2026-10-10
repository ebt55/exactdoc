"""Independent fidelity harness for PDF->DOCX converters.

Deliberately shares no code with the converter under test.

**This module requires the optional `mupdf` extra, and that is a design
constraint rather than an oversight.** PDFium is the shipping parser, so reading
the source PDF back through PDFium to score PDFium's own output would make the
measurement circular: a parser that mis-groups a page would mis-group it
identically on both sides and score itself perfect. The instrument has to be a
different implementation from the thing under test, which is exactly what
PyMuPDF now is.

The consequence, stated so it is not mistaken for a licence problem: the
measurement toolkit is AGPL-governed and the shipped converter is not. Nothing
under `exactdoc/` imports this file. Test modules that reach it -- currently
test_expansion_policy, test_gdocs_qualification, test_parity_evidence_labels and
test_parity_expansion -- skip without the extra rather than fail; see
`tests/mupdf_extra.py`.

Metrics
-------
page_match        pages(src) == pages(rendered)
live_text_cov     3-gram coverage of ALL source text by DOCX *live text*
                  (no figure-region exclusion -- rasterized text counts as LOST)
raster_frac       fraction of source text chars that are NOT live in the docx
word_recall       fraction of source words matched in the render-back PDF
dy_p50/p90        vertical drift of matched words (pt), at the baseline
dx_p50/p90        horizontal drift, at the word box's left edge
within2/within5   fraction of matched words placed within 2pt / 5pt (euclid)
ssim              8x8 window SSIM at 110 dpi
ink_iou           intersection-over-union of binarized ink pixels

How the text is read -- leaders, symbol fonts, operators (WP29) and where a
word sits (its baseline, amendment 3) -- is the same on both sides; see
`page_words`, `live_text_cov` and docs/beta-bar.md.
"""
import _paths  # noqa: F401  (sets sys.path, finds soffice/chrome)
import os, re, io, sys, json, shutil, subprocess, tempfile, difflib
import bisect
from collections import Counter

import fitz
import numpy as np

from _paths import SOFFICE


# ---------------------------------------------------------------- render-back
# One shared LO profile for the whole session: soffice refuses rapid restarts
# with differing profiles and silently exits 0 without writing output.
_PROFILE = os.path.join(tempfile.gettempdir(), "exactdoc_loprof")


def _soffice(args, timeout=900):
    cmd = [SOFFICE, "--headless", "--norestore", "--invisible", "--nolockcheck",
           "-env:UserInstallation=file:///" + _PROFILE.replace("\\", "/")] + args
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _pdf_for(docx_path, out_dir):
    return os.path.join(out_dir,
                        os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")


def _is_stale(docx_path, pdf_path):
    """A render is only reusable if it is NEWER than the DOCX it came from.

    Reusing an existing PDF unconditionally silently reports the previous
    run's results after a code change -- which looked exactly like 'the fix
    changed nothing'. Never cache on existence alone.
    """
    if not os.path.exists(pdf_path):
        return True
    return os.path.getmtime(pdf_path) <= os.path.getmtime(docx_path)


def batch_docx_to_pdf(docx_paths, out_dir):
    """Convert many DOCX in one soffice call. Returns {docx: pdf|None}."""
    os.makedirs(out_dir, exist_ok=True)
    todo = list(docx_paths)
    for d in todo:                       # drop stale renders up front
        p = _pdf_for(d, out_dir)
        if os.path.exists(p) and _is_stale(d, p):
            os.remove(p)
    for _ in range(3):
        pending = [d for d in todo if _is_stale(d, _pdf_for(d, out_dir))]
        if not pending:
            break
        _soffice(["--convert-to", "pdf", "--outdir", out_dir] + pending)
    return {d: (None if _is_stale(d, _pdf_for(d, out_dir)) else _pdf_for(d, out_dir))
            for d in todo}


def docx_to_pdf(docx_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    out = _pdf_for(docx_path, out_dir)
    if not _is_stale(docx_path, out):
        return out
    if os.path.exists(out):
        os.remove(out)
    for _ in range(3):
        _soffice(["--convert-to", "pdf", "--outdir", out_dir, docx_path])
        if os.path.exists(out):
            return out
    raise RuntimeError("LibreOffice produced no PDF for %s" % docx_path)


# ------------------------------------------------------------------ text side
def _ordinal(n, fmt):
    """`n` the way an OOXML number format prints it (the formats a reader
    must know to read a list label; anything else prints as decimal)."""
    if fmt in ("lowerLetter", "upperLetter"):
        s = chr(ord("a") + (n - 1) % 26) * ((n - 1) // 26 + 1) if n > 0 else ""
        return s.upper() if fmt == "upperLetter" else s
    if fmt in ("lowerRoman", "upperRoman"):
        out, v = "", n
        for val, sym in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
                         (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
                         (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
            while v >= val:
                out, v = out + sym, v - val
        return out.upper() if fmt == "upperRoman" else out
    return str(n)


def _numbering_levels(z, W):
    """{numId: {ilvl: (start, numFmt, lvlText)}} from word/numbering.xml."""
    from lxml import etree
    try:
        root = etree.fromstring(z.read("word/numbering.xml"))
    except KeyError:
        return {}
    absn = {}
    for an in root.iter(W + "abstractNum"):
        lv = {}
        for l in an.iter(W + "lvl"):
            def val(tag, default):
                e = l.find(W + tag)
                return e.get(W + "val") if e is not None else default
            lv[int(l.get(W + "ilvl", "0"))] = (
                int(val("start", "1")), val("numFmt", "decimal"), val("lvlText", ""))
        absn[an.get(W + "abstractNumId")] = lv
    out = {}
    for num in root.iter(W + "num"):
        ref = num.find(W + "abstractNumId")
        if ref is not None:
            out[num.get(W + "numId")] = absn.get(ref.get(W + "val"), {})
    return out


def docx_live_text(docx_path, normalise=False):
    """All *live* text in a docx: paragraphs, tables (recursive), headers/footers.

    Reads the XML directly so nothing is missed and no library semantics are
    assumed.

    `normalise=True` reads it the way `page_words` reads a PDF (WP29): a
    symbol-font private-use character is the character its run's font
    encodes, and a leader run (three or more dots) is not text. Paragraphs are
    then kept apart by a newline, so a run cannot be made of the dots that end
    one paragraph and begin the next.

    Live text includes what a reader's renderer GENERATES from the document's
    own structures: a list item's label (w:numPr over numbering.xml) and a
    footnote's number (w:footnoteReference / w:footnoteRef). Neither is a w:t,
    and neither is raster -- the label of item 3 is the text "3." on every
    reader's screen -- so a metric whose complement is `raster_frac` must
    count them. Counted with the renderer's own rules, implemented here and not
    imported: a level counts up from its start, an item restarts every deeper
    level, and footnotes number in document order (custom marks carry their
    mark as text already, and do not count).
    """
    import zipfile
    from lxml import etree
    NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    W = "{%s}" % NS["w"]
    parts, imgs = [], []
    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        for n in names:
            if n.startswith("word/media/"):
                imgs.append((n, z.getinfo(n).file_size))
        levels = _numbering_levels(z, W)
        counters = {}
        note_no = {}
        start = 1
        try:
            st = etree.fromstring(z.read("word/settings.xml"))
            ns_el = st.find(".//" + W + "footnotePr/" + W + "numStart")
            if ns_el is not None:
                start = int(ns_el.get(W + "val", "1"))
        except (KeyError, ValueError):
            pass
        # footnote numbers follow the references' order in the body
        if "word/footnotes.xml" in names:
            body = etree.fromstring(z.read("word/document.xml"))
            for ref in body.iter(W + "footnoteReference"):
                if ref.get(W + "customMarkFollows") not in ("1", "true", "on"):
                    note_no.setdefault(ref.get(W + "id"), start + len(note_no))
        cur_note = None
        for n in names:
            if not (n == "word/document.xml" or
                    re.match(r"word/(header|footer|footnotes|endnotes)\d*\.xml$", n)):
                continue
            root = etree.fromstring(z.read(n))
            for el in root.iter(W + "p", W + "t", W + "footnoteReference",
                                W + "footnoteRef", W + "footnote"):
                tag = el.tag[len(W):]
                if tag == "t":
                    t = el.text or ""
                    if normalise and _has_pua(t):
                        t = _read_run_pua(t, el.getparent(), W)
                    parts.append(t)
                elif tag == "p":
                    if normalise:
                        parts.append("\n")
                    np_ = el.find(W + "pPr/" + W + "numPr")
                    if np_ is None:
                        continue
                    nid = np_.find(W + "numId")
                    il = np_.find(W + "ilvl")
                    nid = nid.get(W + "val") if nid is not None else None
                    il = int(il.get(W + "val")) if il is not None else 0
                    lv = levels.get(nid)
                    if not lv or il not in lv:
                        continue
                    cnt = counters.setdefault(nid, {})
                    cnt[il] = cnt[il] + 1 if il in cnt else lv[il][0]
                    for deeper in [k for k in cnt if k > il]:
                        del cnt[deeper]
                    label = lv[il][2]
                    for k in range(il + 1):
                        if k in lv:
                            label = label.replace(
                                "%%%d" % (k + 1),
                                _ordinal(cnt.get(k, lv[k][0]), lv[k][1]))
                    parts.append(label)
                elif tag == "footnoteReference":
                    num = note_no.get(el.get(W + "id"))
                    if num is not None:
                        parts.append(str(num))
                elif tag == "footnote":
                    cur_note = el.get(W + "id")
                elif tag == "footnoteRef":
                    num = note_no.get(cur_note)
                    if num is not None:
                        parts.append(str(num))
    text = "".join(parts)
    return (_strip_leader_runs(text) if normalise else text), imgs


def _read_run_pua(text, run, W):
    """`text` of a w:t with its symbol-font PUA read through the published
    encoding of its run's font (w:rFonts), as `_read_pua` reads a PDF span."""
    fonts = run.find(W + "rPr/" + W + "rFonts") if run is not None else None
    table = None
    if fonts is not None:
        for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
            table = _pua_table(fonts.get(W + attr))
            if table:
                break
    if not table:
        return text
    return "".join(table.get(ord(c) - 0xF000, c) if _PUA_LO <= ord(c) <= _PUA_HI else c
                   for c in text)


def pdf_text(pdf_path, normalise=False):
    """All of a PDF's text; `normalise=True` reads it as `recall_text` does."""
    doc = fitz.open(pdf_path)
    out = []
    for p in doc:
        out.append(recall_text(p, normalise) if normalise else p.get_text("text"))
    doc.close()
    return "".join(out)


def live_text_cov(src_pdf, docx_path, normalise=True):
    """3-gram coverage of the source PDF's text by the DOCX's live text.

    Both sides are read as `page_words` and `recall_text` read a PDF
    (normalise=True; WP29's reading, applied to live text from 2026-10-10):
    symbol-font PUA as the characters it encodes and leader runs dropped.
    y10_nist_fips180's source spells its equations in Symbol PUA and its DOCX
    in "=" and "+", so its live text read 0.787 at the checkpoint (ckpt-prod);
    read this way, 0.932. A contents page's dots
    are a tab leader in the DOCX, not text. `normalise=False` is the reading
    before.
    """
    live, _imgs = docx_live_text(docx_path, normalise=normalise)
    return round(gram_cov(pdf_text(src_pdf, normalise=normalise), live), 4)


def norm(t):
    return re.sub(r"\s+", "", t or "")


def gram_cov(src, out, k=3):
    s, o = norm(src), norm(out)
    if len(s) < k:
        return 1.0
    g1 = Counter(s[i:i + k] for i in range(len(s) - k + 1))
    g2 = Counter(o[i:i + k] for i in range(len(o) - k + 1))
    inter = sum(min(c, g2[g]) for g, c in g1.items())
    return inter / max(1, sum(g1.values()))


# ------------------------------------------------------------- geometry side
# Chinese, Japanese and Korean are written without spaces, so a whitespace
# tokeniser returns one "word" per rendered LINE -- up to 32 characters on the
# corpus i18n page. Re-wrap that line one character earlier and the token no
# longer matches anything, although every character survived: c4_i18n scored
# doc_recall 0.8298 on Linux and passed on Windows purely because the two
# renderers broke the line in different places. Measured before the fix: 16 of
# 94 source tokens unmatched, all 16 Hangul/CJK/Kana, zero Latin, zero Arabic,
# zero Hebrew (Arabic and Hebrew DO use spaces and never had the problem).
#
# So runs in these scripts are tokenised per character, with the run's box
# divided evenly across them. It is not a leniency: it counts the same content
# the writer emitted, in the unit that script actually has.
_CONTINUA = ((0x3040, 0x30FF),    # Hiragana + Katakana
             (0x3400, 0x4DBF),    # CJK ext A
             (0x4E00, 0x9FFF),    # CJK unified
             (0xAC00, 0xD7AF),    # Hangul syllables
             (0xF900, 0xFAFF))    # CJK compatibility


def _is_continua(ch):
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in _CONTINUA)


def _split_continua(text, x0, y0, x1, y1):
    """One token per character when the run has no word boundaries of its own."""
    if not any(_is_continua(c) for c in text):
        return [(text, x0, y0, x1, y1)]
    step = (x1 - x0) / max(1, len(text))
    return [(c, x0 + i * step, y0, x0 + (i + 1) * step, y1)
            for i, c in enumerate(text) if not c.isspace()]


# Google Docs' PDF exporter writes U+200B ZERO WIDTH SPACE where a tab (typed,
# or a list label's) or a soft line break ends a text segment: "800-63B\u200b"
# before the header's tab, "Secrets....\u200b" before a contents page number,
# the end of every soft-broken code line. 16,526 of the 990,342 words in the
# 2c1c68f live sweep's exports carried one, and each then matched no source
# word, booking a correctly placed word as missing. It is invisible and not
# text; no gated source carries one.
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\ufeff"), None)


# ------------------------------------------------- reading normalisation (WP29)
# Three things a PDF's text layer says that are not the document's words, each
# of which booked correctly converted text as missing. All three are applied
# SYMMETRICALLY -- to the source and to the render alike, by the same function
# -- so they can only stop counting a difference that is not one; they cannot
# hide text that was lost (the text either side still has is compared as
# before). Ratified by the owner 2026-10-06 (docs/beta-bar.md, amendments).
#
# 1. Leaders. A tab leader is drawn as however many dots fill the gap, and the
#    gap depends on the renderer's font metrics: y26_bash_reference's 214
#    pages lost doc_recall 0.9924 -> 0.9712 at the checkpoint, and 2,243 of
#    the 3,027 unmatched source tokens were single "." leader dots (LibreOffice
#    drew fewer dots per contents line, every word kept). A run of three or
#    more leader characters on one line -- as separate tokens, as one token, or
#    glued to the end or start of a word ("Secrets....", "....12") -- carries
#    no word, so it is not counted. One or two dots are text (a full stop, a
#    path's ".."). An ellipsis is three dots too and goes the same way, on both
#    sides. Only dot-like leaders: hyphen and underscore "leaders" are also
#    rules and fill-in blanks, which are content.
_LEADER_WEIGHT = {".": 1, "\u00b7": 1, "\u2024": 1, "\u2025": 2, "\u2026": 3}
_LEADER_MIN = 3
_LEADER_EDGE = re.compile(r"^[.\u00b7\u2024\u2025\u2026]+|[.\u00b7\u2024\u2025\u2026]+$")


def _leader_weight(text):
    """Leader characters in `text` if it is made of nothing else, else 0."""
    if not text or any(c not in _LEADER_WEIGHT for c in text):
        return 0
    return sum(_LEADER_WEIGHT[c] for c in text)


def _strip_glued_leader(text):
    """'Secrets....' -> 'Secrets'; a dot or two at a word's edge is kept."""
    def cut(m):
        return "" if _leader_weight(m.group(0)) >= _LEADER_MIN else m.group(0)
    return _LEADER_EDGE.sub(cut, text)


def _leader_runs(words):
    """Indices of `words` (fitz word tuples) that belong to a leader run: a
    maximal sequence of leader-only tokens adjacent on one fitz line, holding
    at least `_LEADER_MIN` leader characters in all."""
    lines = {}
    for i, w in enumerate(words):
        lines.setdefault((w[5], w[6]), []).append(i)
    drop = set()
    for idx in lines.values():
        idx.sort(key=lambda i: words[i][0])
        run, weight = [], 0
        for i in idx + [None]:
            wt = _leader_weight(words[i][4].translate(_INVISIBLE)) if i is not None else 0
            if wt:
                run.append(i)
                weight += wt
                continue
            if weight >= _LEADER_MIN:
                drop.update(run)
            run, weight = [], 0
    return drop


# 2. Symbol-font private-use code points. A symbolic font with no /ToUnicode
#    reaches every text extractor as U+F000 + its character code, so the
#    source's maths reads as PUA while a render that carries real characters
#    reads as Unicode: y10_nist_fips180 is 36/36 pages and capped at word
#    recall 0.78 because its 385 Symbol and 81 MT Extra glyphs ("=" 93, "-" 66,
#    "+" 63, "<=" 53, "xor" 39) never matched the "=", "-", "+" the render
#    shows. For the faces with a PUBLISHED encoding the code is the character,
#    so the scorer reads it, keyed by the span's font, never by the document.
#    The table is written here from the published sources (Adobe's
#    VENDORS/ADOBE/symbol.txt and zdingbat.txt; for MT Extra the two codes its
#    glyphs show), not imported from the converter, which this module must not
#    share code with. A code outside the table is left as it is.
_SYMBOL_ENC = dict(zip(range(0x20, 0x7F), (
    " !\u2200#\u2203%&\u220b()\u2217+,\u2212./0123456789:;<=>?"
    "\u2245\u0391\u0392\u03a7\u0394\u0395\u03a6\u0393\u0397\u0399\u03d1\u039a"
    "\u039b\u039c\u039d\u039f\u03a0\u0398\u03a1\u03a3\u03a4\u03a5\u03c2\u03a9"
    "\u039e\u03a8\u0396[\u2234]\u22a5_\uf8e5\u03b1\u03b2\u03c7\u03b4\u03b5\u03c6"
    "\u03b3\u03b7\u03b9\u03d5\u03ba\u03bb\u03bc\u03bd\u03bf\u03c0\u03b8\u03c1"
    "\u03c3\u03c4\u03c5\u03d6\u03c9\u03be\u03c8\u03b6{|}\u223c")))
_SYMBOL_ENC.update(zip(range(0xA0, 0x100), (
    "\u20ac\u03d2\u2032\u2264\u2044\u221e\u0192\u2663\u2666\u2665\u2660\u2194"
    "\u2190\u2191\u2192\u2193\u00b0\u00b1\u2033\u2265\u00d7\u221d\u2202\u2022"
    "\u00f7\u2260\u2261\u2248\u2026\u23d0\u23af\u21b5\u2135\u2111\u211c\u2118"
    "\u2297\u2295\u2205\u2229\u222a\u2283\u2287\u2284\u2282\u2286\u2208\u2209"
    "\u2220\u2207\u00ae\u00a9\u2122\u220f\u221a\u22c5\u00ac\u2227\u2228\u21d4"
    "\u21d0\u21d1\u21d2\u21d3\u25ca\u2329\u00ae\u00a9\u2122\u2211"
    # 0xE6-0xEF and 0xF1-0xFE are the pieces of tall brackets, braces and
    # integrals; a piece reads as the character it builds.
    "((([[[{{{|\uf8ff\u232a\u222b\u222b\u222b\u222b)))]]]}}}\uf8ff")))
# Codes the published table itself leaves in the private-use area (the radical
# extender, Apple's logo at 0xF0, the undefined 0xFF) have no reading.
_SYMBOL_ENC = {k: v for k, v in _SYMBOL_ENC.items() if not 0xE000 <= ord(v) <= 0xF8FF}
_ZAPF_ENC = {0x33: "\u2713", 0x34: "\u2714", 0x35: "\u2715", 0x36: "\u2716",
             0x37: "\u2717", 0x38: "\u2718", 0x48: "\u2605", 0x6C: "\u25cf",
             0x6E: "\u25a0", 0x6F: "\u274f", 0x70: "\u2750", 0x71: "\u2751",
             0x72: "\u2752", 0x73: "\u25b2", 0x74: "\u25bc", 0x75: "\u25c6",
             0x76: "\u2756"}
_MTEXTRA_ENC = {0x6C: "\u2113", 0x4B: "\u2026"}
_PUA_LO, _PUA_HI = 0xF020, 0xF0FF


def _pua_table(font):
    """The published encoding of a symbol face, by its whole family name."""
    key = re.sub(r"^[A-Z]{6}\+", "", font or "")           # subset prefix
    key = re.sub(r"[^a-z0-9]", "", key.lower())
    for suffix in ("regular", "mt", "std", "itc"):
        if key.endswith(suffix) and len(key) > len(suffix):
            key = key[:-len(suffix)]
    if key in ("symbol", "symbolneu", "standardsymbolsps", "standardsyml"):
        return _SYMBOL_ENC
    if key in ("zapfdingbats", "dingbats"):
        return _ZAPF_ENC
    if key == "mtextra":
        return _MTEXTRA_ENC
    return None


def _has_pua(text):
    return any(_PUA_LO <= ord(c) <= _PUA_HI for c in text)


def _pua_spans(page):
    """[(Rect, table, text)] of the page's spans that carry symbol-font PUA."""
    out = []
    for b in page.get_text("dict").get("blocks", ()):
        for ln in b.get("lines", ()):
            for s in ln.get("spans", ()):
                if _has_pua(s.get("text", "")):
                    table = _pua_table(s.get("font"))
                    if table:
                        out.append((fitz.Rect(s["bbox"]), table, s["text"]))
    return out


def _read_pua(text, bbox, spans):
    """`text` with each symbol-font PUA character read through the encoding of
    the span it came from (the span holding it that overlaps `bbox`)."""
    if not spans or not _has_pua(text):
        return text
    r = fitz.Rect(bbox)
    out = []
    for c in text:
        o = ord(c)
        if _PUA_LO <= o <= _PUA_HI:
            for rect, table, stext in spans:
                if c in stext and rect.intersects(r) and (o - 0xF000) in table:
                    c = table[o - 0xF000]
                    break
        out.append(c)
    return "".join(out)


# 3. Brackets and operators. Where a token ends is a gap in the drawing, and
#    maths is set with gaps around operators that a re-flowed render does not
#    keep: FIPS 180's source reads "H", "0", "(", "i", "-", "1", ")" where the
#    render reads "H0(", "i-1)" -- the same characters, so not a single token
#    matched. Brackets and mathematical operators are therefore their own
#    tokens on both sides. Not the ASCII hyphen (it is inside words), not the
#    comma or the slash (they attach to words in prose and URLs), not "*"
#    (footnote marks). The pieces share the token's box in proportion to their
#    characters, as the CJK split above does. Exact boxes from the page's
#    character layer were tried and moved nothing (y10 within-2pt 0.4073
#    proportional, 0.4070 exact) at many times the cost, so they are not used.
#    Within-2pt does fall on y10 (0.4814 -> 0.4073): it is a share of the
#    MATCHED words, and the newly matched operators sit less exactly than the
#    prose that matched before -- a truer number, not a worse conversion.
_OPERATORS = ("()[]{}\u2329\u232a\u27e8\u27e9=+<>\u2212\u00b1\u00d7\u00f7"
              "\u2264\u2265\u2260\u2248\u2261\u2245\u223c\u2295\u2297\u2227"
              "\u2228\u00ac\u2211\u220f\u222b\u221a\u2202\u2207\u2208\u2209"
              "\u2282\u2283\u2286\u2287\u222a\u2229\u2192\u2190\u2194\u21d2"
              "\u21d0\u21d4\u2217\u22c5\u2200\u2203")
_OP_SPLIT = re.compile("([%s])" % re.escape(_OPERATORS))


def _split_operators(text, x0, y0, x1, y1):
    """`text` cut at brackets and operators, the pieces sharing its box."""
    parts = [p for p in _OP_SPLIT.split(text) if p]
    if len(parts) <= 1:
        return [(text, x0, y0, x1, y1)]
    step = (x1 - x0) / max(1, len(text))
    out, at = [], 0
    for p in parts:
        out.append((p, x0 + at * step, y0, x0 + (at + len(p)) * step, y1))
        at += len(p)
    return out


# ------------------------------------------- vertical anchor (amendment 3)
# Where a word sits vertically is its BASELINE, read from the glyph origins,
# not the top of its box. The box top is not a position on the page: it is
# derived as baseline minus the font's ascent, and the ascent is whatever the
# reader's copy of the font declares. Measured by PyMuPDF on the corpus (glyph
# origin minus box top, per size): r1_reportlab_report's unembedded Helvetica
# 1.075 em and Times-Roman 1.053 em; the same words rendered by LibreOffice
# (Liberation Sans 0.905, Liberation Serif 0.891), exported by Google Docs and
# by Word (Arial 0.905, Times New Roman 0.891). So every word of a base-14
# source read 1.6-1.7pt "low" at 10pt before anything moved -- most of
# within-2pt's 2pt budget -- while c1_whitepaper, which embeds Liberation,
# read 0.89 against 0.90 and showed no such bias. Every consumer of a page
# (the writer, the renderer, the reader's eye) lines text up on the baseline,
# so that is the anchor on both sides. Ratified by the owner 2026-10-10
# (docs/beta-bar.md, amendment 3).
#
# A word's baseline is that of its largest characters (the first of them), so
# a superscript or subscript glued to a word ("H(i)." in FIPS 180, "x2") does
# not move it; on a line that is not horizontal (rotated text) there is no
# vertical baseline and the word keeps its box top, as it does in the rare
# case that no character of the page's text layer can be tied to it.
_TOL = 0.01                                  # pt; boxes are unions of the same char boxes


def _line_chars(raw):
    """{block number: [(line bbox, horizontal, [x centre], [(-size, origin y)])]}
    from a rawdict, the characters of each line sorted left to right."""
    out = {}
    for b in raw.get("blocks", ()):
        if b.get("type", 0) != 0 or "number" not in b:
            continue
        lines = []
        for ln in b.get("lines", ()):
            d = ln.get("dir", (1.0, 0.0))
            chars = sorted(((c["bbox"][0] + c["bbox"][2]) / 2, -s.get("size", 0.0),
                            c["origin"][1])
                           for s in ln.get("spans", ()) for c in s.get("chars", ())
                           if "origin" in c and not c.get("c", " ").isspace())
            lines.append((ln.get("bbox"), abs(d[1]) < 1e-3,
                          [c[0] for c in chars], [c[1:] for c in chars]))
        out[b["number"]] = lines
    return out


def _holds(box, w):
    return (box is not None and box[0] - _TOL <= w[0] and box[1] - _TOL <= w[1]
            and w[2] <= box[2] + _TOL and w[3] <= box[3] + _TOL)


def _baseline(w, by_block):
    """The baseline of fitz word `w` (x0,y0,x1,y1,text,block,line,wordno), or
    its box top when it has none (see above)."""
    lines = by_block.get(w[5], ())
    line = lines[w[6]] if w[6] < len(lines) and _holds(lines[w[6]][0], w) else \
        next((ln for ln in lines if _holds(ln[0], w)), None)
    if line is None or not line[1]:
        return w[1]
    xs, sized = line[2], line[3]
    chars = sized[bisect.bisect_left(xs, w[0] - _TOL):bisect.bisect_right(xs, w[2] + _TOL)]
    return min(chars, key=lambda c: c[0])[1] if chars else w[1]


def _words(page, baseline):
    """fitz word tuples, each with its vertical anchor appended (w[8])."""
    if not baseline:
        return [tuple(w) + (w[1],) for w in page.get_text("words")]
    tp = page.get_textpage(flags=fitz.TEXTFLAGS_WORDS)   # what "words" builds
    ws = page.get_text("words", textpage=tp)
    by_block = _line_chars(page.get_text("rawdict", textpage=tp))
    return [tuple(w) + (_baseline(w, by_block),) for w in ws]


def page_words(pdf_path, normalise=True, baseline=True):
    """Per page, [(text, x0, y0, x1, y1, y)] in reading order: the word's box
    and `y`, where it sits vertically -- its baseline (amendment 3).

    `baseline=False` anchors `y` at the box top `y0`, the reading before
    2026-10-10; `normalise=False` is the reading before WP29 (2026-10-06): no
    leader, symbol-font or operator normalisation. They exist so a re-score can
    report every reading of the same render; nothing gates on them.
    """
    doc = fitz.open(pdf_path)
    pages = []
    for p in doc:
        ws = _words(p, baseline)           # x0,y0,x1,y1,word,block,line,wordno,y
        ws.sort(key=lambda w: (round(w[1], 1), w[0]))
        spans, drop = None, ()
        if normalise:
            if any(_has_pua(w[4]) for w in ws):
                spans = _pua_spans(p)
            if spans:
                ws = [w[:4] + (_read_pua(w[4], w[:4], spans),) + tuple(w[5:])
                      for w in ws]
            drop = _leader_runs(ws)
        out = []
        for i, w in enumerate(ws):
            if i in drop:
                continue
            text = w[4].translate(_INVISIBLE)
            if normalise:
                text = _strip_glued_leader(text)
            if not text:
                continue
            pieces = (_split_operators(text, w[0], w[1], w[2], w[3]) if normalise
                      else [(text, w[0], w[1], w[2], w[3])])
            # every piece of a word sits on the word's baseline
            out.extend(t + (w[8],) for piece in pieces for t in _split_continua(*piece))
        pages.append(out)
    doc.close()
    return pages


def box_top(pages):
    """`page_words` output re-anchored at the box top: the reading before
    amendment 3, from the same extraction (the words are the same words)."""
    return [[w[:5] + (w[2],) for w in p] for p in pages]


_LEADER_TEXT = re.compile(
    r"[.\u00b7\u2024\u2025\u2026](?:[ \t\u00a0\u200b]*[.\u00b7\u2024\u2025\u2026])*")


def recall_text(page, normalise=True):
    """A page's text as character recall counts it: `page.get_text("text")`,
    read through the same symbol-font table and with the same leader runs
    removed as `page_words` (the operator split has nothing to do here --
    characters do not depend on where a token ends)."""
    text = page.get_text("text")
    if not normalise:
        return text
    if _has_pua(text):
        tables = {}
        for _rect, table, stext in _pua_spans(page):
            for c in stext:
                o = ord(c)
                if _PUA_LO <= o <= _PUA_HI and (o - 0xF000) in table:
                    tables.setdefault(c, Counter())[table[o - 0xF000]] += 1
        if tables:
            text = text.translate({ord(c): n.most_common(1)[0][0]
                                   for c, n in tables.items()})
    return _strip_leader_runs(text)


def _strip_leader_runs(text):
    """`text` without its runs of three or more leader characters (spaces
    between them allowed, line breaks not)."""
    return _LEADER_TEXT.sub(
        lambda m: "" if sum(_LEADER_WEIGHT.get(c, 0) for c in m.group(0)) >= _LEADER_MIN
        else m.group(0), text)


def match_words(src_pages, out_pages):
    """Positional matching, page by page.

    Reading-order alignment breaks on multi-column pages (sorting by y
    interleaves the columns, and a small y shift flips the interleave). So
    match each source word to the *nearest* output word carrying identical
    text, greedily by ascending distance, without replacement.

    Vertical position is the word's anchor `y` (its baseline; `page_words`),
    or its box top for a bare 5-tuple. Pairing is by text, so the anchor
    changes which equal words pair up only where several are in reach, and
    never how many match.
    """
    drifts, matched, total = [], 0, 0
    for i, sp in enumerate(src_pages):
        total += len(sp)
        if i >= len(out_pages):
            continue
        by_text = {}
        for j, o in enumerate(out_pages[i]):
            by_text.setdefault(o[0], []).append(j)
        cands = []
        for si, s in enumerate(sp):
            for oj in by_text.get(s[0], ()):
                o = out_pages[i][oj]
                d = abs(_y(o) - _y(s)) * 3 + abs(o[1] - s[1])   # weight dy
                cands.append((d, si, oj))
        cands.sort()
        used_s, used_o = set(), set()
        for d, si, oj in cands:
            if si in used_s or oj in used_o:
                continue
            used_s.add(si); used_o.add(oj)
            s, o = sp[si], out_pages[i][oj]
            matched += 1
            drifts.append((o[1] - s[1], _y(o) - _y(s), i + 1, s[0]))
    return drifts, matched, total


def _y(w):
    return w[5] if len(w) > 5 else w[2]


def doc_word_recall(src_pages, out_pages):
    """Page-agnostic content recall: is the text present anywhere in the doc?"""
    a = Counter(w[0] for p in src_pages for w in p)
    b = Counter(w[0] for p in out_pages for w in p)
    inter = sum(min(c, b[t]) for t, c in a.items())
    return inter / max(1, sum(a.values()))


# --------------------------------------------------------------- pixel side
def page_array(doc, i, dpi=110):
    """One page of an open document as an (h, w, 3) float64 array.

    At 110 dpi a US-Letter page is 1210x935x3 float64 = 27.2 MB, so *which*
    pages are alive at once is a scaling property of the caller, not a detail.
    """
    pix = doc[i].get_pixmap(dpi=dpi, alpha=False)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width,
                                                           pix.n)
    return a[:, :, :3].astype(np.float64)


def page_arrays(pdf_path, dpi=110):
    """Every page at once. Costs 27.2 MB per page -- see `page_array`.

    `evaluate` deliberately does NOT use this: it compares one page at a time.
    Kept because rasterising a whole short document in one call is a reasonable
    thing for an ad-hoc probe to want.
    """
    doc = fitz.open(pdf_path)
    try:
        return [page_array(doc, i, dpi) for i in range(doc.page_count)]
    finally:
        doc.close()


def pad_to(a, h, w):
    o = np.full((h, w, a.shape[2]), 255.0)
    o[:min(h, a.shape[0]), :min(w, a.shape[1]), :] = a[:h, :w, :]
    return o


def ssim(a, b):
    ga, gb = a.mean(2), b.mean(2)
    k = 8
    H, W = (ga.shape[0] // k) * k, (ga.shape[1] // k) * k
    ga = ga[:H, :W].reshape(H // k, k, W // k, k).transpose(0, 2, 1, 3).reshape(-1, k * k)
    gb = gb[:H, :W].reshape(H // k, k, W // k, k).transpose(0, 2, 1, 3).reshape(-1, k * k)
    ma, mb = ga.mean(1), gb.mean(1)
    va, vb = ga.var(1), gb.var(1)
    cov = ((ga - ma[:, None]) * (gb - mb[:, None])).mean(1)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    s = ((2 * ma * mb + C1) * (2 * cov + C2)) / ((ma ** 2 + mb ** 2 + C1) * (va + vb + C2))
    return float(s.mean())


def ink_iou(a, b, thr=200):
    ga, gb = a.mean(2) < thr, b.mean(2) < thr
    inter = np.logical_and(ga, gb).sum()
    union = np.logical_or(ga, gb).sum()
    return float(inter / max(1, union))


# ------------------------------------------------------------------- runner
# The metrics that depend on how the text is read -- and so on page_words'
# normalisation -- as opposed to page counts, pixels and the DOCX's live text.
WORD_METRICS = ("src_words", "word_recall", "doc_recall", "dx_p50", "dx_p90",
                "dy_p50", "dy_p90", "within2pt", "within5pt", "page_dy_p90")


def word_metrics(src_pdf, rendered_pdf, normalise=True, baseline=True):
    """The word-level half of `evaluate`: recall on the right page and
    anywhere, and the drift of the matched words. Separate so a saved render
    can be re-scored without converting or rendering anything again.
    `normalise` and `baseline` select the reading (see `page_words`)."""
    return drift_metrics(page_words(src_pdf, normalise=normalise, baseline=baseline),
                         page_words(rendered_pdf, normalise=normalise, baseline=baseline))


def drift_metrics(sw, ow):
    """`word_metrics` of two `page_words` readings already made."""
    res = {}
    drifts, matched, total = match_words(sw, ow)
    res["src_words"] = total
    res["word_recall"] = round(matched / max(1, total), 4)      # right page
    res["doc_recall"] = round(doc_word_recall(sw, ow), 4)       # anywhere
    if drifts:
        dx = np.array([d[0] for d in drifts])
        dy = np.array([d[1] for d in drifts])
        eu = np.hypot(dx, dy)
        res["dx_p50"] = round(float(np.percentile(np.abs(dx), 50)), 2)
        res["dx_p90"] = round(float(np.percentile(np.abs(dx), 90)), 2)
        res["dy_p50"] = round(float(np.percentile(np.abs(dy), 50)), 2)
        res["dy_p90"] = round(float(np.percentile(np.abs(dy), 90)), 2)
        res["within2pt"] = round(float((eu <= 2).mean()), 4)
        res["within5pt"] = round(float((eu <= 5).mean()), 4)
        # worst pages by drift
        bad = {}
        for x, y, pg, w in drifts:
            bad.setdefault(pg, []).append(abs(y))
        res["page_dy_p90"] = {p: round(float(np.percentile(v, 90)), 1)
                              for p, v in sorted(bad.items())}
    return res


def evaluate(src_pdf, docx_path, work_dir, save_images=True, dpi=110, img_dir=None,
             rendered_pdf=None):
    """Score a conversion.

    `rendered_pdf` lets a caller supply a render from somewhere other than the
    LibreOffice proxy -- notably the Google Docs oracle, which is the renderer
    the product actually targets.
    """
    os.makedirs(work_dir, exist_ok=True)
    img_dir = img_dir or work_dir
    if save_images:
        os.makedirs(img_dir, exist_ok=True)
    res = {"src": os.path.basename(src_pdf), "docx": os.path.basename(docx_path)}
    res["docx_bytes"] = os.path.getsize(docx_path)

    live, imgs = docx_live_text(docx_path)
    src_t = pdf_text(src_pdf)
    res["src_chars"] = len(norm(src_t))
    res["live_chars"] = len(norm(live))
    res["live_text_cov"] = live_text_cov(src_pdf, docx_path)
    res["raster_frac"] = round(1 - res["live_text_cov"], 4)
    res["n_media"] = len(imgs)
    res["media_bytes"] = sum(s for _, s in imgs)

    try:
        rpdf = rendered_pdf or docx_to_pdf(docx_path, work_dir)
    except Exception as e:
        res["error"] = str(e)[:300]
        return res
    res["render_pdf"] = rpdf
    res["renderer"] = "supplied" if rendered_pdf else "libreoffice"

    s_doc, r_doc = fitz.open(src_pdf), fitz.open(rpdf)
    res["src_pages"], res["out_pages"] = s_doc.page_count, r_doc.page_count
    res["page_match"] = s_doc.page_count == r_doc.page_count
    res["src_pagesize"] = [round(s_doc[0].rect.width, 1), round(s_doc[0].rect.height, 1)]
    res["out_pagesize"] = [round(r_doc[0].rect.width, 1), round(r_doc[0].rect.height, 1)]
    s_doc.close(); r_doc.close()

    res.update(word_metrics(src_pdf, rpdf))

    # Page i of the source is only ever compared with page i of the render, so
    # rasterise exactly that pair and let it go. Materialising both documents
    # first cost (src_pages + out_pages) x 27.2 MB with nothing released until
    # the loop ended: measured on y06_irs_1040_instructions, 126 source pages
    # against a 591-page render asked for 3.4 GB + 16.1 GB and was OOM-killed
    # before it scored a single page. The arrays, their order and every number
    # below are unchanged -- only how long each one stays alive.
    rows = []
    s_doc, r_doc = fitz.open(src_pdf), fitz.open(rpdf)
    try:
        n_src, n_out = s_doc.page_count, r_doc.page_count
        for i in range(max(n_src, n_out)):
            if i >= n_src or i >= n_out:
                rows.append({"page": i + 1, "ssim": 0.0, "iou": 0.0,
                             "note": "missing"})
                continue
            pa, pb = page_array(s_doc, i, dpi), page_array(r_doc, i, dpi)
            h = max(pa.shape[0], pb.shape[0]); w = max(pa.shape[1], pb.shape[1])
            a, b = pad_to(pa, h, w), pad_to(pb, h, w)
            del pa, pb
            rows.append({"page": i + 1, "ssim": round(ssim(a, b), 4),
                         "iou": round(ink_iou(a, b), 4),
                         "mad": round(float(np.abs(a - b).mean()), 2)})
            if save_images:
                import PIL.Image as Image
                gap = 10
                canvas = np.full((h, w * 2 + gap, 3), 180.0)
                canvas[:, :w] = a; canvas[:, w + gap:] = b
                Image.fromarray(canvas.astype(np.uint8)).save(
                    os.path.join(img_dir, "cmp_p%02d.png" % (i + 1)))
                del canvas
            del a, b
    finally:
        s_doc.close(); r_doc.close()
    res["pages"] = rows
    res["mean_ssim"] = round(float(np.mean([r["ssim"] for r in rows])), 4)
    res["mean_iou"] = round(float(np.mean([r["iou"] for r in rows])), 4)
    return res


def brief(res):
    if "error" in res:
        return "%-34s ERROR %s" % (res["src"], res["error"][:90])
    return ("%-30s pg %s/%s %-4s | live %.3f | keep %.3f | place %.3f | "
            "dy50 %5.1f dy90 %6.1f | <2pt %.2f | ssim %.3f iou %.3f | img %d" % (
                res["src"][:30], res["src_pages"], res["out_pages"],
                "ok" if res["page_match"] else "BAD",
                res["live_text_cov"], res.get("doc_recall", 0),
                res.get("word_recall", 0),
                res.get("dy_p50", -1), res.get("dy_p90", -1),
                res.get("within2pt", 0), res["mean_ssim"], res["mean_iou"],
                res["n_media"]))


if __name__ == "__main__":
    src, docx, work = sys.argv[1], sys.argv[2], sys.argv[3]
    r = evaluate(src, docx, work)
    print(json.dumps({k: v for k, v in r.items() if k != "pages"}, indent=1))
    for row in r.get("pages", []):
        print("  p%-3d ssim %.3f iou %.3f mad %.1f" %
              (row["page"], row["ssim"], row["iou"], row.get("mad", 0)))
    print(brief(r))
