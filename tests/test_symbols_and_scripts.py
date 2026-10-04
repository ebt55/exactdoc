"""Symbol-font PUA text and superscript sizes (catalogue #14, #11).

FIPS 180's equations arrived as Private Use code points from Symbol and MT
Extra (`U+F0C5` for the XOR sign) and rendered as junk; EUR-Lex's footnote
markers were written at their already-shrunk drawn size AND marked superscript,
so the renderer shrank them again to ~3pt.

    python tests/test_symbols_and_scripts.py
"""
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.dialect import normalize  # noqa: E402
from exactdoc.layout import Chunk, DocLayout, PageLayout, Para, Run  # noqa: E402
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock  # noqa: E402


def _ir(*spans):
    lines = []
    for i, (text, font) in enumerate(spans):
        y = 100.0 + 20 * i
        sp = Span(text=text, font=font, size=12.0, color="#000000", bold=False,
                  italic=False, mono=False, serif=False, superscript=False,
                  bbox=(72, y - 12, 200, y), origin=(72, y))
        lines.append(Line(spans=[sp], bbox=sp.bbox))
    return DocIR("s.pdf", [PageIR(1, 612, 792, blocks=[
        TextBlock(lines=[ln], bbox=ln.bbox) for ln in lines])])


def _texts(ir):
    return [s.text for b in ir.pages[0].blocks for ln in b.lines for s in ln.spans]


class SymbolPua(unittest.TestCase):
    def test_symbol_operators(self):
        ir = normalize(_ir(("x  y  z  1", "Symbol"),
                           ("", "SymbolMT")))
        self.assertEqual(_texts(ir), ["x ⊕ y = z ≤ 1",
                                      "∧∨−"])

    def test_wingdings_and_zapf_bullets(self):
        ir = normalize(_ir((" item", "Wingdings-Regular"),
                           (" done", "Wingdings"),
                           (" dot", "ZapfDingbats")))
        self.assertEqual(_texts(ir), ["▪ item", "✔ done", "● dot"])

    def test_mt_extra_only_where_pinned(self):
        ir = normalize(_ir(("is  bits, , ", "MT Extra")))
        self.assertEqual(_texts(ir), ["is ℓ bits, …, "])

    def test_other_faces_keep_their_code_points(self):
        # Wingdings 2 is a different encoding that shares a prefix; an
        # ordinary face's PUA has no published meaning at all.
        ir = normalize(_ir(("", "Wingdings2"), ("", "Arial")))
        self.assertEqual(_texts(ir), ["", ""])


def _write(lay, profile="standard"):
    from exactdoc.docxout import write_docx
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    try:
        write_docx(lay, path, output_profile=profile)
        with zipfile.ZipFile(path) as z:
            return z.read("word/document.xml").decode()
    finally:
        os.unlink(path)


def _para(*runs):
    lay = DocLayout()
    lay.pages = [PageLayout(number=1, chunks=[Chunk(elements=[Para(runs=list(runs))])])]
    return lay


def _run(text, size, sup=False):
    return Run(text=text, font="Times", size=size, color="#000000",
               superscript=sup)


def _sizes_before_vertalign(xml):
    import re
    return re.findall(r'<w:sz w:val="(\d+)"/>(?:(?!</w:rPr>).)*<w:vertAlign', xml)


class SuperscriptSize(unittest.TestCase):
    def test_marker_takes_its_line_size(self):
        # EUR-Lex: a 4.93pt marker on 8.5pt text. vertAlign does the shrink.
        xml = _write(_para(_run("Regulation", 8.5), _run("1", 4.93, True),
                           _run(" applies.", 8.5)))
        self.assertIn('w:vertAlign w:val="superscript"', xml)
        self.assertEqual(_sizes_before_vertalign(xml), ["17"])

    def test_lone_script_keeps_its_drawn_size_and_loses_the_raise(self):
        xml = _write(_para(_run("12", 6.0, True)))
        self.assertNotIn("w:vertAlign", xml)
        self.assertIn('<w:sz w:val="12"/>', xml)

    def test_gdocs_profile_is_unchanged(self):
        xml = _write(_para(_run("Regulation", 8.5), _run("1", 4.93, True)),
                     profile="gdocs")
        self.assertEqual(_sizes_before_vertalign(xml), ["10"])


if __name__ == "__main__":
    unittest.main()
