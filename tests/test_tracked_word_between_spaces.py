"""A tracked word between drawn spaces stays one word (WP45).

Word sets y28_doe_oig_word365's running footer `1 | Page` with "Page" expanded
by 3pt: 12pt Arial, 0.248em after each letter, while the spaces around `|` are
drawn (0.278em). PDFium synthesises a space in every tracking gap; the run as a
whole (the header text shares its baseline) has a median gap of 0, and "Page"
alone is past the whole-run cap (0.24em), so the spaces stayed and the DOCX
wrote `P a g e`. A run holding drawn spaces is now also read word by word
between them, capped at its own drawn space's width; the word keeps its
tracking as w:spacing.

    python -m unittest tests.test_tracked_word_between_spaces
"""
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from exactdoc import parse_pdfium as P  # noqa: E402

SIZE = 12.0
ADV = {"P": 8.0, "a": 6.67, "g": 6.67, "e": 6.67, "1": 6.67, "|": 3.12,
       "A": 8.0, "B": 8.0, "C": 8.67, "D": 8.67, "x": 6.0}
SPACE = 3.34            # 12pt Arial's space: 0.278em


def _char(u, x0, x1, gen=False, font="ArialMT"):
    c = P._Char()
    c.u, c.x0, c.x1 = u, x0, x1
    c.y0, c.y1 = 690.0, 702.0
    c.ox, c.oy = x0, 700.0
    c.size, c.font, c.flags, c.color, c.gen = SIZE, font, 0, "#000000", gen
    return c


def _row(parts, x=480.0):
    """parts: (text, gap after each glyph, drawn space after the part?)."""
    out = []
    for text, gap, drawn in parts:
        for k, ch in enumerate(text):
            out.append(_char(ch, x, x + ADV[ch]))
            x += ADV[ch]
            if k < len(text) - 1 and gap:
                out.append(_char(" ", x, x + gap, gen=True))   # PDFium's
                x += gap
        if drawn:
            out.append(_char(" ", x, x + SPACE))                # the producer's
            x += SPACE
    return out


def _text(chars):
    return "".join(c.u for c in sorted(chars, key=lambda c: c.x0))


class TrackedWordBetweenSpaces(unittest.TestCase):
    def test_y28_footer_page_closes_up(self):
        row = _row([("1", 0, True), ("|", 0, True), ("Page", 2.976, False)])
        out = P._drop_tracking_spaces(row)
        self.assertEqual(_text(out), "1 | Page")
        page = [c for c in out if c.u in "Page"]
        self.assertTrue(all(c.tracked for c in page))
        self.assertAlmostEqual(page[0].track_em, 2.976 / SIZE, places=3)
        # and it is written with its tracking, not with spaces
        track, spaced = P._span_tracking(page)
        self.assertAlmostEqual(track, 2.976, places=2)
        self.assertFalse(spaced)

    def test_gaps_as_wide_as_the_drawn_space_stay_spaces(self):
        # letters set a full space apart, between drawn spaces: separate letters
        row = _row([("1", 0, True), ("ABCD", 3.4, False)])
        self.assertEqual(_text(P._drop_tracking_spaces(row)), "1 A B C D")

    def test_drawn_spaces_are_never_dropped(self):
        row = _row([("A", 0, True), ("B", 0, True), ("C", 0, True), ("D", 0, False)])
        self.assertEqual(_text(P._drop_tracking_spaces(row)), "A B C D")

    def test_a_run_without_drawn_spaces_keeps_the_old_cap(self):
        # TeX-style: no drawn spaces at all, gaps at 0.248em -- the whole-run
        # rule and its 0.24em cap decide, as before
        row = _row([("Page", 2.976, False)])
        self.assertEqual(_text(P._drop_tracking_spaces(row)), "P a g e")

    def test_short_or_non_alphabetic_stretches_are_left_alone(self):
        row = _row([("|", 0, True), ("xxx", 2.976, False)])       # 3 letters
        self.assertEqual(_text(P._drop_tracking_spaces(row)), "| x x x")
        # evenly spaced digits are a table's cells, not a tracked word
        digits = _row([("|", 0, True), ("1111", 2.976, False)])
        self.assertEqual(_text(P._drop_tracking_spaces(digits)), "| 1 1 1 1")

    def test_a_word_the_extractor_kept_whole_is_not_touched(self):
        # InDesign's justification letter-spaces a line (y60: 0.054-0.107em)
        # with no space synthesised inside a word: nothing to repair, and
        # marking it tracked would only move paragraph breaks
        row = []
        x = 480.0
        for k, ch in enumerate("ABCD"):
            row.append(_char(ch, x, x + ADV[ch]))
            x += ADV[ch] + 0.9                  # 0.075em, below a space
        row = _row([("1", 0, True)], x=400.0) + row
        out = P._drop_tracking_spaces(row)
        self.assertEqual(_text(out), "1 ABCD")
        self.assertFalse(any(c.track_em for c in out))

    def test_the_gap_reader_does_not_put_the_spaces_back(self):
        row = _row([("|", 0, True), ("Page", 2.976, False)])
        out = sorted(P._drop_tracking_spaces(row), key=lambda c: c.x0)
        p, a = out[2], out[3]
        self.assertEqual((p.u, a.u), ("P", "a"))
        self.assertEqual(P._gap_spaces(p, a), 0)
        # the same gap outside a tracked word is a space, as before
        p.track_em = a.track_em = 0.0
        self.assertEqual(P._gap_spaces(p, a), 1)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        import mupdf_extra
        if not mupdf_extra.AVAILABLE:
            raise unittest.SkipTest(mupdf_extra.REASON)

    def test_a_synthetic_footer_line_converts_to_Page_with_spacing(self):
        import fitz
        from exactdoc import convert
        from exactdoc import options as O
        with tempfile.TemporaryDirectory() as td:
            src, out = os.path.join(td, "s.pdf"), os.path.join(td, "o.docx")
            doc = fitz.open()
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 100), "An ordinary body line of text sits here.",
                             fontsize=12, fontname="helv")
            page.insert_text((72, 700), "12 | ", fontsize=12, fontname="helv")
            x = 72 + fitz.get_text_length("12 | ", fontname="helv", fontsize=12)
            for ch in "Page":
                page.insert_text((x, 700), ch, fontsize=12, fontname="helv")
                x += fitz.get_text_length(ch, fontname="helv", fontsize=12) + 2.976
            doc.save(src)
            doc.close()
            convert(src, out, options=O.RAW, max_pages=0)
            with zipfile.ZipFile(out) as z:
                xml = "".join(z.read(n).decode("utf-8") for n in z.namelist()
                              if n.startswith("word/") and n.endswith(".xml"))
            self.assertIn(">Page<", xml)
            self.assertNotIn("P a g e", xml)
            import re
            m = re.search(r'<w:spacing w:val="(\d+)"/></w:rPr><w:t>Page<', xml)
            self.assertIsNotNone(m)
            self.assertIn(int(m.group(1)), (59, 60))     # 2.976pt in twips


if __name__ == "__main__":
    unittest.main()
