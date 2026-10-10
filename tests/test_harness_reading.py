"""The harness reads source and render the same way (WP29, amendment 2).

Three things a PDF's text layer carries that are not the document's words
booked correctly converted text as missing: leader dots (y26_bash_reference,
2,243 of 3,027 unmatched source tokens), symbol-font private-use code points
(y10_nist_fips180's equations), and maths re-tokenised at different gaps
("( i - 1 )" in the source, "(i-1)" in the render). The normalisation is applied
to BOTH sides by the same function, so these tests pin it on synthetic pairs:
the pair reads as equal when only the drawing differs, and still reads as
different when text was actually lost. `normalise=False` is the old reading.

    python -m unittest tests.test_harness_reading
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import harness  # noqa: E402
import fitz  # noqa: E402


class _Page:
    """A page that answers get_text('words' | 'dict' | 'text'). It has no
    character layer ('rawdict' is empty), so its words keep their box tops."""

    def __init__(self, words, spans=(), text=None):
        self._w, self._spans, self._text = words, list(spans), text

    def get_textpage(self, **_kw):
        return None

    def get_text(self, kind, textpage=None):
        if kind == "words":
            return list(self._w)
        if kind == "rawdict":
            return {"blocks": []}
        if kind == "dict":
            return {"blocks": [{"lines": [{"spans": [
                {"bbox": b, "font": f, "text": t} for b, f, t in self._spans]}]}]}
        if kind == "text":
            return self._text if self._text is not None else \
                " ".join(w[4] for w in self._w)
        raise AssertionError(kind)


class _Doc(list):
    def close(self):
        pass


def _line(tokens, y=100.0, line=0, x=72.0, w=6.0):
    """fitz word tuples for `tokens` set left to right on one line."""
    out = []
    for i, t in enumerate(tokens):
        out.append((x, y, x + w * max(1, len(t)), y + 10.0, t, 0, line, i))
        x += w * max(1, len(t)) + 3.0
    return out


def _read(words, spans=(), normalise=True):
    with mock.patch.object(harness.fitz, "open",
                           return_value=_Doc([_Page(words, spans)])):
        return [w[0] for w in harness.page_words("x.pdf", normalise=normalise)[0]]


def _recall(src_words, out_words, normalise=True, src_spans=(), out_spans=()):
    pages = []
    for words, spans in ((src_words, src_spans), (out_words, out_spans)):
        with mock.patch.object(harness.fitz, "open",
                               return_value=_Doc([_Page(words, spans)])):
            pages.append(harness.page_words("x.pdf", normalise=normalise))
    return harness.doc_word_recall(*pages)


class Leaders(unittest.TestCase):
    def test_a_leader_run_is_not_words_on_either_side(self):
        src = _line(["Introduction"] + ["."] * 38 + ["1"])
        out = _line(["Introduction"] + ["."] * 31 + ["1"])
        self.assertEqual(_read(src), ["Introduction", "1"])
        self.assertEqual(_recall(src, out), 1.0)
        # the old reading booked the seven dots LibreOffice did not draw
        self.assertLess(_recall(src, out, normalise=False), 0.85)

    def test_lost_text_beside_a_leader_is_still_lost(self):
        src = _line(["Redirecting", "Input"] + ["."] * 20 + ["42"])
        out = _line(["Redirecting"] + ["."] * 25 + ["42"])
        self.assertAlmostEqual(_recall(src, out), 2 / 3, places=4)

    def test_one_or_two_dots_are_text(self):
        words = _line(["1.2", ".", "cd", "..", "end."])
        self.assertEqual(_read(words), ["1.2", ".", "cd", "..", "end."])

    def test_a_run_does_not_join_two_lines(self):
        words = _line(["a", ".", "."], line=0) + _line([".", "b"], y=120.0, line=1)
        self.assertEqual(_read(words), ["a", ".", ".", ".", "b"])

    def test_a_leader_glued_to_a_word_or_number_is_cut_off(self):
        words = _line(["Secrets.......", "......12", "etc.", "Bash?."])
        self.assertEqual(_read(words), ["Secrets", "12", "etc.", "Bash?."])

    def test_ellipsis_leaders(self):
        self.assertEqual(_read(_line(["Scope", "…", "…", "3"])),
                         ["Scope", "3"])
        self.assertEqual(_read(_line(["Scope", "………", "3"])),
                         ["Scope", "3"])
        # middle-dot leaders are dot leaders too
        self.assertEqual(_read(_line(["A"] + ["·"] * 5 + ["9"])), ["A", "9"])

    def test_hyphen_and_underscore_runs_are_content(self):
        words = _line(["Name", "_______", "-", "-", "-"])
        self.assertEqual(_read(words), ["Name", "_______", "-", "-", "-"])


class SymbolFonts(unittest.TestCase):
    def test_symbol_pua_reads_as_the_character_it_encodes(self):
        words = _line(["H", "", "a", "", "b", "", "c"])
        spans = [((0, 95, 600, 115), "ABCDEF+Symbol", "")]
        self.assertEqual(_read(words, spans),
                         ["H", "=", "a", "⊕", "b", "≤", "c"])
        self.assertEqual(_read(words, spans, normalise=False)[1], "")

    def test_the_font_decides_not_the_code(self):
        # 0x6C is lambda in Symbol, script l in MathType's MT Extra
        words = _line(["", "x", ""])
        spans = [((70, 95, 80, 115), "MTExtra", ""),
                 ((90, 95, 120, 115), "SymbolMT", "")]
        self.assertEqual(_read(words, spans), ["ℓ", "x", "λ"])

    def test_a_face_with_no_published_encoding_is_left_alone(self):
        words = _line(["", "item"])
        spans = [((0, 95, 600, 115), "LiberationSerif", "")]
        self.assertEqual(_read(words, spans), ["", "item"])

    def test_source_pua_matches_the_render_s_unicode(self):
        src = _line(["x", "", "y", "", "z"])
        spans = [((0, 95, 600, 115), "Symbol", "")]
        out = _line(["x", "+", "y", "=", "z"])
        self.assertEqual(_recall(src, out, src_spans=spans), 1.0)
        self.assertEqual(_recall(src, out, normalise=False, src_spans=spans), 0.6)


class Operators(unittest.TestCase):
    def test_maths_retokenised_at_other_gaps_still_matches(self):
        # FIPS 180: the source sets every glyph apart, the render runs them on
        src = _line(["H", "(", "i", "−", "1", ")", "=", "a", "+", "b"])
        out = _line(["H(", "i−1)", "=a+b"])
        self.assertEqual(_recall(src, out), 1.0)
        self.assertLess(_recall(src, out, normalise=False), 0.5)

    def test_pieces_share_the_token_box(self):
        words = [(100.0, 50.0, 140.0, 60.0, "f(x)", 0, 0, 0)]
        with mock.patch.object(harness.fitz, "open",
                               return_value=_Doc([_Page(words)])):
            got = harness.page_words("x.pdf")[0]
        self.assertEqual([g[0] for g in got], ["f", "(", "x", ")"])
        self.assertEqual([g[1] for g in got], [100.0, 110.0, 120.0, 130.0])
        self.assertEqual(got[-1][3], 140.0)

    def test_hyphens_commas_slashes_stay_inside_words(self):
        words = _line(["non-zero,", "and/or", "x86-64", "*note"])
        self.assertEqual(_read(words), ["non-zero,", "and/or", "x86-64", "*note"])

    def test_the_old_reading_is_unchanged(self):
        words = _line(["f(x)", "."] + ["."] * 5 + ["​", "end"])
        self.assertEqual(_read(words, normalise=False),
                         ["f(x)", ".", ".", ".", ".", ".", ".", "end"])


class RealPdfs(unittest.TestCase):
    """The same, through PyMuPDF on PDFs it wrote: word and character recall."""

    def _pdf(self, lines, path):
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        for i, text in enumerate(lines):
            page.insert_text((20, 30 + 14 * i), text, fontsize=10, fontname="helv")
        doc.save(path)
        doc.close()

    def test_contents_page_with_fewer_leader_dots(self):
        with tempfile.TemporaryDirectory() as td:
            src, out = os.path.join(td, "s.pdf"), os.path.join(td, "o.pdf")
            self._pdf(["Introduction " + ". " * 30 + "1",
                       "Definitions " + ". " * 31 + "3", "x = f(a+b)"], src)
            self._pdf(["Introduction " + ". " * 12 + "1",
                       "Definitions " + ". " * 13 + "3", "x=f(a + b)"], out)
            new = harness.word_metrics(src, out)
            old = harness.word_metrics(src, out, normalise=False)
            self.assertEqual(new["word_recall"], 1.0)
            self.assertEqual(new["doc_recall"], 1.0)
            self.assertLess(old["doc_recall"], 0.8)
            import quality_sweep as qs
            self.assertEqual(qs.char_recall(src, out), (1.0, 1.0))
            self.assertLess(qs.char_recall(src, out, normalise=False)[1], 0.8)

    def test_text_really_lost_still_counts(self):
        with tempfile.TemporaryDirectory() as td:
            src, out = os.path.join(td, "s.pdf"), os.path.join(td, "o.pdf")
            self._pdf(["Introduction " + ". " * 30 + "1", "Scope of work (draft)"], src)
            self._pdf(["Introduction " + ". " * 22 + "1", "Scope"], out)
            m = harness.word_metrics(src, out)
            # Introduction, 1, Scope matched; of, work, (, draft, ) lost
            self.assertAlmostEqual(m["doc_recall"], 3 / 8, places=4)


class RecallText(unittest.TestCase):
    def test_character_recall_reads_the_same_way(self):
        page = _Page([], spans=[((0, 0, 9, 9), "Symbol", "")],
                     text="Intro . . . . . 1\nx  y\n1.2 etc.\n")
        self.assertEqual(harness.recall_text(page), "Intro  1\nx = y\n1.2 etc.\n")
        self.assertEqual(harness.recall_text(page, normalise=False),
                         "Intro . . . . . 1\nx  y\n1.2 etc.\n")


if __name__ == "__main__":
    unittest.main()
