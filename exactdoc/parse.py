"""PDF -> IR parser built on PyMuPDF. The optional `mupdf` extra, not the default.

This module used to carry a top-level `import fitz`, and that single line was the
whole of `tests/test_no_pymupdf.py`'s declared seam: one module in the package
that a PyMuPDF-free install could not import. It is now lazy, so the seam is
**empty** -- every module in the package imports with PyMuPDF absent, and the
only thing that fails is asking for this parser by name.

The laziness is not a style preference. `pypdfium2` is the core dependency and
`backend="pdfium"` is the default, so on a base install `fitz` is genuinely not
there; a caller who asks for `backend="pymupdf"` anyway must get
`BackendUnavailableError` naming the extra to install, not an `ImportError`
traceback out of a module they never mentioned.
"""
import re
from typing import List, Optional

from .errors import BackendUnavailableError, UnsupportedInputError
from .model import (DocIR, PageIR, TextBlock, Line, Span, DrawCmd, ImageObj,
                    LinkDest, xml_safe_text, xml_safe_uri)

_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")


def require_fitz():
    """The PyMuPDF module, or a typed error naming the extra that supplies it.

    One place, used by this parser and by `backend.PyMuPDFBackend`'s render and
    census methods, so every door into PyMuPDF answers the same way. A
    `BackendUnavailableError` is a `ConfigurationError`: the resolution is
    `pip install`, the CLI maps it to exit code 7, and it is deliberately not a
    fallback to the other backend -- silently substituting a parser would change
    which one produced every number.
    """
    try:
        import fitz
    except ImportError as exc:
        raise BackendUnavailableError(
            "the pymupdf backend needs PyMuPDF, which is not installed",
            detail="install it with `pip install exactdoc[mupdf]`. Note that "
                   "PyMuPDF is AGPL-3.0-or-later, and the default install "
                   "carries no AGPL code -- so adding this extra changes your "
                   "obligations for anything you distribute.") from exc
    return fitz


def _goto_dest(doc, lk) -> Optional[LinkDest]:
    """A GoTo link's target as a LinkDest, or None if it is not one.

    PyMuPDF reports the destination point in TWO different coordinate systems
    depending on how the PDF spelled the destination, and nothing in the dict
    says which one you got:

      * LINK_GOTO -- a direct /Dest array -- arrives already flipped into
        page space. Measured on a ReportLab file whose destination is
        `/XYZ 0 600` on a 792pt page, `to.y` is 192.0.
      * LINK_NAMED -- `/Dest /s1` resolved through the catalogue's /Dests --
        arrives as the raw PDF number. Measured on c8_toc_links, whose
        destination is `/XYZ 0 646.5`, `to.y` is 646.5, and the page-space
        answer is 145.5.

    Reading `to` without asking which kind it is therefore puts a named
    destination 501pt from where it belongs on this corpus. PDFium has no such
    split -- FPDFDest_GetLocationInPage is raw bottom-up for both -- so this
    normalisation is what makes the two backends agree to the decimal.

    A destination with no point at all (`/Fit`, a whole-page view) is not an
    error and not a location: it returns None rather than inventing y=0.
    """
    fitz = require_fitz()
    kind = lk.get("kind")
    if kind not in (getattr(fitz, "LINK_GOTO", 1), getattr(fitz, "LINK_NAMED", 4)):
        return None
    to = lk.get("to")
    if to is None or not hasattr(to, "y"):
        return None
    # `page` is not always an int. A named destination PyMuPDF could only
    # half-resolve arrives with the page as a STRING and no point at all:
    # measured on y03_nist_fips197, `{'kind': 4, 'page': '44', 'view': 'Fit'}`.
    # Comparing that to 0 raised TypeError and took the whole conversion with
    # it -- on the shipping backend, for a document that had never been run
    # through this code before the real-world corpus arrived.
    try:
        page = int(lk.get("page", -1))
    except (TypeError, ValueError):
        return None
    if page < 0:
        return None
    try:
        height = doc[page].rect.height
    except Exception:
        return None
    y = float(to.y) if kind == getattr(fitz, "LINK_GOTO", 1) \
        else height - float(to.y)
    return LinkDest(page=int(page), x=float(to.x), y=y)


def _color_hex(v) -> Optional[str]:
    """fitz colors: int (text) or float tuple (drawings)."""
    if v is None:
        return None
    if isinstance(v, int):
        return "#%06x" % (v & 0xFFFFFF)
    try:
        vals = list(v)
    except TypeError:
        return None
    if len(vals) == 1:
        vals = vals * 3
    if len(vals) == 4:  # CMYK -> RGB
        c, m, y, k = vals
        vals = [(1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)]
    r, g, b = [max(0, min(255, round(x * 255))) for x in vals[:3]]
    return "#%02x%02x%02x" % (r, g, b)


def _frame_edges(d):
    """If the path is two nested filled rects (even-odd ring), return the up-to-4
    visible edge bars as bboxes; else None."""
    items = d["items"]
    if len(items) != 2 or any(it[0] != "re" for it in items):
        return None
    if not d.get("fill") and not d.get("color"):
        return None
    r1, r2 = items[0][1], items[1][1]
    outer, inner = (r1, r2) if abs(r1) >= abs(r2) else (r2, r1)
    if not (inner.x0 >= outer.x0 - 0.2 and inner.y0 >= outer.y0 - 0.2 and
            inner.x1 <= outer.x1 + 0.2 and inner.y1 <= outer.y1 + 0.2):
        return None
    # inner must be meaningfully big (a ring, not a tiny hole)
    if inner.width < 0.5 * outer.width or inner.height < 0.3 * outer.height:
        return None
    edges = []
    if inner.y0 - outer.y0 > 0.2:   # top bar
        edges.append((outer.x0, outer.y0, outer.x1, inner.y0))
    if outer.y1 - inner.y1 > 0.2:   # bottom bar
        edges.append((outer.x0, inner.y1, outer.x1, outer.y1))
    if inner.x0 - outer.x0 > 0.2:   # left bar
        edges.append((outer.x0, inner.y0, inner.x0, inner.y1))
    if outer.x1 - inner.x1 > 0.2:   # right bar
        edges.append((inner.x1, inner.y0, outer.x1, inner.y1))
    return edges or None


def _classify_path(d) -> str:
    items = d["items"]
    kinds = [it[0] for it in items]
    r = d["rect"]
    w, h = r.width, r.height
    if all(k == "re" for k in kinds) and len(items) == 1:
        return "rect"
    if all(k == "qu" for k in kinds) and len(items) == 1:
        return "rect"
    if all(k == "l" for k in kinds):
        if len(items) == 1:
            if h <= 2.0 and w > 4:
                return "hline"
            if w <= 2.0 and h > 4:
                return "vline"
            return "line"
        # multiple straight segments; a 4-line closed path is a rect
        if len(items) <= 4 and d.get("closePath"):
            return "rect"
        return "complex"
    if any(k == "c" for k in kinds):
        return "curve" if len(items) <= 8 else "complex"
    return "complex"


def parse_pdf(path: str, keep_image_data: bool = True) -> DocIR:
    fitz = require_fitz()
    doc = fitz.open(path)
    # PyMuPDF opens an encrypted document successfully but rejects every
    # operation on it with a generic ValueError.  Check its documented status
    # while the cause is still unambiguous and before reader diagnostics can
    # escape through the public API.
    if doc.needs_pass:
        doc.close()
        raise UnsupportedInputError("password-protected PDFs are not supported")
    ir = DocIR(path=path, meta=dict(doc.metadata or {}))
    tflags = (fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP)

    for pno, page in enumerate(doc):
        pw, ph = page.rect.width, page.rect.height
        pir = PageIR(number=pno + 1, width=pw, height=ph)

        # ---- links first (so spans can be tagged)
        links = []
        for lk in page.get_links():
            r = lk["from"]
            bbox = (r.x0, r.y0, r.x1, r.y1)
            if lk.get("uri"):
                uri = xml_safe_uri(lk["uri"])
                if uri:
                    links.append({"bbox": bbox, "uri": uri})
                continue
            dest = _goto_dest(doc, lk)
            if dest is not None:
                links.append({"bbox": bbox, "dest": dest})
        pir.links = links

        # ---- text
        td = page.get_text("dict", flags=tflags)
        for blk in td.get("blocks", []):
            if blk.get("type") != 0:
                continue
            lines = []
            for ln in blk.get("lines", []):
                spans = []
                for sp in ln.get("spans", []):
                    text = xml_safe_text(sp.get("text", ""))
                    if text == "":
                        continue
                    flags = sp.get("flags", 0)
                    font = _SUBSET_RE.sub("", sp.get("font", "") or "")
                    fl = font.lower()
                    bold = bool(flags & 16) or "bold" in fl or "black" in fl or "heavy" in fl
                    italic = bool(flags & 2) or "italic" in fl or "oblique" in fl
                    bbox = tuple(sp["bbox"])
                    uri = None
                    dest = None
                    for lk in links:
                        lb = lk["bbox"]
                        ov = (max(0, min(bbox[2], lb[2]) - max(bbox[0], lb[0])) *
                              max(0, min(bbox[3], lb[3]) - max(bbox[1], lb[1])))
                        if ov > 0.5 * max(1e-6, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])):
                            uri = lk.get("uri")
                            dest = lk.get("dest")
                            break
                    spans.append(Span(
                        text=text, font=font, size=float(sp.get("size", 10.0)),
                        color=_color_hex(sp.get("color", 0)) or "#000000",
                        bold=bold, italic=italic,
                        mono=bool(flags & 8) or "courier" in fl or "mono" in fl,
                        serif=bool(flags & 4),
                        superscript=bool(flags & 1),
                        bbox=bbox, origin=tuple(sp.get("origin", (bbox[0], bbox[3]))),
                        link=uri, dest=dest,
                    ))
                if spans:
                    lb = tuple(ln["bbox"])
                    d = ln.get("dir", (1.0, 0.0))
                    lines.append(Line(spans=spans, bbox=lb,
                                      dir=(float(d[0]), float(d[1]))))
            if lines:
                pir.blocks.append(TextBlock(lines=lines, bbox=tuple(blk["bbox"])))

        # ---- vector drawings
        seen_draw = set()
        for d in page.get_drawings():
            r = d["rect"]
            bbox = (r.x0, r.y0, r.x1, r.y1)
            typ = d.get("type", "")
            kind = {"f": "fill", "s": "stroke", "fs": "fillstroke"}.get(typ, "fill")
            fill = _color_hex(d.get("fill"))
            stroke = _color_hex(d.get("color"))
            op = d.get("fill_opacity") if kind == "fill" else d.get("stroke_opacity")
            if op is None:
                op = 1.0
            # dedupe identical repeated paths (some producers emit borders twice)
            sig = (tuple(round(v, 1) for v in bbox), kind, fill, stroke,
                   round(float(d.get("width") or 0.0), 2), len(d["items"]))
            if sig in seen_draw:
                continue
            seen_draw.add(sig)

            # even-odd frame paths (outer rect minus inner rect = border ring):
            # decompose into up to 4 edge bars so the interior stays text
            frame = _frame_edges(d)
            if frame is not None:
                for eb in frame:
                    ex0, ey0, ex1, ey1 = eb
                    eshape = "hline" if (ey1 - ey0) <= (ex1 - ex0) else "vline"
                    pir.drawings.append(DrawCmd(
                        kind="fill", shape=eshape, bbox=eb, fill=fill or stroke,
                        stroke=None, width=0.0, opacity=float(op),
                        n_items=1, seqno=int(d.get("seqno") or 0)))
                continue

            shape = _classify_path(d)
            # a filled path with tiny height/width is effectively a rule
            if shape == "rect" and fill is not None:
                if r.height <= 2.5 and r.width > 8:
                    shape = "hline"
                elif r.width <= 2.5 and r.height > 8:
                    shape = "vline"
            pir.drawings.append(DrawCmd(
                kind=kind, shape=shape, bbox=bbox, fill=fill, stroke=stroke,
                width=float(d.get("width") or 0.0), opacity=float(op),
                n_items=len(d["items"]), seqno=int(d.get("seqno") or 0)))

        # ---- images
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception:
            infos = []
        seen = set()
        for inf in infos:
            xref = inf.get("xref", 0)
            bbox = tuple(inf["bbox"])
            key = (xref, tuple(round(v, 1) for v in bbox))
            if key in seen:
                continue
            seen.add(key)
            data, ext = None, "png"
            if keep_image_data and xref:
                try:
                    ex = doc.extract_image(xref)
                    data, ext = ex["image"], ex["ext"]
                    smask = ex.get("smask")
                    if smask:
                        # rebuild with alpha via pixmap
                        pix = fitz.Pixmap(doc, xref)
                        if pix.colorspace and pix.colorspace.n > 3:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        msk = fitz.Pixmap(doc, smask)
                        pix = fitz.Pixmap(pix, msk)
                        data, ext = pix.tobytes("png"), "png"
                except Exception:
                    data = None
            pir.images.append(ImageObj(
                bbox=bbox, xref=xref, width=int(inf.get("width", 0)),
                height=int(inf.get("height", 0)), data=data, ext=ext))

        ir.pages.append(pir)
    doc.close()
    return ir
