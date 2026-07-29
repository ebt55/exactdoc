"""Where exactly do the two parsers disagree on geometry?

backend_parity reports the END of the pipeline: pdfium converts with 9 more
placement regressions than PyMuPDF (within-2pt 0.510 -> 0.291). That says the
words land ~2pt off; it does not say which extracted quantity is wrong.

Only four numbers reach the writer's vertical model:

    para_top    = first_baseline - (leading - 0.21 * size)
    para_height = n_lines * leading
    leading     = baseline[i+1] - baseline[i]      (within a block)

so an error can only enter through the BASELINE, the SIZE, or the LINE
GROUPING that defines `leading` and `n_lines`. This matches lines between the
two backends by text and reports each of those separately, so the residual is
attributed instead of guessed.

    python testkit/backend_geom.py testkit/adv/c7_code.pdf
    python testkit/backend_geom.py --all
"""
import argparse
import os
import re
import statistics as st
from collections import defaultdict

import _paths  # noqa: F401

from exactdoc.parse import parse_pdf as parse_mu
from exactdoc.parse_pdfium import parse_pdf as parse_px

TK = os.path.dirname(os.path.abspath(__file__))


def _norm(t):
    return re.sub(r"\s+", "", t or "")


def lines_of(doc):
    """(page, normalised text) -> line record, keeping only unambiguous keys."""
    seen, out = defaultdict(int), {}
    for p in doc.pages:
        for bi, b in enumerate(p.blocks):
            for li, ln in enumerate(b.lines):
                k = (p.number, _norm(ln.text))
                if len(k[1]) < 8:
                    continue
                seen[k] += 1
                out[k] = dict(base=ln.baseline, top=ln.bbox[1], bot=ln.bbox[3],
                              size=ln.spans[0].size if ln.spans else 0.0,
                              block=bi, idx=li,
                              nlines=len(b.lines))
    return {k: v for k, v in out.items() if seen[k] == 1}


def leadings(doc):
    """Baseline deltas inside each block, keyed by the FOLLOWING line's text."""
    out = {}
    for p in doc.pages:
        for b in doc_blocks(p):
            for a, c in zip(b, b[1:]):
                k = (p.number, _norm(c.text))
                if len(k[1]) >= 8:
                    out[k] = c.baseline - a.baseline
    return out


def doc_blocks(page):
    return [b.lines for b in page.blocks if len(b.lines) > 1]


def report(path):
    name = os.path.basename(path)
    try:
        mu, px = parse_mu(path, keep_image_data=False), parse_px(path, keep_image_data=False)
    except Exception as e:                                   # noqa: BLE001
        print("%-24s parse failed: %s" % (name, e)); return None

    lm, lp = lines_of(mu), lines_of(px)
    common = sorted(set(lm) & set(lp))
    if len(common) < 20:
        print("%-24s only %d matched lines" % (name, len(common))); return None

    d_base = [lp[k]["base"] - lm[k]["base"] for k in common]
    d_top = [lp[k]["top"] - lm[k]["top"] for k in common]
    d_size = [lp[k]["size"] - lm[k]["size"] for k in common]

    gm, gp = leadings(mu), leadings(px)
    gk = sorted(set(gm) & set(gp) & set(common))
    d_lead = [gp[k] - gm[k] for k in gk]

    # how often do the two backends put a line in a block of the same length?
    same_grp = sum(1 for k in common if lm[k]["nlines"] == lp[k]["nlines"])

    def stat(v):
        if not v:
            return "        n/a"
        a = sorted(abs(x) for x in v)
        return "med %+7.3f  p90 %6.3f  max %6.3f" % (
            st.median(v), a[int(.9 * (len(a) - 1))], a[-1])

    print("\n=== %s  (%d matched lines) ===" % (name, len(common)))
    print("  baseline dy   %s" % stat(d_base))
    print("  bbox top dy   %s" % stat(d_top))
    print("  font size d   %s" % stat(d_size))
    print("  leading   d   %s   (%d pairs)" % (stat(d_lead), len(d_lead)))
    print("  same block length: %d/%d (%.0f%%)"
          % (same_grp, len(common), 100.0 * same_grp / len(common)))

    exact_b = sum(1 for x in d_base if abs(x) < 0.01)
    exact_l = sum(1 for x in d_lead if abs(x) < 0.01)
    print("  baselines identical: %d/%d (%.0f%%)   leadings identical: %d/%d (%.0f%%)"
          % (exact_b, len(d_base), 100.0 * exact_b / len(d_base),
             exact_l, len(d_lead), 100.0 * exact_l / max(1, len(d_lead))))
    return dict(name=name, base=d_base, lead=d_lead, size=d_size,
                grp=(same_grp, len(common)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="*")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    paths = list(a.src)
    if a.all or not paths:
        for d in ("adv", "real"):
            dd = os.path.join(TK, d)
            if os.path.isdir(dd):
                paths += [os.path.join(dd, f) for f in sorted(os.listdir(dd))
                          if f.endswith(".pdf")]
    rs = [r for r in (report(p) for p in paths) if r]
    if len(rs) > 1:
        ab = [abs(x) for r in rs for x in r["base"]]
        al = [abs(x) for r in rs for x in r["lead"]]
        asz = [abs(x) for r in rs for x in r["size"]]
        g0 = sum(r["grp"][0] for r in rs); g1 = sum(r["grp"][1] for r in rs)
        print("\n=== corpus (%d documents) ===" % len(rs))
        for lbl, v in (("|baseline dy|", ab), ("|leading d|", al), ("|size d|", asz)):
            if v:
                print("  %-14s median %.3f  mean %.3f  >0.5pt in %.0f%% of lines"
                      % (lbl, st.median(v), sum(v) / len(v),
                         100.0 * sum(1 for x in v if x > 0.5) / len(v)))
        print("  same block length: %d/%d (%.0f%%)" % (g0, g1, 100.0 * g0 / max(1, g1)))


if __name__ == "__main__":
    main()
