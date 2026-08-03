"""Contracts for conservative symbol-font list-marker normalisation."""
import copy
from pathlib import Path
import unittest

from exactdoc.dialect import normalize
from exactdoc.infer import infer
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock

try:
    from exactdoc.parse_pdfium import parse_pdf
except ImportError:  # pragma: no cover - exercised on optional-backend installs
    parse_pdf = None


ROOT = Path(__file__).resolve().parents[1]


def _span(text, font, x0, x1, *, size=11.0):
    return Span(text=text, font=font, size=size, color="#000000", bold=False,
                italic=False, mono=False, serif=(font == "DejaVuSerif"),
                superscript=False, bbox=(x0, 10.0, x1, 23.0),
                origin=(x0, 21.0))


def _marker_line(x, text_x, *, glyph="\uf0b7", font="OpenSymbol", body=True, y=10.0):
    marker = _span(glyph + " ", font, x, x + 7.5)
    marker.bbox = (x, y, x + 7.5, y + 13.5)
    marker.origin = (x, y + 11.0)
    spans = [marker]
    if body:
        item = _span("item", "DejaVuSerif", text_x, text_x + 22.0)
        item.bbox = (text_x, y, text_x + 22.0, y + 13.0)
        item.origin = (text_x, y + 11.0)
        spans.append(item)
    return Line(spans=spans, bbox=(x, y, text_x + (22.0 if body else 7.5), y + 13.5))


def _ir(lines):
    blocks = [TextBlock(lines=[line], bbox=line.bbox) for line in lines]
    return DocIR("synthetic.pdf", [PageIR(1, 612, 792, blocks=blocks)])


def _texts(ir):
    return [span.text for page in ir.pages for block in page.blocks
            for line in block.lines for span in line.spans]


class SymbolListMarkerUnitTests(unittest.TestCase):
    def test_corroborated_opensymbol_markers_become_google_safe_bullets(self):
        ir = _ir([_marker_line(65, 83, y=y) for y in (10, 25, 40)])
        normalize(ir)
        markers = [line.spans[0] for block in ir.pages[0].blocks for line in block.lines]
        self.assertEqual(["\u2022 "] * 3, [span.text for span in markers])
        self.assertEqual(["Arial"] * 3, [span.font for span in markers])
        self.assertEqual(3, ir.meta["_normalized"]["symbol_markers"])

    def test_negative_cases_remain_unchanged(self):
        cases = {
            "single decorative glyph": [_marker_line(65, 83)],
            "repeated arbitrary pua": [_marker_line(65, 83, glyph="\uf0b8", y=y)
                                       for y in (10, 25)],
            "known code ordinary font": [_marker_line(65, 83, font="DejaVuSerif", y=y)
                                          for y in (10, 25)],
            "no adjacent item text": [_marker_line(65, 83, body=False, y=y)
                                       for y in (10, 25)],
            "unrelated marker edges": [_marker_line(65, 83, y=10),
                                        _marker_line(105, 123, y=25)],
        }
        for label, lines in cases.items():
            with self.subTest(label):
                ir = _ir(lines)
                before = _texts(copy.deepcopy(ir))
                normalize(ir)
                self.assertEqual(before, _texts(ir))
                self.assertEqual(0, ir.meta["_normalized"]["symbol_markers"])

    def test_ordinary_unicode_bullet_is_unchanged(self):
        ir = _ir([_marker_line(65, 83, glyph="\u2022", font="Arial", y=y)
                  for y in (10, 25)])
        before = _texts(copy.deepcopy(ir))
        normalize(ir)
        self.assertEqual(before, _texts(ir))


@unittest.skipUnless(parse_pdf is not None, "pypdfium2 is unavailable")
class SymbolListMarkerFixtureTests(unittest.TestCase):
    def test_l1_word_native_normalizes_and_infers_three_separate_list_items(self):
        ir = parse_pdf(str(ROOT / "testkit/fixtures/l1_word_native.pdf"))
        normalize(ir)
        self.assertEqual(3, ir.meta["_normalized"]["symbol_markers"])
        self.assertFalse(any("\uf0b7" in text for text in _texts(ir)))

        layout = infer(ir)
        paras = [element for page in layout.pages for chunk in page.chunks
                 for element in chunk.elements
                 if element.__class__.__name__ == "Para" and element.text.startswith("\u2022")]
        self.assertEqual(3, len(paras))
        self.assertTrue(all(para.first_indent < 0 and para.tab_stops for para in paras))
        self.assertFalse(any("Index rebuild" in para.text and "Reranker training" in para.text
                             for para in paras))

        snapshot = [(span.text, span.font) for page in ir.pages for block in page.blocks
                    for line in block.lines for span in line.spans]
        normalize(ir)
        self.assertEqual(snapshot, [(span.text, span.font) for page in ir.pages
                                    for block in page.blocks for line in block.lines
                                    for span in line.spans])
        self.assertEqual(0, ir.meta["_normalized"]["symbol_markers"])

    def test_l1_is_the_only_frozen_fixture_with_pua_text(self):
        hits = []
        for pdf in sorted((ROOT / "testkit/fixtures").glob("*.pdf")):
            ir = parse_pdf(str(pdf))
            if any("\ue000" <= char <= "\uf8ff" for text in _texts(ir) for char in text):
                hits.append(pdf.name)
        self.assertEqual(["l1_word_native.pdf"], hits)


if __name__ == "__main__":
    unittest.main()
