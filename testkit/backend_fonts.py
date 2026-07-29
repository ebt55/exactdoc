"""Do the two parsers agree on FONT NAME, and does exactdoc map them the same?

exp_regroup showed block grouping explains the pdfium placement gap on some
documents (c6_long 0.23 -> 0.73, c8_toc_links 0.63 -> 1.00) and none of it on
others (c7_code, f1_fpdf_brief, r1_reportlab_report: unchanged). Geometry is
already known identical, so on that second set the cause is neither.

The next thing that reaches the vertical model is the font NAME: it selects
the mapped family, which selects the natural line-height factor in docxout's
NATURAL_FACTORS. Two parsers reading the same font descriptor differently --
'Helvetica' vs 'Arial', a subset tag kept or stripped, a PostScript name vs a
BaseFont name -- would land on different factors and place every line slightly
off, with no geometric disagreement anywhere.

    python testkit/backend_fonts.py
"""
import os
import re
from collections import Counter

import _paths  # noqa: F401

from exactdoc.parse import parse_pdf as parse_mu
from exactdoc.parse_pdfium import parse_pdf as parse_px

TK = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TK)


def _norm(t):
    return re.sub(r"\s+", "", t or "")


def font_of(doc):
    """(page, line text) -> (font, bold, italic, mono, serif) of the first span."""
    seen, out = Counter(), {}
    for p in doc.pages:
        for b in p.blocks:
            for ln in b.lines:
                k = (p.number, _norm(ln.text))
                if len(k[1]) < 8 or not ln.spans:
                    continue
                s = ln.spans[0]
                seen[k] += 1
                out[k] = (s.font, s.bold, s.italic, s.mono, s.serif)
    return {k: v for k, v in out.items() if seen[k] == 1}


def main():
    try:
        from exactdoc.fonts import map_font
    except ImportError:
        map_font = None

    paths = []
    for d in (os.path.join(ROOT, "corpus", "pdfs"), os.path.join(TK, "adv")):
        if os.path.isdir(d):
            paths += [os.path.join(d, f) for f in sorted(os.listdir(d))
                      if f.endswith(".pdf")]

    tot_name = tot_map = tot_flag = tot = 0
    for path in paths:
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            fm, fp = font_of(parse_mu(path, keep_image_data=False)), \
                     font_of(parse_px(path, keep_image_data=False))
        except Exception as e:                                   # noqa: BLE001
            print("%-22s parse failed: %s" % (name[:22], str(e)[:40])); continue
        common = sorted(set(fm) & set(fp))
        if not common:
            continue
        raw_d = [(fm[k][0], fp[k][0]) for k in common if fm[k][0] != fp[k][0]]
        flag_d = [k for k in common if fm[k][1:] != fp[k][1:]]
        map_d = []
        if map_font:
            for k in common:
                try:
                    a = map_font(fm[k][0], fm[k][3], fm[k][4])
                    b = map_font(fp[k][0], fp[k][3], fp[k][4])
                except Exception:                                # noqa: BLE001
                    continue
                if a != b:
                    map_d.append((fm[k][0], fp[k][0], a, b))
        tot += len(common); tot_name += len(raw_d)
        tot_map += len(map_d); tot_flag += len(flag_d)
        print("%-22s %4d lines | raw name differs %4d | mapped differs %4d | flags %3d"
              % (name[:22], len(common), len(raw_d), len(map_d), len(flag_d)))
        for (a, b), c in Counter(raw_d).most_common(3):
            print("        name  %-28r -> %-28r x%d" % (a[:28], b[:28], c))
        for (a, b, ma, mb), c in Counter(map_d).most_common(2):
            print("        MAP   %-18r/%-18r -> %r vs %r x%d"
                  % (a[:18], b[:18], ma, mb, c))
        if flag_d:
            fc = Counter((fm[k][1:], fp[k][1:]) for k in flag_d)
            for (a, b), c in fc.most_common(2):
                print("        flags (b,i,m,s) %s -> %s  x%d" % (a, b, c))

    print("\n%d lines: raw font name differs on %d (%.0f%%), MAPPED family differs "
          "on %d (%.0f%%), style flags on %d (%.0f%%)"
          % (tot, tot_name, 100.0 * tot_name / max(1, tot),
             tot_map, 100.0 * tot_map / max(1, tot),
             tot_flag, 100.0 * tot_flag / max(1, tot)))


if __name__ == "__main__":
    main()
