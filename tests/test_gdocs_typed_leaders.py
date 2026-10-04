"""Contents-line dot leaders under the Google Docs profile.

Google Docs draws no tab leaders: x02's contents page came back from Docs with
every one of its 1,277 dots missing while the right tab still placed the page
numbers. Typed dots render (live, 2026-10-04), so the gdocs profile types the
source's own leader, two dots short, before a plain right tab; the standard
profile keeps the real dot-leader tab stop.
"""
import os
import re
import tempfile
import unittest
import zipfile

from exactdoc.docxout import write_docx
from exactdoc.layout import Chunk, DocLayout, PageLayout, Para, Run


def _run(text, **kw):
    return Run(text=text, font="Times-Roman", size=11.0, color="#000000", **kw)


def _contents_line(dots=50):
    p = Para(runs=[_run("1. Introduction"), _run("\t", is_tab=True), _run("1")],
             tab_stops=[(468.0, "right", "dot")])
    p.leader_text = "." * dots
    return p


def _xml(profile, *elements):
    lay = DocLayout(pages=[PageLayout(1, [Chunk(elements=list(elements))])])
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.docx")
        write_docx(lay, path, output_profile=profile)
        with zipfile.ZipFile(path) as z:
            return z.read("word/document.xml").decode("utf-8")


class TypedLeaders(unittest.TestCase):
    def test_gdocs_types_the_source_dots_before_a_plain_right_tab(self):
        doc = _xml("gdocs", _contents_line(50))
        self.assertNotIn('w:leader="dot"', doc)
        self.assertIn('w:val="right"', doc)
        dots = re.findall(r"<w:t[^>]*>(\.+)</w:t>", doc)
        self.assertEqual([len(d) for d in dots], [48])
        # label, dots, tab, number -- in that order
        body = re.sub(r"<w:rPr>.*?</w:rPr>", "", doc, flags=re.S)
        self.assertRegex(body, r"1\. Introduction</w:t>.*?\.{48}</w:t>.*?<w:tab/>.*?>1</w:t>")

    def test_standard_keeps_the_real_leader_tab(self):
        doc = _xml("standard", _contents_line(50))
        self.assertIn('w:leader="dot"', doc)
        self.assertEqual(re.findall(r"<w:t[^>]*>(\.{4,})</w:t>", doc), [])

    def test_a_paragraph_without_a_leader_is_untouched(self):
        p = Para(runs=[_run("Name"), _run("\t", is_tab=True), _run("Value")],
                 tab_stops=[(300.0, "right")])
        self.assertEqual(_xml("gdocs", p), _xml("gdocs", p))
        self.assertEqual(re.findall(r"<w:t[^>]*>(\.{4,})</w:t>", _xml("gdocs", p)), [])

    def test_the_layout_is_not_mutated(self):
        p = _contents_line(50)
        before = [(r.text, r.is_tab) for r in p.runs], list(p.tab_stops)
        _xml("gdocs", p)
        self.assertEqual(([(r.text, r.is_tab) for r in p.runs], list(p.tab_stops)), before)


class ContentsLineEndToEnd(unittest.TestCase):
    def test_a_dotted_contents_page_keeps_its_dots_in_gdocs(self):
        try:
            from reportlab.pdfgen import canvas
        except ImportError:                                # pragma: no cover
            self.skipTest("reportlab is not installed")
        from exactdoc.convert import convert
        from exactdoc.options import PDFIUM_GDOCS_CANDIDATE, RAW
        with tempfile.TemporaryDirectory() as td:
            pdf = os.path.join(td, "toc.pdf")
            c = canvas.Canvas(pdf, pagesize=(612, 792))
            c.setFont("Times-Roman", 11)
            y = 700
            for title, page in (("1. Introduction", 1), ("2. Method", 2),
                                ("2.1 Data sources", 2), ("3. Results", 3)):
                c.drawString(72, y, title)
                w = c.stringWidth(title, "Times-Roman", 11)
                # dots run up to the number, as a word processor sets them
                num_x = 540 - c.stringWidth(str(page), "Times-Roman", 11)
                n = int((num_x - 1.5 - 72 - w) / c.stringWidth(".", "Times-Roman", 11))
                c.drawString(72 + w, y, "." * n)
                c.drawRightString(540, y, str(page))
                y -= 20
            c.showPage()
            c.save()
            docs = {}
            for name, opts in (("gdocs", PDFIUM_GDOCS_CANDIDATE), ("raw", RAW)):
                out = os.path.join(td, name + ".docx")
                convert(pdf, out, options=opts)
                with zipfile.ZipFile(out) as z:
                    docs[name] = z.read("word/document.xml").decode("utf-8")
        leaders = docs["raw"].count('w:leader="dot"')
        self.assertEqual(leaders, 4)
        self.assertNotIn('w:leader="dot"', docs["gdocs"])
        self.assertEqual(len(re.findall(r"<w:t[^>]*>\.{20,}</w:t>", docs["gdocs"])), leaders)


if __name__ == "__main__":
    unittest.main()
