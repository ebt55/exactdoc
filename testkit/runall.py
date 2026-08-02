"""Convert the manifest corpus, score it with the harness, and gate on it.

    python testkit/runall.py                        # both lanes, the default
    python testkit/runall.py --lane product         # one lane
    python testkit/runall.py --absolute             # release-qualification gate
    GATE_BASELINE=update python testkit/runall.py   # re-record the numbers

Two distinct lanes always run. `raw` is the open-loop control
(`exactdoc.options.RAW`); `product` is exactly what ships and includes the
LibreOffice correction loop. A product-only number can improve because the loop
memorised its oracle rather than because the converter got better, so **the exit
code gates on both**.

The decision itself is `testkit/gate.py`, tested independently in
`tests/test_gate_mutations.py`. This file's job is to produce numbers and hand
them over; it makes no policy of its own.

Writes, per lane, into testkit/batch/lane_<name>/:
    results.json    every harness result
    verdict.json    what the gate decided and why
and folds both, plus the environment, into testkit/batch/evidence.json.
"""
import argparse
import glob
import json
import os
import sys
import time
import traceback

import _paths  # noqa: F401
import evidence
import gate
import harness

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(ROOT)
OUT = os.path.join(ROOT, "batch")
EVIDENCE = os.path.join(OUT, "evidence.json")


# ------------------------------------------------------------------- the corpus
def resolve_corpus(manifest, dirs=None):
    """-> (paths, problems). The frozen fixtures, verified byte-for-byte.

    The corpus is 16 committed PDFs pinned by SHA-256, not a directory that a
    generator refilled before the run. It was the latter, and the numbers were
    not reproducible because of it: the baseline was recorded against a corpus
    built with Chromium 149, CI runs a runner that ships Chromium 150, and
    `c4_i18n` came out a different file with 5x the vertical drift. See
    `corpus_manifest.py` for the full account.

    Identity is checked here rather than trusted, so a run cannot proceed on
    inputs that are not the inputs the baseline describes.
    """
    import corpus_manifest
    problems, paths = [], []
    for kind, doc, why in corpus_manifest.verify(manifest):
        problems.append((kind, doc, why))
    bad = set(d for k, d, _ in problems if k in ("missing", "identity",
                                                 "unmeasured", "duplicate"))
    for doc_id in sorted(manifest.get("documents", {})):
        if doc_id in bad:
            continue
        paths.append(corpus_manifest.fixture_path(doc_id, manifest))
    return paths, problems


# ------------------------------------------------------------------- one lane
def run_lane(lane, paths, options, out_dir, baseline=None, manifest=None,
             absolute=False, save_images=True):
    """Convert + score + gate one lane. Returns (results, verdict)."""
    from exactdoc.convert import convert

    os.makedirs(out_dir, exist_ok=True)
    results, converted = [], []
    print("\n================ lane: %s (%s) ================"
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
            print("CONVERT FAIL %-28s %s" % (name, e))

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
            print("EVAL FAIL    %-28s %s" % (name, e))

    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    verdict = gate.check(lane, results, manifest=manifest, baseline=baseline,
                         absolute=absolute)
    with open(os.path.join(out_dir, "verdict.json"), "w") as f:
        json.dump(verdict.as_dict(), f, indent=1)
    print("\n" + verdict.report())
    return results, verdict


# ----------------------------------------------------------------------- main
def main(argv=None):
    from exactdoc.options import LANES, validate_lanes

    try:
        validate_lanes()
    except Exception as e:
        print("invalid gate lane contract: %s" % e)
        return 2

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dirs", nargs="*", default=None,
                    help="(compatibility) extra directories to cross-check for "
                         "unexpected documents; the corpus itself comes from "
                         "the manifest")
    ap.add_argument("--lane", choices=sorted(LANES) + ["both"], default="both")
    ap.add_argument("--absolute", action="store_true",
                    help="also apply the release-qualification thresholds")
    ap.add_argument("--backend", default=None,
                    help="override the profile's backend for every lane")
    ap.add_argument("--no-images", action="store_true",
                    help="skip the side-by-side comparison PNGs")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--evidence", default=None,
                    help="evidence JSON to merge into (default <out>/evidence.json)")
    a = ap.parse_args(argv)
    updating = os.environ.get("GATE_BASELINE") == "update"

    manifest = gate.load_manifest()
    if manifest is None:
        print("no corpus manifest at %s -- the gate cannot know which documents "
              "it is supposed to have measured." % gate.MANIFEST_PATH)
        return 2
    paths, problems = resolve_corpus(manifest, a.dirs or None)
    for kind, doc, why in problems:
        print("CORPUS %-11s %-28s %s" % (kind, doc[:28], why))
    if not paths:
        print("no corpus documents resolved; run the generators first")
        return 2

    env = evidence.environment()
    if not env["canonical"]:
        print("\nNOTE: %s is not the canonical environment. CI Linux is the "
              "number of record; local runs render with different fonts and may "
              "legitimately differ inside tolerance." % env["os"])

    lanes = sorted(LANES) if a.lane == "both" else [a.lane]
    if updating and a.lane != "both":
        print("refusing to record a baseline for one lane: raw and product "
              "must be measured together from the same code.")
        return 2
    verdicts, lane_evidence, records = {}, {}, {}
    for lane in lanes:
        options = LANES[lane]
        if a.backend:
            options = options.replace(backend=a.backend)
        out_dir = os.path.join(a.out, "lane_" + lane)
        try:
            baseline = None if updating else gate.load_lane(lane)
        except gate.BaselineInvalid as e:
            print("\nBASELINE INVALID\n  %s" % e)
            return 2
        results, verdict = run_lane(
            lane, paths, options, out_dir, baseline=baseline, manifest=manifest,
            absolute=a.absolute, save_images=not a.no_images)
        verdicts[lane] = verdict
        rec = gate.record(lane, results)
        records[lane] = rec
        lane_evidence[lane] = {"profile": options.as_dict(),
                               "profile_id": options.profile_id(),
                               "documents": rec["documents"],
                               "aggregate": rec["aggregate"],
                               "verdict": verdict.as_dict(),
                               "results": results}

    # One write, after every lane has run, or none at all.
    if updating:
        try:
            gate.check_recordable(records, manifest, env)
        except gate.RecordRefused as e:
            print("\nBASELINE NOT RECORDED\n  %s" % e)
            return 2
        gate.save_lanes(records, environment=env)
        print("\nrecorded numeric baseline for %s" % ", ".join(sorted(records)))

    ev_path = a.evidence or os.path.join(a.out, "evidence.json")
    shipped = LANES.get("product")
    profile = dict(shipped.as_dict(), profile_id=shipped.profile_id()) \
        if "product" in lanes else None
    evidence.merge(ev_path, git=evidence.git_state(), environment=env,
                   profile=profile,
                   corpus={"manifest_documents": len(manifest.get("documents", {})),
                           "resolved": len(paths),
                           "problems": [{"kind": k, "document": d, "detail": w}
                                        for k, d, w in problems]},
                   lanes=lane_evidence)
    print("\n-- evidence --\n%s" % evidence.summarise(
        json.load(open(ev_path))))
    print("\nwrote %s" % ev_path)

    if problems:
        print("\nThe corpus did not match the manifest. Numbers from an "
              "incomplete or unexpected corpus are not comparable to the "
              "baseline, so this is a failure and not a warning.")
        return 1
    if updating:
        return 0
    return 0 if all(v.ok for v in verdicts.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
