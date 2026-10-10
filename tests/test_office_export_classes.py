"""Office and Google Docs export classes (WP15): slides, pleadings, folios, blanks.

Each test pins one finding, measured on the expansion corpus:

1. A slide is page-locked, not flowed (`infer._deck_pages`, `_lock_slide`,
   `_float_graphics`; writer: framePr, tblpPr, wp:anchor). y34's 40 slides
   rendered 98 pages flowed; locked, 40.
2. A blank source page survives (`docxout._blank_page_holder`): Google Docs
   exports empty pages, and folding one away put every later word of y32 on
   the wrong page.
3. Pleading paper's 1-28 line-number gutter is furniture
   (`parse_pdfium._line_number_gutter`, `infer._page_number_gutter`), its
   margin rules are not the body's edge (`PAGE_RULE_FRAC`), and double-spaced
   paragraphs are split where the author broke them (`_author_break`).
4. Upright digits stacked at a line pitch are lines, not a vertical run
   (`parse_pdfium._upright_stack`).
5. Running heads and feet set far in, mirrored, or varying with the section
   are consumed with their rule (`infer._mirrored_furniture`).
6. A numbered heading's "2.5" is glued to its text; a row of graphics is one
   figure.
"""
import os
import re
import tempfile
import unittest
import zipfile

from exactdoc import infer as I
from exactdoc import parse_pdfium as P
from exactdoc.docxout import write_docx
from exactdoc.layout import (Chunk, DocLayout, FigureEl, FloatEl, ImageEl,
                             PageLayout, Para, RuleEl, Run)
from exactdoc.model import DocIR, DrawCmd, Line, PageIR, Span, TextBlock

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:          # pragma: no cover
    _canvas = None


# ---------------------------------------------------------------- helpers
def _char(u, x, oy, size=14.0, turned=False):
    c = P._Char()
    c.u = u
    c.ox, c.oy = x, oy
    c.x0, c.y0, c.x1, c.y1 = x, oy - 0.9 * size, x + 0.5 * size, oy + 0.2 * size
    c.size = size
    c.font = "Times"
    c.flags = 0
    c.color = "#000000"
    c.gen = False
    c.turned = turned
    return c


def _word(text, x, oy, size=14.0):
    out = []
    for i, u in enumerate(text):
        out.append(_char(u, x + i * 0.5 * size, oy, size))
    return out


def _span(text, x0, y0, x1, size=11.0, font="Helvetica", baseline=None):
    base = baseline if baseline is not None else y0 + 0.8 * size
    return Span(text, font, size, "#000000", False, False, False, False, False,
                (x0, y0, x1, y0 + 1.2 * size), (x0, base))


def _line(text, x0, y0, x1, size=11.0, baseline=None):
    s = _span(text, x0, y0, x1, size, baseline=baseline)
    return Line([s], s.bbox)


def _block(lines):
    bb = None
    for l in lines:
        bb = l.bbox if bb is None else (min(bb[0], l.bbox[0]), min(bb[1], l.bbox[1]),
                                        max(bb[2], l.bbox[2]), max(bb[3], l.bbox[3]))
    return TextBlock(list(lines), bb)


def _draw(shape, bbox, kind="fill", fill="#000000", stroke=None, width=1.0):
    return DrawCmd(kind=kind, shape=shape, bbox=bbox, fill=fill, stroke=stroke,
                   width=width, opacity=1.0, n_items=1)


def _para(text, before=0.0, frame=None):
    return Para(runs=[Run(text=text, font="Helvetica", size=11.0,
                          color="#000000")],
                leading=14.0, space_before=before, src_lines=1, frame=frame)


def _write(lay):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "o.docx")
        write_docx(lay, path)
        with zipfile.ZipFile(path) as z:
            return z.read("word/document.xml").decode("utf-8")


def _paragraphs(xml):
    return re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S)


# ---------------------------------------------------------------- parser
class UprightStacks(unittest.TestCase):
    """Finding 4: the pleading gutter's 1-9 were read as "123456789"."""

    def test_upright_digits_at_a_line_pitch_stay_in_the_flow(self):
        chars = [_char(str(i), 50.8, 73.0 + 24.1 * (i - 1)) for i in range(1, 10)]
        flow, rotated = P._split_vertical_runs(chars)
        self.assertEqual(rotated, [])
        self.assertEqual(len(flow), 9)

    def test_turned_glyphs_are_still_a_vertical_run(self):
        chars = [_char(u, 18.0, 200.0 + 5.0 * i, size=10.0, turned=True)
                 for i, u in enumerate("available free of charge")]
        flow, rotated = P._split_vertical_runs(chars)
        self.assertEqual(len(rotated), 1)

    def test_upright_pieces_closer_than_a_line_stay_a_run(self):
        # a TeX brace: upright extension glyphs abutting at 0.5em
        chars = [_char("⎢", 53.5, 160.0 + 5.0 * i, size=10.0)
                 for i in range(10)]
        _flow, rotated = P._split_vertical_runs(chars)
        self.assertEqual(len(rotated), 1)

    def test_a_chart_axis_counting_down_stays_a_run(self):
        # y21's y axis: "876543210" reading down, a line pitch apart
        chars = [_char(str(8 - i), 321.0, 160.0 + 15.0 * i, size=9.0)
                 for i in range(9)]
        _flow, rotated = P._split_vertical_runs(chars)
        self.assertEqual(len(rotated), 1)

    def test_digits_running_on_into_letters_stay_a_run(self):
        # y03's S-box row labels 0-9 then a-f
        chars = [_char(u, 121.0, 491.0 + 13.0 * i, size=10.8)
                 for i, u in enumerate("0123456789abcdef")]
        _flow, rotated = P._split_vertical_runs(chars)
        self.assertEqual(len(rotated), 1)


def _pleading_rows(start=1, n=12, body_x=72.0, extra=()):
    """Rows of a pleading page: a right-aligned number at x1=57.8, a body line."""
    rows = []
    for k in range(n):
        v = start + k
        y = 73.0 + 24.1 * k
        digits = str(v)
        num = [_char(d, 57.8 - 7.0 * (len(digits) - i), y) for i, d in enumerate(digits)]
        for c in num:
            c.x1 = c.x0 + 7.0
        rows.append(num + _word("text of line %d" % v, body_x, y))
    for r in extra:
        rows.append(r)
    return rows


class LineNumberGutter(unittest.TestCase):
    """Finding 3: the gutter is detected, split off and blocked apart."""

    def test_a_page_numbering_its_lines_has_a_gutter(self):
        self.assertAlmostEqual(P._line_number_gutter(_pleading_rows()), 57.8, 1)

    def test_a_table_index_column_counting_on_is_not_a_gutter(self):
        # c3_tables: 10-38 on its second page
        self.assertIsNone(P._line_number_gutter(_pleading_rows(start=10)))

    def test_text_left_of_the_numbers_is_not_a_gutter(self):
        extra = [_word("Paragraph above the table", 40.0, 30.0)]
        self.assertIsNone(P._line_number_gutter(_pleading_rows(extra=extra)))

    def test_the_number_is_split_from_the_line_it_numbers(self):
        chars = [c for row in _pleading_rows() for c in row]
        lines = P._build_lines(chars)
        nums = [l for l in lines if getattr(l, "_gutter", False)]
        self.assertEqual(len(nums), 12)
        body = [l for l in lines if not getattr(l, "_gutter", False)]
        self.assertTrue(all(l.bbox[0] >= 71.9 for l in body))
        self.assertTrue(all(l.text.startswith("text of line") for l in body))

    def test_the_gutter_is_blocked_apart_from_the_body(self):
        chars = [c for row in _pleading_rows() for c in row]
        blocks = P._blocks_apart_from_gutter(P._build_lines(chars), 612.0)
        gutter = [b for b in blocks if all(getattr(l, "_gutter", False) for l in b.lines)]
        self.assertEqual(len(gutter), 1)
        self.assertEqual(len(gutter[0].lines), 12)


# ---------------------------------------------------------------- furniture
def _gutter_page(number, start=1, n=10, height=792.0, extra_lines=()):
    lines = []
    for k in range(n):
        y = 63.0 + 24.1 * k
        lines.append(_line(str(start + k), 50.8, y, 57.8, size=14.0))
    body = [_line("body text line %d" % k, 72.0, 63.0 + 24.1 * k, 500.0, size=14.0)
            for k in range(n)]
    body += list(extra_lines)
    return PageIR(number=number, width=612.0, height=height,
                  blocks=[_block(body), _block(lines)],
                  drawings=[_draw("vline", (64.8, 0.0, 64.8, height), kind="stroke",
                                  fill=None, stroke="#000000", width=0.75)])


class PleadingFurniture(unittest.TestCase):
    def test_the_gutter_is_consumed_on_every_page(self):
        ir = DocIR(path="x.pdf", pages=[_gutter_page(i) for i in (1, 2, 3)])
        res = I.detect_hf(ir)
        for pn in (1, 2, 3):
            self.assertEqual(len(res["gutter"][pn]), 10)
            self.assertEqual(len(res["consumed_text"][pn]), 10)

    def test_a_counting_table_column_is_not_consumed(self):
        pages = [_gutter_page(1, start=10)]
        res = I.detect_hf(DocIR(path="x.pdf", pages=pages))
        self.assertFalse(res["gutter"])

    def test_a_full_height_margin_rule_is_consumed_and_bounds_nothing(self):
        ir = DocIR(path="x.pdf", pages=[_gutter_page(i) for i in (1, 2)])
        res = I.detect_hf(ir)
        self.assertEqual(res["consumed_draw"][1], {0})
        lay = I.infer(ir)
        self.assertGreater(lay.margin_t, 40.0)


# Body text that differs from page to page and carries no page number, so no
# furniture pass can take it for a running line.
_BODY = ["Toolbars hold the commands", "Rulers measure the page",
         "The status bar reports the count", "Menus open on a click",
         "Styles keep a document consistent", "Templates start a document",
         "Fields update themselves", "Frames hold positioned text",
         "Sections change the columns", "Lists number their items",
         "Tables arrange their cells", "Footnotes carry the asides",
         "Indexes collect the terms"]


def _folio_page(number, text, y0=772.0, height=842.0, rule=True):
    body = _line(_BODY[number % len(_BODY)], 70.0, 300.0, 520.0)
    foot = _line(text, 70.0 if number % 2 == 0 else 377.0, y0,
                 200.0 if number % 2 == 0 else 542.0, size=10.3)
    draws = []
    if rule:
        draws.append(_draw("hline", (51.0, y0 - 1.4, 544.0, y0 - 1.4),
                           kind="stroke", fill=None, stroke="#000000", width=0.5))
    return PageIR(number=number, width=595.0, height=height,
                  blocks=[_block([body]), _block([foot])], drawings=draws)


class RunningRules(unittest.TestCase):
    """Finding 5, on y36's shape: feet 70pt up, mirrored, varying by section,
    each set under a rule."""

    N = 12      # the parity pass reads documents of PARITY_MIN_PAGES and more

    def _pages(self):
        self.assertGreaterEqual(self.N, I.PARITY_MIN_PAGES)
        pages = []
        sections = ["Parts of the main window"] * 6 + ["Creating a document"] * 6
        for n in range(1, self.N + 1):
            text = ("%d | Chapter 1 Introducing Writer" % n) if n % 2 == 0 \
                else ("%s | %d" % (sections[n - 1], n))
            pages.append(_folio_page(n, text))
        return pages

    def test_a_running_foots_rule_goes_with_it(self):
        # The feet themselves are the running-furniture passes' (extended
        # band, by parity, from page 2); the rule each is set against is
        # this pass's, and goes to the part as the foot's border.
        res = I.detect_hf(DocIR(path="x.pdf", pages=self._pages()))
        for pn in range(2, self.N + 1):
            self.assertEqual(len(res["consumed_text"][pn]), 1, pn)
            self.assertEqual(res["consumed_draw"][pn], {0}, pn)
            self.assertIn(0, [di for z, di, _d in res["rep_draws"][pn] if z == "bot"])

    def test_a_rule_beside_no_running_line_stays(self):
        pages = self._pages()
        for p in pages:
            p.blocks = p.blocks[:1]             # the feet gone
        res = I.detect_hf(DocIR(path="x.pdf", pages=pages))
        self.assertFalse(any(res["consumed_draw"].values()))

    def test_a_repeated_row_of_cells_is_not_furniture(self):
        # a spreadsheet's header row repeated on every page: several lines on
        # one baseline inside the band, identical text -- content
        pages = []
        for n in range(1, 7):
            cells = [_line("Rate", 60.0, 70.0, 90.0), _line("Band", 200.0, 70.0, 230.0)]
            body = _line("row data", 60.0, 200.0, 300.0)
            pages.append(PageIR(number=n, width=595.0, height=842.0,
                                blocks=[_block(cells), _block([body])]))
        res = I.detect_hf(DocIR(path="x.pdf", pages=pages))
        self.assertFalse(any(res["consumed_text"].values()))


# ---------------------------------------------------------------- paragraphs
class DoubleSpacedParagraphs(unittest.TestCase):
    """Finding 3: a short line before an indent ends a double-spaced paragraph."""

    def _lines(self, pitch):
        rows = [("final decision of the Commissioner and remanding for further", 72, 575),
                ("(See ECF No. 14.)", 72, 176),
                ("Now pending before the Court is a Joint Motion to award fees", 108, 568),
                ("the amount of $5,100.00 under the Equal Access to Justice Act", 72, 546)]
        return [_line(t, x0, 63.0 + pitch * i, x1, size=14.0,
                      baseline=73.0 + pitch * i) for i, (t, x0, x1) in enumerate(rows)]

    def test_double_spaced_text_splits_at_the_authors_break(self):
        groups = I._split_lines_to_paras(self._lines(24.1))
        self.assertEqual([len(g) for g in groups], [2, 2])

    def test_a_heading_gap_is_not_double_spacing(self):
        # y39: a heading 23pt above body set at a 12pt pitch; the median of
        # the block's steps said "double spaced", its tightest step does not
        lines = [_line("3 Extending ensemble filters", 56.0, 100.0, 220.0,
                       size=9.5, baseline=110.0),
                 _line("Algorithms are described to extend the filter", 56.0,
                       123.0, 290.0, size=9.5, baseline=133.0),
                 _line("to the case of a nonlinear model.", 56.0, 135.0, 200.0,
                       size=9.5, baseline=145.0)]
        # the double-spacing rule does not fire; since WP35d the paragraph
        # step does (PARA_STEP_PT: 23pt after a short line over a 12pt pitch),
        # setting the heading apart from its body, which stays together
        # (y39 LibreOffice product dy_p50 10.12 -> 9.80, recall 0.914 kept)
        self.assertEqual([len(g) for g in I._split_lines_to_paras(lines)], [1, 2])
        self.assertFalse(I._author_break(lines[0], lines[1], 290.0, 12.0, 3))

    def test_two_lines_carry_no_pitch(self):
        a = _line("Network Planning Directorate", 65.0, 114.0, 197.0, size=11.0,
                  baseline=123.0)
        b = _line("Published under the transparency requirement", 65.0, 138.0,
                  267.0, size=11.0, baseline=147.5)
        self.assertFalse(I._author_break(a, b, 267.0, 24.5, 2))

    def test_a_stack_of_figures_is_not_prose(self):
        # y47's chart axis: "54" over "52" over "50" at a 15pt pitch for 9pt
        # type -- double-spaced by the numbers, filled by no line breaker
        lines = [_line(str(54 - 2 * i), 196.0, 160.0 + 15.3 * i, 204.0, size=9.0,
                       baseline=170.0 + 15.3 * i) for i in range(6)]
        lines.append(_line("Axis title of the chart here", 196.0, 260.0, 380.0,
                           size=9.0, baseline=270.0))
        self.assertFalse(any(I._author_break(a, b, 380.0, 15.3)
                             for a, b in zip(lines, lines[1:])))

    def test_right_to_left_lines_are_left_alone(self):
        # (boxed as a left-to-right short line would be, so only the script
        # keeps the fit test from firing)
        a = _line("هذا سطر", 72.0, 100.0, 200.0,
                  size=12.0, baseline=110.0)
        b = _line("سطر آخر طويل",
                  72.0, 124.0, 540.0, size=12.0, baseline=134.0)
        self.assertFalse(I._author_break(a, b, 540.0, 24.0))

    def test_single_spaced_text_is_left_to_its_gaps(self):
        groups = I._split_lines_to_paras(self._lines(16.0))
        self.assertEqual([len(g) for g in groups], [4])


class SeparatedMarkers(unittest.TestCase):
    """Finding 6: "2.5" and its heading share a baseline across two blocks."""

    def test_a_section_number_is_a_marker_line(self):
        for t in ("2.5", "2.5.1", "3.1.3."):
            self.assertTrue(I._is_marker_line(_line(t, 70.9, 73.7, 89.0)), t)
        self.assertFalse(I._is_marker_line(_line("2024", 70.9, 73.7, 89.0)))

    def test_a_section_number_glues_to_its_heading(self):
        num = _block([_line("2.5", 70.9, 73.7, 88.9, baseline=84.3)])
        head = _block([_line("Licence holder details", 113.5, 73.7, 354.3,
                             baseline=84.3)])
        out = I._merge_list_markers([num, head])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].lines[0].text.startswith("2.5"))

    def test_a_lone_initial_at_a_column_end_is_not_a_marker(self):
        # y41: "S." ends a left-column line at x 283; the right column's
        # text 21pt away is across the gutter, not its item
        prose = _block([_line("then the eigenvalues of the operator follow from",
                              54.0, 239.0, 292.0, size=10.0, baseline=248.0),
                        _line("S.", 283.0, 251.0, 292.0, size=10.0, baseline=260.0)])
        other = _block([_line("from the literature on representative trees",
                              313.0, 251.0, 560.0, size=10.0, baseline=260.0)])
        self.assertFalse(I._has_item_beside(prose.lines[-1], prose, [prose, other]))

    def test_a_marker_ending_a_block_glues_to_the_item_beside_it(self):
        prose = _block([_line("also 28 U.S.C. 2412(a), (d). The Court addresses",
                              72.0, 425.6, 526.0, size=14.0, baseline=435.5),
                        _line("B.", 72.0, 449.7, 84.9, size=14.0, baseline=459.7)])
        item = _block([_line("Prevailing Party", 108.0, 449.7, 206.4, size=14.0,
                             baseline=459.7)])
        out = I._merge_list_markers([prose, item])
        self.assertEqual(len(out[0].lines), 1)          # "B." left the prose
        merged = out[1].lines[0]
        self.assertTrue(merged.text.startswith("B."))
        self.assertIn("Prevailing Party", merged.text)


class ClustersAndUnderlines(unittest.TestCase):
    def test_a_joint_square_does_not_make_a_box(self):
        cl = [(0, _draw("hline", (71.3, 480.8, 319.0, 481.3))),
              (1, _draw("vline", (319.0, 301.7, 319.5, 480.8))),
              (2, _draw("rect", (319.0, 480.8, 319.5, 481.3)))]
        self.assertNotEqual(I._classify_cluster(cl), "boxlike")

    def test_a_long_rule_under_a_whole_span_is_its_underline(self):
        heading = _line("Whether the Amount Sought is Reasonable", 108.0, 619.0,
                        418.0, size=14.0, baseline=629.0)
        body = _line("The EAJA provides that courts may award reasonable fees",
                     72.0, 643.0, 558.0, size=14.0)
        page = PageIR(number=1, width=612.0, height=792.0,
                      blocks=[_block([heading]), _block([body])],
                      drawings=[_draw("hline", (108.0, 630.6, 417.8, 631.3))])
        lay = I.infer(DocIR(path="x.pdf", pages=[page]))
        els = [e for ch in lay.pages[0].chunks for e in ch.elements]
        self.assertFalse(any(isinstance(e, RuleEl) for e in els))
        self.assertTrue(heading.spans[0]._ul)


# ---------------------------------------------------------------- slides
def _slide(number, title="Outline", body_size=24.0, width=960.0, height=540.0,
           image=True):
    lines = [_line("The American Community Survey", 58.0, 26.0, 431.0, size=28.0),
             _line(title, 58.0, 62.0, 200.0, size=24.0),
             _line("A bullet set in presentation type", 73.0, 120.0, 500.0,
                   size=body_size),
             _line("Another bullet beside a picture", 73.0, 170.0, 520.0,
                   size=body_size),
             _line(str(number), 880.0, 510.0, 887.0, size=12.0)]
    page = PageIR(number=number, width=width, height=height,
                  blocks=[_block([l]) for l in lines])
    if image:
        from exactdoc.model import ImageObj
        page.images = [ImageObj(bbox=(0.0, 459.0, 143.0, 540.0), xref=1, width=1,
                                height=1, data=_PNG, ext="png")]
    return page


_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cf0000000301010018dd8db00000000049454e44ae426082")


class SlideDecks(unittest.TestCase):
    def _ir(self, **kw):
        return DocIR(path="x.pdf", pages=[_slide(i, **kw) for i in (1, 2, 3)])

    def test_landscape_pages_in_presentation_type_are_a_deck(self):
        ir = self._ir()
        self.assertEqual(I._deck_pages(ir, I.detect_hf(ir)), frozenset({1, 2, 3}))

    def test_landscape_pages_in_document_type_are_not(self):
        ir = self._ir(body_size=9.0)
        for p in ir.pages:
            for b in p.blocks:
                for l in b.lines:
                    for s in l.spans:
                        s.size = 9.0
        self.assertEqual(I._deck_pages(ir, I.detect_hf(ir)), frozenset())

    def test_portrait_pages_are_not(self):
        ir = self._ir(width=612.0, height=792.0)
        self.assertEqual(I._deck_pages(ir, I.detect_hf(ir)), frozenset())

    def test_a_slide_is_page_locked(self):
        lay = I.infer(self._ir())
        self.assertIsNone(lay.header_default)        # no furniture on a deck
        self.assertLessEqual(lay.margin_b, I.DECK_MARGIN_B)
        pg = lay.pages[0]
        paras = [e for ch in pg.chunks for e in ch.elements if isinstance(e, Para)]
        self.assertTrue(paras and all(p.frame is not None for p in paras))
        self.assertEqual(len(pg.floats), 1)
        self.assertIsInstance(pg.floats[0].el, ImageEl)
        bullet = [p for p in paras if p.text.startswith("A bullet")][0]
        x, y, w = bullet.frame
        self.assertAlmostEqual(x, 73.0, 0)
        # baseline-anchored: top = baseline - (leading - 0.21 * size)
        self.assertAlmostEqual(y, 120.0 + 0.8 * 24.0 - (bullet.leading - 0.21 * 24.0), 0)

    def test_without_the_capability_a_slide_still_flows(self):
        lay = I.infer(self._ir(), anchored=False)
        pg = lay.pages[0]
        self.assertFalse(pg.floats)
        self.assertFalse(any(getattr(e, "frame", None) for ch in pg.chunks
                             for e in ch.elements))


class SlideWriter(unittest.TestCase):
    def _lay(self):
        img = ImageEl(data=_PNG, ext="png", width=143.0, height=81.0)
        p1 = PageLayout(number=1, chunks=[Chunk(elements=[
            _para("Title", frame=(58.0, 30.0, 400.0)),
            _para("Bullet", frame=(73.0, 110.0, 500.0))])],
            floats=[FloatEl(el=img, bbox=(0.0, 459.0, 143.0, 540.0))])
        p2 = PageLayout(number=2, chunks=[Chunk(elements=[
            _para("Second slide", frame=(58.0, 30.0, 400.0))])])
        return DocLayout(page_w=960.0, page_h=540.0, margin_l=50.0, margin_r=50.0,
                         margin_t=12.0, margin_b=4.0, pages=[p1, p2])

    def test_frames_are_page_anchored_where_the_source_set_them(self):
        xml = _write(self._lay())
        fps = re.findall(r"<w:framePr [^>]*/>", xml)
        self.assertEqual(len(fps), 3)
        self.assertIn('w:x="1460"', fps[1])       # 73pt
        self.assertIn('w:y="2200"', fps[1])       # 110pt
        self.assertTrue(all('w:hAnchor="page"' in f and 'w:vAnchor="page"' in f
                            for f in fps))

    def test_a_slide_page_is_holder_frames_anchor(self):
        paras = _paragraphs(_write(self._lay()))
        kinds = ["F" if "<w:framePr" in p else
                 ("B" if "<w:pageBreakBefore/>" in p else "H") for p in paras]
        # slide 1: holder (with the picture), two frames, the anchor; slide
        # 2: a holder carrying the seam, its frame, the anchor
        self.assertEqual(kinds, ["H", "F", "F", "H", "B", "F", "H"])
        self.assertIn("<wp:anchor", paras[0])
        self.assertIn('relativeFrom="page"', paras[0])
        self.assertNotIn("<wp:inline", paras[0])


class BlankPages(unittest.TestCase):
    """Finding 2."""

    def _lay(self, overflow=False):
        first = [_para("Cover page")]
        if overflow:
            first.append(_para("tall", before=2000.0))
        return DocLayout(pages=[
            PageLayout(number=1, chunks=[Chunk(elements=first)]),
            PageLayout(number=2, chunks=[Chunk()]),
            PageLayout(number=3, chunks=[Chunk(elements=[_para("Third page")])])])

    def test_a_blank_page_is_held(self):
        paras = _paragraphs(_write(self._lay()))
        breaks = [p for p in paras if "<w:pageBreakBefore/>" in p]
        self.assertEqual(len(breaks), 2)
        self.assertNotIn("Third page", breaks[0])
        self.assertIn("Third page", breaks[1])

    def test_behind_a_page_that_overflows_the_spill_takes_its_place(self):
        paras = _paragraphs(_write(self._lay(overflow=True)))
        breaks = [p for p in paras if "<w:pageBreakBefore/>" in p]
        self.assertEqual(len(breaks), 1)


class GraphicRows(unittest.TestCase):
    def test_side_by_side_graphics_become_one_figure(self):
        crest = FigureEl(page_no=1, clip=(0.0, 772.0, 142.0, 814.0), width=142.0,
                         height=42.0)
        logo = ImageEl(data=_PNG, ext="png", width=181.0, height=43.0)
        logo._bbox = (353.0, 770.0, 534.0, 813.0)
        out = I._merge_graphic_rows([crest, logo], [], 1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].clip, (0.0, 770.0, 534.0, 814.0))

    def test_not_across_live_text(self):
        crest = FigureEl(page_no=1, clip=(0.0, 772.0, 142.0, 814.0), width=142.0,
                         height=42.0)
        logo = ImageEl(data=_PNG, ext="png", width=181.0, height=43.0)
        logo._bbox = (353.0, 770.0, 534.0, 813.0)
        text = _block([_line("between them", 200.0, 780.0, 300.0)])
        self.assertEqual(len(I._merge_graphic_rows([crest, logo], [text], 1)), 2)


class Backgrounds(unittest.TestCase):
    """A picture text is set on, or printed into a margin, leaves the flow."""

    def _lay(self):
        return DocLayout(page_w=595.0, page_h=842.0, margin_l=72.0, margin_r=72.0,
                         margin_t=72.0, margin_b=60.0)

    def test_a_panel_under_text_floats_behind_it(self):
        panel = ImageEl(data=_PNG, ext="png", width=594.0, height=654.0)
        panel._bbox = (0.0, 100.0, 594.0, 754.0)
        text = _block([_line("Submissions process", 71.0, 136.0, 236.0)])
        keep, floats = I._float_backgrounds([panel], [text], self._lay(), 595.0, 842.0)
        self.assertEqual(keep, [])
        self.assertTrue(floats[0].behind)

    def test_a_picture_bleeding_off_the_foot_floats_in_front(self):
        art = ImageEl(data=_PNG, ext="png", width=595.0, height=312.0)
        art._bbox = (0.0, 530.0, 595.0, 842.0)
        keep, floats = I._float_backgrounds([art], [], self._lay(), 595.0, 842.0)
        self.assertEqual(len(floats), 1)
        self.assertFalse(floats[0].behind)

    def test_a_full_page_picture_is_left_to_the_writers_rule(self):
        # d630b33 anchors a picture that fills the page, in every profile;
        # neither float pass may take it first
        cover = ImageEl(data=_PNG, ext="png", width=595.0, height=842.0)
        cover._bbox = (0.0, 0.0, 595.0, 842.0)
        text = _block([_line("Discussion paper", 70.0, 300.0, 300.0)])
        keep, floats = I._float_backgrounds([cover], [text], self._lay(),
                                            595.0, 842.0)
        self.assertEqual((keep, floats), ([cover], []))
        keep, floats = I._float_graphics([cover], [text], 595.0, 842.0)
        self.assertEqual((keep, floats), ([cover], []))

    def test_the_full_page_share_is_the_writers(self):
        from exactdoc import docxout
        self.assertEqual(I.FULL_PAGE_FRAC, docxout._FULL_PAGE_FRAC)

    def test_an_ordinary_figure_stays_in_the_flow(self):
        fig = ImageEl(data=_PNG, ext="png", width=300.0, height=200.0)
        fig._bbox = (150.0, 300.0, 450.0, 500.0)
        text = _block([_line("Caption below the figure", 150.0, 510.0, 400.0)])
        keep, floats = I._float_backgrounds([fig], [text], self._lay(), 595.0, 842.0)
        self.assertEqual((len(keep), len(floats)), (1, 0))


class FrontMatterFolios(unittest.TestCase):
    def test_roman_folios_at_the_body_folios_place_are_furniture(self):
        pages = []
        for n in range(1, 13):
            folio = ["", "", "iii", "iv", "v"][n - 1] if n <= 5 else str(n - 5)
            body = _line(_BODY[n % len(_BODY)], 72.0, 300.0, 500.0)
            lines = [_block([body])]
            if folio:
                lines.append(_block([_line(folio, 494.0, 744.5, 504.0, size=9.0)]))
            pages.append(PageIR(number=n, width=612.0, height=792.0, blocks=lines))
        res = I.detect_hf(DocIR(path="x.pdf", pages=pages))
        for n in (3, 4, 5):
            self.assertEqual(len(res["consumed_text"][n]), 1, n)


class Spreadsheets(unittest.TestCase):
    """y35: two right-aligned columns of rates, no rules, no prose."""

    def _body(self):
        out = []
        for pg in (1, 2):
            for k in range(30):
                y = 80.0 + 9.4 * k
                out.append((pg, _line("label %d" % k, 56.0, y, 200.0, size=7.0)))
                out.append((pg, _line("%d.%02d" % (k, k), 370.0, y, 387.0, size=7.0)))
                out.append((pg, _line("%d.%02d" % (k + 1, k), 448.0, y, 465.0, size=7.0)))
        return out

    def test_the_rightmost_column_of_figures_is_the_edge(self):
        self.assertAlmostEqual(I._numeric_column_edge(self._body(), 5, 595.0), 465.0)

    def test_figures_outnumbered_by_wide_prose_do_not_widen(self):
        self.assertIsNone(I._numeric_column_edge(self._body(), 500, 595.0))

    @staticmethod
    def _chunks(two_value_columns):
        blocks = []
        for k in range(12):
            y = 80.0 + 30.0 * k
            blocks.append(_block([_line("Rate label number %s" % "abcdefghijkl"[k],
                                        56.0, y, 250.0, size=9.0)]))
            if two_value_columns:
                blocks.append(_block([_line("%d.50" % (k + 10), 370.0, y, 387.0,
                                            size=9.0)]))
            blocks.append(_block([_line("%d.75" % (k + 10), 448.0, y, 465.0,
                                        size=9.0)]))
        lay = DocLayout(page_w=595.0, page_h=842.0, margin_l=56.0, margin_r=130.0,
                        margin_t=72.0, margin_b=72.0)
        page = PageIR(number=1, width=595.0, height=842.0, blocks=blocks)
        return I._assemble_chunks([], blocks, lay, page)

    def test_two_columns_of_figures_are_a_table_not_two_text_columns(self):
        self.assertTrue(all(ch.n_cols == 1 for ch in self._chunks(True)))

    def test_figure_columns_do_not_outvote_a_text_column(self):
        # y60 (MMWR): a table's figure columns outnumbered the page's real
        # right-hand text column; the split must still fall at the text
        blocks = []
        for k in range(14):
            y = 80.0 + 30.0 * k
            blocks.append(_block([_line("Left column prose line number %d of it" % k,
                                        36.0, y, 290.0, size=9.0)]))
            blocks.append(_block([_line("Right column prose line %d of the page" % k,
                                        319.0, y, 576.0, size=9.0)]))
            for dy in (5.0, 15.0):          # more figure blocks than text ones
                blocks.append(_block([_line("%d.5" % (k + 70), 400.0, y + dy, 420.0,
                                            size=9.0)]))
                blocks.append(_block([_line("%d.1" % (k + 80), 470.0, y + dy, 490.0,
                                            size=9.0)]))
        lay = DocLayout(page_w=612.0, page_h=792.0, margin_l=36.0, margin_r=36.0,
                        margin_t=60.0, margin_b=60.0)
        page = PageIR(number=1, width=612.0, height=792.0, blocks=blocks)
        chunks = I._assemble_chunks([], blocks, lay, page)
        two = [ch for ch in chunks if ch.n_cols == 2]
        self.assertTrue(two)
        right = two[0].elements[two[0].elements.index(
            next(e for e in two[0].elements if type(e).__name__ == "ColBreak")) + 1:]
        self.assertTrue(any(getattr(e, "text", "").startswith("Right column")
                            for e in right))

    def test_a_lone_column_of_figures_keeps_the_two_column_reading(self):
        # a contents page's page numbers (y32): as rows its short titles fall
        # under the row-pair label floor and each number stood alone
        self.assertTrue(any(ch.n_cols == 2 for ch in self._chunks(False)))


class HeaderGutter(unittest.TestCase):
    def test_a_page_locked_gutter_is_written_as_a_header_frame(self):
        ir = DocIR(path="x.pdf", pages=[_gutter_page(i) for i in (1, 2, 3)])
        lay = I.infer(ir)
        part = lay.header_default
        self.assertIsNotNone(part)
        framed = [e for e in part.elements if getattr(e, "frame", None)]
        self.assertEqual(len(framed), 1)
        self.assertEqual(framed[0].text.count("\n"), 9)
        self.assertAlmostEqual(framed[0].leading, 24.1, 1)
        # the frame is followed by the paragraph LibreOffice anchors it to
        self.assertIs(part.elements[-1].frame, None)

    def test_without_the_capability_the_gutter_is_not_printed(self):
        ir = DocIR(path="x.pdf", pages=[_gutter_page(i) for i in (1, 2, 3)])
        lay = I.infer(ir, anchored=False)
        self.assertFalse(lay.header_default and any(
            getattr(e, "frame", None) for e in lay.header_default.elements))


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class EndToEnd(unittest.TestCase):
    """A two-slide deck through the shipped profiles."""

    @classmethod
    def setUpClass(cls):
        from exactdoc.convert import convert
        from exactdoc.options import PDFIUM_GDOCS_CANDIDATE, RAW
        cls._dir = tempfile.TemporaryDirectory()
        pdf = os.path.join(cls._dir.name, "deck.pdf")
        c = _canvas.Canvas(pdf, pagesize=(960, 540))
        for n in (1, 2):
            c.setFont("Helvetica", 28)
            c.drawString(58, 540 - 54, "The Survey")
            c.setFont("Helvetica", 24)
            c.drawString(58, 540 - 82, "Slide title %d" % n)
            c.setFont("Helvetica", 20)
            c.drawString(73, 540 - 140, "First bullet of slide %d" % n)
            c.drawString(73, 540 - 180, "Second bullet of slide %d" % n)
            c.setFillColorRGB(0.2, 0.3, 0.6)
            c.rect(600, 540 - 400, 300, 200, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)
            c.setFont("Helvetica", 12)
            c.drawString(880, 540 - 520, str(n))
            c.showPage()
        c.save()
        cls.std = os.path.join(cls._dir.name, "std.docx")
        cls.gd = os.path.join(cls._dir.name, "gd.docx")
        convert(pdf, cls.std, options=RAW)
        convert(pdf, cls.gd, options=PDFIUM_GDOCS_CANDIDATE)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    @staticmethod
    def _xml(path):
        with zipfile.ZipFile(path) as z:
            return z.read("word/document.xml").decode("utf-8")

    def test_the_standard_profile_locks_the_slides(self):
        xml = self._xml(self.std)
        self.assertGreaterEqual(xml.count("<w:framePr "), 8)
        self.assertEqual(xml.count("<w:pageBreakBefore/>"), 1)

    def test_the_gdocs_profile_keeps_the_flow(self):
        xml = self._xml(self.gd)
        self.assertNotIn("<w:framePr", xml)
        self.assertNotIn("<wp:anchor", xml)


if __name__ == "__main__":
    unittest.main()
