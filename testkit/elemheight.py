"""Bill each layout element for the height it gained.

heightdiff measures intervals BETWEEN text lines, which localises injections
but cannot name a mechanism -- it once reported "65% space_before" for
intervals whose space_before was 0-10pt. This charges the height to elements
instead: find each element's first and last line in the render, compare the
span it occupies against the span it occupied in the source, and rank by the
difference. An element that grew is the thing that grew.

    python testkit/elemheight.py testkit/real/arxiv_transformer.pdf
    python testkit/elemheight.py testkit/real/*.pdf --top 15
"""
import argparse
import os
import re
from collections import Counter, defaultdict

import _paths  # noqa: F401
import fitz

import harness
from exactdoc.parse import parse_pdf
from exactdoc.dialect import normalize
from exactdoc.infer import infer
from exactdoc.layout import Para, TableEl, FigureEl, ImageEl, RuleEl


def _norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


def rendered_index(pdf):
    """{text -> (page_idx, y0, y1)} for lines whose text is unique."""
    d = fitz.open(pdf)
    H = d[0].rect.height if d.page_count else 792.0
    seen = Counter()
    rows = []
    for p in d:
        for b in p.get_text("dict")["blocks"]:
            if b.get("type"):
                continue
            for ln in b["lines"]:
                t = _norm("".join(s["text"] for s in ln["spans"]))
                if len(t) >= 8:
                    seen[t] += 1
                    rows.append((t, p.number, ln["bbox"][1], ln["bbox"][3]))
    d.close()
    return {t: (pi, y0, y1) for t, pi, y0, y1 in rows if seen[t] == 1}, H


def source_lines(src):
    """Per source page: [(text, bbox)] -- the lines as the PDF draws them.

    An element's own text is NOT usable for this: a Para holds its lines joined
    into one string, which never matches a rendered *line*, so matching on it
    silently excludes every paragraph and leaves only tables visible. The
    element's lines are whichever source lines fall inside its bbox.
    """
    d = fitz.open(src)
    pages = []
    for p in d:
        ls = []
        for b in p.get_text("dict")["blocks"]:
            if b.get("type"):
                continue
            for ln in b["lines"]:
                t = _norm("".join(s["text"] for s in ln["spans"]))
                if len(t) >= 8:
                    ls.append((t, ln["bbox"]))
        pages.append(ls)
    d.close()
    return pages


def elem_lines(el, page_lines):
    bb = getattr(el, "bbox", None) or getattr(el, "clip", None) \
        or getattr(el, "_bbox", None)
    if bb is None:
        return []
    out = []
    for t, lb in page_lines:
        cy = (lb[1] + lb[3]) / 2
        cx = (lb[0] + lb[2]) / 2
        if bb[1] - 1 <= cy <= bb[3] + 1 and bb[0] - 2 <= cx <= bb[2] + 2:
            out.append(t)
    return out


def kind_of(el):
    if isinstance(el, Para):
        return "heading" if el.heading else "para"
    if isinstance(el, TableEl):
        return "table:" + (el.role or "?")
    if isinstance(el, FigureEl):
        return "figure"
    if isinstance(el, ImageEl):
        return "image"
    if isinstance(el, RuleEl):
        return "rule"
    return type(el).__name__


def analyse(src, top):
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hdiff")
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(src))[0]
    docx = os.path.join(out_dir, name + ".docx")
    from exactdoc.convert import convert
    convert(src, docx, refine_rounds=0)
    rendered = harness.docx_to_pdf(docx, out_dir)
    idx, H = rendered_index(rendered)
    src_lines = source_lines(src)
    lay = infer(normalize(parse_pdf(src, keep_image_data=False)))

    rows = []
    by_kind = defaultdict(float)
    by_kind_n = Counter()
    for pl in lay.pages:
        for ch in pl.chunks:
            for el in ch.elements:
                bb = getattr(el, "bbox", None) or getattr(el, "clip", None) \
                    or getattr(el, "_bbox", None)
                if bb is None:
                    continue
                pg_lines = src_lines[pl.number - 1] if pl.number <= len(src_lines) else []
                lines = [l for l in elem_lines(el, pg_lines) if l in idx]
                if len(lines) < 2:
                    continue
                pos = [idx[l] for l in lines]
                # only trust elements that stayed on one rendered page
                if len({p for p, _, _ in pos}) != 1:
                    continue
                r_h = max(y1 for _, _, y1 in pos) - min(y0 for _, y0, _ in pos)
                s_h = bb[3] - bb[1]
                if s_h < 6:
                    continue
                grew = r_h - s_h
                k = kind_of(el)
                by_kind[k] += max(0.0, grew)
                by_kind_n[k] += 1
                rows.append((grew, pl.number, k, el))

    # --- the complement: gaps BETWEEN consecutive elements ---------------
    # If elements barely grow but pages inflate, the height is in the gaps.
    # Source gap is measured between element bboxes; rendered gap between the
    # last matched line of one and the first matched line of the next.
    gap_src = gap_out = 0.0
    gap_n = 0
    gap_rows = []
    for pl in lay.pages:
        pg_lines = src_lines[pl.number - 1] if pl.number <= len(src_lines) else []
        # Index every element in layout order, so a "gap" can be confirmed to
        # contain nothing. Pairing merely-consecutive MATCHED elements
        # silently charges the gap for any unmatched element between them --
        # an equation, a rule, a figure -- and those are exactly what a LaTeX
        # page is full of. Only adjacent pairs are measured.
        seq = []
        ei = 0
        for ch in pl.chunks:
            for el in ch.elements:
                ei += 1
                bb = getattr(el, "bbox", None) or getattr(el, "clip", None) \
                    or getattr(el, "_bbox", None)
                if bb is None:
                    continue
                ls = [l for l in elem_lines(el, pg_lines) if l in idx]
                if not ls:
                    continue
                pos = [idx[l] for l in ls]
                if len({p for p, _, _ in pos}) != 1:
                    continue
                seq.append((bb, min(y0 for _, y0, _ in pos),
                            max(y1 for _, _, y1 in pos),
                            pos[0][0], el, ei))
        seq.sort(key=lambda s: s[0][1])
        for a, b in zip(seq, seq[1:]):
            if a[3] != b[3]:
                continue                      # different rendered pages
            if b[5] != a[5] + 1:
                continue                      # something unmatched sits between
            s_gap = b[0][1] - a[0][3]
            o_gap = b[1] - a[2]
            if s_gap < -2 or s_gap > 120:
                continue
            gap_src += s_gap
            gap_out += o_gap
            gap_n += 1
            gap_rows.append((o_gap - s_gap, pl.number, kind_of(a[4]),
                             kind_of(b[4]), a[4]))
    if gap_n:
        print("\n  inter-element gaps: %d pairs, source %.0fpt -> rendered %.0fpt "
              "(%+.0fpt, %+.1fpt per gap)" %
              (gap_n, gap_src, gap_out, gap_out - gap_src,
               (gap_out - gap_src) / gap_n))
        gap_rows.sort(key=lambda r: -r[0])
        for d, pno, ka, kb, ea in gap_rows[:5]:
            if d < 3:
                break
            sb = getattr(ea, "space_before", None)
            print("    +%5.1fpt p%-3d after %-12s before %-12s (sb=%s)" % (
                d, pno, ka, kb, "-" if sb is None else "%.1f" % sb))

    rows.sort(key=lambda r: -r[0])
    print("\n===== %s =====" % name)
    print("%-9s %5s %-14s %8s  %s" % ("grew", "page", "kind", "srcH", "content"))
    for grew, pno, k, el in rows[:top]:
        if grew < 3:
            break
        bb = getattr(el, "bbox", None) or getattr(el, "clip", None)
        desc = ""
        if isinstance(el, Para):
            desc = "n=%d sb=%.0f %r" % (el.src_lines, el.space_before, el.text[:40])
        elif isinstance(el, TableEl):
            desc = "rows=%d cols=%d" % (len(el.rows), len(el.col_widths))
        print("%+8.1f %5d %-14s %8.1f  %s" % (grew, pno, k, bb[3] - bb[1], desc))
    print("\n  total growth by element kind:")
    for k in sorted(by_kind, key=lambda k: -by_kind[k]):
        if by_kind[k] < 1:
            continue
        print("    %-14s %8.0f pt over %3d elements (%.1f pt each)" %
              (k, by_kind[k], by_kind_n[k], by_kind[k] / by_kind_n[k]))
    return by_kind


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="+")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    grand = defaultdict(float)
    for s in a.src:
        for k, v in analyse(s, a.top).items():
            grand[k] += v
    if len(a.src) > 1:
        print("\n===== all documents: growth by kind =====")
        tot = sum(grand.values()) or 1.0
        for k in sorted(grand, key=lambda k: -grand[k]):
            print("  %-14s %8.0f pt  %4.0f%%" % (k, grand[k], 100 * grand[k] / tot))


if __name__ == "__main__":
    main()
