"""Is the remaining placement error systematic, or is it scatter?

The question this answers is the one that decides whether the permissive-parser
port can finish at all. Three times on this branch a change made the pdfium IR
provably match PyMuPDF on the thing that was blamed -- block boundaries 201/201,
path bboxes coordinate-identical, a code region classified identically -- and
the rendered score barely moved. Either the residual is systematic (a per-page
offset or a steady accumulation, which a second pass can remove, and which means
convention-matching still pays) or it is irreducible scatter spread over every
word (which means it cannot be chased document by document).

For a source/render pair this reports, pooled over pages:

    med |dx| A -> B     A = median |dx| as measured
                        B = median |dx| after removing each page's CONSTANT dx
    med |dy| A -> B     A = median |dy| as measured
                        B = median |dy| after removing each page's AFFINE trend
                            (offset + accumulation down the page)
    within2pt -> CEILING
                        within2pt as measured, then what it would be if both
                        systematic parts were removed perfectly -- the best any
                        anchoring fix could do

Both arrows are raw -> after-fit, never p50 -> p90. A number that grows across
the arrow means the fit is fighting the data, not that the error got worse.

    python testkit/residual.py src.pdf rendered.pdf
    python testkit/residual.py src.pdf rendered.pdf --hist   # per-line dy shape

The ceiling is the number to read. If pdfium's ceiling reaches PyMuPDF's actual
score, the gap is systematic and the port is a matter of finding the anchor. If
the ceiling sits well below it, the error is scatter and no amount of
convention-matching closes it.

--hist answers a question no summary statistic can: is the vertical error a few
lines displaced by a whole leading (a wrap or line-count difference) or every
line off by a fraction of a point (an anchoring model difference)? Those have
opposite fixes and identical medians.
"""
import os
import sys

import numpy as np

import _paths  # noqa: F401
import harness


def analyse(src, rendered, keep=False):
    sw, ow = harness.page_words(src), harness.page_words(rendered)
    rows = []
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
        us, uo, xs, ys, dxs, dys = set(), set(), [], [], [], []
        for d, si, oj in cands:
            if si in us or oj in uo:
                continue
            us.add(si)
            uo.add(oj)
            xs.append(sp[si][1])
            ys.append(sp[si][2])
            dxs.append(ow[i][oj][1] - sp[si][1])
            dys.append(ow[i][oj][2] - sp[si][2])
        if len(ys) < 8:
            continue
        xs, ys = np.array(xs), np.array(ys)
        dxs, dys = np.array(dxs), np.array(dys)
        # y: per-page affine trend (offset + accumulation down the page)
        slope, inter = np.polyfit(ys, dys, 1)
        ry = dys - (slope * ys + inter)
        # x: per-page constant only. A slope in x would be a scale error, which
        # is not what a second pass can fix by shifting.
        rx = dxs - np.median(dxs)
        rows.append((dxs, dys, rx, ry))
    if not rows:
        return None
    dxs = np.concatenate([r[0] for r in rows])
    dys = np.concatenate([r[1] for r in rows])
    rx = np.concatenate([r[2] for r in rows])
    ry = np.concatenate([r[3] for r in rows])
    return {
        "n": len(dxs),
        "dx": float(np.median(np.abs(dxs))),
        "dy": float(np.median(np.abs(dys))),
        "rx": float(np.median(np.abs(rx))),
        "ry": float(np.median(np.abs(ry))),
        "within2": float(np.mean(np.hypot(dxs, dys) <= 2.0)),
        "ceiling": float(np.mean(np.hypot(rx, ry) <= 2.0)),
        "dys": dys if keep else None,
    }


def histogram(dys, leading=None, width=52):
    """Where the vertical error actually sits, in 0.5pt buckets."""
    import collections
    buckets = collections.Counter(round(float(d) * 2) / 2.0 for d in dys)
    if not buckets:
        return
    top = max(buckets.values())
    print("  per-word dy distribution (0.5pt buckets, %d words):" % len(dys))
    for k in sorted(buckets):
        if abs(k) > 20:
            continue
        n = buckets[k]
        bar = "#" * max(1, int(width * n / top))
        note = ""
        if leading and abs(abs(k) - leading) < 1.0:
            note = "  <-- one leading (%.1fpt)" % leading
        print("    %+6.1f %-5d %s%s" % (k, n, bar, note))
    far = sum(n for k, n in buckets.items() if abs(k) > 20)
    if far:
        print("    beyond +-20pt: %d words" % far)


def main():
    hist = "--hist" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    r = analyse(args[0], args[1], keep=hist)
    if not r:
        print("too few matched words")
        return 2
    print("%s  (%d matched words)" % (os.path.basename(args[0]), r["n"]))
    print("  median |dx| %.2f -> %.2f after removing the per-page constant"
          % (r["dx"], r["rx"]))
    print("  median |dy| %.2f -> %.2f after removing the per-page affine trend"
          % (r["dy"], r["ry"]))
    print("  within2pt   %.3f -> CEILING %.3f" % (r["within2"], r["ceiling"]))
    if hist:
        lead = float(os.environ.get("LEADING", "0")) or None
        histogram(r["dys"], leading=lead)
    return 0


if __name__ == "__main__":
    sys.exit(main())
