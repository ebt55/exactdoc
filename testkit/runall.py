"""Convert every PDF in the given directories and score with the harness.

    python testkit/runall.py testkit/adv my_samples exactdoc_v1.1/corpus/pdfs

Writes batch/results.json plus side-by-side comparison PNGs per document.
Exit code is non-zero if any document regresses past the gate thresholds,
so this doubles as a CI check.
"""
import os, sys, json, time, glob, traceback

import _paths  # noqa: F401
import harness

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "batch")

# CI gate: a conversion must clear all of these.
GATE = {"page_match": True, "live_text_cov": 0.95, "doc_recall": 0.95,
        "word_recall": 0.90}


def main(dirs, out=OUT, gate=True):
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
            convert(p, docx)
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
    for r in results:
        if "convert_error" in r or "eval_error" in r:
            fails.append((r["src"], "did not convert/score"))
            continue
        for k, thr in GATE.items():
            v = r.get(k)
            if v is None:
                continue
            if (thr is True and v is not True) or (thr is not True and v < thr):
                fails.append((r["src"], "%s=%s (want %s)" % (k, v, thr)))
    print("\n%d/%d documents pass the gate" % (len(results) - len({f[0] for f in fails}),
                                               len(results)))
    for s, why in fails:
        print("  FAIL %-34s %s" % (s[:34], why))
    print("\nwrote", os.path.join(out, "results.json"))
    return 1 if (gate and fails) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or [os.path.join(ROOT, "adv")]))
