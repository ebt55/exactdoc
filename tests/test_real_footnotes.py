"""Real footnotes: page-bottom notes matched 1:1 to their references.

No tool in the benchmark produced a single footnote (SCOTUS: 0 in every
output); the note text stayed in the body at the page bottom, so it did not
move with its reference. `notes.py` reads the note zone (small type at the
foot of the page, under a short rule or a typed separator), opens a note at
each mark (a superscript, a lone raised fragment, or a plain digit), and binds
it only when the page holds EXACTLY ONE superscript reference with that mark.
The standard profile writes them as word/footnotes.xml notes; the zone's
paragraphs stay in the layout, marked, so the typed form is one switch away.

    python -m unittest tests.test_real_footnotes
"""
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import notes as N  # noqa: E402
from exactdoc.layout import DocLayout, Footnote  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None

W, H = 612, 792
BODY = ("The committee reviewed the proposal in detail and agreed the timetable "
        "for the replacement depot.")


def _footnote_pdf(path, refs=("1", "2"), notes=("1", "2"), extra_ref=None,
                  separator="rule", fragment=False, pages=1):
    """Body text with superscript references and notes at the page foot.

    `fragment`: draw each note's mark as its own raised text object left of
    the note's line (the SCOTUS / LibreOffice form) instead of inline.
    """
    c = _canvas.Canvas(path, pagesize=(W, H))
    for pg in range(pages):
        y = 90
        for i in range(12):
            c.setFont("Times-Roman", 11)
            text = BODY if i % 2 == 0 else "It records the reasons for the change."
            c.drawString(72, H - y, text)
            k = i // 4
            if i % 4 == 2 and k < len(refs) and refs[k]:
                x = 72 + c.stringWidth(text, "Times-Roman", 11)
                c.setFont("Times-Roman", 7)
                c.drawString(x, H - y + 4, refs[k])
            if extra_ref and i == 9:
                x = 72 + c.stringWidth(text, "Times-Roman", 11)
                c.setFont("Times-Roman", 7)
                c.drawString(x, H - y + 4, extra_ref)
            y += 14
        foot = 660
        if separator == "rule":
            c.setLineWidth(0.5)
            c.line(72, H - foot, 216, H - foot)
        elif separator == "text":
            c.setFont("Times-Roman", 9)
            c.drawString(72, H - foot - 2, "—" * 6)
        y = foot + 14
        for n in notes:
            if fragment:
                c.setFont("Times-Roman", 6)
                c.drawString(80, H - y + 2.5, n)
                c.setFont("Times-Roman", 9)
                c.drawString(84, H - y, "This note explains the reference it carries "
                             "in a sentence long enough to read as a note.")
            else:
                c.setFont("Times-Roman", 6)
                c.drawString(72, H - y + 3, n)
                c.setFont("Times-Roman", 9)
                c.drawString(72 + c.stringWidth(n, "Times-Roman", 6) + 1, H - y,
                             " This note explains the reference it carries.")
            y += 11
        c.showPage()
    c.save()
    return path


def _convert(pdf, out, gdocs=False):
    from exactdoc.convert import convert
    from exactdoc.options import PDFIUM_GDOCS_CANDIDATE, RAW
    convert(pdf, out, options=PDFIUM_GDOCS_CANDIDATE if gdocs else RAW)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        doc = z.read("word/document.xml").decode("utf-8")
        notes = z.read("word/footnotes.xml").decode("utf-8") \
            if "word/footnotes.xml" in names else None
    return doc, notes


def _layout(pdf):
    from exactdoc.dialect import normalize
    from exactdoc.infer import infer
    from exactdoc.parse_pdfium import parse_pdf
    return infer(normalize(parse_pdf(pdf, keep_image_data=False)))


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class FootnoteDetection(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._dir.cleanup()

    def _pdf(self, **kw):
        return _footnote_pdf(os.path.join(self._dir.name, "f.pdf"), **kw)

    def test_two_notes_under_a_rule_bind_to_their_references(self):
        lay = _layout(self._pdf())
        self.assertEqual([f.mark for f in lay.footnotes], ["1", "2"])
        self.assertTrue(all(f.auto for f in lay.footnotes))
        refs = [r for pg in lay.pages for ch in pg.chunks for el in ch.elements
                for r in getattr(el, "runs", []) if r.footnote is not None]
        self.assertEqual([(r.text, r.footnote) for r in refs], [("1", 0), ("2", 1)])
        first = lay.footnotes[0].paras[0]
        self.assertTrue(first.runs[0].footnote_mark)
        self.assertIn("explains the reference", first.text)
        # the zone stays in the flow, marked, for a profile that writes it typed
        roles = [el.role for ch in lay.pages[0].chunks for el in ch.elements
                 if hasattr(el, "role")]
        self.assertIn("footnote", roles)
        self.assertIsNotNone(lay.pages[0].note_area)

    def test_mark_fragments_and_a_typed_separator(self):
        lay = _layout(self._pdf(separator="text", fragment=True))
        self.assertEqual([f.mark for f in lay.footnotes], ["1", "2"])

    def test_a_note_without_a_reference_binds_nothing(self):
        lay = _layout(self._pdf(refs=("1", None), notes=("1", "2")))
        self.assertEqual(lay.footnotes, [])

    def test_two_candidate_references_for_one_mark_bind_nothing(self):
        # "2" as a footnote and "2" as an exponent: ambiguous, never guessed
        lay = _layout(self._pdf(extra_ref="2"))
        self.assertEqual(lay.footnotes, [])

    def test_an_unmatched_superscript_is_left_alone(self):
        lay = _layout(self._pdf(extra_ref="7"))
        self.assertEqual([f.mark for f in lay.footnotes], ["1", "2"])


class FootnoteNumbering(unittest.TestCase):
    @staticmethod
    def _lay(*marks_by_page):
        lay = DocLayout()
        for pg, marks in enumerate(marks_by_page, start=1):
            for m in marks:
                lay.footnotes.append(Footnote(
                    fid=len(lay.footnotes), page=pg, mark=m,
                    value=int(m) if m.isdigit() else 0))
        return lay

    def test_continuous_numbering_is_automatic(self):
        lay = self._lay(["3", "4"], ["5"])
        N.number_footnotes(lay)
        self.assertEqual((lay.footnote_restart, lay.footnote_start), ("continuous", 3))
        self.assertTrue(all(f.auto for f in lay.footnotes))

    def test_a_restart_keeps_the_source_marks(self):
        # SCOTUS: the dissent starts again at 1
        lay = self._lay(["1", "2"], ["3"], ["1"], ["2"])
        N.number_footnotes(lay)
        self.assertEqual([f.auto for f in lay.footnotes],
                         [True, True, True, False, False])

    def test_per_page_numbering(self):
        lay = self._lay(["1", "2"], ["1"], ["1", "2", "3"])
        N.number_footnotes(lay)
        self.assertEqual(lay.footnote_restart, "eachPage")
        self.assertTrue(all(f.auto for f in lay.footnotes))

    def test_symbols_are_custom_marks(self):
        lay = self._lay(["*", "1"])
        N.number_footnotes(lay)
        self.assertEqual([f.auto for f in lay.footnotes], [False, True])


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class FootnoteSerialisation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = _footnote_pdf(os.path.join(cls._dir.name, "f.pdf"))

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_standard_profile_writes_real_notes(self):
        doc, notes = _convert(self.pdf, os.path.join(self._dir.name, "s.docx"))
        self.assertIsNotNone(notes)
        self.assertEqual(sorted(re.findall(r'<w:footnoteReference w:id="(\d+)"', doc)),
                         ["1", "2"])
        self.assertNotIn("explains the reference", doc)       # left the body
        self.assertEqual(notes.count("explains the reference"), 2)
        self.assertEqual(notes.count("<w:footnoteRef/>"), 2)
        for kind in ("separator", "continuationSeparator"):
            self.assertIn('w:type="%s"' % kind, notes)
        self.assertIn('w:styleId="FootnoteReference"', self._part("s.docx", "word/styles.xml"))

    def test_the_harness_reads_footnote_numbers_as_live_text(self):
        sys.path.insert(0, os.path.join(ROOT, "testkit"))
        import harness
        out = os.path.join(self._dir.name, "h.docx")
        _convert(self.pdf, out)
        live = re.sub(r"\s+", "", harness.docx_live_text(out)[0])
        self.assertIn("2Thisnoteexplains", live)
        self.assertIn("replacementdepot.1", live)

    def test_gdocs_profile_keeps_the_notes_typed(self):
        doc, notes = _convert(self.pdf, os.path.join(self._dir.name, "g.docx"), gdocs=True)
        self.assertIsNone(notes)
        self.assertNotIn("footnoteReference", doc)
        self.assertEqual(doc.count("explains the reference"), 2)

    def test_a_reference_lost_before_the_writer_falls_back_to_typed(self):
        from exactdoc.docxout import write_docx
        lay = _layout(self.pdf)
        for pg in lay.pages:
            for ch in pg.chunks:
                for el in ch.elements:
                    for r in getattr(el, "runs", []):
                        if r.footnote == 1:
                            r.footnote = None
        out = os.path.join(self._dir.name, "lost.docx")
        write_docx(lay, out, output_profile="standard")
        with zipfile.ZipFile(out) as z:
            doc = z.read("word/document.xml").decode("utf-8")
            self.assertNotIn("word/footnotes.xml", z.namelist())
        self.assertEqual(doc.count("explains the reference"), 2)   # nothing lost

    def test_a_document_with_column_sections_keeps_its_notes_typed(self):
        # LibreOffice unbalances every column section once a footnote exists
        from exactdoc.layout import Chunk
        from exactdoc.structures import footnote_plan
        lay = _layout(self.pdf)
        self.assertEqual(len(footnote_plan(lay)), 2)
        lay.pages[0].chunks.append(Chunk(n_cols=2))
        self.assertEqual(footnote_plan(lay), {})

    def _part(self, name, part):
        with zipfile.ZipFile(os.path.join(self._dir.name, name)) as z:
            return z.read(part).decode("utf-8")


if __name__ == "__main__":
    unittest.main()
