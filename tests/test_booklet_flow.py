"""The booklet document-flow merge: runs of consecutive same-shape pages.

`_merge_grid_page_runs` had a measured residual after the grid-run merge
landed: y06 still inflated 126 -> 226 even though the export carried the
same text in FEWER lines at the exact source pitch. The missing pages were
the per-page seams of the booklet's non-grid pages. The extension merges
all-1-col runs -- but only inside documents whose pages are dominated by
>=3-col grids, so the gated corpus (no >=3-col page at all) keeps its
page-exact reconstruction.
"""
import unittest

from exactdoc.docxout import _merge_grid_page_runs, _JOIN_GAP_CAP_PT
from exactdoc.layout import Chunk, ColBreak, PageLayout


def _para(tag):
    class _P:
        pass
    p = _P()
    p.tag = tag
    return p


def page(number, chunks, continuation_only=False):
    pg = PageLayout(number=number, chunks=list(chunks))
    pg.continuation_only = continuation_only
    return pg


def grid_page(number, n_cols=3, lead=(), tail=()):
    chunks = []
    if lead:
        c = Chunk(n_cols=1)
        c.elements = list(lead)
        chunks.append(c)
    g = Chunk(n_cols=n_cols, col_gap=15.0)
    g.elements = [_para("g%d-c1" % number), ColBreak(), _para("g%d-c2" % number)]
    chunks.append(g)
    if tail:
        c = Chunk(n_cols=1)
        c.elements = list(tail)
        chunks.append(c)
    return page(number, chunks)


def onecol_page(number, tags=("a", "b")):
    c = Chunk(n_cols=1)
    c.elements = [_para("%d-%s" % (number, t)) for t in tags]
    return page(number, [c])


class BookletDetection(unittest.TestCase):
    """The booklet signature: >=10 >=3-col pages and >=35% of the document."""

    def _run(self, n_grid, n_plain):
        pgs = [grid_page(i + 1) for i in range(n_grid)] + \
              [onecol_page(1000 + i) for i in range(n_plain)]
        # interleave so grid runs are length 1 and the question is only
        # whether the plain pages merge
        pgs = [p for pair in zip(pgs[:n_grid], pgs[n_grid:]) for p in pair] \
            + pgs[2 * min(n_grid, n_plain):]
        return _merge_grid_page_runs(pgs), len(pgs)

    def test_booklet_merges_one_col_runs(self):
        # 12 grid pages (>= 10, >= 35% of 24) then 12 consecutive 1-col
        # pages: both shapes collapse to one synthetic page each
        pgs = [grid_page(i + 1) for i in range(12)] + \
              [onecol_page(100 + i) for i in range(12)]
        out = _merge_grid_page_runs(pgs)
        self.assertEqual(len(out), 2)
        self.assertEqual(len(out[1].chunks), 12)

    def test_below_count_threshold_is_not_booklet(self):
        # 9 grid pages (<10): the grid run still merges (it always did),
        # but the consecutive 1-col pages keep their seams
        pgs = [grid_page(i + 1) for i in range(9)] + \
              [onecol_page(100 + i) for i in range(9)]
        out = _merge_grid_page_runs(pgs)
        self.assertEqual(len(out), 1 + 9)

    def test_below_fraction_threshold_is_not_booklet(self):
        # 12 grid pages of 40 (0.30 < 0.35)
        pgs = [grid_page(i + 1) for i in range(12)] + \
              [onecol_page(100 + i) for i in range(28)]
        out = _merge_grid_page_runs(pgs)
        # grid runs: the 12 grid pages are consecutive -> 1 synthetic page;
        # the 28 plain pages are one unbroken run but NOT merged (not booklet)
        self.assertEqual(len(out), 1 + 28)


class OneColRuns(unittest.TestCase):
    def _booklet_with_plain_run(self):
        # ten 3-col pages make the document a booklet; the plain run sits
        # in the middle of it
        return [grid_page(i + 1) for i in range(5)] + \
               [onecol_page(10), onecol_page(11), onecol_page(12)] + \
               [grid_page(i + 20) for i in range(5)]

    def test_one_col_run_flows_into_one_page(self):
        out = _merge_grid_page_runs(self._booklet_with_plain_run())
        self.assertEqual(len(out), 3)
        self.assertEqual([c.n_cols for c in out[1].chunks], [1, 1, 1],
                         "the 1-col run concatenates its pages' chunks")
        tags = [e.tag for c in out[1].chunks for e in c.elements]
        self.assertEqual(tags, ["10-a", "10-b", "11-a", "11-b", "12-a", "12-b"])

    def test_shape_change_breaks_the_run(self):
        pgs = [onecol_page(1), grid_page(2, n_cols=2), onecol_page(3)]
        # not a booklet (no >=3-col page): nothing merges at all
        out = _merge_grid_page_runs(pgs)
        self.assertEqual(len(out), 3)

    def test_continuation_only_pages_never_join(self):
        pgs = [grid_page(1) for _ in range(10)] + \
              [page(11, [Chunk(n_cols=1)], continuation_only=True),
               onecol_page(12)]
        out = _merge_grid_page_runs(pgs)
        self.assertTrue(out[-2].continuation_only)
        self.assertEqual(len(out[-2].chunks), 1)
        self.assertEqual(len(out[-1].chunks), 1)

    def test_two_col_run_merges_inside_booklet(self):
        pgs = [grid_page(1, n_cols=3), grid_page(2, n_cols=2),
               grid_page(3, n_cols=2)]
        out = _merge_grid_page_runs(pgs)
        # the 3-col page is its own run; the two 2-col pages merge
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1].chunks[-1].n_cols, 2)


class GridRunsUnchanged(unittest.TestCase):
    """The pre-existing grid-run behavior must survive the extension."""

    def test_grid_run_keeps_first_lead_and_drops_breaks(self):
        pgs = [grid_page(1, lead=[_para("lead1")], tail=[_para("tail1")]),
               grid_page(2, lead=[_para("lead2")], tail=[_para("tail2")])]
        out = _merge_grid_page_runs(pgs)
        self.assertEqual(len(out), 1)
        chunks = out[0].chunks
        self.assertEqual([c.n_cols for c in chunks], [1, 3])
        self.assertEqual([e.tag for e in chunks[0].elements], ["lead1"])
        merged = chunks[1]
        tags = [e.tag for e in merged.elements]
        self.assertNotIn(ColBreak, [type(e) for e in merged.elements])
        self.assertEqual(
            tags,
            ["g1-c1", "g1-c2", "tail1", "lead2", "g2-c1", "g2-c2", "tail2"],
            "page one's grid, then the seam (previous tail before the next "
            "lead), then page two's grid, then the final tail")

    def test_page_with_two_multi_col_chunks_is_not_a_run_member(self):
        pgs = [page(1, [Chunk(n_cols=3), Chunk(n_cols=3)])]
        pgs += [grid_page(i + 2) for i in range(11)]
        out = _merge_grid_page_runs(pgs)
        self.assertEqual(len(out[0].chunks), 2)
        self.assertTrue(all(pg is not pgs[0] for pg in out[1:]))


class JoinedPageGapCap(unittest.TestCase):
    """A joined page's page-relative offsets are dead space in a flow."""

    def test_one_col_continuation_capped(self):
        class _P:
            def __init__(self, tag, sb):
                self.tag = tag
                self.space_before = sb
        c1 = Chunk(n_cols=1)
        c1.elements = [_P("first", 0.0)]
        c2 = Chunk(n_cols=1)
        c2.elements = [_P("second", 240.0), _P("third", 190.0)]
        c3 = Chunk(n_cols=1)
        c3.elements = [_P("fourth", 12.0)]
        pgs = [grid_page(i + 1) for i in range(10)] + \
              [page(11, [c1]), page(12, [c2]), page(13, [c3])]
        out = _merge_grid_page_runs(pgs)
        plains = out[-1]
        els = [e for c in plains.chunks for e in c.elements]
        self.assertEqual(els[0].space_before, 0.0,
                         "the run's own first page keeps its geometry")
        self.assertEqual(els[1].space_before, _JOIN_GAP_CAP_PT,
                         "a continuation page's 240pt page-top offset is capped")
        self.assertEqual(els[2].space_before, _JOIN_GAP_CAP_PT,
                         "a joined page's 190pt gap to a bottom-pinned note "
                         "is page-relative and capped too")
        self.assertEqual(els[3].space_before, 12.0,
                         "a real paragraph gap is untouched")

    def test_grid_seam_lead_capped(self):
        class _P:
            def __init__(self, tag, sb):
                self.tag = tag
                self.space_before = sb
        lead2 = Chunk(n_cols=1)
        lead2.elements = [_P("lead2", 180.0)]
        p1 = grid_page(1, tail=[_P("tail1", 5.0)])
        p2 = page(2, [lead2, Chunk(n_cols=3)])
        pgs = [p1, p2] + [grid_page(i + 3) for i in range(9)]
        out = _merge_grid_page_runs(pgs)
        run = next(p for p in out if any(c.n_cols == 3 for c in p.chunks))
        merged = next(c for c in run.chunks if c.n_cols == 3)
        lead_el = next(e for e in merged.elements if getattr(e, "tag", "") == "lead2")
        tail_el = next(e for e in merged.elements if getattr(e, "tag", "") == "tail1")
        self.assertEqual(lead_el.space_before, _JOIN_GAP_CAP_PT)
        self.assertEqual(tail_el.space_before, 5.0,
                         "a genuine same-page gap before a tail is untouched")


if __name__ == "__main__":
    unittest.main()
