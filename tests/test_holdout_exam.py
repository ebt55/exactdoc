"""scripts/dev/holdout_exam.py: the release rule R1-R5 (beta-bar.md, amendment 6).

Synthetic rows only. No holdout result is read here, nor any sealed set's
directory: every manifest, sweep and Word row below is made up in the test, so
the rule's reading is pinned before an exam is run, not fitted to its outcome.
The only real file read is holdout-3's registration, committed before its set
was opened, whose hash the exam must use.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "holdout_exam", os.path.join(ROOT, "scripts", "dev", "holdout_exam.py"))
X = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(X)

EXIT_MAP = {"InteractiveFormError": ("interactive-form", 19),
            "OcrRequiredError": ("ocr-required", 17),
            "ExactdocError": ("error", 1)}
COMMIT = "c0ffee"
# holdout-3's sealed manifest, as registered on 2026-10-12 before any conversion
# (docs/evidence/holdout3-registration-2026-10-12.json); 0.3.0b2's exam.
HOLDOUT3_SHA256 = "07d622997a13e00251786cf812801d3a30b5086b1b0980fc838e3d32ad315475"
HOLDOUT3_DOCUMENTS = 41
PROFILES = ("prod/id", "raw/id")


def man(**docs):
    """man(a=(pages, promised), ...) -> {file: spec}"""
    return {k + ".pdf": {"file": k + ".pdf", "pages": p, X.PROMISE_FIELD: pr,
                         "design_class": "ordinary-word", "_key": k}
            for k, (p, pr) in docs.items()}


def lo(doc, src, out, wr=0.99, cr=0.99, **kw):
    return dict({"document": doc, "src_pages": src, "out_pages": out,
                 "word_recall": wr, "char_recall": cr, "page_ratio": out / src}, **kw)


def wd(doc, src, out, wr=0.99, cr=0.99, **kw):
    return dict({"doc": doc, "flavour": "product", "opened": True, "repair_prompt": False,
                 "src_pages": src, "out_pages": out, "word_recall": wr, "char_recall": cr}, **kw)


def sweep(rows, profile="prod/id", commit=COMMIT, dirty=False):
    return {"profile": profile, "provenance": {"git_commit": commit, "git_dirty": dirty},
            "documents": rows}


def ev(m, prows, wrows, **kw):
    kw.setdefault("exit_map", EXIT_MAP)
    kw.setdefault("expect_commit", COMMIT)
    kw.setdefault("profiles", PROFILES)
    return X.evaluate(m, sweep(prows), {r["doc"]: r for r in wrows}, **kw)


def clean(n_short=5, n_long=2, short_pages=4, long_pages=40):
    """A manifest of promised documents that all convert perfectly."""
    docs = {}
    for i in range(n_short):
        docs["s%02d" % i] = (short_pages, True)
    for i in range(n_long):
        docs["l%02d" % i] = (long_pages, True)
    m = man(**docs)
    prows = [lo(d, s["pages"], s["pages"]) for d, s in sorted(m.items())]
    wrows = [wd(d, s["pages"], s["pages"]) for d, s in sorted(m.items())]
    return m, prows, wrows


def replace(rows, key, doc, new):
    return [new if r[key] == doc else r for r in rows]


class Validity(unittest.TestCase):
    def test_clean_run_announces(self):
        m, p, w = clean()
        res = ev(m, p, w)
        self.assertTrue(res["R1"]["pass"] and res["R2"]["pass"] and res["R3"]["pass"])
        self.assertTrue(res["announce"])
        self.assertIn("announce: yes", X.render_text(res))

    def test_other_commit_is_invalid(self):
        m, p, w = clean()
        with self.assertRaises(X.ExamInvalid):
            X.evaluate(m, sweep(p, commit="other"), {r["doc"]: r for r in w},
                       exit_map=EXIT_MAP, expect_commit=COMMIT, profiles=PROFILES)

    def test_dirty_tree_is_invalid(self):
        m, p, w = clean()
        with self.assertRaises(X.ExamInvalid):
            X.evaluate(m, sweep(p, dirty=True), {r["doc"]: r for r in w},
                       exit_map=EXIT_MAP, expect_commit=COMMIT, profiles=PROFILES)

    def test_raw_profile_as_product_is_invalid(self):
        m, p, w = clean()
        with self.assertRaises(X.ExamInvalid):
            X.evaluate(m, sweep(p, profile="raw/id"), {r["doc"]: r for r in w},
                       exit_map=EXIT_MAP, expect_commit=COMMIT, profiles=PROFILES)

    def test_missing_or_extra_sweep_rows_are_invalid(self):
        m, p, w = clean()
        with self.assertRaises(X.ExamInvalid):
            ev(m, p[1:], w)
        with self.assertRaises(X.ExamInvalid):
            ev(m, p + [lo("zz.pdf", 1, 1)], w)

    def test_unfinished_word_lane_is_invalid(self):
        m, p, w = clean()
        with self.assertRaises(X.ExamInvalid):
            ev(m, p, w[:-1])

    def test_word_rows_of_another_flavour_are_invalid(self):
        m, p, w = clean()
        w[0]["flavour"] = "raw"
        with self.assertRaises(X.ExamInvalid):
            ev(m, p, w)

    def test_manifest_hash_and_promise_field(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "m.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"documents": {"a": {"file": "a.pdf", "pages": 3,
                                           X.PROMISE_FIELD: True}}}, fh)
        _, docs = X.load_manifest(path, X.sha256(path))
        self.assertEqual(list(docs), ["a.pdf"])
        with self.assertRaises(X.ExamInvalid):
            X.load_manifest(path, X.SEALED_SHA256)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"documents": {"a": {"file": "a.pdf", "pages": 3,
                                           "promised_a_current_bar": True}}}, fh)
        with self.assertRaises(X.ExamInvalid):        # only the NARROWED field is read
            X.load_manifest(path, X.sha256(path))
        with self.assertRaises(X.ExamInvalid):        # nor holdout-3's sealed hash
            X.load_manifest(path, HOLDOUT3_SHA256)

    def test_holdout3_sha_is_pinned_and_read_from_its_registration(self):
        ex = X.exam("holdout3")
        self.assertEqual((ex["sha256"], ex["documents"]), (HOLDOUT3_SHA256, HOLDOUT3_DOCUMENTS))
        with open(os.path.join(ROOT, ex["registration"]), encoding="utf-8") as fh:
            reg = json.load(fh)
        self.assertEqual((reg["manifest_sha256"], reg["documents"]),
                         (HOLDOUT3_SHA256, HOLDOUT3_DOCUMENTS))
        self.assertEqual(X.DEFAULT_EXAM, "holdout3")
        self.assertEqual((X.exam("holdout2")["sha256"], X.exam("holdout2")["documents"]),
                         (X.SEALED_SHA256, 32))
        with self.assertRaises(X.ExamInvalid):
            X.exam("holdout9")

    def test_a_registration_without_a_hash_refuses(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        reg = os.path.join(d, X.EXAMS["holdout3"]["registration"])
        os.makedirs(os.path.dirname(reg))
        with open(reg, "w", encoding="utf-8") as fh:
            json.dump({"documents": 41}, fh)
        with self.assertRaises(X.ExamInvalid):
            X.exam("holdout3", root=d)
        os.remove(reg)
        with self.assertRaises(X.ExamInvalid):
            X.exam("holdout3", root=d)

    def test_verdict_cli_exit_codes(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        mp = os.path.join(d, "m.json")
        with open(mp, "w", encoding="utf-8") as fh:
            json.dump({"documents": {"a": {"file": "a.pdf", "pages": 3,
                                           X.PROMISE_FIELD: True}}}, fh)
        pp, wp = os.path.join(d, "p.json"), os.path.join(d, "w.jsonl")
        with open(pp, "w", encoding="utf-8") as fh:
            json.dump(sweep([lo("a.pdf", 3, 3)], profile=X.shipped_profiles()[0] or "x"), fh)
        with open(wp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(wd("a.pdf", 3, 3)) + "\n")
        args = ["verdict", "--manifest", mp, "--manifest-sha256", X.sha256(mp), "--product", pp,
                "--word", wp, "--commit", COMMIT, "--json", os.path.join(d, "o.json"),
                "--text", os.path.join(d, "o.txt")]
        out = sys.stdout
        sys.stdout = open(os.devnull, "w")
        try:
            self.assertEqual(X.main(args), 0)
            self.assertEqual(X.main(args[:4] + ["0" * 64] + args[5:]), 3)
        finally:
            sys.stdout.close()
            sys.stdout = out
        with open(os.path.join(d, "o.json"), encoding="utf-8") as fh:
            self.assertFalse(json.load(fh)["valid"])


class R1(unittest.TestCase):
    def test_a_crash_fails(self):
        m, p, w = clean()
        p = replace(p, "document", "s00.pdf", {"document": "s00.pdf", "error": "KeyError: x"})
        w = replace(w, "doc", "s00.pdf", {"doc": "s00.pdf", "flavour": "product", "opened": False,
                                          "error": X.NO_DOCX + " (refused or failed upstream)"})
        res = ev(m, p, w)
        self.assertFalse(res["R1"]["pass"])
        self.assertEqual([c["doc"] for c in res["R1"]["crashes"]], ["s00.pdf"])
        self.assertEqual(res["R1"]["word_open_failures"], [])   # no DOCX: counted once
        self.assertFalse(res["announce"])

    def test_typed_refusal_passes_untyped_fails(self):
        m, p, w = clean()
        m["f.pdf"] = {"file": "f.pdf", "pages": 2, X.PROMISE_FIELD: False, "_key": "f"}
        p.append({"document": "f.pdf", "refused": "InteractiveFormError"})
        w.append({"doc": "f.pdf", "flavour": "product", "opened": False,
                  "error": X.NO_DOCX + " (refused or failed upstream)"})
        res = ev(m, p, w)
        self.assertTrue(res["R1"]["pass"])
        self.assertEqual(res["R1"]["refusals"][0]["typed_exit"], 19)
        p[-1] = {"document": "f.pdf", "refused": "ExactdocError"}      # exit 1: untyped
        self.assertFalse(ev(m, p, w)["R1"]["pass"])
        p[-1] = {"document": "f.pdf", "refused": "SomethingNew"}       # unknown class
        self.assertFalse(ev(m, p, w)["R1"]["pass"])

    def test_cli_confirmation_must_match(self):
        m, p, w = clean()
        m["f.pdf"] = {"file": "f.pdf", "pages": 2, X.PROMISE_FIELD: False, "_key": "f"}
        p.append({"document": "f.pdf", "refused": "OcrRequiredError"})
        w.append({"doc": "f.pdf", "flavour": "product", "opened": False,
                  "error": X.NO_DOCX + " (refused or failed upstream)"})
        self.assertTrue(ev(m, p, w, cli_exits={"f.pdf": {"exit": 17}})["R1"]["pass"])
        self.assertFalse(ev(m, p, w, cli_exits={"f.pdf": {"exit": 1}})["R1"]["pass"])
        self.assertFalse(ev(m, p, w, cli_exits={})["R1"]["pass"])        # not confirmed

    def test_word_repair_prompt_hang_or_no_open_fails(self):
        m, p, w = clean()
        for bad in ({"repair_prompt": True}, {"hang": True, "error": "word: timeout"},
                    {"opened": False, "error": "word: cannot open"}):
            w2 = replace(w, "doc", "l00.pdf", dict(wd("l00.pdf", 40, 40), **bad))
            res = ev(m, p, w2)
            self.assertFalse(res["R1"]["pass"], bad)
            self.assertEqual(res["R1"]["word_open_failures"][0]["doc"], "l00.pdf")

    def test_docx_missing_from_word_lane_fails(self):
        m, p, w = clean()
        w = replace(w, "doc", "s01.pdf", {"doc": "s01.pdf", "flavour": "product",
                                          "opened": False, "error": X.NO_DOCX})
        self.assertFalse(ev(m, p, w)["R1"]["pass"])

    def test_raw_crash_is_reported_not_gated(self):
        m, p, w = clean()
        raw = sweep([r if r["document"] != "s00.pdf" else {"document": "s00.pdf", "error": "x"}
                     for r in p], profile="raw/id")
        res = X.evaluate(m, sweep(p), {r["doc"]: r for r in w}, raw=raw, exit_map=EXIT_MAP,
                         expect_commit=COMMIT, profiles=PROFILES)
        self.assertTrue(res["R1"]["pass"])
        self.assertEqual(res["R1"]["raw_crashes_reported"], ["s00.pdf"])

    def test_word_scoring_error_is_not_an_open_failure(self):
        m, p, w = clean()
        w = replace(w, "doc", "l01.pdf", {"doc": "l01.pdf", "flavour": "product", "opened": True,
                                          "repair_prompt": False, "error": "score ValueError"})
        res = ev(m, p, w)
        self.assertTrue(res["R1"]["pass"])
        self.assertEqual(res["R1"]["word_scoring_errors"][0]["doc"], "l01.pdf")


class R2(unittest.TestCase):
    def test_80_percent_is_enough_75_is_not(self):
        m, p, w = clean(n_short=5)                       # 4/5 = 80%
        p = replace(p, "document", "s00.pdf", lo("s00.pdf", 4, 5))
        self.assertTrue(ev(m, p, w)["R2"]["pass"])
        m, p, w = clean(n_short=4)                       # 3/4 = 75%
        p = replace(p, "document", "s00.pdf", lo("s00.pdf", 4, 5))
        res = ev(m, p, w)
        self.assertFalse(res["R2"]["pass"])
        self.assertEqual(res["R2"]["lo"]["misses_pages"], ["s00.pdf"])

    def test_both_lanes_must_be_page_exact(self):
        m, p, w = clean(n_short=4)
        w = replace(w, "doc", "s01.pdf", wd("s01.pdf", 4, 3))
        res = ev(m, p, w)
        self.assertTrue(res["R2"]["lo"]["page_exact_ok"])
        self.assertFalse(res["R2"]["word"]["page_exact_ok"])
        self.assertFalse(res["R2"]["pass"])

    def test_word_recall_share_in_each_lane(self):
        m, p, w = clean(n_short=4)
        w = replace(w, "doc", "s02.pdf", wd("s02.pdf", 4, 4, wr=0.89))
        res = ev(m, p, w)
        self.assertFalse(res["R2"]["word"]["wr_ok"])
        self.assertFalse(res["R2"]["pass"])
        w = replace(w, "doc", "s02.pdf", wd("s02.pdf", 4, 4, wr=0.9))     # 0.9 itself passes
        self.assertTrue(ev(m, p, w)["R2"]["pass"])

    def test_refused_short_promised_is_a_miss(self):
        m, p, w = clean(n_short=4)
        p = replace(p, "document", "s03.pdf", {"document": "s03.pdf", "refused": "OcrRequiredError"})
        w = replace(w, "doc", "s03.pdf", {"doc": "s03.pdf", "flavour": "product", "opened": False,
                                          "error": X.NO_DOCX})
        res = ev(m, p, w)
        self.assertEqual(res["R2"]["lo"]["page_exact"], 3)
        self.assertFalse(res["R2"]["pass"])

    def test_unpromised_and_long_documents_do_not_count(self):
        m, p, w = clean(n_short=4, n_long=1)
        m["u.pdf"] = {"file": "u.pdf", "pages": 3, X.PROMISE_FIELD: False, "_key": "u"}
        p.append(lo("u.pdf", 3, 9, wr=0.1, cr=0.1))
        w.append(wd("u.pdf", 3, 9, wr=0.1, cr=0.1))
        p = replace(p, "document", "l00.pdf", lo("l00.pdf", 40, 41))
        res = ev(m, p, w)
        self.assertEqual(res["R2"]["n"], 4)
        self.assertTrue(res["R2"]["pass"] and res["R3"]["pass"])
        self.assertEqual(res["R3"]["unpromised_catastrophic_reported"], ["u.pdf"])

    def test_twenty_pages_is_short_twenty_one_long(self):
        m, p, w = clean(n_short=1, n_long=1, short_pages=20, long_pages=21)
        res = ev(m, p, w)
        self.assertEqual((res["counts"]["short_promised"], res["counts"]["long_promised"]), (1, 1))


class R3(unittest.TestCase):
    def test_char_recall_below_half_is_catastrophic(self):
        m, p, w = clean()
        p = replace(p, "document", "s00.pdf", lo("s00.pdf", 4, 4, cr=0.49))
        res = ev(m, p, w)
        self.assertEqual(res["R3"]["short_catastrophic"], ["s00.pdf"])
        self.assertFalse(res["R3"]["pass"])
        p = replace(p, "document", "s00.pdf", lo("s00.pdf", 4, 4, cr=0.5))
        self.assertTrue(ev(m, p, w)["R3"]["pass"])

    def test_pages_off_more_than_20_percent(self):
        m, p, w = clean(n_short=5, short_pages=10)
        p = replace(p, "document", "s00.pdf", lo("s00.pdf", 10, 12))     # exactly 20%: not
        self.assertTrue(ev(m, p, w)["R3"]["pass"])
        p = replace(p, "document", "s00.pdf", lo("s00.pdf", 10, 13))     # 30%
        self.assertFalse(ev(m, p, w)["R3"]["pass"])

    def test_either_lane_counts(self):
        m, p, w = clean()
        w = replace(w, "doc", "s01.pdf", wd("s01.pdf", 4, 6))
        res = ev(m, p, w)
        self.assertEqual(res["R3"]["by_lane"]["word"], ["s01.pdf"])
        self.assertFalse(res["R3"]["pass"])

    def test_one_long_allowed_two_not(self):
        m, p, w = clean(n_long=3)
        p = replace(p, "document", "l00.pdf", lo("l00.pdf", 40, 60))
        self.assertTrue(ev(m, p, w)["R3"]["pass"])
        p = replace(p, "document", "l01.pdf", lo("l01.pdf", 40, 40, cr=0.2))
        res = ev(m, p, w)
        self.assertEqual(res["R3"]["long_catastrophic"], ["l00.pdf", "l01.pdf"])
        self.assertFalse(res["R3"]["pass"])

    def test_no_output_is_catastrophic(self):
        m, p, w = clean()
        p = replace(p, "document", "s04.pdf", {"document": "s04.pdf", "refused": "OcrRequiredError"})
        w = replace(w, "doc", "s04.pdf", {"doc": "s04.pdf", "flavour": "product", "opened": False,
                                          "error": X.NO_DOCX})
        res = ev(m, p, w)
        self.assertEqual(res["R3"]["short_catastrophic"], ["s04.pdf"])


class R4R5(unittest.TestCase):
    def test_long_promised_report(self):
        m, p, w = clean(n_short=1, n_long=4, long_pages=100)
        p = replace(p, "document", "l00.pdf", lo("l00.pdf", 100, 102))           # within 2%
        p = replace(p, "document", "l01.pdf", lo("l01.pdf", 100, 103, wr=0.8))   # outside, low wr
        p = replace(p, "document", "l02.pdf", lo("l02.pdf", 100, 110))
        r4 = ev(m, p, w)["R4"]
        self.assertEqual(r4["kind"], "reported")
        self.assertEqual(r4["lo"]["n"], 4)
        self.assertEqual(r4["lo"]["median_abs_delta_pages_pct"], 2.5)            # 0,2,3,10
        self.assertEqual(r4["lo"]["within_max1_2pct"], 2)
        self.assertEqual(r4["lo"]["wr_ge_085"], 3)
        self.assertEqual(r4["word"]["within_max1_2pct"], 4)

    def test_one_page_floor_for_short_long_documents(self):
        m, p, w = clean(n_short=1, n_long=1, long_pages=30)                      # 2% = 0.6
        p = replace(p, "document", "l00.pdf", lo("l00.pdf", 30, 31))
        self.assertEqual(ev(m, p, w)["R4"]["lo"]["within_max1_2pct"], 1)

    def test_r4_and_r5_never_gate(self):
        m, p, w = clean(n_short=5, n_long=1)
        p = replace(p, "document", "l00.pdf", lo("l00.pdf", 40, 47, wr=0.3))
        gd = {d: {"doc": d, "src_pages": s["pages"], "out_pages": s["pages"] + 5,
                  "word_recall": 0.1} for d, s in m.items()}
        res = ev(m, p, w, docs_rows=gd)
        self.assertTrue(res["announce"])
        self.assertTrue(res["R5"]["run"])
        self.assertEqual(res["R5"]["page_exact"], 0)
        self.assertFalse(ev(m, p, w)["R5"]["run"])

    def test_text_has_every_criterion_and_the_table(self):
        m, p, w = clean()
        txt = X.render_text(ev(m, p, w))
        for k in ("R1 PASS", "R2 PASS", "R3 PASS", "R4 reported", "R5 reported", "announce: yes",
                  "s00.pdf", "l01.pdf"):
            self.assertIn(k, txt)
        self.assertNotIn("SYNTHETIC", txt)
        res = ev(m, p, w, manifest_meta={"synthetic": True})
        self.assertIn("SYNTHETIC", X.render_text(res))


class SingleUse(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.ledger = os.path.join(self.d, "ledger.jsonl")
        self.ev = os.path.join(self.d, "evidence")
        os.makedirs(self.ev)

    def test_fresh_resume_then_refused_after_finish(self):
        self.assertEqual(X.guard(self.ledger, self.ev, "r1", "c1", prefix="holdout2-")[0], "fresh")
        X._append(self.ledger, {"event": "start", "run": "r1", "commit": "c1"})
        self.assertEqual(X.guard(self.ledger, self.ev, "r1", "c1", prefix="holdout2-")[0], "resume")
        with self.assertRaises(X.ExamInvalid):                 # another run name
            X.guard(self.ledger, self.ev, "r2", "c1", prefix="holdout2-")
        with self.assertRaises(X.ExamInvalid):                 # same name, other commit
            X.guard(self.ledger, self.ev, "r1", "c2", prefix="holdout2-")
        X._append(self.ledger, {"event": "finish", "run": "r1", "commit": "c1"})
        with self.assertRaises(X.ExamInvalid):
            X.guard(self.ledger, self.ev, "r1", "c1", prefix="holdout2-")
        state, reasons = X.guard(self.ledger, self.ev, "r2", "c1", rerun_reason="owner asked",
                                 prefix="holdout2-")
        self.assertEqual(state, "rerun")
        self.assertTrue(reasons)
        with self.assertRaises(X.ExamInvalid):                 # a blank reason is no reason
            X.guard(self.ledger, self.ev, "r2", "c1", rerun_reason="  ", prefix="holdout2-")

    def test_existing_results_file_refuses(self):
        open(os.path.join(self.ev, "holdout2-2026-10-12.json"), "w").close()
        with self.assertRaises(X.ExamInvalid):
            X.guard(self.ledger, self.ev, "r1", "c1", prefix="holdout2-")

    def test_guard_cli_records_start_and_reason(self):
        out = sys.stdout
        sys.stdout = open(os.devnull, "w")
        try:
            base = ["guard", "--ledger", self.ledger, "--evidence-dir", self.ev,
                    "--commit", "c1", "--record"]
            self.assertEqual(X.main(base + ["--run", "r1"]), 0)
            self.assertEqual(X.main(base + ["--run", "r2"]), 4)
            self.assertEqual(X.main(base + ["--run", "r2", "--rerun-reason", "Word crashed"]), 0)
        finally:
            sys.stdout.close()
            sys.stdout = out
        entries = X._ledger(self.ledger)
        self.assertEqual([e["run"] for e in entries], ["r1", "r2"])
        self.assertEqual(entries[1]["rerun_reason"], "Word crashed")

    def test_wrap_never_overwrites(self):
        exam, text = os.path.join(self.d, "e.json"), os.path.join(self.d, "e.txt")
        with open(exam, "w", encoding="utf-8") as fh:
            json.dump({"valid": True, "announce": True, "R1": {"pass": True}}, fh)
        with open(text, "w", encoding="utf-8") as fh:
            fh.write("announce: yes\n")
        out = os.path.join(self.ev, "holdout2-x.json")
        so = sys.stdout
        sys.stdout = open(os.devnull, "w")
        try:
            args = ["wrap", out, "--exam-json", exam, "--text", text, "--commit", "c1",
                    "--input", "exam=" + exam, "--input", "gone=" + os.path.join(self.d, "nope")]
            self.assertEqual(X.main(args), 0)
            self.assertEqual(X.main(args), 4)
        finally:
            sys.stdout.close()
            sys.stdout = so
        with open(out, encoding="utf-8") as fh:
            e = json.load(fh)
        self.assertEqual(e["tree_commit"], "c1")
        self.assertEqual(e["inputs"]["exam"]["sha256"], X.sha256(exam))
        self.assertTrue(e["inputs"]["gone"]["missing"])
        self.assertTrue(e["verdict"]["announce"])
        self.assertEqual((e["exam_set"], e["release"]), ("holdout3", "0.3.0b2"))

    def test_a_guard_needs_a_prefix(self):
        with self.assertRaises(X.ExamInvalid):
            X.guard(self.ledger, self.ev, "r1", "c1")

    def test_results_pattern(self):
        pat = X.results_pattern("holdout3-")
        for name in ("holdout3-2026-10-13.json", "holdout3-2026-10-13-rerun2.json",
                     "holdout3-dry-dry-rc-2026-10-13.json"):
            self.assertTrue(pat.match(name), name)
        for name in ("holdout3-registration-2026-10-12.json", "holdout3-manifest.json",
                     "holdout2-2026-10-11.json", "holdout3-2026-10-13.txt"):
            self.assertFalse(pat.match(name), name)


class Holdout3(unittest.TestCase):
    """Holdout-3 is its own exam: its own row, ledger, prefix, promise and hash.
    Synthetic directories only; the sealed set is never opened."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.scr = os.path.join(self.d, "scr")
        self.ev = os.path.join(self.d, "evidence")
        os.makedirs(self.scr)
        os.makedirs(self.ev)

    def _quiet(self, argv):
        out = sys.stdout
        sys.stdout = open(os.devnull, "w")
        try:
            return X.main(argv)
        finally:
            sys.stdout.close()
            sys.stdout = out

    def test_every_path_and_prefix_resolves_together(self):
        import contextlib
        import io
        buf = io.StringIO()
        nowhere = os.path.join(self.d, "no-such-set")      # resolve opens nothing
        with contextlib.redirect_stdout(buf):
            self.assertEqual(X.main(["resolve", "--exam", "holdout3", "--hold", nowhere]), 0)
        row = dict(line.split("=", 1) for line in buf.getvalue().splitlines())
        row = {k: v.strip("'") for k, v in row.items()}
        self.assertEqual(row["EXAM"], "holdout3")
        self.assertEqual(row["EXAM_RELEASE"], "0.3.0b2")
        self.assertEqual(row["EXAM_SHA"], HOLDOUT3_SHA256)
        self.assertEqual(row["EXAM_DOCS"], str(HOLDOUT3_DOCUMENTS))
        self.assertEqual(row["EXAM_HOLD"], nowhere)
        self.assertEqual(row["EXAM_MANIFEST_NAME"], "holdout3.json")
        self.assertEqual(row["EXAM_LEDGER"], "holdout3-exam.ledger.jsonl")
        self.assertEqual(row["EXAM_SUFFIX"], ".holdout3")
        self.assertEqual(row["EXAM_PREFIX"], "holdout3-")
        self.assertEqual(row["EXAM_TAG"], "h3")
        self.assertFalse([k for k, v in row.items() if "holdout2" in v or "rv_hold2" in v])
        self.assertFalse(os.path.exists(nowhere))
        ex = X.exam("holdout3")
        self.assertEqual(ex["set_dir"], r"C:\lotmp\rv_hold3")
        h2, h3 = X.exam("holdout2"), X.exam("holdout3")
        for k in ("sha256", "set_dir", "manifest", "ledger", "state_suffix", "prefix", "tag",
                  "release"):
            self.assertNotEqual(h2[k], h3[k], k)

    def test_holdout2s_finished_exam_does_not_block_holdout3(self):
        X._append(os.path.join(self.scr, "holdout2-exam.ledger.jsonl"),
                  {"event": "start", "run": "holdout2-rc", "commit": "71af76e"})
        X._append(os.path.join(self.scr, "holdout2-exam.ledger.jsonl"),
                  {"event": "finish", "run": "holdout2-rc", "commit": "71af76e"})
        for name in ("holdout2-2026-10-11.json", "holdout2-manifest.json",
                     "holdout3-registration-2026-10-12.json"):
            open(os.path.join(self.ev, name), "w").close()
        ledger3 = os.path.join(self.scr, X.exam("holdout3")["ledger"])
        base = ["guard", "--exam", "holdout3", "--ledger", ledger3, "--evidence-dir", self.ev,
                "--commit", "1d7812b", "--record"]
        self.assertEqual(self._quiet(base + ["--run", "holdout3-rc"]), 0)   # no --rerun-reason
        self.assertEqual([e["event"] for e in X._ledger(ledger3)], ["start"])
        # holdout-2's own guard still refuses its own second run
        with self.assertRaises(X.ExamInvalid):
            X.guard(os.path.join(self.scr, "holdout2-exam.ledger.jsonl"), self.ev, "again",
                    "1d7812b", prefix="holdout2-")

    def test_a_second_holdout3_exam_refuses(self):
        ledger3 = os.path.join(self.scr, X.exam("holdout3")["ledger"])
        base = ["guard", "--exam", "holdout3", "--ledger", ledger3, "--evidence-dir", self.ev,
                "--commit", "1d7812b", "--record"]
        self.assertEqual(self._quiet(base + ["--run", "holdout3-rc"]), 0)
        self.assertEqual(self._quiet(base + ["--run", "holdout3-rc"]), 0)    # a resume
        self.assertEqual(self._quiet(base + ["--run", "holdout3-again"]), 4)
        X._append(ledger3, {"event": "finish", "run": "holdout3-rc", "commit": "1d7812b"})
        open(os.path.join(self.ev, "holdout3-2026-10-13.json"), "w").close()
        self.assertEqual(self._quiet(base + ["--run", "holdout3-rc"]), 4)
        self.assertEqual(self._quiet(base + ["--run", "holdout3-rc", "--rerun-reason", "x"]), 0)
        self.assertEqual(X._ledger(ledger3)[-1]["state"], "rerun")

    def _manifest(self, docs, name="holdout3.json", where=None):
        where = where or self.d
        path = os.path.join(where, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"documents": docs}, fh)
        return path

    def test_a_wrong_sha_refuses(self):
        path = self._manifest({"a": {"file": "a.pdf", "pages": 3, "promised": True}})
        with self.assertRaises(X.ExamInvalid):
            X.load_manifest(path, X.exam("holdout3")["sha256"], X.exam("holdout3")["promise_fields"])
        self.assertEqual(self._quiet(["verify-manifest", path, "--exam", "holdout3"]), 3)
        self.assertEqual(self._quiet(["verify-manifest", path, "--exam", "holdout3",
                                      "--sha256", X.sha256(path)]), 0)

    def test_the_document_count_is_the_registrations(self):
        path = self._manifest({"a": {"file": "a.pdf", "pages": 3, "promised": True}})
        with self.assertRaises(X.ExamInvalid):
            X.load_manifest(path, X.sha256(path), ("promised",), documents=HOLDOUT3_DOCUMENTS)

    def test_holdout3_reads_its_own_promise_and_r2_counts_it(self):
        fields = X.exam("holdout3")["promise_fields"]
        docs = {"r%d" % i: {"file": "r%d.pdf" % i, "pages": 2, "promised": True,
                            "design_class": "resume"} for i in range(4)}
        docs["w"] = {"file": "w.pdf", "pages": 5, "promised": True, "design_class": "web-print"}
        docs["s"] = {"file": "s.pdf", "pages": 9, "promised": False, "design_class": "slides"}
        path = self._manifest(docs)
        _, m = X.load_manifest(path, X.sha256(path), fields)
        self.assertEqual({d["_promise_field"] for d in m.values()}, {"promised"})
        prows = [lo(n, s["pages"], s["pages"]) for n, s in m.items()]
        wrows = [wd(n, s["pages"], s["pages"]) for n, s in m.items()]
        res = ev(m, prows, wrows, exam_name="holdout3")
        self.assertEqual(res["R2"]["n"], 5)                  # the Chrome print counts
        self.assertEqual(res["promise_field"], "promised")
        self.assertIn("holdout3 exam", X.render_text(res))
        # with both fields, the narrowed one is read; a field some lack is refused
        for d in docs.values():
            d["promised_b_narrowed"] = d["design_class"] != "web-print" and d["promised"]
        path = self._manifest(docs)
        _, m = X.load_manifest(path, X.sha256(path), fields)
        self.assertEqual(sum(d["_promised"] for d in m.values()), 4)
        del docs["s"]["promised_b_narrowed"]
        path = self._manifest(docs)
        with self.assertRaises(X.ExamInvalid):
            X.load_manifest(path, X.sha256(path), fields)

    def test_expect_promised(self):
        docs = {"a": {"file": "a.pdf", "pages": 3, "promised": True},
                "b": {"file": "b.pdf", "pages": 3, "promised": False}}
        path = self._manifest(docs)
        sha = X.sha256(path)
        base = ["verify-manifest", path, "--exam", "holdout3", "--sha256", sha]
        self.assertEqual(self._quiet(base + ["--expect-promised", "1"]), 0)
        self.assertEqual(self._quiet(base + ["--expect-promised", "35"]), 3)

    def test_locate_by_name_then_by_hash(self):
        setd = os.path.join(self.d, "set")
        os.makedirs(setd)
        path = self._manifest({"a": {"file": "a.pdf", "pages": 1, "promised": True}},
                              name="sealed-manifest.json", where=setd)
        sha = X.sha256(path)
        self.assertEqual(X.locate_manifest(setd, "holdout3.json", sha), path)
        named = self._manifest({"a": {"file": "a.pdf", "pages": 1, "promised": True}},
                               name="holdout3.json", where=setd)
        self.assertEqual(X.locate_manifest(setd, "holdout3.json", sha), named)
        with self.assertRaises(X.ExamInvalid):
            X.locate_manifest(setd, "nothing.json", "0" * 64)


class DrySet(unittest.TestCase):
    def test_two_pdf_synthetic_set(self):
        try:
            import reportlab  # noqa: F401
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest("reportlab/fitz not installed")
        spec = importlib.util.spec_from_file_location(
            "holdout_dryset", os.path.join(ROOT, "scripts", "dev", "holdout_dryset.py"))
        D = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(D)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        digest = D.build(d, "holdout3.json")
        self.assertTrue(os.path.exists(os.path.join(d, "holdout3.sha256")))
        man, docs = X.load_manifest(os.path.join(d, "holdout3.json"), digest)
        self.assertTrue(man["synthetic"])
        self.assertEqual(sorted((s["pages"], s[X.PROMISE_FIELD]) for s in docs.values()),
                         [(3, True), (22, True)])
        for name, s in docs.items():
            self.assertEqual(X.sha256(os.path.join(d, "pdfs", name)), s["sha256"])


if __name__ == "__main__":
    unittest.main()
