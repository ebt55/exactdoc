"""Rule-evidence right-edge widening (defect catalogue #3).

A ragged-right document keeps its flush edge below the wide-line
estimator's 8% membership floor, so the text cluster lands inside the text
it bounds and every paragraph re-wraps. On the real 32-page report that
motivated this, the document's own 32 full-width rules all ended at the
true column edge (539.25 on a 595pt page, text cluster 519.7) and the
~19.5pt of lost width nearly doubled the page count in Google Docs.

The reverse case is measured too: 01_whitepaper_market's six rules
overshoot its correctly-measured column (552.0) by 6pt, decoratively, and
widening on their say-so moved a gated margin. The p90 agreement guard
separates the two populations (3.75pt undershoot vs 6pt overshoot).
"""
import unittest

from exactdoc.infer import _rule_right_edge
from exactdoc.model import DocIR, DrawCmd, PageIR


def _hline(x0, x1, y, w=0.75):
    return DrawCmd(kind="stroke", shape="hline", bbox=(x0, y, x1, y + w),
                   fill=None, stroke="#bbbbbb", width=w, opacity=1.0,
                   n_items=1)


def _ir_with_rules(rules, page_w=595.0):
    p = PageIR(number=1, width=page_w, height=842.0, blocks=[], drawings=rules,
               images=[])
    return DocIR(path="x.pdf", pages=[p])


def _hf():
    return {"consumed_text": {1: set()}, "consumed_draw": {1: set()},
            "rep_lines": {}, "rep_draws": {}, "line_roles": {},
            "band_first": []}


PAGE_W = 595.0


class RuleRightEdge(unittest.TestCase):
    def test_unanimous_rules_widen_to_the_column_edge(self):
        # B13's shape: 32 rules at 539.25, the ragged top decile at 535.5
        rules = [_hline(57.0, 539.25, 60.0 + 25 * i) for i in range(8)]
        wide_x1 = [539.25] + [440.0 + 9.0 * i for i in range(20)]  # p90 ~531
        edge = _rule_right_edge(_ir_with_rules(rules), _hf(), PAGE_W, wide_x1)
        self.assertIsNotNone(edge)
        self.assertAlmostEqual(edge, 539.25, delta=1.0)

    def test_decorative_overshoot_is_rejected(self):
        # 01's shape: rules 6pt past a column the text measures exactly
        rules = [_hline(60.0, 558.0, 60.0 + 25 * i) for i in range(6)]
        wide_x1 = [552.0] * 30
        self.assertIsNone(
            _rule_right_edge(_ir_with_rules(rules, page_w=612.0), _hf(),
                             612.0, wide_x1))

    def test_bleeding_rule_is_furniture(self):
        # a rule running to the paper edge is page furniture, not a column
        rules = [_hline(0.0, 594.0, 60.0 + 25 * i) for i in range(6)]
        wide_x1 = [539.0] * 30
        self.assertIsNone(_rule_right_edge(_ir_with_rules(rules), _hf(),
                                           PAGE_W, wide_x1))

    def test_one_stray_rule_is_not_evidence(self):
        rules = [_hline(57.0, 539.25, 60.0)]  # single rule: below the
        wide_x1 = [500.0] * 30                # max(3, 8%) mass floor
        self.assertIsNone(_rule_right_edge(_ir_with_rules(rules), _hf(),
                                           PAGE_W, wide_x1))

    def test_no_rules_no_opinion(self):
        self.assertIsNone(_rule_right_edge(_ir_with_rules([]), _hf(),
                                           PAGE_W, [539.0] * 10))


if __name__ == "__main__":
    unittest.main()
