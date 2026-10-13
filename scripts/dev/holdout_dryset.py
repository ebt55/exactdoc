"""A 2-PDF synthetic stand-in for a sealed holdout, to prove the exam's plumbing end to end.

    python scripts/dev/holdout_dryset.py OUTDIR [--manifest-name holdout3.json] \
        [--promise-field promised_narrowed]

Writes OUTDIR/pdfs/{d01_short_letter.pdf, d02_long_report.pdf} with reportlab
(invariant mode: the same bytes every time), OUTDIR/<manifest name> in the sealed
manifest's shape (`file`, `sha256`, `pages`, `design_class`, both promise
fields) marked `"synthetic": true`, and OUTDIR/<stem>.sha256. One short
promised document (3 pages, so R2 and R3-short have a denominator) and one long
promised one (22 pages, so R4 and R3-long do). Nothing here touches the sealed
set; the exam prints a SYNTHETIC banner over any verdict read from it.
"""
import hashlib
import json
import os
import sys

WORDS = ("the committee reviewed each proposal against the published criteria and "
         "recorded its findings in plain language so that a reader who was not "
         "present can follow the reasoning from the evidence to the decision").split()


def _para(i, n=60):
    return " ".join(WORDS[(i * 7 + k) % len(WORDS)] for k in range(n)).capitalize() + "."


def _pdf(path, title, pages):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate
    st = getSampleStyleSheet()
    story = []
    for p in range(pages):
        story.append(Paragraph("%s, section %d" % (title, p + 1), st["Heading2"]))
        for i in range(4):
            story.append(Paragraph(_para(p * 4 + i), st["BodyText"]))
        if p < pages - 1:
            story.append(PageBreak())
    SimpleDocTemplate(path, pagesize=letter, title=title, author="exactdoc dry run",
                      invariant=1).build(story)


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def build(out, manifest_name="holdout2.json", promise_field="promised_b_narrowed"):
    """The synthetic set, its manifest naming the promise under `promise_field`
    (the exam's own field: holdout_exam.sh passes it from the exam's row), so the
    dry run reads the synthetic manifest the way the exam reads the sealed one."""
    pdfs = os.path.join(out, "pdfs")
    os.makedirs(pdfs, exist_ok=True)
    specs = [("d01_short_letter", "A short letter", 3, "ordinary-word"),
             ("d02_long_report", "A long report", 22, "long-report-ordinary")]
    docs = {}
    for key, title, pages, cls in specs:
        path = os.path.join(pdfs, key + ".pdf")
        _pdf(path, title, pages)
        import fitz
        with fitz.open(path) as d:
            got = d.page_count
        if got != pages:
            raise SystemExit("%s: built %d pages, wanted %d" % (key, got, pages))
        docs[key] = {"id": key, "file": key + ".pdf", "sha256": _sha(path),
                     "bytes": os.path.getsize(path), "pages": pages,
                     "producer": "ReportLab", "creator": "holdout_dryset.py",
                     "design_class": cls, "promised_a_current_bar": True,
                     "promised_b_narrowed": True, "reason_b": "synthetic"}
        docs[key][promise_field] = True
    man = {"schema": "exactdoc.holdout2.v0", "synthetic": True, "sealed": False,
           "note": "SYNTHETIC dry-run set for scripts/dev/holdout_exam.sh; not a sealed holdout",
           "documents": docs}
    mpath = os.path.join(out, manifest_name)
    with open(mpath, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
        fh.write("\n")
    digest = _sha(mpath)
    stem = os.path.splitext(manifest_name)[0]
    with open(os.path.join(out, stem + ".sha256"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("%s  %s\n" % (digest, manifest_name))
    return digest


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("outdir")
    ap.add_argument("--manifest-name", default="holdout2.json")
    ap.add_argument("--promise-field", default="promised_b_narrowed")
    a = ap.parse_args()
    print(build(a.outdir, a.manifest_name, a.promise_field))
