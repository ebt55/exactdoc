"""Text and URIs the IR hands the writer must be serialisable.

PDFium returns the raw CHARACTER CODE for a glyph whose font gives it no usable
ToUnicode entry. On real-world PDFs that code is a C0 control character, and
lxml refuses to put one in a w:t node -- so `write_docx` raised
`ValueError: All strings must be XML compatible` and the whole document failed
to serialise. It blocked every conversion of the real-world tranche.

The contract is enforced in the parsers, not the writer: see
model.xml_safe_text for why.

    python tests/test_xml_safe_text.py
"""
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.convert import convert                      # noqa: E402
from exactdoc.model import xml_safe_text, xml_safe_uri     # noqa: E402
from exactdoc.options import PDFIUM_GDOCS_CANDIDATE, PRODUCT  # noqa: E402
from exactdoc.parse_pdfium import parse_pdf as parse_pdfium   # noqa: E402

EXPANSION = os.path.join(ROOT, "testkit", "fixtures_expansion")
# A real Adobe PDFMaker document: 15 spans carry U+0002 under PDFium, none
# under PyMuPDF. Outside the y06/y08/y12/y13 image-crash set.
Y_DOC = os.path.join(EXPANSION, "y10_nist_fips180.pdf")

ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                        # pragma: no cover
    _canvas = None
try:
    from exactdoc.parse import parse_pdf as parse_pymupdf
except ImportError:                                        # pragma: no cover
    parse_pymupdf = None


class XmlSafeTextContract(unittest.TestCase):
    def test_matches_what_lxml_will_actually_accept(self):
        # The boundary is probed, not assumed: whatever lxml refuses must be
        # removed, and whatever it accepts must survive. This is the whole
        # contract, and it is why the C1 block (0x7f-0x9f) is NOT stripped.
        from lxml import etree
        for cp in list(range(0x100)) + [0xFFFD, 0xFFFE, 0xFFFF]:
            ch = chr(cp)
            el = etree.Element("t")
            try:
                el.text = ch
            except ValueError:
                self.assertEqual(xml_safe_text(ch), "",
                                 "lxml rejects %s; sanitiser must drop it" % hex(cp))
            else:
                self.assertEqual(xml_safe_text(ch), ch,
                                 "lxml accepts %s; sanitiser must keep it" % hex(cp))

    def test_keeps_the_whitespace_xml_allows(self):
        self.assertEqual(xml_safe_text("a\tb\nc\rd"), "a\tb\nc\rd")

    def test_drops_the_control_character_the_corpus_produces(self):
        self.assertEqual(xml_safe_text("SHA\x02"), "SHA")
        self.assertEqual(xml_safe_text("a\x01b\x1fc"), "abc")

    def test_keeps_ordinary_text_untouched(self):
        for s in ("", "plain", "café", "你好", "a b  c"):
            self.assertEqual(xml_safe_text(s), s)


class XmlSafeUriContract(unittest.TestCase):
    def test_percent_encodes_rather_than_deleting(self):
        # A URI is defined over octets; the spelling for one that cannot appear
        # literally is percent-encoding (RFC 3986 2.1), not deletion -- deleting
        # would silently change where the link points.
        self.assertEqual(xml_safe_uri("https://e.com/a\x02b"),
                         "https://e.com/a%02b")

    def test_leaves_a_clean_uri_alone(self):
        for u in ("https://example.com/spec", "mailto:team@example.com"):
            self.assertEqual(xml_safe_uri(u), u)

    def test_empty_and_none_become_none(self):
        self.assertIsNone(xml_safe_uri(None))
        self.assertIsNone(xml_safe_uri(""))


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class ControlCharactersInASyntheticUri(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = os.path.join(cls._dir.name, "ctrl_uri.pdf")
        c = _canvas.Canvas(cls.pdf, pagesize=(612, 792))
        c.setFont("Helvetica", 12)
        c.drawString(100, 700, "click here")
        c.linkURL("https://example.com/a\x02b", (100, 695, 200, 715), relative=0)
        c.save()

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_both_backends_percent_encode_it(self):
        want = ["https://example.com/a%02b"]
        got = [lk["uri"] for p in parse_pdfium(self.pdf, keep_image_data=False).pages
               for lk in p.links if "uri" in lk]
        self.assertEqual(got, want)
        if parse_pymupdf is not None:
            got_mu = [lk["uri"] for p in parse_pymupdf(
                self.pdf, keep_image_data=False).pages
                for lk in p.links if "uri" in lk]
            self.assertEqual(got_mu, want)

    def test_it_converts_and_the_relationship_target_is_encoded(self):
        out = os.path.join(self._dir.name, "ctrl_uri.docx")
        convert(self.pdf, out, options=PDFIUM_GDOCS_CANDIDATE)
        with zipfile.ZipFile(out) as z:
            rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
        self.assertIn("https://example.com/a%02b", rels)
        self.assertNotIn("\x02", rels)


class RealProducerDocumentConverts(unittest.TestCase):
    """y10_nist_fips180: Adobe PDFMaker, 15 U+0002 spans under PDFium."""

    def test_no_span_reaches_the_ir_with_an_illegal_character(self):
        ir = parse_pdfium(Y_DOC, keep_image_data=False)
        offenders = [s.text for p in ir.pages for b in p.blocks
                     for l in b.lines for s in l.spans if ILLEGAL.search(s.text)]
        self.assertEqual(offenders, [])

    def test_conversion_completes_on_both_backends(self):
        with tempfile.TemporaryDirectory() as d:
            for opts in (PDFIUM_GDOCS_CANDIDATE,
                         PRODUCT.replace(oracle="none", refine_rounds=0)):
                out = os.path.join(d, "y10_%s.docx" % opts.backend)
                convert(Y_DOC, out, options=opts)      # used to raise
                self.assertTrue(os.path.getsize(out) > 0)
                with zipfile.ZipFile(out) as z:
                    self.assertNotIn(
                        "\x02", z.read("word/document.xml").decode("utf-8"))


class GatedCorpusIsUnaffected(unittest.TestCase):
    def test_sanitiser_is_a_no_op_on_a_gated_fixture(self):
        # Byte-identity on the gated 16 rests on the sanitiser never firing
        # there. Verified over all 16 x 2 backends out of band; this pins the
        # property cheaply so a future widening cannot pass unnoticed.
        src = os.path.join(ROOT, "testkit", "fixtures", "c8_toc_links.pdf")
        ir = parse_pdfium(src, keep_image_data=False)
        for p in ir.pages:
            for lk in p.links:
                if "uri" in lk:
                    self.assertEqual(xml_safe_uri(lk["uri"]), lk["uri"])
            for b in p.blocks:
                for l in b.lines:
                    for s in l.spans:
                        self.assertEqual(xml_safe_text(s.text), s.text)


class GotoDestRobustness(unittest.TestCase):
    """PyMuPDF's link dict does not promise the shapes the happy path assumes."""

    def setUp(self):
        if parse_pymupdf is None:                      # pragma: no cover
            self.skipTest("PyMuPDF is not installed")

    def _dest(self, lk):
        from exactdoc.parse import _goto_dest

        class _Rect:
            height = 792.0

        class _Page:
            rect = _Rect()

        class _Doc:
            def __getitem__(self, i):
                return _Page()

        return _goto_dest(_Doc(), lk)

    def test_a_string_page_does_not_raise(self):
        # Measured on y03_nist_fips197: a half-resolved named destination is
        # reported as {'kind': 4, 'page': '44', 'view': 'Fit'} -- page is a
        # STRING and there is no point. Comparing it to 0 raised TypeError and
        # took the whole conversion with it.
        self.assertIsNone(self._dest({"kind": 4, "page": "44", "view": "Fit"}))

    def test_a_missing_point_is_not_a_destination(self):
        self.assertIsNone(self._dest({"kind": 4, "page": 3}))

    def test_a_usable_named_destination_still_resolves(self):
        class _Pt:
            x, y = 0.0, 646.5
        got = self._dest({"kind": 4, "page": 0, "to": _Pt()})
        self.assertEqual((got.page, got.y), (0, 792.0 - 646.5))


if __name__ == "__main__":
    unittest.main()
