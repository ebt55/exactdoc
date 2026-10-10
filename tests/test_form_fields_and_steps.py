"""Two paragraph-structure rules (WP35d), each from a short promised document.

1. A form's label and the first line of its field share a baseline, the field
   in a column of its own (y65: "Purpose:" at x 50, its text at x 145). The
   pair is one paragraph -- label, tab, field, its lines hanging at the field's
   column (`infer._field_labels`, FIELD_GAP_EM); before, the label stood alone
   and its field began a line lower (y65 dy_p50 10.2 in Google Docs), or was
   joined to it by a space and its words moved left.
2. Short paragraphs set a little further apart than their lines (y44: 12.7pt
   pitch, paragraphs 15.7pt apart) are not one paragraph: a step PARA_STEP_PT
   wider than the block's tightest pitch, after a line that ends short, ends a
   paragraph (`infer._split_lines_to_paras`).

    python -m unittest tests.test_form_fields_and_steps
"""
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None

H = 792


def _form_pdf(path):
    c = _canvas.Canvas(path, pagesize=(612, H))
    c.setFont("Helvetica", 10)
    y = 100
    c.drawString(72, H - y, "Meeting notice issued by the regional office.")
    y += 30
    # a label alone in its own text object, its field's first line beside it
    c.drawString(72, H - y, "Purpose:")
    field = ["Members of the staff will present the annual assessment of the plant",
             "at a regular meeting of the city council, and will be available after",
             "the meeting to answer questions from the public about the results."]
    for i, t in enumerate(field):
        c.drawString(167, H - (y + 11.5 * i), t)
    y += 11.5 * len(field) + 20
    c.drawString(72, H - y, "Location:")
    c.drawString(167, H - y, "City Hall, Council Chambers")
    y += 30
    c.drawString(72, H - y, "A closing paragraph of ordinary text that runs across the whole column.")
    c.showPage()
    c.save()
    return path


def _steps_pdf(path):
    c = _canvas.Canvas(path, pagesize=(612, H))
    c.setFont("Helvetica", 10)
    y = 100
    first = "A paragraph that is set justified across the column to its right edge and"
    # ONE text object, as Typst writes the block: the parser keeps it one block
    t = c.beginText(72, H - y)
    t.setFont("Helvetica", 10)
    t.setWordSpace((468 - c.stringWidth(first, "Helvetica", 10)) / first.count(" "))
    t.textOut(first)
    t.setWordSpace(0)
    for step, s in ((12.7, "then ends short."),
                    (15.7, "Each section title is arbitrary."),
                    (15.7, "You can choose any of the entry types for each section."),
                    (15.7, "Markdown syntax is supported everywhere in the text.")):
        t.moveCursor(0, step)
        t.textOut(s)
        y += step
    c.drawText(t)
    y += 40
    c.drawString(72, H - y, "Another heading")
    # the rest of the page sets its lines at the paragraph step, as y44's
    # entries do: the parser's block pitch, so it keeps the intro one block
    for k in range(10):
        y += 15.7
        c.drawString(72, H - y, "Entry line %d of a list set one line apart" % k)
    c.showPage()
    c.save()
    return path


BODY = ["Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod",
        "tempor incididunt ut labore et dolore magnam aliquam quaerat voluptatem.",
        "Ut enim aeque doleamus animo, cum corpore dolemus, fieri tamen permagna",
        "accessio potest, si aliquod aeternum et infinitum impendere malum nobis",
        "opinemur. Quod idem licet transferre in voluptatem, ut postea variari",
        "voluptas distinguique possit, augeri amplificarique non possit. At etiam"]


def _heading_pdf(path, step):
    """y20's block: an 11pt heading `step` above body justified at a 15.69 pitch,
    in ONE text object, as Typst writes it."""
    c = _canvas.Canvas(path, pagesize=(612, H))
    t = c.beginText(72, H - 100)
    t.setFont("Helvetica-Bold", 11)
    t.textOut("1.1.1. Rockets at a glance")
    t.setFont("Helvetica", 11)
    for i, s in enumerate(BODY):
        t.moveCursor(0, step if i == 0 else 15.69)
        t.setWordSpace((468 - c.stringWidth(s, "Helvetica", 11)) / s.count(" "))
        t.textOut(s)
    t.setWordSpace(0)
    t.moveCursor(0, 15.69)
    t.textOut("Athenis, ut e patre audiebam.")
    c.drawText(t)
    c.showPage()
    c.save()
    return path


def _paras(path):
    with zipfile.ZipFile(path) as z:
        doc = z.read("word/document.xml").decode("utf-8")
    out = []
    for p in re.findall(r"<w:p(?: [^>]*)?>.*?</w:p>", doc, re.S):
        text = "".join("\t" if m.startswith("<w:tab/") else re.sub(r"<[^>]+>", "", m)
                       for m in re.findall(r"<w:tab/>|<w:t(?: [^>]*)?>[^<]*</w:t>", p))
        if text.strip():
            out.append((text, p))
    return out


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class FormFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        cls._dir = tempfile.TemporaryDirectory()
        cls.out = os.path.join(cls._dir.name, "form.docx")
        convert(_form_pdf(os.path.join(cls._dir.name, "form.pdf")), cls.out, options=RAW)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_the_label_opens_its_field(self):
        ps = _paras(self.out)
        purpose = [(t, p) for t, p in ps if t.startswith("Purpose:")]
        self.assertEqual(len(purpose), 1, [t for t, _ in ps])
        t, p = purpose[0]
        self.assertTrue(t.startswith("Purpose:\tMembers of the staff"), t)
        self.assertIn("results.", t)                     # the field's lines with it
        # hanging at the field's column, 95pt in: label at the margin
        self.assertIn('w:hanging="1900"', p)
        self.assertIn('w:left="1900"', p)

    def test_a_one_line_field_is_tabbed_too(self):
        t = [t for t, _ in _paras(self.out) if t.startswith("Location:")]
        self.assertEqual(t, ["Location:\tCity Hall, Council Chambers"])

    def test_no_label_stands_alone(self):
        self.assertNotIn("Purpose:", [t.strip() for t, _ in _paras(self.out)])


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class ParagraphSteps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        cls._dir = tempfile.TemporaryDirectory()
        cls.out = os.path.join(cls._dir.name, "steps.docx")
        convert(_steps_pdf(os.path.join(cls._dir.name, "steps.pdf")), cls.out, options=RAW)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_short_paragraphs_a_little_apart_stay_apart(self):
        texts = [t for t, _ in _paras(self.out)]
        self.assertIn("Each section title is arbitrary.", texts)
        self.assertIn("You can choose any of the entry types for each section.", texts)
        self.assertIn("Markdown syntax is supported everywhere in the text.", texts)
        # the wrapped paragraph keeps its two lines together
        self.assertTrue(any(t.startswith("A paragraph that is set justified") and
                            t.endswith("then ends short.") for t in texts), texts)

    def test_a_line_between_them_is_not_centred(self):
        p = [p for t, p in _paras(self.out) if t.startswith("You can choose")][0]
        self.assertNotIn('w:jc w:val="center"', p)


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class ASingleStepAtTheBar(unittest.TestCase):
    """PARA_STEP_RECUR: a step the block takes ONCE must clear
    PARA_STEP_ALONE_EM. y20 sets its heading +2.20pt (0.2em at 11pt, the bar
    exactly) over its body's pitch; split there, Google Docs set the body a
    line longer and the page under it a line low (live dy_p50 5.18 -> 18.05).
    The same block with a step of 0.33em -- y02's requirement tables -- splits."""

    @classmethod
    def setUpClass(cls):
        from exactdoc.convert import convert
        from exactdoc.options import RAW
        cls._dir = tempfile.TemporaryDirectory()
        cls.out = {}
        for name, step in (("bar", 15.69 + 2.20), ("wide", 15.69 + 3.6)):
            pdf = _heading_pdf(os.path.join(cls._dir.name, name + ".pdf"), step)
            cls.out[name] = os.path.join(cls._dir.name, name + ".docx")
            convert(pdf, cls.out[name], options=RAW)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def _heading_alone(self, name):
        return [t.strip() for t, _ in _paras(self.out[name])].count("1.1.1. Rockets at a glance")

    def test_a_single_step_at_the_bar_does_not_split(self):
        self.assertEqual(self._heading_alone("bar"), 0,
                         [t for t, _ in _paras(self.out["bar"])])

    def test_a_single_wide_step_splits(self):
        self.assertEqual(self._heading_alone("wide"), 1,
                         [t for t, _ in _paras(self.out["wide"])])


if __name__ == "__main__":
    unittest.main()
