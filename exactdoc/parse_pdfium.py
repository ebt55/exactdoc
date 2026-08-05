"""PDF -> IR parser built on pypdfium2 (Apache-2.0 / BSD-3).

The shipping parser, and the permissive replacement for parse.py. exactdoc was
AGPL only because PyMuPDF was a core dependency; this module is what let the
project relicense to Apache-2.0, which it did on 2026-08-06.

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

from .model import (DocIR, PageIR, TextBlock, Line, Span, DrawCmd, ImageObj,
                    LinkDest, UndecodedGlyph, xml_safe_text, xml_safe_uri)

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
BLOCK_GAP_FACTOR = 1.15   # multiple of the BODY pitch that ends a block. See
                          # _body_pitch: the reference is the 20th-percentile
                          # gap, not the median, so the factor is close to 1.
# A pitch reference below this fraction of the text's own size is not a
# measurement, and _pitch_reference refuses it. See that function for the
# populations; the short version is that a line of size S cannot advance by
# half its own em, so anything under 0.5em is arithmetic on a polluted sample
# rather than a leading anybody set.
PITCH_FLOOR_EM = 0.5
# What to use instead. Measured over the corpus's healthy references, the
# line-weighted mode of ref/size is 1.10-1.20em and holds 57% of the mass, so
# 1.15 is the corpus's own ordinary leading rather than a guess.
PITCH_DEFAULT_EM = 1.15
# Horizontal reach for joining lines that share a baseline. Deliberately
# SHORT: it now only has to catch genuinely adjacent text, such as a list
# marker and its item. Table rows are joined later by dialect._join_ruled_rows,
# which has the ruling lines and can tell a cell gap from a coincidence --
# something no width threshold here can do, since the two have identical gap
# distributions (median 4.7em each).
BLOCK_SAME_ROW_EM = 1.2
MONO_ADV_EM = 0.6         # advance of a monospaced glyph, as a fraction of size
SPACE_ADV_EM = 0.28       # advance of a space in a proportional face
# Super/subscript reattachment. These are infer._merge_row_lines' numbers, not
# new ones: that pass already absorbs raised fragments into their host row, and
# this is the same rule applied one stage earlier so the fragment reaches the
# IR inside its line, which is where PyMuPDF puts it.
SCRIPT_SIZE_FRAC = 0.92   # a fragment this close to the host's size is a line
SCRIPT_BASE_EM = 0.75     # ...a script's baseline stays inside the host em box
SCRIPT_REACH_EM = 0.5     # ...and it sits against the host's text, not adrift
SCRIPT_RAISE_EM = 0.12    # raised by more than this: a superscript
# Table-row regrouping (see _group_table_rows). Repetition, not width, is the
# evidence: a table repeats its columns and a coincidence does not.
# Column detection (see _column_split). A row's member must substantially FILL
# its own column -- that is what tells a page's columns from a table's cells.
# 0.5 of a column is the bar the two-column form always applied, written so it
# means the same thing at three: at N=2, `0.5 * content_w / 2` is the literal
# `0.25 * content_w` it replaces. Written against the whole page instead, the
# bar silently tightened as N grew -- it demanded three quarters of a column at
# N=3 and refused 166 of y06's 224 three-line rows, which is why generalising
# the search alone changed almost nothing.
COLUMN_MEMBER_FRAC = 0.5
# Nothing wider than three text columns is proposed. The corpus's widest is
# y06's three; four or more wide groups on one baseline is the table shape this
# module refuses elsewhere, and y06 alone carries 1511 baselines of arity 6.
COLUMN_MAX = 3
# Projection fallback (see _projection_gutters), consulted ONLY on pages whose
# baselines carry no column evidence at all.
GUTTER_SPAN_FRAC = 0.6    # a line wider than this much of the content crosses
                          # the columns -- a title or a rule. It says nothing
                          # about where they are, so it is excluded from the
                          # profile rather than allowed to close every band.
GUTTER_CROSS_FRAC = 0.02  # a corridor may be crossed by this share of the
                          # page's body lines and still be a corridor. Measured
                          # over 77 known gutters and 142 known column centres:
                          # gutters cross at p50 0.008 and p75 0.012, column
                          # centres at p50 0.304. See _projection_gutters.
GUTTER_MIN_LINES = 3      # a column carries at least three lines; two is a
                          # coincidence, as everywhere else in this module
TABLE_MIN_ROWS = 3        # three aligned baselines; two is a coincidence
TABLE_ROW_PITCH_MAX = 60  # pt between consecutive rows of one band
TABLE_COL_TOL = 3.0       # x-starts of one column agree to about a character
# A list marker and its item are two lines on one baseline (see
# _marker_starts_visual_line). The vocabulary mirrors infer's BULLET_CHARS and
# NUM_RE; it is repeated rather than imported because a parser must not depend
# on the inference layer.
# Bound on the justification exemption (see _gutter_xs): a gap position that
# recurs down a page is a column gutter, not a stretched space.
GUTTER_MIN_ROWS = 4       # 4x the largest legitimate cluster measured (01: 1)
GUTTER_X_TOL = 3.0        # a gutter holds its x; a word space wanders
MARKER_GAP_EM = 0.5       # separation that is not an interword space
MARKER_GAP_ADV = 0.6      # ...and is wide against the marker's own advance
_MARKER_BULLETS = set("•◦▪‣·-–—*➤►○●♦")
_MARKER_RE = re.compile(r"^\(?(\d{1,3}|[a-zA-Z]|[ivxlIVXL]{1,5})[.):]$")


def _line_size(ln) -> float:
    return max((s.size for s in ln.spans), default=10.0)


def _hexcol(r, g, b):
    return "#%02x%02x%02x" % (r & 255, g & 255, b & 255)


class _Char:
    __slots__ = ("u", "x0", "y0", "x1", "y1", "ox", "oy", "size", "font",
                 "flags", "color", "gen", "sup")

    def __init__(self):
        # Only the flag that _absorb_script_rows sets needs a default; every
        # other slot is assigned by _page_chars before the character is used,
        # and leaving them unset keeps construction as cheap as it was.
        self.sup = False

    @property
    def mono_hint(self) -> bool:
        fl = (self.font or "").lower()
        return bool(self.flags & _FLAG_FIXED) or "courier" in fl or "mono" in fl


def _page_chars(textpage, page_h) -> List[_Char]:
    """Characters with geometry, in content-stream order.

    A note on unmapped glyphs, because one of them crashed every conversion of
    the real-world corpus. When a font gives PDFium no usable ToUnicode entry,
    FPDFText_GetUnicode returns the raw CHARACTER CODE, which for these files is
    a C0 control code -- and lxml refuses to put one in a w:t node, so the whole
    document failed to serialise. model.xml_safe_text now removes them.

    What is lost with them is measurable and worth stating. On Adobe PDFMaker
    output the code is U+0002 and the glyph is the end-of-line hyphen: measured
    on y10_nist_fips180, PDFium reports `...SHA-384, SHA\\x02` where PyMuPDF
    reports `...SHA-384, SHA-`. Dropping it leaves `SHA`, so infer._soft_join
    sees no trailing hyphen and joins the wrapped word with a space -- `SHA 512`
    against the reference's `SHA-512`.

    Mapping U+0002 to a hyphen would fix those documents and be a guess about
    content everywhere else: the code point says nothing about what was drawn,
    and the same code is a different glyph in a different font. So the crash is
    fixed here and the recovery is left as its own problem, with the evidence
    written down rather than encoded as a constant.
    """
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
        # ...and the same is true HORIZONTALLY, which this used to get wrong.
        # PyMuPDF reports a line box that starts at the pen origin, so every
        # line of a left-aligned page starts at exactly the same x. The ink box
        # starts at the first glyph's ink, which moves with whichever letter
        # happens to begin the line: measured on c6_long, 'L' +1.694pt,
        # '1' +1.106, 'R' +0.504, 'T' +0.074, 'w' -0.011 against PyMuPDF's
        # constant 61.500. That is the left side bearing, a different number
        # per line, and it is unfixable downstream -- no per-page correction
        # removes a per-character error. It is why c6_long could reach an IR
        # identical to PyMuPDF's on lines, spans, text, spaces, styles and block
        # boundaries and still score 0.46 against 0.76.
        #
        # Probed before being relied on (§12 law 15): loose.left equals
        # FPDFText_GetCharOrigin's x to 0.000 on every character sampled, and
        # equals PyMuPDF's line x0 exactly.
        lr = raw.FS_RECTF()
        if raw.FPDFText_GetLooseCharBox(textpage.raw, i, ctypes.byref(lr)):
            ly0, ly1 = float(lr.bottom), float(lr.top)
            lx0, lx1 = float(lr.left), float(lr.right)
        else:
            ly0, ly1 = float(b.value), float(t.value)
            lx0, lx1 = float(l.value), float(r_.value)

        c = _Char()
        c.u = chr(u)
        # flip y: PDFium is bottom-left origin, the IR is top-left
        c.x0, c.x1 = lx0, max(lx1, lx0)
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
        c.gen = generated
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

    # A generated space carries no box of its own worth the name: PDFium
    # reports it degenerate, `x..x` at a single coordinate, so the branch above
    # ends up giving it [previous character's end, that coordinate] -- 1.70pt
    # wide on c7_code where the real advance is 5.10pt. The remaining 3.401pt
    # surfaces as a gap to the next character, and downstream that gap is
    # indistinguishable from a producer who positioned words instead of emitting
    # a space: a SECOND space gets synthesised on top of the one already there,
    # giving `def··rerank` where PyMuPDF has `def·rerank`.
    #
    # It is worth exactly ONE space, though, and no more. Running it all the way
    # to the next character also closes the gap between two table cells that
    # happen to have a generated space in it, and _build_lines splits a row into
    # visual lines on precisely that gap (LINE_SPLIT_EM): measured, that fused
    # cells back into single lines and cost 01_whitepaper_market 130 lines -> 105
    # and 03_tech_report_code 73 -> 53. So the space is given one space advance,
    # capped at wherever the next character actually starts.
    for i, c in enumerate(out[:-1]):
        if not c.gen:
            continue
        nxt = out[i + 1]
        if abs(nxt.oy - c.oy) >= 0.5 or nxt.x0 <= c.x1:
            continue
        adv = (MONO_ADV_EM if c.mono_hint else SPACE_ADV_EM) * max(c.size, 1.0)
        c.x1 = min(nxt.x0, max(c.x1, c.x0 + adv))
    _restore_soft_hyphens(out)
    return out


def _restore_soft_hyphens(chars: List[_Char]) -> int:
    """Acrobat PDFMaker's end-of-line hyphen arrives as U+0002. Put it back.

    When a font gives PDFium no usable ToUnicode entry it returns the raw
    character code, and PDFMaker's soft hyphen is code 2. Downstream that is a
    control character: model.xml_safe_text has to drop it, so the hyphen was
    lost entirely and infer._soft_join then rejoined the wrapped word with a
    SPACE -- `SHA 512` where the reference reads `SHA-512`.

    The recovery is positional, because position is what identifies it.
    Measured over y10_nist_fips180, all 15 occurrences:

        font        Times New Roman, every one
        width       3.02pt, every one -- a hyphen's advance at this size
        x           536.5-539.8, every one: the right text edge
        neighbours  `A`->`5`, `A`->`2`, `w`->`b`, `t`->`m` -- the next
                    character always begins the following line

    So U+0002 is restored to U+002D only when it is the LAST character on its
    own baseline: nothing sits to its right on the same line. That is what makes
    it an end-of-line hyphen rather than a stray code, and it is the reading
    PyMuPDF gives for the same rows (`...SHA-384, SHA-`). A U+0002 anywhere else
    is left alone and dropped downstream, because nothing identifies what glyph
    it stood for.

    Deliberately not keyed on the font name: `Times New Roman` is this
    producer's body face, not a property of the defect.
    """
    restored = 0
    for i, c in enumerate(chars):
        if c.u != "\x02":
            continue
        if any(abs(o.oy - c.oy) < 0.5 and o.x0 >= c.x1 - 0.1 and o.u.strip()
               for o in chars[i + 1:i + 40]):
            continue                      # something follows it on this line
        c.u = "-"
        restored += 1
    return restored


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
    # A script is its own span even when it is set at the host's size: the
    # writer has to raise it, and a run cannot be half superscript.
    return (c.font, round(c.size, 2), c.color, bold, italic, mono, serif,
            getattr(c, "sup", False))


def _gutter_xs(exempted: List[float]) -> List[float]:
    """Gap positions that recur down a page: column gutters, not stretched space.

    The justification exemption below forgives ANY gap that follows a real
    space, without bound. On a dense multi-column booklet the producer emits a
    space at the end of every column line, so the exemption forgave the gutter
    too and joined column 2's prose to column 3's mid-sentence: measured on
    y13_irs_pub501, 947 of 4499 lines (21%) crossed a gutter against PyMuPDF's
    zero.

    No em-threshold separates them -- y13's gutters are 1.26em and
    01_whitepaper's legitimate justified gaps are 1.73em, so any threshold that
    caught the first would split the second. Repetition does separate them, and
    by a wide margin. Measured over the gated 16 and the booklets, exempted gaps
    clustered by x on each page:

        01_whitepaper   9 exemptions, all on page 3, every one at its own x
                        (534, 472, 443, 363, ...) -- largest cluster: 1
        every other gated fixture      exemption never fires at all
        y13_irs_pub501  620 exemptions; largest clusters 54, 27, 20, 20
        y12_irs_pub15   724 exemptions; largest clusters 22, 20, 19, 18

    A stretched word space lands wherever the line happens to break; a gutter is
    the same x on every line of the column. GUTTER_MIN_ROWS sits at 4 -- four
    times the largest legitimate cluster observed, and a quarter of the smallest
    structural one.
    """
    if len(exempted) < GUTTER_MIN_ROWS:
        return []
    clusters, cur = [], [sorted(exempted)[0]]
    for x in sorted(exempted)[1:]:
        if x - cur[-1] <= GUTTER_X_TOL:
            cur.append(x)
        else:
            clusters.append(cur)
            cur = [x]
    clusters.append(cur)
    return [sum(c) / len(c) for c in clusters if len(c) >= GUTTER_MIN_ROWS]


def _wide_gap_starts_visual_line(prev: _Char, current: _Char,
                                 fragment: List[_Char],
                                 gutters=()) -> bool:
    """Whether a same-baseline gap is a new visual line rather than justification.

    PDFium exposes literal spaces as ordinary characters.  A producer can then
    justify that same interword space by placing the following glyph far away.
    The wide-gap rule must not turn that one line into a staircase of one-word
    lines.  Generated spaces are different: PDFium inserts them at structural
    gaps too, including table cells, so they keep the ordinary split behaviour.

    A literal leading space has no preceding text in ``fragment`` and remains a
    split.  That preserves the existing indentation/table-cell behaviour rather
    than treating every whitespace-prefixed fragment as justified prose.
    """
    gap = current.x0 - prev.x1
    if gap <= LINE_SPLIT_EM * max(prev.size, current.size, 1.0):
        return False
    explicit_interword_space = not prev.gen and prev.u == " "
    fragment_has_text = any(not char.u.isspace() for char in fragment)
    if not (explicit_interword_space and fragment_has_text):
        return True
    # The exemption, bounded: it does not extend to a gap sitting on one of this
    # page's repeated gap positions. See _gutter_xs -- a stretched word space
    # lands wherever the line breaks, a gutter is the same x on every line.
    mid = (prev.x1 + current.x0) / 2
    return any(abs(mid - g) <= GUTTER_X_TOL for g in gutters)


def _marker_starts_visual_line(fragment: List[_Char], current: _Char) -> bool:
    """Whether `fragment` is a list marker and `current` begins its item text.

    A marker and its item are TWO lines sharing a baseline in the IR, because
    that is what PyMuPDF reports: on x03_lo_lists_nested it gives `1.` at
    x[64.90, 73.15] and `Establish the temporary layover` at x[82.90, 222.97],
    both on baseline 442.55, and infer._merge_list_markers is written against
    exactly that shape. PDFium reports one line, `1. Establish the temporary
    layover`, because the 9.75pt gap between them is under LINE_SPLIT_EM
    (1.10em = 12.1pt at this size) and the wide-gap rule never fires.

    This is a DIFFERENT question from the wide-gap rule and is kept separate
    from it. That one is about interword spacing -- whether a stretched space is
    justification or a structural break. This one is about a specific leading
    token: nothing splits here unless the text so far IS a marker.

    The gap must clear two bars, because either alone is too easy: it must be
    wider than an interword space (MARKER_GAP_EM; a space at this size is
    0.28em) and wide against the marker's own advance (MARKER_GAP_ADV), which
    is what separates `1.` + 9.75pt from an ordinary short first word followed
    by a space. `The depot replacement...` never reaches the vocabulary test at
    all, and a hanging-indent continuation line has no leading marker to match.

    Only ever fires at the START of a visual line: `fragment` is everything
    seen since the last split, so a `1.` mid-sentence is not a marker.
    """
    if not fragment:
        return False
    text = "".join(c.u for c in fragment).strip()
    if not text or len(text) > 5:
        return False
    if not (text in _MARKER_BULLETS or _MARKER_RE.match(text)):
        return False
    # Measure from the marker's INK, not from whatever trails it. PDFium
    # synthesises a space after `1.` and _page_chars gives it one space of
    # advance, so measuring from the fragment's end put the marker's own width
    # at 11.35pt instead of 8.25 and the gap at 6.65 instead of 9.75 -- and the
    # rule missed by a quarter of a point. The inked numbers are also the ones
    # PyMuPDF reports for the same row.
    inked = [c for c in fragment if not c.u.isspace()]
    if not inked:
        return False
    size = max(max(c.size for c in inked), current.size, 1.0)
    gap = current.x0 - inked[-1].x1
    advance = max(1.0, inked[-1].x1 - inked[0].x0)
    return gap > MARKER_GAP_EM * size and gap > MARKER_GAP_ADV * advance


def _row_span(row: List[_Char]):
    return min(c.x0 for c in row), max(c.x1 for c in row)


def _absorb_script_rows(vis_rows):
    """Put super/subscript fragments back on the line they belong to.

    A script sits on its own baseline, so baseline grouping gives it a line of
    its own. PDFium reports `A. Researcher` / `1` / `, B. Coauthor` as three
    lines where PyMuPDF reports one -- `A. Researcher1, B. Coauthor`, with the
    marker as an interior span carrying superscript=True. The IR contract is
    PyMuPDF's, and the cost of missing it is nowhere near the size of a marker.

    Measured on c2_paper2col, a two-column paper with three such markers:

      * each marker became its own Line and therefore its own TextBlock, so
        infer._merge_row_lines -- which already knows how to absorb a raised
        fragment -- never saw it: that pass merges lines *within* a block, and
        the marker was in a different one.
      * the `2` after the second author sorted into the RIGHT COLUMN, ahead of
        that column's real first paragraph, which then carried 111.0pt of
        space_before. The `3` split a two-line paragraph into three.
      * taking the marker out of its host line left the gap it used to occupy,
        and the space heuristic in _build_lines refilled it: `Researcher ,` and
        `terminality .` against PyMuPDF's `Researcher1,` and `terminality3.`,
        so the markers cost word recall as well as geometry.

    The rule is infer._merge_row_lines' script rule, applied one stage earlier:
    a fragment smaller than its host, whose baseline stays inside the host's em
    box, sitting against the host's text. Two structural guards are added,
    because this stage has evidence that stage does not:

      * a fragment may not join the row it was SPLIT FROM. Two visual lines that
        share a baseline were separated on purpose by LINE_SPLIT_EM -- the two
        halves of a two-column page, or the cells of a table row -- and
        absorbing one back would silently undo that.
      * a fragment left of the host's first character is refused. `Line.baseline`
        is the first span's origin, so a raised leading span would make the
        whole line report the script's baseline as its own.
    """
    rows = [(ri, row) for ri, row in vis_rows if row]
    absorbed = set()
    for i, (frag_ri, frag) in enumerate(rows):
        fsz = max(c.size for c in frag)
        fx0 = min(c.x0 for c in frag)
        fb = frag[0].oy
        best = None
        for j, (host_ri, host) in enumerate(rows):
            if j == i or j in absorbed or host_ri == frag_ri:
                continue
            hsz = max(c.size for c in host)
            if fsz >= SCRIPT_SIZE_FRAC * hsz:
                continue                      # same size: a real line
            dy = fb - host[0].oy
            if abs(dy) > SCRIPT_BASE_EM * hsz:
                continue                      # outside the em box
            hx0, hx1 = _row_span(host)
            if fx0 <= hx0 or fx0 > hx1 + SCRIPT_REACH_EM * hsz:
                continue                      # not adjacent, or would lead
            score = (max(0.0, fx0 - hx1), abs(dy))
            if best is None or score < best[0]:
                best = (score, j, hsz)
        if best is None:
            continue
        _, j, hsz = best
        host = rows[j][1]
        if fb < host[0].oy - SCRIPT_RAISE_EM * hsz:
            for c in frag:
                c.sup = True
        host.extend(frag)
        host.sort(key=lambda c: c.x0)
        absorbed.add(i)
    return [row for i, (_, row) in enumerate(rows) if i not in absorbed]


# --- vertical text -----------------------------------------------------------
# PDFium reports no writing direction, so rotated text arrives looking like
# ordinary horizontal text whose characters happen to be stacked. `_build_lines`
# groups by baseline, so a vertical run does not become one line -- it shatters
# into dozens of 1-4 character fragments sharing an x, with the characters
# interleaved into nonsense ('T', 'ihsp', 'ub', 'clia').
#
# Those fragments are body text as far as everything downstream is concerned,
# and the damage is not confined to their own garbled content. NIST SP 800-207
# prints a citation strip vertically in its left margin: under PDFium it became
# 2777 phantom body lines at x=17, which dragged the inferred left margin from
# 72.0 to 16.8 and so moved the body column over the margin band. The
# side-margin furniture guard keys on that column, so it stopped firing --
# 66 promotable margin shapes fell to 13, and y09 re-inflated from ~44 to ~80
# pages of emitted height.
#
# PyMuPDF reports `dir` and `parse.py` routes non-horizontal lines to
# `PageIR.rotated`. This restores the same IR contract from geometry alone:
# characters are in content-stream order, so a rotated run is a run whose
# advance between consecutive characters is vertical rather than horizontal.
VERT_MIN_CHARS = 8          # shorter runs are stacked punctuation, not a strip
VERT_MAX_DX_FRAC = 0.35     # a vertical advance barely moves x
VERT_MIN_DY_FRAC = 0.20     # ...and moves y by a real fraction of the size
VERT_MAX_DY_FRAC = 2.0      # ...but not by more than a plausible advance


def _split_vertical_runs(chars: List[_Char]):
    """(flow_chars, rotated_lines). Pull vertically-advancing runs out of flow.

    Deliberately conservative: a run must be at least VERT_MIN_CHARS long
    before it is taken out, so a couple of stacked glyphs inside ordinary text
    stay exactly where they were and no existing line changes shape.
    """
    n = len(chars)
    if n < VERT_MIN_CHARS:
        return chars, []
    vert = [False] * n
    for i in range(1, n):
        p, c = chars[i - 1], chars[i]
        size = max(1.0, p.size)
        dx, dy = abs(c.ox - p.ox), abs(c.oy - p.oy)
        if dx <= VERT_MAX_DX_FRAC * size and \
                VERT_MIN_DY_FRAC * size <= dy <= VERT_MAX_DY_FRAC * size:
            vert[i - 1] = vert[i] = True
    flow: List[_Char] = []
    rotated: List[Line] = []
    i = 0
    while i < n:
        if not vert[i]:
            flow.append(chars[i])
            i += 1
            continue
        j = i
        while j < n and vert[j]:
            j += 1
        run = chars[i:j]
        line = _vertical_line(run) if len(run) >= VERT_MIN_CHARS else None
        if line is None:
            flow.extend(run)
        else:
            rotated.append(line)
        i = j
    return flow, rotated


def _vertical_line(run: List[_Char]) -> Optional[Line]:
    """One out-of-flow Line for a vertical run, read in increasing y."""
    cs = sorted(run, key=lambda c: c.oy)
    text = xml_safe_text("".join(c.u for c in cs))
    if not text.strip():
        return None
    bb = (min(c.x0 for c in cs), min(c.y0 for c in cs),
          max(c.x1 for c in cs), max(c.y1 for c in cs))
    first = cs[0]
    span = Span(text=text, font=first.font, size=first.size, color=first.color,
                bold=False, italic=False, mono=first.mono_hint, serif=False,
                superscript=False, bbox=bb, origin=(first.ox, first.oy))
    return Line(spans=[span], bbox=bb, dir=(0.0, 1.0))


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

    # split each baseline row into visual lines at wide horizontal gaps.
    # The row index travels with the fragment so _absorb_script_rows can tell a
    # raised marker from the far side of a split it must not undo.
    # Two passes over the same rows. The first records every gap the
    # justification exemption forgives; the second re-decides with this page's
    # repeated gap positions in hand, so a column gutter splits and a stretched
    # word space still does not. Running the real decision function twice is
    # deliberate -- duplicating its conditions to "predict" them is how the two
    # copies drift apart.
    def _split_rows(gutters, record=None):
        out = []
        for ri, row in enumerate(rows):
            row.sort(key=lambda c: c.x0)
            part = [row[0]]
            started = False      # has this row already produced a fragment?
            for prev, c in zip(row, row[1:]):
                if record is not None and \
                        c.x0 - prev.x1 > LINE_SPLIT_EM * max(
                            prev.size, c.size, 1.0) and \
                        not _wide_gap_starts_visual_line(prev, c, part):
                    record.append((prev.x1 + c.x0) / 2)
                if _wide_gap_starts_visual_line(prev, c, part, gutters) or \
                        (not started and _marker_starts_visual_line(part, c)):
                    out.append((ri, part))
                    part = [c]
                    started = True
                else:
                    part.append(c)
            out.append((ri, part))
        return out

    exempted = []
    vis_rows = _split_rows((), record=exempted)
    gutters = _gutter_xs(exempted)
    if gutters:
        vis_rows = _split_rows(gutters)

    vis_rows = _absorb_script_rows(vis_rows)

    lines = []
    for row in vis_rows:
        if any(_is_rtl(c.u[:1] or " ") for c in row):
            row = _reorder_rtl(row)
        # PDFium synthesises a space at the end of a line, where the producer
        # merely stopped drawing. It is line-break decoration, not content, and
        # PyMuPDF does not report it: measured on 01_whitepaper_market, 25% of
        # lines differed from PyMuPDF's text by exactly one trailing space --
        # `|Tier·|` against `|Tier|`, `|•·|` against `|•|`. Dropped after any
        # RTL reordering, so "trailing" means the end of the logical text.
        while row and row[-1].u.isspace():
            row = row[:-1]
        if not row:
            continue
        spans, cur, cur_key = [], [], None
        for c in row:
            k = _style(c)
            gap = (c.x0 - cur[-1].x1) if cur else 0.0
            # A span ends where the STYLE ends. A gap does not end it: a gap
            # with the same style on both sides is a space the producer drew by
            # positioning, and the branch below turns it into one.
            #
            # This condition used to also split on `gap > SPAN_GAP_EM`, which
            # ran BEFORE the space-insertion branch and so consumed the gap
            # instead of bridging it. Measured on c7_code: 79 of 79 intra-line
            # span boundaries sat between spans of identical style, every one at
            # a 3.401pt gap -- exactly one space at that size -- giving 105 spans
            # for 26 lines where PyMuPDF gives 26. The text came out right and
            # reached the writer as four runs per line instead of one.
            #
            # Nothing is left unbounded by dropping it: _build_lines has already
            # split the LINE at LINE_SPLIT_EM (1.10em) further up, so every gap
            # still under consideration here is small enough for spaces to span.
            if cur and k != cur_key:
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
                adv = (MONO_ADV_EM if cur[-1].mono_hint else SPACE_ADV_EM) * max(c.size, 1.0)
                n_sp = int(round(gap / adv)) if adv > 0 else 1
                if cur[-1].u.isspace() or c.u.isspace():
                    # A space is already there, and in proportional text that is
                    # the whole answer however far the gap has been stretched.
                    # Justified text pulls its word gaps to 7.84pt at 9.5pt type
                    # on 02_research_paper and PyMuPDF still reports ONE space;
                    # adding to it gave `Speculative··decoding` on 22% of that
                    # document's lines and 12% of 01_whitepaper_market's,
                    # displacing every word after it along the line.
                    #
                    # Monospace keeps counting: there a run length is code
                    # indentation, and collapsing it once cost 19 unmatched
                    # words and 40pt of horizontal drift on a listing.
                    n_sp = n_sp if cur[-1].mono_hint else 0
                if n_sp >= 1:
                    cur[-1].u += " " * min(n_sp, 24)
            cur.append(c)
        if cur:
            spans.append((cur, cur_key))

        sp_objs = []
        for cs, key in spans:
            if not cs:
                continue
            font, size, color, bold, italic, mono, serif, sup = key
            # Sanitised here rather than in _page_chars: the glyph occupies real
            # advance width on the page, so it stays in the line's geometry even
            # though it carries no text. See model.xml_safe_text for why the
            # contract lives at the parser and not at the writer.
            text = xml_safe_text("".join(c.u for c in cs))
            if not text.strip() and not sp_objs:
                continue
            bb = (min(c.x0 for c in cs), min(c.y0 for c in cs),
                  max(c.x1 for c in cs), max(c.y1 for c in cs))
            sp_objs.append(Span(
                text=text, font=font, size=size, color=color, bold=bold,
                italic=italic, mono=mono, serif=serif, superscript=sup,
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


def _column_split(lines: List[Line]) -> List[float]:
    """Every genuine column gutter on this page, left to right.

    Deciding whether two lines that share a baseline belong together is the
    difference between a table row (join: they are cells) and a two-column page
    (do not join: they are separate flows). Width cannot decide it -- measured,
    a table's cell gaps run WIDER than a two-column gutter, so every single
    threshold fixes one document and breaks the other, and page-wide empty-band
    detection fails too because a full-width title sits across the gutter.

    Structure decides it. An N-column page splits into exactly N groups, all
    wide, at the same x positions, for most of its rows. A table row splits into
    several narrow cells at x positions that differ per table. So look for that
    shape and nothing else.

    This used to look only for N == 2 and return the single best gutter, which
    is why a three-column page came back with one gutter or none: on y06 -- two-
    and three-column throughout -- it found a gutter on 8 of 40 sampled pages,
    and on page 62 the one gutter it did find left a 99-line group still
    holding two interleaved columns, whose pitch reference then read 1.72pt.
    Unseparated columns interleave in reading order, consecutive lines stop
    overlapping horizontally, and every line becomes a block of its own.

    Two things keep the generalisation from lowering the evidence bar:

    * The width test still demands that EVERY member substantially fill its own
      column, which is what refuses a table. It is now written per column --
      `COLUMN_MEMBER_FRAC * content_w / N` -- because written against the whole
      page it was not one bar but N of them: half a column at N=2 and three
      quarters at N=3. At N=2 the expression is arithmetically the old
      `0.25 * content_w`, so a two-column page is judged exactly as before.

    * Rows are judged WITHIN their own arity, and only the arity that describes
      most of the page is believed. A two-line row can never dilute the
      evidence for a three-column reading, or the reverse -- which is what
      pooling them would do, and it would have lost gutters that the previous
      code found on pages carrying both shapes. When two-line rows dominate,
      this function sees exactly what it saw before, from exactly the same
      rows, against exactly the same threshold.
    """
    rows = {}
    for ln in lines:
        rows.setdefault(round(ln.baseline, 0), []).append(ln)
    span_lo = min(l.bbox[0] for l in lines)
    span_hi = max(l.bbox[2] for l in lines)
    content_w = max(1.0, span_hi - span_lo)

    by_arity = {}
    for _, row in rows.items():
        row.sort(key=lambda l: l.bbox[0])
        if not 2 <= len(row) <= COLUMN_MAX:
            continue
        # every member substantially fills its own column: columns are wide,
        # cells are not
        floor = COLUMN_MEMBER_FRAC * content_w / len(row)
        if any(l.bbox[2] - l.bbox[0] < floor for l in row):
            continue
        # every division a real gutter, not a word space
        if any(b.bbox[0] - a.bbox[2] < 6.0 for a, b in zip(row, row[1:])):
            continue
        slot = by_arity.setdefault(len(row), {"rows": 0, "votes": {}})
        slot["rows"] += 1
        for a, b in zip(row, row[1:]):
            bx = (a.bbox[2] + b.bbox[0]) / 2
            k = round(bx / 4.0)
            slot["votes"][k] = slot["votes"].get(k, 0) + 1

    # A row of K wide groups is positive evidence for K columns. A row with
    # FEWER is not evidence against them: it is a baseline on which one column
    # happens to be empty, and its midpoint is then a gutter that does not
    # exist. Measured on y06, whose three-column pages gutter at 216 and 396:
    # the two-line rows of page 6 vote 14-to-4 for 308, the midpoint of a
    # missing middle column, and that is the single gutter the previous code
    # returned there. So take the most specific reading the page can evidence
    # and fall back to the simpler one, rather than letting the more numerous
    # rows win.
    #
    # Corroborated independently: over the whole corpus only six pages have two
    # arities to choose between, and on those the higher-arity gutters are
    # crossed by fewer of the page's own lines than the lower-arity ones
    # (median 0.028 against 0.050, worst 0.189 against 0.310) -- the higher
    # reading is the one the text actually respects.
    for arity in sorted(by_arity, reverse=True):
        slot = by_arity[arity]
        if slot["rows"] < 3:
            continue
        # a gutter is consistent; a coincidence is not
        need = max(3, 0.6 * slot["rows"])
        kept = sorted(k for k, n in slot["votes"].items() if n >= need)
        if not kept:
            continue
        # One gutter can straddle two 4pt buckets. Collapse each run of
        # adjacent buckets to its best-supported member rather than emitting
        # both and cutting a column in half between them.
        runs, run = [], [kept[0]]
        for k in kept[1:]:
            if k - run[-1] <= 1:
                run.append(k)
            else:
                runs.append(run)
                run = [k]
        runs.append(run)
        # An N-column reading needs all N-1 of its gutters. A partial one would
        # cut some column in half and shatter it, which is the failure this
        # function exists to prevent.
        if len(runs) != arity - 1:
            continue
        return [max(r, key=lambda k: slot["votes"][k]) * 4.0 for r in runs]
    return []


def _projection_gutters(lines: List[Line]) -> List[float]:
    """Gutters from a whitespace profile, for pages whose baselines are silent.

    `_column_split` reads column structure off baselines that carry one line
    per column. That is strong evidence when it exists and no evidence at all
    when it does not: columns set on independent vertical grids never share a
    baseline, so nothing is ever proposed. Measured on y06, 91 of 126 pages
    returned nothing, and on those pages most baselines carry a single line.

    So look at the page from the other direction. Project every line onto the
    x axis as a SOLID interval -- the gaps between a line's own words are not
    white space in this sense and must not be able to open a corridor -- and
    look for x where almost nothing is drawn.

    Two things make that work where an earlier empty-band attempt failed, which
    the module has warned about since:

    * A line wider than GUTTER_SPAN_FRAC of the content is excluded. A
      full-width title crossing the gutter is not evidence that the gutter is
      absent; it is not evidence about columns at all. Excluding it is what
      stops one banner closing the corridor for the whole page.

    * The corridor is tolerant rather than empty. A strict white band is a
      page-wide AND, so a single stray line closes it -- measured, that missed
      31 of the 45 gutters the row model finds. Ground-truthed against those
      gutters and against the centre of every column they imply:

          real gutters      crossed by p50 0.008, p75 0.012 of body lines
          column centres    crossed by p50 0.304

      GUTTER_CROSS_FRAC = 0.02 sits above the gutters' p75 and fifteen times
      below the column centres' median.

    Stage 2's rules then apply unchanged: every band must be a real column by
    the same COLUMN_MEMBER_FRAC bar, no more than COLUMN_MAX bands, and an
    N-column reading needs all N-1 of its gutters or it is refused.

    Known limit, measured rather than assumed: a two-column TABLE whose cells
    are wide enough to pass the column bar reads as a two-column page. On a
    ten-page render check of y06 this was 1 of 6 proposals (page 3, whose
    "gutter" is the boundary of an IF-YOU/THEN-USE table). `_group_table_rows`
    runs after band assembly and is the rule that answers tables; this is the
    same documented cell-versus-column limit that x10 already carries, not a
    new one.
    """
    if len(lines) < 2 * GUTTER_MIN_LINES:
        return []
    lo = min(l.bbox[0] for l in lines)
    hi = max(l.bbox[2] for l in lines)
    content_w = max(1.0, hi - lo)
    body = [l for l in lines
            if (l.bbox[2] - l.bbox[0]) <= GUTTER_SPAN_FRAC * content_w]
    if len(body) < 2 * GUTTER_MIN_LINES:
        return []

    tol = GUTTER_CROSS_FRAC * len(body)
    n = int(content_w) + 1
    cover = [0] * n
    for l in body:
        a = max(0, int(l.bbox[0] - lo) + 1)
        b = min(n - 1, int(l.bbox[2] - lo) - 1)
        for i in range(a, b + 1):
            cover[i] += 1

    cands, run = [], None
    for i, c in enumerate(cover):
        if c <= tol:
            run = [i, i] if run is None else [run[0], i]
        elif run is not None:
            cands.append(run)
            run = None
    if run is not None:
        cands.append(run)

    gutters = []
    for a, b in cands:
        x0, x1 = lo + a, lo + b
        # 6.0 is the same width a row-evidenced gutter must clear
        if x1 - x0 < 6.0:
            continue
        # the page's own margins are not gutters
        if x0 <= lo + 0.5 or x1 >= hi - 0.5:
            continue
        gutters.append((x0 + x1) / 2.0)

    if not gutters or len(gutters) + 1 > COLUMN_MAX:
        return []
    edges = [lo] + gutters + [hi]
    floor = COLUMN_MEMBER_FRAC * content_w / (len(gutters) + 1)
    for a, b in zip(edges, edges[1:]):
        mem = [l for l in body
               if a - 0.5 <= (l.bbox[0] + l.bbox[2]) / 2 <= b + 0.5]
        if len(mem) < GUTTER_MIN_LINES:
            return []
        if max(l.bbox[2] for l in mem) - min(l.bbox[0] for l in mem) < floor:
            return []
    return gutters


def _build_blocks(lines: List[Line], page_w: float = 612.0) -> List[TextBlock]:
    """lines -> blocks, by vertical pitch and horizontal adjacency.

    On a multi-column page each column is blocked SEPARATELY. Blocking the page
    as one stream sorts the lines by baseline, which interleaves the columns --
    left line 1, right line 1, left line 2 -- so consecutive lines never
    overlap horizontally and every one becomes a block, and then a paragraph,
    of its own. Measured: 20 paragraphs holding 23 source lines where PyMuPDF
    had 16 holding 47, and 106pt of extra space_before, which cost a page.

    `_column_split` returns every gutter it can evidence, so a three-column
    page is assembled as three bands. It used to return at most one, and a
    three-column page then kept two of its columns interleaved inside a single
    band -- the same failure, one column narrower.
    """
    if not lines:
        return []
    # Baseline coincidence first, and it wins whenever it says anything: it is
    # the stronger evidence, and a page the row model already reads correctly
    # must not be able to move. The profile is a fallback for silence, not a
    # second opinion.
    cols = _column_split(lines) or _projection_gutters(lines)
    if cols:
        bands = [[] for _ in range(len(cols) + 1)]
        for l in lines:
            bands[_band_of((l.bbox[0] + l.bbox[2]) / 2, cols)].append(l)
        bands = [b for b in bands if b]
        if len(bands) > 1:
            out = []
            for b in bands:
                out += _build_blocks_one(b, cols)
            out.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
            return _group_table_rows(out)
    return _group_table_rows(_build_blocks_one(lines, cols))


def _band_of(centre: float, cols: List[float]) -> int:
    """Which column band an x-centre falls in. Boundaries belong to the LEFT
    band, which is the convention the two-column form used."""
    i = 0
    while i < len(cols) and centre > cols[i]:
        i += 1
    return i


def _group_table_rows(blocks: List[TextBlock]) -> List[TextBlock]:
    """Put the cells of a table row back in ONE block, from column repetition.

    BLOCK_SAME_ROW_EM cannot do this and the comment on it says why: measured
    over the corpus, the same-baseline gaps inside a table and the coincidental
    ones have identical distributions, so no width threshold separates them. A
    real table's gaps are far wider than 1.2em anyway -- x10's header row runs
    `Corridor` to `Q1` across 157pt, about 15em -- so every cell became its own
    block, and then its own paragraph.

    dialect._join_ruled_rows repairs this from the RULING LINES, which is the
    right evidence when there are any. x10's second table is borderless: 5 rows
    x 4 cells, no rules, so it stayed shattered. Measured on x10 under
    pdfium/gdocs/none/refine0, that was 40 paragraphs against PyMuPDF's 16,
    +2 pages, and -- because the harness's `word_recall` only counts a word
    found on the RIGHT page -- 0.4664 against the reference's 0.9963, while
    `doc_recall` stayed at 0.9851. Nothing was lost; it moved pages.

    What decides it here is repetition, not width: three or more consecutive
    multi-cell baselines whose cell x-starts land in the SAME columns are a
    table, and a coincidence is not repeated. This is the discriminator
    _column_split already uses in this module, applied to rows instead of pages,
    and the two-column guard is the same one: a baseline carrying exactly two
    lines that are both WIDE is a page split, not a table row, and is refused.

    Deliberately in the PDFium parser and not in dialect: this is one backend's
    grouping being normalised to the IR contract PyMuPDF already satisfies, and
    the same rule applied in the shared layer moved PyMuPDF's own blocks on
    02_research_paper -- a shipping-lane change for a backend that had nothing
    wrong with it.
    """
    if len(blocks) < 3:
        return blocks
    rows = {}
    for bi, b in enumerate(blocks):
        for ln in b.lines:
            if not ln.horizontal or not ln.spans or not ln.text.strip():
                continue
            key = next((k for k in rows if abs(ln.baseline - k) <= 1.5), None)
            rows.setdefault(key if key is not None else round(ln.baseline, 1),
                            []).append((bi, ln))
    multi = sorted((base, items) for base, items in rows.items() if len(items) >= 2)
    if len(multi) < TABLE_MIN_ROWS:
        return blocks

    bands, cur = [], [multi[0]]
    for prev, r in zip(multi, multi[1:]):
        if r[0] - prev[0] <= TABLE_ROW_PITCH_MAX:
            cur.append(r)
        else:
            bands.append(cur)
            cur = [r]
    bands.append(cur)

    host_of = {}
    for grp in bands:
        if len(grp) < TABLE_MIN_ROWS:
            continue
        lo = min(l.bbox[0] for _, items in grp for _, l in items)
        hi = max(l.bbox[2] for _, items in grp for _, l in items)
        width = max(1.0, hi - lo)

        def _page_split(items):
            """Two wide halves on one baseline are a page's columns, not cells.

            Checked PER ROW, not per band. Checked per band it missed the case
            that matters: on 02_research_paper a two-column prose line sits 46pt
            below a real 4-column table, close enough to join its band, and one
            such row among five never reaches a band-level majority. It was then
            grouped as though it were a table row -- which cost that document a
            page and took its candidate word_recall from 0.9586 to 0.8029, the
            very failure this rule exists to remove.
            """
            return len(items) == 2 and all(
                (l.bbox[2] - l.bbox[0]) > 0.25 * width for _, l in items)

        grp = [r for r in grp if not _page_split(r[1])]
        if len(grp) < TABLE_MIN_ROWS:
            continue
        xs = sorted(l.bbox[0] for _, items in grp for _, l in items)
        cols, need = [], max(TABLE_MIN_ROWS, 0.6 * len(grp))
        for x in xs:
            if cols and x - cols[-1][-1] <= TABLE_COL_TOL:
                cols[-1].append(x)
            else:
                cols.append([x])
        if sum(1 for c in cols if len(c) >= need) < 2:
            continue
        for _, items in grp:
            host = min(bi for bi, _ in items)
            for bi, ln in items:
                host_of[id(ln)] = host
    if not host_of:
        return blocks

    moved = {}
    for bi, b in enumerate(blocks):
        keep = []
        for ln in b.lines:
            host = host_of.get(id(ln))
            if host is None or host == bi:
                keep.append(ln)
            else:
                moved.setdefault(host, []).append(ln)
        b.lines = keep
    for host, lns in moved.items():
        blocks[host].lines.extend(lns)
    out = []
    for b in blocks:
        if not b.lines:
            continue
        b.lines.sort(key=lambda l: (round(l.baseline, 1), l.bbox[0]))
        bb = None
        for l in b.lines:
            bb = (l.bbox if bb is None else
                  (min(bb[0], l.bbox[0]), min(bb[1], l.bbox[1]),
                   max(bb[2], l.bbox[2]), max(bb[3], l.bbox[3])))
        b.bbox = bb
        out.append(b)
    out.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    return out


def _body_pitch(lines: List[Line]) -> float:
    """The pitch of ordinary body text: the 20th-percentile line gap.

    This is the reference the block-split test multiplies, and it used to be the
    MEDIAN gap. The median is biased upward by exactly the thing it is meant to
    exclude -- the gaps *between* blocks are in the sample, and so are a table's
    row pitches -- so on a page of paragraphs the tolerance grew until the
    paragraph boundary fitted inside it. Measured on c6_long: body pitch 15pt,
    paragraph boundaries 19.5-23.2pt, and median x 1.6 admitted anything up to
    ~24pt, fusing 72 of 201 lines into the wrong block.

    The 20th percentile approximates the tightest recurring pitch on the page,
    which is what body text sets, and is unmoved by however many wide gaps sit
    above it.

    Evidence for the choice, and for the factor (testkit/block_gaps.py, which
    labels 685 consecutive line pairs with PyMuPDF's own answer):

        gap <= median * 1.60   355/685 wrong     <- shipped before this
        gap <= p20    * 1.30   178/685
        gap <= p20    * 1.15   140/685           <- this
        gap <= p20    * 1.05   154/685
        per-page adaptive cut  322/682

    Note what that table also says: no fixed factor is *right*. Every document
    separates cleanly on its own, at its own ratio (1.00 to 1.24 across the
    corpus), and no single value serves all of them -- 140 of 685 stay wrong.
    A per-page adaptive cut was measured before being written and is worse.
    """
    gaps = sorted(b.baseline - a.baseline for a, b in zip(lines, lines[1:])
                  if 0 < b.baseline - a.baseline < 60)
    if not gaps:
        return 12.0
    return gaps[max(0, int(0.2 * len(gaps)) - 1)]


def _pitch_by_size(lines: List[Line]) -> dict:
    """Body pitch per type size, because a page can set more than one.

    The page-wide 20th percentile fixed the median's upward bias but inherited
    the same shape of error in the other direction: on c7_code the code
    listings run at an 11.25pt pitch, which drags the page percentile below the
    15.0pt pitch of the body text, and body paragraphs then split into one block
    per line. Measured, that is the whole of that document's remaining gap --
    3 boundary disagreements, all `pdfium SPLITS where PyMuPDF merges` at
    exactly gap=15.0.

    Text of one size shares one leading, so the reference is computed within
    each size and only falls back to the page when a size has too few samples
    to be worth trusting. This is not the sliding window that was tried and
    reverted: a window averages over whatever happens to be nearby, has no idea
    what it is averaging over, and cut `02_research_paper`'s paragraphs in half
    by mixing body text with heading leading. A size bucket is a property of the
    text itself rather than of the window, which is why it survives.
    """
    buckets = {}
    for a, b in zip(lines, lines[1:]):
        d = b.baseline - a.baseline
        if not (0 < d < 60):
            continue
        buckets.setdefault(round(_line_size(a), 1), []).append(d)
    out = {}
    for size, gaps in buckets.items():
        if len(gaps) < 3:
            continue
        gaps.sort()
        out[size] = gaps[max(0, int(0.2 * len(gaps)) - 1)]
    return out


def _pitch_reference(by_size: dict, typical: float, size: float,
                     columnar: bool = True) -> float:
    """The block-continuation reference for text of `size`, or a default.

    `_body_pitch` and `_pitch_by_size` both take the 20th percentile of the
    consecutive baseline deltas. That is the right statistic on a list of lines
    that is in reading order WITHIN one column, and the wrong one on a list
    where two columns interleave -- left line 1, right line 1, left line 2 --
    because half of those deltas are then the vertical offset between the
    columns rather than a line step, and they sit near zero. The percentile
    lands in that population and collapses, the gate `gap <= ref * 1.15`
    rejects every genuine line step, and each line becomes its own block.

    `_column_split` returns at most one gutter and under-detects, so this is
    reached often: on y06 it found a gutter on 8 of 40 sampled pages of a
    document that is two- and three-column throughout, and on its page 20 the
    reference came out 2.67pt for 10pt text whose true in-column pitch is
    11.50pt.

    So refuse the impossible answer rather than the specific cause. Measured
    over the whole corpus in place -- 3,291 (page, column-group, size) buckets
    carrying 105,000 lines -- ref/size is bimodal:

        healthy      1.10 .. 1.20em   57% of the line mass, the modal leading
                     0.69em           the tightest healthy case measured
        collapsed    0.00 .. 0.42em   the interleaved-column population

    The floor sits at 0.5em, inside that valley and below anything a
    typesetter sets: solid setting is 1.0em and even that is rare. On the
    GATED 16 the statistic leaves 0.422em..0.647em completely empty, so the
    floor has 0.078em of margin below and 0.147em above on the only corpus
    that authorises anything.

    Fallback order keeps real measurement ahead of the constant: a collapsed
    size bucket first tries the page-wide value, which is a different sample
    and often survives, and only then takes PITCH_DEFAULT_EM * size.

    This can only ever RAISE a reference, so it can only ever JOIN lines. It
    does not detect columns and does not pretend to.

    `columnar` is the firing condition, and it is a correction (task #40). The
    constant fallback is only taken on a page where a gutter was actually
    found. When the guard was written `_column_split` returned at most one
    gutter and usually none, so a collapsed reference on a page with no gutter
    was overwhelmingly an undetected column; the N-column split and the
    whitespace profile then made detection succeed, and what is left in the
    no-gutter population is no longer that.

    Measured over 4,132 firings: on the y family, which the guard was built
    for, 72% sit on pages where a gutter WAS found. On 02_research_paper, whose
    render regressed, 0% do -- and there the fallback was the bare constant
    100% of the time, because the page-wide value had collapsed too. Joining on
    that guess produced blocks that are geometrically right (two-line
    paragraph fragments, 74 -> 63 against a reference of 45) and a render that
    is worse: within2pt 0.6675 -> 0.5685 at candidate and 0.5685 -> 0.0178 at
    shipping. A guess good enough to improve the IR is not good enough to
    reflow the page.

    A page-wide measurement, when it survives, is still taken either way: that
    is a measurement rather than a guess, and it is what most of the gated
    corpus uses.
    """
    ref = by_size.get(round(size, 1), typical)
    if size <= 0 or ref >= PITCH_FLOOR_EM * size:
        return ref
    if typical >= PITCH_FLOOR_EM * size:
        return typical
    if not columnar:
        return ref
    return PITCH_DEFAULT_EM * size


def _build_blocks_one(lines: List[Line], col_xs) -> List[TextBlock]:
    if not lines:
        return []
    typical = _body_pitch(lines)
    by_size = _pitch_by_size(lines)

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
            if same and col_xs:
                lo = min(prev.bbox[2], ln.bbox[2])
                hi = max(prev.bbox[0], ln.bbox[0])
                same = not any(lo <= c <= hi for c in col_xs)
        else:
            ref = _pitch_reference(by_size, typical, _line_size(prev),
                                   columnar=bool(col_xs))
            same = (0 < gap <= ref * BLOCK_GAP_FACTOR) and overlap > 0
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


# A glyph the text page kept nothing of leaves a text page-object whose bounds
# have collapsed to a point: PDFium could not measure what it could not
# identify. Anything with real extent is ink we can see and therefore not this
# case, so the threshold is tight on purpose.
_DEGENERATE_EXTENT = 0.5


def _obj_text(obj, textpage) -> str:
    """The characters PDFium recovered for one text page-object, if any."""
    try:
        n = raw.FPDFTextObj_GetText(obj.raw, textpage, None, 0)
    except Exception:
        return ""
    if n <= 0:
        return ""
    buf = ctypes.create_string_buffer(n * 2)
    raw.FPDFTextObj_GetText(obj.raw, textpage,
                            ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort)), n)
    return buf.raw[:n * 2].decode("utf-16-le", "replace").rstrip("\x00")


def _page_undecoded(page, page_h, textpage) -> List[UndecodedGlyph]:
    """Text page-objects the text page dropped entirely.

    LibreOffice writes its list bullets as a symbol-font glyph that PDFium
    cannot map to any character: measured on x03_lo_lists_nested, the text page
    reports 1320 characters, none with U+0000 and none in the private-use area,
    while the page-object layer still shows the ten bullets as text objects with
    empty text and bounds collapsed to a point. PyMuPDF reports U+F0B7 for the
    same glyphs, which is why only one arm loses the lists.

    Recovering the *position* is all this can honestly do; deciding whether a
    position is a list marker is `dialect`'s job, and it refuses every mark it
    cannot corroborate. Empty text alone is not evidence of a lost glyph -- a
    producer also emits empty text objects for trailing whitespace -- so the
    collapsed bounds are required too, and even then the mark is only a
    candidate.
    """
    out = []
    tp_raw = getattr(textpage, "raw", textpage)
    for obj in page.get_objects():
        try:
            if raw.FPDFPageObj_GetType(obj.raw) != raw.FPDF_PAGEOBJ_TEXT:
                continue
        except Exception:
            continue
        if _obj_text(obj, tp_raw).strip():
            continue                      # decoded fine; already in the blocks
        l = ctypes.c_float(); b = ctypes.c_float()
        r_ = ctypes.c_float(); t = ctypes.c_float()
        if not raw.FPDFPageObj_GetBounds(obj.raw, ctypes.byref(l), ctypes.byref(b),
                                         ctypes.byref(r_), ctypes.byref(t)):
            continue
        if (float(r_.value) - float(l.value)) > _DEGENERATE_EXTENT or \
                (float(t.value) - float(b.value)) > _DEGENERATE_EXTENT:
            continue                      # has extent: visible ink, not this
        size = ctypes.c_float()
        try:
            raw.FPDFTextObj_GetFontSize(obj.raw, ctypes.byref(size))
        except Exception:
            pass
        fr = ctypes.c_uint(); fg = ctypes.c_uint()
        fb = ctypes.c_uint(); fa = ctypes.c_uint()
        try:
            raw.FPDFPageObj_GetFillColor(obj.raw, ctypes.byref(fr), ctypes.byref(fg),
                                         ctypes.byref(fb), ctypes.byref(fa))
        except Exception:
            pass
        out.append(UndecodedGlyph(
            origin=(float(l.value), page_h - float(t.value)),
            size=float(size.value) or 0.0,
            color=_hexcol(fr.value, fg.value, fb.value)))
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


def _link_uri(doc, link) -> Optional[str]:
    """The URI a link annotation activates, or None if it is not a URI link.

    A GoTo link has no action at all in this fixture -- it carries a bare
    /Dest -- so `FPDFLink_GetAction` returning NULL is an ordinary answer and
    not a failure. See parse_pdf on why GoTo stops here.
    """
    act = raw.FPDFLink_GetAction(link)
    if not act or raw.FPDFAction_GetType(act) != raw.PDFACTION_URI:
        return None
    need = raw.FPDFAction_GetURIPath(doc.raw, act, None, 0)
    if not need:
        return None
    buf = ctypes.create_string_buffer(need)
    raw.FPDFAction_GetURIPath(doc.raw, act, buf, need)
    return xml_safe_uri(buf.raw[:max(0, need - 1)].decode("utf-8", "replace"))


def _link_dest(doc, link) -> Optional[LinkDest]:
    """A GoTo link's target as a LinkDest, or None if it is not one.

    A destination reaches a link either directly (`/Dest`, which is what
    Chromium writes) or through a GoTo action (`/A << /S /GoTo /D ... >>`), so
    both are asked for. FPDFDest_GetLocationInPage reports the raw PDF number
    in bottom-up user space for BOTH spellings -- unlike PyMuPDF, which flips
    one and not the other (see parse._goto_dest) -- so a single flip here puts
    the two backends on the same number.

    `has_y` is honoured rather than assumed: a `/Fit` destination carries no
    point, and reporting y=0 for it would anchor every such link to the top of
    the page as though that were measured.
    """
    dest = raw.FPDFLink_GetDest(doc.raw, link)
    if not dest:
        act = raw.FPDFLink_GetAction(link)
        if act:
            dest = raw.FPDFAction_GetDest(doc.raw, act)
    if not dest:
        return None
    page_index = raw.FPDFDest_GetDestPageIndex(doc.raw, dest)
    if page_index < 0:
        return None
    has_x = ctypes.c_int(); has_y = ctypes.c_int(); has_z = ctypes.c_int()
    x = ctypes.c_float(); y = ctypes.c_float(); z = ctypes.c_float()
    if not raw.FPDFDest_GetLocationInPage(dest, ctypes.byref(has_x),
                                          ctypes.byref(has_y), ctypes.byref(has_z),
                                          ctypes.byref(x), ctypes.byref(y),
                                          ctypes.byref(z)):
        return None
    if not has_y.value:
        return None
    # The TARGET page's height, and read without loading the page: a link can
    # point at a page of a different size, and `doc[page_index]` would open a
    # second handle on a page this parser may already have open -- closing it
    # would invalidate the one in use, and not closing it leaks one per link.
    size = raw.FS_SIZEF()
    if not raw.FPDF_GetPageSizeByIndexF(doc.raw, page_index, ctypes.byref(size)):
        return None
    target_h = float(size.height)
    return LinkDest(page=int(page_index),
                    x=float(x.value) if has_x.value else 0.0,
                    y=target_h - float(y.value))


def _page_links(page, page_h, doc):
    """URI and GoTo link rectangles for a page, read from its LINK ANNOTATIONS.

    This used to call `FPDFLink_LoadWebLinks`, which does something else
    entirely: it scans the extracted TEXT for substrings that look like URLs.
    That finds a link only where the anchor text IS the URL, and invents one
    wherever prose happens to contain a URL the producer never linked.
    PyMuPDF's `page.get_links()` reads the page's /Annots array, and the IR
    contract is PyMuPDF's, so this reads the same array.

    Measured on c8_toc_links, whose page carries six /Link annotations -- three
    URI and three GoTo -- the weblink scan recovered ONE of the three URI
    links: `team@example.com`, the only one whose anchor text is the address
    itself. `the specification` -> https://example.com/spec and `RFC` ->
    https://example.com/rfc-2119 were invisible to it, because a text scan
    cannot see an annotation. Against PyMuPDF's three, that was 1/3, and the
    two it missed are the ordinary case: prose linked by a word.

    The rectangles agree with PyMuPDF's to the decimal once flipped into the
    IR's top-left origin, which is what lets the existing span-tagging loop in
    parse_pdf stay exactly as it was.

    `FPDFLink_Enumerate` walks the annotations without the caller owning a
    handle, so unlike the weblink set there is nothing here to leak or close.
    """
    links = []
    try:
        start = ctypes.c_int(0)
        link = raw.FPDF_LINK()
        while raw.FPDFLink_Enumerate(page.raw, ctypes.byref(start),
                                     ctypes.byref(link)):
            uri = _link_uri(doc, link)
            target = None if uri else _link_dest(doc, link)
            if not uri and target is None:
                continue
            r = raw.FS_RECTF()
            if not raw.FPDFLink_GetAnnotRect(link, ctypes.byref(r)):
                continue
            entry = {"bbox": (min(r.left, r.right), page_h - max(r.top, r.bottom),
                              max(r.left, r.right), page_h - min(r.top, r.bottom))}
            if uri:
                entry["uri"] = uri
            else:
                entry["dest"] = target
            links.append(entry)
    except Exception:
        pass
    return links


def parse_pdf(path: str, keep_image_data: bool = True) -> DocIR:
    """Parse a PDF into the backend-neutral IR.

    Every native handle is closed on the way out, in reverse order of acquisition.
    None of them was: a parity run over 16 documents ended with pypdfium2 printing
    "The following objects are still open and will now be closed" and listing the
    documents, pages and text pages this function had opened. Interpreter exit
    collected them, which is not a resource policy -- a worker process converting a
    queue would hold a native document per job until it died, and PDF documents are
    not small in MuPDF or PDFium.

    GoTo (internal) links are carried as `Span.dest` (model.LinkDest), in the
    IR's top-left origin, and the writer turns them into w:hyperlink w:anchor
    against a bookmark. `_link_dest` explains the one coordinate subtlety.
    """
    doc = pdfium.PdfDocument(path)
    try:
        meta = {}
        try:
            meta = {k.lower(): v
                    for k, v in (doc.get_metadata_dict() or {}).items()}
        except Exception:
            pass
        ir = DocIR(path=path, meta=meta)
        for pno in range(len(doc)):
            page = doc[pno]
            try:
                w, h = page.get_width(), page.get_height()
                pir = PageIR(number=pno + 1, width=w, height=h)
                pir.links = _page_links(page, h, doc)
                tp = page.get_textpage()
                try:
                    _flow, pir.rotated = _split_vertical_runs(_page_chars(tp, h))
                    lines = _build_lines(_flow)
                    # Needs the text page open: the question is precisely which
                    # objects it kept nothing of.
                    pir.undecoded = _page_undecoded(page, h, tp)
                finally:
                    tp.close()
                for sp in (s for l in lines for s in l.spans):
                    for lk in pir.links:
                        lb = lk["bbox"]
                        ov = (max(0, min(sp.bbox[2], lb[2]) - max(sp.bbox[0], lb[0])) *
                              max(0, min(sp.bbox[3], lb[3]) - max(sp.bbox[1], lb[1])))
                        if ov > 0.5 * max(1e-6, (sp.bbox[2] - sp.bbox[0]) *
                                          (sp.bbox[3] - sp.bbox[1])):
                            sp.link = lk.get("uri")
                            sp.dest = lk.get("dest")
                            break
                pir.blocks = _build_blocks(lines, w)
                pir.drawings = _page_paths(page, h)
                pir.images = _page_images(page, h, keep_image_data)
            finally:
                page.close()
            ir.pages.append(pir)
        return ir
    finally:
        doc.close()
