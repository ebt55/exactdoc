"""WP49: tab- and right-aligned layouts read as columns or tables.

Holdout-1 (37 public PDFs the converter had never seen) showed four layout
mechanisms that a word processor sets with TABS being read as columns or
tables. Each is reproduced here by a synthetic page (tests/wp49_fixtures.py),
together with the look-alike structure the converter must keep:

A  a resume's place and dates at a right tab on the entry lines' baselines
   were read as a second text column (dates behind a column break, bullets
   moved after the columns) -- `infer._right_tab_fields`;
D  a contents page in two levels, each level's numbers flush at its own edge
   a few points from the other's, was not read as leader lines at all, and
   its entries welded into one paragraph -- `infer._leader_levels`;
C2 a picture made of a stray fill under a table -- or merged out of several
   -- painted the table's text as pixels while its boxes wrote it again
   (`infer._covers_text`): no picture may paint text the page also writes;
B  section headings with a rule under each, read as a booktabs table, and
C1 table cells filled two rectangles to a path, read as a picture plus
   one-cell boxes, are recorded as known defects (expected failures): their
   fixes were deferred from 0.3.0b1.

Every WP49 reading is the standard profile's: `infer(tab_layouts=False)` --
what the gdocs profile passes -- reproduces the earlier layout exactly.
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from exactdoc import infer as I  # noqa: E402
from exactdoc.layout import ColBreak, FigureEl, Para, TableEl, iter_paras  # noqa: E402
from exactdoc.model import Line, Span  # noqa: E402

import wp49_fixtures as F  # noqa: E402


def _parse(path):
    from exactdoc.dialect import normalize
    from exactdoc.parse_pdfium import parse_pdf
    return normalize(parse_pdf(path, keep_image_data=True))


def _infer(path, **kw):
    return I.infer(_parse(path), **kw)


def _elements(lay, page=1):
    return [el for ch in lay.pages[page - 1].chunks for el in ch.elements]


def _texts(lay):
    return [p.text for p in iter_paras(lay)]


def _shape(lay):
    """A layout's structure, for comparing two readings of one page."""
    out = []
    for pl in lay.pages:
        for ch in pl.chunks:
            out.append(("chunk", ch.n_cols))
            for el in ch.elements:
                if isinstance(el, Para):
                    out.append(("para", el.text, tuple(el.tab_stops), el.align))
                else:
                    out.append((type(el).__name__,))
    return out


class _rule:
    """Turn one WP49 switch (infer.WP49_RULES) on or off for a block."""
    def __init__(self, name, on):
        self.name, self.on = name, on

    def __enter__(self):
        self.was = I.WP49_RULES[self.name]
        I.WP49_RULES[self.name] = self.on

    def __exit__(self, *exc):
        I.WP49_RULES[self.name] = self.was


def _text_drawn_twice(lay):
    """Characters of written text whose source box centre lies inside a
    picture's clip on the same page: painted as pixels and written again."""
    def paras(el):
        if isinstance(el, Para):
            yield el
        elif isinstance(el, TableEl):
            for r in el.rows:
                for c in r:
                    if c is not None:
                        yield from c.paras
    n = 0
    for pl in lay.pages:
        els = [e for ch in pl.chunks for e in ch.elements]
        clips = [e.clip for e in els if isinstance(e, FigureEl)]
        for e in els:
            for q in paras(e):
                if q.bbox is None:
                    continue
                cx, cy = (q.bbox[0] + q.bbox[2]) / 2, (q.bbox[1] + q.bbox[3]) / 2
                if any(c[0] <= cx <= c[2] and c[1] <= cy <= c[3] for c in clips):
                    n += len(q.text.strip())
    return n


# ------------------------------------------------------------- unit level
def _span(text, x0, x1, base, size=10.5, font="Times-Roman"):
    return Span(text=text, font=font, size=size, color="#000000", bold=False,
                italic=False, mono=False, serif=True, superscript=False,
                bbox=(x0, base - 8.0, x1, base + 2.5), origin=(x0, base))


def _line(text, x0, x1, base, **kw):
    s = _span(text, x0, x1, base, **kw)
    return Line(spans=[s], bbox=s.bbox)


def _entries(right_x1=540.0, flush=True, ragged=True):
    """Lines of four resume entries: label at the margin, field at the right
    on the same baseline, two lines each, a full-width bullet between."""
    out, base = [], 120.0
    fields = (("Town, MA", "August 2019 - Present"), ("Springfield, IL", "June 2019"),
              ("Cambridge, MA", "May 2015 - Dec 2016"), ("Portland, OR", "May 2013"))
    for i, (place, dates) in enumerate(fields):
        for j, t in enumerate((place, dates)):
            w = 6.0 * len(t)
            x1 = right_x1 if flush else right_x1 - 9.0 * ((i + j) % 3)
            x0 = x1 - w if ragged else 400.0
            out.append(_line("Employer or role %d" % i, 72.0, 260.0, base + 13 * j))
            out.append(_line(t, x0, x1, base + 13 * j))
        out.append(_line("• a bullet that runs the full width of the text column",
                         80.0, 535.0, base + 30))
        base += 56
    return out


class RightTabFieldsUnit(unittest.TestCase):
    def test_flush_ragged_short_paired_fields_are_a_tab(self):
        self.assertAlmostEqual(I._right_tab_fields(_entries(), 72.0, 540.0), 540.0)

    def test_fields_that_do_not_share_a_right_edge_are_not(self):
        self.assertIsNone(I._right_tab_fields(_entries(flush=False), 72.0, 540.0))

    def test_flush_left_short_lines_are_a_column_not_fields(self):
        self.assertIsNone(I._right_tab_fields(_entries(ragged=False), 72.0, 540.0))

    def test_lines_alone_on_their_baselines_are_not_fields(self):
        lines = [l for l in _entries() if l.bbox[0] > 300.0]
        self.assertIsNone(I._right_tab_fields(lines, 72.0, 540.0))


class LeaderLevelsUnit(unittest.TestCase):
    def _toc(self, edges):
        return [_line("Entry %d ........................ %d" % (i, i), 72.0, e, 100.0 + 20 * i)
                for i, e in enumerate(edges)]

    def _read(self, lines):
        items = [("blk", l.bbox, [l]) for l in lines]
        return I._leader_lines(items, 72.0, 540.0)[0]

    def test_two_exact_levels_a_fraction_of_an_em_apart_are_leaders(self):
        got = self._read(self._toc([543.3, 539.5] * 5))
        self.assertEqual(len(got), 10)
        self.assertEqual({e for _l, e in got}, {543.3})   # one stop, the outermost

    def test_scattered_numbers_stay_text(self):
        # a fixed run of dots: three nearly agree, the rest wherever they fell
        got = self._read(self._toc([278.6, 287.3, 293.1, 294.3, 300.1, 300.4,
                                    300.7, 305.1]))
        self.assertEqual(got, [])

    def test_levels_further_apart_than_half_an_em_stay_text(self):
        got = self._read(self._toc([543.3, 530.0] * 5))
        self.assertEqual(got, [])

    def test_switched_off_by_the_flag(self):
        tok = I._TAB_LAYOUTS.set(False)
        try:
            self.assertEqual(self._read(self._toc([543.3, 539.5] * 5)), [])
        finally:
            I._TAB_LAYOUTS.reset(tok)


# --------------------------------------------------------- end to end
@unittest.skipUnless(F.available(), "reportlab is not installed")
class TabLayoutsEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        d = cls._dir.name
        cls.paths = {}
        for name in ("right_tab_resume", "two_column_prose", "grid_aligned_columns",
                     "right_aligned_sidebar", "two_level_contents",
                     "fixed_dot_contents", "underlined_sections", "booktabs_table",
                     "zebra_multirect_table", "one_path_bar_chart",
                     "one_path_horizontal_bars"):
            cls.paths[name] = getattr(F, name)(os.path.join(d, name + ".pdf"))

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def both(self, name):
        return (_infer(self.paths[name]),
                _infer(self.paths[name], tab_layouts=False))

    # A -------------------------------------------------------------------
    def test_A_right_tab_fields_stay_beside_their_entries(self):
        lay, old = self.both("right_tab_resume")
        # the defect, reproduced with WP49 off: a column break with the dates
        self.assertTrue(any(isinstance(e, ColBreak) for e in _elements(old)))
        els = _elements(lay)
        self.assertFalse([e for e in els if isinstance(e, (ColBreak, TableEl))])
        self.assertTrue(all(ch.n_cols == 1 for ch in lay.pages[0].chunks))
        rows = [p for p in els if isinstance(p, Para) and "\t" in p.text
                and not p.text.startswith("•")]
        texts = [p.text for p in rows]
        for employer, place, role, dates in F.RESUME_ROWS[:3]:
            self.assertIn(employer + "\t" + place, texts)
            self.assertIn(role + "\t" + dates, texts)
        for p in rows:      # one right stop, at the fields' own edge
            self.assertEqual(len(p.tab_stops), 1)
            self.assertEqual(p.tab_stops[0][1], "right")
            self.assertAlmostEqual(p.tab_stops[0][0], F.R_EDGE - F.L_MARGIN, delta=2.0)

    def test_A_reading_order_keeps_bullets_under_their_entry(self):
        texts = _texts(_infer(self.paths["right_tab_resume"]))
        first = texts.index(F.RESUME_ROWS[0][0] + "\t" + F.RESUME_ROWS[0][1])
        second = texts.index(F.RESUME_ROWS[1][0] + "\t" + F.RESUME_ROWS[1][1])
        between = texts[first:second]
        self.assertEqual(sum(1 for t in between if t.startswith("•")),
                         len(F.RESUME_BULLETS))

    def test_A_controls_are_unchanged(self):
        for name in ("two_column_prose", "grid_aligned_columns", "right_aligned_sidebar"):
            with self.subTest(name):
                lay, old = self.both(name)
                self.assertEqual(_shape(lay), _shape(old))

    def test_A_a_real_two_column_page_stays_two_columns(self):
        lay = _infer(self.paths["two_column_prose"])
        self.assertTrue(any(ch.n_cols == 2 for ch in lay.pages[0].chunks))

    # D -------------------------------------------------------------------
    def test_D_two_level_contents_entries_are_leader_lines(self):
        lay, old = self.both("two_level_contents")
        entries = [p for p in _elements(lay) if isinstance(p, Para) and "\t" in p.text]
        self.assertEqual(len(entries), len(F.TOC_ENTRIES))
        stops = {p.tab_stops[0][0] for p in entries}
        self.assertEqual(len(stops), 1)
        for p, (level, label, num) in zip(entries, F.TOC_ENTRIES):
            self.assertTrue(p.text.startswith(label))
            self.assertTrue(p.text.rstrip().endswith(num))
        # level 2 keeps its indent
        lvl = {lab: p.left_indent for p, (_lv, lab, _n) in zip(entries, F.TOC_ENTRIES)}
        self.assertGreater(lvl["Background and scope"], lvl["Overview"] + 8.0)
        # with WP49 off: the earlier reading, no entry a leader line
        self.assertFalse([p for p in _elements(old) if isinstance(p, Para)
                          and p.tab_stops and "\t" in p.text])

    def test_D_fixed_dot_contents_stay_text(self):
        lay, old = self.both("fixed_dot_contents")
        self.assertEqual(_shape(lay), _shape(old))
        self.assertFalse([p for p in _elements(lay) if isinstance(p, Para)
                          and "\t" in p.text])

    # B and C: known defects, fixes deferred --------------------------------
    @unittest.expectedFailure
    def test_B_underlined_section_headings_are_not_a_table(self):
        lay = _infer(self.paths["underlined_sections"])
        self.assertFalse([e for e in _elements(lay) if isinstance(e, TableEl)])

    def test_B_control_booktabs_table_is_a_table(self):
        lay = _infer(self.paths["booktabs_table"])
        tables = [e for e in _elements(lay) if isinstance(e, TableEl)]
        self.assertEqual(len(tables), 1)
        self.assertEqual((len(tables[0].rows), len(tables[0].col_widths)), (5, 4))

    @unittest.expectedFailure
    def test_C_multirect_zebra_table_is_one_tiled_table(self):
        lay = _infer(self.paths["zebra_multirect_table"])
        els = _elements(lay)
        self.assertFalse([e for e in els if isinstance(e, FigureEl)])
        tables = [e for e in els if isinstance(e, TableEl)]
        self.assertEqual(len(tables), 1)
        self.assertGreaterEqual(len(tables[0].col_widths), 4)

    def test_C2_no_picture_paints_text_the_page_also_writes(self):
        # C2 ships switched off (infer.WP49_RULES); its rule is tested on
        with _rule("figure_covers_text", True):
            for name in ("zebra_multirect_table", "one_path_bar_chart",
                         "one_path_horizontal_bars", "right_tab_resume"):
                with self.subTest(name):
                    self.assertEqual(_text_drawn_twice(_infer(self.paths[name])), 0)
        # the defect, reproduced with the rule off: the stray row fills'
        # picture covers the whole table, whose amounts the cell boxes write
        with _rule("figure_covers_text", False):
            self.assertGreater(_text_drawn_twice(
                _infer(self.paths["zebra_multirect_table"])), 0)

    def test_C_controls_one_path_bar_charts_are_pictures(self):
        for on in (False, True):
            with _rule("figure_covers_text", on):
                for name in ("one_path_bar_chart", "one_path_horizontal_bars"):
                    with self.subTest(name, c2=on):
                        els = _elements(_infer(self.paths[name]))
                        self.assertTrue([e for e in els if isinstance(e, FigureEl)])
                        self.assertFalse([e for e in els if isinstance(e, TableEl)])


if __name__ == "__main__":
    unittest.main()
