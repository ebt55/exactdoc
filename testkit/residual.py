"""Is the remaining placement error systematic, or is it scatter?

The question this answers is the one that decides whether the permissive-parser
port can finish at all. Three times on this branch a change made the pdfium IR
provably match PyMuPDF on the thing that was blamed -- block boundaries 201/201,
path bboxes coordinate-identical, a code region classified identically -- and
the rendered score barely moved. Either the residual is systematic (a per-page
offset or a steady accumulation, which a second pass can remove, and which means
convention-matching still pays) or it is irreducible scatter spread over every
word (which means it cannot be chased document by document).

For a source/render pair this reports, per page and pooled:

    med |dx|, |dy|          the raw error
    resid after fit         what survives removing a per-page affine trend in y
                            and a per-page constant in x
    within2pt               as measured
    CEILING                 within2pt if that systematic part were removed
                            perfectly -- the best any anchoring fix could do

The ceiling is the number to read. If pdfium's ceiling reaches PyMuPDF's actual
score, the gap is systematic and the port is a matter of finding the anchor. If
the ceiling sits well below it, the error is scatter and no amount of
convention-matching closes it.

    python testkit/residual.py src.pdf rendered.pdf
"""
import os
import sys

import numpy as np

import _paths  # noqa: F401
import harness


def analyse(src, rendered):
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
    }


def main():
    r = analyse(sys.argv[1], sys.argv[2])
    if not r:
        print("too few matched words")
        return 2
    print("%s  (%d matched words)" % (os.path.basename(sys.argv[1]), r["n"]))
    print("  median |dx| %.2f -> %.2f after removing the per-page constant"
          % (r["dx"], r["rx"]))
    print("  median |dy| %.2f -> %.2f after removing the per-page affine trend"
          % (r["dy"], r["ry"]))
    print("  within2pt   %.3f -> CEILING %.3f" % (r["within2"], r["ceiling"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
