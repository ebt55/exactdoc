"""Live Google Docs sweep over the expansion corpus (non-gating, resumable).

    EXACTDOC_ROOT=<tree> python gdsweep.py OUTDIR [--only y28,y30]

Per document: convert with the gdocs candidate profile, round-trip through
Google Docs (upload -> export PDF -> delete), score the export against the
source with testkit/harness.evaluate plus quality_sweep.char_recall.
One JSON line per document in OUTDIR/rows.jsonl; finished documents are
skipped on a re-run, so an interrupted sweep resumes.
"""
import argparse
import glob
import json
import os
import sys
import time
import traceback

ROOT = os.environ["EXACTDOC_ROOT"]
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "testkit"))
import gdocs_oracle as go  # noqa: E402
import harness  # noqa: E402
import quality_sweep as qs  # noqa: E402
from exactdoc import options as O  # noqa: E402
from exactdoc.convert import convert  # noqa: E402
if os.environ.get("EXACTDOC_TRACKING_HONOURED") == "1":
    # A/B switch: restore the pre-2026-10-04 belief that Docs honours tracking
    from exactdoc import fonts as _F
    _F.GDOCS_HONOURS_RUN_TRACKING = True

if os.environ.get("EXACTDOC_NO_NEW_FACTORS") == "1":
    # A/B switch: drop the 2026-10-04 Calibri-family natural factors
    from exactdoc import docxout as _D
    for _k in ("carlito", "calibri", "cambria", "caladea"):
        _D.NATURAL_FACTORS.pop(_k, None)

if os.environ.get("EXACTDOC_OLD_FACTORS") == "1":
    # A/B switch: the pre-2026-10-04 natural factors for the re-measured families
    from exactdoc import docxout as _D2
    _D2.NATURAL_FACTORS.update({"arial": 1.144, "times new roman": 1.144,
        "courier new": 1.127, "georgia": 1.130, "roboto": 1.194, "noto serif": 1.360,
        "noto sans": 1.356, "verdana": 1.209, "vollkorn": 1.392, "consolas": 1.165})

KEYS = ("page_match", "src_pages", "out_pages", "word_recall", "doc_recall",
        "dx_p50", "dx_p90", "dy_p50", "dy_p90", "within2pt", "mean_ssim",
        "live_text_cov", "raster_frac")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--only", default="")
    ap.add_argument("--corpus", default="expansion", choices=("expansion", "gated", "both"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    dirs = {"expansion": ["fixtures_expansion"], "gated": ["fixtures"],
            "both": ["fixtures", "fixtures_expansion"]}[a.corpus]
    srcs = []
    for d in dirs:
        srcs += sorted(glob.glob(os.path.join(ROOT, "testkit", d, "*.pdf")))
    if a.only:
        pre = tuple(a.only.split(","))
        srcs = [s for s in srcs if os.path.basename(s).startswith(pre)]
    rows_path = os.path.join(a.out, "rows.jsonl")
    done = set()
    if os.path.exists(rows_path):
        with open(rows_path) as f:
            done = {json.loads(line)["doc"] for line in f if line.strip()}
    svc = go._service(interactive=False)
    for src in srcs:
        doc = os.path.basename(src)
        if doc in done:
            continue
        stem = os.path.splitext(doc)[0]
        docx = os.path.join(a.out, stem + ".docx")
        rendered = os.path.join(a.out, stem + ".gdocs.pdf")
        row = {"doc": doc}
        t0 = time.monotonic()
        try:
            convert(src, docx, options=O.PDFIUM_GDOCS_CANDIDATE)
            row["convert_s"] = round(time.monotonic() - t0, 1)
            for attempt in (1, 2, 3):
                try:
                    go.roundtrip(svc, docx, rendered)
                    break
                except go.RoundtripError as exc:
                    row["roundtrip_retry_%d" % attempt] = exc.stage
                    if exc.stage == "cleanup" or attempt == 3:
                        raise
                    time.sleep(5 * attempt)
            res = harness.evaluate(src, docx, a.out, save_images=False,
                                   rendered_pdf=rendered)
            row.update({k: res.get(k) for k in KEYS})
            cr = qs.char_recall(src, rendered)
            row["char_recall"], row["char_doc_recall"] = cr
        except Exception as exc:
            row["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            row["trace"] = traceback.format_exc()[-600:]
            if isinstance(exc, go.RoundtripError) and exc.stage == "cleanup":
                print("CLEANUP FAILURE -- stopping; see the orphan ledger", flush=True)
                with open(rows_path, "a") as f:
                    f.write(json.dumps(row) + "\n")
                return 2
        row["total_s"] = round(time.monotonic() - t0, 1)
        with open(rows_path, "a") as f:
            f.write(json.dumps(row) + "\n")
        print(doc, {k: row.get(k) for k in ("page_match", "src_pages", "out_pages",
                                             "word_recall", "char_recall", "dy_p50",
                                             "error")}, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
