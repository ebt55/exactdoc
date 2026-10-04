"""Verbatim mono blocks keep their line breaks (defect catalogue #2).

A block whose every glyph is monospace is verbatim matter; its line breaks
are semantic. Live-verified in Google Docs: such a block emitted as one
run-per-line paragraph with space joiners collapsed onto a single wrapped
line. The join now keeps each source line, separated by "\n" the writer
renders as w:br, and `_mergeable` refuses to merge break-carrying
paragraphs with neighbours.
"""
import unittest

from exactdoc.infer import _mergeable, para_from_lines
from exactdoc.layout import Para, Run
from exactdoc.model import Line, Span


def _line(text, x0, x1, y, mono=True, font="Consolas"):
    return Line(
        spans=[Span(text=text, font=font, size=9.0, color="#000000",
                    bold=False, italic=False, mono=mono, serif=not mono,
                    superscript=False, bbox=(x0, y - 9, x1, y),
                    origin=(x0, y))],
        bbox=(x0, y - 9, x1, y))


def _runs(text, mono=True):
    return [Run(text=text, font="Consolas" if mono else "Georgia",
                size=9.0, color="#000000", bold=False, italic=False,
                mono=mono, serif=not mono)]


COL_L, COL_R = 57.0, 539.0


class MonoBlockBreaks(unittest.TestCase):
    def test_all_mono_lines_keep_breaks(self):
        lines = [_line("import json", 90, 150, 100.0),
                 _line("data = json.loads(text)", 90, 240, 114.0),
                 _line("print(data['x'])", 90, 200, 128.0)]
        p = para_from_lines(lines, COL_L, COL_R)
        self.assertTrue(p.line_breaks)
        joined = "".join(r.text for r in p.runs)
        self.assertIn("json.loads(text)\n", joined)
        self.assertEqual(joined.count("\n"), 2)

    def test_equal_length_code_lines_are_not_a_justified_edge(self):
        """y26: `if test-commands; then` / `  consequent-commands;` are both 22
        characters, so in a monospace face they END at the same x, and the
        justify test pinned a 219.6pt right indent that left the block exactly
        its widest line -- the third line wrapped and spilled the page."""
        lines = [_line("if test-commands; then", 176, 302, 678.0, font="CMTT10"),
                 _line("  consequent-commands;", 176, 302, 692.0, font="CMTT10"),
                 _line("[elif more-test-commands; then", 176, 348, 705.0,
                       font="CMTT10")]
        p = para_from_lines(lines, COL_L, COL_R)
        self.assertTrue(p.line_breaks)
        self.assertEqual(p.align, "left")
        self.assertEqual(p.right_indent, 0.0)
        # a prose paragraph with the same geometry still pins its edge
        prose = [_line(t, 176, 302 if i < 2 else 348, y, mono=False,
                       font="Georgia")
                 for i, (t, y) in enumerate((("aaaa bbbb", 678.0),
                                             ("cccc dddd", 692.0),
                                             ("eeee ffff gg", 705.0)))]
        q = para_from_lines(prose, COL_L, COL_R)
        self.assertEqual(q.align, "justify")
        self.assertGreater(q.right_indent, 0.0)

    def test_prose_paragraph_still_joins_with_spaces(self):
        lines = [_line("first prose line here", 57, 300, 100.0, mono=False,
                       font="Georgia"),
                 _line("second line follows", 57, 280, 114.0, mono=False,
                       font="Georgia")]
        p = para_from_lines(lines, COL_L, COL_R)
        self.assertFalse(p.line_breaks)
        joined = "".join(r.text for r in p.runs)
        self.assertIn("here second", joined)

    def test_mixed_block_is_not_verbatim(self):
        # one prose span disqualifies the block: a stray mono run inside
        # prose must not lock the paragraph's lines
        lines = [_line("purely code", 57, 200, 100.0),
                 _line("mono then ", 57, 150, 114.0),
                 ]
        lines[1].spans.append(Span(text="but this is prose", font="Georgia",
                                   size=10.0, color="#000000", bold=False,
                                   italic=False, mono=False, serif=True,
                                   superscript=False,
                                   bbox=(150, 105, 300, 114), origin=(150, 114)))
        lines[1].bbox = (57, 105, 300, 114)
        p = para_from_lines(lines, COL_L, COL_R)
        self.assertFalse(p.line_breaks)

    def test_break_paragraphs_do_not_merge(self):
        a = Para(runs=_runs("line one\n"))
        a.line_breaks = True
        a.bbox = (57.0, 91.0, 200.0, 100.0)
        b = Para(runs=_runs("next block"))
        b.bbox = (57.0, 101.0, 200.0, 110.0)
        self.assertFalse(_mergeable(a, b))

    def test_prose_paragraphs_still_merge(self):
        a = Para(runs=_runs("first", mono=False))
        a.bbox = (57.0, 91.0, 257.0, 100.0)
        b = Para(runs=_runs("second", mono=False))
        b.bbox = (57.0, 101.0, 257.0, 110.0)
        self.assertTrue(_mergeable(a, b))


if __name__ == "__main__":
    unittest.main()
