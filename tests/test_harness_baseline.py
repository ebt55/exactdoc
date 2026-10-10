"""Placement is read at the text baseline (amendment 3, 2026-10-10).

A word's box top is its baseline minus the font's ascent, and the ascent is
whatever the reader's copy of the font declares: PyMuPDF puts an unembedded
Helvetica's box top 1.075 em above the baseline and LibreOffice's Liberation
Sans (Docs' and Word's Arial too) 0.905 em, so every word of a base-14 source
read ~1.7pt low at 10pt although nothing moved. These tests pin the new reading
on synthetic PDFs: text of fonts with different ascents set on the same
baseline reads 0 drift, a real offset still reads as itself, a glued
superscript does not move its word, and `baseline=False` is the old reading.
Live text coverage reads leaders and symbol-font PUA the way `page_words` does,
and `rescore` re-reads it from the kept DOCX.

    python -m unittest tests.test_harness_baseline
"""
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import fitz  # noqa: E402
import harness  # noqa: E402

WORDS = (("Alpha", "Beta", "Gamma"), ("delta", "epsilon"), ("zeta", "eta", "theta"))


def _pdf(path, font="helv", size=20, shift=0.0, lines=WORDS):
    """Each word set at a fixed x on baselines 100, 140, 180 (+ shift)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    for i, line in enumerate(lines):
        for j, word in enumerate(line):
            page.insert_text((30 + 120 * j, 100 + 40 * i + shift), word,
                             fontsize=size, fontname=font)
    doc.save(path)
    doc.close()
    return path


class BaselineAnchor(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _p(self, name, **kw):
        return _pdf(os.path.join(self.td, name), **kw)

    def test_fonts_of_different_ascent_on_one_baseline_read_no_drift(self):
        # Helvetica's box top is 1.075 em above the baseline, Courier's 0.932:
        # 2.86pt apart at 20pt, with every glyph on the same baseline
        src = self._p("s.pdf", font="helv")
        out = self._p("o.pdf", font="cour")
        new = harness.word_metrics(src, out)
        self.assertEqual(new["word_recall"], 1.0)
        self.assertEqual(new["dy_p50"], 0.0)
        self.assertEqual(new["dy_p90"], 0.0)
        self.assertEqual(new["within2pt"], 1.0)
        # the box-top reading booked the ascent difference as drift
        old = harness.word_metrics(src, out, baseline=False)
        self.assertAlmostEqual(old["dy_p50"], 2.86, places=2)
        self.assertEqual(old["within2pt"], 0.0)
        self.assertEqual(old["word_recall"], new["word_recall"])

    def test_a_real_vertical_offset_is_still_read(self):
        src = self._p("s.pdf", font="helv")
        moved = self._p("o.pdf", font="cour", shift=3.0)
        new = harness.word_metrics(src, moved)
        self.assertEqual(new["dy_p50"], 3.0)
        self.assertEqual(new["within2pt"], 0.0)
        self.assertEqual(new["within5pt"], 1.0)
        # same font: both readings agree on a pure offset
        same = self._p("h.pdf", font="helv", shift=-2.5)
        self.assertEqual(harness.word_metrics(src, same)["dy_p50"], 2.5)
        self.assertEqual(harness.word_metrics(src, same, baseline=False)["dy_p50"], 2.5)

    def test_the_anchor_is_the_glyph_origin(self):
        words = harness.page_words(self._p("s.pdf"))[0]
        self.assertEqual(sorted({round(w[5], 3) for w in words}), [100.0, 140.0, 180.0])
        for w in words:                       # the box is unchanged
            self.assertLess(w[2], w[5])
            self.assertGreater(w[4], w[5])

    def test_baseline_false_is_the_old_reading_and_box_top_reproduces_it(self):
        src = self._p("s.pdf")
        old = harness.page_words(src, baseline=False)
        self.assertEqual(old, harness.box_top(harness.page_words(src)))
        self.assertTrue(all(w[5] == w[2] for w in old[0]))
        for normalise in (True, False):
            self.assertEqual(
                harness.page_words(src, normalise=normalise, baseline=False),
                harness.box_top(harness.page_words(src, normalise=normalise)))

    def test_a_glued_superscript_does_not_move_its_word(self):
        path = os.path.join(self.td, "sup.pdf")
        doc = fitz.open()
        page = doc.new_page(width=400, height=300)
        for y, base, sup in ((100, "E=mc", "2"), (150, "H", "(i)")):
            page.insert_text((50, y), base, fontsize=20, fontname="helv")
            dx = fitz.get_text_length(base, fontname="helv", fontsize=20)
            page.insert_text((50 + dx, y - 8), sup, fontsize=12, fontname="helv")
        doc.save(path)
        doc.close()
        got = {w[0]: w[5] for w in harness.page_words(path)[0]}
        # "H(i)": three of its four characters are raised; the word is not
        self.assertEqual(got["H"], 150.0)
        self.assertEqual(got["("], 150.0)
        self.assertEqual(got["mc2"], 100.0)

    def test_rotated_text_keeps_its_box_top(self):
        path = os.path.join(self.td, "rot.pdf")
        doc = fitz.open()
        page = doc.new_page(width=400, height=300)
        page.insert_text((200, 250), "Rotated words", fontsize=12, fontname="helv",
                         rotate=90)
        doc.save(path)
        doc.close()
        words = harness.page_words(path)[0]
        self.assertEqual(len(words), 2)
        self.assertTrue(all(w[5] == w[2] for w in words))

    def test_pairing_is_by_text_so_recall_never_moves(self):
        # equal words, one line each side, different fonts: as many pairs
        src = self._p("s.pdf", lines=(("a", "a", "b"), ("a", "b", "b")))
        out = self._p("o.pdf", font="cour", lines=(("a", "b"), ("a", "a", "b")))
        new = harness.word_metrics(src, out)
        old = harness.word_metrics(src, out, baseline=False)
        for k in ("src_words", "word_recall", "doc_recall"):
            self.assertEqual(new[k], old[k])
        self.assertEqual(new["word_recall"], round(5 / 6, 4))

    def test_a_bare_word_tuple_still_matches_at_its_box_top(self):
        src = [[("x", 10.0, 50.0, 20.0, 60.0)]]
        out = [[("x", 10.0, 51.0, 20.0, 61.0)]]
        drifts, matched, total = harness.match_words(src, out)
        self.assertEqual((matched, total), (1, 1))
        self.assertEqual(drifts[0][:2], (0.0, 1.0))


def _docx(path, paragraphs):
    """A minimal DOCX; each paragraph is [(text, font or None)] runs."""
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = []
    for runs in paragraphs:
        rs = []
        for text, font in runs:
            rpr = ('<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s"/></w:rPr>' % (font, font)
                   if font else "")
            rs.append('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, text))
        body.append("<w:p>%s</w:p>" % "".join(rs))
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (W, "".join(body)))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml.encode("utf-8"))
    return path


class LiveText(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _src(self, lines):
        path = os.path.join(self.td, "s.pdf")
        doc = fitz.open()
        page = doc.new_page(width=500, height=300)
        for i, text in enumerate(lines):
            page.insert_text((20, 40 + 16 * i), text, fontsize=10, fontname="helv")
        doc.save(path)
        doc.close()
        return path

    def test_a_contents_leader_is_not_text_on_either_side(self):
        src = self._src(["Introduction " + ". " * 30 + "1",
                         "Definitions " + ". " * 31 + "3"])
        # the DOCX draws its leaders as tab leaders: no dots in the live text
        docx = _docx(os.path.join(self.td, "tab.docx"),
                     [[("Introduction", None), ("1", None)],
                      [("Definitions", None), ("3", None)]])
        self.assertEqual(harness.live_text_cov(src, docx), 1.0)
        self.assertLess(harness.live_text_cov(src, docx, normalise=False), 0.5)
        # dots written as text are leaders too, and still not counted
        dots = _docx(os.path.join(self.td, "dots.docx"),
                     [[("Introduction ......... 1", None)],
                      [("Definitions", None), ("........", None), ("3", None)]])
        self.assertEqual(harness.live_text_cov(src, dots), 1.0)

    def test_text_really_missing_from_the_docx_still_counts(self):
        src = self._src(["Introduction " + ". " * 30 + "1",
                         "Scope of the work, in full detail"])
        docx = _docx(os.path.join(self.td, "d.docx"),
                     [[("Introduction", None), ("1", None)], [("Scope", None)]])
        # 16 of the 38 three-grams of "Introduction1Scopeofthework,infulldetail"
        self.assertEqual(harness.live_text_cov(src, docx), round(16 / 38, 4))

    def test_symbol_pua_in_a_run_reads_through_the_run_s_font(self):
        docx = _docx(os.path.join(self.td, "d.docx"),
                     [[("x ", None), ("", "Symbol"), (" y", None)]])
        live, _ = harness.docx_live_text(docx, normalise=True)
        # Symbol's 0x3D is "=", 0xB3 is the greater-or-equal sign; a PUA
        # character in an ordinary face has no published reading
        self.assertEqual(live, "\nx =≥ y")
        raw, _ = harness.docx_live_text(docx)
        self.assertEqual(raw, "x  y")

    def test_paragraphs_do_not_join_into_a_leader(self):
        docx = _docx(os.path.join(self.td, "d.docx"),
                     [[("and so on etc.", None)], [("..", None), (" cd up", None)]])
        live, _ = harness.docx_live_text(docx, normalise=True)
        self.assertEqual(harness.norm(live), "andsoonetc...cdup")


class Rescore(unittest.TestCase):
    """rescore re-reads placement at the baseline and live text from the DOCX,
    keeping the box-top / raw reading as the control."""

    def test_rescore_row(self):
        import rescore
        with tempfile.TemporaryDirectory() as td:
            src = _pdf(os.path.join(td, "s.pdf"), font="helv",
                       lines=(("Introduction", "1"),))
            out = _pdf(os.path.join(td, "o.pdf"), font="cour",
                       lines=(("Introduction", "1"),))
            # a source with a leader the DOCX does not carry as text
            doc = fitz.open(src)
            doc[0].insert_text((30, 200), "Scope . . . . . . 2", fontsize=10, fontname="helv")
            doc.save(os.path.join(td, "s2.pdf"))
            doc.close()
            src = os.path.join(td, "s2.pdf")
            docx = _docx(os.path.join(td, "d.docx"),
                         [[("Introduction", None), ("1", None)], [("Scope", None), ("2", None)]])
            row = {"document": "s2.pdf", "within2pt": 0.1, "dy_p50": 9.0,
                   "live_text_cov": 0.5, "word_recall": 0.2}
            new = rescore.rescore_row(row, src, out, docx)
            self.assertEqual(new["scorer"], "wp36")
            self.assertEqual(new["before"]["within2pt"], 0.1)
            self.assertEqual(new["dy_p50"], 0.0)
            self.assertEqual(new["control"]["within2pt"], 0.0)
            self.assertEqual(new["live_text_cov"], 1.0)
            self.assertLess(new["control"]["live_text_cov"], 1.0)
            self.assertNotIn("live_text_copied", new)
            kept = rescore.rescore_row(row, src, out, None)
            self.assertEqual(kept["live_text_cov"], 0.5)
            self.assertTrue(kept["live_text_copied"])


if __name__ == "__main__":
    unittest.main()
