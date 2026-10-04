"""`exactdoc --diagnose file.pdf`: what a tester can paste instead of the PDF.

A bad-conversion report is only actionable with the document, and the
documents testers care about are the ones they cannot share. This prints the
facts the converter's decisions turn on -- which program made the PDF, its
page geometry and fonts, what the scan step classified it as, and what layout
the inference stage found (columns, tables, lists, headings) -- and nothing a
reader could reconstruct the document from: no text, no title or author, no
file name, no dates, no image bytes. Counts and names of fonts and programs
only. Producer and font names can still identify an organisation, which is why
the report opens by asking for a read-through before sharing.

Read-only: it parses and lays out the document exactly as a conversion would
and writes nothing.
"""
import os
import platform
import sys
import time
from collections import Counter

# Common paper sizes in points, matched within 2pt -- the rounding PDF
# producers apply when they convert millimetres (A4 is 595.28 x 841.89).
_PAPER = {(612, 792): "Letter", (595, 842): "A4", (612, 1008): "Legal",
          (420, 595): "A5", (842, 1191): "A3", (729, 1032): "B5 (JIS)",
          (720, 405): "16:9 slide", (960, 540): "16:9 slide",
          (720, 540): "4:3 slide"}


def _paper(w, h):
    for (pw, ph), name in _PAPER.items():
        for a, b in ((pw, ph), (ph, pw)):
            if abs(w - a) <= 2 and abs(h - b) <= 2:
                return name + (" landscape" if w > h and pw < ph else "")
    return "custom"


def _walk(elements):
    """Yield every layout element, descending into table cells."""
    from .layout import TableEl
    for el in elements:
        yield el
        if isinstance(el, TableEl):
            for row in el.rows:
                for cell in row:
                    if cell is not None:
                        for sub in _walk(list(cell.paras) +
                                         list(getattr(cell, "blocks", []) or [])):
                            yield sub


def _layout_counts(lay):
    from .layout import FigureEl, ImageEl, Para, TableEl
    c = Counter()
    for page in lay.pages:
        if any(ch.n_cols > 1 for ch in page.chunks):
            c["pages with columns"] += 1
        els = [e for ch in page.chunks for e in ch.elements]
        els += list(getattr(page, "floats", []) or [])
        for el in _walk(els):
            if isinstance(el, Para):
                if el.heading:
                    c["headings"] += 1
                elif el.numbering is not None:
                    c["list items"] += 1
                else:
                    c["paragraphs"] += 1
            elif isinstance(el, TableEl):
                c["tables (%s)" % (el.role or "table")] += 1
            elif isinstance(el, FigureEl):
                c["figures (drawn, rasterised)"] += 1
            elif isinstance(el, ImageEl):
                c["pictures"] += 1
    if lay.cover_band is not None:
        c["cover band"] += 1
    c["footnotes"] += len(getattr(lay, "footnotes", None) or ())
    for part in ("header_default", "footer_default"):
        if getattr(lay, part, None) is not None:
            c[part.split("_")[0] + "s"] += 1
    return c


def diagnose(pdf_path, backend_name="pdfium"):
    """-> list of report lines for `pdf_path`. Raises the usual input errors."""
    from . import __version__
    from .backend import get_backend
    from .dialect import fingerprint, normalize
    from .infer import infer
    from .input import check_input_path, parse
    from .scan import census_widgets, classify_ir, refusal

    check_input_path(pdf_path)
    bk = get_backend(backend_name)
    t0 = time.monotonic()
    widgets = census_widgets(bk, pdf_path)
    ir = parse(bk, pdf_path, keep_image_data=False)
    parse_s = time.monotonic() - t0
    scan = classify_ir(ir, widgets=widgets)
    fp = fingerprint(ir)

    sizes = Counter((round(p.width), round(p.height)) for p in ir.pages)
    fonts, chars = Counter(), 0
    rotated = undecoded = ocr = links_ext = links_int = images = 0
    hidden = Counter()
    for p in ir.pages:
        for b in p.blocks:
            for ln in b.lines:
                for s in ln.spans:
                    n = len(s.text.strip())
                    fonts[s.font or "(unnamed)"] += n
                    chars += n
        rotated += len(p.rotated)
        undecoded += len(p.undecoded)
        ocr += p.ocr_chars
        images += len(p.images)
        hidden.update(p.hidden_chars or {})
        for link in p.links:
            if link.get("uri"):
                links_ext += 1
            else:
                links_int += 1

    t1 = time.monotonic()
    lay = None
    layout_note = ""
    error = refusal(scan, max_pages=0)
    if error is None:
        try:
            lay = infer(normalize(ir))
        except Exception as e:                  # a finding, not a crash
            layout_note = "layout stage failed: %s" % type(e).__name__
    layout_s = time.monotonic() - t1

    from .verify import SOFFICE
    try:
        from importlib.metadata import version as _v
        pdfium_v = _v("pypdfium2")
    except Exception:                           # pragma: no cover
        pdfium_v = "?"
    out = [
        "exactdoc diagnose -- no text, title, author or file name is included;",
        "read it through before sharing (producer and font names can name an",
        "organisation).",
        "",
        "environment",
        "  exactdoc %s, Python %s, %s %s" % (
            __version__, platform.python_version(), platform.system(),
            platform.machine()),
        "  pypdfium2 %s, LibreOffice %s" % (
            pdfium_v, "found" if SOFFICE else "not found"),
        "document",
        "  file size     %.1f MB" % (os.path.getsize(pdf_path) / 1e6),
        "  pages         %d" % len(ir.pages),
        "  page sizes    %s" % ", ".join(
            "%dx%d pt %s x%d" % (w, h, _paper(w, h), n)
            for (w, h), n in sizes.most_common(4)),
        "  producer      %s" % (fp["producer"] or "(none)"),
        "  creator       %s" % (fp["creator"] or "(none)"),
        "  class         %s%s" % (
            scan.classification,
            "" if error is None else "  -> refused (%s)" % error.code),
        "  text          %d characters%s" % (
            chars, ", %d in an OCR layer" % ocr if ocr else ""),
        "  form widgets  %s" % (
            "%d on %d form page(s)" % (scan.widget_count, scan.form_pages)
            if scan.census_available else "not counted"),
        "  pictures      %d placed image(s)" % images,
        "  drawing       %d rects, %d curves, %d backdrops, %d vector markers"
        % (fp["rects"], fp["curves"], fp["backdrops"], fp["vector_markers"]),
        "  links         %d external, %d internal" % (links_ext, links_int),
    ]
    if rotated or undecoded:
        out.append("  oddities      %d rotated line(s), %d undecodable glyph(s)"
                   % (rotated, undecoded))
    if hidden:
        out.append("  hidden text   %s" % ", ".join(
            "%s %d" % kv for kv in sorted(hidden.items())))
    out.append("fonts (share of characters)")
    for name, n in fonts.most_common(12):
        out.append("  %5.1f%%  %s" % (100.0 * n / max(1, chars), name))
    if len(fonts) > 12:
        out.append("  ... and %d more" % (len(fonts) - 12))
    out.append("layout found")
    if lay is not None:
        counts = _layout_counts(lay)
        for key in sorted(counts):
            if counts[key]:
                out.append("  %-28s %d" % (key, counts[key]))
    else:
        out.append("  (%s)" % (layout_note or "not run: the document is refused"))
    out.append("timing")
    out.append("  read %.1fs, layout %.1fs" % (parse_s, layout_s))
    return out


def main(pdf_path, backend_name="pdfium", stream=None):
    stream = stream or sys.stdout
    for line in diagnose(pdf_path, backend_name=backend_name):
        print(line, file=stream)
    return 0
