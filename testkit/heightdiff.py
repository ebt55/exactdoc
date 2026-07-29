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


def classify(lay, pageno, y0, y1, crossed_break):
    """Bucket an injection interval by the constructs inside it."""
    els = annotate(lay, pageno, y0, y1)
    kinds = set()
    for s in els:
        kinds.add(s.split("(")[0])
    if crossed_break:
        return "page-break tail"
    if not kinds:
        return "within a paragraph (re-wrap)"
    if "FIGURE" in kinds or "IMAGE" in kinds:
        return "figure/image"
    if "TABLE" in kinds:
        return "table"
    if "RULE" in kinds:
        return "rule / footnote separator"
    if kinds == {"Para"}:
        return "between paragraphs (space_before)"
    return "mixed: " + ",".join(sorted(kinds))


def summarise(paths, min_jump):
    from collections import defaultdict
    tot = defaultdict(float)
    cnt = defaultdict(int)
    per_doc = {}
    skipped = [0]
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hdiff")
    os.makedirs(out_dir, exist_ok=True)
    from exactdoc.convert import convert
    for src in paths:
        name = os.path.splitext(os.path.basename(src))[0]
        docx = os.path.join(out_dir, name + ".docx")
        convert(src, docx, refine_rounds=0)
        rendered = harness.docx_to_pdf(docx, out_dir)
        src_pages, SH = doc_lines(src)
        out_pages, OH = doc_lines(rendered)
        ocount = Counter(t for pg in out_pages for t, _, _ in pg)
        opos = {}
        for ri, pg in enumerate(out_pages):
            for t, y0, y1 in pg:
                if ocount[t] == 1:
                    opos[t] = (ri, ri * OH + y0)
        lay = infer(normalize(parse_pdf(src, keep_image_data=False)))
        dtot = 0.0
        for pno in range(1, len(src_pages) + 1):
            sp = src_pages[pno - 1]
            scount = Counter(t for t, _, _ in sp)
            m = [(t, y0, opos[t]) for t, y0, _ in sp if scount[t] == 1 and t in opos]
            m.sort(key=lambda x: x[1])
            if len(m) < 4:
                continue
            for (t0, y0, (r0, c0)), (t1, y1, (r1, c1)) in zip(m, m[1:]):
                # An interval spanning a rendered page break carries the unused
                # tail of that page, which is a CONSEQUENCE of overflow, not a
                # cause -- and when a match lands pages away (duplicate text,
                # reordering) the continuous-scroll delta is meaningless. Both
                # are excluded; the flow injections are what can be acted on.
                if r1 != r0:
                    skipped[0] += 1
                    continue
                jump = (c1 - c0) - (y1 - y0)
                if jump < min_jump:
                    continue
                k = classify(lay, pno, y0, y1, False)
                tot[k] += jump
                cnt[k] += 1
                dtot += jump
        per_doc[name] = dtot
    grand = sum(tot.values()) or 1.0
    print("\n%-36s %10s %7s %8s" % ("injection site", "total pt", "count", "share"))
    for k in sorted(tot, key=lambda k: -tot[k]):
        print("%-36s %10.0f %7d %7.0f%%" % (k, tot[k], cnt[k], 100 * tot[k] / grand))
    print("%-36s %10.0f" % ("TOTAL (in-flow)", grand))
    print("(%d intervals crossed a rendered page break and were excluded)"
          % skipped[0])
    print("\nper document:")
    for n, v in sorted(per_doc.items(), key=lambda kv: -kv[1]):
        print("  %-28s %8.0f pt  (~%.1f pages)" % (n, v, v / 720.0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="+")
    ap.add_argument("--pages", default="1-3")
    ap.add_argument("--min-jump", type=float, default=4.0)
    ap.add_argument("--summary", action="store_true",
                    help="aggregate injections by construct across all pages")
    a = ap.parse_args()
    if a.summary or len(a.src) > 1:
        summarise(a.src, a.min_jump)
        return

    src = a.src[0]
    lo, hi = (int(x) for x in a.pages.split("-")) if "-" in a.pages \
        else (int(a.pages), int(a.pages))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hdiff")
    os.makedirs(out, exist_ok=True)
    name = os.path.splitext(os.path.basename(src))[0]
    docx = os.path.join(out, name + ".docx")
    from exactdoc.convert import convert
    convert(src, docx, refine_rounds=0)
    rendered = harness.docx_to_pdf(docx, out)

    src_pages, SH = doc_lines(src)
    out_pages, OH = doc_lines(rendered)

    # continuous-scroll index of rendered lines, keyed by unique text
    ocount = Counter(t for pg in out_pages for t, _, _ in pg)
    opos = {}
    for ri, pg in enumerate(out_pages):
        for t, y0, y1 in pg:
            if ocount[t] == 1:
                opos[t] = (ri, ri * OH + y0)

    lay = infer(normalize(parse_pdf(src, keep_image_data=False)))

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
