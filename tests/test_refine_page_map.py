"""The refinement loop's page map, on a document that repeats its paragraphs.

`_map_pages` decides which rendered page each source page begins on by letting
the page's first distinctive lines vote. x13_rl_report_running repeats every
paragraph of page 1 on page 2 -- and twice within page 1 -- so page 2's opening
lines voted for rendered page 1 once per occurrence there, out-voted rendered
page 2, and the loop read page 2 as a one-page SPILL of page 1. Every round
then halved page 2's gaps: -66pt by the foot of the page, dy_p90 64pt in the
product lane while the open-loop lane measured 5pt.
"""
import unittest

from exactdoc.refine import _map_pages


def _page(texts, y0=80.0):
    return [(t, y0 + 15.0 * i, 0.0) for i, t in enumerate(texts)]


HEADER = "transitauthorityoperationscommittee"
P1, P2 = "membersshouldnotethatthefigures", "mitigationisavailablebutunglamorous"


class RepeatedParagraphs(unittest.TestCase):
    def test_a_repeated_opening_maps_to_the_next_page(self):
        src = [_page([HEADER, "depotreplacementinterimreport", P1, P2, P1]),
               _page([HEADER, P1, P2, "ridershipbordered"])]
        out = [_page([HEADER, "depotreplacementinterimreport", P1, P2, P1]),
               _page([HEADER, P1, P2, "ridershipbordered"])]
        self.assertEqual(_map_pages(src, out), [0, 1])

    def test_distinct_pages_still_map_by_votes(self):
        src = [_page(["alphaalphaalpha1", "betabetabetabeta"]),
               _page(["gammagammagamma", "deltadeltadelta"])]
        # page 1's content spilled onto two rendered pages
        out = [_page(["alphaalphaalpha1"]), _page(["betabetabetabeta"]),
               _page(["gammagammagamma", "deltadeltadelta"])]
        self.assertEqual(_map_pages(src, out), [0, 2])


if __name__ == "__main__":
    unittest.main()
