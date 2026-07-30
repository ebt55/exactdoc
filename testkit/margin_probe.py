"""Does the page's vertical origin agree between backends, and would it?

Ruling law 18 gate 3. `infer()` derives `DocLayout.margin_t` from line-box
TOPS -- the one vertical quantity the two parsers legitimately disagree about,
because it comes from font-metric tables they do not share (M2.d escalation
packet). Baselines, which they report identically, carry the same information.

This reports, per document and per backend:

    margin_t        as shipped, from line-box tops
    baseline-anchored   what it becomes when the topmost text contributes
                    `baseline - (leading - 0.21*size)` instead of its box top --
                    exactdoc's own published paragraph-top convention, the same
                    formula the writer uses to place the paragraph

and the pdfium-minus-pymupdf disagreement under each. The fix's own claim is
that the second column agrees sub-0.1pt across backends; if it does not, the
convention has not been removed and nothing should be rendered.

    python testkit/margin_probe.py
"""
import argparse
import glob
import os
import sys

import _paths  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DESCENT = 0.21          # exactdoc's published descent convention
SINGLE_LEAD = 1.16      # infer()'s own single-line leading multiple


def _line_top_baseline_anchored(block_lines, ln):
    """`baseline - (leading - 0.21*size)`, the writer's paragraph-top formula."""
    size = max((s.size for s in ln.spans), default=10.0)
    bases = [l.baseline for l in block_lines]
    diffs = sorted(b2 - b1 for b1, b2 in zip(bases, bases[1:]) if b2 > b1)
    lead = diffs[len(diffs) // 2] if diffs else max(size * SINGLE_LEAD, 4.0)
    return ln.baseline - (lead - DESCENT * size)


def margins(path, parse, why=False):
    """(shipped, baseline-anchored) margin_t, unrounded, + what set the minimum."""
    from exactdoc.dialect import normalize
    ir = normalize(parse(path, keep_image_data=False))
    shipped, anchored = [], []
    for p in ir.pages:
        for b in p.blocks:
            for ln in b.lines:
                shipped.append((ln.bbox[1], "text p%d |%s|"
                                % (p.number, ln.text[:26])))
                anchored.append((_line_top_baseline_anchored(b.lines, ln),
                                 "text p%d |%s|" % (p.number, ln.text[:26])))
        for d in p.drawings:
            # drawings have no baseline; their boxes are geometry both backends
            # now agree on (M2.b), so they contribute unchanged to both columns
            shipped.append((d.bbox[1], "draw p%d %s" % (p.number, d.shape)))
            anchored.append((d.bbox[1], "draw p%d %s" % (p.number, d.shape)))
    if not shipped:
        return None, None, "", ""
    s = min(shipped)
    a = min(anchored)
    return s[0], a[0], s[1], a[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--why", action="store_true")
    a = ap.parse_args()
    from exactdoc.parse import parse_pdf as mu
    from exactdoc.parse_pdfium import parse_pdf as pf

    srcs = sorted(glob.glob(os.path.join(ROOT, "corpus", "pdfs", "*.pdf")))
    srcs += sorted(glob.glob(os.path.join(ROOT, "testkit", "adv", "*.pdf")))
    if a.names:
        srcs = [s for s in srcs if any(k in os.path.basename(s) for k in a.names)]

    print("%-24s %-17s %-17s %-9s %s"
          % ("document", "shipped mu/pf", "anchored mu/pf", "d shipped", "d anchored"))
    worst_ship = worst_anch = 0.0
    for s in srcs:
        name = os.path.splitext(os.path.basename(s))[0]
        try:
            ms, ma, msw, maw = margins(s, mu)
            ps, pa, psw, paw = margins(s, pf)
        except Exception as e:
            print("%-24s FAILED %s" % (name[:24], e))
            continue
        if ms is None or ps is None:
            continue
        ds, da = abs(ps - ms), abs(pa - ma)
        worst_ship = max(worst_ship, ds)
        worst_anch = max(worst_anch, da)
        flag = "" if da <= 0.1 else "   <-- still disagrees"
        print("%-24s %-17s %-17s %-9.2f %.3f%s"
              % (name[:24], "%.1f / %.1f" % (ms, ps), "%.1f / %.1f" % (ma, pa),
                 ds, da, flag))
        if a.why and da > 0.1:
            print("      pymupdf min set by: %s" % maw)
            print("      pdfium  min set by: %s" % paw)
    print("\nworst backend disagreement: shipped %.2fpt -> baseline-anchored %.2fpt"
          % (worst_ship, worst_anch))
    print("law 18 gate 3 requires the anchored column to agree within 0.1pt")
    return 0


if __name__ == "__main__":
    sys.exit(main())

