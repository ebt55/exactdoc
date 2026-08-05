"""Probe: how much of the expansion corpus's page inflation is a two-line spill?

    python testkit/probe_thin_pages.py
    python testkit/probe_thin_pages.py --only y01 y02 --arm pdfium
    python testkit/probe_thin_pages.py --json /tmp/thin.json

WHY THIS EXISTS
---------------
The NIST and IRS documents in `fixtures_expansion/` paginate long. Measured at
e5e7f30 on the parity profile, the excess is not spread across the document --
it is EXACTLY thin pages, and on y02 under the reference arm the identity is
exact: page_err +59, thin pages 59.

Every source page ends in an explicit page break, so the reconstruction has zero
slack at the bottom (`refine.py` says the same thing from the closed-loop side).
When a page's content renders one or two lines taller than the page box, those
lines flow onto a new rendered page -- and then the hard break fires and advances
again, stranding the spill alone. A one-line overflow costs a whole page.

WHAT IT COUNTS
--------------
Per document, per arm: source pages, rendered pages, page_err, and the rendered
pages carrying fewer than THIN_LINES lines. Those thin pages are then split by
how many BODY lines they carry:

    <= 2 lines   a spill. Absorbing two lines of overflow reclaims this page.
    >  2 lines   a genuinely short page -- a section end, a figure page. No
                 amount of slack compression reclaims it, and trying would only
                 crush the spacing of a page that was already correct.

That split is the point of the probe: it bounds what a spill fix can win, before
one is written. A count of thin pages alone does not, because it silently
promises pages that are short because the source was short.

Body lines are counted by geometry -- anything whose vertical midpoint falls
outside the middle 84% of the page is running furniture, not content. A one-line
spill page still renders its running head and page number, so counting raw lines
calls it a three-line page and hides the whole effect.

This probe measures and never adjudicates. It reads the expansion corpus, which
`testkit/gate.py` never sees and `parity_policy.json` governs none of; its exit
code is 1 only when a document could not be measured at all.
"""
import argparse
import json
import os
import sys
import time

import _paths  # noqa: F401
import backend_parity
import corpus_manifest
import harness

import fitz

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "probe_thin_out")

THIN_LINES = 20      # a rendered page below this is "thin"; the predecessor's
                     # threshold, kept so the numbers stay comparable
SPILL_LINES = 2      # body lines at or below which a thin page is a spill
FURNITURE_BAND = 0.08   # fraction of page height that is header/footer, each end


def line_profile(pdf_path):
    """-> [(total_lines, body_lines)] for every page of a rendered PDF."""
    doc = fitz.open(pdf_path)
    rows = []
    try:
        for page in doc:
            h = page.rect.height
            lo, hi = h * FURNITURE_BAND, h * (1.0 - FURNITURE_BAND)
            total = body = 0
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:      # 0 = text; images have no lines
                    continue
                for line in block.get("lines", ()):
                    text = "".join(s.get("text", "") for s in line.get("spans", ()))
                    if not text.strip():
                        continue
                    total += 1
                    mid = (line["bbox"][1] + line["bbox"][3]) / 2.0
                    if lo <= mid <= hi:
                        body += 1
            rows.append((total, body))
    finally:
        doc.close()
    return rows


def summarise(src_pages, profile):
    thin = [(t, b) for t, b in profile if t < THIN_LINES]
    hist = {}
    for _, b in thin:
        hist[b] = hist.get(b, 0) + 1
    return {"src_pages": src_pages,
            "out_pages": len(profile),
            "page_err": len(profile) - src_pages,
            "thin": len(thin),
            "spill": sum(1 for _, b in thin if b <= SPILL_LINES),
            "short": sum(1 for _, b in thin if b > SPILL_LINES),
            "body_hist": {str(k): v for k, v in sorted(hist.items())}}


def measure_arm(backend, doc_ids, profile, out_root):
    """Convert and render one arm. -> {doc_id: summary}."""
    from exactdoc.convert import convert

    options = profile.replace(backend=backend)
    out = os.path.join(out_root, backend)
    os.makedirs(out, exist_ok=True)
    pairs = []
    for doc_id in doc_ids:
        src = corpus_manifest.expansion_fixture_path(doc_id)
        docx = os.path.join(out, os.path.splitext(doc_id)[0] + ".docx")
        t0 = time.time()
        convert(src, docx, options=options)
        print("  convert %-30s %-8s %5.1fs" % (doc_id[:30], backend,
                                               time.time() - t0))
        pairs.append((doc_id, src, docx))
    harness.batch_docx_to_pdf([p[2] for p in pairs], os.path.join(out, "r"))

    res = {}
    for doc_id, src, docx in pairs:
        rendered = os.path.join(out, "r",
                                os.path.splitext(os.path.basename(docx))[0] + ".pdf")
        if not os.path.exists(rendered):
            res[doc_id] = {"error": "the render oracle produced no PDF"}
            continue
        doc = fitz.open(src)
        src_pages = doc.page_count
        doc.close()
        res[doc_id] = summarise(src_pages, line_profile(rendered))
    return res


def report(rows, arms):
    out = ["", "%-30s %-8s %5s %5s %6s %6s %6s %6s"
           % ("document", "arm", "src", "out", "err", "thin", "spill", "short")]
    for doc_id in sorted(rows):
        for arm in arms:
            r = rows[doc_id].get(arm) or {}
            if "error" in r:
                out.append("%-30s %-8s %s" % (doc_id[:30], arm, r["error"]))
                continue
            out.append("%-30s %-8s %5d %5d %+6d %6d %6d %6d"
                       % (doc_id[:30], arm, r["src_pages"], r["out_pages"],
                          r["page_err"], r["thin"], r["spill"], r["short"]))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", choices=backend_parity.PROFILE_NAMES,
                    default="candidate")
    ap.add_argument("--only", nargs="+", default=["y01", "y02", "y03", "y09"],
                    help="substrings; the documents to measure")
    ap.add_argument("--arm", nargs="+", default=["pymupdf", "pdfium"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    manifest = corpus_manifest.load_expansion()
    problems = corpus_manifest.verify_expansion(manifest)
    if problems:
        print("expansion corpus does not match corpus_expansion.json:")
        for kind, doc, why in problems:
            print("  %-11s %-30s %s" % (kind, doc[:30], why))
        return 1
    doc_ids = [d for d in sorted(manifest["documents"])
               if any(k in d for k in a.only)]
    if not doc_ids:
        print("--only matched no document in corpus_expansion.json")
        return 1

    profile = backend_parity.conversion_profile(a.profile)
    out_root = os.path.join(a.out or OUT, a.profile)
    os.makedirs(out_root, exist_ok=True)
    print("profile    %s (arms differ only in backend)" % profile.profile_id())
    print("documents  %s" % ", ".join(doc_ids))
    print("thin       < %d lines;  spill  <= %d body lines"
          % (THIN_LINES, SPILL_LINES))

    rows = {}
    for arm in a.arm:
        for doc_id, summary in measure_arm(arm, doc_ids, profile, out_root).items():
            rows.setdefault(doc_id, {})[arm] = summary
    print(report(rows, a.arm))

    payload = {"schema": "exactdoc.thin-page-probe.v1", "gating": False,
               "profile": a.profile, "profile_id": profile.profile_id(),
               "thin_lines": THIN_LINES, "spill_lines": SPILL_LINES,
               "furniture_band": FURNITURE_BAND, "documents": rows}
    path = a.json or os.path.join(out_root, "thin_pages.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
    print("\nwrote %s" % path)
    print("This probe measures the expansion corpus and gates nothing.")
    return 1 if any("error" in r for d in rows.values() for r in d.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
