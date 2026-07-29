"""Sweep the wrap-width correction and measure LINE-BREAK AGREEMENT directly.

line_match = fraction of source text lines that appear verbatim as a line in the
render-back PDF (order-free, position-free). This isolates re-wrap from layout.
"""
import _paths  # noqa: F401  (sets sys.path, finds soffice/chrome)
import os, sys, glob, json
from collections import Counter
import fitz, harness
from exactdoc import docxout

_orig = docxout.write_para
ALPHA = 0.0          # extra narrowing as a fraction of wrap width
QUANT = True         # also apply the size-quantisation correction


def patched(container, p, content_w, par=None, ctx=None):
    if p.runs:
        tot = {}
        for r in p.runs:
            if r.text and not r.is_tab:
                tot[r.size] = tot.get(r.size, 0) + len(r.text)
        if tot:
            src_sz = max(tot, key=tot.get)
            k = (round(src_sz * 2) / 2) / src_sz if src_sz > 0.01 else 1.0
            wrap_w = max(1.0, content_w - p.left_indent - p.right_indent)
            adj = (1.0 - k) if QUANT else 0.0
            p.right_indent = p.right_indent + wrap_w * (adj + ALPHA)
    return _orig(container, p, content_w, par, ctx)


docxout.write_para = patched


def text_lines(pdf):
    d = fitz.open(pdf)
    out = Counter()
    for p in d:
        for b in p.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for ln in b["lines"]:
                t = "".join(s["text"] for s in ln["spans"]).strip()
                t = " ".join(t.split())
                if len(t) > 12:
                    out[t] += 1
    d.close()
    return out


def line_match(src_pdf, out_pdf):
    a, b = text_lines(src_pdf), text_lines(out_pdf)
    inter = sum(min(c, b[t]) for t, c in a.items())
    return inter / max(1, sum(a.values()))


if __name__ == "__main__":
    srcs = []
    for d in sys.argv[1:]:
        srcs += sorted(glob.glob(os.path.join(d, "*.pdf")))
    root = os.path.dirname(os.path.abspath(__file__))
    from exactdoc.convert import convert
    # Zero refine, explicitly: this sweep measures what the wrap-width correction
    # does to line-break agreement, and the closed loop would correct over the top
    # of the very effect being swept.
    from exactdoc.options import RAW

    print("%-8s %-6s | %-28s %s" % ("alpha", "quant", "doc", "line_match  pages  <2pt"))
    for quant, alpha in [(False, 0.0), (True, 0.0), (True, -0.004), (True, 0.004),
                         (False, -0.008), (False, -0.004), (False, 0.004), (False, 0.008)]:
        QUANT, ALPHA = quant, alpha
        globals()["QUANT"], globals()["ALPHA"] = quant, alpha
        tag = "q%d_a%+.3f" % (int(quant), alpha)
        out = os.path.join(root, "sweep", tag)
        os.makedirs(out, exist_ok=True)
        pairs = []
        for s in srcs:
            n = os.path.splitext(os.path.basename(s))[0]
            dx = os.path.join(out, n + ".docx")
            convert(s, dx, options=RAW)
            pairs.append((s, dx))
        harness.batch_docx_to_pdf([d for _, d in pairs], os.path.join(out, "r"))
        for s, dx in pairs:
            rp = os.path.join(out, "r", os.path.basename(dx).replace(".docx", ".pdf"))
            if not os.path.exists(rp):
                print("  render fail", s); continue
            lm = line_match(s, rp)
            r = harness.evaluate(s, dx, os.path.join(out, "r"), save_images=False)
            print("%-8.3f %-6s | %-28s %.4f      %d/%d   %.3f" % (
                alpha, quant, os.path.basename(s)[:28], lm,
                r["src_pages"], r["out_pages"], r.get("within2pt", 0)))
