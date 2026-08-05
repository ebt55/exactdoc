"""The permissive shaper: right numbers, right provenance, no extra needed.

Four things are checked here, and they are four different claims.

**The data is the published Adobe data.** Re-derived from reportlab's BSD-3
`_fontdata` tables and compared cell by cell. This is the provenance check: if
`exactdoc/_base14_widths.py` ever stops matching an independent copy of the AFM
metrics, either it was hand-edited or it was regenerated from somewhere else,
and both are reasons to stop. Skipped where reportlab is absent, because it is a
`test`-extra dependency and this file must still run in a base install.

**The arithmetic is exact, not approximate.** Advances are additive and linear
in size. Both are properties of how a simple `Tj` is measured, both were probed
against MuPDF before the table was written, and both are what make one table
serve every point size without error accumulating along a line.

**It agrees with MuPDF wherever MuPDF can see.** 2190 Latin-1 cells across ten
faces, identical. Skipped without the `mupdf` extra.

**It deliberately disagrees where MuPDF cannot.** MuPDF's base-14 lookup is
Latin-1 only and charges the face's space width for the 27 WinAnsi codepoints
above U+00FF -- em dash 1000 answered as 278. That divergence is asserted to
EXIST, in the direction of the AFM, so nobody "fixes" the shaper back into
bug-compatibility without reading this.

    python -m unittest tests.test_base14_metrics
"""
import os
import sys
import unicodedata
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
# `discover -s tests` and running this file directly both put `tests/` on the
# path; `python -m unittest tests.test_base14_metrics` does not, and that is the
# invocation this module's docstring advertises.
sys.path.insert(0, HERE)

import mupdf_extra                                            # noqa: E402

from exactdoc import _base14_widths as W                      # noqa: E402
from exactdoc.metrics import (Base14Metrics, NullMetrics,     # noqa: E402
                              get_metrics)

# MuPDF shorthand -> (family, bold, italic) as `ladder._b14` maps them, so the
# tests drive the same door the ladder does rather than the table directly.
FACE = {"helv": ("Arial", False, False), "hebo": ("Arial", True, False),
        "heit": ("Arial", False, True), "hebi": ("Arial", True, True),
        "tiro": ("Times New Roman", False, False),
        "tibo": ("Times New Roman", True, False),
        "tiit": ("Times New Roman", False, True),
        "tibi": ("Times New Roman", True, True),
        "cour": ("Courier New", False, False),
        "cobo": ("Courier New", True, False)}

#: The 27 WinAnsi codepoints above U+00FF that MuPDF resolves to the space
#: width. Listed rather than computed so the set itself is reviewable.
ABOVE_LATIN1 = [0x20AC, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6,
                0x2030, 0x0160, 0x2039, 0x0152, 0x017D, 0x2018, 0x2019, 0x201C,
                0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122, 0x0161, 0x203A,
                0x0153, 0x017E, 0x0178]


def width(text, short, size=1000.0, metrics=None):
    fam, bold, italic = FACE[short]
    m = metrics or Base14Metrics()
    return m.text_width(text, fam, size, bold=bold, italic=italic)


class Provenance(unittest.TestCase):
    """The committed table must match an independent copy of the AFM data."""

    def setUp(self):
        try:
            from reportlab.pdfbase import _fontdata
        except ImportError:                                   # pragma: no cover
            self.skipTest("reportlab (test extra) not installed")
        self.fd = _fontdata

    def test_every_width_matches_reportlabs_afm_tables(self):
        ps = {"helv": "Helvetica", "hebo": "Helvetica-Bold",
              "heit": "Helvetica-Oblique", "hebi": "Helvetica-BoldOblique",
              "tiro": "Times-Roman", "tibo": "Times-Bold",
              "tiit": "Times-Italic", "tibi": "Times-BoldItalic",
              "cour": "Courier", "cobo": "Courier-Bold"}
        enc = self.fd.encodings["WinAnsiEncoding"]
        checked = 0
        for short, face in sorted(ps.items()):
            afm = self.fd.widthsByFontGlyph[face]
            for code in range(32, 256):
                gname = enc[code]
                if gname in (None, ".notdef") or gname not in afm:
                    continue
                try:
                    ch = bytes([code]).decode("cp1252")
                except UnicodeDecodeError:
                    continue
                if unicodedata.category(ch) == "Cc":
                    continue                       # see the next test
                got = width(ch, short)
                self.assertAlmostEqual(
                    got, float(afm[gname]), places=6,
                    msg="%s U+%04X (%s): table %s, AFM %s"
                        % (short, ord(ch), gname, got, afm[gname]))
                checked += 1
        self.assertGreater(checked, 2000, "only %d cells compared" % checked)

    def test_the_committed_file_is_what_the_generator_produces(self):
        """Byte-for-byte, so a hand-edit cannot survive.

        The width assertions above would pass a file someone reformatted or
        added a stray entry to; this one would not. It is the difference between
        "the numbers are right" and "the file is generated".

        Read through `W.__file__` rather than the generator's write target: the
        base-wheel proof runs this suite against the INSTALLED package with the
        source tree's `exactdoc/` deliberately absent, so a repo-relative path
        finds nothing there. What is being checked is the shipped file.
        """
        sys.path.insert(0, os.path.join(ROOT, "testkit"))
        import gen_base14_widths as gen
        with open(W.__file__, encoding="utf-8") as fh:
            shipped = fh.read()
        self.assertEqual(
            shipped, gen.render(gen.afm_tables()),
            "%s is not what testkit/gen_base14_widths.py produces -- re-run "
            "the generator rather than editing the table." % W.__file__)

    def test_the_unused_code_to_bullet_rule_is_about_bytes_not_characters(self):
        """The one place the AFM table is deliberately not copied verbatim.

        WinAnsiEncoding fills its UNUSED byte codes with `bullet` (PDF spec
        Annex D), and 0x7F is one of them, so reportlab's table answers 350 for
        code 127. That is a statement about a byte in a PDF string. U+007F the
        *character* is DEL, and a caller shaping text that contains it wants the
        missing-glyph fallback, not a bullet 26% wider than a space.

        Keyed on characters, these tables therefore omit the control range --
        which is also what makes them agree with MuPDF, whose answer for U+007F
        is the same fallback.
        """
        enc = self.fd.encodings["WinAnsiEncoding"]
        self.assertEqual(enc[0x7F], "bullet", "premise changed")
        for short in ("helv", "tiro"):
            self.assertNotIn(0x7F, W.WIDTHS[short] or {})
            self.assertAlmostEqual(width("\x7f", short),
                                   float(W.FALLBACK[short]), places=6)

    def test_the_fallback_is_each_faces_own_space_width(self):
        """Not a magic constant: the same rule MuPDF uses, from the same data."""
        for short in FACE:
            self.assertEqual(W.FALLBACK[short] if short in W.FALLBACK
                             else W.COURIER_WIDTH,
                             int(round(width(" ", short))),
                             "fallback for %s is not its space width" % short)


class Arithmetic(unittest.TestCase):
    def test_advances_are_additive(self):
        """No kerning. If this fails, a line's width stops being a sum."""
        for short in FACE:
            for a, b in (("A", "V"), ("T", "o"), ("W", "a"), ("f", ","),
                         ("P", "."), ("l", "l")):
                self.assertAlmostEqual(
                    width(a + b, short), width(a, short) + width(b, short),
                    places=6, msg="%s: %r" % (short, a + b))

    def test_width_is_linear_in_size(self):
        s = "The quick brown fox jumps over the lazy dog, 0123456789!"
        for short in FACE:
            at1000 = width(s, short, 1000.0)
            for size in (6.0, 8.5, 11.0, 9.77, 72.0):
                self.assertAlmostEqual(width(s, short, size),
                                       at1000 * size / 1000.0, places=6,
                                       msg="%s at %s" % (short, size))

    def test_a_string_is_the_sum_of_its_characters(self):
        s = "Hamburgefonstiv — “quoted”, 50% … €9"
        for short in FACE:
            self.assertAlmostEqual(width(s, short),
                                   sum(width(c, short) for c in s),
                                   places=6, msg=short)

    def test_courier_is_fixed_pitch(self):
        for short in ("cour", "cobo"):
            for ch in "iWm .—€":
                self.assertAlmostEqual(width(ch, short), 600.0, places=6,
                                       msg="%s %r" % (short, ch))
            self.assertAlmostEqual(width("iWm", short), 1800.0, places=6)

    def test_empty_text_is_zero_not_none(self):
        for short in FACE:
            self.assertEqual(width("", short), 0.0)

    def test_a_font_with_no_base14_equivalent_is_unmeasurable(self):
        """None, never a guess. The contract every caller already handles."""
        self.assertIsNone(
            Base14Metrics().text_width("hello", "Comic Sans MS", 11.0))


class AgreementWithMuPDF(unittest.TestCase):
    """Where MuPDF can see, the two must agree exactly."""

    @mupdf_extra.needs_extra
    def test_identical_on_every_latin1_codepoint(self):
        mu = get_metrics("mupdf")
        self.assertEqual(mu.name, "mupdf")
        checked, bad = 0, []
        for short in sorted(FACE):
            for cp in range(0x20, 0x100):
                ch = chr(cp)
                a = width(ch, short, 1000.0, metrics=mu)
                b = width(ch, short, 1000.0)
                if a is None or b is None:
                    continue
                checked += 1
                if abs(a - b) > 0.01:
                    bad.append("%s U+%04X mupdf=%s base14=%s"
                               % (short, cp, a, b))
        self.assertFalse(bad, "\n".join(bad[:20]))
        self.assertGreater(checked, 2000, "only %d cells compared" % checked)

    @mupdf_extra.needs_extra
    def test_it_diverges_above_latin1_and_the_afm_is_right(self):
        """The divergence is asserted to EXIST, so it cannot be "fixed" away.

        MuPDF charges the space width for these; the AFM gives them real
        advances and the renderer will too. Bug-compatibility here would mean
        deliberately mis-measuring an em dash by 72% of its width.
        """
        mu = get_metrics("mupdf")
        for short in ("helv", "hebo", "tiro", "tibo", "tiit", "tibi"):
            space = W.FALLBACK[short]
            for cp in ABOVE_LATIN1:
                ch = chr(cp)
                self.assertAlmostEqual(
                    width(ch, short, 1000.0, metrics=mu), float(space),
                    places=4,
                    msg="MuPDF stopped charging the space width for U+%04X in "
                        "%s -- re-derive this test's premise" % (cp, short))
                self.assertEqual(
                    width(ch, short, 1000.0),
                    float(W.WIDTHS[short][cp]),
                    "base14 must answer the AFM width for U+%04X in %s"
                    % (cp, short))

    @mupdf_extra.needs_extra
    def test_the_em_dash_is_the_worked_example(self):
        mu = get_metrics("mupdf")
        self.assertAlmostEqual(width("—", "helv", 1000.0, metrics=mu),
                               278.0, places=4)
        self.assertAlmostEqual(width("—", "helv", 1000.0), 1000.0,
                               places=4)


class Selection(unittest.TestCase):
    def test_the_default_shaper_needs_no_extra(self):
        m = get_metrics()
        self.assertEqual(m.name, "base14")
        self.assertIsInstance(m, Base14Metrics)
        self.assertIsNotNone(m.text_width("hello", "Arial", 11.0))

    def test_none_the_string_still_means_measure_nothing(self):
        """`None` and `"none"` are different requests and used to collapse."""
        self.assertIsInstance(get_metrics("none"), NullMetrics)
        self.assertIsNone(get_metrics("none").text_width("x", "Arial", 11.0))
        self.assertIsInstance(get_metrics(None), Base14Metrics)

    def test_asking_for_mupdf_without_the_extra_degrades_to_base14(self):
        """Not to NullMetrics. A missing extra is a provenance difference now,
        not a capability one."""
        got = get_metrics("mupdf")
        self.assertIn(got.name, ("mupdf", "base14"))
        if not mupdf_extra.AVAILABLE:
            self.assertEqual(got.name, "base14")

    def test_an_unknown_name_still_raises(self):
        with self.assertRaises(ValueError):
            get_metrics("harfbuzz")


class TableShape(unittest.TestCase):
    def test_ten_faces_map_to_six_tables_plus_courier(self):
        self.assertEqual(sorted(W.WIDTHS), sorted(FACE))
        self.assertIsNone(W.WIDTHS["cour"])
        self.assertIsNone(W.WIDTHS["cobo"])
        real = [id(v) for v in W.WIDTHS.values() if v is not None]
        self.assertEqual(len(set(real)), 6, "expected 6 distinct tables")

    def test_the_oblique_faces_share_their_upright_siblings_table(self):
        self.assertIs(W.WIDTHS["heit"], W.WIDTHS["helv"])
        self.assertIs(W.WIDTHS["hebi"], W.WIDTHS["hebo"])

    def test_every_table_covers_the_winansi_repertoire(self):
        for short, table in sorted(W.WIDTHS.items()):
            if table is None:
                continue
            self.assertGreaterEqual(len(table), 200,
                                    "%s has only %d glyphs" % (short, len(table)))
            for cp in ABOVE_LATIN1:
                self.assertIn(cp, table, "%s lacks U+%04X" % (short, cp))


if __name__ == "__main__":
    unittest.main()
