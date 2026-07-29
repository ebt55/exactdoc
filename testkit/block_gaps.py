"""Does a block-split threshold exist? Plot the two distributions it separates.

Protocol §12.6: never tune a threshold before plotting the distributions it is
supposed to separate. This repository has already proved once that a threshold
CANNOT exist for one such decision (table-cell gaps vs coincidental
same-baseline gaps: identical medians, 4.7em each), and a session was lost
tuning it before that was known.

The decision here is `_build_blocks_one`'s:

    same_block  <=>  gap <= reference_pitch * BLOCK_GAP_FACTOR

So for every consecutive pair of pdfium lines this measures `gap / reference`
and labels the pair with PyMuPDF's answer -- same block or not -- by pairing
lines across backends geometrically. Two distributions come out. If they
separate, a threshold exists and the plot says where; if they overlap, no
value of BLOCK_GAP_FACTOR can be right and the decision needs a different
signal.

Several candidate references are scored side by side, because the previous
attempt at this failed by changing the reference (a local median) without
checking it on the whole corpus -- it fixed a code listing and cut
02_research_paper's paragraphs in half.

    python testkit/block_gaps.py                 # corpus
    python testkit/block_gaps.py c6_long         # one document
"""
import argparse
import glob
import os
import sys
from collections import defaultdict

import _paths  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lines(ir):
    out = []
    for pno, p in enumerate(ir.pages, 1):
        for bi, b in enumerate(p.blocks):
            for ln in b.lines:
                out.append({"page": pno, "block": id(b), "base": ln.baseline,
                            "x0": ln.bbox[0], "x1": ln.bbox[2],
                            "size": max((s.size for s in ln.spans), default=10.0)})
    out.sort(key=lambda r: (r["page"], round(r["base"], 1), r["x0"]))
    return out


def _pair(a, b):
    """MuPDF line -> pdfium line, matched on page/baseline/x."""
    used, out = set(), {}
    for i, ra in enumerate(a):
        best, bd = None, None
        for j, rb in enumerate(b):
            if j in used or rb["page"] != ra["page"]:
                continue
            if abs(rb["base"] - ra["base"]) > 0.6 or abs(rb["x0"] - ra["x0"]) > 2.0:
                continue
            d = abs(rb["base"] - ra["base"]) + abs(rb["x0"] - ra["x0"]) / 10.0
            if bd is None or d < bd:
                best, bd = j, d
        if best is not None:
            used.add(best)
            out[j_key(ra)] = b[best]
    return out


def j_key(r):
    return (r["page"], round(r["base"], 1), round(r["x0"], 1))


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


def references(page_lines):
    """Candidate reference pitches for one page: {name: value}."""
    gaps = [b["base"] - a["base"] for a, b in zip(page_lines, page_lines[1:])]
    valid = [g for g in gaps if 0 < g < 60]
    if not valid:
        return {}
    med = _median(valid)
    # the modal pitch, to 0.5pt -- body text dominates a page by line count even
    # when a table's rows drag the median
    hist = defaultdict(int)
    for g in valid:
        hist[round(g * 2) / 2.0] += 1
    modal = max(hist.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    # the smallest pitch that is not noise: the 20th percentile
    p20 = sorted(valid)[max(0, int(0.2 * len(valid)) - 1)]
    return {"median": med, "modal": modal, "p20": p20}


def collect(path):
    from exactdoc.parse import parse_pdf as mu
    from exactdoc.parse_pdfium import parse_pdf as pf

    A = _lines(mu(path, keep_image_data=False))
    B = _lines(pf(path, keep_image_data=False))
    m = _pair(A, B)

    rows = []
    by_page = defaultdict(list)
    for r in B:
        by_page[r["page"]].append(r)
    for pno, pl in by_page.items():
        refs = references(pl)
        if not refs:
            continue
        for a, b in zip(pl, pl[1:]):
            gap = b["base"] - a["base"]
            if not (0 < gap < 60):
                continue
            ka = [k for k, v in m.items() if v is a]
            kb = [k for k, v in m.items() if v is b]
            if not ka or not kb:
                continue
            mu_a = next(x for x in A if j_key(x) == ka[0])
            mu_b = next(x for x in A if j_key(x) == kb[0])
            rows.append({"same": mu_a["block"] == mu_b["block"],
                         "gap": gap, "refs": refs,
                         "pagekey": (os.path.basename(path), pno)})
    return rows


def page_cuts(path):
    """{(document, page): adaptive cut} from the page's own gaps."""
    from exactdoc.parse_pdfium import parse_pdf as pf
    out = {}
    by_page = defaultdict(list)
    for r in _lines(pf(path, keep_image_data=False)):
        by_page[r["page"]].append(r)
    for pno, pl in by_page.items():
        gaps = [b["base"] - a["base"] for a, b in zip(pl, pl[1:])]
        gaps = [g for g in gaps if 0 < g < 60]
        out[(os.path.basename(path), pno)] = otsu(gaps)
    return out


def summarise(name, rows):
    if not rows:
        print("  %s: no comparable pairs" % name)
        return
    print("\n== %s  (%d consecutive line pairs)" % (name, len(rows)))
    print("  %-8s %-28s %-28s %s"
          % ("ref", "gap/ref WITHIN a block", "gap/ref AT a boundary", "separable?"))
    for ref in ("median", "modal", "p20"):
        same = sorted(r["gap"] / r["refs"][ref] for r in rows
                      if r["same"] and r["refs"].get(ref))
        diff = sorted(r["gap"] / r["refs"][ref] for r in rows
                      if not r["same"] and r["refs"].get(ref))
        if not same or not diff:
            continue
        # best achievable split, and what it costs
        best_err, best_t = None, None
        for t in [x / 100.0 for x in range(50, 400)]:
            err = sum(1 for v in same if v > t) + sum(1 for v in diff if v <= t)
            if best_err is None or err < best_err:
                best_err, best_t = err, t
        verdict = ("YES at %.2f (%d/%d misclassified)"
                   % (best_t, best_err, len(same) + len(diff))) if best_err == 0 \
            else "overlap: best %.2f still misses %d of %d" % (
                best_t, best_err, len(same) + len(diff))
        print("  %-8s p50 %.2f  max %.2f (n=%-4d) p50 %.2f  min %.2f (n=%-4d) %s"
              % (ref, _median(same), max(same), len(same),
                 _median(diff), min(diff), len(diff), verdict))


def otsu(gaps):
    """Unsupervised 1-D split of a page's gaps into 'inside' and 'between'.

    The per-document tables show every document separating cleanly at its OWN
    ratio and no single ratio serving them all, so the question is whether the
    split point can be found from the page itself rather than fixed in advance.
    This is Otsu's method on the sorted gaps: pick the cut maximising
    between-class variance.
    """
    xs = sorted(gaps)
    if len(xs) < 4:
        return None
    best, cut = None, None
    for i in range(1, len(xs)):
        lo, hi = xs[:i], xs[i:]
        if not lo or not hi:
            continue
        mlo = sum(lo) / len(lo)
        mhi = sum(hi) / len(hi)
        v = len(lo) * len(hi) * (mlo - mhi) ** 2
        if best is None or v > best:
            best, cut = v, (xs[i - 1] + xs[i]) / 2.0
    return cut


def evaluate_rules(rows, pages):
    """Score the shipped rule and an adaptive one against PyMuPDF's answer."""
    print("\n-- rule scoring (labels from PyMuPDF's own block boundaries) --")

    # shipped: gap <= median_pitch * 1.6
    err = sum(1 for r in rows
              if (r["gap"] <= r["refs"]["median"] * 1.6) != r["same"])
    print("  shipped   gap <= median * 1.60          %d/%d wrong (%.0f%%)"
          % (err, len(rows), 100.0 * err / max(1, len(rows))))

    for f in (1.6, 1.3, 1.15, 1.05):
        e = sum(1 for r in rows if (r["gap"] <= r["refs"]["p20"] * f) != r["same"])
        print("  fixed     gap <= p20 * %.2f            %d/%d wrong (%.0f%%)"
              % (f, e, len(rows), 100.0 * e / max(1, len(rows))))

    # adaptive: per-page Otsu cut on that page's own gaps
    e = miss = 0
    for r in rows:
        cut = pages.get(r["pagekey"])
        if cut is None:
            miss += 1
            continue
        if (r["gap"] <= cut) != r["same"]:
            e += 1
    print("  adaptive  per-page Otsu cut            %d/%d wrong (%.0f%%)%s"
          % (e, len(rows) - miss, 100.0 * e / max(1, len(rows) - miss),
             "" if not miss else "  [%d pairs on pages too small to cut]" % miss))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    srcs = sorted(glob.glob(os.path.join(ROOT, "corpus", "pdfs", "*.pdf")))
    srcs += sorted(glob.glob(os.path.join(ROOT, "testkit", "adv", "*.pdf")))
    if a.names:
        srcs = [s for s in srcs if any(k in os.path.basename(s) for k in a.names)]
    allrows, cuts = [], {}
    for s in srcs:
        rows = collect(s)
        allrows += rows
        cuts.update(page_cuts(s))
        summarise(os.path.splitext(os.path.basename(s))[0], rows)
    summarise("CORPUS", allrows)
    evaluate_rules(allrows, cuts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
