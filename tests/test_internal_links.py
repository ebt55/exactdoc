"""Internal (GoTo) links: IR destination, both backends, and the writer.

A GoTo link becomes `Span.dest` (model.LinkDest) in the IR and
`w:hyperlink w:anchor` + `w:bookmarkStart/End` in the DOCX. The two coordinate
traps this pins:

  * PyMuPDF reports the destination point in two different spaces depending on
    how the PDF spelled it -- a direct /Dest array arrives flipped into page
    space, a NAMED destination arrives as the raw PDF number. PDFium is raw for
    both. Without normalisation the two backends disagree by 501pt on c8.
  * a /Fit destination carries no point at all, and must not be read as y=0.

    python tests/test_internal_links.py
"""
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.convert import convert                       # noqa: E402
from exactdoc.docxout import _anchor_name, _plan_bookmarks  # noqa: E402
from exactdoc.layout import DocLayout, Chunk, PageLayout, Para, Run  # noqa: E402
from exactdoc.model import LinkDest                        # noqa: E402
from exactdoc.options import PDFIUM_GDOCS_CANDIDATE, PRODUCT  # noqa: E402
from exactdoc.parse_pdfium import parse_pdf as parse_pdfium  # noqa: E402

C8 = os.path.join(ROOT, "testkit", "fixtures", "c8_toc_links.pdf")

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                        # pragma: no cover
    _canvas = None
try:
    from exactdoc.parse import parse_pdf as parse_pymupdf
except ImportError:                                        # pragma: no cover
    parse_pymupdf = None


def _goto_pdf(path):
    """A direct /Dest GoTo whose destination is a point on the same page."""
    c = _canvas.Canvas(path, pagesize=(612, 792))
    c.setFont("Helvetica", 12)
    c.bookmarkHorizontalAbsolute("sec1", 600)   # /XYZ 0 600 -> top-left y 192
    c.drawString(100, 600, "Section One")
    c.drawString(100, 500, "jump")
    c.linkAbsolute("jump", "sec1", (100, 495, 140, 515))
    c.save()
    return path


def _crosspage_pdf(path):
    """A link on page 1 whose destination is a point on page 2."""
    c = _canvas.Canvas(path, pagesize=(612, 792))
    c.setFont("Helvetica", 12)
    c.drawString(100, 700, "go to chapter two")
    c.linkAbsolute("go", "ch2", (100, 695, 240, 715))
    c.showPage()
    c.setFont("Helvetica", 12)
    c.bookmarkHorizontalAbsolute("ch2", 500)    # page 2, top-left y 292
    c.drawString(100, 500, "Chapter Two")
    c.save()
    return path


def _para(top, bottom, text="x"):
    p = Para(runs=[Run(text=text, font="Helvetica", size=10, color="#000000")])
    p.bbox = (61.5, top, 300.0, bottom)
    return p


def _layout(paras):
    lay = DocLayout(src_path="")
    pg = PageLayout(number=1)
    ch = Chunk(n_cols=1)
    ch.elements = list(paras)
    pg.chunks = [ch]
    lay.pages = [pg]
    return lay


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class DestinationExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = _goto_pdf(os.path.join(cls._dir.name, "goto.pdf"))

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def _dests_of(self, path, parse):
        ir = parse(path, keep_image_data=False)
        return [lk["dest"] for p in ir.pages for lk in p.links if "dest" in lk]

    def _dests(self, parse):
        return self._dests_of(self.pdf, parse)

    def test_pdfium_resolves_the_destination_into_top_left_space(self):
        # /XYZ 0 600 on a 792pt page is y=192.0 with the origin at the top.
        self.assertEqual(self._dests(parse_pdfium),
                         [LinkDest(page=0, x=0.0, y=192.0)])

    def test_both_backends_agree_on_a_direct_destination(self):
        if parse_pymupdf is None:                          # pragma: no cover
            self.skipTest("PyMuPDF is not installed")
        self.assertEqual(self._dests(parse_pymupdf), self._dests(parse_pdfium))

    def test_a_destination_on_another_page_keeps_its_page_index(self):
        path = _crosspage_pdf(os.path.join(self._dir.name, "cross.pdf"))
        got = self._dests_of(path, parse_pdfium)
        self.assertEqual(got, [LinkDest(page=1, x=0.0, y=292.0)])
        if parse_pymupdf is not None:
            self.assertEqual(self._dests_of(path, parse_pymupdf), got)

    def test_a_cross_page_destination_anchors_on_the_target_page(self):
        path = _crosspage_pdf(os.path.join(self._dir.name, "cross2.pdf"))
        out = os.path.join(self._dir.name, "cross.docx")
        convert(path, out, options=PDFIUM_GDOCS_CANDIDATE)
        with zipfile.ZipFile(out) as z:
            doc = z.read("word/document.xml").decode("utf-8")
        anchors = re.findall(r'<w:hyperlink w:anchor="([^"]+)"', doc)
        names = re.findall(r'<w:bookmarkStart[^>]*w:name="([^"]+)"', doc)
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0], "exactdoc_dest_p1_29200")
        self.assertIn(anchors[0], names)

    def test_the_anchor_span_carries_the_destination_not_a_uri(self):
        ir = parse_pdfium(self.pdf, keep_image_data=False)
        tagged = [(s.text, s.link, s.dest) for p in ir.pages for b in p.blocks
                  for l in b.lines for s in l.spans if s.dest or s.link]
        self.assertEqual(tagged,
                         [("jump", None, LinkDest(page=0, x=0.0, y=192.0))])


class NamedDestinationsOnC8(unittest.TestCase):
    """c8's destinations are NAMED (`/Dest /s1`), the trap case."""

    def test_both_backends_agree_to_the_decimal(self):
        if parse_pymupdf is None:                          # pragma: no cover
            self.skipTest("PyMuPDF is not installed")
        want = [lk["dest"] for p in parse_pymupdf(C8, keep_image_data=False).pages
                for lk in p.links if "dest" in lk]
        got = [lk["dest"] for p in parse_pdfium(C8, keep_image_data=False).pages
               for lk in p.links if "dest" in lk]
        self.assertEqual(want, got)
        self.assertEqual([d.y for d in got], [145.5, 235.5, 333.75])
        self.assertEqual([d.page for d in got], [0, 0, 0])


class AnchoringRule(unittest.TestCase):
    def test_destination_inside_an_element_selects_that_element(self):
        # The common case: /XYZ names the target's top edge, which lands just
        # inside it once font ascent is counted. "Nearest at-or-below" alone
        # would skip it and take the following paragraph.
        first, second = _para(179.1, 195.6, "target"), _para(220.0, 240.0, "after")
        lay = _layout([first, second])
        lay.pages[0].chunks[0].elements[0].runs[0].dest = LinkDest(0, 0.0, 192.0)
        _plan_bookmarks(lay)
        self.assertTrue(hasattr(first, "_bookmark"))
        self.assertFalse(hasattr(second, "_bookmark"))

    def test_destination_in_a_gap_selects_the_next_element_below(self):
        first, second = _para(100.0, 120.0), _para(200.0, 220.0)
        lay = _layout([first, second])
        first.runs[0].dest = LinkDest(0, 0.0, 150.0)
        _plan_bookmarks(lay)
        self.assertFalse(hasattr(first, "_bookmark"))
        self.assertTrue(hasattr(second, "_bookmark"))

    def test_destination_below_all_content_selects_the_last_element(self):
        first, second = _para(100.0, 120.0), _para(200.0, 220.0)
        lay = _layout([first, second])
        first.runs[0].dest = LinkDest(0, 0.0, 700.0)
        _plan_bookmarks(lay)
        self.assertTrue(hasattr(second, "_bookmark"))

    def test_ties_are_broken_by_flow_order(self):
        # Two elements share a top edge; the earlier one in flow order wins.
        first, second = _para(200.0, 220.0, "first"), _para(200.0, 220.0, "second")
        lay = _layout([first, second])
        first.runs[0].dest = LinkDest(0, 0.0, 205.0)
        _plan_bookmarks(lay)
        self.assertTrue(hasattr(first, "_bookmark"))
        self.assertFalse(hasattr(second, "_bookmark"))

    def test_two_destinations_on_one_element_share_one_bookmark(self):
        # Otherwise the element carries only the last name minted and every
        # other anchor points at a bookmark that was never written.
        target, other = _para(200.0, 260.0, "target"), _para(300.0, 320.0)
        lay = _layout([target, other])
        target.runs[0].dest = LinkDest(0, 0.0, 210.0)
        other.runs[0].dest = LinkDest(0, 0.0, 250.0)
        anchors, ids = _plan_bookmarks(lay)
        self.assertEqual(len(set(anchors.values())), 1)
        self.assertEqual(set(anchors.values()), set(ids))
        self.assertEqual(getattr(target, "_bookmark"), list(ids)[0])
        self.assertFalse(hasattr(other, "_bookmark"))

    def test_every_planned_anchor_has_an_id_and_an_owner(self):
        first, second = _para(100.0, 120.0), _para(200.0, 220.0)
        lay = _layout([first, second])
        first.runs[0].dest = LinkDest(0, 0.0, 110.0)
        second.runs[0].dest = LinkDest(0, 0.0, 210.0)
        anchors, ids = _plan_bookmarks(lay)
        self.assertEqual(sorted(set(anchors.values())), sorted(ids))
        owned = {getattr(el, "_bookmark", None) for el in (first, second)}
        self.assertEqual(owned, set(ids))

    def test_anchor_names_are_deterministic_and_distinguish_points(self):
        a = _anchor_name(LinkDest(0, 0.0, 145.5))
        self.assertEqual(a, _anchor_name(LinkDest(0, 99.0, 145.5)))  # x is not
        self.assertEqual(a, "exactdoc_dest_p0_14550")
        self.assertNotEqual(a, _anchor_name(LinkDest(1, 0.0, 145.5)))
        self.assertNotEqual(a, _anchor_name(LinkDest(0, 0.0, 145.51)))
        self.assertTrue(re.match(r"^[A-Za-z][A-Za-z0-9_]*$", a))
        self.assertLessEqual(len(a), 40)   # Word's bookmark-name limit


class WriterEmitsInternalLinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.xml = {}
        for opts in (PDFIUM_GDOCS_CANDIDATE,
                     PRODUCT.replace(oracle="none", refine_rounds=0)):
            out = os.path.join(cls._dir.name, "c8_%s.docx" % opts.backend)
            convert(C8, out, options=opts)
            with zipfile.ZipFile(out) as z:
                cls.xml[opts.backend] = z.read("word/document.xml").decode("utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_three_internal_anchors_and_three_bookmarks(self):
        for backend, doc in self.xml.items():
            anchors = re.findall(r'<w:hyperlink w:anchor="([^"]+)"', doc)
            starts = re.findall(r'<w:bookmarkStart[^>]*w:name="([^"]+)"', doc)
            self.assertEqual(len(anchors), 3, backend)
            self.assertEqual(len(starts), 3, backend)
            self.assertEqual(len(re.findall(r"<w:bookmarkEnd", doc)), 3, backend)

    def test_every_anchor_resolves_to_a_bookmark(self):
        for backend, doc in self.xml.items():
            anchors = set(re.findall(r'<w:hyperlink w:anchor="([^"]+)"', doc))
            names = set(re.findall(r'<w:bookmarkStart[^>]*w:name="([^"]+)"', doc))
            self.assertTrue(anchors <= names, "%s: %s" % (backend, anchors - names))

    def test_bookmark_ids_are_unique(self):
        for backend, doc in self.xml.items():
            ids = re.findall(r'<w:bookmarkStart w:id="(\d+)"', doc)
            self.assertEqual(len(ids), len(set(ids)), backend)

    def test_external_links_still_use_relationships(self):
        for backend, doc in self.xml.items():
            self.assertEqual(len(re.findall(r'<w:hyperlink r:id=', doc)), 3,
                             backend)

    def test_both_backends_anchor_at_the_same_places(self):
        got = {}
        for backend, doc in self.xml.items():
            got[backend] = sorted(
                re.findall(r'<w:bookmarkStart[^>]*w:name="([^"]+)"', doc))
        self.assertEqual(len(set(map(tuple, got.values()))), 1, got)

    def test_internal_link_text_keeps_the_sources_own_styling(self):
        # c8's table of contents is #123a5e with no underline. Word's Hyperlink
        # character style would repaint it blue and underline it, so the writer
        # must not reach for it -- the run carries its own rPr instead.
        for backend, doc in self.xml.items():
            for m in re.finditer(
                    r'<w:hyperlink w:anchor="[^"]*">(.*?)</w:hyperlink>', doc, re.S):
                frag = m.group(1)
                self.assertNotIn("w:rStyle", frag, backend)
                self.assertIn("123A5E", frag.upper(), backend)
                self.assertNotIn("<w:u ", frag, backend)


if __name__ == "__main__":
    unittest.main()
