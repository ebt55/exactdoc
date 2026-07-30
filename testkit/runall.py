"""Convert every PDF in the given directories and score with the harness.

    python testkit/runall.py testkit/adv corpus/pdfs
    REFINE=lanes python testkit/runall.py testkit/adv corpus/pdfs

Writes batch/results.json plus side-by-side comparison PNGs per document.

Exit code is non-zero on a NEW failure, so this doubles as a CI check. Not on
any failure: three corpus documents have never cleared the thresholds (D3
nested tables, D4 rounded cards, and the exec brief's live-text coverage), so
"exit 1 if anything fails" meant the gate returned 1 on every run it had ever
made. A check that always fails carries the same information as one that always
passes, and it is why the CI step had to be marked continue-on-error to keep
the build usable -- which in turn meant nothing was actually gated.

So the known-failing set is recorded per lane in gate_baseline.json, measured
on the canonical Linux environment, and this exits non-zero when a document
fails that the record says should pass, or fails on a metric the record does
not list for it. A document that PASSES while the record says it fails is also
an error: the record is then stale, and a stale record silently re-admits the
regression it was meant to catch. Re-record deliberately:

    GATE_BASELINE=update REFINE=lanes python testkit/runall.py ...
"""
import os, sys, json, time, glob, traceback

import _paths  # noqa: F401
import harness

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "batch")
BASELINE = os.path.join(ROOT, "gate_baseline.json")

# CI gate: a conversion must clear all of these.
GATE = {"page_match": True, "live_text_cov": 0.95, "doc_recall": 0.95,
        "word_recall": 0.90}


def _load_baseline(lane):
    """{document: [failing metric, ...]} for this lane; empty if unrecorded."""
    if not os.path.exists(BASELINE):
        return {}
    with open(BASELINE) as f:
        return json.load(f).get("lanes", {}).get(lane, {})


def _save_baseline(lane, failing):
    data = {"lanes": {}}
    if os.path.exists(BASELINE):
        with open(BASELINE) as f:
            data = json.load(f)
    data.setdefault("lanes", {})[lane] = {k: sorted(v) for k, v in failing.items()}
    data["_note"] = ("Documents known to miss the gate, per lane, measured on "
                     "the canonical Linux environment (see gate.yml). A new "
                     "entry needs a defect ID in STATUS.md; a removed one "
                     "means something got fixed. Regenerate deliberately with "
                     "GATE_BASELINE=update, never to silence a failure.")
    with open(BASELINE, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    print("recorded baseline for lane '%s' in %s" % (lane, BASELINE))


def main(dirs, out=OUT, gate=True, refine_rounds=None):
    if refine_rounds is None:
        env = os.environ.get("REFINE", "0")
        refine_rounds = int(env) if env.isdigit() else 0
    os.makedirs(out, exist_ok=True)
    pdfs = []
    for d in dirs:
        pdfs += sorted(glob.glob(os.path.join(d, "*.pdf")))
    if not pdfs:
        print("no PDFs found in", dirs)
        return 2

    from exactdoc.convert import convert
    results, converted = [], []
    for p in pdfs:
        name = os.path.splitext(os.path.basename(p))[0]
        docx = os.path.join(out, name + ".docx")
        t0 = time.time()
        try:
            convert(p, docx, refine_rounds=refine_rounds)
            converted.append((p, docx, round(time.time() - t0, 2)))
        except Exception as e:
            results.append({"src": os.path.basename(p),
                            "convert_error": "%s: %s" % (type(e).__name__, e),
                            "trace": traceback.format_exc()[-1200:]})
            print("CONVERT FAIL %-28s %s" % (name, e))

    print("\n-- LibreOffice batch render --")
    rmap = harness.batch_docx_to_pdf([d for _, d, _ in converted],
                                     os.path.join(out, "rendered"))
    print("rendered %d/%d" % (sum(1 for v in rmap.values() if v), len(rmap)))

    print("\n-- scoring --")
    for p, docx, secs in converted:
        name = os.path.splitext(os.path.basename(p))[0]
        try:
            r = harness.evaluate(p, docx, os.path.join(out, "rendered"),
                                 save_images=True,
                                 img_dir=os.path.join(out, "cmp_" + name))
            r["convert_s"] = secs
            results.append(r)
            print(harness.brief(r))
        except Exception as e:
            results.append({"src": os.path.basename(p),
                            "eval_error": "%s: %s" % (type(e).__name__, e)})
            print("EVAL FAIL    %-28s %s" % (name, e))

    with open(os.path.join(out, "results.json"), "w") as f:
        json.dump(results, f, indent=1)

    fails = []
    failing = {}                    # {document: {metric, ...}} for the baseline
    for r in results:
        if "convert_error" in r or "eval_error" in r:
            fails.append((r["src"], "did not convert/score"))
            failing.setdefault(r["src"], set()).add("convert_or_eval")
            continue
        for k, thr in GATE.items():
            v = r.get(k)
            if v is None:
                continue
            if (thr is True and v is not True) or (thr is not True and v < thr):
                fails.append((r["src"], "%s=%s (want %s)" % (k, v, thr)))
                failing.setdefault(r["src"], set()).add(k)
    print("\n%d/%d documents pass the gate" % (len(results) - len(failing),
                                               len(results)))
    for s, why in fails:
        print("  FAIL %-34s %s" % (s[:34], why))
    print("\nwrote", os.path.join(out, "results.json"))
    if not gate:
        return 0

    lane = os.path.basename(out)
    if os.environ.get("GATE_BASELINE") == "update":
        _save_baseline(lane, failing)
        return 0

    known = _load_baseline(lane)
    novel, stale = [], []
    for doc, metrics in sorted(failing.items()):
        allowed = set(known.get(doc, []))
        for m in sorted(metrics - allowed):
            novel.append((doc, m))
    for doc, metrics in sorted(known.items()):
        now = failing.get(doc, set())
        if not now:
            stale.append((doc, "passes now; recorded as failing"))
        else:
            for m in sorted(set(metrics) - now):
                stale.append((doc, "%s passes now; recorded as failing" % m))

    if not known:
        print("\nno recorded baseline for lane '%s' -- gating on any failure."
              "\nRecord one with GATE_BASELINE=update once the run is trusted."
              % lane)
        return 1 if fails else 0
    print("\n%d known failure(s) in the record, %d new, %d stale"
          % (sum(len(v) for v in known.values()), len(novel), len(stale)))
    for doc, m in novel:
        print("  NEW FAILURE  %-30s %s" % (doc[:30], m))
    for doc, why in stale:
        print("  STALE RECORD %-30s %s" % (doc[:30], why))
    if novel or stale:
        print("\nThe record is measured on CI Linux, which is the number of "
              "record;\nlocal runs render with different fonts and may "
              "legitimately differ.")
    if stale:
        print("A stale record silently re-admits the regression it was meant "
              "to catch.\nRe-record with GATE_BASELINE=update and say so in the "
              "commit message.")
    return 1 if (novel or stale) else 0


def lanes(dirs):
    """Run the gate twice -- refine OFF and refine ON -- and report both.

    refine() tunes the layout against the same renderer the gate then measures
    with, so a refined-only number can improve because the loop memorised the
    oracle rather than because the converter got better. The no-refine lane is
    the uncontaminated number; the refined lane is the product default. Both
    are always printed side by side, and the exit code gates on the refined
    lane (what users get) while regressions in the raw lane stay visible.
    """
    import statistics as st
    results = {}
    for tag, rr in (("norefine", 0), ("refine", 3)):
        print("\n================ lane: %s ================" % tag)
        out = os.path.join(OUT, "lane_" + tag)
        code = main(dirs, out=out, gate=True, refine_rounds=rr)
        with open(os.path.join(out, "results.json")) as f:
            results[tag] = (code, json.load(f))
    print("\n================ lane comparison ================")
    print("%-10s %-9s %-11s %-9s %-9s" %
          ("lane", "pagematch", "within2pt", "livetext", "dy50med"))
    for tag in ("norefine", "refine"):
        _, rows = results[tag]
        ok = [r for r in rows if "convert_error" not in r and "eval_error" not in r]
        if not ok:
            print("%-10s (no results)" % tag)
            continue
        print("%-10s %d/%-7d %-11.3f %-9.4f %-9.2f" % (
            tag, sum(1 for r in ok if r.get("page_match")), len(ok),
            st.mean(r.get("within2pt", 0) for r in ok),
            st.mean(r.get("live_text_cov", 0) for r in ok),
            st.median([r.get("dy_p50", 0) for r in ok])))
    return results["refine"][0]


if __name__ == "__main__":
    args = sys.argv[1:] or [os.path.join(ROOT, "adv")]
    if os.environ.get("REFINE", "") == "lanes":
        sys.exit(lanes(args))
    sys.exit(main(args))
