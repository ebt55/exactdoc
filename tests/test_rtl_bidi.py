"""Right-to-left text: logical order, paragraph direction, OOXML bidi (WP14).

Measured on the tranche-4 RTL documents (y47-y50: Word 365, Word 2016,
WeasyPrint), every one of which converted to roughly twice its pages:

  * the parser reversed RTL letters only, so punctuation, brackets and numbers
    stayed in visual order -- `.פעולות` for `פעולות.`, `2026 ،114` for the
    ILO's `114، 2026`, every `(` closed the wrong way;
  * PDFium's RTL word spaces arrive font-less and 1pt, one run each;
  * inference measured RTL paragraphs as Latin ones (a justified paragraph's
    ragged-LEFT last line read as ragged right, full-width lines as centred);
  * the writer declared no direction at all, and no complex-script size.

    python tests/test_rtl_bidi.py
"""
import io
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.parse_pdfium import (_Char, _build_lines,  # noqa: E402
                                   _visual_to_logical)
from exactdoc.model import Line, Span  # noqa: E402

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _char(u, x0, x1, size=10.0, font="ArialMT", baseline=100.0, gen=False):
    c = _Char()
    c.u = u
    c.x0, c.x1 = x0, x1
    c.y0, c.y1 = baseline - size, baseline
    c.ox, c.oy = x0, baseline
    c.size = size
    c.font = font
    c.flags = 0
    c.color = "#000000"
    c.gen = gen
    return c


def _visual(text, x0=10.0, adv=5.0, **kw):
    """Characters drawn left to right in exactly the order given."""
    return [_char(ch, x0 + i * adv, x0 + (i + 1) * adv, **kw)
            for i, ch in enumerate(text)]


def _logical(visual_text):
    row, rtl = _visual_to_logical(_visual(visual_text))
    return "".join(c.u for c in row), rtl


class VisualToLogical(unittest.TestCase):
    """The inverse of UAX #9 on what a page draws."""

    def test_pure_hebrew_word(self):
        self.assertEqual(_logical("םולש"), ("שלום", True))

    def test_punctuation_lands_at_the_logical_end(self):
        # drawn: full stop at the far left, comma left of the first word
        self.assertEqual(_logical(".םלוע ,םולש"), ("שלום, עולם.", True))

    def test_brackets_are_mirrored_back(self):
        # A logical `(` at the right of a parenthetical is DRAWN as `)`: the
        # page reads `(לארשיב)` left to right, its ToUnicode included.
        drawn = "(" + "בישראל"[::-1] + ") " + "רלוונטיים"[::-1]
        self.assertEqual(_logical(drawn), ("רלוונטיים (בישראל)", True))

    def test_a_number_keeps_its_own_order(self):
        self.assertEqual(_logical("ךרענ 2026 תנשב"), ("בשנת 2026 נערך", True))

    def test_two_numbers_stay_two_units(self):
        # y47's running head: `الدورة 114، 2026` is drawn `2026 ،114 ةرودلا`.
        self.assertEqual(_logical("2026 ،114 ةرودلا"),
                         ("الدورة 114، 2026", True))

    def test_latin_island_with_numbers_stays_whole(self):
        # W7: a number after Latin text is Latin, so `Volume 1, Issue 3` is
        # one left-to-right island inside the Hebrew sentence
        drawn = ("הכרה בנושאים פורצי דרך"[::-1] + " Volume 1, Issue 3 " +
                 "מתאפשרת דרך מענקי"[::-1])
        self.assertEqual(_logical(drawn), (
            "מתאפשרת דרך מענקי Volume 1, Issue 3 הכרה בנושאים פורצי דרך",
            True))

    def test_separators_inside_a_number(self):
        self.assertEqual(_logical("םיחנ 3.14 1,000 ןושאר"),
                         ("ראשון 1,000 3.14 נחים", True))

    def test_latin_line_with_an_embedded_hebrew_word(self):
        self.assertEqual(_logical("the word םולש here"),
                         ("the word שלום here", False))

    def test_latin_line_with_hebrew_around_a_number(self):
        self.assertEqual(_logical("please see םלוע 12 םולש at the end"),
                         ("please see שלום 12 עולם at the end", False))

    def test_base_direction_is_the_majority_of_strong_letters(self):
        # more Latin letters than Hebrew: the line reads left to right
        self.assertFalse(_logical("רשא ERC Volume יקנעמ")[1])
        self.assertTrue(_logical("רשא ERC יקנעמ")[1])

    def test_line_reread_at_its_paragraphs_direction(self):
        from exactdoc.parse_pdfium import relogical_spans
        sp = Span(text=".(Basiri, et al., 2014)", font="TimesNewRomanPSMT",
                  size=12.0, color="#000000", bold=False, italic=False,
                  mono=False, serif=True, superscript=False,
                  bbox=(10, 0, 120, 12), origin=(10, 12))
        out = relogical_spans([sp], was_rtl=False, want_rtl=True)
        self.assertEqual("".join(s.text for s in out), "(Basiri, et al., 2014).")
        # and back again
        back = relogical_spans(out, was_rtl=True, want_rtl=False)
        self.assertEqual("".join(s.text for s in back), ".(Basiri, et al., 2014)")

    def test_line_with_no_rtl_is_untouched(self):
        row = _visual("plain (text) 12")
        out, rtl = _visual_to_logical(list(row))
        self.assertFalse(rtl)
        self.assertEqual([id(c) for c in out], [id(c) for c in row])

    def test_combining_mark_follows_its_base(self):
        # shin 10-20 with a point drawn over it at 13-17, then lamed 20-26
        row = [_char("ל", 4.0, 10.0), _char("ש", 10.0, 20.0),
               _char("\u05b8", 13.0, 17.0)]
        out, rtl = _visual_to_logical(sorted(row, key=lambda c: c.x0))
        self.assertTrue(rtl)
        self.assertEqual("".join(c.u for c in out), "ש\u05b8ל")


class RtlLines(unittest.TestCase):
    def test_line_is_flagged_and_reads_logically(self):
        lines = _build_lines(_visual(".םלוע ,םולש"))
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].rtl)
        self.assertEqual(lines[0].text, "שלום, עולם.")
        # logical order: the first span is the rightmost
        self.assertGreaterEqual(lines[0].spans[0].bbox[2],
                                lines[0].spans[-1].bbox[2])

    def test_latin_line_is_not_flagged(self):
        self.assertFalse(_build_lines(_visual("plain text"))[0].rtl)

    def test_positioned_word_gap_becomes_a_space(self):
        # two Hebrew words 3pt apart with no space glyph (0.3em at 10pt):
        # every logical neighbour pair inside an RTL word measures a negative
        # gap, so only the visual pass can see this one.
        chars = _visual("םלוע", x0=10.0) + _visual("םולש", x0=33.0)
        self.assertEqual(_build_lines(chars)[0].text, "שלום עולם")

    def test_doubled_synthetic_space_is_dropped(self):
        # PDFium's generated space on top of a drawn one (y49 p2, `ERC`)
        heb = "אשר מבטאים"[::-1]
        x = 10.0 + 5.0 * len(heb)
        chars = (_visual(heb, x0=10.0) + [_char(" ", x, x + 3.0),
                                          _char(" ", x, x + 3.0, gen=True)]
                 + _visual("ERC", x0=x + 3.0))
        self.assertEqual(_build_lines(chars)[0].text, "ERC אשר מבטאים")


class ComplexScriptSpaces(unittest.TestCase):
    """Spaces that are not word breaks, in scripts whose glyphs stack or join."""

    def test_generated_space_on_top_of_a_devanagari_glyph_is_dropped(self):
        from exactdoc.parse_pdfium import _drop_inked_spaces
        # y54: `डेटा` -- ड, ट, the e-matra drawn after ट, a generated space
        # whose origin lies inside ट, then ा
        chars = [_char("ड", 335.6, 343.0), _char("ट", 342.5, 350.2),
                 _char("े", 337.4, 342.6), _char(" ", 342.6, 348.2, gen=True),
                 _char("ा", 349.0, 353.5)]
        chars[3].ox = 348.2
        self.assertEqual([c.u for c in _drop_inked_spaces(chars)],
                         ["ड", "ट", "े", "ा"])

    def test_space_stepping_back_behind_its_cluster_is_dropped(self):
        from exactdoc.parse_pdfium import _drop_inked_spaces
        # an /ActualText cluster `खि` followed by a space at the cluster origin
        chars = [_char("ख", 369.3, 376.0), _char("ि", 375.8, 382.3),
                 _char(" ", 382.3, 383.8, gen=True), _char("ल", 383.8, 393.5)]
        chars[2].ox = 369.3
        self.assertEqual("".join(c.u for c in _drop_inked_spaces(chars)), "खिल")

    def test_real_devanagari_word_space_stays(self):
        from exactdoc.parse_pdfium import _drop_inked_spaces
        chars = [_char("क", 322.2, 332.5), _char(" ", 332.5, 334.7, gen=True),
                 _char("ड", 335.6, 343.0)]
        chars[1].ox = 334.7
        self.assertEqual(len(_drop_inked_spaces(chars)), 3)

    def test_latin_generated_spaces_are_untouched(self):
        from exactdoc.parse_pdfium import _drop_inked_spaces
        chars = [_char("a", 10.0, 15.0), _char(" ", 15.0, 15.0, gen=True),
                 _char("b", 12.0, 17.0)]
        chars[1].ox = 13.0
        self.assertEqual(len(_drop_inked_spaces(chars)), 3)

    def test_space_inside_a_joined_arabic_word_is_dropped(self):
        # y47 p3: `وتكييف` drawn with a space glyph between the two yehs,
        # whose ink meets across it
        letters = "فييكتو"                 # visual order, left to right
        chars = []
        x = 10.0
        for ch in letters:
            c = _char(ch, x, x + 5.0)
            c.ix0, c.ix1 = x - 0.2, x + 5.2          # joined ink
            chars.append(c)
            x += 5.0
        sp = _char(" ", 14.0, 17.0)                  # between ف and ي
        chars.insert(1, sp)
        self.assertEqual(_build_lines(chars)[0].text, "وتكييف")

    def test_word_space_between_arabic_words_stays(self):
        a = [_char(ch, 10.0 + 5 * i, 15.0 + 5 * i) for i, ch in enumerate("يف")]
        b = [_char(ch, 28.0 + 5 * i, 33.0 + 5 * i) for i, ch in enumerate("ملاع")]
        for c in a + b:
            c.ix0, c.ix1 = c.x0 + 0.3, c.x1 - 0.3
        sp = _char(" ", 20.0, 28.0)
        self.assertEqual(_build_lines(a + [sp] + b)[0].text, "عالم في")


class RtlRows(unittest.TestCase):
    def test_reference_closing_an_rtl_line_joins_it(self):
        # a 7pt `8` raised at the LEFT end of a 12pt Arabic line (y47 p9)
        line = _visual("لاخدلا ةضفخنملا نادلبلا يف", x0=60.0, size=12.0,
                       baseline=152.2)
        ref = _char("8", 55.0, 59.0, size=7.9, baseline=148.1)
        lines = _build_lines(line + [ref])
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].text.endswith("8"))
        self.assertTrue(lines[0].text.startswith("في البلدان"))

    def test_arabic_mark_joins_its_letter(self):
        # a tanween drawn 1.4pt above its letter: one line, not two
        line = _visual("ايمسر", x0=60.0, size=12.0, baseline=300.0)
        mark = _char("ً", 61.0, 64.0, size=12.0, baseline=298.6)
        lines = _build_lines(line + [mark])
        self.assertEqual(len(lines), 1)
        # logical order, the mark after the alef it sits on
        self.assertEqual(lines[0].text, "رسمياً")


class RtlInferenceHelpers(unittest.TestCase):
    def test_hebrew_and_arabic_letter_ordinals(self):
        from exactdoc.infer import NUM_RE, _inline_marker
        self.assertTrue(NUM_RE.match("א."))
        self.assertTrue(NUM_RE.match("ب)"))
        self.assertEqual(_inline_marker("ב. מה תהיה יחידת התצפית")[1], {2})
        self.assertEqual(_inline_marker("ج. نص البند")[1], {3})   # abjad

    def test_brackets_balance_across_a_paragraph(self):
        from exactdoc.infer import _balance_brackets
        from exactdoc.layout import Run

        def runs(*texts):
            return [Run(text=t, font="ArialMT", size=11, color="#000000")
                    for t in texts]
        # y50: `(Liu, 2012)` read back as `)Liu, 2012)`
        r = runs("میپردازد ", ")Liu, 2012).")
        self.assertEqual(_balance_brackets(r), 1)
        self.assertEqual("".join(x.text for x in r), "میپردازد (Liu, 2012).")
        # a parenthetical opened on one line and closed on the next
        r = runs("CR-ERC. )להלן: ", "\"מחקר הבסיס\").")
        _balance_brackets(r)
        self.assertEqual("".join(x.text for x in r),
                         "CR-ERC. (להלן: \"מחקר הבסיס\").")
        # a pair read back the wrong way round: counts balance, shapes do not
        r = runs("ההטמעה )ראו להלן(, והצוות")
        self.assertEqual(_balance_brackets(r), 2)
        self.assertEqual(r[0].text, "ההטמעה (ראו להלן), והצוות")
        # balanced text and a lone list marker are left alone
        for t in ("רלוונטיים (בישראל: ועוד);", "1) פריט ראשון", "x (a) b)"):
            r = runs(t)
            self.assertEqual(_balance_brackets(r), 0, t)

    def test_visual_rtl_number_marker(self):
        from exactdoc.infer import _neutral_rtl_text
        self.assertEqual(_neutral_rtl_text(".2"), "2.")
        # mirrored glyphs read back: a logical `(12)` is drawn `(12)` too
        self.assertEqual(_neutral_rtl_text("(12)"), "(12)")
        self.assertEqual(_neutral_rtl_text("(3"), "3)")

    def test_complex_script_family(self):
        from exactdoc.fonts import complex_script_family
        self.assertEqual(complex_script_family("David,Bold"), "David")
        self.assertEqual(complex_script_family("BNazaninBold"), "BNazanin")
        self.assertEqual(complex_script_family("Microsoft-Sans-Serif"),
                         "Microsoft Sans Serif")
        self.assertIsNone(complex_script_family("ArialMT"))     # table knows it
        self.assertIsNone(complex_script_family("David", profile="gdocs"))
        # open faces whose PostScript names do not spell their family
        self.assertEqual(complex_script_family("DejaVuSans"), "DejaVu Sans")
        self.assertEqual(complex_script_family("NotoNaskh-Bold"),
                         "Noto Naskh Arabic")


def _rtl_line(x0, x1, y, text="שלום עולם זה טקסט", size=10.0):
    sp = Span(text=text, font="ArialMT", size=size, color="#000000",
              bold=False, italic=False, mono=False, serif=False,
              superscript=False, bbox=(x0, y - size, x1, y), origin=(x1, y))
    return Line(spans=[sp], bbox=(x0, y - size, x1, y), rtl=True)


class RtlParagraphGeometry(unittest.TestCase):
    """Alignment and indents come back in START/END terms."""

    def setUp(self):
        from exactdoc.infer import para_from_lines
        self.para = para_from_lines

    def test_justified_paragraph_with_ragged_left_last_line(self):
        lines = [_rtl_line(72, 540, 100), _rtl_line(72, 540, 114),
                 _rtl_line(72, 540, 128), _rtl_line(300, 540, 142)]
        p = self.para(lines, 72, 540)
        self.assertTrue(p.rtl)
        self.assertEqual(p.align, "justify")
        self.assertEqual((p.left_indent, p.right_indent, p.first_indent),
                         (0.0, 0.0, 0.0))

    def test_first_line_indent_is_on_the_right(self):
        lines = [_rtl_line(72, 522, 100), _rtl_line(72, 540, 114),
                 _rtl_line(72, 540, 128), _rtl_line(200, 540, 142)]
        p = self.para(lines, 72, 540)
        self.assertAlmostEqual(p.first_indent, 18.0, places=1)
        self.assertEqual(p.left_indent, 0.0)

    def test_start_indented_block(self):
        # every line ends 36pt in from the right margin: a start indent
        lines = [_rtl_line(150, 504, 100), _rtl_line(220, 504, 114)]
        p = self.para(lines, 72, 540)
        self.assertEqual(p.align, "left")       # start: flush right on the page
        self.assertAlmostEqual(p.left_indent, 36.0, places=1)

    def test_latin_paragraph_is_unchanged(self):
        lines = [_rtl_line(72, 540, 100), _rtl_line(72, 300, 114)]
        for ln in lines:
            ln.rtl = False
        p = self.para(lines, 72, 540)
        self.assertFalse(p.rtl)

    def test_short_line_between_full_ones_ends_the_paragraph(self):
        from exactdoc.infer import paras_from_line_list
        lines = [_rtl_line(72, 540, 100), _rtl_line(72, 540, 117.7),
                 _rtl_line(300, 540, 135.4),            # last line: ends short
                 _rtl_line(72, 540, 153.1), _rtl_line(200, 540, 170.8)]
        paras = paras_from_line_list(lines, 72, 540)
        self.assertEqual([p.src_lines for p in paras], [3, 2])

    def test_full_line_fragments_join_across_wide_leading(self):
        from exactdoc.infer import _merge_flow_paras
        # y49 p1: each 12pt body line its own block at a 17.7pt pitch
        frags = [self.para([_rtl_line(72, 540, y, size=12.0)], 72, 540)
                 for y in (100.0, 117.7, 135.4)]
        frags.append(self.para([_rtl_line(250, 540, 153.1, size=12.0)], 72, 540))
        merged = _merge_flow_paras(frags, 540, 72)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].src_lines, 4)
        self.assertEqual(merged[0].align, "justify")

    def test_fragment_ending_short_does_not_join(self):
        from exactdoc.infer import _merge_flow_paras
        frags = [self.para([_rtl_line(250, 540, 100.0, size=12.0)], 72, 540),
                 self.para([_rtl_line(72, 540, 117.7, size=12.0)], 72, 540)]
        self.assertEqual(len(_merge_flow_paras(frags, 540, 72)), 2)


class BidiMarkup(unittest.TestCase):
    """What the writer declares for a right-to-left paragraph and its runs."""

    def _write(self, paras, profile="standard"):
        from exactdoc.docxout import write_docx
        from exactdoc.layout import Chunk, DocLayout, PageLayout
        lay = DocLayout()
        lay.pages = [PageLayout(number=1, chunks=[Chunk(elements=paras)])]
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            write_docx(lay, path, output_profile=profile)
            with zipfile.ZipFile(path) as z:
                from lxml import etree
                return etree.fromstring(z.read("word/document.xml"))
        finally:
            os.unlink(path)

    def _para(self, text, rtl=True, bold=False):
        from exactdoc.layout import Para, Run
        return Para(runs=[Run(text=text, font="ArialMT", size=11.0,
                              color="#000000", bold=bold)],
                    align="left", rtl=rtl, leading=13.0)

    def test_rtl_paragraph_and_runs(self):
        from exactdoc.layout import Run
        p = self._para("שלום עולם, ", bold=True)
        p.runs.append(Run(text="ERC", font="ArialMT", size=11.0, color="#000000"))
        p.runs.append(Run(text=" 2026.", font="ArialMT", size=11.0,
                          color="#000000"))
        root = self._write([p])
        wp = next(e for e in root.iter(W + "p") if e.find(W + "pPr") is not None
                  and e.find(W + "pPr").find(W + "bidi") is not None)
        ppr = wp.find(W + "pPr")
        names = [c.tag.replace(W, "") for c in ppr]
        # schema order: bidi before spacing/ind/jc
        self.assertLess(names.index("bidi"), names.index("jc"))
        self.assertEqual(ppr.find(W + "jc").get(W + "val"), "left")   # = start
        runs = wp.findall(W + "r")
        he, latin, tail = runs
        rp = he.find(W + "rPr")
        self.assertIsNotNone(rp.find(W + "rtl"))
        self.assertIsNotNone(rp.find(W + "bCs"))
        self.assertEqual(rp.find(W + "szCs").get(W + "val"),
                         rp.find(W + "sz").get(W + "val"))
        self.assertEqual(rp.find(W + "lang").get(W + "bidi"), "he-IL")
        order = [c.tag.replace(W, "") for c in rp]
        self.assertEqual(order, sorted(order, key=lambda n: (
            ["rFonts", "b", "bCs", "i", "iCs", "color", "sz", "szCs", "rtl",
             "lang"].index(n) if n in ("rFonts", "b", "bCs", "i", "iCs",
                                       "color", "sz", "szCs", "rtl", "lang")
            else 99)))
        # Latin letters read left to right; the digits-and-punctuation tail of
        # an RTL paragraph reads right to left (Word resolves a run without
        # w:rtl as LTR text, which would move the full stop).
        self.assertIsNone(latin.find(W + "rPr").find(W + "rtl"))
        self.assertIsNotNone(tail.find(W + "rPr").find(W + "rtl"))

    def test_google_docs_profile_writes_real_bidi(self):
        # granted live 2026-10-04 (options.PROFILE_CAPABILITIES)
        root = self._write([self._para("שלום עולם.")], profile="gdocs")
        self.assertIsNotNone(root.find(".//" + W + "bidi"))

    def test_a_profile_without_bidi_writes_the_visual_equivalent(self):
        # no `bidi` capability: a left-to-right paragraph, sides swapped,
        # and no complex-script run properties at all
        from exactdoc import options as O
        p = self._para("שלום עולם.")
        p.left_indent = 36.0
        caps = O.PROFILE_CAPABILITIES["gdocs"]
        O.PROFILE_CAPABILITIES["gdocs"] = caps - {"bidi"}
        try:
            root = self._write([p], profile="gdocs")
        finally:
            O.PROFILE_CAPABILITIES["gdocs"] = caps
        for tag in ("bidi", "rtl", "szCs", "lang"):
            self.assertIsNone(root.find(".//" + W + tag), tag)
        wp = next(e for e in root.iter(W + "p")
                  if "".join(t.text or "" for t in e.iter(W + "t")))
        ppr = wp.find(W + "pPr")
        self.assertEqual(ppr.find(W + "jc").get(W + "val"), "right")
        ind = ppr.find(W + "ind")
        self.assertEqual(ind.get(W + "right"), "720")
        self.assertIsNone(ind.get(W + "left"))

    def test_latin_paragraph_is_byte_for_byte_what_it_was(self):
        root = self._write([self._para("plain text", rtl=False)])
        for tag in ("bidi", "rtl", "szCs", "bCs", "lang"):
            self.assertIsNone(root.find(".//" + W + tag), tag)

    def test_indic_run_gets_its_complex_script_size(self):
        root = self._write([self._para("भारत का अपना", rtl=False)])
        r = next(root.iter(W + "r"))
        self.assertEqual(r.find(W + "rPr").find(W + "szCs").get(W + "val"), "22")
        self.assertEqual(r.find(W + "rPr").find(W + "lang").get(W + "bidi"),
                         "hi-IN")
        self.assertIsNone(r.find(W + "rPr").find(W + "rtl"))


def _font_with_hebrew():
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                 r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(path):
            return path
    return None


try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:  # pragma: no cover
    _canvas = None


@unittest.skipIf(_canvas is None or _font_with_hebrew() is None,
                 "reportlab or a Hebrew-capable TrueType font is missing")
class EndToEnd(unittest.TestCase):
    """A synthetic PDF drawn the way Word draws Hebrew: glyphs placed right to
    left, each word's spaces separate, the paragraph justified to both
    margins with its last line flush right."""

    def _pdf(self):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        pdfmetrics.registerFont(TTFont("HebTest", _font_with_hebrew()))
        buf = io.BytesIO()
        c = canvas = _canvas.Canvas(buf, pagesize=(612, 792))
        canvas.setFont("HebTest", 11)
        words = ("איכות האחזור יורדת באופן לא ליניארי ככל שהקורפוס גדל מעבר "
                 "לנקודה שבה כויל מודל ההטמעה והצוות לא רואה זאת כי הוא "
                 "מודד רק ממוצעים של רלוונטיות בכל הרבעונים.").split()
        y, i = 700.0, 0
        sw = pdfmetrics.stringWidth(" ", "HebTest", 11)
        while i < len(words):
            x, line = 540.0, []
            while i < len(words):
                w = pdfmetrics.stringWidth(words[i], "HebTest", 11)
                if line and x - w - sw < 72:
                    break
                line.append(words[i])
                x -= w + sw
                i += 1
            last = i >= len(words)
            extra = 0.0 if last or len(line) < 2 else (x + sw - 72) / (len(line) - 1)
            x = 540.0
            for w_ in line:                      # right to left, word by word
                w = pdfmetrics.stringWidth(w_, "HebTest", 11)
                c.drawString(x - w, y, w_[::-1])  # visual order inside the word
                x -= w + sw + extra
            y -= 14.0
        c.save()
        return buf.getvalue()

    def test_parse_and_write(self):
        from exactdoc.convert import convert
        from exactdoc.parse_pdfium import parse_pdf
        d = tempfile.mkdtemp()
        src = os.path.join(d, "he.pdf")
        out = os.path.join(d, "he.docx")
        with open(src, "wb") as f:
            f.write(self._pdf())
        ir = parse_pdf(src)
        lines = [ln for b in ir.pages[0].blocks for ln in b.lines]
        self.assertTrue(all(ln.rtl for ln in lines))
        self.assertTrue(lines[0].text.startswith("איכות האחזור"))
        self.assertTrue(lines[-1].text.endswith("הרבעונים."))
        convert(src, out, refine_rounds=0, oracle="none")
        with zipfile.ZipFile(out) as z:
            from lxml import etree
            root = etree.fromstring(z.read("word/document.xml"))
        paras = [p for p in root.iter(W + "p")
                 if "".join(t.text or "" for t in p.iter(W + "t")).strip()]
        self.assertEqual(len(paras), 1)
        ppr = paras[0].find(W + "pPr")
        self.assertIsNotNone(ppr.find(W + "bidi"))
        self.assertEqual(ppr.find(W + "jc").get(W + "val"), "both")
        text = "".join(t.text or "" for t in paras[0].iter(W + "t"))
        self.assertTrue(text.startswith("איכות האחזור יורדת"))
        self.assertTrue(text.endswith("בכל הרבעונים."))


if __name__ == "__main__":
    unittest.main()
