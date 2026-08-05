"""A line pitch far below the text's own size is not a measurement.

`_body_pitch` and `_pitch_by_size` take the 20th percentile of the consecutive
baseline deltas, which is the right statistic within one column and the wrong
one across two. `_column_split` returns at most one gutter and under-detects --
on y06 it found one on 8 of 40 sampled pages of a document that is two- and
three-column throughout -- so the list reaching `_build_blocks_one` interleaves
the columns, half its deltas are the offset BETWEEN columns rather than a line
step, and the percentile lands in that near-zero population.

y06 page 20 is the worked case: reference 2.67pt for 10pt text whose true
in-column pitch is 11.50pt, so the gate `gap <= ref * 1.15` came out 3.08pt,
every genuine 11.50pt step was rejected, and 117 lines became 107 blocks.

The guard refuses the impossible answer rather than the specific cause, and can
only ever RAISE a reference -- which can only ever JOIN lines. It does not
detect columns; it makes a column-split failure survivable instead of fatal.

    python tests/test_pdfium_pitch_floor.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.model import Line, Span                        # noqa: E402
from exactdoc.parse_pdfium import (BLOCK_GAP_FACTOR,         # noqa: E402
                                   PITCH_DEFAULT_EM, PITCH_FLOOR_EM,
                                   _build_blocks, _pitch_reference)

# ref/size measured in place over the whole corpus at 0cf76ed -- 3,291
# (page, column-group, size) buckets, `_build_blocks_one` wrapped so the real
# `_column_split` above it still chose the groups. See PITCH_FLOOR_EM.
#
# The gated 16 are the only corpus that authorises anything, and on them the
# statistic is empty between 0.422 and 0.647.
GATED_COLLAPSED = {                    # (document, size, computed reference)
    "02_research_paper 9.0pt": (9.0, 0.230),      # 0.026em, the worst measured
    "01_whitepaper_market 10.5pt": (10.5, 1.500),  # 0.143em, true pitch 15.0
    "03_tech_report_code 10.5pt": (10.5, 1.500),
    "04_exec_brief 10.5pt": (10.5, 1.500),
    "05_memo 10.5pt": (10.5, 1.500),
    "02_research_paper 8.5pt": (8.5, 3.500),      # 0.412em, the highest
}
GATED_HEALTHY = {
    "04_exec_brief 8.5pt": (8.5, 5.500),          # 0.647em, the lowest healthy
    "04_exec_brief 7.5pt": (7.5, 5.500),          # 0.733em
    "c1_whitepaper 16.9pt": (16.9, 14.001),       # 0.828em
    "y06 page 5, single-column": (10.0, 11.36),   # 1.136em, the healthy mode
    "y06 page 62 group b": (10.0, 11.50),         # 1.150em, column-clean
}


class TheThreshold(unittest.TestCase):
    """It has to separate two measured populations, not just be a number."""

    def test_it_refuses_every_collapse_measured_on_the_gated_corpus(self):
        for name, (size, ref) in GATED_COLLAPSED.items():
            self.assertLess(ref / size, PITCH_FLOOR_EM,
                            "%s is a collapse and must be refused" % name)

    def test_it_keeps_every_healthy_reference_on_the_gated_corpus(self):
        for name, (size, ref) in GATED_HEALTHY.items():
            self.assertGreaterEqual(ref / size, PITCH_FLOOR_EM,
                                    "%s is a measurement and must be kept" % name)

    def test_it_keeps_real_margin_to_both_populations(self):
        worst_collapse = max(r / s for s, r in GATED_COLLAPSED.values())
        best_healthy = min(r / s for s, r in GATED_HEALTHY.values())
        self.assertGreater(PITCH_FLOOR_EM - worst_collapse, 0.05)
        self.assertGreater(best_healthy - PITCH_FLOOR_EM, 0.10)

    def test_the_floor_is_below_anything_a_typesetter_sets(self):
        # Solid setting is 1.0em and is already rare; the corpus's modal
        # leading is 1.10-1.20em. Half an em is not a leading.
        self.assertLess(PITCH_FLOOR_EM, 1.0)

    def test_the_default_admits_the_pitch_the_corpus_actually_sets(self):
        # y06's true in-column pitch is 11.50pt at size 10.0. The gate the
        # default produces has to accept that step, or the fallback fixes
        # nothing.
        self.assertGreaterEqual(PITCH_DEFAULT_EM * 10.0 * BLOCK_GAP_FACTOR,
                                11.50)

    def test_the_default_does_not_reach_a_paragraph_boundary(self):
        # A boundary is the pitch plus space-before: on y06, 1.15em of pitch
        # and never less than half a line again. Erring high fuses paragraphs,
        # which is the failure this must not introduce.
        self.assertLess(PITCH_DEFAULT_EM * BLOCK_GAP_FACTOR, 1.15 * 1.5)


class TheGuard(unittest.TestCase):
    def test_y06_page_20_is_refused(self):
        # The worked case: 2.67pt for 10pt text.
        self.assertGreater(_pitch_reference({10.0: 2.67}, 2.67, 10.0), 2.67)

    def test_a_healthy_bucket_is_returned_untouched(self):
        self.assertEqual(_pitch_reference({10.0: 11.5}, 11.5, 10.0), 11.5)

    def test_it_never_lowers_a_reference(self):
        # The whole safety argument: raising can only join lines, and joining
        # is what a correct measurement would have done.
        for size in (6.0, 8.0, 9.5, 10.0, 10.5, 12.0, 16.9, 24.0):
            for ref in (0.05, 0.5, 1.5, 3.0, 5.5, 11.5, 15.0, 40.0):
                got = _pitch_reference({round(size, 1): ref}, ref, size)
                self.assertGreaterEqual(got + 1e-9, ref,
                                        "size %s ref %s" % (size, ref))

    def test_a_collapsed_bucket_prefers_the_page_wide_measurement(self):
        # Real measurement before the constant: the page-wide sample is a
        # different one and often survives when a size bucket does not.
        got = _pitch_reference({10.0: 1.2}, 14.0, 10.0)
        self.assertEqual(got, 14.0)

    def test_the_constant_is_reached_only_when_both_have_collapsed(self):
        got = _pitch_reference({10.0: 1.2}, 2.67, 10.0)
        self.assertAlmostEqual(got, PITCH_DEFAULT_EM * 10.0)

    def test_a_missing_bucket_falls_through_to_the_page_and_is_guarded(self):
        # `by_size` omits a size with too few samples; the page-wide value it
        # falls back to can be collapsed too, and used not to be checked.
        self.assertAlmostEqual(_pitch_reference({}, 2.67, 10.0),
                               PITCH_DEFAULT_EM * 10.0)

    def test_a_sizeless_line_cannot_be_judged(self):
        # No size, no opinion -- the guard must not invent one.
        self.assertEqual(_pitch_reference({}, 2.67, 0.0), 2.67)


class TheFiringCondition(unittest.TestCase):
    """The constant is a guess, and a guess needs a reason (task #40).

    When this guard was written `_column_split` returned at most one gutter and
    usually none, so a collapsed reference on a page with no gutter was
    overwhelmingly an undetected column. The N-column split and the whitespace
    profile then made detection succeed, and the no-gutter population is no
    longer that.

    Measured over 4,132 firings: 72% of the y family's sit on pages where a
    gutter WAS found; 0% of 02_research_paper's do, and there the fallback was
    the bare constant every time because the page-wide value had collapsed too.
    Joining on that guess gave blocks that are geometrically right and a render
    that is worse -- within2pt 0.6675 -> 0.5685 at candidate, 0.5685 -> 0.0178
    at shipping.
    """

    def test_the_constant_is_not_reached_without_column_evidence(self):
        self.assertEqual(_pitch_reference({10.0: 1.2}, 2.67, 10.0,
                                          columnar=False), 1.2)

    def test_the_constant_is_reached_with_column_evidence(self):
        self.assertAlmostEqual(_pitch_reference({10.0: 1.2}, 2.67, 10.0,
                                                columnar=True),
                               PITCH_DEFAULT_EM * 10.0)

    def test_a_surviving_page_wide_measurement_is_taken_either_way(self):
        # A measurement is not a guess: it does not need the column evidence.
        for columnar in (True, False):
            self.assertEqual(
                _pitch_reference({10.0: 1.2}, 14.0, 10.0, columnar=columnar),
                14.0)

    def test_it_still_never_lowers_a_reference(self):
        for columnar in (True, False):
            for size in (8.0, 10.0, 12.0):
                for ref in (0.05, 1.5, 11.5, 40.0):
                    got = _pitch_reference({round(size, 1): ref}, ref, size,
                                           columnar=columnar)
                    self.assertGreaterEqual(got + 1e-9, ref)

    def test_a_polluted_page_with_no_columns_is_left_alone(self):
        # 02_research_paper's shape: the guard must not reflow it.
        lines, body = _polluted_page()
        blocks = _build_blocks(lines)
        held = max(sum(1 for l in b.lines if l in body) for b in blocks)
        self.assertEqual(held, 1,
                         "the constant fired on a page with no column evidence")


def _line(x0, x1, baseline, size=10.0, text="word"):
    bbox = (x0, baseline - size, x1, baseline + 2.0)
    span = Span(text=text, font="Helvetica", size=size, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=bbox, origin=(x0, baseline))
    return Line(spans=[span], bbox=bbox)


def _polluted_page(pitch=11.5, top=100.0):
    """A body column whose size bucket also holds sub-step deltas.

    This is the shape the guard repairs. Baselines INCREASE down the page --
    the parser's convention, which `_body_pitch`'s `0 < d` filter depends on.

    The first six lines are three tightly-stacked pairs 1.5pt apart: a
    fraction, a stacked unit, the second column of a row that sits a shade
    below the first. They are legitimate lines and they overlap the body
    horizontally, so nothing rejects them -- but their deltas join the same
    10pt bucket as the body's, and the 20th percentile then reads 1.5 rather
    than 11.5.

    Note what is NOT tested here: two columns that interleave without
    overlapping horizontally. Those are refused by the `overlap > 0` term
    before the pitch is ever consulted, so no pitch fix can reach them. That
    is the N-column split's job, not this guard's.
    """
    lines, y = [], top
    for _ in range(3):
        lines.append(_line(80.0, 180.0, y))
        lines.append(_line(80.0, 180.0, y + 1.5))
        y += 40.0
    y += 40.0
    body = [_line(80.0, 180.0, y + i * pitch) for i in range(10)]
    return lines + body, body


def _columnar(lines, n=4, top=60.0, pitch=14.0):
    """Give a page real column structure, so `_column_split` evidences it.

    Four baselines each carrying two wide members either side of x=300 -- the
    shape the row model reads. Needed because the constant fallback only fires
    on a page whose columns were actually found (task #40).
    """
    out = list(lines)
    for i in range(n):
        y = top + i * pitch
        out.append(_line(60.0, 290.0, y))
        out.append(_line(310.0, 589.0, y))
    out.sort(key=lambda l: (l.baseline, l.bbox[0]))
    return out


class AgainstTheRealAssembly(unittest.TestCase):
    """The guard has to survive `_build_blocks`, not just its own arithmetic."""

    def test_a_polluted_pitch_bucket_no_longer_shatters_the_body(self):
        lines, body = _polluted_page()
        blocks = _build_blocks(_columnar(lines))
        # The ten body lines share a left edge, a size and an 11.5pt step.
        # Before the guard the reference read 1.5, the gate came out 1.7, and
        # each of them became a block of its own.
        held = max(sum(1 for l in b.lines if l in body) for b in blocks)
        self.assertEqual(held, len(body),
                         "the body column must assemble as one block")

    def test_the_reference_that_page_computes_is_the_collapsed_one(self):
        # Pins the premise rather than assuming it: without the guard this
        # page really does compute an impossible pitch.
        from exactdoc.parse_pdfium import _body_pitch, _pitch_by_size
        lines, _ = _polluted_page()
        self.assertLess(_body_pitch(lines), PITCH_FLOOR_EM * 10.0)
        self.assertLess(_pitch_by_size(lines)[10.0], PITCH_FLOOR_EM * 10.0)

    def test_a_clean_single_column_page_is_unchanged_by_the_guard(self):
        lines = [_line(80.0, 180.0, 100.0 + i * 11.5) for i in range(10)]
        blocks = _build_blocks(lines)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(len(blocks[0].lines), 10)

    def test_a_paragraph_boundary_still_ends_a_block(self):
        # Ten lines at 11.5pt pitch, a 23pt boundary, ten more. The default
        # must not bridge it, or the guard trades shattering for fusing.
        lines = [_line(80.0, 180.0, 100.0 + i * 11.5) for i in range(10)]
        base = 100.0 + 9 * 11.5 + 23.0
        lines += [_line(80.0, 180.0, base + i * 11.5) for i in range(10)]
        self.assertEqual(len(_build_blocks(lines)), 2)


if __name__ == "__main__":
    unittest.main()
