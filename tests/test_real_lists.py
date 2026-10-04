"""Real list numbering: typed-marker items read as lists and written as w:numPr.

The benchmark found 0 `w:numPr` in every output of every tool (design audit
finding 9): a typed "3." does not renumber when a reader inserts an item, and a
typed bullet carries no list semantics. `lists.assign_lists` reads the items
inference already recognises as lists -- levels from the marker column, format
and start from the marker, sequence checked against the renderer's own
counters -- and the standard profile writes them as numbering
(`options.PROFILE_CAPABILITIES`). Measured in the canonical LibreOffice, the
numbered renders put every word where the typed renders did on x03, x09, c1,
c6, 01, l1, r1, c8, x17, x18, y17, y28 and y30 (0 words moved > 0.5pt).

    python -m unittest tests.test_real_lists
"""
import importlib.util
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import lists as L  # noqa: E402
from exactdoc.layout import (Chunk, DocLayout, ListItem, PageLayout,  # noqa: E402
                             Para, Run)
from exactdoc.structures import strip_marker  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None


def _run(text, size=11.0, **kw):
    return Run(text=text, font="Times-Roman", size=size, color="#000000", **kw)


def _tab_item(marker, text, left, hang=18.0, size=11.0):
    """A marker-and-tab item as infer.para_from_lines builds one."""
    p = Para(runs=[_run(marker, size), Run(text="\t", font="Times-Roman",
                                           size=size, color="#000000", is_tab=True),
                   _run(text, size)],
             left_indent=left, first_indent=-hang, leading=12.8,
             tab_stops=[(left, "left")], bbox=(0, 0, 100, 12), src_lines=1)
    return p


def _inline_item(marker, text, left, align="left"):
    p = Para(runs=[_run(marker + " " + text)], left_indent=left, align=align,
             leading=12.8, bbox=(0, 0, 100, 12), src_lines=1)
    p._list_item = True
    return p


def _body(text):
    return Para(runs=[_run(text)], leading=12.8, bbox=(0, 0, 100, 12), src_lines=1)


def _lay(*pages):
    lay = DocLayout()
    for i, els in enumerate(pages, start=1):
        lay.pages.append(PageLayout(number=i, chunks=[Chunk(elements=list(els))]))
    return lay


class MarkerParsing(unittest.TestCase):
    def test_bullets_and_dashes(self):
        self.assertEqual(L.parse_marker("•").kind, "bullet")
        self.assertEqual(L.parse_marker("").glyph, "•")   # Symbol PUA
        self.assertEqual(L.parse_marker("–").kind, "dash")

    def test_ordinal_forms(self):
        m = L.parse_marker("(a)")
        self.assertEqual((m.prefix, m.suffix), ("(", ")"))
        self.assertIn(("lowerLetter", 1), m.cands)
        self.assertEqual(L.parse_marker("12.").cands, (("decimal", 12),))
        self.assertIn(("lowerRoman", 4), L.parse_marker("iv)").cands)
        self.assertEqual(set(L.parse_marker("i.").cands),
                         {("lowerLetter", 9), ("lowerRoman", 1)})
        self.assertEqual(L.parse_marker("B)").cands[0], ("upperLetter", 2))

    def test_not_markers(self):
        for t in ("(1.", "1", "word.", "iiii.", "", "10.5"):
            self.assertIsNone(L.parse_marker(t), t)


class ListInference(unittest.TestCase):
    def test_nested_bullets_take_levels_from_their_columns(self):
        items = [_tab_item("•", "a", 18), _tab_item("•", "b", 36),
                 _tab_item("•", "c", 54), _tab_item("•", "d", 18)]
        lay = _lay(items)
        self.assertEqual(L.assign_lists(lay, 11.0), 4)
        self.assertEqual([p.numbering.level for p in items], [0, 1, 2, 0])
        self.assertEqual(len({p.numbering.list_id for p in items}), 1)
        lvl = lay.lists[0].levels[1]
        self.assertEqual((lvl.fmt, lvl.text, lvl.left, lvl.hanging, lvl.sep),
                         ("bullet", "•", 36, 18.0, "tab"))

    def test_numbered_list_continues_across_body_text_and_pages(self):
        a, b = _tab_item("1.", "one", 18), _tab_item("2.", "two", 18)
        c = _tab_item("3.", "three", 18)
        lay = _lay([a, b, _body("an interruption")], [c])
        L.assign_lists(lay, 11.0)
        self.assertEqual({a.numbering.list_id, b.numbering.list_id,
                          c.numbering.list_id}, {0})
        self.assertEqual(lay.lists[0].levels[0].start, 1)
        self.assertEqual(lay.lists[0].levels[0].text, "%1.")

    def test_a_restart_is_a_new_list_at_the_source_value(self):
        items = [_tab_item("1.", "a", 18), _tab_item("2.", "b", 18),
                 _tab_item("1.", "c", 18), _tab_item("2.", "d", 18)]
        lay = _lay(items)
        L.assign_lists(lay, 11.0)
        self.assertNotEqual(items[1].numbering.list_id, items[2].numbering.list_id)
        self.assertEqual(lay.lists[items[2].numbering.list_id].levels[0].start, 1)

    def test_a_sublevel_that_keeps_counting_splits_rather_than_misnumbers(self):
        # x03: "2." under one parent, "3." under the next. Word and LibreOffice
        # both restart a sub-level under a new parent, so the item that keeps
        # counting must open a list of its own, at its own value, at level 0.
        items = [_tab_item("1.", "p", 18), _tab_item("1.", "s", 36),
                 _tab_item("2.", "s", 36), _tab_item("2.", "p", 18),
                 _tab_item("3.", "s", 36)]
        lay = _lay(items)
        L.assign_lists(lay, 11.0)
        last = items[-1].numbering
        self.assertEqual(last.level, 0)
        self.assertEqual(lay.lists[last.list_id].levels[0].start, 3)
        self.assertEqual(len({p.numbering.list_id for p in items[:4]}), 1)

    def test_a_lone_ordinal_is_not_a_list(self):
        # SCOTUS: "v.<tab>Hillery, 474 U. S. 254" is a citation, not item five
        items = [_tab_item("v.", "Hillery, 474 U. S. 254", 18), _body("text")]
        lay = _lay(items)
        self.assertEqual(L.assign_lists(lay, 11.0), 0)
        self.assertIsNone(items[0].numbering)

    def test_roman_reading_needs_a_roman_sibling(self):
        items = [_tab_item("i.", "a", 18), _tab_item("ii.", "b", 18)]
        lay = _lay(items)
        L.assign_lists(lay, 11.0)
        self.assertEqual(items[0].numbering.fmt, "lowerRoman")
        self.assertEqual(lay.lists[0].levels[0].start, 1)

    def test_heading_sized_numbers_stay_headings(self):
        # c6: "1. Section heading number 1" at 14pt over a 10.5pt body
        items = [_inline_item("1.", "Section one", 0), _inline_item("2.", "Section two", 0)]
        for p in items:
            p.runs = [_run(p.runs[0].text, size=14.0)]
        lay = _lay(items)
        self.assertEqual(L.assign_lists(lay, 10.5), 0)

    def test_dashes_need_a_sibling(self):
        lone = _lay([_tab_item("-", "only", 18)])
        self.assertEqual(L.assign_lists(lone, 11.0), 0)
        pair = _lay([_tab_item("-", "a", 18), _tab_item("-", "b", 18)])
        self.assertEqual(L.assign_lists(pair, 11.0), 2)

    def test_a_tab_item_off_its_levels_column_starts_its_own_list(self):
        # y28 p36: text at 38.7pt in a level whose tab stop is 36.0 -- the
        # level's stop would pull its text 2.9pt left.
        items = [_tab_item("•", "a", 36.0), _tab_item("•", "b", 38.7, hang=20.7)]
        lay = _lay(items)
        L.assign_lists(lay, 11.0)
        self.assertNotEqual(items[0].numbering.list_id, items[1].numbering.list_id)

    def test_justified_space_items_keep_their_space_as_text(self):
        # y24: the typed space stretches with the line; a w:suff space would not
        items = [_inline_item("•", "x " * 30, 12, align="justify"),
                 _inline_item("•", "y", 12)]
        lay = _lay(items)
        L.assign_lists(lay, 11.0)
        self.assertEqual(lay.lists[0].levels[0].sep, "nothing")
        self.assertEqual(strip_marker(items[1].runs, items[1].numbering)[0].text, " y")

    def test_a_later_indented_list_is_not_a_level_of_an_earlier_one(self):
        items = [_tab_item("•", "a", 18), _body("a paragraph at the margin"),
                 _tab_item("1.", "x", 54), _tab_item("2.", "y", 54)]
        lay = _lay(items)
        L.assign_lists(lay, 11.0)
        self.assertEqual(items[2].numbering.level, 0)
        self.assertNotEqual(items[0].numbering.list_id, items[2].numbering.list_id)


class MarkerStripping(unittest.TestCase):
    def test_tab_form(self):
        p = _tab_item("1.", "text", 18)
        out = strip_marker(p.runs, ListItem(0, 0, "decimal", "1.", "tab", 1))
        self.assertEqual([r.text for r in out], ["text"])
        self.assertEqual(p.runs[0].text, "1.")          # never mutated

    def test_inline_form_and_a_locked_line_without_its_tab(self):
        out = strip_marker([_run("• Rebuilt it")], ListItem(0, 0, "bullet", "•", "space"))
        self.assertEqual(out[0].text, "Rebuilt it")
        # the ladder's line lock drops tab runs: "•Responsibility…"
        out = strip_marker([_run("•Responsibility for")],
                           ListItem(0, 0, "bullet", "•", "tab"))
        self.assertEqual(out[0].text, "Responsibility for")

    def test_a_paragraph_that_no_longer_opens_with_its_marker(self):
        self.assertIsNone(strip_marker([_run("2. text")],
                                       ListItem(0, 0, "decimal", "1.", "space", 1)))


class LevelSerialisation(unittest.TestCase):
    def test_the_label_keeps_its_markers_spacing_and_scale(self):
        # x17: without the marker's letter-spacing the item text sat 0.58pt left
        from docx.oxml.ns import qn
        from exactdoc.layout import ListLevel
        from exactdoc.structures import _lvl
        marker = _run("•", tracking=0.3, width_scale=0.97)
        el = _lvl(0, ListLevel(fmt="bullet", text="•", sep="space", left=12.2,
                               hanging=11.5, marker_run=marker), "standard")
        rpr = el.find(qn("w:rPr"))
        self.assertEqual(rpr.find(qn("w:spacing")).get(qn("w:val")), "6")
        self.assertEqual(rpr.find(qn("w:w")).get(qn("w:val")), "97")
        self.assertEqual(el.find(qn("w:suff")).get(qn("w:val")), "space")
        ind = el.find(qn("w:pPr")).find(qn("w:ind"))
        self.assertEqual((ind.get(qn("w:left")), ind.get(qn("w:hanging"))), ("244", "230"))
        # no tab stop for a space-separated level
        self.assertIsNone(el.find(qn("w:pPr")).find(qn("w:tabs")))


class GdocsSeparators(unittest.TestCase):
    """Google Docs draws a tab where `w:suff space`/`nothing` asks for a
    space or nothing (live, 2026-10-04: c1's run-in "1. text" items 26pt
    right), so under that profile a list numbers only if every level is
    tab-separated; the rest keep their typed form, whole."""

    def _plan(self, tab_only):
        from exactdoc.structures import numbering_plan
        run_in = [_inline_item("1.", "first", 0), _inline_item("2.", "second", 0)]
        tabbed = [_tab_item("•", "a", 18), _tab_item("•", "b", 18)]
        lay = _lay(run_in + [_body("between the two lists")] + tabbed)
        L.assign_lists(lay, 11.0)
        seps = {ld.list_id: {lv.sep for lv in ld.levels.values()} for ld in lay.lists}
        return numbering_plan(lay, tab_only=tab_only), seps

    def test_tab_only_drops_a_run_in_list(self):
        plan, seps = self._plan(tab_only=True)
        self.assertEqual(sorted(map(sorted, seps.values())), [["space"], ["tab"]])
        self.assertEqual({lid for lid, s in seps.items() if s == {"tab"}}, set(plan))

    def test_by_default_both_lists_number(self):
        plan, seps = self._plan(tab_only=False)
        self.assertEqual(set(plan), set(seps))


def _list_pdf(path):
    W, H = 612, 792
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Roman", 11)
    y = 90

    def line(x, text, font="Times-Roman", size=11):
        nonlocal y
        c.setFont(font, size)
        c.drawString(x, H - y, text)

    line(72, "A paragraph of body text that introduces the lists below it.")
    y += 24
    for lvl, text in ((0, "Site preparation"), (1, "Confirm the hoarding line"),
                      (1, "Photograph the boundary"), (0, "Utilities")):
        line(72 + 18 * lvl, "•")
        line(90 + 18 * lvl, text)
        y += 15
    y += 12
    line(72, "Then the numbered steps, in order.")
    y += 20
    for n, text in ((1, "Establish the layover"), (2, "Mark the bays")):
        line(72, "%d." % n)
        line(90, text)
        y += 15
    line(72, "A note between the steps that interrupts the list.")
    y += 15
    line(72, "3.")
    line(90, "Publish the times")
    c.showPage()
    c.save()
    return path


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from exactdoc.convert import convert
        from exactdoc.options import PDFIUM_GDOCS_CANDIDATE, RAW
        cls._dir = tempfile.TemporaryDirectory()
        pdf = _list_pdf(os.path.join(cls._dir.name, "lists.pdf"))
        cls.std = os.path.join(cls._dir.name, "std.docx")
        cls.gd = os.path.join(cls._dir.name, "gd.docx")
        cls.typed = os.path.join(cls._dir.name, "typed.docx")
        convert(pdf, cls.std, options=RAW)
        convert(pdf, cls.gd, options=PDFIUM_GDOCS_CANDIDATE)
        # the typed form, as a profile without the capability writes it
        from exactdoc import options as O
        caps = O.PROFILE_CAPABILITIES["gdocs"]
        O.PROFILE_CAPABILITIES["gdocs"] = frozenset()
        try:
            convert(pdf, cls.typed, options=PDFIUM_GDOCS_CANDIDATE)
        finally:
            O.PROFILE_CAPABILITIES["gdocs"] = caps

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    @staticmethod
    def _xml(path, part):
        with zipfile.ZipFile(path) as z:
            return z.read(part).decode("utf-8")

    def test_standard_profile_writes_numbering(self):
        doc = self._xml(self.std, "word/document.xml")
        self.assertEqual(doc.count("<w:numPr>"), 7)
        # the marker left the text: the level draws it
        self.assertNotIn(">•<", doc)
        self.assertNotIn(">1.<", doc)
        num = self._xml(self.std, "word/numbering.xml")
        self.assertIn('w:lvlText w:val="%1."', num)
        self.assertIn('w:lvlText w:val="•"', num)

    def test_numbered_items_share_one_num_across_the_interruption(self):
        doc = self._xml(self.std, "word/document.xml")
        ids = re.findall(r'<w:ilvl w:val="(\d)"/><w:numId w:val="(\d+)"/>', doc)
        numbered = ids[-3:]
        self.assertEqual(len({n for _l, n in numbered}), 1, ids)
        # above python-docx's template lists (numId 1-9), never one of them
        self.assertTrue(all(int(n) > 9 for _l, n in ids), ids)

    def test_gdocs_profile_numbers_tab_separated_lists(self):
        # live, 2026-10-04: Docs renders tab-separated levels where the typed
        # form put them (options.PROFILE_CAPABILITIES)
        doc = self._xml(self.gd, "word/document.xml")
        self.assertEqual(doc.count("<w:numPr>"), 7)
        self.assertNotIn(">•<", doc)

    def test_without_the_capability_the_markers_stay_typed(self):
        doc = self._xml(self.typed, "word/document.xml")
        self.assertNotIn("<w:numPr>", doc)
        self.assertIn(">•<", doc)

    # The harness is the measurement toolkit and imports PyMuPDF (the AGPL
    # `mupdf` extra) at module scope; the install-check CI job has neither.
    @unittest.skipUnless(importlib.util.find_spec("fitz"),
                         "testkit/harness.py needs PyMuPDF (the mupdf extra)")
    def test_the_harness_reads_generated_labels_as_live_text(self):
        # A label is text every reader renders, not raster: the live-text
        # metric (1 - raster_frac) must see "3." whether typed or numbered.
        sys.path.insert(0, os.path.join(ROOT, "testkit"))
        import harness
        real, _ = harness.docx_live_text(self.std)
        typed, _ = harness.docx_live_text(self.typed)
        norm = lambda t: re.sub(r"\s+", "", t)
        self.assertEqual(norm(real), norm(typed))
        self.assertIn("3.Publishthetimes", norm(real))


if __name__ == "__main__":
    unittest.main()
