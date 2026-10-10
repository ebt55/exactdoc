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


if __name__ == "__main__":
    unittest.main()
