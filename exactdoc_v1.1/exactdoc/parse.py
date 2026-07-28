"""PDF -> IR parser built on PyMuPDF."""
import re
from typing import List, Optional

import fitz

from .model import DocIR, PageIR, TextBlock, Line, Span, DrawCmd, ImageObj

_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")


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
    doc = fitz.open(path)
    ir = DocIR(path=path, meta=dict(doc.metadata or {}))
    tflags = (fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP)

    for pno, page in enumerate(doc):
        pw, ph = page.rect.width, page.rect.height
        pir = PageIR(number=pno + 1, width=pw, height=ph)

        # ---- links first (so spans can be tagged)
        links = []
        for lk in page.get_links():
            if lk.get("uri"):
                r = lk["from"]
                links.append({"bbox": (r.x0, r.y0, r.x1, r.y1), "uri": lk["uri"]})
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
                    text = sp.get("text", "")
                    if text == "":
                        continue
                    flags = sp.get("flags", 0)
                    font = _SUBSET_RE.sub("", sp.get("font", "") or "")
                    fl = font.lower()
                    bold = bool(flags & 16) or "bold" in fl or "black" in fl or "heavy" in fl
                    italic = bool(flags & 2) or "italic" in fl or "oblique" in fl
                    bbox = tuple(sp["bbox"])
                    uri = None
                    for lk in links:
                        lb = lk["bbox"]
                        ov = (max(0, min(bbox[2], lb[2]) - max(bbox[0], lb[0])) *
                              max(0, min(bbox[3], lb[3]) - max(bbox[1], lb[1])))
                        if ov > 0.5 * max(1e-6, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])):
                            uri = lk["uri"]
                            break
                    spans.append(Span(
                        text=text, font=font, size=float(sp.get("size", 10.0)),
                        color=_color_hex(sp.get("color", 0)) or "#000000",
                        bold=bold, italic=italic,
                        mono=bool(flags & 8) or "courier" in fl or "mono" in fl,
                        serif=bool(flags & 4),
                        superscript=bool(flags & 1),
                        bbox=bbox, origin=tuple(sp.get("origin", (bbox[0], bbox[3]))),
                        link=uri,
                    ))
                if spans:
                    lb = tuple(ln["bbox"])
                    lines.append(Line(spans=spans, bbox=lb))
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
