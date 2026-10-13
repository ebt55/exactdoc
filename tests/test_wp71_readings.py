"""WP71: readings for holdout-3's short documents (development data since its
exam), each its own switch in `infer.WP71_RULES`, standard profile only.

  2. Right-tab fields a blank template sets (`infer._right_tab_fields`):
     fields that all say the same thing cannot start ragged; a banner centred
     across the page's middle and a list set two-up are neither fields nor
     column lines; one long field set beside the page's white is a field.
  3. A grid of pictures over short captions (`infer._picture_grid`): a
     letter's signature pages, one layout row per row of signers.
  1. A URL a line broke inside of, at the line's edge, joins with nothing
     (`infer._url_continues`).
  4. A small label in the margin heads the line it stands beside
     (`infer._margin_labels`); a full line indented on the left is not
     right-aligned unless a paragraph beside it is (`_settle_wide_right`).

    python -m unittest tests.test_wp71_readings
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from exactdoc import infer as I                                 # noqa: E402
from exactdoc.model import Line, Span                           # noqa: E402

L, R = 72.0, 540.0          # content box; w = 468, middle 306


def _line(text, x0, x1, base, size=10.5):
    s = Span(text=text, font="Times-Roman", size=size, color="#000000", bold=False,
             italic=False, mono=False, serif=True, superscript=False,
             bbox=(x0, base - 8.0, x1, base + 2.5), origin=(x0, base))
    return Line(spans=[s], bbox=s.bbox)


def _off(rule):
    old = I.WP71_RULES[rule]
    I.WP71_RULES[rule] = False
    return lambda: I.WP71_RULES.__setitem__(rule, old)


def _template(field="City, ST", fields=None, banner=False, two_up=False, wide=False):
    """Entries of a blank resume template: a title at the margin and the same
    placeholder field flush at the right on its baseline, empty bullets
    between."""
    out, base = [], 120.0
    if banner:
        out.append(_line("IMA BRONCO", 243.0, 369.0, base - 45))
        out.append(_line("SECTION HEADER", 255.0, 357.0, base - 30))
    if wide:
        out.append(_line("Boise State University", L, 224.0, base - 35))
        out.append(_line("Expected Graduation: Month Year", 385.0, R, base - 35))
    if two_up:
        for j in range(3):
            out.append(_line("●", 90.0, 97.0, base + 2 + 13 * j))
            out.append(_line("Class", 108.0, 134.0, base + 2 + 13 * j))
            out.append(_line("● Class", 342.0, 386.0, base + 2 + 13 * j))
        base += 45
    for i in range(4):
        t = fields[i] if fields else field
        out.append(_line("Title - Organization / Company", L, 233.0, base))
        out.append(_line(t, R - 6.0 * len(t), R, base))
        for j in range(3):
            out.append(_line("●", 90.0, 97.0, base + 16 + 13 * j))
        base += 70
    return out


class IdenticalFields(unittest.TestCase):
    def test_fields_that_say_the_same_thing_are_a_tab(self):
        self.assertAlmostEqual(I._right_tab_fields(_template(), L, R), R)

    def test_switched_off_they_are_refused_as_before(self):
        self.addCleanup(_off("tab_fields_same_text"))
        self.assertIsNone(I._right_tab_fields(_template(), L, R))

    def test_a_flush_left_list_of_different_words_is_still_refused(self):
        # a skills list in a right-hand column: every item starts at one x
        items = ["Python", "Java", "Docker", "SQL"]
        lines = _template(fields=items)
        for l, t in zip([l for l in lines if l.text in items], items):
            l.spans[0].bbox = l.bbox = (430.0, l.bbox[1], 430.0 + 6.0 * len(t) + 60, l.bbox[3])
        self.assertIsNone(I._right_tab_fields(lines, L, R))

    def test_the_gdocs_profile_is_untouched(self):
        tok = I._TAB_LAYOUTS.set(False)
        try:
            self.assertIsNone(I._right_tab_fields(_template(), L, R))
        finally:
            I._TAB_LAYOUTS.reset(tok)


class BannersTwoUpAndWideFields(unittest.TestCase):
    def test_a_centred_banner_is_no_field(self):
        lines = _template(field="Semester Year", banner=True)
        self.assertAlmostEqual(I._right_tab_fields(lines, L, R), R)
        self.addCleanup(_off("tab_fields_not_banner"))
        self.assertIsNone(I._right_tab_fields(lines, L, R))

    def test_a_line_wholly_right_of_the_middle_is_not_excluded(self):
        lines = _template(field="Semester Year", banner=True)
        for b in lines[:2]:
            b.spans[0].bbox = b.bbox = (330.0, b.bbox[1], 432.0, b.bbox[3])
            self.assertFalse(b.bbox[0] < 306.0 <= b.bbox[2])
        self.assertIsNone(I._right_tab_fields(lines, L, R))

    def test_a_two_up_list_is_no_field(self):
        lines = _template(field="Semester Year", two_up=True)
        self.assertAlmostEqual(I._right_tab_fields(lines, L, R), R)
        self.addCleanup(_off("tab_fields_two_up"))
        self.assertIsNone(I._right_tab_fields(lines, L, R))

    def test_one_long_field_beside_white_is_a_field(self):
        lines = _template(field="Semester Year", wide=True)
        self.assertAlmostEqual(I._right_tab_fields(lines, L, R), R)
        self.addCleanup(_off("tab_fields_wide_field"))
        self.assertIsNone(I._right_tab_fields(lines, L, R))

    def test_a_long_line_its_neighbour_runs_up_to_is_not(self):
        lines = _template(field="Semester Year", wide=True)
        lines[0].spans[0].bbox = lines[0].bbox = (L, lines[0].bbox[1], 370.0, lines[0].bbox[3])
        self.assertIsNone(I._right_tab_fields(lines, L, R))


# --------------------------------------------------------- 3. picture grid
def _pic(x0, y0, w=140.0, h=40.0):
    from exactdoc.layout import ImageEl
    e = ImageEl(data=b"", ext="png", width=w, height=h)
    e._bbox = (x0, y0, x0 + w, y0 + h)
    return ("el", e._bbox, e)


def _blk(lines):
    b = I._mk_block(lines)
    return ("blk", b.bbox, b)


def _signatures(rows=4, caption=2, sizes=None, extra=None):
    """A letter's signature page: two signers to a row, a signature picture
    over each signer's name and title."""
    items = []
    for r in range(rows):
        y = 90.0 + 92.0 * r
        lines = []
        for c, x in enumerate((42.0, 402.0)):
            w = sizes[(2 * r + c) % len(sizes)] if sizes else 140.0
            items.append(_pic(x, y, w))
            for k in range(caption):
                t = ("Signer %d%s" % (r, "ab"[c])) if k == 0 else "Member of Congress"
                lines.append(_line(t, x, x + 100.0, y + 52.0 + 15.0 * k))
        items.append(_blk(lines))
    if extra:
        items.append(_blk([extra]))
    return items


class PictureGrid(unittest.TestCase):
    def test_signatures_are_a_grid(self):
        g = I._picture_grid(_signatures())
        self.assertIsNotNone(g)
        rows = g[0]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(len(r) == 2 for r in rows))
        # the two names of a row are two cells, not one line
        self.assertEqual([l.text for l in rows[0][0][1]], ["Signer 0a", "Member of Congress"])
        self.assertEqual([l.text for l in rows[0][1][1]], ["Signer 0b", "Member of Congress"])

    def test_icons_beside_paragraphs_are_not(self):
        # a brochure's icon over a paragraph of four lines and more
        self.assertIsNone(I._picture_grid(_signatures(caption=4)))

    def test_pictures_of_different_sizes_are_not(self):
        self.assertIsNone(I._picture_grid(_signatures(sizes=[140.0, 60.0])))

    def test_other_text_in_the_band_is_not(self):
        self.assertIsNone(I._picture_grid(_signatures(
            extra=_line("A note set across the grid", 200.0, 380.0, 200.0))))

    def test_two_rows_are_not(self):
        self.assertIsNone(I._picture_grid(_signatures(rows=2)))

    def test_a_caption_line_keeps_its_break(self):
        from exactdoc.layout import Para, Run
        q = Para(runs=[Run(text="Signer 0a Member of Congress", font="Arial", size=10.0,
                           color="#000000")], align="justify", right_indent=220.0)
        I._caption_lines(q, ["Signer 0a", "Member of Congress"])
        self.assertEqual(q.text, "Signer 0a" + chr(10) + "Member of Congress")
        self.assertTrue(q.line_breaks)
        self.assertEqual((q.align, q.right_indent), ("left", 0.0))


# ------------------------------------------- 4. small labels, wide lines
def _sized(text, x0, x1, base, size):
    s = Span(text=text, font="Arial", size=size, color="#000000", bold=False,
             italic=False, mono=False, serif=False, superscript=False,
             bbox=(x0, base - 0.8 * size, x0 + (x1 - x0), base + 0.25 * size),
             origin=(x0, base))
    return Line(spans=[s], bbox=s.bbox)


def _memo_head(label_base_shift=2.2, label_size=6.0):
    blocks = []
    for k, (lab, val) in enumerate((("DATE", "September 9, 2025"), ("TO", "Mark Swann"),
                                    ("SUBJECT", "Prioritized Suggestions"))):
        base = 155.0 + 24.0 * k
        blocks.append(I._mk_block([_sized(val, 72.9, 175.0, base, 12.0)]))
        blocks.append(I._mk_block([_sized(lab, 67.1 - 4.0 * len(lab), 67.1,
                                          base - label_base_shift, label_size)]))
    return blocks


class MarginLabels(unittest.TestCase):
    def test_a_small_label_heads_its_line(self):
        out = I._merge_list_markers(_memo_head())
        texts = [l.text for b in out for l in b.lines]
        self.assertEqual(len(texts), 3)
        self.assertTrue(texts[0].startswith("DATE") and "September" in texts[0])
        ln = out[0].lines[0]
        self.assertEqual(I._marker_split_idx(ln.spans), 0)

    def test_switched_off_they_stay_apart(self):
        self.addCleanup(_off("margin_labels"))
        self.assertEqual(len([l for b in I._merge_list_markers(_memo_head()) for l in b.lines]), 6)

    def test_a_label_a_line_off_its_row_is_not(self):
        # 6pt lines stacked: the baselines differ by more than 0.45 of a pitch
        out = I._merge_list_markers(_memo_head(label_base_shift=6.0))
        self.assertEqual(len([l for b in out for l in b.lines]), 6)

    def test_a_lone_glyph_is_not_a_label(self):
        blocks = _memo_head()
        blocks[1].lines[0].spans[0].text = chr(0x2032)
        out = I._merge_list_markers(blocks)
        self.assertEqual(len([l for b in out for l in b.lines]), 5)

    def test_text_the_same_size_is_not_a_label(self):
        out = I._merge_list_markers(_memo_head(label_size=12.0))
        self.assertEqual(len([l for b in out for l in b.lines]), 6)


class WideLinesAreNotRightAligned(unittest.TestCase):
    def _para(self, x0, x1):
        return I.para_from_lines([_sized("Fire Department Staffing Models: Evaluate whether",
                                         x0, x1, 326.0, 12.0)], 72.0, 540.0)

    def test_a_full_line_indented_on_the_left_is_left(self):
        p = self._para(108.0, 540.0)
        self.assertEqual(p.align, "right")      # settled with its neighbours
        I._settle_wide_right([p])
        self.assertEqual(p.align, "left")

    def test_beside_a_flush_right_paragraph_it_stays_right(self):
        p = self._para(108.0, 540.0)
        q = self._para(400.0, 540.0)
        self.assertEqual(q.align, "right")
        I._settle_wide_right([q, p])
        self.assertEqual(p.align, "right")

    def test_a_short_flush_right_line_is_right(self):
        p = self._para(400.0, 540.0)
        I._settle_wide_right([p])
        self.assertEqual(p.align, "right")


# ------------------------------------------------ 1. a URL broken at the edge
def _join(last, nxt, at_edge=True, line_text=None):
    from exactdoc.layout import Run
    runs = [Run(text=last, font="Arial", size=10.0, color="#000000")]
    I._soft_join(runs, nxt, dehyphenate=False, at_edge=at_edge, line_text=line_text)
    return runs[0].text


class UrlJoin(unittest.TestCase):
    def test_a_url_broken_at_the_edge_joins_with_nothing(self):
        self.assertEqual(_join("see https://example.org/courses/", "1595954/files"),
                         "see https://example.org/courses/")

    def test_short_of_the_edge_it_keeps_its_space(self):
        self.assertEqual(_join("see https://example.org/courses/", "1595954/files",
                               at_edge=False), "see https://example.org/courses/ ")

    def test_prose_keeps_its_space(self):
        self.assertEqual(_join("the department generally", "implemented it"),
                         "the department generally ")

    def test_a_token_wider_than_the_measure_joins(self):
        tok = "dib=eyJ2IjoiMSJ9.pv3kvhQSwJK2b5HjBZ46GDupAPfIF1CN687FFpEtNRTBQcPiAKFvj8c"
        self.assertEqual(_join(tok, "cFofX-uonK8dmlv", line_text=tok), tok)

    def test_figures_stacked_in_a_cell_keep_their_space(self):
        self.assertEqual(_join("695,200", "7,176,500", line_text="695,200"), "695,200 ")
        bullet = chr(0x25CF)
        self.assertEqual(_join(bullet, bullet, line_text=bullet), bullet + " ")

    def test_a_row_of_cells_is_not_a_wide_line(self):
        cells = Line(spans=[_sized("C++", 108.0, 130.0, 300.0, 11.0).spans[0],
                            _sized("MATLAB", 300.0, 340.0, 300.0, 11.0).spans[0]],
                     bbox=(108.0, 290.0, 540.0, 303.0))
        self.assertTrue(I._row_of_cells(cells))
        self.assertFalse(I._row_of_cells(_sized("Fire Department Staffing", 108.0, 540.0,
                                                 300.0, 11.0)))

    def test_switched_off_it_is_a_space(self):
        self.addCleanup(_off("url_join"))
        self.assertEqual(_join("see https://example.org/courses/", "1595954/files"),
                         "see https://example.org/courses/ ")

    def test_a_joined_url_breaks_after_its_separators(self):
        from exactdoc.layout import Para, Run
        r = Run(text="see https://example.org/courses/1595954/files?x=1", font="Arial",
                size=10.0, color="#000000")
        r._url_join = True
        q = Para(runs=[r])
        I._url_overflow(q)
        z = chr(0x200B)
        self.assertEqual(q.runs[0].text, "see https://" + z + "example.org/" + z +
                         "courses/" + z + "1595954/" + z + "files?" + z + "x=" + z + "1")
        self.assertEqual(I.URL_OVERFLOW, "zwsp")

    def test_halves_the_document_uses_as_words_keep_their_space(self):
        from exactdoc import hyphen
        ev = hyphen.HyphenEvidence([["see the files and the courses here"]])
        tok = hyphen.activate(ev)
        try:
            self.assertEqual(_join("at https://example.org/", "files"),
                             "at https://example.org/ ")
            self.assertEqual(_join("at https://example.org/", "q7x9"),
                             "at https://example.org/")
        finally:
            hyphen.deactivate(tok)


if __name__ == "__main__":
    unittest.main()
