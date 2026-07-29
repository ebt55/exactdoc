"""The acceptance test for replacing the parser -- and the policy it enforces.

The swap is done when pypdfium2 is not WORSE than PyMuPDF, not when it is
perfect. Several corpus documents already fail on PyMuPDF (nested tables,
rasterised SVG charts), and chasing those while believing they are swap
regressions would burn the schedule on pre-existing bugs.

So this converts both backends over the manifest corpus with the same profile
and marks each document REGRESSION / same / BETTER / expected-div / accepted.

    python testkit/backend_parity.py
    python testkit/backend_parity.py --refine 3
    python testkit/backend_parity.py --refine 3 --only c7_code
    python testkit/backend_parity.py --update-policy   # record the floors

**The policy is `parity_policy.json`, not this docstring.** It used to be the
other way round: the code exited on `regressions == 0` while ROADMAP §3.2 and
STATUS D2 said two named documents were formally accepted divergences. An
executable rule that contradicts the ratified rule has one outcome -- the step
gets marked `continue-on-error` so the build stays usable, which is what
happened, and from then on nothing was gated at all. Two accepted shortfalls now
live in the policy file with numeric floors: worsening past a floor fails, and
so does clearing the divergence entirely, because an acceptance that no longer
describes reality is a stale record.

--only takes substrings and narrows the run. The full run converts 16 documents
twice and renders both, which is minutes; a single document is seconds. It exists
so a hypothesis about one document costs that document. `--only` can never report
the swap as acceptable: the verdict needs the whole corpus, and the exit code
says so.
"""
import argparse
import json
import os
import sys

import _paths  # noqa: F401
import evidence
import gate
import harness
import runall

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(ROOT)
POLICY_PATH = os.path.join(ROOT, "parity_policy.json")

# Compared in priority order, matching the gate's own: a wrong page count is the
# loudest failure, rasterised text is unrecoverable, page-level placement next,
# and fine placement last -- but *present*, because leaving within2pt out was a
# real hole. Measured: a swap this harness called clean cost within-2pt
# 0.510 -> 0.291 and median drift 0.69pt -> 2.02pt, invisibly.
DIMENSIONS = ("page_err", "live_text_cov", "word_recall", "within2pt")
LOWER_IS_BETTER = ("page_err",)


def load_policy(path=POLICY_PATH):
    with open(path) as f:
        return json.load(f)


def _clean(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def dims(res):
    return {"page_err": abs(res["out_pages"] - res["src_pages"]),
            "live_text_cov": res.get("live_text_cov", 0.0),
            "word_recall": res.get("word_recall", 0.0),
            "within2pt": res.get("within2pt", 0.0)}


def compare(a, b, margins):
    """-> (verdict, dimension) where verdict is 'worse' | 'better' | None."""
    da, db = dims(a), dims(b)
    for name in DIMENSIONS:
        margin = margins.get(name, 0)
        delta = db[name] - da[name]
        if abs(delta) <= margin:
            continue
        if name in LOWER_IS_BETTER:
            return ("worse" if delta > 0 else "better"), name
        return ("worse" if delta < 0 else "better"), name
    return None, None


def run(backend, srcs, out_root, refine):
    """Convert the corpus with one backend. No monkey-patching.

    This used to reassign `exactdoc.convert.parse_pdf`, so the gate measured a
    module it had mutated rather than the product, and the mutation silently
    bypassed whatever backend selection `convert()` would have done itself.
    """
    from exactdoc.options import PRODUCT
    from exactdoc.convert import convert

    options = PRODUCT.replace(backend=backend, refine_rounds=refine)
    out = os.path.join(out_root, backend)
    os.makedirs(out, exist_ok=True)
    pairs = []
    for s in srcs:
        n = os.path.splitext(os.path.basename(s))[0]
        dx = os.path.join(out, n + ".docx")
        try:
            convert(s, dx, options=options)
            pairs.append((s, dx, n))
        except Exception as e:
            print("  CONVERT FAIL [%s] %-22s %s" % (backend, n[:22], str(e)[:50]))
    harness.batch_docx_to_pdf([p[1] for p in pairs], os.path.join(out, "r"))
    res = {}
    for s, dx, n in pairs:
        try:
            res[os.path.basename(s)] = harness.evaluate(
                s, dx, os.path.join(out, "r"), save_images=False)
        except Exception as e:
            print("  EVAL FAIL [%s] %-22s %s" % (backend, n[:22], str(e)[:50]))
    return res


def adjudicate(ref, cand, policy, subset=False):
    """Apply the policy. -> (rows, summary dict)."""
    margins = _clean(policy.get("margins", {}))
    divergence = _clean(policy.get("expected_divergence", {}))
    accepted = _clean(policy.get("accepted_shortfalls", {}))
    rows, failures = [], []
    counts = {"regressions": 0, "same": 0, "better": 0, "expected_div": 0,
              "accepted": 0, "missing": 0}

    for doc_id in sorted(set(ref) | set(cand)):
        A, B = ref.get(doc_id), cand.get(doc_id)
        if not A or not B:
            counts["missing"] += 1
            failures.append(("missing", doc_id,
                             "scored under %s only -- a document that cannot be "
                             "compared is not a document that agrees"
                             % ("reference" if A else "candidate")))
            rows.append({"document": doc_id, "verdict": "MISSING"})
            continue
        state, dim = compare(A, B, margins)
        row = {"document": doc_id, "reference": dims(A), "candidate": dims(B),
               "dimension": dim}

        if doc_id in divergence:
            row["verdict"] = "expected-div"
            counts["expected_div"] += 1
        elif doc_id in accepted:
            spec = accepted[doc_id]
            row["verdict"] = "accepted"
            row["defect"] = spec.get("defect")
            counts["accepted"] += 1
            if not spec.get("defect"):
                failures.append(("undocumented", doc_id,
                                 "accepted shortfall with no defect ID"))
            floors = spec.get("floors")
            if floors is None:
                failures.append(("unrecorded", doc_id,
                                 "accepted with no numeric floors -- record them "
                                 "with --update-policy on the canonical "
                                 "environment. An unbounded acceptance is an "
                                 "acceptance of anything"))
            else:
                cd = dims(B)
                for name, floor in sorted(_clean(floors).items()):
                    v = cd.get(name)
                    if v is None:
                        continue
                    tol = gate.METRICS.get(name, {}).get("tol", 0)
                    bad = (v > floor + tol) if name in LOWER_IS_BETTER \
                        else (v < floor - tol)
                    if bad:
                        failures.append(("below-floor", doc_id,
                                         "%s %.4g against a ratified floor of "
                                         "%.4g" % (name, v, floor)))
            if state != "worse":
                failures.append(("stale", doc_id,
                                 "accepted as worse, but the candidate is no "
                                 "longer worse (%s). A stale acceptance hides "
                                 "the next real regression on this document"
                                 % (state or "equal")))
        elif state == "worse":
            row["verdict"] = "REGRESSION"
            counts["regressions"] += 1
            failures.append(("regression", doc_id,
                             "worse on %s: %.4g -> %.4g" %
                             (dim, dims(A)[dim], dims(B)[dim])))
        elif state == "better":
            row["verdict"] = "BETTER"
            counts["better"] += 1
        else:
            row["verdict"] = "same"
            counts["same"] += 1
        rows.append(row)

    ok = not failures and not subset
    summary = dict(counts)
    summary.update({"ok": ok, "subset": subset,
                    "failures": [{"kind": k, "document": d, "detail": v}
                                 for k, d, v in failures]})
    return rows, summary


def record_policy(ref, cand, policy, path=POLICY_PATH):
    """Write the measured floors for each accepted shortfall."""
    accepted = policy.get("accepted_shortfalls", {})
    for doc_id, spec in accepted.items():
        if doc_id.startswith("_") or doc_id not in cand:
            continue
        spec["floors"] = {k: round(v, 4) for k, v in dims(cand[doc_id]).items()}
        spec["reference_at_record"] = {k: round(v, 4)
                                       for k, v in dims(ref[doc_id]).items()}
    with open(path, "w") as f:
        json.dump(policy, f, indent=1, sort_keys=True)
        f.write("\n")
    print("recorded floors for %d accepted shortfall(s) in %s"
          % (sum(1 for k in accepted if not k.startswith("_")), path))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refine", type=int, default=None,
                    help="refine rounds for both backends (default: the product "
                         "profile's)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", nargs="+", default=None,
                    help="substrings; run only the matching documents")
    ap.add_argument("--update-policy", action="store_true",
                    help="record the accepted shortfalls' numeric floors")
    ap.add_argument("--evidence", default=None,
                    help="evidence JSON to merge the parity verdict into")
    a = ap.parse_args(argv)

    from exactdoc.options import PRODUCT
    refine = PRODUCT.refine_rounds if a.refine is None else a.refine

    manifest = gate.load_manifest()
    if manifest is None:
        print("no corpus manifest -- parity cannot know which documents it "
              "should have compared")
        return 2
    srcs, problems = runall.resolve_corpus(manifest)
    for kind, doc, why in problems:
        print("CORPUS %-11s %-28s %s" % (kind, doc[:28], why))
    if not srcs:
        print("no corpus; run the generators first")
        return 2

    subset = False
    if a.only:
        srcs = [s for s in srcs if any(k in os.path.basename(s) for k in a.only)]
        if not srcs:
            print("--only matched no document")
            return 2
        subset = True
        print("subset run: %s -- this cannot report the swap as acceptable, "
              "only the full corpus can"
              % ", ".join(os.path.basename(s) for s in srcs))

    policy = load_policy()
    out_root = a.out or os.path.join(ROOT, "parity")
    ref_name = policy.get("reference_backend", "pymupdf")
    cand_name = policy.get("candidate_backend", "pdfium")
    print("reference %s vs candidate %s, refine %d, %d document(s)"
          % (ref_name, cand_name, refine, len(srcs)))

    ref = run(ref_name, srcs, out_root, refine)
    cand = run(cand_name, srcs, out_root, refine)

    if a.update_policy:
        record_policy(ref, cand, policy)
        policy = load_policy()

    rows, summary = adjudicate(ref, cand, policy, subset=subset)
    print("\n%-22s %-22s %-22s %s"
          % ("document", ref_name, cand_name, "verdict"))
    for row in rows:
        if row["verdict"] == "MISSING":
            print("%-22s %-22s %-22s MISSING" % (row["document"][:22], "-", "-"))
            continue
        r, c = row["reference"], row["candidate"]
        fmt = "pg%+d l%.2f p%.2f w%.2f"
        print("%-22s %-22s %-22s %s"
              % (row["document"][:22],
                 fmt % (r["page_err"], r["live_text_cov"], r["word_recall"],
                        r["within2pt"]),
                 fmt % (c["page_err"], c["live_text_cov"], c["word_recall"],
                        c["within2pt"]),
                 row["verdict"]))

    print("\n%d regression(s), %d same, %d better, %d expected-divergence, "
          "%d accepted, %d missing"
          % (summary["regressions"], summary["same"], summary["better"],
             summary["expected_div"], summary["accepted"], summary["missing"]))
    for f in summary["failures"]:
        print("  %-13s %-28s %s" % (f["kind"], f["document"][:28], f["detail"]))
    if subset:
        print("subset run: exit code reports findings among what it ran, and "
              "cannot report the swap as acceptable")
    print("PASS" if summary["ok"] else "FAIL")

    ev_path = a.evidence or os.path.join(ROOT, "batch", "evidence.json")
    parity = dict(summary)
    parity.update({"reference_backend": ref_name, "candidate_backend": cand_name,
                   "refine_rounds": refine, "documents": rows})
    evidence.merge(ev_path, parity=parity)

    if a.update_policy:
        return 0
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
