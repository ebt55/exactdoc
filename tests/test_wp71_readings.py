"""WP71: readings for holdout-3's short documents (development data since its
exam), each its own switch in `infer.WP71_RULES`, standard profile only.

  2. Right-tab fields a blank template sets (`infer._right_tab_fields`):
     fields that all say the same thing cannot start ragged; a banner centred
     across the page's middle and a list set two-up are neither fields nor
     column lines; one long field set beside the page's white is a field.

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


if __name__ == "__main__":
    unittest.main()
