"""Running headers, footers and page numbering (audit finding 3: B1, B2, B3, B26).

What these pin down, each measured on a real document first:

* B1 -- the default header/footer comes from the page carrying the MODAL
  furniture, not from page 2. NIST SP 800-171's page 2 is its title page; its
  running head (111 pages) was consumed from the body and no part was written.
* B2 -- furniture is found beyond the fixed 62/64pt bands when the evidence
  says so: the RFC footer 105pt above the bottom of A4 carries the page's own
  number. Repetition alone does not qualify out there, and neither does a
  numbered row that is not part of an unbroken chain from the paper edge.
* B3 -- printed numbers that differ from the physical index (roman front
  matter, a restart at 1) become live PAGE fields in a section whose
  `w:pgNumType` states where the count starts. "v3.2" is still never a field.
* B26 -- the body starts below the header in every renderer: margin_t is
  never left inside the header's extent, and a page-sized background no longer
  sets it.

    python tests/test_running_furniture.py
"""
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lxml import etree                                     # noqa: E402

from exactdoc import furniture as F                        # noqa: E402
from exactdoc.docxout import write_docx                    # noqa: E402
from exactdoc.infer import detect_hf, infer                # noqa: E402
from exactdoc.layout import (Chunk, DocLayout, HFPart, HFSection,  # noqa: E402
                             PageLayout, Para, Run)
from exactdoc.model import DocIR, DrawCmd, Line, PageIR, Span, TextBlock  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                        # pragma: no cover
    _canvas = None

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo "
         "lima mike november oscar papa quebec romeo sierra tango uniform "
         "victor whiskey xray yankee zulu").split()


def _ln(text, x0, y0, size=10.0, x1=None):
    x1 = x1 if x1 is not None else x0 + 0.5 * size * len(text)
    bb = (x0, y0, x1, y0 + 1.1 * size)
    s = Span(text, "Helvetica", size, "#000000", False, False, False, False,
             False, bb, (x0, y0 + size))
    return Line([s], bb)


def _body(pg, top=100.0, n=20, x0=72.0):
    """Body lines whose text never repeats across pages and carries no digit."""
    out = []
    for i in range(n):
        w = [WORDS[(pg * 7 + i * 3 + k) % len(WORDS)] for k in range(8)]
        out.append(_ln(" ".join(w), x0, top + 14.0 * i, x1=520.0))
    return out


def _page(n, lines, W=612.0, H=792.0, drawings=()):
    return PageIR(number=n, width=W, height=H,
                  blocks=[TextBlock([l], l.bbox) for l in lines],
                  drawings=list(drawings))


def _text(part):
    if part is None:
        return None
    return " | ".join("".join("{%s}" % r.field if r.field else r.text
                              for r in el.runs)
                      for el in part.elements if isinstance(el, Para))


class NumberTokens(unittest.TestCase):
    def test_digits_and_roman_words(self):
        toks = [(f, v) for _, _, f, v in F.num_tokens("PAGE vii of 28")]
        self.assertEqual(toks, [("lowerRoman", 7), ("decimal", 28)])

    def test_version_string_v_is_not_a_numeral(self):
        # the "v" is glued to the digit: not a word, so not a roman token
        toks = [(f, v) for _, _, f, v in F.num_tokens("SDK v3.2")]
        self.assertEqual(toks, [("decimal", 3), ("decimal", 2)])

    def test_only_valid_single_case_numerals(self):
        self.assertEqual(F.num_tokens("Mix did LCD"), [])
        self.assertEqual([v for *_, v in F.num_tokens("MIX XIV")], [1009, 14])

    def test_label_parsing(self):
        self.assertEqual(F.parse_label("xii"), ("lowerRoman", 12))
        self.assertEqual(F.parse_label("17"), ("decimal", 17))
        self.assertIsNone(F.parse_label("Front Cover"))
        self.assertIsNone(F.parse_label("A-3"))


class PageNumberModel(unittest.TestCase):
    def _front_matter(self):
        ev = [(pg, "lowerRoman", pg - 3, True) for pg in range(4, 14)]
        ev += [(pg, "decimal", pg - 13, True) for pg in range(14, 30)]
        return ev

    def test_offsets_and_formats_are_believed_over_runs(self):
        pn = F.page_number_model(self._front_matter())
        self.assertEqual(pn[4], ("lowerRoman", -3))
        self.assertEqual(pn[13], ("lowerRoman", -3))
        self.assertEqual(pn[14], ("decimal", -13))

    def test_two_pages_at_an_offset_are_a_coincidence(self):
        # "Step 1" / "Step 2" on consecutive pages 5 and 6
        pn = F.page_number_model([(5, "decimal", 1, True), (6, "decimal", 2, True)])
        self.assertEqual(pn, {})

    def test_labels_corroborate_a_short_run(self):
        ev = [(5, "decimal", 1, True), (6, "decimal", 2, True)]
        labels = [None, None, None, None, "1", "2"]
        self.assertEqual(F.page_number_model(ev, labels),
                         {5: ("decimal", -4), 6: ("decimal", -4)})

    def test_offset_zero_keeps_the_historical_two_page_rule(self):
        pn = F.page_number_model([(2, "decimal", 2, True), (5, "decimal", 5, True)])
        self.assertEqual(pn, {2: ("decimal", 0), 5: ("decimal", 0)})

    def test_labels_carry_a_run_over_a_silent_page(self):
        # printed from page 16, labelled from 15 (a chapter opener)
        ev = [(pg, "decimal", pg - 14, True) for pg in range(16, 22)]
        labels = [None] * 14 + [str(i) for i in range(1, 8)]
        pn = F.page_number_model(ev, labels)
        self.assertEqual(pn[15], ("decimal", -14))
        self.assertNotIn(14, pn)


class NumberingSections(unittest.TestCase):
    def test_front_matter_after_an_unnumbered_lead_in(self):
        pn = {pg: ("lowerRoman", -3) for pg in range(4, 14)}
        pn.update({pg: ("decimal", -13) for pg in range(14, 30)})
        self.assertEqual(F.numbering_sections(pn, 30),
                         [(1, None, None), (4, "lowerRoman", 1), (14, "decimal", 1)])

    def test_plain_arabic_needs_no_section(self):
        pn = {pg: ("decimal", 0) for pg in range(1, 9)}
        self.assertEqual(F.numbering_sections(pn, 8), [])

    def test_restarts(self):
        # a slip opinion: every opinion restarts at 1
        pn = {pg: ("decimal", 0) for pg in range(1, 9)}
        pn.update({pg: ("decimal", -8) for pg in range(9, 20)})
        self.assertEqual(F.numbering_sections(pn, 19),
                         [(1, "decimal", 1), (9, "decimal", 1)])

    def test_printed_parity_follows_the_printed_number(self):
        pn = {pg: ("decimal", -8) for pg in range(9, 20)}
        par = F.printed_parity(pn, 19)
        self.assertEqual(par[9], 1)      # printed "1": a recto
        self.assertEqual(par[10], 0)


class TitlePageDoesNotLoseTheParts(unittest.TestCase):
    """B1: page 2 carries no furniture; the modal page does."""

    def _ir(self):
        pages = [_page(1, [_ln("Agency Report", 200, 300, size=24)]),
                 _page(2, [_ln("Title page notice", 72, 400)])]
        for pg in range(3, 11):
            lines = [_ln("Agency Report Series", 72, 35, size=9)]
            lines += _body(pg)
            lines += [_ln("Page %d" % pg, 280, 745, size=9)]
            pages.append(_page(pg, lines))
        return DocIR(path="b1.pdf", pages=pages)

    def test_parts_are_built_from_the_modal_page(self):
        lay = infer(self._ir())
        self.assertEqual(_text(lay.header_default), "Agency Report Series")
        self.assertEqual(_text(lay.footer_default), "Page {PAGE}")
        self.assertTrue(lay.different_first)

    def test_a_folio_less_first_page_is_not_given_the_footer(self):
        lay = infer(self._ir())
        self.assertIsNone(lay.footer_first)


class ExtendedFurnitureBand(unittest.TestCase):
    """B2: an RFC footer 105pt above the bottom of A4."""
    H = 841.0

    def _ir(self, footer, below=None, n=8):
        pages = []
        for pg in range(1, n + 1):
            lines = _body(pg, top=80.0, n=30)
            y = self.H - 105.0 - 11.0
            for x, t in footer(pg):
                lines.append(_ln(t, x, y))
            if below:
                # outside the legacy 64pt band: plain body text, not furniture
                lines.append(_ln(below(pg), 72, self.H - 85.0))
            pages.append(_page(pg, lines, W=595.0, H=self.H))
        return DocIR(path="b2.pdf", pages=pages)

    @staticmethod
    def _rfc(pg):
        return [(72, "Fielding, et al."), (250, "Standards Track"),
                (470, "[Page %d]" % pg)]

    def test_numbered_footer_row_is_furniture(self):
        lay = infer(self._ir(self._rfc))
        self.assertEqual(_text(lay.footer_default),
                         "Fielding, et al.\tStandards Track\t[Page {PAGE}]")
        self.assertAlmostEqual(lay.footer_default.distance, 105.0, delta=0.5)
        flow = [el.text for pl in lay.pages for ch in pl.chunks
                for el in ch.elements if isinstance(el, Para)]
        self.assertFalse(any("Standards Track" in t for t in flow))

    def test_repetition_alone_is_not_furniture_out_there(self):
        # the same row without the page's number: could be a repeated table
        # header; it stays in the body
        hf = detect_hf(self._ir(lambda pg: [(72, "Fielding, et al."),
                                            (250, "Standards Track")]))
        self.assertEqual(sum(len(v) for v in hf["consumed_text"].values()), 0)

    def test_chain_from_the_edge_is_required(self):
        # a non-furniture line sits between the numbered row and the edge
        hf = detect_hf(self._ir(self._rfc,
                                below=lambda pg: " ".join(WORDS[pg:pg + 5])))
        self.assertEqual(sum(len(v) for v in hf["consumed_text"].values()), 0)

    def test_body_margin_bottom_clears_the_footer(self):
        lay = infer(self._ir(self._rfc))
        d = lay.footer_default
        self.assertGreaterEqual(lay.margin_b + 1e-6, d.distance + 9.0)


class PageNumbering(unittest.TestCase):
    """B3: roman front matter, then arabic restarting at 1."""

    def _ir(self):
        pages = [_page(1, [_ln("Cover", 250, 300, size=30)]),
                 _page(2, [_ln("Inside cover notice", 72, 400)])]
        romans = ["i", "ii", "iii", "iv"]
        for pg in range(3, 15):
            num = romans[pg - 3] if pg < 7 else str(pg - 6)
            lines = [_ln("SENTINEL SDK v3.2", 72, 35, size=9)]
            lines += _body(pg)
            lines += [_ln("PAGE " + num, 280, 745, size=9)]
            pages.append(_page(pg, lines))
        return DocIR(path="b3.pdf", pages=pages)

    def test_sections_state_the_count(self):
        lay = infer(self._ir())
        self.assertEqual([(s.start_page, s.num_fmt, s.num_start, s.blank)
                          for s in lay.hf_sections],
                         [(1, None, None, True), (3, "lowerRoman", 1, False),
                          (7, "decimal", 1, False)])

    def test_page_numbers_are_fields_and_versions_are_not(self):
        lay = infer(self._ir())
        self.assertEqual(_text(lay.footer_default), "PAGE {PAGE}")
        self.assertEqual(_text(lay.header_default), "SENTINEL SDK v3.2")


class VersoRecto(unittest.TestCase):
    """Alternating running heads (a slip opinion), 114pt down the page."""

    def _ir(self, n=14):
        pages = []
        for pg in range(1, n + 1):
            if pg % 2:
                head = _ln("Cite as: 603 U. S. ____ (2024) %d" % pg, 244, 114,
                           size=9, x1=455)
            else:
                head = _ln("%d LOPER BRIGHT ENTERPRISES v. RAIMONDO" % pg, 156,
                           114, size=9, x1=409)
            pages.append(_page(pg, [head] + _body(pg, top=150.0)))
        return DocIR(path="eo.pdf", pages=pages)

    def test_even_and_odd_parts(self):
        lay = infer(self._ir())
        self.assertTrue(lay.even_odd)
        self.assertEqual(_text(lay.header_default),
                         "Cite as: 603 U. S. ____ (2024) {PAGE}")
        self.assertEqual(_text(lay.header_even),
                         "{PAGE} LOPER BRIGHT ENTERPRISES v. RAIMONDO")

    def test_body_starts_below_the_head(self):
        lay = infer(self._ir())
        self.assertGreaterEqual(lay.margin_t, 114.0 + 9.0)


class BodyOrigin(unittest.TestCase):
    """B26: margin_t is never inside the header, nor set by a background."""

    def _ir(self, background_on=()):
        pages = []
        for pg in range(1, 7):
            lines = [_ln("RFC 9110      HTTP Semantics      June 2022", 72, 35,
                         size=10)]
            lines += _body(pg, top=70.0)
            dr = [DrawCmd("fill", "rect", (0, 0, 595, 841), "#e9e9e9", None,
                          0.0, 1.0, 1)] if pg in background_on else []
            pages.append(_page(pg, lines, W=595.0, H=841.0, drawings=dr))
        return DocIR(path="b26.pdf", pages=pages)

    def test_page_sized_background_does_not_set_the_margin(self):
        lay = infer(self._ir(background_on=(3,)))
        self.assertAlmostEqual(lay.margin_t, 70.0, delta=0.5)

    def test_margin_top_clears_the_header(self):
        lay = infer(self._ir())
        hd = lay.header_default
        self.assertIsNotNone(hd)
        self.assertGreaterEqual(lay.margin_t, hd.distance + 10.0)


def _hf_para(text, field=False):
    runs = [Run(text=text, font="Helvetica", size=9, color="#000000")]
    if field:
        runs.append(Run(text="", font="Helvetica", size=9, color="#000000",
                        field="PAGE"))
    return Para(runs=runs, leading=10.4)


def _write(lay):
    fd, out = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    try:
        write_docx(lay, out)
        z = zipfile.ZipFile(out)
        doc = etree.fromstring(z.read("word/document.xml"))
        settings = etree.fromstring(z.read("word/settings.xml"))
        z.close()
    finally:
        os.remove(out)
    return doc, settings


def _layout(n_pages, cols=None):
    lay = DocLayout(src_path="")
    for pg in range(1, n_pages + 1):
        pl = PageLayout(number=pg)
        ch = Chunk(n_cols=(cols or {}).get(pg, 1))
        ch.elements.append(Para(runs=[Run(text="page %d body" % pg,
                                          font="Helvetica", size=10,
                                          color="#000000")], leading=12.0))
        pl.chunks.append(ch)
        lay.pages.append(pl)
    lay.header_default = HFPart(elements=[_hf_para("Head ")], distance=30.0)
    lay.footer_default = HFPart(elements=[_hf_para("Page ", field=True)],
                                distance=30.0)
    return lay


def _sects(doc):
    return doc.findall(".//" + W_NS + "sectPr")


def _pgnum(sect):
    el = sect.find(W_NS + "pgNumType")
    if el is None:
        return None
    return (el.get(W_NS + "fmt"), el.get(W_NS + "start"))


class WriterNumbering(unittest.TestCase):
    def test_restart_opens_a_section_with_pgnumtype(self):
        lay = _layout(4)
        lay.hf_sections = [HFSection(1, 1, "lowerRoman"), HFSection(3, 1, "decimal")]
        doc, _ = _write(lay)
        s = _sects(doc)
        self.assertEqual(len(s), 2)
        self.assertEqual(_pgnum(s[0]), ("lowerRoman", "1"))
        self.assertEqual(_pgnum(s[1]), ("decimal", "1"))

    def test_column_section_continues_the_count(self):
        # python-docx clones the last sectPr: a restart must not ride along
        lay = _layout(3, cols={3: 2})
        lay.hf_sections = [HFSection(1, 1, "lowerRoman"), HFSection(2, 5, "decimal")]
        doc, _ = _write(lay)
        s = _sects(doc)
        self.assertEqual(_pgnum(s[1]), ("decimal", "5"))
        self.assertEqual(_pgnum(s[2]), ("decimal", None))

    def test_title_page_flag_stays_on_the_first_section(self):
        lay = _layout(3)
        lay.different_first = True
        lay.hf_sections = [HFSection(1, None, None), HFSection(2, 1, "decimal")]
        doc, _ = _write(lay)
        s = _sects(doc)
        self.assertIsNotNone(s[0].find(W_NS + "titlePg"))
        self.assertIsNone(s[1].find(W_NS + "titlePg"))

    def test_blank_lead_in_restates_the_parts_after_it(self):
        lay = _layout(4)
        lay.hf_sections = [HFSection(1, None, None, blank=True),
                           HFSection(3, 1, "lowerRoman")]
        doc, _ = _write(lay)
        s = _sects(doc)
        refs = [len(x.findall(W_NS + "headerReference")) for x in s]
        self.assertEqual(refs, [1, 1])

    def test_even_and_odd_headers(self):
        lay = _layout(4)
        lay.even_odd = True
        lay.header_even = HFPart(elements=[_hf_para("Even head ")], distance=30.0)
        doc, settings = _write(lay)
        self.assertIsNotNone(settings.find(W_NS + "evenAndOddHeaders"))
        kinds = sorted((r.tag.split("}")[1], r.get(W_NS + "type"))
                       for r in _sects(doc)[0]
                       if r.tag in (W_NS + "headerReference",
                                    W_NS + "footerReference"))
        self.assertEqual(kinds, [("footerReference", "default"),
                                 ("footerReference", "even"),
                                 ("headerReference", "default"),
                                 ("headerReference", "even")])

    def test_no_numbering_written_without_sections(self):
        doc, settings = _write(_layout(3))
        self.assertEqual([_pgnum(s) for s in _sects(doc)], [None])
        self.assertIsNone(settings.find(W_NS + "evenAndOddHeaders"))


def _refs(sect):
    return sorted((r.tag.split("}")[1][0], r.get(W_NS + "type")) for r in sect
                  if r.tag in (W_NS + "headerReference", W_NS + "footerReference"))


class WriterPageStyleConsistency(unittest.TestCase):
    """Measured in the canonical LibreOffice: a first-page footer with no
    default footer beside it cost every later page two lines (body bottom
    753.6 -> 729.6), and a first-page header with no default header pushed
    every body top from 58 to 72pt."""

    def test_a_side_without_furniture_gets_no_first_page_reference(self):
        lay = _layout(3)
        lay.footer_default = None          # header-only document
        lay.different_first = True         # page 1 carries no head
        doc, _ = _write(lay)
        self.assertEqual(_refs(_sects(doc)[0]),
                         [("h", "default"), ("h", "first")])

    def test_first_page_only_footer_gets_an_empty_default_beside_it(self):
        lay = _layout(3)
        lay.footer_default = None
        lay.different_first = True
        lay.footer_first = HFPart(elements=[_hf_para("Cover note")], distance=30.0)
        doc, _ = _write(lay)
        self.assertIn(("f", "default"), _refs(_sects(doc)[0]))
        self.assertIn(("f", "first"), _refs(_sects(doc)[0]))

    def test_even_parts_only_for_sides_with_furniture(self):
        lay = _layout(4)
        lay.footer_default = None
        lay.even_odd = True
        lay.header_even = HFPart(elements=[_hf_para("Even head ")], distance=30.0)
        doc, _ = _write(lay)
        self.assertEqual(_refs(_sects(doc)[0]),
                         [("h", "default"), ("h", "even")])


class BottomReserve(unittest.TestCase):
    """The body may run down to the footer's top, as it may run to 14pt from
    the edge when there is no footer."""

    def test_margin_bottom_relaxes_to_the_footer_top(self):
        lay = infer(TitlePageDoesNotLoseTheParts()._ir())
        f = lay.footer_default
        self.assertAlmostEqual(lay.margin_b, f.distance + f.elements[0].leading,
                               delta=0.15)

    def test_refine_lowers_footers_only_when_pages_spill(self):
        from exactdoc.refine import FOOTER_FLOOR_PT, _apply
        lay = infer(TitlePageDoesNotLoseTheParts()._ir())
        before = lay.footer_default.distance
        m = {"spill": [0] * len(lay.pages), "offset": [0.0] * len(lay.pages)}
        _apply(lay, m)
        self.assertEqual(lay.footer_default.distance, before)
        m["spill"][4] = 1
        self.assertTrue(_apply(lay, m))
        self.assertEqual(lay.footer_default.distance, FOOTER_FLOOR_PT)
        self.assertLess(lay.margin_b, FOOTER_FLOOR_PT + 12.0)


class SplitRunsKeepTheirFace(unittest.TestCase):
    def test_pagefields_split_keeps_serif(self):
        from exactdoc.infer import _pagefields
        r = Run(text="Cite as: 603 U. S. 7", font="CenturySchoolbook", size=9,
                color="#000000", serif=True)
        out = _pagefields([r], ["LIT", "PAGE"], [])
        self.assertTrue(all(x.serif for x in out))
        self.assertEqual([x.field for x in out if x.field], ["PAGE"])


@unittest.skipIf(_canvas is None, "reportlab is required to build the PDF")
class EndToEnd(unittest.TestCase):
    """A real PDF: roman front matter, a title page, page labels."""

    def _pdf(self, path):
        c = _canvas.Canvas(path, pagesize=(612, 792))
        romans = ["ii", "iii", "iv"]
        c.addPageLabel(0, style="ROMAN_LOWER")
        c.addPageLabel(4, style="ARABIC", start=1)
        for pg in range(1, 10):
            if pg == 1:
                c.setFont("Helvetica-Bold", 28)
                c.drawString(150, 500, "Field Manual")
            else:
                c.setFont("Helvetica", 9)
                c.drawString(72, 750, "Field Manual for Operators")
                c.setFont("Helvetica", 10)
                for i in range(25):
                    w = [WORDS[(pg * 5 + i * 3 + k) % len(WORDS)] for k in range(9)]
                    c.drawString(72, 690 - 14 * i, " ".join(w))
                c.setFont("Helvetica", 9)
                num = romans[pg - 2] if pg < 5 else str(pg - 4)
                c.drawString(300, 40, num)
            c.showPage()
        c.save()
        return path

    def test_converted_document_numbers_its_pages(self):
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        from exactdoc.parse_pdfium import parse_pdf
        with tempfile.TemporaryDirectory() as td:
            pdf = self._pdf(os.path.join(td, "fm.pdf"))
            labels = parse_pdf(pdf, keep_image_data=False).meta.get("page_labels")
            self.assertEqual(labels[:6], ["i", "ii", "iii", "iv", "1", "2"])
            out = convert(pdf, os.path.join(td, "fm.docx"), options=RAW)
            z = zipfile.ZipFile(out)
            doc = etree.fromstring(z.read("word/document.xml"))
            heads = [etree.tostring(etree.fromstring(z.read(n)), method="text",
                                    encoding="unicode")
                     for n in z.namelist() if n.startswith("word/header")]
            z.close()
        # printed from page 2 ("ii"); the labels carry the roman count back
        # over the folio-less title page, so it starts on page 1 at "i"
        nums = [_pgnum(s) for s in _sects(doc)]
        self.assertEqual(nums, [("lowerRoman", "1"), ("decimal", "1")])
        self.assertTrue(any("Field Manual for Operators" in h for h in heads))


if __name__ == "__main__":
    unittest.main()
