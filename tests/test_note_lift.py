"""Real footnotes stand where the source's ended, as far as the render has room.

A renderer stacks a page's real notes at the foot of the body box, and the
bottom reserve is relaxed to the footer's top (`infer._can_relax_bottom_margin`)
because re-wrapped body text overruns the source's body box. So on y02 (NIST
SP 800-171) every page whose notes bound -- WP27 made them bind -- set its
notes ~45pt below the source's (p20: 712 -> 761, p97: 718 -> 761), and the
refine loop, reading a quarter of the page 45pt low, pulled the headings up.

The writer now closes a page's last note with an empty line of
`PageLayout.note_lift_pt` (a space after is not honoured at the area's foot;
an empty line is), and only the refine loop sets that lift: never past where
the source's notes ended (`notes.note_lift_cap`), never more than the render
shows free between the body and the notes (`refine._notes_free`), and given
back first when the page spills. Lifting every page to the source height
open-loop rendered y02 115 pages for 114 and the spill cascaded, so an
open-loop write lifts nothing.

    python -m unittest tests.test_note_lift
"""
import os
import sys
import tempfile
import unittest
import unittest.mock
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import notes as N  # noqa: E402
from exactdoc import refine as R  # noqa: E402
from exactdoc.layout import DocLayout, NoteArea, PageLayout  # noqa: E402

from tests.test_real_footnotes import _canvas, _footnote_pdf, _layout  # noqa: E402


def _foot(pl):
    return 763.5            # y02's body foot: 792 - 28.5


class Cap(unittest.TestCase):
    def test_the_cap_is_the_room_under_the_source_notes(self):
        pl = PageLayout(number=97, note_area=NoteArea(top=570.0, bottom=720.0,
                                                      height=140.0))
        self.assertAlmostEqual(N.note_lift_cap(pl, _foot), 43.5)

    def test_a_page_whose_note_runs_on_gets_none(self):
        pl = PageLayout(number=3, note_area=NoteArea(top=570.0, bottom=720.0,
                                                     height=140.0, runs_on=True))
        self.assertEqual(N.note_lift_cap(pl, _foot), 0.0)

    def test_an_open_loop_page_lifts_nothing(self):
        lay = DocLayout(pages=[PageLayout(number=1, note_area=NoteArea(
            top=570.0, bottom=720.0, height=140.0))])
        self.assertEqual(N.footnote_lifts(lay, _foot), {})

    def test_the_loop_lift_is_capped_and_charged_to_the_area(self):
        pl = PageLayout(number=1, note_area=NoteArea(top=570.0, bottom=720.0,
                                                     height=140.0))
        pl.note_lift_pt = 80.0
        lay = DocLayout(pages=[pl])
        self.assertEqual(N.footnote_lifts(lay, _foot), {1: 43.5})
        self.assertAlmostEqual(N.footnote_areas(lay, _foot)[1],
                               140.0 + N.FOOTNOTE_AREA_OVERHEAD_PT + 43.5)


class NotesFree(unittest.TestCase):
    # (text, baseline, bottom): y02 p97's shape -- body to the table, notes
    # 46pt below the source's, the first note's mark joined to its text
    SRC = [("tailoring criteria for eliminating", 241.0, 244.0),
           ("control, control enhancement, or specific elements", 534.0, 537.0),
           ("36", 577.0, 579.0),
           ("the security controls in tables e-1 through e-14", 580.0, 582.0),
           ("tables will be updated upon publication", 591.0, 593.0),
           ("comprehensive security program.", 718.0, 720.0),
           ("appendix e page 84", 754.0, 756.0)]
    OUT = [("tailoring criteria for eliminating", 250.0, 253.0),
           ("control, control enhancement, or specific elements", 524.0, 527.0),
           ("36the security controls in tables e-1 through e-14", 623.0, 625.0),
           ("tables will be updated upon publication", 634.0, 636.0),
           ("comprehensive security program.", 761.0, 763.0),
           ("appendix e page 84", 772.0, 774.0)]

    def test_free_is_measured_from_the_moved_zone_top(self):
        # the note lines moved +43 (634 - 591, 761 - 718); the zone's top
        # 570 is at 613 in the render, and the body ends at 527
        free = R._notes_free(self.SRC, self.OUT, (570.0, 720.0), band_top=60.0)
        self.assertAlmostEqual(free, 613.0 - 527.0)

    def test_the_footer_alone_measures_nothing(self):
        # y03: its notes' ligatures read differently on each side, and only
        # the running footer under them matched
        out = [l for l in self.OUT if not l[0].startswith(("tables", "comprehensive"))]
        self.assertIsNone(R._notes_free(self.SRC, out, (570.0, 720.0)))

    def test_unmatched_notes_measure_nothing(self):
        out = [l for l in self.OUT if not l[0].startswith(("tables", "comprehensive",
                                                           "appendix"))]
        self.assertIsNone(R._notes_free(self.SRC, out, (570.0, 720.0)))


def _page(lift=0.0, cap_bottom=720.0):
    pl = PageLayout(number=1, note_area=NoteArea(top=570.0, bottom=cap_bottom,
                                                 height=140.0))
    pl.note_lift_pt = lift
    return pl


class Apply(unittest.TestCase):
    def _apply(self, pl, spill=0, need=None, free=None, offset=0.0, room=None,
               out_pages=1):
        lay = DocLayout(pages=[pl])
        m = {"spill": [spill], "offset": [offset], "need": [need],
             "room": [room], "notes_free": [free],
             "out_pages": out_pages, "src_pages": 1}
        with unittest.mock.patch.object(R, "_note_cap", lambda lay, pl: 43.5), \
                unittest.mock.patch.object(R, "_page_elements", lambda pl: []):
            return R._apply(lay, m)

    def test_room_above_the_notes_lifts_them_up_to_the_cap(self):
        pl = _page()
        self.assertTrue(self._apply(pl, free=86.0))
        self.assertAlmostEqual(pl.note_lift_pt, 43.5)

    def test_little_room_lifts_them_only_that_far(self):
        pl = _page()
        self.assertTrue(self._apply(pl, free=R.NOTE_HEAD_PT + 12.0))
        self.assertAlmostEqual(pl.note_lift_pt, 12.0)

    def test_a_render_off_by_pages_lifts_nothing_more(self):
        # y47, 65 pages for 57: a lift there emptied a page and the render
        # lost its last three pages' text
        pl = _page()
        self.assertFalse(self._apply(pl, free=86.0, out_pages=2))
        self.assertEqual(pl.note_lift_pt, 0.0)
        pl = _page(lift=30.0)
        self.assertTrue(self._apply(pl, free=R.NOTE_HEAD_PT - 8.0, out_pages=2))
        self.assertAlmostEqual(pl.note_lift_pt, 22.0)    # given back all the same

    def test_a_body_that_closed_in_takes_the_lift_back(self):
        pl = _page(lift=30.0)
        self.assertTrue(self._apply(pl, free=R.NOTE_HEAD_PT - 8.0))
        self.assertAlmostEqual(pl.note_lift_pt, 22.0)

    def test_a_page_that_spills_gives_its_lift_back_first(self):
        pl = _page(lift=30.0)
        self.assertTrue(self._apply(pl, spill=1, need=12.0))
        self.assertAlmostEqual(pl.note_lift_pt, 18.0)

    def test_a_lift_is_not_room_for_a_push(self):
        # y03 p16: its lower half sat high, the median said "push down", and
        # the room the lifted notes left at the foot moved a right top 13pt
        from exactdoc.layout import Chunk, Para
        pl = _page(lift=30.0)
        first = Para(runs=[], space_before=6.0)
        pl.chunks = [Chunk(elements=[first])]
        lay = DocLayout(pages=[pl])
        m = {"spill": [0], "offset": [-12.0], "need": [None],
             "room": [32.0], "notes_free": [50.0],
             "out_pages": 1, "src_pages": 1}
        with unittest.mock.patch.object(R, "_note_cap", lambda lay, pl: 43.5):
            R._apply(lay, m)
        self.assertAlmostEqual(pl.note_lift_pt, 43.5)
        self.assertEqual(first.space_before, 6.0)

    def test_an_unlifted_page_pushes_as_before(self):
        from exactdoc.layout import Chunk, Para
        pl = PageLayout(number=1)
        first = Para(runs=[], space_before=6.0)
        pl.chunks = [Chunk(elements=[first])]
        lay = DocLayout(pages=[pl])
        m = {"spill": [0], "offset": [-12.0], "need": [None],
             "room": [32.0], "notes_free": [None],
             "out_pages": 1, "src_pages": 1}
        R._apply(lay, m)
        self.assertEqual(first.space_before, 18.0)

    def test_no_measurement_moves_nothing(self):
        pl = _page()
        self.assertFalse(self._apply(pl, free=None))
        self.assertEqual(pl.note_lift_pt, 0.0)



@unittest.skipIf(_canvas is None, "reportlab is not installed")
class Written(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = _footnote_pdf(os.path.join(cls._dir.name, "f.pdf"))

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def _notes(self, lay, name):
        from exactdoc.docxout import write_docx
        out = os.path.join(self._dir.name, name)
        write_docx(lay, out, output_profile="standard")
        with zipfile.ZipFile(out) as z:
            return z.read("word/footnotes.xml").decode("utf-8")

    def test_an_open_loop_write_is_unchanged(self):
        lay = _layout(self.pdf)
        self.assertNotIn('w:lineRule="exact"/></w:pPr></w:p></w:footnote>',
                         self._notes(lay, "open.docx"))

    def test_the_last_note_of_a_lifted_page_closes_with_an_empty_line(self):
        lay = _layout(self.pdf)
        pl = next(p for p in lay.pages if p.note_area is not None)
        pl.note_lift_pt = 20.0
        notes = self._notes(lay, "lift.docx")
        blocks = notes.split("</w:footnote>")
        body = [b for b in blocks if "explains the reference" in b]
        self.assertEqual(len(body), 2)
        self.assertNotIn('w:line="400" w:lineRule="exact"', body[0])
        self.assertIn('<w:spacing w:before="0" w:after="0" w:line="400" '
                      'w:lineRule="exact"/></w:pPr></w:p>', body[1])


if __name__ == "__main__":
    unittest.main()
