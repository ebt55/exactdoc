"""The acceptance test for replacing the parser.

The swap is done when pypdfium2 is not WORSE than PyMuPDF -- not when it is
perfect. Several corpus documents already fail on PyMuPDF (nested tables,
rasterised SVG charts), and chasing those while believing they are swap
regressions would burn the schedule on pre-existing bugs.

So this converts both backends on the same corpus with the same settings and
prints them side by side, marking each document REGRESSION / same / BETTER.
Exit code is non-zero only if a document is worse under pdfium.

    python testkit/backend_parity.py
    python testkit/backend_parity.py --refine 3
"""
import argparse
import glob
import os
import sys

import _paths  # noqa: F401
import harness

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(backend, srcs, out_root, refine):
    import exactdoc.convert as C
    from exactdoc.parse import parse_pdf as mu
    from exactdoc.parse_pdfium import parse_pdf as pf
    C.parse_pdf = mu if backend == "pymupdf" else pf
    out = os.path.join(out_root, backend)
    os.makedirs(out, exist_ok=True)
    pairs = []
    for s in srcs:
        n = os.path.splitext(os.path.basename(s))[0]
        dx = os.path.join(out, n + ".docx")
        try:
            C.convert(s, dx, refine_rounds=refine)
            pairs.append((s, dx, n))
        except Exception as e:
            print("  CONVERT FAIL [%s] %-22s %s" % (backend, n[:22], str(e)[:50]))
    harness.batch_docx_to_pdf([p[1] for p in pairs], os.path.join(out, "r"))
    res = {}
    for s, dx, n in pairs:
        try:
            res[n] = harness.evaluate(s, dx, os.path.join(out, "r"),
                                      save_images=False)
        except Exception as e:
            print("  EVAL FAIL [%s] %-22s %s" % (backend, n[:22], str(e)[:50]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refine", type=int, default=0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    srcs = sorted(glob.glob(os.path.join(ROOT, "corpus", "pdfs", "*.pdf")))
    srcs += sorted(glob.glob(os.path.join(ROOT, "testkit", "adv", "*.pdf")))
    if not srcs:
        print("no corpus; run the generators first")
        return 2
    out_root = a.out or os.path.join(ROOT, "testkit", "parity")

    mu = run("pymupdf", srcs, out_root, a.refine)
    pf = run("pdfium", srcs, out_root, a.refine)

    print("\n%-22s %-16s %-16s %s" % ("document", "pymupdf", "pdfium", "verdict"))
    worse = same = better = 0
    for n in sorted(set(mu) | set(pf)):
        A, B = mu.get(n), pf.get(n)
        if not A or not B:
            print("%-22s %-16s %-16s MISSING" % (n[:22], bool(A), bool(B)))
            worse += 1
            continue
        # a document is worse if it loses pages it had, or loses live text
        dp_a = abs(A["out_pages"] - A["src_pages"])
        dp_b = abs(B["out_pages"] - B["src_pages"])
        lv_a, lv_b = A["live_text_cov"], B["live_text_cov"]
        pl_a, pl_b = A.get("word_recall", 0), B.get("word_recall", 0)
        if dp_b > dp_a or lv_b < lv_a - 0.02 or pl_b < pl_a - 0.05:
            v, worse = "REGRESSION", worse + 1
        elif dp_b < dp_a or lv_b > lv_a + 0.02 or pl_b > pl_a + 0.05:
            v, better = "BETTER", better + 1
        else:
            v, same = "same", same + 1
        print("%-22s %s/%-3s l%.2f p%.2f  %s/%-3s l%.2f p%.2f  %s" % (
            n[:22], A["src_pages"], A["out_pages"], lv_a, pl_a,
            B["src_pages"], B["out_pages"], lv_b, pl_b, v))

    print("\n%d regressions, %d same, %d better" % (worse, same, better))
    print("swap is acceptable when regressions == 0")
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main())
