"""Fly a probe set's <doc>.<A>.gdocs.docx / <doc>.<B>.gdocs.docx pairs live; score vs source.

    EXACTDOC_ROOT=<tree> python flypairs.py PROBE_DIR OUT_DIR A B
Sources: testkit/fixtures, testkit/fixtures_expansion, or <PROBE_DIR>/../<doc>.pdf.
Rows -> OUT_DIR/rows.json (written with LF newlines).
"""
import glob, json, os, sys
ROOT = os.environ["EXACTDOC_ROOT"]
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "testkit"))
import gdocs_oracle as go, harness, quality_sweep as qs

PROBE, OUT, A, B = sys.argv[1:5]
KEYS = ("src_pages", "out_pages", "word_recall", "within2pt", "dy_p50", "mean_ssim", "live_text_cov")
def source(stem):
    for d in (os.path.join(ROOT, "testkit", "fixtures"), os.path.join(ROOT, "testkit", "fixtures_expansion"),
              os.path.join(PROBE, "..")):
        p = os.path.join(d, stem + ".pdf")
        if os.path.exists(p): return p
    raise FileNotFoundError(stem)
stems = sorted({os.path.basename(p).split(".")[0] for p in glob.glob(os.path.join(PROBE, "*.%s.gdocs.docx" % B))})
svc = go._service(interactive=False)
rows = []
for stem in stems:
    src = source(stem)
    for v in (A, B):
        docx = os.path.join(PROBE, "%s.%s.gdocs.docx" % (stem, v))
        if not os.path.exists(docx):
            continue
        work = os.path.join(OUT, stem + "." + v); os.makedirs(work, exist_ok=True)
        pdf = os.path.join(work, "gdocs.pdf")
        if not os.path.exists(pdf):
            go.roundtrip(svc, docx, pdf)
        res = harness.evaluate(src, docx, work, save_images=False, rendered_pdf=pdf)
        row = {"doc": stem, "v": v, **{k: res.get(k) for k in KEYS},
               "scorer": harness.HARNESS_READING}
        row["char_recall"] = qs.char_recall(src, pdf)[0]
        rows.append(row); print(json.dumps(row), flush=True)
with open(os.path.join(OUT, "rows.json"), "w", newline="\n") as f:
    json.dump(rows, f, indent=1)
