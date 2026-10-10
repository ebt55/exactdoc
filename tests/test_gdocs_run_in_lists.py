"""Run-in numbered paragraphs stay typed under the gdocs profile.

Google Docs sets the text after a list label at the item's indent start (the
end of its hanging indent) and ignores the paragraph's own tab stops there. An
item with no hanging indent -- label and text from one left edge, the text
placed by a custom tab stop, EUR-Lex's "1.<tab>" article paragraphs -- had its
text set at the next half inch: on Google's exports of the 71558af sweep, y18's
items with a 21.5pt stop set their text 36pt past the label (363 of 374), a
line longer than the page planner modelled on 19 paragraphs, and two pages
spilled. Typed, Docs keeps the stop (y18's own typed items, y01/y09's 24pt
contents tabs). So under gdocs such a list keeps its typed form
(`docxout._gdocs_list_defs`); a hanging list still numbers, and the standard
profile is untouched.

    python -m unittest tests.test_gdocs_run_in_lists
"""
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import lists as L  # noqa: E402
from exactdoc.docxout import GDOCS_LIST_MIN_HANGING_PT, _gdocs_list_defs  # noqa: E402
from exactdoc.layout import (Chunk, DocLayout, ListDef, ListItem, ListLevel,  # noqa: E402
                             PageLayout, Para, Run)
from exactdoc.structures import numbering_plan  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None


def _run(text, size=11.0, **kw):
    return Run(text=text, font="Times-Roman", size=size, color="#000000", **kw)


def _item(marker, text, left, hang, stop):
    """A marker-and-tab item as infer.para_from_lines builds one: `hang` 0
    is a run-in item whose text a tab stop at `stop` places."""
    return Para(runs=[_run(marker), Run(text="\t", font="Times-Roman", size=11.0,
                                        color="#000000", is_tab=True), _run(text)],
                left_indent=left, first_indent=-hang, leading=12.8,
                tab_stops=[(stop, "left")], bbox=(0, 0, 100, 12), src_lines=1)


def _lay(*els):
    lay = DocLayout()
    lay.pages.append(PageLayout(number=1, chunks=[Chunk(elements=list(els))]))
    return lay


class ListDefs(unittest.TestCase):
    def _plan(self):
        run_in = [_item("1.", "first article paragraph", 0.0, 0.0, 21.5),
                  _item("2.", "second article paragraph", 0.0, 0.0, 21.5)]
        hanging = [_item("(a)", "a point", 21.5, 21.5, 21.5),
                   _item("(b)", "another point", 21.5, 21.5, 21.5)]
        lay = _lay(*(run_in + [Para(runs=[_run("between")], leading=12.8,
                                    bbox=(0, 0, 100, 12), src_lines=1)] + hanging))
        L.assign_lists(lay, 11.0)
        ids = {p.runs[0].text: p.numbering.list_id for p in run_in + hanging
               if p.numbering is not None}
        return lay, ids

    def test_both_lists_are_lists(self):
        lay, ids = self._plan()
        self.assertEqual(set(ids), {"1.", "2.", "(a)", "(b)"})
        self.assertEqual(len(set(ids.values())), 2)

    def test_gdocs_drops_the_run_in_list_and_keeps_the_hanging_one(self):
        lay, ids = self._plan()
        plan = numbering_plan(lay, tab_only=True)
        self.assertEqual(set(plan), set(ids.values()))     # both write as tab lists
        kept = _gdocs_list_defs(lay, plan)
        self.assertEqual(set(kept), {ids["(a)"]})
        self.assertNotIn(ids["1."], kept)
        # nothing mutated: the plan the caller passed is whole
        self.assertEqual(set(plan), set(ids.values()))

    def test_a_list_is_all_or_nothing(self):
        # one item with no hanging indent takes its whole list with it, as
        # numbering_plan treats an item it cannot strip
        items = [_item("1.", "hangs", 21.5, 21.5, 21.5),
                 _item("2.", "hangs too", 21.5, 21.5, 21.5),
                 _item("3.", "runs in", 0.0, 0.0, 21.5)]
        lay = _lay(*items)
        lay.lists = [ListDef(list_id=0, levels={0: ListLevel(
            fmt="decimal", text="%1.", left=21.5, hanging=21.5)})]
        for k, p in enumerate(items, start=1):
            p.numbering = ListItem(list_id=0, level=0, fmt="decimal",
                                   marker="%d." % k, value=k)
        plan = numbering_plan(lay, tab_only=True)
        self.assertEqual(set(plan), {0})
        self.assertEqual(_gdocs_list_defs(lay, plan), {})
        items[2].first_indent = -21.5          # now every item hangs
        self.assertEqual(set(_gdocs_list_defs(lay, plan)), {0})

    def test_threshold_is_under_a_point(self):
        self.assertLess(GDOCS_LIST_MIN_HANGING_PT, 1.0)


def _articles_pdf(path):
    """Two run-in numbered articles (label at the margin, text at a 21.5pt
    stop, continuation lines back at the margin) and a hanging (a)/(b) list."""
    W, H = 612, 792
    c = _canvas.Canvas(path, pagesize=(W, H))
    y = [90]

    def line(x, text, width=None):
        # `width`: justify the line to it, as the source's article text is
        t = c.beginText(x, H - y[0])
        t.setFont("Times-Roman", 10)
        if width is not None and " " in text:
            natural = c.stringWidth(text, "Times-Roman", 10)
            t.setWordSpace((width - natural) / text.count(" "))
        t.textOut(text)
        c.drawText(t)

    body = ("The providers of such systems shall keep the documentation referred to in this "
            "Article at the disposal of the national competent authorities for a period ending "
            "ten years after the system has been placed on the market or put into service, "
            "and shall make it available to the authorities upon a reasoned request.")
    words = body.split()
    for n in (1, 2, 3):
        line(72, "%d." % n)
        x0, limit = 93.5, 446.5
        cur = []
        for w in words:
            if c.stringWidth(" ".join(cur + [w]), "Times-Roman", 10) > limit:
                line(x0, " ".join(cur), limit)
                y[0] += 12.0
                cur, x0, limit = [w], 72, 468.0
            else:
                cur.append(w)
        line(x0, " ".join(cur))
        y[0] += 24.0
    for m, text in (("(a)", "the name and address of the provider;"),
                    ("(b)", "the description of the system and its intended purpose;")):
        line(72, m)
        line(93.5, text)
        y[0] += 14.0
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
        pdf = _articles_pdf(os.path.join(cls._dir.name, "articles.pdf"))
        cls.std = os.path.join(cls._dir.name, "std.docx")
        cls.gd = os.path.join(cls._dir.name, "gd.docx")
        convert(pdf, cls.std, options=RAW)
        convert(pdf, cls.gd, options=PDFIUM_GDOCS_CANDIDATE)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    @staticmethod
    def _paras(path):
        with zipfile.ZipFile(path) as z:
            doc = z.read("word/document.xml").decode("utf-8")
        return re.findall(r"<w:p(?: [^>]*)?>.*?</w:p>", doc, re.S)

    @staticmethod
    def _text(p):
        return "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p))

    def test_standard_profile_numbers_the_articles(self):
        # the form Word and LibreOffice honour: label from the level, text at
        # the paragraph's own 21.5pt stop
        arts = [p for p in self._paras(self.std) if "The providers" in self._text(p)]
        self.assertEqual(len(arts), 3)
        for p in arts:
            self.assertIn("<w:numPr>", p)
            self.assertTrue(self._text(p).startswith("The providers"), self._text(p))
            self.assertRegex(p, r'<w:tab w:pos="4[23]\d" w:val="left"/>')

    def test_gdocs_types_the_articles_with_their_stop(self):
        arts = [p for p in self._paras(self.gd) if "The providers" in self._text(p)]
        self.assertEqual(len(arts), 3)
        for n, p in enumerate(arts, start=1):
            self.assertNotIn("<w:numPr>", p)
            self.assertTrue(self._text(p).startswith("%d.The providers" % n), self._text(p))
            # the label's typed tab, and the paragraph's stop at the text
            self.assertIn("<w:tab/>", p)
            self.assertRegex(p, r'<w:tab w:pos="4[23]\d" w:val="left"/>')
            self.assertNotIn("w:hanging", p)

    def test_gdocs_still_numbers_the_hanging_list(self):
        pts = [p for p in self._paras(self.gd) if self._text(p).startswith("the ")]
        self.assertEqual(len(pts), 2)
        self.assertTrue(all("<w:numPr>" in p for p in pts))


if __name__ == "__main__":
    unittest.main()
