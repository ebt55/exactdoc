"""Decompose vertical drift: constant per-page offset vs. accumulation down page.

If drift is mostly a constant offset per page, a cheap per-page top correction
removes it. If it grows with y, the height model is wrong and needs closed-loop
correction. Reports, per page:
    n      matched words
    med    median dy (the constant part)
    slope  d(dy)/d(y_src)  -- accumulation rate, pt per pt
    resid  median |dy - (med + slope*y)|  -- irreducible scatter
"""
import _paths  # noqa: F401  (sets sys.path, finds soffice/chrome)
import sys, os
import numpy as np
import harness

src, rendered = sys.argv[1], sys.argv[2]
sw, ow = harness.page_words(src), harness.page_words(rendered)

print("%-4s %-6s %-8s %-9s %-8s %s" % ("pg", "n", "med_dy", "slope", "resid", "explained"))
allres = []
for i, sp in enumerate(sw):
    if i >= len(ow):
        break
    by = {}
    for j, o in enumerate(ow[i]):
        by.setdefault(o[0], []).append(j)
    cands = []
    for si, s in enumerate(sp):
        for oj in by.get(s[0], ()):
            o = ow[i][oj]
            cands.append((abs(o[2] - s[2]) * 3 + abs(o[1] - s[1]), si, oj))
    cands.sort()
    us, uo, ys, dys = set(), set(), [], []
    for d, si, oj in cands:
        if si in us or oj in uo:
            continue
        us.add(si); uo.add(oj)
        ys.append(sp[si][2]); dys.append(ow[i][oj][2] - sp[si][2])
    if len(ys) < 8:
        print("%-4d %-6d (too few matches)" % (i + 1, len(ys)))
        continue
    ys, dys = np.array(ys), np.array(dys)
    med = float(np.median(dys))
    slope, inter = np.polyfit(ys, dys, 1)
    resid = float(np.median(np.abs(dys - (slope * ys + inter))))
    before = float(np.median(np.abs(dys)))
    print("%-4d %-6d %-8.2f %-9.4f %-8.2f  %.0f%% of |dy| removable by "
          "per-page affine fit" % (i + 1, len(ys), med, slope, resid,
                                   100 * (1 - resid / max(1e-6, before))))
    allres.append((before, resid))

if allres:
    b = np.mean([x[0] for x in allres]); r = np.mean([x[1] for x in allres])
    print("\nmean |dy| = %.2f pt  ->  after removing per-page affine trend: %.2f pt" % (b, r))
    print("so %.0f%% of the vertical error is systematic (fixable by a second pass)"
          % (100 * (1 - r / max(1e-6, b))))
