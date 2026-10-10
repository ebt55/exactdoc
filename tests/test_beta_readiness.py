"""testkit/beta_readiness.py reads measurements honestly.

Synthetic inputs: a small corpus, sweeps written to a temp folder, Docs and
Word rows, lane verdicts, an accepted sweep, a kept DOCX and a README. What is
pinned is the reading -- a missing input is UNMEASURED and never PASS, a typed
refusal is not a crash, an upload failure is not the converter's, REPORTED
criteria do not gate, "FAIL by N" counts what it says -- and which criteria
gate, as the owner ratified them on 2026-10-05 and amended them on 2026-10-06
(the LibreOffice lane reads the product DOCX; the accepted sweep is compared in
its own flavour). One test reads the real manifests:
the gated tiers come from the ratified policy, so ordinary_digital is 72.

    python -m unittest tests.test_beta_readiness
"""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import beta_readiness as B                                     # noqa: E402


def _doc(tier="ordinary_digital", pages=3, promised=True, gated=False):
    return {"tier": tier, "pages": pages, "promised": promised, "gated": gated}


DOCS = {
    "short.pdf": _doc(pages=3),
    "short2.pdf": _doc(pages=2),
    "long.pdf": _doc(pages=50),
    "paper.pdf": _doc(pages=8, promised=False),
    "form.pdf": _doc(tier="unsupported", pages=2, promised=False),
}


def _row(doc, src, out, conv=1.0, cr=0.99, wr=0.99, dy=1.0, **kw):
    r = {"document": doc, "src_pages": src, "out_pages": out,
         "page_ratio": out / src, "convert_s": conv, "char_recall": cr,
         "word_recall": wr, "dy_p50": dy, "doc_recall": wr,
         "live_text_cov": 0.99, "within2pt": 0.5,
         "editability": {"textbox_frac": 0.0, "one_cell_tables_per_page": 0.0,
                         "numpr_frac": None}}
    r.update(kw)
    return r


class Reading(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _sweep(self, name, profile, rows):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"schema": "exactdoc.quality-sweep.v1", "profile": profile,
                       "corpus": "both", "documents": rows}, fh)
        return path

    def _jsonl(self, name, rows):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return path

    def _gate(self, raw_ok=True):
        for lane, ok in (("raw", raw_ok), ("product", True)):
            d = os.path.join(self.dir, "run.batch", "lane_%s" % lane)
            os.makedirs(d)
            with open(os.path.join(d, "verdict.json"), "w") as fh:
                json.dump({"lane": lane, "ok": ok, "failures": [] if ok else ["x"],
                           "notes": ["16 document(s) measured, 16 expected"]}, fh)

    def _by_key(self, result):
        return {c["key"]: c for c in result["criteria"]}

    def test_everything_missing_is_unmeasured_never_pass(self):
        res = B.evaluate(DOCS, {}, {"lo": None, "word": None, "docs": None}, None)
        self.assertEqual(res["verdict"], "INCOMPLETE")
        gating = [c for c in res["criteria"] if c["key"] not in B.BAR["reported_only"]]
        self.assertNotIn("PASS", [c["status"] for c in gating])
        self.assertEqual(len(res["criteria"]), 13)

    def test_a_full_reading(self):
        raw = [_row("short.pdf", 3, 3), _row("short2.pdf", 2, 2, dy=25.0),
               _row("long.pdf", 50, 51, conv=40.0),
               _row("paper.pdf", 8, 12, cr=0.3)]            # unpromised: not graded
        self._sweep("r.sweep.json", "pdfium/standard/none/refine0@240dpi", raw)
        self._sweep("p.sweep.json", "pdfium/standard/libreoffice/refine3@240dpi",
                    [_row("short.pdf", 3, 3, conv=61.0),     # over 60s at 3 pages
                     _row("short2.pdf", 2, 2),
                     _row("long.pdf", 50, 50, conv=70.0, dy=5.0),
                     _row("form.pdf", 2, 2, conv=999.0)])    # unsupported: not timed
        self._jsonl("rows.jsonl", [
            {"doc": "short.pdf", "src_pages": 3, "out_pages": 4, "char_recall": 0.99,
             "word_recall": 0.95, "dy_p50": 2.0},
            {"doc": "short2.pdf", "error": "RoundtripError: upload"},
            {"doc": "form.pdf", "error": "InteractiveFormError: no"},
            {"doc": "probe.pdf", "src_pages": 1, "out_pages": 9}])
        self._jsonl("word_rows.jsonl", [
            {"doc": "short", "word_version": "16.0", "out_pages": 3, "ok": True,
             "repair_prompt": False, "compat": 15},
            {"doc": "short2", "word_version": "16.0", "out_pages": 2, "ok": True,
             "repair_prompt": True, "compat": 15}])
        self._gate()
        accepted = self._sweep("accepted.json", "pdfium/standard/libreoffice/refine3@240dpi",
                               [_row("short.pdf", 3, 3), _row("short2.pdf", 2, 2),
                                _row("long.pdf", 50, 50), _row("paper.pdf", 8, 8)])
        os.makedirs(os.path.join(self.dir, "kept", "short"))
        with zipfile.ZipFile(os.path.join(self.dir, "kept", "short", "short.docx"), "w") as z:
            z.writestr("word/document.xml",
                       '<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Fancy Grotesk"/>'
                       '</w:rPr></w:r>')
            z.writestr("word/fontTable.xml", '<w:font w:name="Times New Roman"/>')
        readme = os.path.join(self.dir, "README.md")
        with open(readme, "w", encoding="utf-8") as fh:
            fh.write("See [old](docs/evidence/sweep-2020-01-01.json). In the live "
                     "sweep, 5 of the 9 compared came back with exactly the right "
                     "number of pages.\n")

        sweeps = B.find_sweeps([self.dir], DOCS)
        self.assertEqual(sorted(sweeps), ["product", "raw"])
        docs_rows = B.find_rows([self.dir], DOCS, "docs")
        word_rows = B.find_rows([self.dir], DOCS, "word")
        self.assertTrue(docs_rows[0].endswith("rows.jsonl"))
        self.assertTrue(word_rows[0].endswith("word_rows.jsonl"))
        # amendment 1 (2026-10-06): the LibreOffice lane is the product sweep
        lanes = {"lo": sweeps["product"][1]["documents"],
                 "docs": [r for r in docs_rows[1] if B.row_lane(r) == "docs"],
                 "word": [r for r in word_rows[1] if B.row_lane(r) == "word"]}
        res = B.evaluate(DOCS, sweeps, lanes, B.find_gate([self.dir]),
                         accepted=(accepted, B.load_sweep(accepted)),
                         docx_dir=os.path.join(self.dir, "kept"), readme_path=readme)
        c = self._by_key(res)

        self.assertEqual(c["crash"]["status"], "PASS")
        self.assertIn("1/1 unsupported refused", c["crash"]["detail"])
        self.assertIn("1 upload/measurement failure(s) not counted", c["crash"]["detail"])
        # product: short.pdf 61s > 60s; long.pdf 70s <= 1.5 x 50; form.pdf skipped
        self.assertEqual((c["time"]["status"], c["time"]["by"]), ("FAIL", 1))
        self.assertIn("short 61s for 3 pages", c["time"]["misses"][0])
        # Word: short2 showed a repair prompt; compat recorded
        self.assertEqual((c["word-open"]["status"], c["word-open"]["by"]), ("FAIL", 1))
        self.assertIn("compatibility modes 15 x2", c["word-open"]["detail"])
        # short promised: LO exact, Word exact, Docs short.pdf 3->4
        self.assertEqual((c["short-exact"]["status"], c["short-exact"]["by"]), ("FAIL", 1))
        self.assertEqual(c["short-exact"]["misses"], ["Docs live short (3->4 pages, "
                                                      "wr 0.95, cr 0.99, dy50 2.0)"])
        # long.pdf is 50->50 in the product sweep; Word/Docs have no row
        self.assertIn("LO product 1/1", c["long-close"]["detail"])
        # Docs' 3->4 is +33%; paper.pdf's 0.3 char recall is unpromised, so unread
        self.assertEqual((c["catastrophic"]["status"], c["catastrophic"]["by"]), ("FAIL", 1))
        self.assertNotIn("paper", " ".join(c["catastrophic"]["misses"]))
        self.assertEqual(c["placement"]["status"], "REPORTED")
        self.assertIn("would FAIL", c["placement"]["detail"])
        # long.pdf dy_p50 1.0 -> 5.0 against the accepted PRODUCT sweep; the raw
        # sweep's 50 -> 51 is not read, because the accepted sweep is product
        self.assertEqual((c["regression"]["status"], c["regression"]["by"]), ("FAIL", 1))
        self.assertIn("long dy_p50 1 -> 5", c["regression"]["misses"][0])
        self.assertIn("(product flavour)", c["regression"]["detail"])
        self.assertEqual(c["editability"]["status"], "REPORTED")
        self.assertIn("LO product sweep", c["editability"]["detail"])
        self.assertEqual((c["fonts"]["status"], c["fonts"]["by"]), ("FAIL", 1))
        self.assertIn("Fancy Grotesk", c["fonts"]["misses"][0])
        self.assertEqual(c["gate"]["status"], "PASS")
        # 12 gates since ratification: a stale citation and a contradicted count
        self.assertEqual((c["readme"]["status"], c["readme"]["by"]), ("FAIL", 2))
        self.assertEqual(c["gdocs-policy"]["status"], "REPORTED")
        # criterion 13 reads every lane, not Docs alone
        for lane in ("LO product", "Word", "Docs live"):
            self.assertIn(lane, c["gdocs-policy"]["detail"])
        self.assertTrue(any(m.startswith("LO product ") for m in c["gdocs-policy"]["misses"]))
        self.assertEqual(res["verdict"], "NOT READY")
        text = B.render(res, [("raw sweep", "r.sweep.json", "x", False)])
        self.assertIn("ratified by the owner on 2026-10-05, amended 2026-10-06", text)
        self.assertIn("0.3.0b1 is not tagged while any gating criterion fails", text)
        self.assertIn(" 2 FAIL by 1 ", text)

    def test_a_crash_and_a_failed_lane_fail(self):
        path = self._sweep("r.sweep.json", "pdfium/standard/none/refine0@240dpi",
                           [_row("short.pdf", 3, 4, cr=0.4),
                            {"document": "short2.pdf", "error": "KeyError: 'x'"}])
        self._gate(raw_ok=False)
        sweeps = {"raw": (path, B.load_sweep(path))}
        res = B.evaluate(DOCS, sweeps, {"lo": sweeps["raw"][1]["documents"],
                                        "word": None, "docs": None},
                         B.find_gate([self.dir]))
        c = self._by_key(res)
        self.assertEqual((c["crash"]["status"], c["crash"]["by"]), ("FAIL", 1))
        self.assertEqual(c["gate"]["status"], "FAIL")
        self.assertEqual(c["catastrophic"]["status"], "FAIL")

    def test_serial_timings_win_over_the_sweep(self):
        prod = self._sweep("p.sweep.json", "pdfium/standard/libreoffice/refine3@240dpi",
                           [_row("short.pdf", 3, 3, conv=90.0),
                            _row("long.pdf", 50, 50, conv=70.0)])
        path = os.path.join(self.dir, "run.timing.json")
        with open(path, "w") as fh:
            json.dump({"schema": "exactdoc.serial-timing.v1", "jobs": 1,
                       "profile": "pdfium/standard/libreoffice/refine3@240dpi",
                       "documents": [{"document": "short.pdf", "src_pages": 3,
                                      "convert_s": 41.0}]}, fh)
        timings = B.find_timings([self.dir])
        self.assertEqual(list(timings), ["product"])
        res = B.evaluate(DOCS, {"product": (prod, B.load_sweep(prod))},
                         {"lo": None, "word": None, "docs": None}, None,
                         timings=timings)
        c = self._by_key(res)["time"]
        # short.pdf: 90s in the sweep, 41s alone -> under its 60s limit
        self.assertNotIn("short", " ".join(c["misses"]))
        self.assertIn("1 timed serially", c["detail"])

    def test_a_targeted_sweep_is_not_a_reading_of_the_product(self):
        self._sweep("only.sweep.json", "pdfium/standard/none/refine0@240dpi",
                    [_row("short.pdf", 3, 3)])
        many = dict(DOCS, **{"d%d.pdf" % i: _doc() for i in range(20)})
        self.assertEqual(B.find_sweeps([self.dir], many), {})

    def test_the_real_corpus(self):
        docs = B.corpus()
        self.assertEqual(len(docs), 95)
        self.assertEqual(sum(1 for d in docs.values() if d["tier"] == "ordinary_digital"), 72)
        self.assertEqual(docs["c3_tables.pdf"]["tier"], "designed_stress")
        self.assertFalse(docs["c3_tables.pdf"]["promised"])
        self.assertTrue(docs["01_whitepaper_market.pdf"]["promised"])
        for not_yet in ("y34_census_slides_pptx365.pdf", "y58_ssa_statement_indd20.pdf",
                        "y41_arxiv_ieeetran.pdf"):
            self.assertIs(docs[not_yet]["promised"], False, not_yet)
        self.assertEqual([d for d, s in docs.items() if s["promised"] is None], [])
        self.assertEqual(sum(1 for d in docs.values() if d["promised"]), 62)

    def test_amendment_1_the_libreoffice_lane_is_the_product_docx(self):
        # raw gains a page on short.pdf, product does not: the lane reads product
        raw = self._sweep("r.sweep.json", "pdfium/standard/none/refine0@240dpi",
                          [_row("short.pdf", 3, 4), _row("short2.pdf", 2, 2),
                           _row("long.pdf", 50, 50)])
        prod = self._sweep("p.sweep.json", "pdfium/standard/libreoffice/refine3@240dpi",
                           [_row("short.pdf", 3, 3), _row("short2.pdf", 2, 2),
                            _row("long.pdf", 50, 50, conv=200.0)])
        out = os.path.join(self.dir, "res.json")
        with mock.patch("sys.stdout", new=io.StringIO()), \
                mock.patch.object(B, "corpus", return_value=DOCS):
            B.main(["--raw", raw, "--product", prod, "--json", out,
                    "--runs", os.path.join(self.dir, "none")])
        with open(out, encoding="utf-8") as fh:
            c = self._by_key(json.load(fh))
        self.assertIn("LO product 2/2 = 100.0%", c["short-exact"]["detail"])
        # criterion 2 still times both profiles: long.pdf 200s > 1.5 x 50 (product)
        self.assertIn("product long 200s", " ".join(c["time"]["misses"]))
        self.assertEqual(B.BAR["lo_flavour"], "product")
        self.assertIn("2026-10-06", B.BAR["amended"])

    def test_the_accepted_sweep_is_compared_in_its_own_flavour(self):
        rows = [_row("short.pdf", 3, 3), _row("short2.pdf", 2, 2),
                _row("long.pdf", 50, 50), _row("paper.pdf", 8, 8)]
        raw = self._sweep("r.sweep.json", "pdfium/standard/none/refine0@240dpi",
                          rows[:2] + [_row("long.pdf", 50, 52)] + rows[3:])
        prod = self._sweep("p.sweep.json", "pdfium/standard/libreoffice/refine3@240dpi",
                           rows)
        sweeps = {"raw": (raw, B.load_sweep(raw)), "product": (prod, B.load_sweep(prod))}
        lanes = {"lo": rows, "word": None, "docs": None}

        def reading(accepted_rows, profile):
            acc = self._sweep("acc-%s.json" % profile.split("/")[2], profile, accepted_rows)
            res = B.evaluate(DOCS, sweeps, lanes, None, accepted=(acc, B.load_sweep(acc)))
            return self._by_key(res)["regression"]

        # a product accepted sweep: the product sweep matches it
        c = reading(rows, "pdfium/standard/libreoffice/refine3@240dpi")
        self.assertEqual(c["status"], "PASS")
        # a raw accepted sweep (the pre-amendment reading): long.pdf 50 -> 52 raw
        c = reading(rows, "pdfium/standard/none/refine0@240dpi")
        self.assertEqual((c["status"], c["by"]), ("FAIL", 1))
        self.assertIn("(raw flavour)", c["detail"])
        # wp18-m2-prod ran 13 documents: it cannot say "no document worse"
        c = reading(rows[:1], "pdfium/standard/libreoffice/refine3@240dpi")
        self.assertEqual(c["status"], "UNMEASURED")
        self.assertIn("covers 1 documents", c["detail"])

    def test_the_ratified_split(self):
        self.assertEqual(set(B.BAR["reported_only"]),
                         {"placement", "editability", "gdocs-policy"})
        self.assertIn("2026-10-05", B.BAR["ratified"])

    def test_profile_kinds(self):
        self.assertEqual(B._profile_kind("pdfium/standard/none/refine0@240dpi"), "raw")
        self.assertEqual(B._profile_kind("pdfium/standard/libreoffice/refine3@240dpi"),
                         "product")
        self.assertEqual(B._profile_kind("pdfium/gdocs/none/refine0@240dpi"), "gdocs-lo")
        self.assertIsNone(B._profile_kind("nonsense"))
        # a capped refine loop is a measurement, not the product
        self.assertIsNone(B._profile_kind("pdfium/standard/libreoffice/refine1@240dpi"))


PROD = "pdfium/standard/libreoffice/refine3@240dpi"


class Waivers(unittest.TestCase):
    """Criterion-8 exceptions (testkit/beta_waivers.json): bounded, tied to the
    accepted sweep by name and SHA-256, to a reading and to a release, and
    self-retiring. paper.pdf is unpromised; its dy_p50 goes 20 -> 23 against a
    tolerance of max(0.5, 10% x 20) = 2, so it is flagged; the waiver's
    ceiling is 25."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name
        self.rows = [_row("short.pdf", 3, 3), _row("short2.pdf", 2, 2),
                     _row("long.pdf", 50, 50), _row("paper.pdf", 8, 8, dy=20.0)]
        self.acc = self._sweep("accepted-x.sweep.json", self.rows,
                               rescored={"scorer": "wp29"})
        import hashlib
        with open(self.acc, "rb") as fh:
            self.sha = hashlib.sha256(fh.read()).hexdigest()

    def tearDown(self):
        self._td.cleanup()

    def _sweep(self, name, rows, **extra):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict({"schema": "exactdoc.quality-sweep.v1", "profile": PROD,
                            "corpus": "both", "documents": rows}, **extra), fh)
        return path

    def _spec(self, **over):
        spec = {"ceiling": 25.0, "release": "0.3.0b1",
                "accepted_sweep": {"name": "accepted-x.sweep.json", "sha256": self.sha},
                "reading": "wp29",
                "measured": {"accepted": 20.0, "current": 23.0, "sweep": "cur.sweep.json"},
                "decided_by": "the owner", "decided_on": "2026-10-10",
                "evidence": "docs/beta-bar.md#exceptions", "conditions": "a-g"}
        for k, v in over.items():
            if v is None:
                spec.pop(k, None)
            else:
                spec[k] = v
        return spec

    def _waivers(self, doc="paper.pdf", metric="dy_p50", spec=None, raw=None):
        path = os.path.join(self.dir, "beta_waivers.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(raw if raw is not None else {
                "schema": B.WAIVERS_SCHEMA,
                "regression": {doc: {metric: spec if spec is not None else self._spec()}}}, fh)
        return path

    def _read(self, current_rows, waivers_path=None, release=B.RELEASE, **extra):
        cur = self._sweep("cur.sweep.json", current_rows, **extra)
        sweeps = {"product": (cur, B.load_sweep(cur))}
        res = B.evaluate(DOCS, sweeps, {"lo": current_rows, "word": None, "docs": None},
                         None, accepted=(self.acc, B.load_sweep(self.acc)),
                         waivers=B.load_waivers(waivers_path or self._waivers()),
                         release=release)
        return {c["key"]: c for c in res["criteria"]}["regression"], res

    def _current(self, dy=23.0, **kw):
        return self.rows[:3] + [_row("paper.pdf", 8, 8, dy=dy, **kw)]

    def test_without_a_waiver_the_flag_fails(self):
        path = self._waivers(raw={"schema": B.WAIVERS_SCHEMA, "regression": {}})
        c, _ = self._read(self._current(), path)
        self.assertEqual((c["status"], c["by"]), ("FAIL", 1))
        self.assertIn("paper dy_p50 20 -> 23 (tolerance 2)", c["misses"])
        self.assertEqual(c["waivers"], [])

    def test_in_bounds_passes_and_prints_the_waiver(self):
        c, res = self._read(self._current())
        self.assertEqual(c["status"], "PASS")
        self.assertEqual(c["waived"], 1)
        self.assertIn("1 waived: paper dy_p50 20->23 <= ceiling 25.0, owner exception "
                      "2026-10-10", c["detail"])
        (v,) = c["waivers"]
        self.assertEqual((v["verdict"], v["blocking"]), ("waived", False))
        self.assertEqual((v["accepted"], v["current"], v["tolerance"]), (20.0, 23.0, 2.0))
        self.assertEqual(v["accepted_sweep"]["sha256"], self.sha)
        self.assertIn(" 8 PASS (1 waived)", B.render(res, []))

    def test_every_other_metric_on_the_waived_document_stays_gated(self):
        c, _ = self._read(self._current(wr=0.90, doc_recall=0.99))
        self.assertEqual((c["status"], c["by"]), ("FAIL", 1))
        self.assertEqual(c["waived"], 1)
        self.assertEqual([m for m in c["misses"] if not m.startswith("(")],
                         ["paper word_recall 0.99 -> 0.9 (tolerance 0.02)"])

    def test_out_of_bounds_blocks(self):
        c, _ = self._read(self._current(dy=25.5))
        self.assertEqual((c["status"], c["by"]), ("FAIL", 1))
        self.assertEqual(c["waived"], 0)
        self.assertEqual(c["waivers"][0]["verdict"], "out-of-bounds")
        self.assertIn("paper dy_p50 20 -> 25.5 (tolerance 2)", c["misses"])
        self.assertTrue(any(m.startswith("waiver out of bounds: paper dy_p50 20->25.5 > "
                                         "ceiling 25.0") for m in c["misses"]))

    def test_a_stale_accepted_sweep_blocks(self):
        for named in ({"name": "accepted-x.sweep.json", "sha256": "0" * 64},
                      {"name": "accepted-y.sweep.json", "sha256": self.sha}):
            c, _ = self._read(self._current(),
                              self._waivers(spec=self._spec(accepted_sweep=named)))
            self.assertEqual(c["status"], "FAIL", named)
            self.assertEqual(c["waivers"][0]["verdict"], "stale")
            self.assertTrue(any(m.startswith("stale waiver: paper dy_p50 names %s"
                                             % named["name"]) for m in c["misses"]))
            # the flag is not lifted by a stale waiver
            self.assertIn("paper dy_p50 20 -> 23 (tolerance 2)", c["misses"])
        # stale even when the document is no longer flagged: it dies with its sweep
        c, _ = self._read(self._current(dy=20.0), self._waivers(spec=self._spec(
            accepted_sweep={"name": "accepted-x.sweep.json", "sha256": "0" * 64})))
        self.assertEqual((c["status"], c["by"]), ("FAIL", 1))

    def test_another_release_is_stale(self):
        c, _ = self._read(self._current(), self._waivers(spec=self._spec(release="0.2.0")))
        self.assertEqual((c["status"], c["waivers"][0]["verdict"]), ("FAIL", "stale"))
        self.assertIn("granted for 0.2.0, this is 0.3.0b1", c["misses"][-1])
        # the same 0.3.0b1 waiver, read for the next release
        c, _ = self._read(self._current(), release="0.3.0b2")
        self.assertEqual((c["status"], c["waivers"][0]["verdict"]), ("FAIL", "stale"))

    def test_another_reading_is_not_like_for_like(self):
        # amendment 4 (a): sweeps read differently are not compared at all, so
        # no waiver is judged
        c, _ = self._read(self._current(), rescored={"scorer": "wp36"})
        self.assertEqual((c["status"], c["waivers"]), ("UNMEASURED", []))
        self.assertIn("mixed reading", c["detail"])
        self.assertFalse(c["waiver_file"]["evaluated"])
        # both sides read wp29, the waiver names another reading: stale
        c, _ = self._read(self._current(), self._waivers(spec=self._spec(reading="wp36")),
                          rescored={"scorer": "wp29"})
        self.assertEqual((c["status"], c["waivers"][0]["verdict"]), ("FAIL", "stale"))
        self.assertIn("names the wp36 reading, the accepted sweep is read wp29",
                      c["misses"][-1])

    def test_an_unused_waiver_is_a_note_not_a_failure(self):
        c, _ = self._read(self._current(dy=21.0))
        self.assertEqual(c["status"], "PASS")
        self.assertEqual((c["waivers"][0]["verdict"], c["waivers"][0]["blocking"]),
                         ("unused", False))
        self.assertTrue(any(m.startswith("(note) waiver unused, delete it: paper dy_p50")
                            for m in c["misses"]))

    def test_a_promised_document_is_refused(self):
        c, _ = self._read(self._current(), self._waivers(doc="short.pdf"))
        self.assertEqual(c["status"], "FAIL")
        self.assertEqual(c["waivers"][0]["verdict"], "refused")
        self.assertIn("short is a promised document", c["misses"][-1])

    def test_an_unbounded_waiver_is_refused(self):
        for spec in (self._spec(ceiling=None), dict(self._spec(), ceiling=None)):
            c, _ = self._read(self._current(), self._waivers(spec=spec))
            self.assertEqual((c["status"], c["waivers"][0]["verdict"]), ("FAIL", "refused"))
            self.assertIn("unbounded", c["misses"][-1])
            self.assertIn("paper dy_p50 20 -> 23 (tolerance 2)", c["misses"])

    def test_malformed_entries_and_files_are_refused(self):
        bad = [self._spec(decided_by=None),                      # unattributed
               self._spec(decided_on="yesterday"),
               self._spec(accepted_sweep={"name": "accepted-x.sweep.json"}),
               self._spec(ceiling=22.0),                         # does not admit 23
               self._spec(ceiling=19.0),                         # relaxes nothing
               dict(self._spec(), floor=10.0)]                   # wrong kind of bound
        for spec in bad:
            c, _ = self._read(self._current(), self._waivers(spec=spec))
            self.assertEqual((c["status"], c["waivers"][0]["verdict"]), ("FAIL", "refused"),
                             spec)
        c, _ = self._read(self._current(), self._waivers(raw={"schema": "nope"}))
        self.assertEqual((c["status"], c["by"]), ("FAIL", 1))
        self.assertIn("waiver file refused", c["misses"][-1])

    def test_main_carries_the_verdicts_into_the_json(self):
        cur = self._sweep("cur.sweep.json", self._current())
        out = os.path.join(self.dir, "res.json")
        with mock.patch("sys.stdout", new=io.StringIO()) as printed, \
                mock.patch.object(B, "corpus", return_value=DOCS):
            B.main(["--product", cur, "--accepted", self.acc, "--json", out,
                    "--waivers", self._waivers(), "--runs", os.path.join(self.dir, "none")])
        with open(out, encoding="utf-8") as fh:
            res = json.load(fh)
        c = {c["key"]: c for c in res["criteria"]}["regression"]
        self.assertEqual(res["release"], "0.3.0b1")
        self.assertEqual([(v["document"], v["metric"], v["verdict"]) for v in c["waivers"]],
                         [("paper.pdf", "dy_p50", "waived")])
        self.assertEqual(c["waiver_file"]["entries"], 1)
        self.assertIn("1 criterion-8 waiver(s) for release 0.3.0b1", printed.getvalue())

    def test_the_committed_waiver_file(self):
        w = B.load_waivers(B.WAIVERS)
        self.assertIsNone(w["error"])
        import gate
        docs = B.corpus()
        for doc, metric, spec in w["entries"]:
            self.assertIsNone(B._waiver_refusal(doc, metric, spec, docs, gate.METRICS),
                              (doc, metric))
            self.assertEqual(spec["release"], B.RELEASE)


class Amendment4(unittest.TestCase):
    """Amendment 4 (owner-delegated, 2026-10-10): a dy_p50 flag is not a
    regression when within2pt rose by more than 0.05, within5pt fell by no
    more than 0.05 and dy_p50 rose by at most max(3pt, 30% of the accepted
    value), in the same reading. The shapes are the measured ones."""

    Y43 = ((8.79, 0.0715, 0.1860), (10.64, 0.1238, 0.1846))     # wp39-A -> wp39-C
    Y33 = ((0.35, 0.1432, 0.2812), (1.89, 0.4111, 0.7449))      # wp21-base -> wp34-g10
    Y55 = ((15.56, 0.0184, 0.0829), (17.26, 0.0829, 0.0876))    # wp39-A -> wp39-C

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _sweep(self, name, rows, **extra):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict({"schema": "exactdoc.quality-sweep.v1", "profile": PROD,
                            "corpus": "both", "documents": rows}, **extra), fh)
        return path

    def _rows(self, shape, **kw):
        dy, w2, w5 = shape
        return [_row("short.pdf", 3, 3), _row("short2.pdf", 2, 2), _row("long.pdf", 50, 50),
                _row("paper.pdf", 8, 8, dy=dy, within2pt=w2, within5pt=w5, **kw)]

    def _read(self, before, after, waivers=None, acc_extra=None, cur_extra=None, **kw):
        acc = self._sweep("acc.sweep.json", self._rows(before), **(acc_extra or {}))
        cur = self._sweep("cur.sweep.json", self._rows(after, **kw), **(cur_extra or {}))
        res = B.evaluate(DOCS, {"product": (cur, B.load_sweep(cur))},
                         {"lo": None, "word": None, "docs": None}, None,
                         accepted=(acc, B.load_sweep(acc)), waivers=waivers)
        return {c["key"]: c for c in res["criteria"]}["regression"], res

    def test_the_y43_shape_is_exempt_and_named(self):
        c, res = self._read(*self.Y43)
        self.assertEqual(c["status"], "PASS")
        (e,) = c["exempted"]
        self.assertEqual((e["document"], e["cap"], e["within2pt_delta"], e["within5pt_delta"]),
                         ("paper.pdf", 3.0, 0.0523, -0.0014))
        self.assertIn("(exempt, amendment 4) paper dy_p50 8.79 -> 10.64 (+1.85, cap 3.00pt = "
                      "max(3pt, 30% of 8.79)); within2pt 0.0715 -> 0.1238 (+0.0523); "
                      "within5pt 0.1860 -> 0.1846 (-0.0014)", c["misses"])
        self.assertIn(" 8 PASS (1 exempt, amendment 4)", B.render(res, []))
        self.assertEqual(B.BAR["c8_dy_cap_pt"], 3.0)
        self.assertEqual(B.BAR["c8_dy_cap_frac"], 0.30)

    def test_the_reverse_y18_shape_is_flagged(self):
        # within2pt up 0.12, but within5pt down 0.125: placement got worse
        c, _ = self._read((3.20, 0.0083, 0.3366), (4.51, 0.1301, 0.2116))
        self.assertEqual((c["status"], c["exempted"]), ("FAIL", []))
        self.assertIn("paper dy_p50 3.2 -> 4.51 (tolerance 0.5)", c["misses"])

    def test_a_real_gain_on_a_small_drift_needs_the_3pt_floor(self):
        (dy0, _, _), (dy1, _, _) = self.Y33
        self.assertGreater(dy1 - dy0, 0.30 * dy0)          # 30% alone would flag it
        c, _ = self._read(*self.Y33)
        self.assertEqual(c["status"], "PASS")
        self.assertEqual(c["exempted"][0]["cap"], 3.0)

    def test_the_cap_is_proportional_and_binding(self):
        before, (_, w2, w5) = self.Y55
        cap = 0.30 * before[0]                              # 4.668
        c, _ = self._read(before, (before[0] + cap - 0.01, w2, w5))
        self.assertEqual((c["status"], round(c["exempted"][0]["cap"], 3)), ("PASS", 4.668))
        c, _ = self._read(before, (before[0] + cap + 0.01, w2, w5))
        self.assertEqual((c["status"], c["exempted"]), ("FAIL", []))

    def test_a_row_without_within5pt_gets_no_exemption(self):
        before, after = self.Y43
        acc = self._rows(before)
        cur = self._rows(after)
        del cur[-1]["within5pt"]
        a = self._sweep("acc.sweep.json", acc)
        p = self._sweep("cur.sweep.json", cur)
        res = B.evaluate(DOCS, {"product": (p, B.load_sweep(p))},
                         {"lo": None, "word": None, "docs": None}, None,
                         accepted=(a, B.load_sweep(a)))
        c = {c["key"]: c for c in res["criteria"]}["regression"]
        self.assertEqual((c["status"], c["exempted"]), ("FAIL", []))

    def test_every_other_metric_is_judged_as_before(self):
        c, _ = self._read(*self.Y43, wr=0.90, doc_recall=0.99)
        self.assertEqual((c["status"], c["by"]), ("FAIL", 1))
        self.assertEqual(len(c["exempted"]), 1)
        self.assertEqual([m for m in c["misses"] if not m.startswith("(")],
                         ["paper word_recall 0.99 -> 0.9 (tolerance 0.02)"])

    def test_a_mixed_reading_is_unmeasured(self):
        c, res = self._read(*self.Y43, acc_extra={"rescored": {"scorer": "wp29"}},
                            cur_extra={"rescored": {"scorer": "wp36"}})
        self.assertEqual(c["status"], "UNMEASURED")
        self.assertIn("mixed reading", c["detail"])
        self.assertEqual(c["exempted"], [])
        # the same reading on both sides, or a sweep scored as it ran: compared
        for cur_extra in ({"rescored": {"scorer": "wp29"}}, {}):
            c, _ = self._read(*self.Y43, acc_extra={"rescored": {"scorer": "wp29"}},
                              cur_extra=cur_extra)
            self.assertEqual(c["status"], "PASS", cur_extra)
            self.assertEqual(c["readings"]["accepted"], "wp29")

    def test_a_document_is_judged_by_the_rule_or_its_waiver_never_both(self):
        before, after = self.Y43
        acc = self._sweep("acc.sweep.json", self._rows(before))
        with open(acc, "rb") as fh:
            import hashlib
            sha = hashlib.sha256(fh.read()).hexdigest()
        spec = {"ceiling": 12.0, "release": "0.3.0b1",
                "accepted_sweep": {"name": "acc.sweep.json", "sha256": sha},
                "reading": "wp29",
                "measured": {"accepted": 8.79, "current": 10.64, "sweep": "cur.sweep.json"},
                "decided_by": "the owner", "decided_on": "2026-10-10",
                "evidence": "x", "conditions": "y"}
        path = os.path.join(self.dir, "w.json")
        for name, verdict, status in (("acc.sweep.json", "waived", "PASS"),
                                      ("other.sweep.json", "stale", "FAIL")):
            spec["accepted_sweep"]["name"] = name
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"schema": B.WAIVERS_SCHEMA,
                           "regression": {"paper.pdf": {"dy_p50": spec}}}, fh)
            c, _ = self._read(before, after, waivers=B.load_waivers(path))
            # the rule would exempt this shape; the waiver judges it instead
            self.assertEqual(c["exempted"], [], name)
            self.assertEqual((c["waivers"][0]["verdict"], c["status"]), (verdict, status))
            if verdict == "stale":
                self.assertIn("paper dy_p50 8.79 -> 10.64 (tolerance 0.879)", c["misses"])


if __name__ == "__main__":
    unittest.main()
