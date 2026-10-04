"""Pages of another size keep their own paper (design audit B9).

`infer` copied page 1's size into DocLayout and the writer put it on every
section, so a portrait, landscape, A4 sequence came out as three Letter-portrait
pages (measured: one `pgSz 12240x15840` for mixed_sizes.pdf), and the margins
were measured over all pages at once -- the landscape page's 650pt lines then
set the portrait right margin.

Each page size is now its own group: margins are measured per group, the page
loop runs in its page's geometry, and the writer opens a NEW_PAGE section with
that page's pgSz, w:orient and pgMar wherever the geometry changes. A document
of one size takes none of these paths.

    python tests/test_mixed_page_sizes.py
"""
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.dialect import normalize  # noqa: E402
from exactdoc.docxout import write_docx  # noqa: E402
from exactdoc.infer import _size_groups, infer  # noqa: E402
from exactdoc.model import PageIR  # noqa: E402
from exactdoc.parse_pdfium import parse_pdf  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.lib.pagesizes import landscape, letter
except ImportError:                                    # pragma: no cover
    _canvas = None

A4 = (595.28, 841.89)
BODY = ("Body text of an ordinary report paragraph that runs most of the way "
        "across the column")


def _mixed(path):
    c = _canvas.Canvas(path, pagesize=letter)
    for page_size, rows, width_words in ((letter, 12, 13), (landscape(letter), 8, 20),
                                         (A4, 12, 13), (letter, 12, 13)):
        c.setPageSize(page_size)
        c.setFont("Helvetica", 10)
        top = page_size[1] - 72
        for k in range(rows):
            words = (BODY + " lorem ipsum dolor sit amet consectetur") .split()
            c.drawString(72, top - 14 * k, " ".join(words[:width_words]) + " %d" % k)
        c.showPage()
    c.save()
    return path


def _uniform(path):
    c = _canvas.Canvas(path, pagesize=letter)
    for _ in range(2):
        c.setFont("Helvetica", 10)
        for k in range(12):
            c.drawString(72, 720 - 14 * k, BODY + " %d" % k)
        c.showPage()
    c.save()
    return path


def _sections(docx):
    xml = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8")
    out = []
    for sect in re.findall(r"<w:sectPr\b.*?</w:sectPr>", xml, re.S):
        sz = re.search(r"<w:pgSz\b[^>]*/>", sect).group(0)
        w = int(re.search(r'w:w="(\d+)"', sz).group(1))
        h = int(re.search(r'w:h="(\d+)"', sz).group(1))
        orient = re.search(r'w:orient="(\w+)"', sz)
        mar = re.search(r"<w:pgMar\b[^>]*/>", sect).group(0)
        left = int(re.search(r'w:left="(\d+)"', mar).group(1))
        right = int(re.search(r'w:right="(\d+)"', mar).group(1))
        out.append((w, h, orient.group(1) if orient else None, left, right))
    return out


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class MixedSizes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = _mixed(os.path.join(cls._dir.name, "mixed.pdf"))
        cls.lay = infer(normalize(parse_pdf(cls.pdf)))
        cls.docx = os.path.join(cls._dir.name, "mixed.docx")
        write_docx(cls.lay, cls.docx)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_page_one_is_the_document_geometry(self):
        self.assertEqual((self.lay.page_w, self.lay.page_h), (612.0, 792.0))
        self.assertIsNone(self.lay.pages[0].page_w)
        self.assertIsNone(self.lay.pages[3].page_w, "back to page 1's size")

    def test_other_sizes_carry_their_own(self):
        land, a4 = self.lay.pages[1], self.lay.pages[2]
        self.assertEqual((land.page_w, land.page_h), (792.0, 612.0))
        self.assertEqual((round(a4.page_w, 1), round(a4.page_h, 1)), (595.3, 841.9))
        ml, mr, mt, mb = land.margins
        self.assertAlmostEqual(ml, 72.0, delta=1.0)
        # the column holds the landscape page's own lines
        self.assertGreaterEqual(792.0 - ml - mr, self.widest(1) - 72.0 - 1.0)

    @classmethod
    def widest(cls, pno):
        ir = parse_pdf(cls.pdf, keep_image_data=False)
        return max(ln.bbox[2] for b in ir.pages[pno].blocks for ln in b.lines)

    def test_landscape_lines_do_not_set_the_portrait_margin(self):
        # portrait content ends where the portrait lines end, not at the
        # landscape page's right edge
        self.assertAlmostEqual(612.0 - self.lay.margin_r, self.widest(0), delta=2.0)

    def test_writer_emits_a_section_per_geometry(self):
        secs = _sections(self.docx)
        sizes = [(w, h, o) for w, h, o, _, _ in secs]
        self.assertEqual(sizes, [(12240, 15840, None), (15840, 12240, "landscape"),
                                 (11906, 16838, None), (12240, 15840, None)])

    def test_landscape_text_is_not_wrapped_into_a_portrait_column(self):
        land = _sections(self.docx)[1]
        content_twips = land[0] - land[3] - land[4]
        self.assertGreaterEqual(content_twips, (self.widest(1) - 72.0 - 1.0) * 20)
        self.assertGreater(content_twips, 468 * 20, "wider than page 1's column")


class GridRunsStopAtAChangeOfPaper(unittest.TestCase):
    """The writer's multi-column run merge must not swallow a page whose
    paper differs: the merged page would lose the geometry and its section."""

    def test_run_splits_at_the_geometry_change(self):
        from exactdoc.docxout import _merge_grid_page_runs
        from exactdoc.layout import Chunk, PageLayout, Para, Run

        def page(n, **geo):
            body = [Para(runs=[Run(text="column text %d" % n, font="Helvetica",
                                   size=10, color="#000000")])]
            return PageLayout(number=n, chunks=[Chunk(n_cols=2, elements=body)], **geo)

        land = dict(page_w=792.0, page_h=612.0, margins=(72.0, 72.0, 54.0, 54.0))
        pages = [page(1), page(2), page(3, **land), page(4, **land)]
        out = _merge_grid_page_runs(pages)
        self.assertEqual([p.number for p in out], [1, 3])
        self.assertIsNone(out[0].page_w)
        self.assertEqual((out[1].page_w, out[1].page_h, out[1].margins),
                         (792.0, 612.0, (72.0, 72.0, 54.0, 54.0)))


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class UniformDocumentsAreUntouched(unittest.TestCase):
    def test_one_section_no_orientation_no_page_geometry(self):
        with tempfile.TemporaryDirectory() as d:
            lay = infer(normalize(parse_pdf(_uniform(os.path.join(d, "u.pdf")))))
            out = os.path.join(d, "u.docx")
            write_docx(lay, out)
            self.assertTrue(all(p.page_w is None and p.margins is None for p in lay.pages))
            self.assertEqual([s[:3] for s in _sections(out)], [(12240, 15840, None)])

    def test_size_groups_tolerate_scanner_jitter(self):
        pages = [PageIR(number=1, width=612.0, height=792.0),
                 PageIR(number=2, width=611.2, height=793.4),
                 PageIR(number=3, width=595.3, height=841.9)]
        groups = _size_groups(pages)
        self.assertEqual([[p.number for p in g] for g in groups], [[1, 2], [3]])
        same = pages[:2]
        self.assertIs(_size_groups(same)[0], same, "one size: the page list itself")


if __name__ == "__main__":
    unittest.main()
