"""Résumé structure: the defects that made an ordinary résumé convert wrong.

The release bar names résumés and whitepapers: an ordinary document of that
class must open essentially perfectly. Measured on the owner's résumé and the
x17/x18 fixtures (defect catalogue 2026-10-04 #7, #8, #22; design audit B16):

  * typed list markers ("• text" in ONE span) never opened an item, so x17's
    bullets fused ("…partition loss. • Introduced…" on one line) and RFC 9110
    p40's four one-line items were glued back together by the flow merge;
  * a section rule between two lines of one PDFium block sorted after the
    whole block -- the rule under "SUMMARY" landed under the summary text;
  * a page holding a single role/date row was refused its tab stop because
    the column evidence was counted per page, so the date fell into the
    description below it as a 406pt first-line indent;
  * the content edge was read from ragged prose while the dates and the
    rules both reach 22pt further right;
  * body-size letter-spaced section headings were never headings, so Google
    Docs' outline of a converted résumé was empty;
  * the ladder gave a typed-marker item's first line less room than it has,
    so x17's first bullet was not line-locked and re-wrapped.

    python -m unittest tests.test_resume_structure
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import infer as I  # noqa: E402
from exactdoc import ladder  # noqa: E402
from exactdoc.layout import (Chunk, DocLayout, PageLayout, Para, RuleEl,  # noqa: E402
                             Run)
from exactdoc.metrics import get_metrics  # noqa: E402
from exactdoc.model import DocIR, DrawCmd, Line, PageIR, Span, TextBlock  # noqa: E402

try:
    from reportlab.pdfgen import canvas as _canvas
except ImportError:                                    # pragma: no cover
    _canvas = None


def _span(text, x0, top, size=9.7, font="LiberationSerif", bold=False,
          italic=False, mono=False, x1=None, tracked=False):
    x1 = x1 if x1 is not None else x0 + 0.48 * size * len(text)
    s = Span(text=text, font=font, size=size, color="#111111", bold=bold,
             italic=italic, mono=mono, serif=True, superscript=False,
             bbox=(x0, top, x1, top + 1.1 * size),
             origin=(x0, top + 0.86 * size))
    s.tracked = tracked
    return s


def _ln(text, x0, top, **kw):
    s = _span(text, x0, top, **kw)
    return Line(spans=[s], bbox=s.bbox)


def _blk(lines):
    bb = None
    for ln in lines:
        bb = ln.bbox if bb is None else (min(bb[0], ln.bbox[0]), min(bb[1], ln.bbox[1]),
                                         max(bb[2], ln.bbox[2]), max(bb[3], ln.bbox[3]))
    return ("blk", bb, TextBlock(lines=list(lines), bbox=bb))


def _texts(flow):
    return [(type(e).__name__, e.text if isinstance(e, Para) else "")
            for e in flow]


# x17 page 1, as the parser reports it: CSS `text-indent:-11.5pt` with a
# literal "• " -- the marker shares its span with the item text.
COL_L, COL_R = 43.5, 552.75
X17_ITEMS = [
    ("• Rebuilt the ingestion path so that a replayed shipment event is "
     "idempotent, which removed the nightly reconciliation job", 44.5, 194.6, 541.3),
    ("entirely.", 56.0, 207.4, 92.0),
    ("• Took the p99 of the quoting endpoint from 1.9s to 240ms by moving "
     "the tariff lookup behind a read-through cache.", 44.5, 221.6, 517.9),
    ("• Wrote the migration runbook the team still uses for zero-downtime "
     "schema changes on the shipments table.", 44.5, 235.1, 482.7),
]


def _x17_lines():
    return [_ln(t, x0, top, x1=x1) for t, x0, top, x1 in X17_ITEMS]


class TypedMarkerTokens(unittest.TestCase):
    def test_tokens_that_open_an_item(self):
        for t in ("• Rebuilt the path", "◦ nested", "– an en-dash item",
                  "1. Install", "12) Twelve", "(a) first", "iv. fourth",
                  "(B) upper in parentheses"):
            self.assertIsNotNone(I._inline_marker(t), t)

    def test_tokens_that_do_not(self):
        for t in ("A. Smith and B. Jones", "3.5 years of work", "e.g. this",
                  "i.e. that", "2021. The company", "•Fused", "(1. odd",
                  "IV. Roman heading", "• "):
            self.assertIsNone(I._inline_marker(t), t)

    def test_roman_and_alpha_share_a_style(self):
        style_i, vals_i = I._inline_marker("i. first")
        style_ii, vals_ii = I._inline_marker("ii. second")
        self.assertEqual(style_i, style_ii)
        self.assertIn(1, vals_i)          # roman one
        self.assertIn(9, vals_i)          # ninth letter
        self.assertEqual(vals_ii, {2})


class TypedMarkerEvidence(unittest.TestCase):
    def test_x17_bullets_open_three_items_with_their_hang(self):
        lines = _x17_lines()
        starts = I._inline_list_starts([lines])
        self.assertEqual(len(starts), 3)
        paras = I.paras_from_line_list(lines, COL_L, COL_R, starts)
        self.assertEqual(len(paras), 3, [p.text for p in paras])
        first = paras[0]
        self.assertIn("entirely.", first.text)
        self.assertNotIn("Took", first.text)
        # continuation lines under the text, first line out at the marker
        self.assertAlmostEqual(first.left_indent, 56.0 - COL_L, delta=0.05)
        self.assertAlmostEqual(first.first_indent, 44.5 - 56.0, delta=0.05)
        self.assertTrue(all(p._list_item for p in paras))

    def test_without_evidence_the_old_grouping_stands(self):
        paras = I.paras_from_line_list(_x17_lines(), COL_L, COL_R)
        self.assertEqual(len(paras), 1)

    def test_a_lone_bullet_needs_a_hang(self):
        flat = [_ln("• the only bullet, a wrapped separator", 60.0, 100.0),
                _ln("and its next line at the same x", 60.0, 112.6)]
        self.assertEqual(I._inline_list_starts([flat]), set())
        hung = [_ln("• the only bullet, with a hanging indent", 60.0, 100.0),
                _ln("continuation under the text", 66.0, 112.6)]
        self.assertEqual(len(I._inline_list_starts([hung])), 1)

    def test_a_numbered_heading_alone_is_not_a_list(self):
        # c6's "5. Section heading number 5" -- gated; nothing may move it
        one = [_ln("5. Section heading number 5", 72.0, 100.0, size=14.0)]
        self.assertEqual(I._inline_list_starts([one]), set())
        seq = [_ln("4. Fourth step of the procedure", 72.0, 100.0),
               _ln("5. Fifth step of the procedure", 72.0, 112.6)]
        self.assertEqual(len(I._inline_list_starts([seq])), 2)

    def test_numbers_out_of_sequence_are_not_a_list(self):
        lines = [_ln("10. In this section the figure shows", 72.0, 100.0),
                 _ln("3. something else entirely", 72.0, 112.6)]
        self.assertEqual(I._inline_list_starts([lines]), set())

    def test_dashes_need_a_second_dash(self):
        one = [_ln("– as expected – was not what happened", 72.0, 100.0)]
        self.assertEqual(I._inline_list_starts([one]), set())
        two = [_ln("– first dash item", 72.0, 100.0),
               _ln("– second dash item", 72.0, 112.6)]
        self.assertEqual(len(I._inline_list_starts([two])), 2)

    def test_monospace_is_code_not_a_list(self):
        code = [_ln("- key: alpha", 72.0, 100.0, mono=True, font="Courier"),
                _ln("- key: beta", 72.0, 110.0, mono=True, font="Courier")]
        self.assertEqual(I._inline_list_starts([code]), set())

    def test_rfc_items_in_separate_blocks_do_not_merge(self):
        # y17_rfc9110 p40 (design audit B16): one block per item, 2.7pt apart,
        # inside `_mergeable`'s 3.2pt join window.
        items = [_blk([_ln("• control data to describe and route the message,",
                           79.9, 394.9, size=10.0, x1=310.4)]),
                 _blk([_ln("• a headers lookup table of name/value pairs for "
                           "extending that control data", 79.9, 411.0, size=10.0,
                           x1=514.3),
                       _ln("additional information about the sender,", 85.9,
                           424.6, size=10.0, x1=422.2)]),
                 _blk([_ln("• a potentially unbounded stream of content, and",
                           79.9, 440.7, size=10.0, x1=314.8)])]
        flow = I._merge_flow_paras(I._to_flow(items, 65.9, 529.0), 529.0)
        paras = [e for e in flow if isinstance(e, Para)]
        self.assertEqual(len(paras), 3, [p.text for p in paras])
        self.assertTrue(paras[1].text.startswith("• a headers"))
        self.assertAlmostEqual(paras[1].first_indent, -6.0, delta=0.05)

    def test_single_line_siblings_take_the_measured_hang(self):
        lines = _x17_lines()
        paras = I.paras_from_line_list(lines, COL_L, COL_R,
                                       I._inline_list_starts([lines]))
        self.assertEqual(paras[1].first_indent, 0.0)   # nothing to measure
        I._propagate_list_hangs(paras)
        self.assertAlmostEqual(paras[1].first_indent, -11.5, delta=0.05)
        self.assertAlmostEqual(paras[1].left_indent, 12.5, delta=0.05)


class RuleBetweenLinesOfOneBlock(unittest.TestCase):
    """The owner's résumé: heading and summary are ONE PDFium block."""

    def _rule(self, y0, y1):
        r = RuleEl(width_pct=100.0, thickness=0.75, color="#000000",
                   length=510.8)
        r._bbox = (42.75, y0, 553.5, y1)
        return ("el", r._bbox, r)

    def test_the_rule_is_emitted_between_heading_and_text(self):
        blk = _blk([_ln("SUMMARY", 42.8, 110.6, size=9.49, bold=True, x1=107.3),
                    _ln("Backend software engineer with 3.5 years building",
                        42.8, 131.4, x1=553.5),
                    _ln("agents, model fine-tuning, and inference deployment",
                        42.8, 144.9, x1=553.5)])
        flow = I._to_flow([blk, self._rule(124.5, 125.25)], 43.26, 553.46)
        kinds = [type(e).__name__ for e in flow]
        self.assertEqual(kinds, ["Para", "RuleEl", "Para"], _texts(flow))
        self.assertEqual(flow[0].text, "SUMMARY")

    def test_a_rule_inside_a_line_box_does_not_cut(self):
        # y06_irs_1040's flowchart: a row border 0.5pt under a baseline
        blk = _blk([_ln("Can claim a nonrefundable credit (other than the",
                        93.9, 496.2, size=9.31, x1=358.4),
                    _ln("child tax credit or the credit for other dependents)",
                        93.9, 509.1, size=9.31, x1=364.8)])
        top_line = blk[2].lines[0]
        y = top_line.spans[0].origin[1] + 0.5
        flow = I._to_flow([blk, self._rule(y, y + 1.0)], 42.0, 570.0)
        paras = [e for e in flow if isinstance(e, Para)]
        self.assertEqual(len(paras), 1, _texts(flow))


def _row_lines(page=1):
    left = Line(spans=[_span("Software Engineer · Zackriya Solutions", 42.8, 61.3,
                             size=10.0, font="Georgia-Bold", bold=True, x1=243.2)],
                bbox=(42.8, 61.3, 243.2, 72.3))
    right = Line(spans=[_span("January 2022 – June 2025", 448.7, 62.6, size=8.6,
                              font="Georgia-Italic", italic=True, x1=553.6)],
                 bbox=(448.7, 62.6, 553.6, 72.1))
    # pin both halves to one baseline, as the parser reports them
    right.spans[0].origin = (448.7, left.spans[0].origin[1])
    desc = [_ln("Remote, India — Service company delivering MVPs, applied-AI "
                "systems, and data tools", 42.6, 77.3 + 11.0 * i, size=8.6,
                font="Georgia-Italic", italic=True, x1=547.7) for i in range(2)]
    return left, right, desc


class RowsUseDocumentEvidence(unittest.TestCase):
    """The owner's résumé page 2: one role/date row on the page."""

    def _items(self):
        left, right, desc = _row_lines()
        return left, right, [_blk([left]), _blk([right] + desc)]

    def test_a_single_row_alone_is_still_refused(self):
        _l, _r, items = self._items()
        pairs, _ = I._row_pairs(items, 43.26, 553.46)
        self.assertEqual(pairs, [])

    def test_a_single_row_is_kept_when_the_document_has_its_column(self):
        left, right, items = self._items()
        evidence = [(553.5, I._row_style(right), I._row_style(left)),
                    (553.6, I._row_style(right), I._row_style(left))]
        pairs, consumed = I._row_pairs(items, 43.26, 553.46, evidence)
        self.assertEqual(len(pairs), 1)
        para = I._row_para(pairs[0][0], pairs[0][1], 43.26, 553.46)
        self.assertEqual(para.text,
                         "Software Engineer · Zackriya Solutions\tJanuary 2022 – June 2025")

    def test_one_style_on_both_sides_is_a_broken_sentence(self):
        left, right, items = self._items()
        right.spans[0].font, right.spans[0].italic = "Georgia-Bold", False
        right.spans[0].bold, right.spans[0].size = True, 10.0
        evidence = [(553.5, I._row_style(right), I._row_style(left))] * 3
        pairs, _ = I._row_pairs(items, 43.26, 553.46, evidence)
        self.assertEqual(pairs, [])

    def test_the_label_keeps_its_inner_word_spaces(self):
        # y06_irs_1040: two runs split after "- " came out "Table -Continued"
        left = Line(spans=[_span("Earned Income Credit (EIC) Table - ", 36.0, 40.0,
                                 font="Helvetica-Bold", bold=True, x1=230.0),
                           _span("Continued", 230.0, 40.0, font="Helvetica",
                                 x1=280.0)], bbox=(36.0, 40.0, 280.0, 50.7))
        right = _ln("(Caution. This is not a tax table.)", 450.0, 40.0,
                    font="Helvetica-Oblique", italic=True, x1=570.0)
        para = I._row_para(left, right, 36.0, 570.0)
        self.assertTrue(para.text.startswith("Earned Income Credit (EIC) Table - Continued\t"),
                        para.text)


def _hline(x0, x1, y):
    return DrawCmd(kind="stroke", shape="hline", bbox=(x0, y, x1, y + 0.75),
                   fill=None, stroke="#444444", width=0.75, opacity=1.0,
                   n_items=1)


class ContentEdgeFromFields(unittest.TestCase):
    """x17: rules end at 552.75, dates at 552.3, ragged prose p90 at 529.9."""

    def _ir(self, x1=552.75):
        p = PageIR(number=1, width=595.0, height=842.0, blocks=[],
                   drawings=[_hline(43.5, x1, 90.0 + 50 * i) for i in range(5)])
        return DocIR(path="x.pdf", pages=[p])

    def _hf(self):
        return {"consumed_text": {1: set()}, "consumed_draw": {1: set()}}

    WIDE = [512.7, 529.9, 541.3, 530.7, 517.8, 518.0, 520.0, 525.0, 528.0, 529.0]

    def test_prose_alone_cannot_vouch_for_the_rule_edge(self):
        self.assertIsNone(I._rule_right_edge(self._ir(), self._hf(), 595.0, self.WIDE))

    def test_two_dates_at_the_rule_edge_can(self):
        edge = I._rule_right_edge(self._ir(), self._hf(), 595.0, self.WIDE,
                                  row_x1=[552.3, 552.3])
        self.assertAlmostEqual(edge, 552.75, delta=0.5)

    def test_one_date_is_not_a_column(self):
        self.assertIsNone(I._rule_right_edge(self._ir(), self._hf(), 595.0,
                                             self.WIDE, row_x1=[552.3]))

    def test_field_rows_need_a_style_contrast(self):
        left, right, _ = _row_lines()
        self.assertEqual(I._field_row_ends([[left, right]], 43.26, 595.0), [553.6])
        same = _ln("of the tax year, unless the", 480.0, 61.3, size=10.0,
                   font="Georgia-Bold", bold=True, x1=553.6)
        same.spans[0].origin = (480.0, left.spans[0].origin[1])
        self.assertEqual(I._field_row_ends([[left, same]], 43.26, 595.0), [])


def _para(text, bold=True, size=9.49, align="left", li=0.0, top=110.6,
          tracked=False):
    p = Para(runs=[Run(text=text, font="Georgia-Bold" if bold else "Georgia",
                       size=size, color="#111111", bold=bold)],
             align=align, left_indent=li, bbox=(42.8 + li, top, 200.0, top + 10.7))
    p.src_lines = 1
    p._tracked = tracked
    return p


def _rule_el(y):
    r = RuleEl(width_pct=100.0, thickness=0.75, color="#000000", length=510.0)
    r._bbox = (42.75, y, 553.5, y + 0.75)
    return r


def _layout(elements):
    lay = DocLayout()
    pg = PageLayout(number=1)
    pg.chunks = [Chunk(n_cols=1, elements=elements)]
    lay.pages = [pg]
    return lay


class BodySizeSectionHeadings(unittest.TestCase):
    BODY = 9.7

    def _mark(self, *els):
        lay = _layout(list(els))
        I._mark_headings(lay, self.BODY)
        return [e.heading for e in els if isinstance(e, Para)]

    def test_caps_heading_over_its_rule_is_heading_1(self):
        body = _para("Backend software engineer with 3.5 years", bold=False,
                     size=9.7, top=131.4)
        self.assertEqual(self._mark(_para("SUMMARY"), _rule_el(124.5), body), [1, 0])

    def test_tracking_alone_is_enough(self):
        self.assertEqual(self._mark(_para("EDUCATION", tracked=True)), [1])

    def test_bold_caps_without_a_section_device_is_a_label(self):
        self.assertEqual(self._mark(_para("WARNING")), [0])

    def test_labels_and_running_heads_are_not_sections(self):
        self.assertEqual(self._mark(_para("AND", li=115.9), _rule_el(122.0)), [0])
        self.assertEqual(self._mark(_para("CATEGORY: COMPUTER SECURITY"),
                                    _rule_el(124.5)), [0])
        self.assertEqual(self._mark(_para("CONTENTS", align="right"),
                                    _rule_el(124.5)), [0])
        self.assertEqual(self._mark(_para("SUMMARY", bold=False), _rule_el(124.5)), [0])

    def test_they_sit_below_size_ranked_headings(self):
        title = _para("A Real Title In Large Type", size=16.0, top=40.0)
        self.assertEqual(self._mark(title, _para("SUMMARY"), _rule_el(124.5)), [1, 2])


class LadderGivesTheHangItsRoom(unittest.TestCase):
    """x17's first bullet: 506.5pt of line against 496.8pt of avail, but the
    first line starts 11.5pt out in the hang, so it has 508.3pt of room."""

    TEXT = ("• Rebuilt the ingestion path so that a replayed shipment event is "
            "idempotent, which removed the nightly reconciliation job entirely.")

    def _para(self, typed):
        p = Para(runs=[Run(text=self.TEXT, font="Times-Roman", size=9.7,
                           color="#111111")], left_indent=12.5, first_indent=-11.5)
        p._list_item = typed
        return p

    def _avail(self, metrics):
        w = metrics.text_width(self.TEXT, "Times New Roman", 9.7)
        if w is None:
            self.skipTest("text metrics unavailable")
        return w - 6.0          # short of the line, inside line + hang

    def test_a_typed_item_first_line_gets_the_hang(self):
        metrics = get_metrics()
        avail = self._avail(metrics)
        self.assertEqual(ladder.predict_lines(self._para(True), avail, metrics), 1)

    def test_other_hanging_paragraphs_are_predicted_as_before(self):
        metrics = get_metrics()
        avail = self._avail(metrics)
        self.assertEqual(ladder.predict_lines(self._para(False), avail, metrics), 2)

    def test_a_tabbed_marker_is_predicted_as_before(self):
        metrics = get_metrics()
        avail = self._avail(metrics)
        p = self._para(True)
        p.runs = [Run(text="•", font="Times-Roman", size=9.7, color="#111111"),
                  Run(text="\t", font="Times-Roman", size=9.7, color="#111111",
                      is_tab=True),
                  Run(text=self.TEXT[2:], font="Times-Roman", size=9.7,
                      color="#111111")]
        self.assertEqual(ladder.predict_lines(p, avail - 3.0, metrics), 2)


def _synthetic_resume(path, pages=2):
    """Two pages: rows on page 1, ONE row on page 2; tracked caps over rules."""
    W, H = 595.0, 842.0
    L, R = 43.5, 552.75
    c = _canvas.Canvas(path, pagesize=(W, H))

    def heading(text, top):
        c.saveState()               # Tc is graphics state: keep it off the body
        t = c.beginText(L, H - top)
        t.setFont("Helvetica-Bold", 9.5)
        t.setCharSpace(1.5)
        t.textOut(text)
        c.drawText(t)
        c.restoreState()
        c.setLineWidth(0.75)
        c.line(L, H - top - 4.5, R, H - top - 4.5)

    def row(left, right, top):
        c.setFont("Times-Bold", 9.5)
        c.drawString(L, H - top, left)
        c.setFont("Times-Italic", 8.5)
        c.drawRightString(R - 0.5, H - top, right)

    def body(lines, top):
        c.setFont("Times-Roman", 9.5)
        for i, ln in enumerate(lines):
            c.drawString(L, H - top - 12.6 * i, ln)

    if pages == 2:
        heading("EXPERIENCE", 52)
        row("Senior Backend Engineer - Northwind Logistics Platform", "2021 - 2024", 70)
        body(["Rebuilt the ingestion path so that a replayed shipment event is idempotent."], 84)
        row("Backend Engineer, Distributed Systems - Meridian Data", "2019 - 2021", 110)
        body(["Owned the message bus consumers through a broker upgrade."], 124)
        c.showPage()
    heading("EXPERIENCE, CONTINUED", 52)
    row("Software Engineer - Cobalt Analytics", "2017 - 2019", 70)
    c.setFont("Times-Italic", 8.5)
    c.drawString(L, H - 82, "Remote team; consulting work for logistics and billing clients")
    c.drawString(L, H - 93, "from the first prototype to the production rollout.")
    c.showPage()
    c.save()
    return path


@unittest.skipIf(_canvas is None, "reportlab is not installed")
class SyntheticResumeEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from exactdoc.dialect import normalize
        from exactdoc.parse_pdfium import parse_pdf
        cls._dir = tempfile.TemporaryDirectory()
        cls.lay2 = I.infer(normalize(parse_pdf(
            _synthetic_resume(os.path.join(cls._dir.name, "r2.pdf"), 2),
            keep_image_data=False)))
        cls.lay1 = I.infer(normalize(parse_pdf(
            _synthetic_resume(os.path.join(cls._dir.name, "r1.pdf"), 1),
            keep_image_data=False)))

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    @staticmethod
    def _paras(lay, page):
        return [e for ch in lay.pages[page - 1].chunks for e in ch.elements
                if isinstance(e, Para)]

    def test_the_lone_row_on_page_two_is_a_tab_row(self):
        row = [p for p in self._paras(self.lay2, 2) if "Cobalt" in p.text]
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0].text, "Software Engineer - Cobalt Analytics\t2017 - 2019")
        self.assertEqual(row[0].tab_stops[0][1], "right")

    def test_without_the_document_column_it_is_not(self):
        texts = [p.text for p in self._paras(self.lay1, 1)]
        self.assertFalse(any("\t" in t for t in texts), texts)

    def test_tracked_caps_over_a_rule_are_section_headings(self):
        heads = {p.text: p.heading for p in self._paras(self.lay2, 1) + self._paras(self.lay2, 2)
                 if p.heading}
        self.assertEqual(heads, {"EXPERIENCE": 1, "EXPERIENCE, CONTINUED": 1})


if __name__ == "__main__":
    unittest.main()
