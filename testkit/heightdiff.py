"""Where does the extra vertical height enter, line by line?

Two root-cause attempts on LaTeX pagination started from plausible mechanisms
(re-wrap; fragment paragraphs) and each fixed something real without moving
page counts. This tool replaces guessing with the direct measurement: match
text lines between the source PDF and the rendered DOCX, sort by source y, and
report d(dy)/d(line) -- the JUMPS. Wherever dy grows between two consecutive
source lines, that many points of height were injected between them, and the
layout elements sitting in that interval are the suspects.

Rendered y is treated as a continuous scroll (page_index * page_height + y) so
content that spilled to the next rendered page stays comparable; the expected
artifact is one jump at each rendered page break (the unused bottom of the
page), which is labelled as such.

    python testkit/heightdiff.py testkit/real/arxiv_transformer.pdf --pages 1-5
"""
import argparse
import os
import re
import sys
from collections import Counter

import _paths  # noqa: F401
import fitz

import harness
from exactdoc.parse import parse_pdf
from exactdoc.dialect import normalize
from exactdoc.infer import infer
from exactdoc.layout import Para, TableEl, FigureEl, ImageEl, RuleEl


def _norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


def doc_lines(pdf):
    d = fitz.open(pdf)
    pages = []
    H = d[0].rect.height if d.page_count else 792.0
    for p in d:
        ls = []
        for b in p.get_text("dict")["blocks"]:
            if b.get("type"):
                continue
            for ln in b["lines"]:
                t = _norm("".join(s["text"] for s in ln["spans"]))
                if len(t) >= 10:
                    ls.append((t, ln["bbox"][1], ln["bbox"][3]))
        pages.append(ls)
    d.close()
    return pages, H


def annotate(lay, pageno, y0, y1):
    """Elements of source page `pageno` whose top sits in (y0, y1]."""
    out = []
    pl = lay.pages[pageno - 1]
    for ch in pl.chunks:
        for el in ch.elements:
            bb = getattr(el, "bbox", None) or getattr(el, "clip", None) \
                or getattr(el, "_bbox", None)
            if bb is None:
                continue
            if y0 - 1.0 < bb[1] <= y1 + 1.0:
                if isinstance(el, Para):
                    out.append("Para(sb=%.1f lead=%.1f n=%d) %r" % (
                        el.space_before, el.leading, el.src_lines, el.text[:36]))
                elif isinstance(el, FigureEl):
                    out.append("FIGURE(sb=%.1f h=%.1f)" % (el.space_before, el.height))
                elif isinstance(el, ImageEl):
                    out.append("IMAGE(sb=%.1f h=%.1f)" % (el.space_before, el.height))
                elif isinstance(el, TableEl):
                    bbh = (el.bbox[3] - el.bbox[1]) if el.bbox else -1
                    out.append("TABLE(role=%s sb=%.1f h=%.1f rows=%d)" % (
                        el.role, el.space_before, bbh, len(el.rows)))
                elif isinstance(el, RuleEl):
                    out.append("RULE(sb=%.1f)" % el.space_before)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--pages", default="1-3")
    ap.add_argument("--min-jump", type=float, default=4.0)
    a = ap.parse_args()

    lo, hi = (int(x) for x in a.pages.split("-")) if "-" in a.pages \
        else (int(a.pages), int(a.pages))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hdiff")
    os.makedirs(out, exist_ok=True)
    name = os.path.splitext(os.path.basename(a.src))[0]
    docx = os.path.join(out, name + ".docx")
    from exactdoc.convert import convert
    convert(a.src, docx, refine_rounds=0)
    rendered = harness.docx_to_pdf(docx, out)

    src_pages, SH = doc_lines(a.src)
    out_pages, OH = doc_lines(rendered)

    # continuous-scroll index of rendered lines, keyed by unique text
    ocount = Counter(t for pg in out_pages for t, _, _ in pg)
    opos = {}
    for ri, pg in enumerate(out_pages):
        for t, y0, y1 in pg:
            if ocount[t] == 1:
                opos[t] = (ri, ri * OH + y0)

    lay = infer(normalize(parse_pdf(a.src, keep_image_data=False)))

    for pno in range(lo, hi + 1):
        sp = src_pages[pno - 1]
        scount = Counter(t for t, _, _ in sp)
        matched = [(t, y0, opos[t]) for t, y0, _ in sp
                   if scount[t] == 1 and t in opos]
        matched.sort(key=lambda m: m[1])
        if len(matched) < 4:
            print("== source page %d: only %d matched lines ==" % (pno, len(matched)))
            continue
        base_dy = matched[0][2][1] - matched[0][1]
        print("\n== source page %d: %d matched lines, first-line dy %.1f ==" %
              (pno, len(matched), base_dy))
        total = 0.0
        prev_t, prev_y, (prev_ri, prev_cy) = matched[0]
        for t, y0, (ri, cy) in matched[1:]:
            d_src = y0 - prev_y
            d_out = cy - prev_cy
            jump = d_out - d_src
            if jump >= a.min_jump:
                total += jump
                brk = "  [rendered page break %d->%d]" % (prev_ri + 1, ri + 1) \
                    if ri != prev_ri else ""
                print("  +%6.1fpt between y=%.0f and y=%.0f%s" % (jump, prev_y, y0, brk))
                print("      after: %r" % prev_t[:64])
                for s in annotate(lay, pno, prev_y, y0):
                    print("      >> %s" % s)
            prev_t, prev_y, prev_ri, prev_cy = t, y0, ri, cy
        print("  page total injected: +%.1fpt (page height %.0f)" % (total, SH))


if __name__ == "__main__":
    main()
