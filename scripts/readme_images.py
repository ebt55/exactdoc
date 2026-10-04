"""Rebuild the README's example images in docs/images/.

Each image puts a page of a corpus PDF beside the same page of exactdoc's DOCX
as LibreOffice renders it. The renders must come from the canonical container,
so this script does not convert anything: it reads a quality sweep that kept its
DOCX and render PDFs, and only rasterises and composes.

1. In the canonical container (docker/gate.Dockerfile, with
   FONTCONFIG_FILE=scripts/fonts.conf), run the product sweep over the example
   documents and keep its working directory:

       python testkit/quality_sweep.py --corpus both --profile product \\
           --json readme-examples.json --only 01_whitepaper c3_tables \\
           c2_paper2col x17_resume x05_lo y34_census y41_arxiv y58_ssa

   It writes testkit/sweep/product/<stem>/<stem>.docx and <stem>.pdf (the render).

2. Copy testkit/sweep/ out of the container if needed, then:

       python scripts/readme_images.py testkit/sweep [name ...]

   With no names every image is rebuilt. Record the sweep payload under
   docs/evidence/ (see docs/evidence/readme-examples-2026-10-04.json), because
   the README quotes page counts from it.

Needs pypdfium2 and Pillow (both core dependencies). The label font is Segoe UI
on Windows and DejaVu Sans elsewhere; images differ slightly between the two.
"""
import os
import sys

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "images")
SS = 2                      # supersampling, for crisp text and lines

BG = (246, 248, 250)
MUTED = (89, 99, 110)
BORDER = (208, 215, 222)
BLUE = (9, 105, 218)
GREEN = (26, 127, 55)
RED = (207, 34, 46)
PURPLE = (130, 80, 223)
AMBER = (191, 135, 0)

_FONTS = {
    False: [r"C:\Windows\Fonts\segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    True: [r"C:\Windows\Fonts\segoeuib.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}


def font(size, bold=False):
    for path in _FONTS[bold]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size * SS)
    return ImageFont.load_default()


def src_path(stem):
    for d in ("fixtures", "fixtures_expansion"):
        p = os.path.join(ROOT, "testkit", d, stem + ".pdf")
        if os.path.exists(p):
            return p
    raise SystemExit("no source PDF for " + stem)


class Run:
    """A kept quality sweep: <dir>/product/<stem>/<stem>.pdf is the render."""

    def __init__(self, path):
        self.dir = os.path.join(path, "product") if os.path.isdir(
            os.path.join(path, "product")) else path

    def render_pdf(self, stem):
        p = os.path.join(self.dir, stem, stem + ".pdf")
        if not os.path.exists(p):
            raise SystemExit("no render for %s in %s" % (stem, self.dir))
        return p


def render(pdf_path, index, height):
    """(image, px-per-pt scale, page height in pt, page, document) at a pixel height."""
    pdf = pdfium.PdfDocument(pdf_path)
    page = pdf[index]
    _, h = page.get_size()
    scale = height * SS / h
    return page.render(scale=scale).to_pil().convert("RGB"), scale, h, page, pdf


def text_box(page, page_h, scale, needle):
    """Image-space bbox of the first occurrence of `needle` on the page."""
    tp = page.get_textpage()
    occ = tp.search(needle, match_case=True).get_next()
    if not occ:
        raise SystemExit("text not found on the page: %r" % needle)
    xs, ys = [], []
    for k in range(occ[0], occ[0] + occ[1]):
        l, b, r, t = tp.get_charbox(k)
        if r > l:
            xs += [l, r]
            ys += [b, t]
    return (min(xs) * scale, (page_h - max(ys)) * scale,
            max(xs) * scale, (page_h - min(ys)) * scale)


def union(boxes, pad=0):
    return (min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad,
            max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad)


def pill(draw, xy, text, fill, size=15):
    f = font(size, True)
    x, y = xy
    tw = draw.textlength(text, font=f)
    pad_x, h = 10 * SS, (size + 12) * SS
    draw.rounded_rectangle((x, y, x + tw + 2 * pad_x, y + h), radius=h // 2, fill=fill)
    draw.text((x + pad_x, y + h / 2), text, font=f, fill=(255, 255, 255), anchor="lm")


def framed(canvas, img, x, y):
    """Paste a page with a soft shadow and a hairline border."""
    sh = Image.new("RGBA", (img.width + 40 * SS, img.height + 40 * SS), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((20 * SS, 22 * SS, 20 * SS + img.width, 22 * SS + img.height),
                                 fill=(0, 0, 0, 38))
    sh = sh.filter(ImageFilter.GaussianBlur(6 * SS))
    canvas.paste(sh, (x - 20 * SS, y - 20 * SS), sh)
    canvas.paste(img, (x, y))
    ImageDraw.Draw(canvas).rectangle((x - 1, y - 1, x + img.width, y + img.height),
                                     outline=BORDER, width=SS)


def save(canvas, name, colors):
    """Downsample, reduce to a palette, and write an optimised PNG."""
    final = canvas.resize((canvas.width // SS, canvas.height // SS), Image.LANCZOS)
    pal = final.quantize(colors=colors, method=Image.MEDIANCUT, dither=Image.NONE)
    path = os.path.join(OUT, name)
    pal.save(path, optimize=True)
    print("%-26s %4dx%-4d %6.1f KB" % (name, final.width, final.height,
                                        os.path.getsize(path) / 1024.0))


def pair(run, name, stem, page_no, height, right_label, right_color, highlights=()):
    """Source page | DOCX render page. `highlights` are (x0, y0, x1, y1) page fractions
    outlined in red on the render, to point at what went wrong."""
    left = render(src_path(stem), page_no - 1, height)[0]
    right = render(run.render_pdf(stem), page_no - 1, height)[0]
    m, arrow_w, top, bottom = 28 * SS, 56 * SS, 58 * SS, 24 * SS
    width = m + left.width + arrow_w + right.width + m
    canvas = Image.new("RGB", (width, top + max(left.height, right.height) + bottom), BG)
    draw = ImageDraw.Draw(canvas)
    pill(draw, (m, 16 * SS), "Original PDF", MUTED)
    framed(canvas, left, m, top)
    ax, ay = m + left.width + arrow_w // 2, top + left.height // 2
    draw.polygon([(ax - 12 * SS, ay - 16 * SS), (ax + 12 * SS, ay), (ax - 12 * SS, ay + 16 * SS)],
                 fill=(140, 149, 159))
    x = m + left.width + arrow_w
    pill(draw, (x, 16 * SS), right_label, right_color)
    framed(canvas, right, x, top)
    draw = ImageDraw.Draw(canvas)
    for fx0, fy0, fx1, fy1 in highlights:
        draw.rounded_rectangle((x + fx0 * right.width, top + fy0 * right.height,
                                x + fx1 * right.width, top + fy1 * right.height),
                               radius=8 * SS, outline=RED, width=3 * SS)
    save(canvas, name, 96)


def editable(run, name, stem, page_no, height):
    """One DOCX page with its Word structure labelled: what "editable" means.

    The regions are found from the render's own text, so they follow the
    layout if a later converter moves it. The labels name what the DOCX
    actually contains on that page of 01_whitepaper_market (header part,
    numbered-list paragraphs, Heading 1/2 styles, a w:tbl, a drawing, a footer
    with a PAGE field); check them again if the example document changes.
    """
    img, scale, ph, page, _pdf = render(run.render_pdf(stem), page_no - 1, height)

    def box(*needles):
        return union([text_box(page, ph, scale, n) for n in needles])

    p = 5 * SS
    tbl = box("Tier", "Experimentation", "Spot")
    hy = int(tbl[1] + 4 * SS)                    # inside the dark header row
    xr = img.width - 1
    while xr > tbl[2] and sum(img.getpixel((xr, hy))) > 300:
        xr -= 1                                  # the table's drawn right edge
    above, below = box("tiered strategy is shown below."), box("2.1 Sensitivity")
    body = box("We model total cost as the sum")
    lst = box("Latency-sensitive requests represent 17% of volume but 44% of infrastructure spend.",
              "Batch-tolerant workloads are the fastest-growing segment, at 58% year over year.")
    foot = box("2026 Meridian Analytics", "Page 2")
    regions = [
        ("Header (repeats on every page)", PURPLE,
         union([box("THE ECONOMICS OF TIERED AI INFERENCE", "MERIDIAN ANALYTICS")], p)),
        ("Bulleted list", GREEN, (lst[0] - p - 22 * SS, lst[1] - p, lst[2] + p, lst[3] + p)),
        ("Heading 2", BLUE, union([box("1.2 Supply-side response")], p)),
        ("Table: real rows and cells", AMBER,
         (tbl[0] - 3 * p, tbl[1] - 2 * p, xr + p, tbl[3] + 2 * p)),
        ("Heading 1", BLUE, union([box("2. Cost Model")], p)),
        # a picture has no text to find: it is the band between its intro and the next heading
        ("Chart: kept as a picture", MUTED,
         (body[0] - p, above[3] + 4 * p, tbl[2] - 2 * p, below[1] - 4 * p)),
        ("Footer with a live page number", PURPLE,
         (foot[0] - p - 12 * SS, foot[1] - p, foot[2] + p, foot[3] + p)),
    ]
    m, top, label_w = 28 * SS, 58 * SS, 300 * SS
    canvas = Image.new("RGB", (m + img.width + 40 * SS + label_w + m, top + img.height + 24 * SS), BG)
    pill(ImageDraw.Draw(canvas), (m, 16 * SS), "exactdoc's DOCX, opened in LibreOffice", BLUE)
    framed(canvas, img, m, top)
    over = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    for _label, c, (x0, y0, x1, y1) in regions:
        od.rounded_rectangle((m + x0, top + y0, m + x1, top + y1), radius=6 * SS,
                             fill=c + (34,), outline=c + (255,), width=2 * SS)
    canvas.paste(over, (0, 0), over)
    draw = ImageDraw.Draw(canvas)
    lx, f = m + img.width + 40 * SS, font(15, True)
    for label, c, (x0, y0, x1, y1) in regions:
        cy = top + (y0 + y1) / 2
        draw.line((m + x1 + 2 * SS, cy, lx - 6 * SS, cy), fill=c, width=2 * SS)
        draw.ellipse((lx - 10 * SS, cy - 4 * SS, lx - 2 * SS, cy + 4 * SS), fill=c)
        draw.text((lx + 4 * SS, cy), label, font=f, fill=c, anchor="lm")
    save(canvas, name, 200)


LO = "exactdoc's DOCX, opened in LibreOffice"
IMAGES = {
    "hero-whitepaper.png": lambda r, n: pair(r, n, "01_whitepaper_market", 1, 640, LO, BLUE),
    "editable-structure.png": lambda r, n: editable(r, n, "01_whitepaper_market", 2, 760),
    "works-tables.png": lambda r, n: pair(r, n, "c3_tables", 1, 470, LO, BLUE),
    "works-two-column.png": lambda r, n: pair(r, n, "c2_paper2col", 1, 470, LO, BLUE),
    "works-resume.png": lambda r, n: pair(r, n, "x17_resume_twocol", 1, 470, LO, BLUE),
    "works-footnotes.png": lambda r, n: pair(r, n, "x05_lo_quotes_notes", 1, 470, LO, BLUE),
    # The red outlines point at the failure on THIS render; re-check them by eye
    # whenever the images are rebuilt, because a better converter moves them.
    "not-yet-slides.png": lambda r, n: pair(
        r, n, "y34_census_slides_pptx365", 3, 300, "exactdoc's DOCX: the layout falls apart", RED,
        highlights=[(0.20, 0.17, 0.97, 0.55)]),
    "not-yet-dense-paper.png": lambda r, n: pair(
        r, n, "y41_arxiv_ieeetran", 1, 560, "exactdoc's DOCX: equations break, pages multiply", RED,
        highlights=[(0.55, 0.53, 0.92, 0.63), (0.48, 0.74, 0.545, 0.975)]),
    "not-yet-designed.png": lambda r, n: pair(
        r, n, "y58_ssa_statement_indd20", 1, 560, "exactdoc's DOCX: panels become pictures", RED,
        highlights=[(0.06, 0.92, 0.97, 0.985)]),
}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    run, names = Run(argv[0]), argv[1:] or sorted(IMAGES)
    os.makedirs(OUT, exist_ok=True)
    for name in names:
        if name not in IMAGES:
            raise SystemExit("unknown image %r; one of: %s" % (name, ", ".join(sorted(IMAGES))))
        IMAGES[name](run, name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
