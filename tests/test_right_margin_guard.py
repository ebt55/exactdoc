"""A right-margin estimate far inside its own evidence is not a measurement.

`_margin_cluster` takes the rightmost cluster of wide-line right edges carrying
8% of the mass. On a ragged-right document the flush edge sits a little inside
the widest lines, which is correct. But when the flush edge itself is thinner
than 8% -- what a densely fragmented parse does to a multi-column page, by
turning long lines into many short ones -- the rightmost cluster that still
qualifies can be an interior band, and the estimate lands far inside the text
it is meant to bound.

y06_irs_1040_instructions under PDFium is the extreme: the estimator answers
385.8 against a p90 line end of 570.0, so `margin_r` comes out 226.2 on a 612pt
page and the content width is 343.8 instead of 528.0. Every paragraph in the
document re-wraps, 2,096 of them end up with no room at all, and 126 source
pages render as 599. The same document under PyMuPDF sees the same geometry,
gets None from the estimator, takes the mirror-the-left-margin fallback and
lands on the correct 42.0 -- so the reference arm was failing safe by accident.

The guard makes that deliberate on both arms. Erring wide costs a little
under-wrapping; erring narrow re-flows the document.
"""
import unittest

from exactdoc.infer import (MARGIN_MISCLUSTER_PT, _margin_cluster,
                            _right_edge_misclustered)

# (p90 of the wide-line right edges) minus (the estimate), measured over the
# expansion corpus at fc4adf2, both arms. See MARGIN_MISCLUSTER_PT.
CORRECT = {
    "y03_fips197 [pdfium]": (535.4, 535.0),
    "y07_f1040_form [pymupdf]": (567.9, 568.0),
    "y13_pub501 [pymupdf]": (559.4, 546.2),
    "y11_sp80053r5 [pdfium]": (518.6, 500.2),
    "y01_sp80063b [pdfium]": (539.3, 519.2),
    "y09_sp800207 [pdfium]": (539.2, 518.5),
    "y17_rfc9110 [pymupdf]": (525.7, 503.6),
    "y08_sp80088r1 [pdfium]": (539.6, 516.9),      # worst correct case, 22.7pt
    "gated 16, every document": (552.0, 552.0),    # cluster == p90 exactly
}
MISCLUSTERED = {
    "y07_f1040_form [pdfium]": (566.0, 470.2),     # 95.8pt inside
    "y06_1040_instructions [pdfium]": (570.0, 385.8),   # 184.2pt inside
}


def _edges(p90, n=200):
    """A wide-line population whose 90th percentile is exactly `p90`."""
    k = int(0.9 * (n - 1))          # the index the guard reads
    return [p90 - 40.0] * k + [p90] * (n - k)


class TheThreshold(unittest.TestCase):
    """It has to separate two measured populations, not just be a number."""

    def test_it_clears_every_correct_estimate_in_the_corpus(self):
        for name, (p90, mr) in CORRECT.items():
            self.assertLess(p90 - mr, MARGIN_MISCLUSTER_PT,
                            "%s is a correct estimate and must not trip" % name)

    def test_it_catches_every_mis_cluster_in_the_corpus(self):
        for name, (p90, mr) in MISCLUSTERED.items():
            self.assertGreater(p90 - mr, MARGIN_MISCLUSTER_PT,
                               "%s is a mis-cluster and must trip" % name)

    def test_it_keeps_real_margin_to_both_populations(self):
        worst_correct = max(p90 - mr for p90, mr in CORRECT.values())
        best_failure = min(p90 - mr for p90, mr in MISCLUSTERED.values())
        self.assertGreater(MARGIN_MISCLUSTER_PT - worst_correct, 25.0)
        self.assertGreater(best_failure - MARGIN_MISCLUSTER_PT, 25.0)


class TheGuard(unittest.TestCase):
    def test_y06_under_pdfium_trips(self):
        p90, mr = MISCLUSTERED["y06_1040_instructions [pdfium]"]
        self.assertTrue(_right_edge_misclustered(_edges(p90), mr))

    def test_y07_under_pdfium_trips(self):
        p90, mr = MISCLUSTERED["y07_f1040_form [pdfium]"]
        self.assertTrue(_right_edge_misclustered(_edges(p90), mr))

    def test_an_ordinary_ragged_right_edge_does_not_trip(self):
        # y08_sp80088r1, the worst correct case in the corpus at 22.7pt inside.
        p90, mr = CORRECT["y08_sp80088r1 [pdfium]"]
        self.assertFalse(_right_edge_misclustered(_edges(p90), mr))

    def test_a_flush_edge_does_not_trip(self):
        # Every gated document: the cluster IS the p90.
        self.assertFalse(_right_edge_misclustered(_edges(552.0), 552.0))

    def test_no_estimate_is_not_a_mis_cluster(self):
        # None already takes the fallback; the guard must not invent an opinion.
        self.assertFalse(_right_edge_misclustered(_edges(570.0), None))

    def test_no_evidence_is_not_a_mis_cluster(self):
        self.assertFalse(_right_edge_misclustered([], 385.8))

    def test_a_single_outlier_line_cannot_condemn_an_estimate(self):
        # y02's reference arm has a wide-line MAX of 613.2 on a 612pt page.
        # Judged against the max, its correct 524.3-ish edge would look 89pt
        # inside; judged against p90 it does not.
        edges = _edges(524.3) + [613.2]
        self.assertFalse(_right_edge_misclustered(edges, 524.3))


class AgainstTheEstimator(unittest.TestCase):
    """The guard must fire on what `_margin_cluster` actually returns, not on a
    hand-built number."""

    def test_a_tight_interior_band_beats_a_spread_flush_edge(self):
        # This is the y06 shape. `_cluster` chains -- a value joins on being
        # within tol of the PREVIOUS VALUE -- so a flush edge whose lines are
        # spread over tens of points collapses into one wide cluster, and the
        # 8%-within-2.5pt membership test then rejects it however many lines it
        # holds. A tight interior band of line ends passes the same test on far
        # fewer lines, and `max(good)` has nothing to its right to prefer.
        interior = [385.8 + (i % 3) * 0.4 for i in range(200)]
        flush = [540.0 + 0.5 * i for i in range(120)]      # 540..600, ragged
        vals = interior + flush
        mr = _margin_cluster(vals, left=False)
        self.assertIsNotNone(mr)
        self.assertLess(mr, 400.0, "the interior band won, as it does on y06")
        self.assertTrue(_right_edge_misclustered(vals, mr))

    def test_a_well_populated_flush_edge_is_kept(self):
        vals = [430.0 + (i % 5) for i in range(60)] + \
               [551.2 + (i % 3) * 0.3 for i in range(140)]
        mr = _margin_cluster(vals, left=False)
        self.assertIsNotNone(mr)
        self.assertGreater(mr, 545.0)
        self.assertFalse(_right_edge_misclustered(vals, mr))


if __name__ == "__main__":
    unittest.main()
