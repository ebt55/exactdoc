"""PDFium link extraction: the IR carries the page's URI link ANNOTATIONS.

parse_pdfium used to call FPDFLink_LoadWebLinks, which scans extracted TEXT for
URL-shaped substrings.  That is a different question from "what did the producer
link", and it is wrong in both directions: measured over the 32 corpus
documents it missed every link whose anchor text is a word rather than a URL
(c8_toc_links 1 of 3, 01_whitepaper_market 0 of 1, 04_exec_brief 0 of 1,
x05_lo_quotes_notes 1 of 2) and invented 17 spurious rects on
x11_chrome_toc_headings, which has 20 URL-shaped strings and 3 real
annotations.

PyMuPDF's page.get_links() reads /Annots, and the IR contract is PyMuPDF's.

    python tests/test_pdfium_links.py
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.parse_pdfium import parse_pdf  # noqa: E402

C8 = os.path.join(ROOT, "testkit", "fixtures", "c8_toc_links.pdf")

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None


def _synthetic(path):
    """One page carrying a URI link, a GoTo link, and unlinked URL text."""
    c = _canvas.Canvas(path, pagesize=(612, 792))
    c.setFont("Helvetica", 12)
    # a URI annotation over ordinary prose
    c.drawString(100, 700, "the specification")
    c.linkURL("https://example.com/spec", (100, 695, 210, 715), relative=0)
    # an internal GoTo annotation
    c.bookmarkPage("sec1")
    c.drawString(100, 600, "Section One")
    c.drawString(100, 500, "jump to section")
    c.linkAbsolute("jump", "sec1", (100, 495, 190, 515))
    # URL-shaped text that the producer did NOT link
    c.drawString(100, 400, "see https://example.com/unlinked for more")
    c.save()
    return path


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class PdfiumLinkAnnotations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = _synthetic(os.path.join(cls._dir.name, "links.pdf"))
        cls.ir = parse_pdf(cls.pdf, keep_image_data=False)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def _links(self):
        return [lk for p in self.ir.pages for lk in p.links]

    def test_uri_annotation_becomes_a_link(self):
        self.assertEqual([lk["uri"] for lk in self._links() if "uri" in lk],
                         ["https://example.com/spec"])

    def test_goto_annotation_without_a_point_yields_no_destination(self):
        # `bookmarkPage` writes a /Fit destination: a whole-page view carrying
        # no point at all. FPDFDest_GetLocationInPage reports has_y=0 for it,
        # and reporting y=0 anyway would anchor the link to the top of the page
        # as though that had been measured. It is skipped instead.
        self.assertEqual([lk for lk in self._links() if "dest" in lk], [])
        self.assertEqual(len(self._links()), 1)

    def test_url_text_without_an_annotation_is_not_a_link(self):
        # The removed weblink scan would have reported this one.
        for lk in self._links():
            self.assertNotIn("unlinked", lk.get("uri") or "")

    def test_rect_is_flipped_into_the_irs_top_left_origin(self):
        # /Rect [100 695 210 715] on a 792pt page.
        bbox = self._links()[0]["bbox"]
        self.assertAlmostEqual(bbox[0], 100.0, delta=0.5)
        self.assertAlmostEqual(bbox[1], 792 - 715, delta=0.5)
        self.assertAlmostEqual(bbox[2], 210.0, delta=0.5)
        self.assertAlmostEqual(bbox[3], 792 - 695, delta=0.5)

    def test_span_under_the_rect_carries_the_uri(self):
        tagged = [(s.text, s.link) for p in self.ir.pages for b in p.blocks
                  for l in b.lines for s in l.spans if s.link]
        self.assertEqual(tagged, [("the specification",
                                   "https://example.com/spec")])


class PdfiumLinksOnC8(unittest.TestCase):
    """c8_toc_links carries six /Link annotations: three URI, three GoTo."""

    @classmethod
    def setUpClass(cls):
        cls.ir = parse_pdf(C8, keep_image_data=False)

    def test_recovers_all_three_uri_links(self):
        self.assertEqual(sorted(lk["uri"] for p in self.ir.pages
                                for lk in p.links if "uri" in lk),
                         ["https://example.com/rfc-2119",
                          "https://example.com/spec",
                          "mailto:team@example.com"])

    def test_uri_and_goto_are_separate_entries_never_mixed(self):
        entries = [lk for p in self.ir.pages for lk in p.links]
        self.assertEqual(len(entries), 6)
        self.assertEqual(sum(1 for lk in entries if "uri" in lk), 3)
        self.assertEqual(sum(1 for lk in entries if "dest" in lk), 3)
        # a consumer never has to sniff a string to tell them apart
        for lk in entries:
            self.assertNotEqual("uri" in lk, "dest" in lk)

    def test_anchor_text_is_tagged_not_just_the_url_shaped_word(self):
        # `the specification` and `RFC` are ordinary words; only
        # `team@example.com` is URL-shaped, and it was all the text scan found.
        tagged = {s.text: s.link for p in self.ir.pages for b in p.blocks
                  for l in b.lines for s in l.spans if s.link}
        self.assertEqual(tagged, {
            "the specification": "https://example.com/spec",
            "RFC": "https://example.com/rfc-2119",
            "team@example.com": "mailto:team@example.com"})

    def test_matches_the_pymupdf_reference_backend(self):
        try:
            from exactdoc.parse import parse_pdf as parse_reference
        except ImportError:                            # pragma: no cover
            self.skipTest("PyMuPDF is not installed")
        want = parse_reference(C8, keep_image_data=False)
        got = self.ir
        for a, b in zip(want.pages, got.pages):
            self.assertEqual([lk.get("uri") for lk in a.links],
                             [lk.get("uri") for lk in b.links])
            self.assertEqual([lk.get("dest") for lk in a.links],
                             [lk.get("dest") for lk in b.links])
            for la, lb in zip(a.links, b.links):
                for i in range(4):
                    self.assertAlmostEqual(la["bbox"][i], lb["bbox"][i],
                                           delta=0.5)


if __name__ == "__main__":
    unittest.main()
