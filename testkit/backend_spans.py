"""Diff the two backends at SPAN level, inside matched lines.

backend_geom.py answered "is the geometry the same?" -- yes: baselines
identical on 4,734 of 4,734 lines, leadings 99-100%, sizes to 0.005pt.
exp_regroup.py answered "is it the block grouping?" -- for about half the
failing documents, yes. Two documents are explained by neither, both
code-heavy (c7_code 0.92 -> 0.16, 03_tech_report_code 0.46 -> 0.23), and the
cause has never been measured. This instrument exists to stop that being
guessed at.

It pairs lines across backends by baseline and x, then reports, per document:

  spans/line      do the two agree on where a line divides into runs?
  text            is the CHARACTER content of the matched line identical?
  space runs      how many runs of >=2 spaces, and how wide -- the synthesised
                  indentation that _build_lines reconstructs from a gap
  mono flags      does one backend think the line is monospaced and the other not
  style keys      font/size/bold/italic/serif per span

Text differences are printed with the space runs made visible, because the
suspected failure mode is invisible: the same words with a different number of
spaces between them reads identically in a terminal.

    python testkit/backend_spans.py                       # the whole corpus
    python testkit/backend_spans.py c7_code 03_tech       # named documents
    python testkit/backend_spans.py --show 12 c7_code     # with example lines
"""
import argparse
import glob
import os
import sys
from collections import Counter

import _paths  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASELINE_TOL = 0.6      # pt; the backends agree on baselines far tighter
X_TOL = 2.0             # pt; line start


def _lines(ir):
    """[(page_no, baseline, x0, line)] flattened, in reading order."""
    out = []
    for pno, p in enumerate(ir.pages, 1):
        for b in p.blocks:
            for ln in b.lines:
                out.append((pno, ln.baseline, ln.bbox[0], ln))
    out.sort(key=lambda t: (t[0], round(t[1], 1), t[2]))
    return out


def _pair(a_lines, b_lines):
    """Match lines across backends on (page, baseline, x). Unmatched reported."""
    used, pairs, unmatched = set(), [], []
    b_by_page = {}
    for i, (pno, base, x0, ln) in enumerate(b_lines):
        b_by_page.setdefault(pno, []).append(i)
    for pno, base, x0, ln in a_lines:
        best, best_d = None, None
        for i in b_by_page.get(pno, ()):
            if i in used:
                continue
            _, bb, bx, _ = b_lines[i]
            if abs(bb - base) > BASELINE_TOL or abs(bx - x0) > X_TOL:
                continue
            d = abs(bb - base) + abs(bx - x0) / 10.0
            if best_d is None or d < best_d:
                best, best_d = i, d
        if best is None:
            unmatched.append((pno, base, ln))
        else:
            used.add(best)
            pairs.append((ln, b_lines[best][3]))
    return pairs, unmatched


def _space_runs(text):
    """[(start_index, length)] for every run of 2+ spaces."""
    runs, i = [], 0
    while i < len(text):
        if text[i] == " ":
            j = i
            while j < len(text) and text[j] == " ":
                j += 1
            if j - i >= 2:
                runs.append((i, j - i))
            i = j
        else:
            i += 1
    return runs


def _visible(text):
    return text.replace(" ", "·")          # middle dot: spaces you can count


def _stylekey(sp):
    return (sp.font, round(sp.size, 2), sp.bold, sp.italic, sp.mono, sp.serif)


def report(path, show=0):
    from exactdoc.parse import parse_pdf as mu
    from exactdoc.parse_pdfium import parse_pdf as pf

    name = os.path.splitext(os.path.basename(path))[0]
    a, b = _lines(mu(path, keep_image_data=False)), _lines(pf(path, keep_image_data=False))
    pairs, unmatched = _pair(a, b)

    n_span_diff = n_text_diff = n_mono_diff = n_style_diff = n_space_diff = 0
    span_delta = Counter()
    examples = []
    for la, lb in pairs:
        ta = "".join(s.text for s in la.spans)
        tb = "".join(s.text for s in lb.spans)
        d_span = len(lb.spans) - len(la.spans)
        if d_span:
            n_span_diff += 1
            span_delta[d_span] += 1
        ra, rb = _space_runs(ta), _space_runs(tb)
        differs_text = ta != tb
        if differs_text:
            n_text_diff += 1
        if [n for _, n in ra] != [n for _, n in rb]:
            n_space_diff += 1
        if any(s.mono for s in la.spans) != any(s.mono for s in lb.spans):
            n_mono_diff += 1
        if [_stylekey(s) for s in la.spans] != [_stylekey(s) for s in lb.spans]:
            n_style_diff += 1
        if differs_text and len(examples) < show:
            examples.append((ta, tb, ra, rb))

    n = max(1, len(pairs))
    print("\n== %s" % name)
    print("  lines            mupdf %d, pdfium %d, matched %d, unmatched %d"
          % (len(a), len(b), len(pairs), len(unmatched)))
    print("  span count diff  %d/%d lines (%.0f%%)   deltas %s"
          % (n_span_diff, len(pairs), 100.0 * n_span_diff / n,
             dict(span_delta.most_common(5))))
    print("  TEXT diff        %d/%d lines (%.0f%%)"
          % (n_text_diff, len(pairs), 100.0 * n_text_diff / n))
    print("  space-run diff   %d/%d lines (%.0f%%)"
          % (n_space_diff, len(pairs), 100.0 * n_space_diff / n))
    print("  mono flag diff   %d/%d lines" % (n_mono_diff, len(pairs)))
    print("  style key diff   %d/%d lines" % (n_style_diff, len(pairs)))
    for ta, tb, ra, rb in examples:
        print("    mupdf  |%s|  runs=%s" % (_visible(ta)[:96], [n for _, n in ra]))
        print("    pdfium |%s|  runs=%s" % (_visible(tb)[:96], [n for _, n in rb]))
    return {"text_diff": n_text_diff, "pairs": len(pairs),
            "space_diff": n_space_diff, "span_diff": n_span_diff}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="substrings; default is everything")
    ap.add_argument("--show", type=int, default=0,
                    help="print N example lines whose text differs")
    a = ap.parse_args()

    srcs = sorted(glob.glob(os.path.join(ROOT, "corpus", "pdfs", "*.pdf")))
    srcs += sorted(glob.glob(os.path.join(ROOT, "testkit", "adv", "*.pdf")))
    if a.names:
        srcs = [s for s in srcs if any(k in os.path.basename(s) for k in a.names)]
    if not srcs:
        print("no matching corpus documents")
        return 2
    for s in srcs:
        try:
            report(s, a.show)
        except Exception as e:
            print("\n== %s\n  FAILED: %s: %s"
                  % (os.path.basename(s), type(e).__name__, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
