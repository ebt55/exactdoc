"""Diagnose WHY lines re-wrap: compare source vs rendered wrap geometry."""
import _paths  # noqa: F401  (sets sys.path, finds soffice/chrome)
import sys, re
from collections import Counter, defaultdict
import fitz
import numpy as np


def lines_of(pdf):
    d = fitz.open(pdf)
    out = []
    for p in d:
        ls = []
        for b in p.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for ln in b["lines"]:
                t = "".join(s["text"] for s in ln["spans"])
                if t.strip():
                    ls.append((t, ln["bbox"], ln["spans"][0]["size"],
                               ln["spans"][0]["font"]))
        ls.sort(key=lambda x: (round(x[1][1], 1), x[1][0]))
        out.append(ls)
    d.close()
    return out


def col_geometry(pages, label):
    x0s = Counter(); x1s = Counter(); sizes = Counter(); fonts = Counter()
    for ls in pages:
        for t, bb, sz, fn in ls:
            if bb[2] - bb[0] < 200:
                continue
            x0s[round(bb[0], 0)] += 1
            x1s[round(bb[2], 0)] += 1
            sizes[round(sz, 2)] += 1
            fonts[re.sub(r"^[A-Z]{6}\+", "", fn)] += 1
    print("[%s] modal left  %s" % (label, x0s.most_common(4)))
    print("[%s] modal right %s" % (label, x1s.most_common(4)))
    print("[%s] sizes       %s" % (label, sizes.most_common(4)))
    print("[%s] fonts       %s" % (label, fonts.most_common(6)))


def leading_of(pages, label):
    gaps = Counter()
    for ls in pages:
        prev = None
        for t, bb, sz, fn in ls:
            if prev is not None:
                g = round(bb[1] - prev, 1)
                if 0 < g < 40:
                    gaps[g] += 1
            prev = bb[1]
    print("[%s] line pitch  %s" % (label, gaps.most_common(6)))


def wrap_compare(src_pages, out_pages):
    """Find the first line where source and render diverge, per page."""
    print("\n-- first divergence per page --")
    for i in range(min(len(src_pages), len(out_pages))):
        a = [t.strip() for t, *_ in src_pages[i]]
        b = [t.strip() for t, *_ in out_pages[i]]
        n = min(len(a), len(b))
        j = 0
        while j < n and a[j] == b[j]:
            j += 1
        if j >= n and len(a) == len(b):
            print(" p%-2d IDENTICAL (%d lines)" % (i + 1, len(a)))
        else:
            print(" p%-2d lines %d vs %d, diverge at line %d" % (i + 1, len(a), len(b), j))
            if j < len(a):
                print("      SRC: %r" % a[j][:100])
            if j < len(b):
                print("      OUT: %r" % b[j][:100])


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    sp, op = lines_of(src), lines_of(out)
    col_geometry(sp, "src"); col_geometry(op, "out")
    leading_of(sp, "src"); leading_of(op, "out")
    ns = sum(len(x) for x in sp); no = sum(len(x) for x in op)
    print("\ntotal text lines: src %d  out %d  (delta %+d)" % (ns, no, no - ns))
    wrap_compare(sp, op)
