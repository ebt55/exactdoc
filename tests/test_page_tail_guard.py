"""One overflow must not cost a whole page (WP18).

Every source page ends in a hard page break, so an element that runs even a
point past the bottom of the box goes over alone and the break then costs a
whole page. Two findings, each pinned here on synthetic input:

1. A rule repeated at one place on most pages, with a running line beyond it
   and nothing of the body between them, is that line's furniture whatever the
   gap (`infer._repeated_running_rules`). y17_rfc9110's foot rule, 9.2pt over
   its foot on all 194 pages, stayed in the body as a 2pt paragraph behind a
   66pt gap; Google Docs set 77 pages that carried nothing but it.
2. The element that closes a page and is there only for where it sits -- a
   rule, an empty paragraph, a line placed by a gap of three body lines or
   more -- keeps one body line of clearance from the bottom of the box, paid
   from its own gap (`docxout._guard_page_tail`). y31's cover date went over
   in Google Docs on both cover pages.
"""
import os
import re
import tempfile
import unittest
import zipfile

from exactdoc import infer as I
from exactdoc.docxout import (SPILL_EDGE_SLACK_PT, SPILL_GAP_FLOOR_PT,
                              SPILL_MIN_GAP_SCALE, TAIL_PLACEMENT_LINES,
                              _body_capacity, _body_line_pt, _guard_page_tail,
                              _stack_used, write_docx)
from exactdoc.layout import (Chunk, DocLayout, HFPart, PageLayout, Para,
                             RuleEl, Run)
from exactdoc.model import DocIR, DrawCmd, Line, PageIR, Span, TextBlock


# ---------------------------------------------------------------- furniture
def _line(text, x0, y0, x1, size=10.0):
    s = Span(text, "Helvetica", size, "#000000", False, False, False, False,
             False, (x0, y0, x1, y0 + 1.2 * size), (x0, y0 + 0.8 * size))
    return Line([s], s.bbox)


def _block(lines):
    bb = (min(l.bbox[0] for l in lines), min(l.bbox[1] for l in lines),
          max(l.bbox[2] for l in lines), max(l.bbox[3] for l in lines))
    return TextBlock(list(lines), bb)


def _hline(x0, y0, x1, y1):
    return DrawCmd(kind="fill", shape="hline", bbox=(x0, y0, x1, y1),
                   fill="#cccccc", stroke=None, width=0.0, opacity=1.0,
                   n_items=1)


_WORDS = ["Resources", "Representations", "Connections", "Messages",
          "Intermediaries", "Caches", "Specifications", "Extensibility",
          "Semantics", "Identifiers", "Fields", "Methods"]

H = 841.0          # y17 is A4-ish: 595 x 841
FOOT_Y = 723.5     # y17's foot, 117pt up: outside BOTZ, inside the extended band


def _rfc_page(n, gap=9.2, rule=True, body_between=False, foot_y=FOOT_Y):
    """A page of RFC 9110's shape: body text, and a foot carrying the page's
    number set `gap` under a grey rule, x 56.2-539.0."""
    body = [_line("Section on %s, page %d" % (_WORDS[n % len(_WORDS)], n),
                  66.0, 300.0, 500.0)]
    if body_between:
        body.append(_line("a body line under the rule on " + _WORDS[n % 12],
                          66.0, foot_y - gap + 0.5, 300.0, size=4.0))
    foot = [_line("Fielding, et al.", 56.2, foot_y, 115.5, size=9.0),
            _line("Standards Track", 262.8, foot_y, 332.5, size=9.0),
            _line("Page %d" % n, 506.8, foot_y, 538.8, size=9.0)]
    draws = [_hline(56.2, foot_y - gap - 0.7, 539.0, foot_y - gap)] if rule else []
    return PageIR(number=n, width=595.0, height=H,
                  blocks=[_block(body), _block(foot)], drawings=draws)


def _detect(pages):
    return I.detect_hf(DocIR(path="x.pdf", pages=pages))


class RepeatedRunningRules(unittest.TestCase):
    N = 12

    def test_a_repeated_rule_over_the_foot_goes_with_it(self):
        # 9.2pt is past RUNNING_RULE_GAP_PT (a single page's evidence);
        # repetition on every page is what admits it.
        self.assertGreater(9.2, I.RUNNING_RULE_GAP_PT)
        res = _detect([_rfc_page(n) for n in range(1, self.N + 1)])
        for pn in range(2, self.N + 1):
            self.assertEqual(res["consumed_draw"][pn], {0}, pn)
            self.assertIn(("bot", 0), [(z, di) for z, di, _ in
                                       res["rep_draws"][pn]], pn)

    def test_a_rule_on_too_few_pages_stays_in_the_body(self):
        pages = [_rfc_page(n, rule=n <= 4) for n in range(1, self.N + 1)]
        res = _detect(pages)
        self.assertFalse(any(res["consumed_draw"].values()))

    def test_body_text_between_rule_and_foot_keeps_the_rule(self):
        pages = [_rfc_page(n, body_between=True) for n in range(1, self.N + 1)]
        res = _detect(pages)
        self.assertFalse(any(res["consumed_draw"].values()))

    def test_a_rule_beyond_the_parts_reach_stays(self):
        # build_hf_part draws a rule as a row's border only this close
        gap = I.HF_RULE_REACH_PT + 4.0
        res = _detect([_rfc_page(n, gap=gap) for n in range(1, self.N + 1)])
        self.assertFalse(any(res["consumed_draw"].values()))

    def test_a_foot_inside_the_legacy_zone_is_left_as_it_was(self):
        # y28's shape: the foot inside BOTZ, its rule 3.5pt above and outside
        # it -- the rule there is the body's room as much as the foot's, and
        # LibreOffice lost a page when the part took it.
        foot_y = H - I.BOTZ + 1.0
        res = _detect([_rfc_page(n, gap=3.5, foot_y=foot_y)
                       for n in range(1, self.N + 1)])
        self.assertLess(foot_y - 3.5 - 0.7, H - I.BOTZ)
        self.assertFalse(any(res["consumed_draw"].values()))

    def test_the_part_draws_it_as_the_foot_rows_top_border(self):
        pages = [_rfc_page(n) for n in range(1, self.N + 1)]
        res = _detect(pages)
        pg = pages[5]
        items = [(z, bi, l) for z, bi, l in res["rep_lines"][pg.number]
                 if z == "bot"]
        draws = [(z, di, d) for z, di, d in res["rep_draws"][pg.number]
                 if z == "bot"]
        part = I.build_hf_part(items, draws, pg, 56.2, 56.0,
                               res["line_roles"])
        self.assertIsNotNone(part)
        border = part.elements[0].border_top
        self.assertIsNotNone(border)
        # measured from the rule's middle: 723.5 - (713.6 + 714.3) / 2
        self.assertAlmostEqual(border[2], 9.6, delta=0.06)


# ---------------------------------------------------------------- the writer
LEAD = 12.0


def _lay(**kw):
    d = dict(page_w=612.0, page_h=792.0, margin_l=72.0, margin_r=72.0,
             margin_t=72.0, margin_b=72.0)
    d.update(kw)
    return DocLayout(**d)


def _para(text="alpha beta gamma", gap=0.0, lead=LEAD):
    # Georgia has no base-14 metrics: `_page_spill` cannot predict it, so the
    # guard reads the source's line budget alone and the arithmetic is exact.
    p = Para(runs=[Run(text=text, font="Georgia", size=10.0,
                       color="#000000")] if text else [],
             leading=lead, space_before=gap, src_lines=1)
    return p


def _rule(gap):
    return RuleEl(width_pct=100.0, thickness=0.75, color="#cccccc",
                  space_before=gap)


def _page(lay, tail, clearance, n=20, gap=8.0):
    """A one-column page of `n` one-line paragraphs, closed by `tail`, whose
    gap is set so the page's stack ends `clearance` inside the box."""
    head = [_para(gap=gap) for _ in range(n)]
    used = n * (gap + LEAD)
    tail_h = 2.0 if isinstance(tail, RuleEl) else LEAD
    tail.space_before = round(_body_capacity(lay) - clearance - used - tail_h, 1)
    pg = PageLayout(number=1, chunks=[Chunk(n_cols=1, elements=head + [tail])])
    return pg


def _guard(pg, lay, plan=None):
    return _guard_page_tail(pg, 468.0, lay, 0.0, "standard", plan or {}, LEAD)


class TheTailGuard(unittest.TestCase):
    def test_a_rule_closing_the_page_keeps_a_body_line_clear(self):
        lay = _lay()
        tail = _rule(0.0)
        pg = _page(lay, tail, clearance=3.0)
        plan = _guard(pg, lay)
        self.assertEqual(list(plan), [id(tail)])
        self.assertAlmostEqual(tail.space_before - plan[id(tail)], LEAD - 3.0,
                               delta=0.11)
        self.assertAlmostEqual(_body_capacity(lay) - _stack_used(pg, 0.0, plan),
                               LEAD, delta=0.11)

    def test_a_line_placed_by_its_gap_moves_up_by_what_it_needs(self):
        lay = _lay()
        tail = _para("July 2025")
        pg = _page(lay, tail, clearance=-2.0, n=10)    # 2pt over: the edge bias
        self.assertGreaterEqual(tail.space_before, TAIL_PLACEMENT_LINES * LEAD)
        plan = _guard(pg, lay)
        self.assertAlmostEqual(tail.space_before - plan[id(tail)], LEAD + 2.0,
                               delta=0.11)

    def test_an_ordinary_paragraph_gap_is_left_alone(self):
        lay = _lay()
        tail = _para("the last line of the page")
        # 31 paragraphs at a 20pt pitch leave the last one a 7pt gap
        pg = _page(lay, tail, clearance=3.0, n=31)
        self.assertLess(tail.space_before, TAIL_PLACEMENT_LINES * LEAD)
        self.assertEqual(_guard(pg, lay), {})

    def test_a_tail_with_a_line_of_room_is_left_alone(self):
        lay = _lay()
        tail = _rule(0.0)
        pg = _page(lay, tail, clearance=LEAD + 1.0)
        self.assertEqual(_guard(pg, lay), {})

    def test_a_page_past_its_box_by_its_own_account_is_left_alone(self):
        # a stack that runs past the box by more than the edge bias: a spill
        # the guard does not plan, or a stack that is not the page
        lay = _lay()
        tail = _para("ISBN 978-0-00-000000-0")
        pg = _page(lay, tail, clearance=-(SPILL_EDGE_SLACK_PT + 4.0), n=5)
        self.assertEqual(_guard(pg, lay), {})

    def test_the_gap_keeps_its_floor(self):
        lay = _lay()
        tail = _rule(0.0)
        pg = _page(lay, tail, clearance=0.0, n=31, gap=8.0)
        gap = tail.space_before
        plan = _guard(pg, lay)
        floor = max(SPILL_GAP_FLOOR_PT, gap * SPILL_MIN_GAP_SCALE)
        self.assertGreaterEqual(plan[id(tail)], round(floor, 1) - 0.05)

    def test_an_existing_plan_is_kept_and_counted(self):
        lay = _lay()
        tail = _rule(0.0)
        pg = _page(lay, tail, clearance=LEAD + 1.0)
        other = pg.chunks[0].elements[3]
        # a spill plan that took 5pt from another gap leaves more room still
        plan = _guard(pg, lay, {id(other): other.space_before - 5.0})
        self.assertEqual(list(plan), [id(other)])

    def test_a_framed_or_tabular_close_is_not_the_guards(self):
        lay = _lay()
        tail = _rule(0.0)
        pg = _page(lay, tail, clearance=1.0)
        tail.frame = (72.0, 700.0, 468.0)
        self.assertEqual(_guard(pg, lay), {})

    def test_the_body_line_is_the_line_weighted_median(self):
        lay = _lay()
        big = _para(lead=30.0)
        big.src_lines = 1
        body = _para(lead=13.6)
        body.src_lines = 40
        head = _para(lead=20.0)
        head.heading = 2
        head.src_lines = 50
        lay.pages = [PageLayout(number=1, chunks=[Chunk(elements=[
            big, body, head, _rule(4.0)])])]
        self.assertAlmostEqual(_body_line_pt(lay), 13.6)
        self.assertEqual(_body_line_pt(_lay()), 0.0)


class TheWriter(unittest.TestCase):
    @staticmethod
    def _befores(lay):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "o.docx")
            write_docx(lay, path)
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8")
        return [int(v) for v in re.findall(r'w:before="(\d+)"', xml)]

    def _doc(self):
        lay = _lay()
        tail = _rule(0.0)
        pg = _page(lay, tail, clearance=3.0)
        nxt = PageLayout(number=2, chunks=[Chunk(elements=[_para("next page")])])
        lay.pages = [pg, nxt]
        return lay, tail

    def test_the_rule_is_written_with_its_reduced_gap(self):
        lay, tail = self._doc()
        asked = tail.space_before
        befores = self._befores(lay)
        want = round((asked - (LEAD - 3.0)) * 20)
        self.assertIn(want, befores)
        self.assertNotIn(round(asked * 20), befores)

    def test_the_layout_is_not_modified(self):
        lay, tail = self._doc()
        asked = tail.space_before
        self._befores(lay)
        self.assertEqual(tail.space_before, asked)

    def test_a_footer_rows_border_is_room_the_body_does_not_have(self):
        # A foot rule taken into the footer is the row's top border; the
        # border and its space are part of the footer's height.
        lay = _lay(margin_b=20.0)
        foot = _para("Standards Track")
        lay.footer_default = HFPart(elements=[foot], distance=105.0)
        plain = _body_capacity(lay)
        foot.border_top = (0.75, "#cccccc", 9.2)
        self.assertAlmostEqual(plain - _body_capacity(lay), 9.95, delta=0.01)


if __name__ == "__main__":
    unittest.main()
