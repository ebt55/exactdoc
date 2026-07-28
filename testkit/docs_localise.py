"""Localise where Google Docs injects space, paragraph by paragraph.

Reads a DOCX's paragraph properties, then finds each paragraph's rendered y in
the LibreOffice render and the Docs render. The paragraph where (Docs - LO)
jumps is the construct responsible.

    python testkit/docs_localise.py testkit/batch/c8_toc_links.docx
"""
import os
import re
import sys
import zipfile

import _paths  # noqa: F401
import fitz
from lxml import etree

import harness

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _pt(v, scale=20.0):
    return None if v is None else round(int(v) / scale, 2)


def docx_paragraphs(path):
    """[(text, props)] in document order."""
    out = []
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find("{%s}body" % W)
    for p in body.iter("{%s}p" % W):
        txt = "".join(t.text or "" for t in p.iter("{%s}t" % W))
        ppr = p.find("{%s}pPr" % W)
        props = {"before": None, "after": None, "line": None, "rule": None,
                 "style": None, "sizes": set(), "sect": False, "border": False}
        if ppr is not None:
            sp = ppr.find("{%s}spacing" % W)
            if sp is not None:
                props["before"] = _pt(sp.get("{%s}before" % W))
                props["after"] = _pt(sp.get("{%s}after" % W))
                props["line"] = _pt(sp.get("{%s}line" % W))
                props["rule"] = sp.get("{%s}lineRule" % W)
            st = ppr.find("{%s}pStyle" % W)
            props["style"] = st.get("{%s}val" % W) if st is not None else None
            props["sect"] = ppr.find("{%s}sectPr" % W) is not None
            props["border"] = ppr.find("{%s}pBdr" % W) is not None
        for rpr in p.iter("{%s}rPr" % W):
            szel = rpr.find("{%s}sz" % W)
            if szel is not None:
                props["sizes"].add(_pt(szel.get("{%s}val" % W), 2.0))
        out.append((" ".join(txt.split()), props))
    return out


def rendered_ys(pdf):
    """{normalised text -> y0 of first occurrence}"""
    d = fitz.open(pdf)
    pos, page_of = {}, {}
    for p in d:
        for b in p.get_text("dict")["blocks"]:
            if b.get("type"):
                continue
            for ln in b["lines"]:
                t = " ".join("".join(s["text"] for s in ln["spans"]).split())
                if t and t not in pos:
                    pos[t] = ln["bbox"][1]
                    page_of[t] = p.number
    d.close()
    return pos, page_of


def main(docx):
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quirks")
    os.makedirs(out, exist_ok=True)
    lo_pdf = harness.docx_to_pdf(docx, out)
    import gdocs_oracle as G
    svc = G._service(interactive=False)
    gd_pdf = os.path.join(out, os.path.basename(docx) + ".loc.gdocs.pdf")
    G.roundtrip(svc, docx, gd_pdf)

    lo, lop = rendered_ys(lo_pdf)
    gd, gdp = rendered_ys(gd_pdf)

    print("%-40s %6s %6s %6s %5s %7s %7s %8s" %
          ("paragraph", "before", "line", "rule", "size", "LO_y", "GD_y", "GD-LO"))
    prev = None
    for txt, pr in docx_paragraphs(docx):
        if not txt:
            continue
        if txt not in lo or txt not in gd:
            continue
        # normalise for page: add page height so cross-page stays monotonic
        ly = lo[txt] + 792.0 * lop[txt]
        gy = gd[txt] + 792.0 * gdp[txt]
        delta = gy - ly
        jump = ""
        if prev is not None and abs(delta - prev) > 2.0:
            jump = "  <== +%.1f HERE" % (delta - prev)
        sizes = ",".join("%.1f" % s for s in sorted(pr["sizes"])) or "-"
        print("%-40s %6s %6s %6s %5s %7.1f %7.1f %8.1f%s" % (
            txt[:40],
            "-" if pr["before"] is None else "%.1f" % pr["before"],
            "-" if pr["line"] is None else "%.1f" % pr["line"],
            (pr["rule"] or "-")[:6], sizes, ly, gy, delta, jump))
        prev = delta


if __name__ == "__main__":
    main(sys.argv[1])
