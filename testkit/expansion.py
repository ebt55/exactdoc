"""Measure the expansion corpus with the gate's metrics and none of its authority.

    python testkit/expansion.py                     # both lanes
    python testkit/expansion.py --lane product      # one lane
    python testkit/expansion.py --tier ordinary_digital

**This never gates.** It imports nothing from `gate.py`, reads no baseline,
makes no comparison, and returns 0 whatever the numbers say. A metric here is an
observation about documents nobody has promised anything about yet.

The distinction is the whole reason this file exists rather than a `--corpus`
flag on `runall.py`. `runall.py` resolves `corpus_manifest.json`, hands the paths
to `gate.check`, and exits on the verdict; every number it produces is bound to
`gate_baseline.json`. Adding 16 documents to that path would compare a
32-document run against a 16-document baseline and call the difference a
regression. So the expansion corpus gets its own runner, and the gate keeps its
own corpus, and neither file knows the other's documents exist.

What it will refuse to do: run at all on a corpus that does not match
`corpus_expansion.json`. Measuring bytes that are not the recorded bytes
produces numbers that describe nothing, and that failure has already cost this
repository three red pull requests -- see `corpus_manifest.py`.

Exit codes say something narrow and honest:

    0    every document converted, rendered and scored
    1    the corpus did not match its manifest, or a document failed to convert
         or score -- an infrastructure failure, never a fidelity judgement

Writes per lane into testkit/expansion_out/lane_<name>/:
    results.json     every harness result
    summary.json     per-tier aggregates
"""
import argparse
import json
import os
import sys
import time
import traceback

import _paths  # noqa: F401
import corpus_manifest
import harness

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "expansion_out")

# The metrics worth reporting per tier. Deliberately the same names `gate.py`
# and `gdocs_quality_policy.json` use, so a promoted document's numbers mean the
# same thing before and after promotion. Same names, no thresholds.
REPORTED = ("live_text_cov", "doc_recall", "word_recall", "within2pt",
            "dy_p50", "mean_ssim", "raster_frac")


def resolve(tier=None):
    """-> (paths, specs, problems). Fail closed on any identity mismatch."""
    manifest = corpus_manifest.load_expansion()
    problems = corpus_manifest.verify_expansion(manifest)
    documents = manifest.get("documents", {})
    paths, specs = [], {}
    for doc_id in sorted(documents):
        spec = documents[doc_id]
        if tier and spec.get("tier") != tier:
            continue
        paths.append(corpus_manifest.expansion_fixture_path(doc_id))
        specs[doc_id] = spec
    return paths, specs, problems


def run_lane(lane, paths, options, out_dir, save_images=False):
    """Convert + render + score one lane. No verdict is computed anywhere here."""
    from exactdoc.convert import convert

    os.makedirs(out_dir, exist_ok=True)
    results, converted = [], []
    print("\n================ expansion lane: %s (%s) ================"
          % (lane, options.profile_id()))
    for p in paths:
        name = os.path.splitext(os.path.basename(p))[0]
        docx = os.path.join(out_dir, name + ".docx")
        t0 = time.time()
        try:
            convert(p, docx, options=options)
            converted.append((p, docx, round(time.time() - t0, 2)))
        except Exception as e:
            results.append({"src": os.path.basename(p),
                            "convert_error": "%s: %s" % (type(e).__name__, e),
                            "trace": traceback.format_exc()[-1200:]})
            print("CONVERT FAIL %-30s %s" % (name, e))

    print("\n-- LibreOffice batch render --")
    rmap = harness.batch_docx_to_pdf([d for _, d, _ in converted],
                                     os.path.join(out_dir, "rendered"))
    print("rendered %d/%d" % (sum(1 for v in rmap.values() if v), len(rmap)))

    print("\n-- scoring --")
    for p, docx, secs in converted:
        name = os.path.splitext(os.path.basename(p))[0]
        try:
            r = harness.evaluate(p, docx, os.path.join(out_dir, "rendered"),
                                 save_images=save_images,
                                 img_dir=os.path.join(out_dir, "cmp_" + name))
            r["convert_s"] = secs
            results.append(r)
            print(harness.brief(r))
        except Exception as e:
            results.append({"src": os.path.basename(p),
                            "eval_error": "%s: %s" % (type(e).__name__, e)})
            print("EVAL FAIL    %-30s %s" % (name, e))

    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    return results


def summarise(results, specs):
    """Per-tier medians and the documents that did not produce a number.

    A median, not a mean: one document failing to render would drag a mean and
    make a broken run look like a merely poor one. And the failure list is
    reported separately from the statistics rather than folded into them,
    because "we could not measure this" is not a low score.
    """
    def median(values):
        values = sorted(values)
        if not values:
            return None
        mid = len(values) // 2
        if len(values) % 2:
            return values[mid]
        return (values[mid - 1] + values[mid]) / 2.0

    by_tier, broken = {}, []
    for r in results:
        doc_id = r.get("src")
        spec = specs.get(doc_id, {})
        tier = spec.get("tier", "unclassified")
        row = by_tier.setdefault(tier, {"documents": 0, "measured": 0,
                                        "metrics": {}, "page_match": 0})
        row["documents"] += 1
        if "convert_error" in r or "eval_error" in r or "error" in r:
            broken.append((doc_id, r.get("convert_error") or r.get("eval_error")
                           or r.get("error")))
            continue
        row["measured"] += 1
        if r.get("page_match"):
            row["page_match"] += 1
        for metric in REPORTED:
            value = r.get(metric)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                row["metrics"].setdefault(metric, []).append(float(value))
    for row in by_tier.values():
        row["metrics"] = {m: round(median(v), 4)
                          for m, v in sorted(row["metrics"].items())}
    return by_tier, broken


def report(by_tier, broken):
    lines = []
    for tier, row in sorted(by_tier.items()):
        lines.append("  %s: %d document(s), %d measured, %d page-exact"
                     % (tier, row["documents"], row["measured"], row["page_match"]))
        for metric, value in sorted(row["metrics"].items()):
            lines.append("      median %-14s %8.4f" % (metric, value))
    if broken:
        lines.append("  %d document(s) produced no measurement:" % len(broken))
        for doc_id, why in broken:
            lines.append("      %-30s %s" % (doc_id, str(why)[:80]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lane", choices=["raw", "product", "both"], default="both")
    ap.add_argument("--tier", default=None,
                    help="measure only one tier (%s)" % ", ".join(corpus_manifest.TIERS))
    ap.add_argument("--save-images", action="store_true",
                    help="keep per-page comparison rasters (slow, large)")
    a = ap.parse_args(argv)

    paths, specs, problems = resolve(a.tier)
    if problems:
        print("expansion corpus does not match corpus_expansion.json:")
        for kind, doc, why in problems:
            print("  %-11s %-30s %s" % (kind, doc[:30], why))
        print("\nRefusing to measure. Numbers computed over bytes that are not "
              "the recorded bytes describe nothing at all.")
        return 1
    if not paths:
        print("no expansion fixtures%s -- nothing to measure."
              % (" in tier %s" % a.tier if a.tier else ""))
        # Rule: a loop over nothing is not a pass.
        return 1

    from exactdoc.options import LANES
    lanes = ["raw", "product"] if a.lane == "both" else [a.lane]
    print("expansion corpus: %d document(s)%s"
          % (len(paths), " in tier %s" % a.tier if a.tier else ""))

    failed = False
    payload = {"schema": "exactdoc.expansion-measurement.v1", "gating": False,
               "documents": len(paths), "tier_filter": a.tier, "lanes": {}}
    for lane in lanes:
        out_dir = os.path.join(OUT, "lane_" + lane)
        results = run_lane(lane, paths, LANES[lane], out_dir,
                           save_images=a.save_images)
        by_tier, broken = summarise(results, specs)
        if broken or len(results) != len(paths):
            failed = True
        print("\n-- %s summary (NON-GATING) --" % lane)
        print(report(by_tier, broken))
        payload["lanes"][lane] = {"tiers": by_tier,
                                  "unmeasured": [d for d, _ in broken]}
        with open(os.path.join(out_dir, "summary.json"), "w") as f:
            json.dump(payload["lanes"][lane], f, indent=1, sort_keys=True)

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "expansion.json"), "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)

    print("\nThese numbers gate nothing. No baseline describes this corpus and "
          "testkit/gate.py never saw it; promotion into the gate is the "
          "deliberate commit in docs/corpus-expansion.md §7.")
    if failed:
        print("\nExit 1: at least one document produced no measurement. That is "
              "an infrastructure failure, not a fidelity judgement.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
