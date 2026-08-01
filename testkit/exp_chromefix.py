"""PROTOTYPE FIX for the Chromium/Skia dialect. No tool files are edited.

Three defects, all in the parse->cluster stage:

 1. Chromium paints an opaque white page-background rect covering the whole
    page. It is invisible, but it touches every other drawing, so union-find
    merges ALL drawings into one page-sized cluster.
 2. `_classify_cluster` returns "figure" if ANY member is curve/complex. A CSS
    `list-style: disc` bullet is a 3x3pt bezier circle -> one bullet poisons
    the whole cluster.
 3. => `build_figure` seeds at page size and rasterises the entire page.

Fix: drop page-background fills; re-express tiny bullet glyphs as *text*
markers (the marker dialect infer.py already understands), so they never reach
the clusterer.
"""
import _paths  # noqa: F401  (sets sys.path, finds soffice/chrome)
import os, sys, glob, json
import harness
from exactdoc import parse as P
from exactdoc.model import TextBlock, Line, Span

_orig_parse = P.parse_pdf
ENABLED = True

BULLET_MAX = 9.0            # pt; a list bullet is never bigger
BG_COVER = 0.60             # fraction of page area that makes a fill a backdrop


def _is_page_bg(d, pw, ph):
    if d.shape != "rect" or not d.fill:
        return False
    x0, y0, x1, y1 = d.bbox
    if (x1 - x0) * (y1 - y0) < BG_COVER * pw * ph:
        return False
    r, g, b = (int(d.fill[1:3], 16), int(d.fill[3:5], 16), int(d.fill[5:7], 16))
    return min(r, g, b) >= 245          # white / near-white backdrop


def _is_bullet(d):
    x0, y0, x1, y1 = d.bbox
    w, h = x1 - x0, y1 - y0
    if not (0.5 < w <= BULLET_MAX and 0.5 < h <= BULLET_MAX):
        return False
    if not d.fill:
        return False
    return abs(w - h) <= 2.0 and d.shape in ("curve", "complex", "rect")


def patched_parse(path, keep_image_data=True):
    ir = _orig_parse(path, keep_image_data)
    if not ENABLED:
        return ir
    for p in ir.pages:
        keep, bullets = [], []
        for d in p.drawings:
            if _is_page_bg(d, p.width, p.height):
                continue                                   # defect 1
            if _is_bullet(d):
                bullets.append(d)                          # defect 2
                continue
            keep.append(d)
        p.drawings = keep
        # re-express each bullet as a one-span text block, matching the
        # "separate marker box" dialect infer.py already handles.
        for d in bullets:
            x0, y0, x1, y1 = d.bbox
            size = 10.0
            near = [l for b in p.blocks for l in b.lines
                    if abs((l.bbox[1] + l.bbox[3]) / 2 - (y0 + y1) / 2) < 9
                    and l.bbox[0] > x0]
            if near:
                near.sort(key=lambda l: l.bbox[0])
                size = near[0].spans[0].size
            bb = (x0, y0 - size * 0.55, x0 + size * 0.5, y1 + size * 0.2)
            sp = Span(text="\u2022", font="Arial", size=size, color=d.fill or "#000000",
                      bold=False, italic=False, mono=False, serif=False,
                      superscript=False, bbox=bb, origin=(x0, y1))
            p.blocks.append(TextBlock(lines=[Line(spans=[sp], bbox=bb)], bbox=bb))
        p.blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    return ir


P.parse_pdf = patched_parse
# Registered on the backend seam, not assigned over `exactdoc.convert.parse_pdf`:
# that assignment stopped having any effect once the backend was selected through
# the seam, and an experiment that quietly measures the unpatched parser still
# prints a number.
from exactdoc.backend import register_backend       # noqa: E402
from exactdoc.convert import convert                # noqa: E402
from exactdoc.options import PRODUCT                # noqa: E402

_OPTIONS = PRODUCT.replace(
    backend=register_backend("chromefix", patched_parse), refine_rounds=0)


if __name__ == "__main__":
    mode = sys.argv[1]
    ENABLED = (mode == "on")
    globals()["ENABLED"] = ENABLED
    root = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(root, "chromefix_" + mode)
    os.makedirs(out, exist_ok=True)
    srcs = []
    for d in sys.argv[2:]:
        srcs += sorted(glob.glob(os.path.join(d, "*.pdf")))
    pairs = []
    for s in srcs:
        n = os.path.splitext(os.path.basename(s))[0]
        dx = os.path.join(out, n + ".docx")
        convert(s, dx, options=_OPTIONS)
        pairs.append((s, dx))
    harness.batch_docx_to_pdf([d for _, d in pairs], os.path.join(out, "r"))
    rows = []
    for s, dx in pairs:
        try:
            r = harness.evaluate(s, dx, os.path.join(out, "r"), save_images=True,
                                 img_dir=os.path.join(out, "cmp_" +
                                                      os.path.splitext(os.path.basename(dx))[0]))
            rows.append(r); print(harness.brief(r))
        except Exception as e:
            print("FAIL", os.path.basename(s), e)
    json.dump(rows, open(os.path.join(out, "res.json"), "w"), indent=1)
