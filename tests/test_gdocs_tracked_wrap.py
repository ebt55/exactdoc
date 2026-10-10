"""A letter-spaced paragraph keeps the source's line breaks in Google Docs.

Docs drops w:spacing, so a paragraph the source tracked (Chrome sets every
glyph 0.25-0.35pt apart) sets narrower there and fits more words a line: 8 of
x07's 21 paragraphs came out a line short on Google's export, and with no room
on the page to pay for them everything below stepped up (dy_p50 16.4). The
gdocs writer narrows such a paragraph by the share the tracking added, at the
nearest width where the width tables (untracked, as Docs) set it in its source
line count, and the page planner models it at that width
(`docxout._gdocs_tracking_indent`).

    python -m unittest tests.test_gdocs_tracked_wrap
"""
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from docx import Document  # noqa: E402

from exactdoc import docxout  # noqa: E402
from exactdoc.docxout import (WriteCtx, _gdocs_tracking_indent, _text_metrics,  # noqa: E402
                              predict_lines_for, write_para)
from exactdoc.layout import Para, Run  # noqa: E402

WORDS = ("the depot replacement programme was approved on the understanding that "
         "service levels would be maintained throughout construction and that "
         "assumption has not survived contact with the site because the temporary "
         "layover facility is smaller than planned and is now the binding constraint "
         "on every route that turns there in the evening peak").split()
AVAIL = 468.0
TRACK = 0.3


def _para(k, tracking=TRACK, align="left"):
    text = " ".join(WORDS[:k])
    p = Para(runs=[Run(text=text, font="Times-Roman", size=11.0, color="#111111",
                       tracking=tracking)], align=align, leading=14.0)
    # the source's line count: the text broken at its tracked advances
    m = _text_metrics("standard")
    lines, cur = 1, 0.0
    for w in text.split(" "):
        ww = m.text_width(w, "Times New Roman", 11.0) + tracking * len(w)
        sp = m.text_width(" ", "Times New Roman", 11.0) + tracking
        if cur and cur + sp + ww > AVAIL:
            lines, cur = lines + 1, ww
        else:
            cur = cur + sp + ww if cur else ww
    p.src_lines = lines
    return p


def _short_by_a_line():
    """A paragraph Docs (untracked) would set a line shorter than the source."""
    gd = _text_metrics("gdocs")
    for k in range(20, len(WORDS) + 1):
        p = _para(k)
        if p.src_lines >= 2 and predict_lines_for(p, AVAIL, gd) == p.src_lines - 1:
            return p
    raise AssertionError("no paragraph re-wraps shorter untracked")


class Indent(unittest.TestCase):
    def test_a_tracked_paragraph_is_narrowed_to_its_source_count(self):
        p = _short_by_a_line()
        r = _gdocs_tracking_indent(p, AVAIL, 0.0)
        self.assertGreater(r, 0.0)
        self.assertLess(r, 0.1 * AVAIL)
        gd = _text_metrics("gdocs")
        self.assertEqual(predict_lines_for(p, AVAIL - r, gd), p.src_lines)

    def test_nothing_to_make_up(self):
        p = _short_by_a_line()
        untracked = _para(len(p.runs[0].text.split()), tracking=0.0)
        untracked.src_lines = p.src_lines - 1
        self.assertEqual(_gdocs_tracking_indent(untracked, AVAIL, 0.0), 0.0)
        one = _para(5)
        self.assertEqual(one.src_lines, 1)
        self.assertEqual(_gdocs_tracking_indent(one, AVAIL, 0.0), 0.0)
        centred = _short_by_a_line()
        centred.align = "center"
        self.assertEqual(_gdocs_tracking_indent(centred, AVAIL, 0.0), 0.0)

    def test_the_planner_models_the_source_count(self):
        from exactdoc.layout import Chunk, DocLayout, PageLayout
        p = _short_by_a_line()
        lay = DocLayout()
        pg = PageLayout(number=1, chunks=[Chunk(elements=[p])])
        got = docxout._gdocs_flow(pg, AVAIL, lay, 0.0)
        self.assertEqual(got[1][0][1], p.src_lines)


class Writer(unittest.TestCase):
    def _right(self, profile):
        p = _short_by_a_line()
        doc = Document()
        write_para(doc, p, AVAIL, ctx=WriteCtx(output_profile=profile))
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "p.docx")
            doc.save(path)
            x = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
        m = re.search(r'<w:ind [^>]*w:right="(\d+)"', x)
        return int(m.group(1)) / 20 if m else 0.0

    def test_gdocs_writes_the_narrower_width(self):
        p = _short_by_a_line()
        self.assertAlmostEqual(self._right("gdocs"),
                               _gdocs_tracking_indent(p, AVAIL, 0.0), places=1)

    def test_the_standard_profile_keeps_its_width(self):
        self.assertEqual(self._right("standard"), 0.0)


if __name__ == "__main__":
    unittest.main()
