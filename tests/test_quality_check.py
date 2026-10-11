"""The contributor quality check's verdict (testkit/quality_check.py, WP54).

Everything here is synthetic: side records shaped like what `collect` writes,
fed to `compare`, and a fake runall batch with hand-made DOCX packages fed to
`collect`. No LibreOffice, no container, no corpus. The live run (the same
commit twice, then a base-vs-head pair) is scripts/dev/quality_check.sh.

    python -m unittest tests.test_quality_check
"""
import contextlib
import copy
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import quality_check as Q  # noqa: E402

READING = {"scorer": "wp42", "source": "ca563181d6ad"}
FP = "9cb0bc17" + "0" * 56


def row(doc, **kw):
    r = {"document": doc, "src_pages": 2, "out_pages": 2, "word_recall": 0.95,
         "doc_recall": 0.99, "live_text_cov": 1.0, "within2pt": 0.60,
         "within5pt": 0.90, "dy_p50": 1.0, "convert_s": 3.0}
    r.update(kw)
    return r


def side(rows=None, raw=None, binding="bound", failures=(), reading=READING, fp=FP,
         docx=None, sweep=None, name="x"):
    rows = rows if rows is not None else [row("a.pdf"), row("b.pdf")]
    raw = raw if raw is not None else copy.deepcopy(rows)

    def lane(rs, fails):
        fl = [{"kind": "binding", "document": None, "detail": "recorded under another"}] \
            if binding == "refused" else []
        fl += list(fails)
        return {"verdict": {"ok": not fl, "failures": fl,
                            "baseline_binding": {"mode": binding}},
                "rows": copy.deepcopy(rs)}
    s = {"schema": Q.SIDE_SCHEMA, "side": name, "ref": name, "commit": name * 4,
         "gate": {"lanes": {"raw": lane(raw, ()), "product": lane(rows, failures)},
                  "provenance": {"environment_fingerprint": fp, "canonical": binding == "bound",
                                 "reading": reading, "image_ref": "img"}},
         "sweep": sweep, "docx": docx or {}}
    return s


def digests(word="w", content="c"):
    return {"word_xml": word, "content": content}


class Verdicts(unittest.TestCase):

    def verdict(self, base, head, **kw):
        report, _ = Q.compare(base, head, **kw)
        return report

    def test_identical_sides_are_neutral(self):
        r = self.verdict(side(), side())
        self.assertEqual(r["verdict"], "NEUTRAL")
        self.assertEqual(r["exit_code"], 3)
        self.assertEqual(r["regressions"], [])

    def test_worse_beyond_tolerance_regresses(self):
        head = side([row("a.pdf", word_recall=0.90), row("b.pdf")])  # tol 0.02
        r = self.verdict(side(), head)
        self.assertEqual(r["verdict"], "REGRESSES")
        self.assertEqual(r["exit_code"], 1)
        self.assertIn("a.pdf", r["lanes"]["gate:product"]["worse"])
        self.assertTrue(any("word_recall" in x for x in r["regressions"]))

    def test_inside_tolerance_is_same(self):
        head = side([row("a.pdf", word_recall=0.935, within2pt=0.56), row("b.pdf")])
        r = self.verdict(side(), head)
        self.assertEqual(r["verdict"], "NEUTRAL")

    def test_better_beyond_tolerance_lifts(self):
        head = side([row("a.pdf", within2pt=0.70), row("b.pdf")])     # tol 0.05
        r = self.verdict(side(), head)
        self.assertEqual(r["verdict"], "LIFTS")
        self.assertEqual(r["exit_code"], 0)
        self.assertIn("a.pdf", r["lanes"]["gate:product"]["better"])

    def test_one_worse_outweighs_any_number_better(self):
        head = side([row("a.pdf", within2pt=0.9), row("b.pdf", out_pages=3)])
        r = self.verdict(side(), head)
        self.assertEqual(r["verdict"], "REGRESSES")

    def test_raw_lane_is_judged_too(self):
        head = side(raw=[row("a.pdf", doc_recall=0.90), row("b.pdf")])
        self.assertEqual(self.verdict(side(), head)["verdict"], "REGRESSES")

    def test_new_crash_regresses_and_a_fixed_crash_lifts(self):
        crash = side([{"document": "a.pdf", "error": "ValueError: boom"}, row("b.pdf")])
        self.assertEqual(self.verdict(side(), crash)["verdict"], "REGRESSES")
        self.assertEqual(self.verdict(crash, side())["verdict"], "LIFTS")

    def test_infrastructure_failure_is_unmeasured_not_a_verdict(self):
        infra = side([{"document": "a.pdf", "error": "evaluate RuntimeError: soffice"},
                      row("b.pdf")])
        r = self.verdict(side(), infra)
        self.assertEqual(r["verdict"], "UNMEASURED")
        self.assertEqual(r["exit_code"], 2)

    def test_amendment_4_dy_rise_with_more_words_within_2pt_is_not_worse(self):
        # dy 1.0 -> 3.5 (> tol 0.5, < cap 3pt); within2pt +0.10; within5pt held
        head = side([row("a.pdf", dy_p50=3.5, within2pt=0.70), row("b.pdf")])
        r = self.verdict(side(), head)
        self.assertEqual(r["verdict"], "LIFTS")
        self.assertTrue(r["lanes"]["gate:product"]["exempt_amendment_4"])

    def test_unchanged_docx_cannot_be_better_or_worse(self):
        d = {"gate:product": {"a.pdf": digests(), "b.pdf": digests()},
             "gate:raw": {"a.pdf": digests(), "b.pdf": digests()}}
        head = side([row("a.pdf", word_recall=0.80), row("b.pdf")], docx=d)
        r = self.verdict(side(docx=d), head)
        self.assertEqual(r["verdict"], "NEUTRAL")
        self.assertIn("a.pdf", r["lanes"]["gate:product"]["noise"])
        self.assertEqual(r["lanes"]["gate:product"]["docx_changed"], [])

    def test_reading_mismatch_is_unmeasured(self):
        head = side([row("a.pdf", within2pt=0.9), row("b.pdf")],
                    reading={"scorer": "wp43", "source": "x"})
        r = self.verdict(side(), head)
        self.assertEqual(r["verdict"], "UNMEASURED")
        self.assertTrue(any("reading" in p for p in r["problems"]))

    def test_reading_code_change_under_one_name_warns(self):
        head = side(reading={"scorer": "wp42", "source": "different"})
        r = self.verdict(side(), head)
        self.assertEqual(r["verdict"], "NEUTRAL")
        self.assertTrue(r["warnings"])

    def test_environment_mismatch_is_unmeasured(self):
        r = self.verdict(side(), side(fp="1" * 64))
        self.assertEqual(r["verdict"], "UNMEASURED")

    LOCK = ('[[package]]\nname = "exactdoc"\nversion = "%s"\n\n'
            '[[package]]\nname = "lxml"\nversion = "%s"\n')

    def test_dependency_change_is_unmeasured_and_named(self):
        r = self.verdict(side(), side(), changed=["uv.lock", "exactdoc/infer.py"],
                         locks=(self.LOCK % ("0.2.0a1", "6.1.1"), self.LOCK % ("0.2.0a1", "6.1.2")))
        self.assertEqual(r["verdict"], "UNMEASURED")
        self.assertEqual(r["contract_changes"], ["uv.lock"])

    def test_a_version_bump_in_uv_lock_is_not_a_dependency_change(self):
        r = self.verdict(side(), side(), changed=["uv.lock"],
                         locks=(self.LOCK % ("1.0.0", "6.1.1"), self.LOCK % ("0.2.0a1", "6.1.1")))
        self.assertEqual(r["verdict"], "NEUTRAL")
        self.assertEqual(r["contract_changes"], ["uv.lock"])

    def test_contract_paths_are_named(self):
        r = self.verdict(side(), side(), changed=[
            "testkit/gate_baseline.json", "testkit/fixtures/c1_whitepaper.pdf",
            "exactdoc/docxout.py", "tests/test_x.py"])
        self.assertEqual(r["contract_changes"], ["testkit/fixtures/c1_whitepaper.pdf",
                                                 "testkit/gate_baseline.json"])
        self.assertEqual(r["verdict"], "NEUTRAL")

    def test_missing_lane_is_unmeasured(self):
        head = side()
        head["gate"]["lanes"]["raw"] = None
        self.assertEqual(self.verdict(side(), head)["verdict"], "UNMEASURED")

    def test_document_missing_on_head_is_unmeasured(self):
        head = side([row("a.pdf")], raw=[row("a.pdf")])
        self.assertEqual(self.verdict(side(), head)["verdict"], "UNMEASURED")


class Gate(unittest.TestCase):

    def test_canonical_head_gate_failure_regresses(self):
        fail = [{"kind": "threshold", "document": "a.pdf", "detail": "word_recall 0.8 misses 0.9"}]
        r, _ = Q.compare(side(), side(failures=fail))
        self.assertTrue(r["gate_canonical"])
        self.assertEqual(r["verdict"], "REGRESSES")
        self.assertFalse(r["gate"]["product"]["head_ok"])

    def test_off_canonical_the_binding_finding_is_ignored(self):
        r, _ = Q.compare(side(binding="refused"), side(binding="refused"))
        self.assertFalse(r["gate_canonical"])
        self.assertEqual(r["verdict"], "NEUTRAL")
        self.assertEqual(r["gate"]["product"]["new_findings"], [])

    def test_off_canonical_only_new_findings_count(self):
        old = [{"kind": "regression", "document": "a.pdf",
                "detail": "dy_p50 1 -> 2.1 (recorded 1, tolerance 0.5)"}]
        moved = [{"kind": "regression", "document": "a.pdf",
                  "detail": "dy_p50 1 -> 2.3 (recorded 1, tolerance 0.5)"}]
        r, _ = Q.compare(side(binding="refused", failures=old),
                         side(binding="refused", failures=moved))
        self.assertEqual(r["verdict"], "NEUTRAL")         # same finding, other numbers
        new = moved + [{"kind": "regression", "document": "b.pdf",
                        "detail": "within2pt 0.6 -> 0.4 (recorded 0.6, tolerance 0.05)"}]
        r, _ = Q.compare(side(binding="refused", failures=old),
                         side(binding="refused", failures=new))
        self.assertEqual(r["verdict"], "REGRESSES")
        self.assertEqual(len(r["gate"]["product"]["new_findings"]), 1)

    def test_finding_key_ignores_numbers(self):
        a = {"kind": "regression", "document": None,
             "detail": "aggregate mean_within2pt 0.73 -> 0.70 (tolerance 0.02)"}
        b = dict(a, detail="aggregate mean_within2pt 0.73 -> 0.69 (tolerance 0.02)")
        self.assertEqual(Q.finding_key(a), Q.finding_key(b))
        self.assertEqual(Q.finding_key(a)[2], "aggregate mean_within2pt")


class Determinism(unittest.TestCase):

    def test_same_bytes_same_numbers_is_deterministic(self):
        d = {"gate:product": {"a.pdf": digests(), "b.pdf": digests()},
             "gate:raw": {"a.pdf": digests(), "b.pdf": digests()}}
        r, _ = Q.compare(side(docx=d), side(docx=d), repeat=True)
        self.assertEqual(r["verdict"], "DETERMINISTIC")
        self.assertEqual(r["exit_code"], 0)
        self.assertEqual(r["determinism"]["docx_word_xml_identical"], "4/4")

    def test_timing_never_breaks_determinism(self):
        d = {"gate:product": {"a.pdf": digests(), "b.pdf": digests()},
             "gate:raw": {"a.pdf": digests(), "b.pdf": digests()}}
        slow = side([row("a.pdf", convert_s=99.0), row("b.pdf")], docx=d)
        r, _ = Q.compare(side(docx=d), slow, repeat=True)
        self.assertEqual(r["verdict"], "DETERMINISTIC")

    def test_different_bytes_are_nondeterministic(self):
        d1 = {"gate:product": {"a.pdf": digests(), "b.pdf": digests()},
              "gate:raw": {"a.pdf": digests(), "b.pdf": digests()}}
        d2 = copy.deepcopy(d1)
        d2["gate:product"]["a.pdf"] = digests("w2", "c2")
        r, _ = Q.compare(side(docx=d1), side(docx=d2), repeat=True)
        self.assertEqual(r["verdict"], "NONDETERMINISTIC")
        self.assertEqual(r["exit_code"], 4)
        self.assertTrue(any("a.pdf word/*.xml" in x for x in r["determinism"]["differing"]))

    def test_moved_number_on_identical_bytes_is_nondeterministic(self):
        d = {"gate:product": {"a.pdf": digests(), "b.pdf": digests()},
             "gate:raw": {"a.pdf": digests(), "b.pdf": digests()}}
        r, _ = Q.compare(side(docx=d), side([row("a.pdf", within2pt=0.6001), row("b.pdf")],
                                              docx=d), repeat=True)
        self.assertEqual(r["verdict"], "NONDETERMINISTIC")
        self.assertTrue(any("within2pt" in x for x in r["determinism"]["differing"]))


def _docx(path, body, stamp):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", body)
        z.writestr("docProps/core.xml", "<created>%s</created>" % stamp)


class Collect(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qc_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def batch(self, name, body, stamp):
        b = os.path.join(self.tmp, name)
        for lane in Q.LANES:
            d = os.path.join(b, "lane_" + lane)
            os.makedirs(d)
            res = [dict(row("a.pdf"), src="a.pdf", renderer="libreoffice",
                        pages=[{"page": 1}], trace="t"),
                   {"src": "b.pdf", "convert_error": "ValueError: boom"}]
            for r in res:
                r.pop("document", None)
            with open(os.path.join(d, "results.json"), "w") as f:
                json.dump(res, f)
            with open(os.path.join(d, "verdict.json"), "w") as f:
                json.dump({"lane": lane, "ok": True, "failures": [],
                           "baseline_binding": {"mode": "bound"}}, f)
            _docx(os.path.join(d, "a.docx"), body, stamp)
        with open(os.path.join(b, "provenance.json"), "w") as f:
            json.dump({"environment_fingerprint": FP, "reading": READING}, f)
        return b

    def test_docprops_do_not_count_and_word_xml_does(self):
        p1, p2, p3 = (os.path.join(self.tmp, n) for n in ("1.docx", "2.docx", "3.docx"))
        _docx(p1, "<w:body>x</w:body>", "2026-10-11T10:00")
        _docx(p2, "<w:body>x</w:body>", "2026-10-11T11:00")
        _docx(p3, "<w:body>y</w:body>", "2026-10-11T10:00")
        self.assertEqual(Q.docx_digests(p1), Q.docx_digests(p2))
        self.assertNotEqual(Q.docx_digests(p1)["word_xml"], Q.docx_digests(p3)["word_xml"])
        self.assertIsNone(Q.docx_digests(os.path.join(self.tmp, "absent.docx")))

    def test_collect_then_compare_end_to_end(self):
        base = Q.collect("base", self.batch("b", "<x/>", "t1"), out=os.path.join(self.tmp, "ob"),
                         ref="main", commit="a" * 40, steps={"gate": 0})
        head = Q.collect("head", self.batch("h", "<x/>", "t2"), out=os.path.join(self.tmp, "oh"),
                         ref="HEAD", commit="b" * 40)
        prod = base["gate"]["lanes"]["product"]["rows"]
        self.assertEqual(prod[0]["document"], "a.pdf")
        self.assertNotIn("pages", prod[0])
        self.assertNotIn("trace", prod[0])
        self.assertTrue(prod[1]["error"].startswith("ValueError"))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "ob", "side.json")))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "ob", "docx", "gate-raw", "a.docx")))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = Q.main(["compare", os.path.join(self.tmp, "ob"), os.path.join(self.tmp, "oh"),
                         "--json", os.path.join(self.tmp, "r.json"), "--repeat"])
        self.assertIn("VERDICT DETERMINISTIC (exit 0)", out.getvalue())
        with open(os.path.join(self.tmp, "r.json")) as f:
            rep = json.load(f)
        # a.docx identical but for docProps; b.pdf crashed on both sides alike
        self.assertEqual(rep["verdict"], "DETERMINISTIC", rep["determinism"])
        self.assertEqual(rc, 0)

    def test_collect_reads_a_sweep(self):
        sw = os.path.join(self.tmp, "sweep")
        os.makedirs(os.path.join(sw, "product", "x01"))
        _docx(os.path.join(sw, "product", "x01", "x01.docx"), "<x/>", "t")
        payload = os.path.join(self.tmp, "sweep.json")
        with open(payload, "w") as f:
            json.dump({"profile": "p", "corpus": "expansion", "reading": READING,
                       "documents": [row("x01.pdf", worst_pages_dy90=[[1, 2.0]])]}, f)
        rec = Q.collect("head", self.batch("h", "<x/>", "t"), sweep=payload, sweep_dir=sw)
        self.assertEqual(len(rec["sweep"]["rows"]), 1)
        self.assertIn("x01.pdf", rec["docx"]["sweep:product"])
        self.assertIn("sweep:product", Q.lane_rows(rec))


class Script(unittest.TestCase):
    SH = os.path.join(ROOT, "scripts", "dev", "quality_check.sh")

    def test_the_container_gets_every_module_the_comparison_imports(self):
        with open(self.SH, encoding="utf-8") as f:
            sh = f.read()
        m = re.search(r'tar -C "\$ROOT/testkit" -cf - ([^|]+)\|', sh)
        self.assertIsNotNone(m)
        shipped = set(m.group(1).split())
        with open(os.path.join(ROOT, "testkit", "quality_check.py"), encoding="utf-8") as f:
            src = f.read()
        local = {n + ".py" for n in re.findall(r"^import (\w+)", src, re.M)
                 if os.path.exists(os.path.join(ROOT, "testkit", n + ".py"))}
        self.assertTrue(local <= shipped, local - shipped)
        self.assertIn("quality_check.py", shipped)

    def test_the_published_image_is_the_one_ci_gates_in(self):
        with open(self.SH, encoding="utf-8") as f:
            pub = re.search(r"^PUBLISHED=(\S+)$", f.read(), re.M).group(1)
        with open(os.path.join(ROOT, ".github", "workflows", "gate.yml"),
                  encoding="utf-8") as f:
            ci = re.search(r"^\s+image:\s*(\S+)\s*$", f.read(), re.M).group(1)
        self.assertEqual(pub, ci)

    def test_the_gate_is_never_run_with_the_stale_baseline_allowance(self):
        with open(self.SH, encoding="utf-8") as f:
            code = [l for l in f if not l.lstrip().startswith("#")]
        self.assertFalse(any("ALLOW_STALE_BASELINE" in l for l in code))

    # Not on Windows: `bash` there may be WSL's launcher, which fails without a
    # distribution installed. The Linux and macOS runs check it.
    @unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "no POSIX bash")
    def test_shell_syntax(self):
        p = subprocess.run(["bash", "-n", "scripts/dev/quality_check.sh"], cwd=ROOT,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
