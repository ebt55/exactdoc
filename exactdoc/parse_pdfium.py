"""PDF -> IR parser built on pypdfium2 (Apache-2.0 / BSD-3).

The permissive replacement for parse.py. exactdoc is AGPL only because
PyMuPDF is; this module exists so the project can relicense.

PDFium exposes glyphs, not documents: characters with a font, a size, a colour
and a box, and nothing that says which of them form a word, a line or a
paragraph. PyMuPDF's `get_text("dict")` does that grouping internally, and
every threshold downstream of parse.py was calibrated against its answers. So
the grouping has to be rebuilt here, and rebuilt to agree -- which is exactly
what testkit/golden_ir.py measures.

Coordinates: PDFium is bottom-left origin, the IR is top-left. Every y is
flipped on the way in. Sizes are in points throughout.
"""
import ctypes
import re
from typing import List, Optional

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from .model import DocIR, PageIR, TextBlock, Line, Span, DrawCmd, ImageObj

_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")

# PDF FontDescriptor flag bits (PDF 32000-1, table 123)
_FLAG_FIXED = 1 << 0
_FLAG_SERIF = 1 << 1
_FLAG_ITALIC = 1 << 6
_FLAG_BOLD = 1 << 18

# Grouping tolerances, in points. Chosen to reproduce PyMuPDF's grouping;
# golden_ir.py is the arbiter, not intuition.
BASELINE_TOL = 1.0        # chars on the same visual line
SPAN_GAP_EM = 0.28        # style-independent gap that ends a span
SPACE_GAP_EM = 0.24       # gap wide enough to mean a space the producer drew
                          # by positioning rather than by emitting a character
LINE_SPLIT_EM = 1.10      # gap that ends the LINE, not merely the span:
                          # sharing a baseline is not sharing a line. Table
                          # cells and the two halves of a two-column page do
                          # exactly that, and merging them fused rows into
                          # single lines (measured: 0.60x PyMuPDF's count).
BLOCK_GAP_FACTOR = 1.6    # line pitch multiple that ends a block
# Horizontal reach for joining lines that share a baseline. Deliberately
# SHORT: it now only has to catch genuinely adjacent text, such as a list
# marker and its item. Table rows are joined later by dialect._join_ruled_rows,
# which has the ruling lines and can tell a cell gap from a coincidence --
# something no width threshold here can do, since the two have identical gap
# distributions (median 4.7em each).
BLOCK_SAME_ROW_EM = 1.2
MONO_ADV_EM = 0.6         # advance of a monospaced glyph, as a fraction of size


def _line_size(ln) -> float:
    return max((s.size for s in ln.spans), default=10.0)


def _hexcol(r, g, b):
    return "#%02x%02x%02x" % (r & 255, g & 255, b & 255)


class _Char:
    __slots__ = ("u", "x0", "y0", "x1", "y1", "ox", "oy", "size", "font",
                 "flags", "color")

    @property
    def mono_hint(self) -> bool:
        fl = (self.font or "").lower()
        return bool(self.flags & _FLAG_FIXED) or "courier" in fl or "mono" in fl


def _page_chars(textpage, page_h) -> List[_Char]:
    n = raw.FPDFText_CountChars(textpage.raw)
    out = []
    buf = ctypes.create_string_buffer(128)
    for i in range(n):
        u = raw.FPDFText_GetUnicode(textpage.raw, i)
        if u in (0, 0xFFFE):
            continue
        # PDFium synthesises characters that are not in the PDF: spaces, where
        # a producer positioned words instead of emitting a space, and CR/LF at
        # line ends. All of them carry a dummy 1.0pt size.
        #
        # Dropping them all was wrong. PDFium's space synthesis is better than
        # the gap heuristic below -- with the generated spaces gone, headings
        # came out as 'ImplementationNotes', because at 22pt the ink-to-ink gap
        # falls under any threshold that does not also produce spurious spaces
        # in body text. So keep generated SPACES and let them inherit the
        # neighbouring style; drop only the line breaks, which are pure
        # reading-order decoration and would otherwise each become a 1pt run.
        generated = False
        try:
            generated = raw.FPDFText_IsGenerated(textpage.raw, i) == 1
        except Exception:
            pass
        if generated and chr(u) in ("\r", "\n"):
            continue
        l = ctypes.c_double(); r_ = ctypes.c_double()
        b = ctypes.c_double(); t = ctypes.c_double()
        if not raw.FPDFText_GetCharBox(textpage.raw, i,
                                       ctypes.byref(l), ctypes.byref(r_),
                                       ctypes.byref(b), ctypes.byref(t)):
            continue
        ox = ctypes.c_double(); oy = ctypes.c_double()
        raw.FPDFText_GetCharOrigin(textpage.raw, i, ctypes.byref(ox), ctypes.byref(oy))
        flags = ctypes.c_int()
        ln = raw.FPDFText_GetFontInfo(textpage.raw, i, buf, 128, ctypes.byref(flags))
        font = buf.raw[:max(0, ln - 1)].decode("utf-8", "replace") if ln else ""
        cr = ctypes.c_uint(); cg = ctypes.c_uint()
        cb = ctypes.c_uint(); ca = ctypes.c_uint()
        raw.FPDFText_GetFillColor(textpage.raw, i, ctypes.byref(cr), ctypes.byref(cg),
                                  ctypes.byref(cb), ctypes.byref(ca))
        # The LOOSE box is derived from the font's metrics; the tight box is
        # the glyph's ink. PyMuPDF reports metric-based line boxes, so using
        # ink here made every line box start below the true ascent and shifted
        # the inferred top margin (measured 71.8pt against 67.8pt) and with it
        # every space_before on the page.
        lr = raw.FS_RECTF()
        if raw.FPDFText_GetLooseCharBox(textpage.raw, i, ctypes.byref(lr)):
            ly0, ly1 = float(lr.bottom), float(lr.top)
        else:
            ly0, ly1 = float(b.value), float(t.value)

        c = _Char()
        c.u = chr(u)
        # flip y: PDFium is bottom-left origin, the IR is top-left
        c.x0, c.x1 = float(l.value), float(r_.value)
        c.y0, c.y1 = page_h - max(ly1, float(t.value)), page_h - min(ly0, float(b.value))
        c.ox, c.oy = float(ox.value), page_h - float(oy.value)
        # FPDFText_GetFontSize reports the size BEFORE the text matrix. Chromium
        # lays out in CSS pixels and applies a 0.75 matrix, so every size came
        # out 4/3 too large -- which inflated leading, paragraph heights and
        # therefore page counts across the board (7 source pages rendered as
        # 20). The effective size is the reported size times the matrix's
        # vertical scale; producers that use an identity matrix are unaffected.
        size = abs(float(raw.FPDFText_GetFontSize(textpage.raw, i)))
        try:
            m = raw.FS_MATRIX()
            if raw.FPDFText_GetMatrix(textpage.raw, i, ctypes.byref(m)):
                vs = (m.b * m.b + m.d * m.d) ** 0.5
                if vs > 1e-6:
                    size *= vs
        except Exception:
            pass
        # a generated space has no font of its own; inherit the run it joins
        if generated and out:
            prev = out[-1]
            c.size = prev.size
            c.font, c.flags, c.color = prev.font, prev.flags, prev.color
            c.x0, c.x1 = prev.x1, max(prev.x1, c.x1)
            c.y0, c.y1 = prev.y0, prev.y1
            out.append(c)
            continue
        c.size = size
        c.font = _SUBSET_RE.sub("", font)
        c.flags = int(flags.value)
        c.color = _hexcol(cr.value, cg.value, cb.value)
        out.append(c)
    return out


def _is_rtl(ch: str) -> bool:
    o = ord(ch)
    return (0x0590 <= o <= 0x05FF or 0x0600 <= o <= 0x06FF or
            0x0700 <= o <= 0x074F or 0x0750 <= o <= 0x077F or
            0x08A0 <= o <= 0x08FF or 0xFB1D <= o <= 0xFB4F or
            0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF)


def _reorder_rtl(row):
    """Visual order -> logical order for right-to-left runs.

    PDFium reports glyphs in visual order, so sorting a line by x -- which is
    what every other script needs -- lays each Arabic or Hebrew word out
    backwards: 'Ù†ÙŠÙ…Ø¶ØªÙ„Ø§' where the text reads 'Ø§Ù„ØªØ¶Ù…ÙŠÙ†'. The characters are all
    present and correctly shaped; only their sequence is mirrored. Reversing
    each maximal run of RTL characters restores logical order, which is what
    the writer must emit and what PyMuPDF already returns.

    This is not a full bidi implementation -- no embedding levels, no bracket
    pairing -- and it does not need to be: the IR only has to carry the same
    order the other backend does.
    """
    out, i, n = [], 0, len(row)
    while i < n:
        if _is_rtl(row[i].u[:1] or " "):
            j = i
            while j < n and (_is_rtl(row[j].u[:1] or " ") or
                             (row[j].u.isspace() and j + 1 < n and
                              _is_rtl(row[j + 1].u[:1] or " "))):
                j += 1
            out.extend(reversed(row[i:j]))
            i = j
        else:
            out.append(row[i])
            i += 1
    return out


def _is_cjk(ch: str) -> bool:
    """CJK, kana, hangul and full-width forms.

    These scripts set no spaces between characters, and their glyphs are
    full-width, so an inter-glyph gap that would mean a space in Latin text
    means nothing here. Without this guard the gap heuristic inserted spaces
    mid-word -- 'ã‚³ãƒ¼ãƒ‘ã‚¹ ãŒåŸ‹ã‚è¾¼ã¿' where the source has none -- which cost
    32% of the text-coverage score on the multilingual document.
    """
    o = ord(ch)
    return (0x2E80 <= o <= 0x303F or 0x3040 <= o <= 0x33FF or
            0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or
            0xA000 <= o <= 0xA4CF or 0xAC00 <= o <= 0xD7AF or
            0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE4F or
            0xFF00 <= o <= 0xFFEF)


# Serif families whose FontDescriptor is routinely absent. The standard 14
# fonts may legally omit the descriptor entirely, and non-embedded system
# fonts often do too, so `flags` arrives as 0 and the Serif bit is unreadable.
_SERIF_NAMES = ("times", "georgia", "garamond", "cambria", "palatino", "book",
                "minion", "caslon", "baskerville", "didot", "bodoni", "utopia",
                "charter", "constantia", "sabon", "century", "roman", "serif",
                "mincho", "songti", "sungti", "batang", "yugothic")


def _style(c: _Char):
    fl = c.font.lower()
    bold = bool(c.flags & _FLAG_BOLD) or "bold" in fl or "black" in fl or "heavy" in fl
    italic = bool(c.flags & _FLAG_ITALIC) or "italic" in fl or "oblique" in fl
    mono = bool(c.flags & _FLAG_FIXED) or "courier" in fl or "mono" in fl
    # The descriptor is authoritative when present, but "present" is not
    # detectable from a single bit -- a font with no descriptor and a font with
    # a descriptor that clears every flag both arrive as 0. Measured against
    # PyMuPDF, this backend called Times-Roman, Times-Bold and Times-Italic
    # sans on every core-14 document. Fall back to the name, as bold/italic/
    # mono already do above, and never let "sans-serif" match "serif".
    serif = bool(c.flags & _FLAG_SERIF)
    if not serif and "sans" not in fl:
        serif = any(k in fl for k in _SERIF_NAMES)
    return (c.font, round(c.size, 2), c.color, bold, italic, mono, serif)


def _build_lines(chars: List[_Char]) -> List[Line]:
    """chars -> spans -> lines, by baseline then x.

    PDFium emits characters in content-stream order, which is not reading
    order, so grouping is geometric: characters sharing a baseline form a
    line, and a style change or a wide gap ends a span. The gap test also
    reinserts the spaces that a producer drew as positioning rather than as
    space characters -- without it, justified text arrives as one long word.
    """
    if not chars:
        return []
    rows = []
    for c in sorted(chars, key=lambda c: (round(c.oy, 1), c.ox)):
        placed = False
        for r in rows:
            if abs(c.oy - r[0].oy) <= max(BASELINE_TOL, 0.12 * c.size):
                r.append(c)
                placed = True
                break
        if not placed:
            rows.append([c])

    # split each baseline row into visual lines at wide horizontal gaps
    vis_rows = []
    for row in rows:
        row.sort(key=lambda c: c.x0)
        part = [row[0]]
        for prev, c in zip(row, row[1:]):
            if c.x0 - prev.x1 > LINE_SPLIT_EM * max(prev.size, c.size, 1.0):
                vis_rows.append(part)
                part = [c]
            else:
                part.append(c)
        vis_rows.append(part)

    lines = []
    for row in vis_rows:
        if any(_is_rtl(c.u[:1] or " ") for c in row):
            row = _reorder_rtl(row)
        spans, cur, cur_key = [], [], None
        for c in row:
            k = _style(c)
            gap = (c.x0 - cur[-1].x1) if cur else 0.0
            if cur and (k != cur_key or gap > SPAN_GAP_EM * max(c.size, 1.0)):
                spans.append((cur, cur_key))
                cur, cur_key = [], None
            if not cur:
                cur_key = k
            elif gap > SPACE_GAP_EM * max(c.size, 1.0) \
                    and not _is_cjk(cur[-1].u[-1]) and not _is_cjk(c.u):
                # A gap can stand for SEVERAL spaces. Code indentation is one
                # wide gap, and emitting a single space for it collapsed four
                # columns to one -- 19 unmatched words and 40pt of horizontal
                # drift on a listing. Monospace advances are ~0.6em, so the
                # count is recoverable from the gap; proportional text is
                # ~0.28em and rarely runs more than one.
                adv = (MONO_ADV_EM if cur[-1].mono_hint else 0.28) * max(c.size, 1.0)
                n_sp = int(round(gap / adv)) if adv > 0 else 1
                if cur[-1].u.isspace() or c.u.isspace():
                    n_sp = min(n_sp, 1) if not cur[-1].mono_hint else n_sp
                if n_sp >= 1:
                    cur[-1].u += " " * min(n_sp, 24)
            cur.append(c)
        if cur:
            spans.append((cur, cur_key))

        sp_objs = []
        for cs, key in spans:
            if not cs:
                continue
            font, size, color, bold, italic, mono, serif = key
            text = "".join(c.u for c in cs)
            if not text.strip() and not sp_objs:
                continue
            bb = (min(c.x0 for c in cs), min(c.y0 for c in cs),
                  max(c.x1 for c in cs), max(c.y1 for c in cs))
            sp_objs.append(Span(
                text=text, font=font, size=size, color=color, bold=bold,
                italic=italic, mono=mono, serif=serif, superscript=False,
                bbox=bb, origin=(cs[0].ox, cs[0].oy)))
        if not sp_objs:
            continue
        lb = (min(s.bbox[0] for s in sp_objs), min(s.bbox[1] for s in sp_objs),
              max(s.bbox[2] for s in sp_objs), max(s.bbox[3] for s in sp_objs))
        lines.append(Line(spans=sp_objs, bbox=lb))
    lines.sort(key=lambda l: (round(l.bbox[1], 1), l.bbox[0]))
    _reconstruct_indents(lines)
    return lines


def _reconstruct_indents(lines: List[Line]) -> None:
    """Put back the leading indentation PDFium does not report.

    PDFium synthesises the spaces a producer drew by positioning -- but only
    BETWEEN two characters, because that is the only place a gap exists to
    measure. At the start of a line there is nothing to the left, so the indent
    is simply absent: measured on c7_code, the raw character stream for
    `    def __init__(...)` begins with 'd' at x=93.17 and contains no space at
    all, while PyMuPDF reports the same line starting at x=72.25 with four
    leading spaces.

    Downstream that is not a cosmetic difference. The line box starts at the
    first ink instead of at the code block's left edge, so the paragraph is
    written at the wrong x and every glyph on the line is displaced by the
    indent. It is the whole of the code-heavy gap the defect register left
    unattributed: c7_code within-2pt 0.91 -> 0.16 with 16 of its 26 lines
    failing to pair with their PyMuPDF counterparts at all.

    Reconstruction needs a left edge to measure from, and the block's own
    minimum will not do -- a block whose every line is indented (a continuation
    inside a function body) would measure zero indent. The reference is the
    leftmost line of the surrounding *monospace run*: consecutive mono lines,
    which is exactly the extent of one code listing, ended by the first
    proportional line. On c7_code that yields 72.25 for both listings, and the
    two are separated by their heading.

    Restricted to monospace deliberately. Indentation is load-bearing in code
    and decorative almost everywhere else, a proportional font has no single
    advance width to divide by, and the measured defect is entirely in code
    blocks. A proportional first-line indent stays where it is: expressed by
    the line box, as it already was.

    Lines that SHARE a baseline are excluded, and that exclusion is not a
    detail. A configuration table whose cells are set in a monospace face puts
    three of them on one baseline at x=61, 153 and 223; read as a listing, the
    second and third are "indented" by 18 and 32 spaces and get dragged back to
    the left margin. Measured, when this function did that:
    03_tech_report_code within-2pt 0.23 -> 0.03. A line alone on its baseline is
    a line of a listing; several lines on one baseline are the cells of a row,
    and their x is a column position rather than an indent.
    """
    # A baseline carrying more than one line is a row of cells, not a listing.
    rows = {}
    for ln in lines:
        rows.setdefault(round(ln.baseline, 1), []).append(ln)
    solo = {id(ln) for group in rows.values() if len(group) == 1 for ln in group}

    def flush(run):
        if len(run) < 2:
            return
        left = min(l.bbox[0] for l in run)
        for ln in run:
            size = max((s.size for s in ln.spans), default=10.0)
            adv = MONO_ADV_EM * max(size, 1.0)
            n = int(round((ln.bbox[0] - left) / adv)) if adv > 0 else 0
            if n < 1:
                continue
            first = ln.spans[0]
            first.text = " " * min(n, 40) + first.text
            first.bbox = (left, first.bbox[1], first.bbox[2], first.bbox[3])
            first.origin = (left, first.origin[1])
            ln.bbox = (left, ln.bbox[1], ln.bbox[2], ln.bbox[3])

    run = []
    for ln in lines:
        inked = [s for s in ln.spans if s.text.strip()]
        mono = bool(inked) and all(s.mono for s in inked) and id(ln) in solo
        # A listing is contiguous. Two listings separated by other content share
        # no left edge, and the run must not straddle the gap between them.
        if mono and run:
            pitch = max(_line_size(ln), _line_size(run[-1]), 1.0)
            if ln.baseline - run[-1].baseline > 3.0 * pitch:
                flush(run)
                run = []
        if mono:
            run.append(ln)
        else:
            flush(run)
            run = []
    flush(run)


def _column_split(lines: List[Line]) -> Optional[float]:
    """The x of a genuine column gutter on this page, or None.

    Deciding whether two lines that share a baseline belong together is the
    difference between a table row (join: they are cells) and a two-column page
    (do not join: they are separate flows). Width cannot decide it -- measured,
    a table's cell gaps run WIDER than a two-column gutter, so every single
    threshold fixes one document and breaks the other, and page-wide empty-band
    detection fails too because a full-width title sits across the gutter.

    Structure decides it. A two-column page splits into exactly TWO groups, both
    wide, at the same x, for most of its rows. A table row splits into several
    narrow cells at x positions that differ per table. So look for that shape
    and nothing else.
    """
    rows = {}
    for ln in lines:
        rows.setdefault(round(ln.baseline, 0), []).append(ln)
    span_lo = min(l.bbox[0] for l in lines)
    span_hi = max(l.bbox[2] for l in lines)
    content_w = max(1.0, span_hi - span_lo)

    votes = {}
    pairs = 0
    for _, row in rows.items():
        row.sort(key=lambda l: l.bbox[0])
        # EXACTLY two groups. This is the whole discriminator: a two-column
        # baseline carries one line from each column, while a table row carries
        # one per cell -- four to seven on the corpus's tables. Taking the
        # widest gap of an arbitrary-length row instead let a wide first table
        # column masquerade as a gutter.
        if len(row) != 2:
            continue
        a, b = row
        g = b.bbox[0] - a.bbox[2]
        if g < 6.0:
            continue
        left_w = a.bbox[2] - a.bbox[0]
        right_w = b.bbox[2] - b.bbox[0]
        # both halves substantial: columns are wide, cells are not
        if left_w < 0.25 * content_w or right_w < 0.25 * content_w:
            continue
        pairs += 1
        bx = (a.bbox[2] + b.bbox[0]) / 2
        votes[round(bx / 4.0)] = votes.get(round(bx / 4.0), 0) + 1

    if not votes or pairs < 3:
        return None
    bx4, n = max(votes.items(), key=lambda kv: kv[1])
    # a gutter is consistent; a coincidence is not
    return bx4 * 4.0 if n >= max(3, 0.6 * pairs) else None


def _build_blocks(lines: List[Line], page_w: float = 612.0) -> List[TextBlock]:
    """lines -> blocks, by vertical pitch and horizontal adjacency.

    On a two-column page each column is blocked SEPARATELY. Blocking the page
    as one stream sorts the lines by baseline, which interleaves the columns --
    left line 1, right line 1, left line 2 -- so consecutive lines never
    overlap horizontally and every one becomes a block, and then a paragraph,
    of its own. Measured: 20 paragraphs holding 23 source lines where PyMuPDF
    had 16 holding 47, and 106pt of extra space_before, which cost a page.
    """
    if not lines:
        return []
    col_x = _column_split(lines)
    if col_x is not None:
        left = [l for l in lines if (l.bbox[0] + l.bbox[2]) / 2 <= col_x]
        right = [l for l in lines if (l.bbox[0] + l.bbox[2]) / 2 > col_x]
        if left and right:
            out = _build_blocks_one(left, col_x) + _build_blocks_one(right, col_x)
            out.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
            return out
    return _build_blocks_one(lines, col_x)


def _build_blocks_one(lines: List[Line], col_x) -> List[TextBlock]:
    if not lines:
        return []
    # A page-wide median pitch is a poor threshold for a page with several
    # pitches -- 03_tech_report_code page 1 has fourteen, and its median of
    # 22.0pt (the configuration table outnumbers everything else) puts the split
    # at 35.2pt, swallowing the 23.0pt blank lines inside a code listing whose
    # own pitch is 11.5pt. Replacing it with a LOCAL median was tried and
    # reverted: it split the listing correctly and cost 02_research_paper
    # within-2pt 0.57 -> 0.02, because a local window inside a dense
    # two-column body finds a pitch small enough to cut paragraphs in half.
    # Recorded in SESSIONS.md; the estimator needs to be robust in both
    # directions before it is worth another attempt.
    pitches = []
    for a, b in zip(lines, lines[1:]):
        d = b.baseline - a.baseline
        if 0 < d < 60:
            pitches.append(d)
    pitches.sort()
    typical = pitches[len(pitches) // 2] if pitches else 12.0

    blocks, cur = [], [lines[0]]
    for prev, ln in zip(lines, lines[1:]):
        gap = ln.baseline - prev.baseline
        overlap = min(prev.bbox[2], ln.bbox[2]) - max(prev.bbox[0], ln.bbox[0])
        # gap == 0 means the two lines SHARE a baseline -- the cells of a table
        # row, or a marker and its item. Requiring 0 < gap made each of them a
        # block of its own, and therefore a paragraph of its own: one table
        # document went from 29 paragraphs to 98, its accumulated space_before
        # from 176pt to 1359pt, and the column detector started finding
        # two-column regions in the debris.
        # A change of type size ends the block. Without it a heading merges
        # into the paragraph beneath it -- '1 Introduction Retrieval quality
        # degrades...' as one 12-line paragraph where PyMuPDF has a 1-line
        # heading and a 6-line body -- because the gap between them is within
        # the ordinary line-pitch tolerance.
        if abs(_line_size(ln) - _line_size(prev)) > 0.06 * max(
                _line_size(prev), _line_size(ln), 1.0):
            blocks.append(cur)
            cur = [ln]
            continue

        if abs(gap) <= 0.6:
            # ...unless they cross this page's column boundary (structural,
            # see _column_split), or sit too far apart to be one row.
            #
            # The distance test is a compromise and provably so: measured over
            # the corpus, the same-baseline gaps inside a TABLE and the
            # spurious ones that merely coincide have identical distributions
            # (median 4.7em for both), so no threshold separates them. The
            # parser cannot answer this question from geometry alone -- knowing
            # a region is a table needs the ruling lines, which infer.py has
            # and this module does not. BLOCK_SAME_ROW_EM keeps the common
            # cases right; the residue is a known limit, not a tuning target.
            hgap = max(ln.bbox[0], prev.bbox[0]) - min(ln.bbox[2], prev.bbox[2])
            em = max(_line_size(prev), _line_size(ln), 1.0)
            same = hgap <= BLOCK_SAME_ROW_EM * em
            if same and col_x is not None:
                same = not (min(prev.bbox[2], ln.bbox[2]) <= col_x <=
                            max(prev.bbox[0], ln.bbox[0]))
        else:
            same = (0 < gap <= typical * BLOCK_GAP_FACTOR) and overlap > 0
        if same:
            cur.append(ln)
        else:
            blocks.append(cur)
            cur = [ln]
    blocks.append(cur)

    out = []
    for grp in blocks:
        bb = (min(l.bbox[0] for l in grp), min(l.bbox[1] for l in grp),
              max(l.bbox[2] for l in grp), max(l.bbox[3] for l in grp))
        out.append(TextBlock(lines=grp, bbox=bb))
    return out


# PDFium segment types. Getting these backwards is not a subtle bug: MOVETO
# is 2 and BEZIERTO is 1, so treating 2 as "curve" makes EVERY path curved --
# every path starts with a MOVETO. That classified all 342 rules and fills in
# one test document as curves, which promoted their cluster to "figure" and
# rasterised the page: 1.1% live text out of character-perfect extraction.
SEG_LINETO = raw.FPDF_SEGMENT_LINETO      # 0
SEG_BEZIERTO = raw.FPDF_SEGMENT_BEZIERTO  # 1
SEG_MOVETO = raw.FPDF_SEGMENT_MOVETO      # 2


def _obj_matrix(obj):
    """(a, b, c, d, e, f) for a page object, or None when unavailable."""
    try:
        m = raw.FS_MATRIX()
        if raw.FPDFPageObj_GetMatrix(obj.raw, ctypes.byref(m)):
            return (m.a, m.b, m.c, m.d, m.e, m.f)
    except Exception:
        pass
    return None


def _apply_matrix(m, x, y):
    if m is None:
        return x, y
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def _matrix_scale(m):
    """Uniform scale factor of a matrix, for converting stroke widths."""
    if m is None:
        return 1.0
    a, b, c, d, _, _ = m
    s = abs(a * d - b * c) ** 0.5
    return s if s > 1e-9 else 1.0


def _classify(pts, w, h) -> str:
    has_curve = any(t == SEG_BEZIERTO for _, _, t in pts)
    # a rectangle arrives as MOVETO + 3-4 LINETO
    corners = sum(1 for _, _, t in pts if t in (SEG_LINETO, SEG_MOVETO))
    if not has_curve:
        # Orientation comes from the POINTS, not the bounds. FPDFPageObj_GetBounds
        # includes the stroke width, so a 3pt-wide stroked rule measures 3pt
        # across and misses a bounds-based "thin" test -- PyMuPDF's rect is the
        # geometric path and does not. Those rules then classified as "line",
        # which promotes their cluster straight to "figure": two callout accent
        # bars were enough to rasterise both callouts and 23% of a document's
        # text.
        #
        # The points reaching here are in PAGE space. They did not used to be:
        # PDFium reports segment points in OBJECT space, so this test compared
        # object-space dx/dy against page-space w/h. On a Chromium document that
        # is every path on the page -- measured, 578 of the corpus's 612 path
        # objects carry a non-identity matrix, and raw points miss the true
        # bounds by up to 5438pt (testkit/backend_paths.py).
        if len(pts) <= 3:
            xs = [x for x, _, _ in pts]
            ys = [y for _, y, _ in pts]
            dx, dy = max(xs) - min(xs), max(ys) - min(ys)
            if dy <= 1.0 and dx > 4:
                return "hline"
            if dx <= 1.0 and dy > 4:
                return "vline"
        if h <= 2.0 and w > 4:
            return "hline"
        if w <= 2.0 and h > 4:
            return "vline"
        if corners in (4, 5):
            return "rect"
        if corners <= 3:
            return "line"
        return "complex"
    return "curve" if len(pts) <= 12 else "complex"


def _rect_pts(pts):
    """The (x, y) corners of a path, if it is an axis-aligned rectangle."""
    if any(t == SEG_BEZIERTO for _, _, t in pts):
        return None
    xs = {round(x, 2) for x, _, _ in pts}
    ys = {round(y, 2) for _, y, _ in pts}
    if len(xs) == 2 and len(ys) == 2:
        return (min(xs), min(ys), max(xs), max(ys))
    return None


def _frame_edges(sub_rects):
    """Two nested rectangles (an even-odd ring) -> its visible edge bars.

    parse.py does this so a decorative frame's bounding box does not swallow
    everything inside it. Without it the same frames become opaque blocks here.
    """
    if len(sub_rects) != 2:
        return None
    r1, r2 = sub_rects
    a1 = (r1[2] - r1[0]) * (r1[3] - r1[1])
    a2 = (r2[2] - r2[0]) * (r2[3] - r2[1])
    outer, inner = (r1, r2) if a1 >= a2 else (r2, r1)
    if not (inner[0] >= outer[0] - 0.2 and inner[1] >= outer[1] - 0.2 and
            inner[2] <= outer[2] + 0.2 and inner[3] <= outer[3] + 0.2):
        return None
    ow, oh = outer[2] - outer[0], outer[3] - outer[1]
    iw, ih = inner[2] - inner[0], inner[3] - inner[1]
    if iw < 0.5 * ow or ih < 0.3 * oh:
        return None
    edges = []
    if inner[1] - outer[1] > 0.2:
        edges.append((outer[0], outer[1], outer[2], inner[1]))
    if outer[3] - inner[3] > 0.2:
        edges.append((outer[0], inner[3], outer[2], outer[3]))
    if inner[0] - outer[0] > 0.2:
        edges.append((outer[0], inner[1], inner[0], inner[3]))
    if outer[2] - inner[2] > 0.2:
        edges.append((inner[2], inner[1], outer[2], inner[3]))
    return edges or None


def _page_paths(page, page_h) -> List[DrawCmd]:
    out = []
    seen = set()
    for obj in page.get_objects():
        try:
            if raw.FPDFPageObj_GetType(obj.raw) != raw.FPDF_PAGEOBJ_PATH:
                continue
        except Exception:
            continue
        l = ctypes.c_float(); b = ctypes.c_float()
        r_ = ctypes.c_float(); t = ctypes.c_float()
        if not raw.FPDFPageObj_GetBounds(obj.raw, ctypes.byref(l), ctypes.byref(b),
                                         ctypes.byref(r_), ctypes.byref(t)):
            continue
        bounds_bbox = (float(l.value), page_h - float(t.value),
                       float(r_.value), page_h - float(b.value))
        # Segment points are in OBJECT space: the path object's own matrix has
        # to be applied before they mean anything on the page. Skipping it is
        # not a small error -- measured across the corpus, 578 of 612 path
        # objects carry a non-identity matrix (every path on every Chromium
        # document) and untransformed points miss the true bounds by up to
        # 5438pt. testkit/backend_paths.py measures this and keeps measuring it.
        mat = _obj_matrix(obj)
        n = raw.FPDFPath_CountSegments(obj.raw)
        pts = []
        for i in range(max(0, n)):
            seg = raw.FPDFPath_GetPathSegment(obj.raw, i)
            if not seg:
                continue
            sx = ctypes.c_float(); sy = ctypes.c_float()
            raw.FPDFPathSegment_GetPoint(seg, ctypes.byref(sx), ctypes.byref(sy))
            px, py = _apply_matrix(mat, float(sx.value), float(sy.value))
            pts.append((px, page_h - py, raw.FPDFPathSegment_GetType(seg)))
        fillmode = ctypes.c_int(); stroke = ctypes.c_int()
        raw.FPDFPath_GetDrawMode(obj.raw, ctypes.byref(fillmode), ctypes.byref(stroke))
        fr = ctypes.c_uint(); fg = ctypes.c_uint()
        fb = ctypes.c_uint(); fa = ctypes.c_uint()
        raw.FPDFPageObj_GetFillColor(obj.raw, ctypes.byref(fr), ctypes.byref(fg),
                                     ctypes.byref(fb), ctypes.byref(fa))
        sr = ctypes.c_uint(); sg = ctypes.c_uint()
        sb = ctypes.c_uint(); sa = ctypes.c_uint()
        raw.FPDFPageObj_GetStrokeColor(obj.raw, ctypes.byref(sr), ctypes.byref(sg),
                                       ctypes.byref(sb), ctypes.byref(sa))
        sw = ctypes.c_float()
        raw.FPDFPageObj_GetStrokeWidth(obj.raw, ctypes.byref(sw))
        # ...in object space too, like the points, so it scales with the matrix.
        stroke_w = float(sw.value) * _matrix_scale(mat)
        has_fill = fillmode.value != 0 and fa.value > 0
        has_stroke = bool(stroke.value) and sa.value > 0
        kind = "fillstroke" if (has_fill and has_stroke) else \
               "stroke" if has_stroke else "fill"

        # GetBounds returns the INK envelope: a stroked path inflated by its
        # line width in every direction. PyMuPDF returns the geometric path, and
        # every threshold downstream was tuned against that. The difference
        # decides structure, not appearance: a 0.75pt box border arrives 1.5pt
        # wide instead of zero-width, and infer.py's table detector reads that
        # bar as a column -- measured on 03_tech_report_code, a code listing was
        # built as a two-column table with a 3.0pt first column and its line
        # breaks discarded, where PyMuPDF builds role=code with all ten lines.
        #
        # Curves keep the envelope: their control points hull wider than the
        # drawn curve, so for those GetBounds is the better estimate. Paths that
        # yield no points keep it too.
        bbox = bounds_bbox
        if pts and not any(t == SEG_BEZIERTO for _, _, t in pts):
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bbox = (min(xs), min(ys), max(xs), max(ys))

        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        fill = _hexcol(fr.value, fg.value, fb.value) if has_fill else None
        stroke_c = _hexcol(sr.value, sg.value, sb.value) if has_stroke else None
        opacity = (fa.value if has_fill else sa.value) / 255.0

        # Producers emit borders twice; keep one. parse.py dedupes the same way.
        sig = (tuple(round(v, 1) for v in bbox), kind, fill, stroke_c,
               round(stroke_w, 2), len(pts))
        if sig in seen:
            continue
        seen.add(sig)

        # even-odd ring -> its visible edge bars, so the frame's bbox does not
        # swallow the content inside it
        subs = []
        cur = []
        for x, y, t in pts:
            if t == SEG_MOVETO and cur:
                subs.append(cur)
                cur = []
            cur.append((x, y, t))
        if cur:
            subs.append(cur)
        if len(subs) == 2 and fillmode.value == raw.FPDF_FILLMODE_ALTERNATE:
            rects = [_rect_pts(s) for s in subs]
            if all(rects):
                edges = _frame_edges(rects)
                if edges:
                    for eb in edges:
                        out.append(DrawCmd(
                            kind="fill",
                            shape="hline" if (eb[3] - eb[1]) <= (eb[2] - eb[0]) else "vline",
                            bbox=eb, fill=fill or stroke_c, stroke=None, width=0.0,
                            opacity=opacity, n_items=1))
                    continue

        shape = _classify(pts, w, h)
        if shape == "rect" and fill is not None:
            if h <= 2.5 and w > 8:
                shape = "hline"
            elif w <= 2.5 and h > 8:
                shape = "vline"
        out.append(DrawCmd(
            kind=kind, shape=shape, bbox=bbox, fill=fill, stroke=stroke_c,
            width=stroke_w, opacity=opacity, n_items=max(1, len(pts))))
    return out


def _page_images(page, page_h, keep_data) -> List[ImageObj]:
    out = []
    for obj in page.get_objects():
        try:
            if raw.FPDFPageObj_GetType(obj.raw) != raw.FPDF_PAGEOBJ_IMAGE:
                continue
        except Exception:
            continue
        l = ctypes.c_float(); b = ctypes.c_float()
        r_ = ctypes.c_float(); t = ctypes.c_float()
        if not raw.FPDFPageObj_GetBounds(obj.raw, ctypes.byref(l), ctypes.byref(b),
                                         ctypes.byref(r_), ctypes.byref(t)):
            continue
        bbox = (float(l.value), page_h - float(t.value),
                float(r_.value), page_h - float(b.value))
        data = None
        if keep_data:
            try:
                import io
                from PIL import Image
                pil = obj.get_bitmap(render=False).to_pil()
                buf = io.BytesIO()
                pil.save(buf, format="PNG")
                data = buf.getvalue()
            except Exception:
                data = None
        out.append(ImageObj(bbox=bbox, xref=0,
                            width=int(bbox[2] - bbox[0]), height=int(bbox[3] - bbox[1]),
                            data=data, ext="png"))
    return out


def _page_links(page, textpage, page_h):
    links = []
    try:
        wl = raw.FPDFLink_LoadWebLinks(textpage.raw)
        if wl:
            n = raw.FPDFLink_CountWebLinks(wl)
            for i in range(n):
                need = raw.FPDFLink_GetURL(wl, i, None, 0)
                buf = (ctypes.c_ushort * need)()
                raw.FPDFLink_GetURL(wl, i, buf, need)
                uri = "".join(chr(c) for c in buf[:max(0, need - 1)])
                cnt = raw.FPDFLink_CountRects(wl, i)
                for j in range(cnt):
                    l = ctypes.c_double(); t = ctypes.c_double()
                    r_ = ctypes.c_double(); b = ctypes.c_double()
                    raw.FPDFLink_GetRect(wl, i, j, ctypes.byref(l), ctypes.byref(t),
                                         ctypes.byref(r_), ctypes.byref(b))
                    links.append({"bbox": (float(l.value), page_h - float(t.value),
                                           float(r_.value), page_h - float(b.value)),
                                  "uri": uri})
    except Exception:
        pass
    return links


def parse_pdf(path: str, keep_image_data: bool = True) -> DocIR:
    doc = pdfium.PdfDocument(path)
    meta = {}
    try:
        meta = {k.lower(): v for k, v in (doc.get_metadata_dict() or {}).items()}
    except Exception:
        pass
    ir = DocIR(path=path, meta=meta)
    for pno in range(len(doc)):
        page = doc[pno]
        w, h = page.get_width(), page.get_height()
        pir = PageIR(number=pno + 1, width=w, height=h)
        tp = page.get_textpage()
        pir.links = _page_links(page, tp, h)
        lines = _build_lines(_page_chars(tp, h))
        for sp in (s for l in lines for s in l.spans):
            for lk in pir.links:
                lb = lk["bbox"]
                ov = (max(0, min(sp.bbox[2], lb[2]) - max(sp.bbox[0], lb[0])) *
                      max(0, min(sp.bbox[3], lb[3]) - max(sp.bbox[1], lb[1])))
                if ov > 0.5 * max(1e-6, (sp.bbox[2] - sp.bbox[0]) *
                                  (sp.bbox[3] - sp.bbox[1])):
                    sp.link = lk["uri"]
                    break
        pir.blocks = _build_blocks(lines, w)
        pir.drawings = _page_paths(page, h)
        pir.images = _page_images(page, h, keep_image_data)
        ir.pages.append(pir)
    return ir
