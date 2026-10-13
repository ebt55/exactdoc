"""Synthetic PDFs for WP68: a stray shape grown into a page-sized picture.

A stray drawing -- one path no cluster claimed -- is pictured by
`infer.build_figure`, which grows the picture over the text lines and images
it touches. Lines had a budget (`max_area`); images had none. One drawing
touching a large image grew to the image's size and then took every line
inside it, rasterised, as one picture in the flow: a page of text became a
picture, and a picture taller than the content box cost a page of its own.

Each builder draws the smallest page that shows ONE mechanism, the way the
producer that motivated it draws it, or a control that looks similar and must
keep its reading. Generated at test time with reportlab and Pillow (no fixture
bytes are committed) and parsed by the real PDFium backend.

page_background    a Word template's full-page background picture (bands at
                   the top and foot of the sheet), a drawn logo in the top
                   band and a page of text over the white between them
cover_band_stripe  a cover: a dark band across the page with the title on it
                   and narrow white stripes down its right end, the stripes
                   drawn a few points taller than the band
thumb_tab          a report's full-height tinted thumb tab at the paper's
                   edge, standing a few points into the text column, under a
                   header banner picture that reaches it
cover_photo        CONTROL: a cover photograph (not the whole sheet) with
                   its headline set on it and a small drawn mark over its
                   corner -- pictured whole, headline included, as before
text_strip         CONTROL: a tinted strip down the margin that carries its
                   own text (a chapter label) -- not furniture
card_chart         CONTROL: a small bar chart drawn inside a ruled card
back_cover         CONTROL: a back cover -- a drawn wave across the page and
                   two large photographs under it, no text on them: the
                   wave's picture takes them, as before (refused, each would
                   stand in the flow at its own height)
photo_shadow       a photograph over its drop shadow -- a one-colour raster
                   with a soft mask, a little larger -- in a page of text;
                   control: the same photograph without a shadow, and two
                   photographs side by side
"""
import io

try:
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from PIL import Image
except ImportError:                                    # pragma: no cover
    _canvas = None

W, H = 612.0, 792.0
WORDS = ("the office reviewed the financial statements and the reports on "
         "internal control over financial reporting and on compliance with "
         "laws regulations contracts and grant agreements for the year").split()


def available():
    return _canvas is not None


def _line(k, n=12):
    return " ".join(WORDS[(k * 5 + i) % len(WORDS)] for i in range(n))


def _full(k, width, size=10, font="Helvetica"):
    """A line of words filling `width` as a justified line does, to within a
    word: the text column's right edge is then measured where it is."""
    out, i = [], 0
    while True:
        w = WORDS[(k * 5 + i) % len(WORDS)]
        if stringWidth(" ".join(out + [w]), font, size) > width:
            break
        out.append(w)
        i += 1
    return " ".join(out)


def _text(c, x, top, s, size=10, font="Helvetica", rgb=(0, 0, 0)):
    c.setFillColorRGB(*rgb)
    c.setFont(font, size)
    c.drawString(x, H - top - size, s)
    c.setFillColorRGB(0, 0, 0)


def _image(c, x0, top, x1, bottom, paint):
    """A raster placed at (x0, top)-(x1, bottom), top-down page coordinates,
    painted by `paint(img)` on an RGB canvas 1px per 2pt."""
    w, h = max(1, int((x1 - x0) / 2)), max(1, int((bottom - top) / 2))
    img = Image.new("RGB", (w, h), (255, 255, 255))
    paint(img)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    c.drawImage(ImageReader(buf), x0, H - bottom, x1 - x0, bottom - top)


def _logo(c, x, top, size=45.0, rgb=(0.1, 0.27, 0.48)):
    """A drawn seal: ONE path of many curves, as a placed vector logo is."""
    c.setFillColorRGB(*rgb)
    p = c.beginPath()
    r = size / 2
    cx, cy = x + r, H - top - r
    p.moveTo(cx + r, cy)
    k = 0.5523 * r
    for (ax, ay, bx, by, ex, ey) in (
            (cx + r, cy + k, cx + k, cy + r, cx, cy + r),
            (cx - k, cy + r, cx - r, cy + k, cx - r, cy),
            (cx - r, cy - k, cx - k, cy - r, cx, cy - r),
            (cx + k, cy - r, cx + r, cy - k, cx + r, cy)):
        p.curveTo(ax, ay, bx, by, ex, ey)
    r2 = r * 0.55
    p.moveTo(cx + r2, cy)
    k2 = 0.5523 * r2
    for (ax, ay, bx, by, ex, ey) in (
            (cx + r2, cy + k2, cx + k2, cy + r2, cx, cy + r2),
            (cx - k2, cy + r2, cx - r2, cy + k2, cx - r2, cy),
            (cx - r2, cy - k2, cx - k2, cy - r2, cx, cy - r2),
            (cx + k2, cy - r2, cx + r2, cy - k2, cx + r2, cy)):
        p.curveTo(ax, ay, bx, by, ex, ey)
    p.close()
    c.drawPath(p, stroke=0, fill=1, fillMode=0)
    c.setFillColorRGB(0, 0, 0)


def _bands(img):
    """A background picture: a blue band across the top and the foot."""
    w, h = img.size
    px = img.load()
    for y in list(range(0, h // 22)) + list(range(h - h // 22, h)):
        for x in range(w):
            px[x, y] = (20, 60, 120)


def _body(c, top, n, x=72, k0=0, right=540):
    """n lines of text from x to (within a word of) the column's right edge."""
    for i in range(n):
        _text(c, x, top + 14 * i, _full(k0 + i, right - x))


def page_background(path):
    """Page 1: a memo page. Page 2: the full-page background picture, a drawn
    logo in its top band beside the heading, and 30 lines of text."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    _text(c, 72, 72, "MEMORANDUM", 14, "Helvetica-Bold")
    _body(c, 110, 30)
    c.showPage()
    _image(c, 0, 0, W, H, _bands)
    _logo(c, 72, 52)
    _text(c, 130, 60, "At a Glance", 18, "Helvetica-Bold")
    _text(c, 130, 84, "Audit of the Financial Statements", 10)
    _body(c, 140, 30, k0=40)
    c.showPage()
    _body(c, 72, 40, k0=80)
    c.showPage()
    c.save()
    return path


def cover_band_stripe(path):
    """Page 1, a cover: a dark band 227-589 across the page, the title in
    white on it, four 7pt white stripes down its right end drawn from 226 to
    595 (taller than the band), the office's name at the foot. Page 2: text."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    _text(c, 380, 60, "OFFICE OF INSPECTOR GENERAL", 10, "Helvetica-Bold")
    c.setFillColorRGB(0.12, 0.23, 0.33)
    c.rect(0, H - 589, W, 589 - 227, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    for x in (530, 546, 562, 578):
        c.rect(x, H - 595, 7, 595 - 226, stroke=0, fill=1)
    white = (1, 1, 1)
    _text(c, 72, 300, "Summary of Single Audit Oversight", 22, "Helvetica-Bold", white)
    _text(c, 72, 330, "Activities for the Period October", 22, "Helvetica-Bold", white)
    _text(c, 72, 360, "to December 2025", 22, "Helvetica-Bold", white)
    _text(c, 72, 400, "Report Number: 2026-SA-0001", 12, "Helvetica-Bold", white)
    _text(c, 72, 420, "July 16, 2026", 12, "Helvetica-Bold", white)
    _text(c, 72, 730, "Office of Audit and Evaluation | Office of Inspector General", 9)
    c.showPage()
    _text(c, 72, 72, "Highlights", 16, "Helvetica-Bold")
    _body(c, 110, 40)
    c.showPage()
    c.save()
    return path


def _dark(img):
    img.paste((20, 50, 90), (0, 0) + img.size)


def thumb_tab(path, pages=3):
    """Every page: a header banner picture (x 36-540, y 27-68) with the
    section title on it in white, a 56pt tinted tab down the paper's full
    height at the outer edge (right on odd pages, left on even), standing
    6pt into the 72-540 text column, and 44 lines of text."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    for k in range(pages):
        right = k % 2 == 0
        c.setFillColorRGB(0.86, 0.89, 0.90)
        if right:
            c.rect(534, 0, 56, H, stroke=0, fill=1)
        else:
            c.rect(20, 0, 57, H, stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)
        _image(c, 36, 27, 540, 68, _dark)
        _text(c, 60, 38, "Management and Administration", 16, "Helvetica-Bold",
              (1, 1, 1))
        _body(c, 90, 44, x=84 if not right else 72, k0=k * 50)
        c.showPage()
    c.save()
    return path


def _photo(img):
    w, h = img.size
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (40 + (x * 3) % 90, 70 + (y * 2) % 80, 60 + ((x + y) % 70))


def cover_photo(path):
    """CONTROL. Page 1, a cover: a photograph x 40-612, y 0-616 (not the
    whole sheet), the headline in white on it, a small drawn mark over its
    top-left corner, text under it. Page 2: text."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    _image(c, 40, 0, W, 616, _photo)
    _logo(c, 48, 24, 54, (0.95, 0.95, 0.95))
    white = (1, 1, 1)
    _text(c, 90, 420, "Instructions for the Year", 30, "Helvetica-Bold", white)
    _text(c, 90, 460, "Including the Tax Tables", 30, "Helvetica-Bold", white)
    _text(c, 90, 520, "Department of the Treasury", 14, "Helvetica", white)
    _body(c, 640, 8)
    c.showPage()
    _body(c, 72, 40, k0=20)
    c.showPage()
    c.save()
    return path


def text_strip(path):
    """CONTROL. A 50pt tinted strip down the left margin, the full height of
    the paper, standing a few points into the column, with the chapter's
    label set on it; text beside it."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFillColorRGB(0.86, 0.89, 0.90)
    c.rect(24, 0, 52, H, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    _text(c, 30, 60, "Ch. 2", 11, "Helvetica-Bold")
    _text(c, 30, 300, "Audit", 11, "Helvetica-Bold")
    _body(c, 72, 44, x=84)
    c.showPage()
    c.save()
    return path


def card_chart(path):
    """CONTROL. A ruled card (x 72-540, y 150-450) holding a heading, two
    lines of text and a small bar chart drawn as one path; text around it."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    _body(c, 72, 5)
    c.setStrokeColorRGB(0.2, 0.2, 0.2)
    c.rect(72, H - 450, 468, 300, stroke=1, fill=0)
    _text(c, 90, 165, "Recoveries by year", 12, "Helvetica-Bold")
    _text(c, 90, 185, _line(3, 11))
    _text(c, 90, 199, _line(4, 11))
    c.setFillColorRGB(0.1, 0.3, 0.6)
    p = c.beginPath()
    for i, hgt in enumerate((60, 110, 85, 150, 130)):
        p.rect(150 + i * 60, H - 420, 30, hgt)
    c.drawPath(p, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    _body(c, 470, 12, k0=30)
    c.showPage()
    c.save()
    return path


def _shadow_png(w, h):
    """A drop shadow as an office suite exports it: black, the shape in the
    soft mask (alpha falling off toward the edge)."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        for x in range(w):
            e = min(x, y, w - 1 - x, h - 1 - y)
            px[x, y] = (0, 0, 0, max(0, min(160, e * 12)))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def photo_shadow(path, shadow=True):
    """Text, a 451x338pt photograph at (98, 239) over a shadow at (88, 231)
    10pt larger every way (when `shadow`), text under it."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    _body(c, 72, 10)
    if shadow:
        c.drawImage(ImageReader(_shadow_png(236, 177)), 88, H - 585, 471, 354,
                    mask="auto")
    _image(c, 98, 239, 549, 577, _photo)
    _body(c, 600, 10, k0=20)
    c.showPage()
    c.save()
    return path


def two_photos(path):
    """CONTROL: two photographs side by side, neither under the other."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    _body(c, 72, 10)
    _image(c, 72, 239, 300, 420, _photo)
    _image(c, 312, 239, 540, 420, _photo)
    _body(c, 440, 10, k0=20)
    c.showPage()
    c.save()
    return path


def back_cover(path):
    """CONTROL. Page 1: text. Page 2, a back cover: a drawn wave (one path of
    curves) across the page at y 380-440, a photograph x -1-238 y 233-730 and
    another x 237-613 y 410-730 under and beside it, the office's address at
    the foot; no text on the photographs."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    _body(c, 72, 40)
    c.showPage()
    _image(c, -1, 233, 238, 730, _photo)
    _image(c, 237, 410, 613, 730, _photo)
    c.setFillColorRGB(0.1, 0.27, 0.48)
    p = c.beginPath()
    p.moveTo(0, H - 440)
    for k in range(6):
        x = k * 102
        p.curveTo(x + 34, H - 380, x + 68, H - 380, x + 102, H - 440)
    p.lineTo(612, H - 445)
    p.lineTo(0, H - 445)
    p.close()
    c.drawPath(p, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    _text(c, 72, 750, "Office of Inspector General | 245 Murray Lane SW | Washington, DC", 9)
    c.showPage()
    c.save()
    return path


BUILDERS = {
    "back_cover": back_cover,
    "photo_shadow": photo_shadow,
    "two_photos": two_photos,
    "page_background": page_background,
    "cover_band_stripe": cover_band_stripe,
    "thumb_tab": thumb_tab,
    "cover_photo": cover_photo,
    "text_strip": text_strip,
    "card_chart": card_chart,
}
