"""Is BLOCK GROUPING the whole of the pdfium placement gap?

backend_geom.py established that the two parsers extract identical geometry:
baselines agree on 4734/4734 lines to within 0.001pt, leadings on 99-100% of
pairs, sizes to 0.005pt. The only surviving difference is which lines get
grouped into which TextBlock -- 35% agreement -- plus a ~0.8pt loose-box
inflation of line bbox tops on LaTeX.

That makes grouping the suspect, not the proof. This is the proof: parse with
pdfium, then RE-BLOCK its lines using PyMuPDF's block boundaries, and convert.

    pymupdf   geometry MU     grouping MU
    pdfium    geometry PX     grouping PX
    hybrid    geometry PX     grouping MU     <-- this lane

If hybrid scores like pymupdf, grouping is the entire cause and the remaining
port work is `_build_blocks` alone. If it scores like pdfium, something outside
both geometry and grouping is at fault and the port needs a different search.

The hybrid is a MEASUREMENT DEVICE, not a candidate implementation -- it runs
both parsers, so it inherits AGPL and buys nothing. Its only job is to split
the difference between two hypotheses.

    python testkit/exp_regroup.py
    python testkit/exp_regroup.py --refine 3
"""
import argparse
import glob
import os
import sys

import _paths  # noqa: F401
import harness

from exactdoc.model import TextBlock, bbox_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _centre(ln):
    """A point that identifies the line: start of its baseline."""
    return (ln.bbox[0] + min(4.0, 0.25 * (ln.bbox[2] - ln.bbox[0])), ln.baseline)


def hybrid_parse(path, keep_image_data=True):
    """PDFium geometry, PyMuPDF block boundaries."""
    from exactdoc.parse import parse_pdf as mu
    from exactdoc.parse_pdfium import parse_pdf as px

    a = px(path, keep_image_data=keep_image_data)
    b = mu(path, keep_image_data=False)

    for pi, page in enumerate(a.pages):
        if pi >= len(b.pages):
            break
        boxes = [bl.bbox for bl in b.pages[pi].blocks]
        if not boxes:
            continue
        lines = [ln for blk in page.blocks for ln in blk.lines]
        buckets = {}
        orphan = []
        for ln in lines:
            x, y = _centre(ln)
            hit = None
            for bi, bb in enumerate(boxes):
                if bb[0] - 2 <= x <= bb[2] + 2 and bb[1] - 2 <= y <= bb[3] + 2:
                    hit = bi
                    break
            if hit is None:
                # nearest block by vertical distance, so nothing is dropped
                best, bd = None, 1e9
                for bi, bb in enumerate(boxes):
                    d = abs(y - 0.5 * (bb[1] + bb[3])) + \
                        (0 if bb[0] - 6 <= x <= bb[2] + 6 else 400)
                    if d < bd:
                        best, bd = bi, d
                hit = best
                if hit is None:
                    orphan.append(ln)
                    continue
            buckets.setdefault(hit, []).append(ln)

        blocks = []
        for bi in sorted(buckets):
            ls = sorted(buckets[bi], key=lambda l: (round(l.baseline, 1), l.bbox[0]))
            bb = None
            for l in ls:
                bb = bbox_union(bb, l.bbox)
            blocks.append(TextBlock(lines=ls, bbox=bb))
        for ln in orphan:
            blocks.append(TextBlock(lines=[ln], bbox=ln.bbox))
        blocks.sort(key=lambda t: (round(t.bbox[1], 1), t.bbox[0]))
        page.blocks = blocks
    return a


def run(lane, srcs, out_root, refine):
    # The hybrid lane is registered on the backend seam rather than assigned over
    # `exactdoc.convert.parse_pdf`. That assignment only ever worked because
    # `convert` held the parser as a module global; once the backend is selected
    # through the seam it is a no-op that sets an attribute nobody reads, and the
    # lane would silently measure the default parser while reporting itself as
    # the hybrid.
    from exactdoc.backend import register_backend
    from exactdoc.convert import convert
    from exactdoc.options import PRODUCT

    if lane == "hybrid":
        try:
            register_backend("hybrid-regroup", hybrid_parse)
        except ValueError:
            pass
        backend = "hybrid-regroup"
    else:
        backend = lane
    options = PRODUCT.replace(backend=backend, refine_rounds=refine)
    out = os.path.join(out_root, lane)
    os.makedirs(out, exist_ok=True)
    pairs = []
    for s in srcs:
        n = os.path.splitext(os.path.basename(s))[0]
        dx = os.path.join(out, n + ".docx")
        try:
            convert(s, dx, options=options)
            pairs.append((s, dx, n))
        except Exception as e:                                   # noqa: BLE001
            print("  CONVERT FAIL [%s] %-20s %s" % (lane, n[:20], str(e)[:44]))
    harness.batch_docx_to_pdf([p[1] for p in pairs], os.path.join(out, "r"))
    res = {}
    for s, dx, n in pairs:
        try:
            res[n] = harness.evaluate(s, dx, os.path.join(out, "r"), save_images=False)
        except Exception as e:                                   # noqa: BLE001
            print("  EVAL FAIL [%s] %-20s %s" % (lane, n[:20], str(e)[:44]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refine", type=int, default=0)
    a = ap.parse_args()

    srcs = sorted(glob.glob(os.path.join(ROOT, "corpus", "pdfs", "*.pdf")))
    srcs += sorted(glob.glob(os.path.join(ROOT, "testkit", "adv", "*.pdf")))
    out_root = os.path.join(ROOT, "testkit", "regroup")

    lanes = {L: run(L, srcs, out_root, a.refine)
             for L in ("pymupdf", "pdfium", "hybrid")}

    names = sorted(set().union(*[set(v) for v in lanes.values()]))
    print("\n%-20s %-18s %-18s %-18s" % ("document", "pymupdf", "pdfium", "hybrid"))
    agg = {L: [] for L in lanes}
    for n in names:
        row = []
        for L in ("pymupdf", "pdfium", "hybrid"):
            r = lanes[L].get(n)
            if not r:
                row.append("%-18s" % "-")
                continue
            agg[L].append(r["within2pt"])
            row.append("%s/%-2s l%.2f w%.2f" % (r["src_pages"], r["out_pages"],
                                                r["live_text_cov"], r["within2pt"]))
        print("%-20s %s" % (n[:20], " ".join(row)))

    print("\nmean within-2pt over documents scored in all three lanes:")
    common = [n for n in names if all(n in lanes[L] for L in lanes)]
    for L in ("pymupdf", "pdfium", "hybrid"):
        v = [lanes[L][n]["within2pt"] for n in common]
        print("  %-9s %.3f   (%d documents)" % (L, sum(v) / max(1, len(v)), len(v)))
    print("\nif hybrid ~= pymupdf, block grouping is the entire gap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
