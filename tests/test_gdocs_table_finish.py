"""The last four ports that took the live report to CLEAN 1:1.

- `_split_span_at_boundaries`: a single span the parser joined across cells
  ("base L0", 40pt over a 28.5pt drawn column) is split at the boundary by
  advance arithmetic -- mono exactly, proportional evenly -- and only ever
  at a space within three characters of the computed boundary.
- `_gdocs_min_col_widths`: the Docs importer drops the boundary of a
  sub-minimum column; lift it, funded proportionally above the minimum so
  no column loses enough to re-wrap (a word-plus-space, ~6pt).
- the single-line pitch bias: one-line paragraphs pitch ~0.38pt/line looser
  in Docs (47-line list block, +18pt on one page); their `leading` is the
  size*1.16 heuristic, so shaving it corrects an estimate.
- pageBreakBefore instead of a carrier paragraph (gdocs): a carrier spills
  and double-fires exactly when its page fills exactly; a break-before is
  a no-op at a page top. Proven live: the double-fire blank disappeared
  and the aligner returned CLEAN 1:1.
"""
import unittest

from exactdoc.docxout import _gdocs_min_col_widths
from exactdoc.infer import _split_span_at_boundaries
from exactdoc.model import Span


def _span(text, x0, x1, mono=True, font="Consolas", size=8.5):
    return Span(text=text, font=font, size=size, color="#000000",
                bold=False, italic=italic_for(mono), mono=mono, serif=not mono,
                superscript=False, bbox=(x0, 100.0, x1, 108.5),
                origin=(x0, 108.5))


def italic_for(mono):
    return False


COLS = [57.4, 70.9, 167.6, 292.9, 538.9]


class SplitSpanAtBoundaries(unittest.TestCase):
    def test_mono_header_splits_at_the_space(self):
        # 'base L0': 'base' ends inside column 0, 'L0' belongs to column 1;
        # the boundary at 70.9 falls just past the joining space
        s = _span("base L0", 61.0, 101.0)     # crosses 70.9
        pieces = _split_span_at_boundaries(s, COLS)
        self.assertEqual([p.text for p in pieces], ["base ", "L0"])
        self.assertAlmostEqual(pieces[0].bbox[2], 61.0 + 5 * 4.675, delta=0.5)

    def test_proportional_span_splits_at_nearest_space(self):
        # 'runs verdict bearing' in Georgia bold crossing the 167.6 edge
        s = _span("runs verdict bearing", 130.0, 265.0, mono=False,
                  font="Georgia-Bold", size=8.5)
        pieces = _split_span_at_boundaries(s, COLS)
        self.assertEqual(len(pieces), 2)
        self.assertEqual(pieces[0].text, "runs ")
        self.assertEqual(pieces[1].text, "verdict bearing")

    def test_no_space_near_boundary_refuses_to_cut(self):
        s = _span("20/40-thing", 61.0, 120.0)   # crosses 70.9, no space
        pieces = _split_span_at_boundaries(s, COLS)
        self.assertEqual(len(pieces), 1)
        self.assertIs(pieces[0], s)

    def test_span_inside_one_band_returned_as_is(self):
        s = _span("L1", 175.0, 185.0)
        pieces = _split_span_at_boundaries(s, COLS)
        self.assertEqual(len(pieces), 1)
        self.assertIs(pieces[0], s)


class GdocsMinColWidths(unittest.TestCase):
    def test_subminimum_column_lifted(self):
        ws = _gdocs_min_col_widths([141.8, 14.0, 111.0, 30.0, 156.8], 22.0)
        self.assertEqual(ws[1], 22.0)
        self.assertGreaterEqual(min(ws), 22.0)

    def test_total_width_preserved(self):
        src = [141.8, 14.0, 111.0, 30.0, 156.8]
        ws = _gdocs_min_col_widths(src, 22.0)
        self.assertAlmostEqual(sum(ws), sum(src), delta=0.05)

    def test_funding_stays_below_a_wrap_threshold(self):
        # the widest column must not lose enough to re-wrap: funding an
        # 8.4pt deficit proportionally took at most 3.07pt from any one
        # column on the live-verified case, under half a word-plus-space
        src = [141.8, 14.0, 111.0, 30.0, 156.8]
        ws = _gdocs_min_col_widths(src, 22.0)
        losses = [s - w for s, w in zip(src, ws) if w < s]
        self.assertTrue(all(0 <= l <= 3.2 for l in losses), losses)

    def test_healthy_table_untouched(self):
        src = [141.8, 28.5, 111.0, 30.8, 79.5]
        self.assertEqual(_gdocs_min_col_widths(src, 22.0), src)


if __name__ == "__main__":
    unittest.main()
