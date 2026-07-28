"""Inventory the OOXML vocabulary actually emitted, and flag Google-Docs risks."""
import _paths  # noqa: F401  (sets sys.path, finds soffice/chrome)
import sys, glob, os, zipfile, re
from collections import Counter
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Constructs Google Docs is known to drop, flatten, or mis-import on .docx upload.
RISK = {
    "w:cols":        "multi-column sections - Docs supports 1-3 equal cols; "
                     "unequal widths/custom spacing get normalised",
    "w:tblLayout":   "fixed table layout - Docs re-computes column widths",
    "w:fldSimple":   "field codes - PAGE/NUMPAGES survive; most others flatten",
    "w:framePr":     "text frames - Docs drops framing, text reflows inline",
    "w:pict":        "VML picture - not supported",
    "w:txbxContent": "text box - Docs drops or converts to inline",
    "w:drawing":     "DrawingML - inline images OK, anchored/floating are not",
    "w:tabs":        "custom tab stops - imported, but leader dots are lossy",
    "w:sectPr":      "section properties - Docs keeps page size/margins only "
                     "for the FIRST section; mid-document geometry changes are "
                     "flattened to the first section's page setup",
    "w:vAlign":      "cell vertical alignment - supported",
    "w:shd":         "shading - supported on runs/paras/cells",
    "w:spacing":     "spacing - lineRule=exact is honoured",
    "w:ind":         "indents - supported",
    "w:br":          "breaks - page/column breaks supported",
    "w:noProof":     "-",
}
CRITICAL = {"w:framePr", "w:pict", "w:txbxContent"}


def audit(path):
    counts = Counter()
    with zipfile.ZipFile(path) as z:
        parts = [n for n in z.namelist() if n.endswith(".xml") and n.startswith("word/")]
        for n in parts:
            try:
                root = etree.fromstring(z.read(n))
            except Exception:
                continue
            for el in root.iter():
                if not isinstance(el.tag, str):
                    continue
                tag = etree.QName(el).localname
                ns = etree.QName(el).namespace
                pfx = "w:" if ns == W else (ns or "").rsplit("/", 1)[-1][:6] + ":"
                counts[pfx + tag] += 1
        media = [n for n in z.namelist() if n.startswith("word/media/")]
        # section count + column usage
        doc = etree.fromstring(z.read("word/document.xml"))
        sects = doc.findall(".//{%s}sectPr" % W)
        cols = [c.get("{%s}num" % W) for s in sects for c in s.findall("{%s}cols" % W)]
    return counts, len(sects), cols, media


if __name__ == "__main__":
    files = []
    for a in sys.argv[1:]:
        files += sorted(glob.glob(a))
    agg = Counter()
    print("%-32s %-6s %-8s %-6s %s" % ("docx", "sects", "cols", "media", "notes"))
    for f in files:
        c, ns, cols, media = audit(f)
        agg.update(c)
        print("%-32s %-6d %-8s %-6d" % (os.path.basename(f)[:32], ns,
                                        ",".join(x for x in cols if x) or "-", len(media)))
    print("\n== emitted vocabulary (aggregate) ==")
    for tag, n in agg.most_common():
        if tag in RISK:
            flag = "!! " if tag in CRITICAL else "   "
            print("%s%-16s %-8d %s" % (flag, tag, n, RISK[tag]))
    print("\n== risk constructs NOT present (good) ==")
    for t in sorted(set(RISK) - set(agg)):
        print("   %-16s" % t)
