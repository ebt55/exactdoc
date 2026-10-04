"""The refine loop: page alignment, overflow levers, cost, and degradation.

Four properties, each of which the loop once lacked (see `exactdoc.refine`):

  * pages are mapped by a monotone alignment over unique lines, so running
    heads and repeated furniture cannot pull a page onto the wrong render;
  * a spilled page with no gap slack gets <=3% line pitch, then table padding,
    never more than the render says must go, and the spend is recorded;
  * the source is read once per loop however many rounds run;
  * a LibreOffice that is installed but fails costs a warning, not the DOCX,
    and the result says what actually ran.

Synthetic throughout: a fake backend serves page lines for "source" and
"rendered" PDFs, so the assertions are about the loop's arithmetic and not
about any renderer's metrics.
"""
import io
import os
import sys
import tempfile
import unittest
import warnings
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from exactdoc import refine as R
from exactdoc.layout import (Cell, Chunk, DocLayout, FigureEl, PageLayout,
                             Para, RuleEl, Run, TableEl)


def _lines(*texts, top=72.0, pitch=12.0):
    """page_lines rows: (text, top, baseline, bottom)."""
    return [(t, top + k * pitch, top + k * pitch + 9.0, top + k * pitch + 11.0)
            for k, t in enumerate(texts)]


class _FakeBackend:
    name = "fake"

    def __init__(self, pages_by_path):
        self.pages = pages_by_path
        self.calls = []

    def page_lines(self, path):
        self.calls.append(path)
        return self.pages[path]


HEAD = "RFC 9999 Example Semantics June 2026"
FOOT = "Example, et al. Standards Track"


def _content(page, n=6):
    return ["page %d distinctive body line number %d" % (page, k)
            for k in range(n)]


class AlignmentTests(unittest.TestCase):
    def test_running_heads_cannot_anchor_and_mapping_is_monotone(self):
        # Three source pages, every one opening with the same head and closing
        # with the same foot. Page 1 spills: its last two lines land on a
        # rendered page of their own, which also carries the head and foot.
        src = [[HEAD] + _content(p) + [FOOT] for p in range(3)]
        out = [[HEAD] + _content(0) + [FOOT],
               [HEAD] + _content(1)[:4] + [FOOT],
               [HEAD] + _content(1)[4:] + [FOOT],
               [HEAD] + _content(2) + [FOOT]]
        norm = lambda pages: [[(R._norm(t), 0.0, 0.0) for t in pg]
                              for pg in pages]
        anchors = R._align(norm(src), norm(out))
        self.assertNotIn(R._norm(HEAD),
                         [norm(src)[a[0]][a[1]][0] for a in anchors])
        self.assertEqual(R._map_pages(norm(src), norm(out)), [0, 1, 3])

    def test_out_of_order_coincidences_are_dropped_by_the_chain(self):
        # A line unique on both sides but rendered far out of sequence (a
        # caption that floated) is one bad anchor among many good ones; the
        # longest increasing chain drops it rather than following it.
        src = [_content(p) for p in range(4)]
        out = [list(pg) for pg in src]
        stray = "floating caption text unique in both"
        src[1].insert(0, stray)
        out[3].append(stray)
        norm = lambda pages: [[(R._norm(t), 0.0, 0.0) for t in pg]
                              for pg in pages]
        self.assertEqual(R._map_pages(norm(src), norm(out)), [0, 1, 2, 3])

    def test_short_strings_do_not_anchor(self):
        src = [["41"] + _content(0), ["42"] + _content(1)]
        out = [["42"] + _content(0), ["41"] + _content(1)]
        norm = lambda pages: [[(R._norm(t), 0.0, 0.0) for t in pg]
                              for pg in pages]
        anchors = R._align(norm(src), norm(out))
        texts = [norm(src)[a[0]][a[1]][0] for a in anchors]
        self.assertNotIn("41", texts)
        self.assertEqual(R._map_pages(norm(src), norm(out)), [0, 1])


class MeasureTests(unittest.TestCase):
    def test_source_is_read_once_across_rounds(self):
        src = [_lines(*_content(0))]
        bk = _FakeBackend({"src.pdf": src, "r0.pdf": src, "r1.pdf": src})
        cache = {}
        R._measure("src.pdf", "r0.pdf", bk, src_cache=cache)
        R._measure("src.pdf", "r1.pdf", bk, src_cache=cache)
        self.assertEqual(bk.calls.count("src.pdf"), 1)

    def test_need_is_the_overflow_less_the_room_left_behind(self):
        # Body band 72..720. Source page 0 renders across two pages: the first
        # holds 48 lines at a 13.4pt pitch, ending at 72 + 47*13.4 + 11 =
        # 712.8 (7.2pt left behind); the second carries the last two lines,
        # ending at 72 + 13.4 + 11 = 96.4 (24.4pt of overflow). 24.4 - 7.2 +
        # the fit safety is what must leave the page.
        body = _content(0, 50)
        src = [_lines(*body, pitch=12.0), _lines(*_content(1))]
        full = _lines(*body[:48], pitch=13.4)
        tail = _lines(*body[48:], pitch=13.4)
        rendered = [full, tail, _lines(*_content(1))]
        bk = _FakeBackend({"s": src, "r": rendered})
        m = R._measure("s", "r", bk, geom=(792.0, 72.0, 720.0))
        self.assertEqual(m["spill"], [1, 0])
        want = (96.4 - 72.0) - (720.0 - 712.8) + R.FIT_SAFETY_PT
        self.assertAlmostEqual(m["need"][0], want, places=6)
        self.assertIsNone(m["need"][1])


def _dense_page(n_paras=10, lead=12.0, lines=4, gap=0.0):
    els = [Para(runs=[Run(text="x", font="Helvetica", size=10.0,
                          color="#000000")],
                leading=lead, src_lines=lines, space_before=gap)
           for _ in range(n_paras)]
    return PageLayout(number=1, chunks=[Chunk(elements=els)]), els


class LeverTests(unittest.TestCase):
    def test_a_gapless_page_squeezes_leading_up_to_the_measured_need(self):
        pg, els = _dense_page()
        lay = DocLayout(pages=[pg])
        state = R.new_state()
        # 10 paras x 4 lines x 12pt = 480pt of pitch; need 4.8pt -> 1%
        R._apply(lay, {"spill": [1], "offset": [0.0], "need": [4.8]}, state)
        for p in els:
            self.assertAlmostEqual(p.leading, 12.0 * 0.99)
        led = R.ledger_summary(state)
        self.assertAlmostEqual(led["leading_pt"], 4.8, places=1)
        self.assertEqual(led["leading_pages"], 1)
        self.assertEqual(led["gap_pt"], 0.0)

    def test_leading_never_compounds_past_three_percent(self):
        pg, els = _dense_page()
        lay = DocLayout(pages=[pg])
        state = R.new_state()
        for _ in range(5):
            R._apply(lay, {"spill": [1], "offset": [0.0], "need": [100.0]},
                     state)
        for p in els:
            self.assertAlmostEqual(p.leading, 12.0 * (1 - R.MAX_LEADING_SQUEEZE))

    def test_gaps_are_spent_first_and_leading_only_for_the_remainder(self):
        pg, els = _dense_page(gap=10.0)
        lay = DocLayout(pages=[pg])
        state = R.new_state()
        # 100pt of gaps; the unchanged gap rule takes half of it (50pt),
        # which covers a 30pt need -- leading untouched.
        R._apply(lay, {"spill": [1], "offset": [0.0], "need": [30.0]}, state)
        self.assertEqual([p.leading for p in els], [12.0] * len(els))
        self.assertAlmostEqual(R.ledger_summary(state)["gap_pt"], 50.0)

    def test_without_a_measured_need_only_the_gap_rule_runs(self):
        pg, els = _dense_page(gap=10.0)
        lay = DocLayout(pages=[pg])
        R._apply(lay, {"spill": [1], "offset": [0.0], "need": [None]})
        self.assertEqual([p.leading for p in els], [12.0] * len(els))

    def test_table_padding_is_the_last_lever(self):
        cell = lambda: Cell(paras=[Para(runs=[Run(text="c", font="Helvetica",
                                                  size=9.0, color="#000000")],
                                        leading=11.0, src_lines=1)],
                            pad=(3.0, 4.0, 3.0, 4.0))
        t = TableEl(rows=[[cell(), cell()] for _ in range(10)],
                    col_widths=[100.0, 100.0])
        pg = PageLayout(number=1, chunks=[Chunk(elements=[t])])
        lay = DocLayout(pages=[pg])
        state = R.new_state()
        # leading base: 10 rows x 11pt = 110pt -> 3% = 3.3pt; pads 10 x 6pt.
        R._apply(lay, {"spill": [1], "offset": [0.0], "need": [9.3]}, state)
        led = R.ledger_summary(state)
        self.assertAlmostEqual(led["leading_pt"], 3.3, places=1)
        self.assertAlmostEqual(led["padding_pt"], 6.0, places=1)
        top, left, bottom, right = t.rows[0][0].pad
        self.assertAlmostEqual(top, 3.0 * 0.9)
        self.assertEqual((left, right), (4.0, 4.0))
        # never past half the inferred pad, whatever is asked
        for _ in range(4):
            R._apply(lay, {"spill": [1], "offset": [0.0], "need": [500.0]},
                     state)
        self.assertAlmostEqual(t.rows[0][0].pad[0], 1.5)


class _Writer:
    def __init__(self):
        self.n = 0

    def __call__(self, _lay, path, **_kw):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("_rels/.rels", "<Relationships/>")
            z.writestr("word/document.xml", "<w:document>round %d</w:document>"
                       % self.n)
        self.n += 1
        return path


def _m(pages, spill, offset):
    return {"out_pages": pages, "src_pages": 2, "spill": spill,
            "offset": offset, "need": [None] * len(spill)}


class StoppingTests(unittest.TestCase):
    def _run(self, ms):
        renders = []

        def render(candidate, scratch):
            renders.append(candidate)
            return os.path.join(scratch, "r.pdf")

        report = {}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("exactdoc.docxout.write_docx", side_effect=_Writer()), \
                mock.patch("exactdoc.refine._measure", side_effect=ms), \
                mock.patch("exactdoc.refine._apply", return_value=True):
            R.refine(object(), "in.pdf", os.path.join(d, "o.docx"), rounds=3,
                     render=render, backend=_FakeBackend({}), report=report)
        return renders, report

    def test_offsets_that_stop_improving_end_the_loop(self):
        # Nothing spills; the offsets got worse. Another round would only
        # oscillate, so the loop stops and keeps the best.
        renders, report = self._run([_m(2, [0, 0], [3.0, 0.0]),
                                     _m(2, [0, 0], [4.0, 0.0])])
        self.assertEqual(len(renders), 2)          # not 4
        self.assertEqual(report["stopped"], "no-improvement")
        self.assertEqual(report["published_round"], 0)

    def test_corrections_that_diverge_end_the_loop(self):
        renders, report = self._run([_m(3, [1, 0], [0.0, 0.0]),
                                     _m(4, [2, 0], [0.0, 0.0])])
        self.assertEqual(len(renders), 2)
        self.assertEqual(report["stopped"], "no-improvement")

    def test_a_stalled_spill_gets_its_remaining_rounds(self):
        # x11's shape: the spill holds for a round and closes on the next.
        renders, report = self._run([_m(3, [1, 0], [0.0, 0.0]),
                                     _m(3, [1, 0], [5.0, 0.0]),
                                     _m(2, [0, 0], [0.0, 0.0])])
        self.assertEqual(len(renders), 3)
        self.assertEqual(report["stopped"], "converged")
        self.assertEqual(report["published_round"], 2)


class ConvertResultTests(unittest.TestCase):
    def _convert(self, render):
        from exactdoc.convert import convert_result
        from exactdoc.options import PRODUCT

        class Bk:
            name = "pdfium"

        lay = DocLayout()
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "o.docx")
            with mock.patch("exactdoc.convert._select_backend", return_value=Bk()), \
                 mock.patch("exactdoc.convert.preflight", return_value=None), \
                 mock.patch("exactdoc.convert.parse_input", return_value=object()), \
                 mock.patch("exactdoc.convert.normalize", return_value=object()), \
                 mock.patch("exactdoc.convert.infer", return_value=lay), \
                 mock.patch("exactdoc.docxout.write_docx", side_effect=_Writer()), \
                 mock.patch("exactdoc.targets.get_renderer",
                            return_value=(render, "libreoffice")):
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    res = convert_result("in.pdf", out, options=PRODUCT)
            return res, caught

    def test_a_failed_oracle_is_a_degraded_result_not_a_failure(self):
        class Dead:
            last_failure = "LibreOffice exited with status 1 without writing a PDF (3 attempts)"
            closed = False

            def __call__(self, _c, _s):
                return None

            def close(self):
                Dead.closed = True

        res, caught = self._convert(Dead())
        self.assertTrue(res.degraded)
        self.assertEqual(res.resolved_options.oracle, "none")
        self.assertEqual(res.resolved_options.refine_rounds, 0)
        self.assertEqual(res.requested_options.refine_rounds, 3)
        self.assertEqual([w.code for w in res.warnings], ["oracle-degraded"])
        self.assertIn("exited with status 1", res.warnings[0].detail)
        self.assertEqual(res.refine_rounds_completed, 0)
        self.assertEqual(len(res.oracle_runs), 1)
        self.assertFalse(res.oracle_runs[0].ok)
        self.assertTrue(Dead.closed)
        self.assertTrue(any(w.category.__name__ == "OracleDegradedWarning"
                            for w in caught))
        d = res.as_dict()
        self.assertTrue(d["degraded"])
        self.assertEqual(d["warnings"][0]["code"], "oracle-degraded")


class CliDegradationTests(unittest.TestCase):
    def test_cli_exits_zero_and_says_so_on_stderr(self):
        from exactdoc import cli
        from exactdoc.options import PRODUCT
        from exactdoc.result import ConversionResult, ConversionWarning
        res = ConversionResult(
            output_path="o.docx", output_sha256="0" * 64,
            requested_options=PRODUCT,
            resolved_options=PRODUCT.replace(oracle="none", refine_rounds=0),
            warnings=(ConversionWarning(
                code="oracle-degraded", stage="refine",
                message="the libreoffice oracle failed in refine round 0; the "
                        "published DOCX is the open-loop conversion, unrefined",
                detail="LibreOffice did not finish within 300s"),))
        err, out = io.StringIO(), io.StringIO()
        with mock.patch("exactdoc.convert.convert_result", return_value=res), \
                redirect_stderr(err), redirect_stdout(out):
            code = cli.main(["in.pdf", "-o", "o.docx"])
        self.assertIn(code, (0, None))
        self.assertIn("wrote o.docx", out.getvalue())
        self.assertIn("warning: the libreoffice oracle failed", err.getvalue())
        self.assertIn("did not finish", err.getvalue())


if __name__ == "__main__":
    unittest.main()
