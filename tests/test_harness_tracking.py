"""Letter-spaced source words read as the word they spell (amendment 5, 2026-10-10).

x17_resume_twocol's headings are Liberation Sans Bold 9.5pt with every glyph
followed by 1.39-1.92pt, and the text extractor breaks them where a gap looks
like a space: "S UM M ARY". The DOCX, Word and Docs say "SUMMARY". The harness
now joins a run whose glyph gaps -- inside the tokens and between them -- are
all tracking-sized and alike. These tests pin it on synthetic PDFs: a tracked
heading is one word, ordinary and justified word spacing in the same face is
not joined, and source and render are read alike.

    python -m unittest tests.test_harness_tracking
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import fitz  # noqa: E402
import harness  # noqa: E402

FONT, SIZE = "hebo", 9.5            # Helvetica-Bold, x17's heading size


def _tracked(page, x, y, word, gaps=(1.92, 1.39)):
    """Set `word` glyph by glyph, each followed by the next of `gaps` (x17's
    measured extremes, alternating) -- as a tracking producer draws it."""
    for k, ch in enumerate(word):
        page.insert_text((x, y), ch, fontsize=SIZE, fontname=FONT)
        x += fitz.get_text_length(ch, fontname=FONT, fontsize=SIZE) + gaps[k % len(gaps)]
    return x


def _words_at(page, x, y, words, gap):
    """Words set whole, `gap` pt apart."""
    for w in words:
        page.insert_text((x, y), w, fontsize=SIZE, fontname=FONT)
        x += fitz.get_text_length(w, fontname=FONT, fontsize=SIZE) + gap
    return x


class Tracking(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _pdf(self, name, draw):
        path = os.path.join(self.td, name)
        doc = fitz.open()
        page = doc.new_page(width=400, height=300)
        draw(page)
        doc.save(path)
        doc.close()
        return path

    def _read(self, path, **kw):
        return [w[0] for w in harness.page_words(path, **kw)[0]]

    def test_a_tracked_heading_reads_as_one_word(self):
        src = self._pdf("s.pdf", lambda p: _tracked(p, 40, 100, "SUMMARY"))
        old = self._read(src, tracked=False)
        self.assertGreater(len(old), 1)              # the extractor broke it
        self.assertEqual("".join(old), "SUMMARY")
        self.assertEqual(self._read(src), ["SUMMARY"])
        w = harness.page_words(src)[0][0]
        self.assertAlmostEqual(w[1], 40.0, places=2)  # the run's box
        self.assertEqual(w[5], 100.0)                 # and its baseline

    def test_ordinary_word_spacing_in_the_same_face_is_not_joined(self):
        def draw(p):
            p.insert_text((40, 100), "THE BIG RED CAT SAT", fontsize=SIZE, fontname=FONT)
            _words_at(p, 40, 130, ["A", "IS", "TO", "OK"], gap=2.64)   # one space
        src = self._pdf("s.pdf", draw)
        self.assertEqual(self._read(src), self._read(src, tracked=False))
        self.assertIn("THE", self._read(src))

    def test_justified_wide_spacing_is_not_joined(self):
        src = self._pdf("s.pdf", lambda p: _words_at(
            p, 40, 100, ["WIDE", "JUSTIFIED", "LINE", "OF", "WORDS"], gap=7.0))
        self.assertEqual(self._read(src),
                         ["WIDE", "JUSTIFIED", "LINE", "OF", "WORDS"])

    def test_a_heading_beside_ordinary_text_joins_alone(self):
        def draw(p):
            x = _tracked(p, 40, 100, "SKILLS")
            _words_at(p, x + 8.0, 100, ["Python", "and", "Rust"], gap=2.64)
        src = self._pdf("s.pdf", draw)
        self.assertEqual(self._read(src), ["SKILLS", "Python", "and", "Rust"])

    def test_source_and_render_are_read_alike(self):
        src = self._pdf("s.pdf", lambda p: (_tracked(p, 40, 100, "EXPERIENCE"),
                                            _tracked(p, 40, 140, "SUMMARY")))
        out = self._pdf("o.pdf", lambda p: (_words_at(p, 40, 100, ["EXPERIENCE"], 0),
                                            _words_at(p, 40, 140, ["SUMMARY"], 0)))
        self.assertEqual(harness.word_metrics(src, out)["word_recall"], 1.0)
        self.assertLess(harness.word_metrics(src, out, tracked=False)["word_recall"], 0.5)
        # a render that is letter-spaced itself reads the same way
        spaced = self._pdf("r.pdf", lambda p: (_tracked(p, 40, 100, "EXPERIENCE"),
                                               _tracked(p, 40, 140, "SUMMARY")))
        self.assertEqual(harness.word_metrics(spaced, out)["word_recall"], 1.0)

    def test_a_heading_split_into_single_letters_reads_as_one_word(self):
        # how LibreOffice and Word draw a w:spacing heading: every gap wide
        # enough for a synthesised space, so no token keeps two glyphs
        src = self._pdf("s.pdf", lambda p: _tracked(p, 40, 100, "SUMMARY", gaps=(2.2,)))
        self.assertEqual(self._read(src, tracked=False), list("SUMMARY"))
        self.assertEqual(self._read(src), ["SUMMARY"])
        # three letters are not evidence enough on their own
        few = self._pdf("f.pdf", lambda p: _tracked(p, 40, 100, "ABC", gaps=(2.2,)))
        self.assertEqual(self._read(few), ["A", "B", "C"])

    def test_a_space_the_producer_drew_is_a_word_space(self):
        # letters set apart by real space glyphs, the spaces narrowed (Docs'
        # export of x06's spaced Greek): not tracking, not joined
        def draw(p):
            tw = fitz.TextWriter(p.rect)
            font = fitz.Font("hebo")
            x = 40.0
            for ch in "S U M M A R Y":
                size = SIZE * 0.25 if ch == " " else SIZE     # a narrow drawn space
                tw.append((x, 100), ch, font=font, fontsize=size)
                x += font.text_length(ch, fontsize=size) + 0.3
            tw.write_text(p)
        src = self._pdf("s.pdf", draw)
        self.assertEqual(self._read(src), list("SUMMARY"))
        # the gaps alone are tracking-sized: only the drawn spaces keep it apart
        from unittest import mock
        real = harness._line_chars
        undrawn = lambda raw: {b: [ln[:5] + ([],) for ln in lines]
                               for b, lines in real(raw).items()}
        with mock.patch.object(harness, "_line_chars", undrawn):
            self.assertEqual(self._read(src), ["SUMMARY"])

    def test_maths_set_with_gaps_is_left_to_the_operator_split(self):
        src = self._pdf("s.pdf", lambda p: _words_at(p, 40, 100, ["n", "−1"], gap=1.6))
        self.assertEqual(self._read(src), self._read(src, tracked=False))


if __name__ == "__main__":
    unittest.main()
