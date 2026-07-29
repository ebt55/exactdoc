"""Mutation tests: every way the gate used to report a false green must be red.

A gate is a claim about what cannot get past it, and this project has already
paid twice for believing such a claim unverified -- once when the parity harness
omitted `within2pt` and reported 0 regressions on a swap that cost 0.510 -> 0.291,
and once when a gate that could not run at all (an undeclared `pypdfium2`) looked
exactly like a gate that passed.

So each test below starts from a *healthy* result set, breaks exactly one thing,
and asserts the verdict turns red for the expected reason. If a check is ever
weakened or deleted, one of these fails. They need no corpus, no LibreOffice and
no PDF: the decision under test is a pure function of already-measured numbers,
which is the reason it was extracted into `testkit/gate.py` in the first place.

    python tests/test_gate_mutations.py
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "testkit"))

import gate  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print("  %-4s %s%s" % ("ok" if cond else "FAIL", name,
                           "" if cond else "   <-- " + detail))
    if not cond:
        FAILED.append(name)


# ------------------------------------------------------------------- fixtures
# Two documents is enough to exercise every rule, and small enough that a
# failure names the cause instead of requiring a bisect. `good` passes every
# threshold; `known` is a recorded shortfall carrying a defect ID, modelled on
# 04_exec_brief, whose live-text coverage has never reached 0.95.
def result(src, pages=(3, 3), live=0.99, doc=0.99, word=0.97, w2=0.60,
           dy=0.50, raster=0.01):
    return {"src": src, "src_pages": pages[0], "out_pages": pages[1],
            "page_match": pages[0] == pages[1], "live_text_cov": live,
            "doc_recall": doc, "word_recall": word, "within2pt": w2,
            "dy_p50": dy, "dy_p90": dy * 3, "raster_frac": raster,
            "mean_ssim": 0.80, "mean_iou": 0.70, "renderer": "libreoffice",
            "src_words": 900, "n_media": 0}


def healthy():
    return [result("good.pdf"),
            result("known.pdf", live=0.941, doc=0.944)]


MANIFEST = {"documents": {"good.pdf": {"path": "corpus/pdfs", "src_pages": 3},
                          "known.pdf": {"path": "corpus/pdfs", "src_pages": 3}}}


def baseline_for(results):
    rec = gate.record("product", results)
    rec["shortfall_defects"] = {"known.pdf": "D-test"}
    return rec


def verdict(results, baseline=None, manifest=None, absolute=False):
    return gate.check("product", results,
                      manifest=manifest if manifest is not None else MANIFEST,
                      baseline=baseline if baseline is not None
                      else baseline_for(healthy()),
                      absolute=absolute)


def kinds(v):
    return set(v.kinds())


# ----------------------------------------------------------------------- tests
def test_healthy_passes():
    v = verdict(healthy())
    check("a healthy lane passes", v.ok, v.report())


def test_removed_document():
    """`gen_corpus.py` exits 0 after skipping 8 of 16 documents."""
    r = [x for x in healthy() if x["src"] != "known.pdf"]
    v = verdict(r)
    check("removing a corpus document fails", "missing" in kinds(v), v.report())


def test_unexpected_document():
    r = healthy() + [result("stranger.pdf")]
    v = verdict(r)
    check("an unmanifested document fails", "unexpected" in kinds(v), v.report())


def test_duplicate_document():
    """Two inputs with one basename overwrite each other's output and row."""
    r = healthy() + [result("good.pdf", w2=0.10)]
    v = verdict(r)
    check("a duplicated document fails", "duplicate" in kinds(v), v.report())


def test_identity_change():
    """A generator change that alters a document re-bases every number."""
    r = healthy()
    r[0]["src_pages"] = 4
    r[0]["out_pages"] = 4
    v = verdict(r)
    check("a changed source page count fails", "identity" in kinds(v), v.report())


def test_render_error():
    """harness.evaluate() returns {'error': ...}; nothing used to look."""
    r = healthy()
    r[0] = {"src": "good.pdf", "error": "LibreOffice produced no PDF",
            "live_text_cov": 0.99}
    v = verdict(r)
    check("a render error fails", "error" in kinds(v), v.report())


def test_convert_error():
    r = healthy()
    r[0] = {"src": "good.pdf", "convert_error": "ValueError: document closed"}
    v = verdict(r)
    check("a conversion error fails", "error" in kinds(v), v.report())


def test_missing_metric():
    """An absent metric used to be skipped: `if v is None: continue`."""
    for metric in ("within2pt", "dy_p50", "live_text_cov", "word_recall"):
        r = healthy()
        del r[0][metric]
        v = verdict(r)
        check("deleting %s fails" % metric,
              "no-metric" in kinds(v) or "unrecorded" in kinds(v), v.report())


def test_known_failure_sliding_further():
    """The old baseline stored metric NAMES: 0.941 could fall to 0.10 unseen."""
    r = healthy()
    r[1]["live_text_cov"] = 0.10
    v = verdict(r)
    check("a known failure sliding to 0.10 fails", "regression" in kinds(v),
          v.report())


def test_known_failure_inside_tolerance():
    r = healthy()
    r[1]["live_text_cov"] = 0.941 - gate.METRICS["live_text_cov"]["tol"] / 2
    v = verdict(r)
    check("a known failure inside tolerance still passes", v.ok, v.report())


def test_page_error_magnitude():
    """page_match is a boolean: 1 page over and 40 over looked identical."""
    base = healthy()
    base[1]["out_pages"] = 4                      # already failing page_err
    bl = baseline_for(base)
    bl["shortfall_defects"] = {"known.pdf": "D-test"}
    worse = copy.deepcopy(base)
    worse[1]["out_pages"] = 40
    v = gate.check("product", worse, manifest=MANIFEST, baseline=bl)
    check("a page error growing 1 -> 37 fails", "regression" in kinds(v),
          v.report())


def test_stale_record():
    """A recorded shortfall that now passes silently re-admits the regression."""
    r = healthy()
    r[1]["live_text_cov"] = 0.97
    r[1]["doc_recall"] = 0.98
    v = verdict(r)
    check("a stale record fails", "stale" in kinds(v), v.report())


def test_undocumented_shortfall():
    """A recorded shortfall with no defect ID is an unexplained number."""
    bl = gate.record("product", healthy())        # no shortfall_defects
    v = verdict(healthy(), baseline=bl)
    check("a shortfall with no defect ID fails", "undocumented" in kinds(v),
          v.report())


def test_new_threshold_failure():
    r = healthy()
    r[0]["word_recall"] = 0.50
    v = verdict(r)
    check("a new threshold failure fails",
          "threshold" in kinds(v) and "regression" in kinds(v), v.report())


def test_unrecorded_document():
    bl = gate.record("product", [healthy()[0]])
    bl["shortfall_defects"] = {"known.pdf": "D-test"}
    v = verdict(healthy(), baseline=bl)
    check("a document with no numeric baseline fails",
          "unrecorded" in kinds(v), v.report())


def test_unrecorded_metric():
    bl = baseline_for(healthy())
    del bl["documents"]["good.pdf"]["within2pt"]
    v = verdict(healthy(), baseline=bl)
    check("a metric with no recorded value fails", "unrecorded" in kinds(v),
          v.report())


def test_aggregate_regression():
    """Per-document moves can each stay in tolerance and still move the mean."""
    bl = baseline_for(healthy())
    r = healthy()
    for x in r:
        x["within2pt"] -= 0.045                   # under the per-doc tolerance
    v = gate.check("product", r, manifest=MANIFEST, baseline=bl)
    check("an aggregate-only regression fails", "regression" in kinds(v),
          v.report())


def test_absolute_mode_flags_known_shortfall():
    v = verdict(healthy(), absolute=True)
    check("release mode refuses a known shortfall",
          "unqualified" in kinds(v), v.report())
    check("regression mode accepts the same shortfall", verdict(healthy()).ok)


def test_both_lanes_gate():
    """`REFINE=lanes` returned only the refined lane's status."""
    import runall
    src = open(runall.__file__).read()
    check("the runner gates on every lane it ran",
          "all(v.ok for v in verdicts.values())" in src,
          "runall.main() must not return one lane's status")


def test_shipped_default_is_the_measured_default():
    """The API, the CLI and the product lane must be one configuration."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    from exactdoc.cli import build_parser
    from exactdoc.options import LANES, PRODUCT
    defaults = {a.dest: a.default for a in build_parser()._actions}
    check("CLI refine default == PRODUCT",
          defaults["refine"] == PRODUCT.refine_rounds,
          "CLI %r vs profile %r" % (defaults["refine"], PRODUCT.refine_rounds))
    check("CLI target default == PRODUCT", defaults["target"] == PRODUCT.target)
    check("CLI backend default == PRODUCT", defaults["backend"] == PRODUCT.backend)
    check("CLI dpi default == PRODUCT", defaults["dpi"] == PRODUCT.dpi)
    check("the product lane is the shipped profile",
          LANES["product"] is PRODUCT)
    check("the raw lane is refine-free", LANES["raw"].refine_rounds == 0)


# ------------------------------------------------------- the parity policy
# `backend_parity.adjudicate()` is pure for the same reason `gate.check()` is,
# and it needs the same treatment: the policy it applies used to live in a
# docstring while the code exited on a different rule entirely.
def parity_fixture():
    """Reference and candidate results, plus a policy that accepts one doc."""
    ref = {"good.pdf": result("good.pdf", w2=0.60),
           "accepted.pdf": result("accepted.pdf", w2=0.72),
           "diverges.pdf": result("diverges.pdf", live=0.71)}
    cand = {"good.pdf": result("good.pdf", w2=0.60),
            "accepted.pdf": result("accepted.pdf", w2=0.53),
            "diverges.pdf": result("diverges.pdf", live=0.68)}
    policy = {
        "reference_backend": "pymupdf", "candidate_backend": "pdfium",
        "margins": {"page_err": 0, "live_text_cov": 0.05,
                    "word_recall": 0.05, "within2pt": 0.08},
        "expected_divergence": {"diverges.pdf": {"reason": "verified visually"}},
        "accepted_shortfalls": {"accepted.pdf": {
            "defect": "D2",
            "floors": {"within2pt": 0.53, "page_err": 0, "live_text_cov": 0.99,
                       "word_recall": 0.97}}},
    }
    return ref, cand, policy


def parity_kinds(ref, cand, policy, subset=False):
    import backend_parity
    _, summary = backend_parity.adjudicate(ref, cand, policy, subset=subset)
    return summary, set(f["kind"] for f in summary["failures"])


def test_parity_healthy_passes():
    ref, cand, policy = parity_fixture()
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("the ratified policy passes", summary["ok"], str(summary["failures"]))
    check("the accepted shortfall is not counted a regression",
          summary["regressions"] == 0, str(summary))
    check("the expected divergence is not counted a regression",
          summary["expected_div"] == 1, str(summary))


def test_parity_accepted_shortfall_worsening():
    """An unbounded acceptance is an acceptance of anything."""
    ref, cand, policy = parity_fixture()
    cand["accepted.pdf"]["within2pt"] = 0.20
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("an accepted shortfall falling past its floor fails",
          "below-floor" in kinds_, str(summary["failures"]))


def test_parity_stale_acceptance():
    """A document accepted as worse that is no longer worse hides the next one."""
    ref, cand, policy = parity_fixture()
    cand["accepted.pdf"]["within2pt"] = 0.72
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a stale acceptance fails", "stale" in kinds_,
          str(summary["failures"]))


def test_parity_unbounded_acceptance():
    ref, cand, policy = parity_fixture()
    policy["accepted_shortfalls"]["accepted.pdf"]["floors"] = None
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("an acceptance with no numeric floors fails", "unrecorded" in kinds_,
          str(summary["failures"]))


def test_parity_new_regression():
    ref, cand, policy = parity_fixture()
    cand["good.pdf"]["within2pt"] = 0.20
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a new regression fails", "regression" in kinds_ and
          summary["regressions"] == 1, str(summary["failures"]))


def test_parity_missing_document():
    ref, cand, policy = parity_fixture()
    del cand["good.pdf"]
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a document scored under one backend only fails",
          "missing" in kinds_, str(summary["failures"]))


def test_parity_subset_cannot_pass():
    ref, cand, policy = parity_fixture()
    summary, _ = parity_kinds(ref, cand, policy, subset=True)
    check("a --only subset can never report the swap acceptable",
          not summary["ok"], str(summary))


def test_committed_parity_policy_is_wellformed():
    import backend_parity
    policy = backend_parity.load_policy()
    accepted = {k: v for k, v in policy.get("accepted_shortfalls", {}).items()
                if not k.startswith("_")}
    check("the policy names its two backends",
          policy.get("reference_backend") and policy.get("candidate_backend"))
    for doc_id, spec in sorted(accepted.items()):
        check("accepted %s carries a defect ID" % doc_id, bool(spec.get("defect")))
        check("accepted %s carries numeric floors" % doc_id,
              isinstance(spec.get("floors"), dict) and spec["floors"],
              "floors=%r -- record them with --update-policy" % spec.get("floors"))
    for doc_id, spec in sorted(policy.get("expected_divergence", {}).items()):
        if doc_id.startswith("_"):
            continue
        check("divergence %s carries rendered evidence" % doc_id,
              bool(spec.get("verified")))


def test_evidence_merge_never_empties_a_section():
    """The artifact is the single source of a release claim. Nothing may blank it.

    Measured on a full green run: the final `evidence.py --out` step, whose job is
    to fill in the environment, passed the empty template's `parity: None` over
    the verdict the previous step had recorded, and the run finished with an
    evidence file that had forgotten its own parity result.
    """
    import tempfile
    import evidence
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "evidence.json")
        evidence.merge(p, parity={"ok": True, "regressions": 0},
                       lanes={"product": {"verdict": {"ok": True}}},
                       corpus={"resolved": 16})
        evidence.merge(p, parity=None, corpus=None, lanes={},
                       environment={"os": "linux"})
        with open(p) as f:
            doc = json.load(f)
    check("a None section does not overwrite a recorded one",
          doc.get("parity", {}).get("ok") is True, json.dumps(doc.get("parity")))
    check("an empty lanes dict does not drop recorded lanes",
          "product" in (doc.get("lanes") or {}), str(doc.get("lanes")))
    check("the corpus section survives", (doc.get("corpus") or {}).get("resolved") == 16)
    check("a later section still merges in", doc["environment"]["os"] == "linux")


def test_relative_tolerance():
    """dy_p50 spans 0.04pt to 101pt; one absolute slack cannot serve both."""
    small = gate.tolerance(gate.METRICS["dy_p50"], 0.6)
    large = gate.tolerance(gate.METRICS["dy_p50"], 101.0)
    check("the absolute floor governs a small drift", abs(small - 0.5) < 1e-9,
          str(small))
    check("the proportional term governs a large drift", large > 10.0, str(large))
    check("a fraction metric stays absolute",
          gate.tolerance(gate.METRICS["within2pt"], 0.9) == 0.05)


def test_committed_baseline_is_wellformed():
    """The committed record must satisfy the schema the gate reads."""
    doc = gate.load()
    if not doc:
        check("a baseline is committed", False, "no gate_baseline.json")
        return
    check("baseline is schema 2", doc.get("schema") == 2, str(doc.get("schema")))
    from exactdoc.options import LANES
    for lane in LANES:
        entry = doc.get("lanes", {}).get(lane)
        check("lane %r is recorded" % lane, bool(entry),
              "lanes present: %s" % sorted(doc.get("lanes", {})))
        if not entry:
            continue
        docs = entry.get("documents", {})
        manifest = gate.load_manifest() or {"documents": {}}
        check("lane %r records every manifest document" % lane,
              set(docs) == set(manifest["documents"]),
              "record %d, manifest %d" % (len(docs), len(manifest["documents"])))
        for doc_id, metrics in sorted(docs.items()):
            missing = [m for m in gate.METRICS if m not in metrics]
            check("lane %r %s records every gated metric" % (lane, doc_id),
                  not missing, "missing %s" % missing)
            for name, value in sorted(metrics.items()):
                spec = gate.METRICS.get(name)
                if spec and not gate.clears(spec["dir"], value, spec["threshold"]):
                    check("lane %r %s shortfall has a defect ID" % (lane, doc_id),
                          doc_id in entry.get("shortfall_defects", {}),
                          "%s=%s below %s" % (name, value, spec["threshold"]))


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print("gate mutation tests (%d)" % len(tests))
    for t in tests:
        print("\n%s" % t.__name__)
        t()
    print("\n%s" % ("all clear" if not FAILED else
                    "%d FAILED: %s" % (len(FAILED), ", ".join(FAILED))))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
