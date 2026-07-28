"""Probe a PDF: producer, fonts, drawings, and what exactdoc's infer() decides."""
import _paths  # noqa: F401  (sets sys.path, finds soffice/chrome)
import sys, os, json
import fitz
from exactdoc.parse import parse_pdf
from exactdoc.infer import infer
from exactdoc.layout import FigureEl, TableEl, Para, ImageEl, RuleEl

p = sys.argv[1]
d = fitz.open(p)
print("== metadata ==")
print(json.dumps(d.metadata, indent=1))
print("pages:", d.page_count, "size:", d[0].rect)
fonts = set()
for pg in d:
    for f in pg.get_fonts():
        fonts.add((f[3], f[4]))
print("fonts:", sorted(fonts))
for pg in d:
    dr = pg.get_drawings()
    print("p%d drawings=%d images=%d links=%d" % (pg.number + 1, len(dr),
          len(pg.get_images()), len(pg.get_links())))
    from collections import Counter
    c = Counter()
    for x in dr:
        c[(x.get("type"), len(x["items"]), tuple(i[0] for i in x["items"])[:4])] += 1
    for k, v in c.most_common(12):
        print("    ", k, v)
d.close()

print("\n== exactdoc IR ==")
ir = parse_pdf(p, keep_image_data=False)
print(ir.summary())
lay = infer(ir)
print("\n== inferred layout ==")
print("margins", lay.margin_l, lay.margin_r, lay.margin_t, lay.margin_b)
print("cover_band", lay.cover_band is not None, "hdr", lay.header_default is not None,
      "ftr", lay.footer_default is not None)
for pg in lay.pages:
    print("page", pg.number)
    for ch in pg.chunks:
        print("  chunk cols=%d pre_gap=%.1f n=%d" % (ch.n_cols, ch.pre_gap, len(ch.elements)))
        for el in ch.elements:
            t = type(el).__name__
            if isinstance(el, Para):
                print("    Para[%s] '%s'" % (el.align, el.text[:70]))
            elif isinstance(el, FigureEl):
                print("    *** FigureEl clip=%s  %.0fx%.0f" %
                      ([round(v, 1) for v in el.clip], el.width, el.height))
            elif isinstance(el, TableEl):
                print("    TableEl role=%s %dx%d" % (el.role, len(el.rows),
                      len(el.rows[0]) if el.rows else 0))
            else:
                print("   ", t)
