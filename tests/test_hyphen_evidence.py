"""Line-end hyphens decided by the document's vocabulary (catalogue #2, #17, #18).

Geometry alone (justified + at the wrap edge) kept 464 breaks mid-word on a
ragged booklet (`re-turn`), 205 on a justified opinion whose lines miss the
edge test, and deleted real hyphens in a justified paper that never
hyphenates (`singlecorpus`). PDFium hands every line-end hyphen back as U+0002
whatever the producer drew, so the code point cannot decide either.

    python tests/test_hyphen_evidence.py
"""
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import hyphen  # noqa: E402
from exactdoc.hyphen import HyphenEvidence, split_pair  # noqa: E402
from exactdoc.infer import _soft_join, infer  # noqa: E402
from exactdoc.layout import DocLayout, Para, Run  # noqa: E402
from exactdoc.model import DocIR, Line, PageIR, Span, TextBlock  # noqa: E402


def _runs(text):
    return [Run(text=text, font="Times", size=10.0, color="#000000")]


def _ev(*blocks):
    return HyphenEvidence([list(b) for b in blocks])


# A document that hyphenates: its breaks resolve to words it spells out whole.
HYPHENATING = [
    ["Congress acted and the meaning of the text was plain to Con-",
     "gress when it wrote the statute, which is the mean-",
     "ing that controls; the return was filed with the re-",
     "turn address and the income was reported as in-",
     "come for the year."],
]
# A document that does not: its line-end hyphens are compounds it also spells
# out mid-line.
COMPOUNDING = [
    ["a single-corpus evaluation over nation-states with a middle-income",
     "panel, where the single-",
     "corpus result held for the nation-",
     "states and the middle-",
     "income group alike."],
]


class Evidence(unittest.TestCase):
    def test_split_pair(self):
        self.assertEqual(split_pair("the meaning of Con-", "gress acted"),
                         ("Con", "gress"))
        self.assertIsNone(split_pair("SHA-", "256 digest"))
        self.assertIsNone(split_pair("Middle-", "Income Trap"))

    def test_document_balance(self):
        self.assertTrue(_ev(*HYPHENATING).hyphenates)
        self.assertFalse(_ev(*COMPOUNDING).hyphenates)
        self.assertIsNone(_ev(["one line only"]).hyphenates)

    def test_attested_joined_form_is_a_break(self):
        ev = _ev(*HYPHENATING)
        self.assertTrue(ev.is_break("Con", "gress", at_edge=False))

    def test_attested_compound_is_kept_even_at_the_edge(self):
        ev = _ev(*COMPOUNDING)
        self.assertFalse(ev.is_break("single", "corpus", at_edge=True))
        self.assertFalse(ev.is_break("nation", "states", at_edge=True))

    def test_unattested_fragment_follows_the_document(self):
        self.assertTrue(_ev(*HYPHENATING).is_break("Ham", "ilton", at_edge=False))
        self.assertFalse(_ev(*COMPOUNDING).is_break("sl", "organism", at_edge=True))

    def test_two_words_in_a_hyphenating_document(self):
        blocks = HYPHENATING + [["a self-serving and self-evident well-known view",
                                 "if ever it contained one"]]
        ev = _ev(*blocks)
        # `which-` builds no compound here: a closed word broken at a morpheme
        self.assertTrue(ev.is_break("which", "ever", at_edge=False))
        # `self-` heads compounds in this document: keep it
        self.assertFalse(ev.is_break("self", "contained", at_edge=True))

    def test_one_letter_side_is_never_a_break(self):
        self.assertFalse(_ev(*HYPHENATING).is_break("e", "mail", at_edge=True))

    def test_geometry_decides_only_without_evidence(self):
        ev = _ev(["nothing hyphenated here at all"])
        self.assertTrue(ev.is_break("zorb", "plix", at_edge=True))
        self.assertFalse(ev.is_break("zorb", "plix", at_edge=False))


class SoftJoinConsultsEvidence(unittest.TestCase):
    def _join(self, ev, text, nxt, at_edge):
        token = hyphen.activate(ev)
        try:
            r = _runs(text)
            _soft_join(r, nxt, dehyphenate=at_edge)
            return r[0].text
        finally:
            hyphen.deactivate(token)

    def test_ragged_break_is_deleted_when_the_word_is_attested(self):
        # the old rule kept it: not justified, not at the edge
        self.assertEqual(self._join(_ev(*HYPHENATING), "the re-", "turn was",
                                    at_edge=False), "the re")

    def test_justified_compound_is_kept(self):
        # the old rule deleted it: justified and at the edge
        self.assertEqual(self._join(_ev(*COMPOUNDING), "a single-", "corpus run",
                                    at_edge=True), "a single-")

    def test_without_evidence_the_geometry_verdict_stands(self):
        r = _runs("black-")
        _soft_join(r, "box", dehyphenate=True)
        self.assertEqual(r[0].text, "black")


def _line(text, y, x0=72.0, x1=None, size=10.0):
    x1 = x1 if x1 is not None else x0 + 5.0 * len(text)
    sp = Span(text=text, font="Times-Roman", size=size, color="#000000",
              bold=False, italic=False, mono=False, serif=True,
              superscript=False, bbox=(x0, y - size, x1, y), origin=(x0, y))
    return Line(spans=[sp], bbox=(x0, y - size, x1, y))


class AutoHyphenation(unittest.TestCase):
    def _ir(self, lines):
        block = TextBlock(lines=lines, bbox=(72, 90, 540, 100 + 14 * len(lines)))
        return DocIR("synthetic.pdf", [PageIR(1, 612, 792, blocks=[block])])

    def test_hyphenated_flag_comes_from_the_vocabulary(self):
        texts = HYPHENATING[0]
        lay = infer(self._ir([_line(t, 100 + 14 * i) for i, t in enumerate(texts)]))
        self.assertTrue(lay.hyphenated)
        texts = COMPOUNDING[0]
        lay = infer(self._ir([_line(t, 100 + 14 * i) for i, t in enumerate(texts)]))
        self.assertFalse(lay.hyphenated)

    def test_unhyphenated_paragraphs_opt_out(self):
        lay = DocLayout()
        lay.hyphenated = True
        from exactdoc.layout import Chunk, PageLayout
        body = Para(runs=_runs("body"), src_lines=4)
        head = Para(runs=_runs("Title"), heading=1, src_lines=1)
        centred = Para(runs=_runs("cover"), align="center", src_lines=2)
        single = Para(runs=_runs("one line"), src_lines=1)
        lay.pages = [PageLayout(number=1, chunks=[Chunk(elements=[
            body, head, centred, single])])]
        self.assertEqual(hyphen.mark_unhyphenated(lay), 3)
        self.assertFalse(getattr(body, "no_hyphenation", False))
        self.assertTrue(head.no_hyphenation and centred.no_hyphenation
                        and single.no_hyphenation)
        lay.hyphenated = False
        other = Para(runs=_runs("x"), heading=1)
        lay.pages[0].chunks[0].elements = [other]
        self.assertEqual(hyphen.mark_unhyphenated(lay), 0)

    def test_writer_places_the_settings_and_the_opt_out(self):
        from exactdoc.docxout import write_docx
        from exactdoc.layout import Chunk, PageLayout
        lay = DocLayout()
        lay.hyphenated = True
        head = Para(runs=_runs("Title"), heading=1, src_lines=1)
        body = Para(runs=_runs("body text " * 20), src_lines=3)
        lay.pages = [PageLayout(number=1, chunks=[Chunk(elements=[head, body])])]
        hyphen.mark_unhyphenated(lay)
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            write_docx(lay, path)
            with zipfile.ZipFile(path) as z:
                settings = z.read("word/settings.xml").decode()
                document = z.read("word/document.xml").decode()
        finally:
            os.unlink(path)
        tab = settings.index("w:defaultTabStop")
        auto = settings.index("w:autoHyphenation")
        caps = settings.index("w:doNotHyphenateCaps")
        self.assertLess(tab, auto)
        self.assertLess(auto, caps)
        self.assertEqual(document.count("w:suppressAutoHyphens"), 1)


if __name__ == "__main__":
    unittest.main()
