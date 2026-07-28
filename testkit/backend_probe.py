"""How much of the tuning is coupled to PyMuPDF?

The licence question (PyMuPDF is AGPL, so exactdoc must be) is really a
risk question: every threshold in dialect.py and infer.py was calibrated
against what `page.get_text("dict")` returns, and a different parser returns
a different shape. Swapping first wastes tuning; tuning first raises the cost
of swapping. Neither argument settles it -- a measurement does.

This compares the permissive candidates against PyMuPDF on the corpus, on the
axes the converter actually consumes:

  chars      raw text recovered (does the parser see the same glyphs?)
  lines      how many visual lines the parser reports -- the single biggest
             coupling, because inference rebuilds paragraphs from lines
  blocks     paragraph-ish grouping (PyMuPDF and pdfminer both provide it)
  fonts      is font family/size/bold/italic available per span?
  drawings   vector paths, with fill/stroke, needed for tables and figures

    python testkit/backend_probe.py
"""
import os
import glob
import statistics as st

import _paths  # noqa: F401


def pymupdf_stats(path):
    import fitz
    d = fitz.open(path)
    chars = lines = blocks = spans = draws = 0
    fonts = set()
    for p in d:
        td = p.get_text("dict")
        for b in td["blocks"]:
            if b.get("type"):
                continue
            blocks += 1
            for ln in b["lines"]:
                lines += 1
                for s in ln["spans"]:
                    spans += 1
                    chars += len(s["text"])
                    fonts.add(s["font"])
        draws += len(p.get_drawings())
    d.close()
    return dict(chars=chars, lines=lines, blocks=blocks, spans=spans,
                draws=draws, fonts=len(fonts))


def pdfminer_stats(path):
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer, LTTextLine, LTChar, LTCurve, LTLine, LTRect
    chars = lines = blocks = draws = 0
    fonts = set()
    for page in extract_pages(path):
        for el in page:
            if isinstance(el, LTTextContainer):
                blocks += 1
                for ln in el:
                    if isinstance(ln, LTTextLine):
                        lines += 1
                        for c in ln:
                            if isinstance(c, LTChar):
                                chars += 1
                                fonts.add(c.fontname)
            elif isinstance(el, (LTCurve, LTLine, LTRect)):
                draws += 1
    return dict(chars=chars, lines=lines, blocks=blocks, spans=-1,
                draws=draws, fonts=len(fonts))


def pypdfium_stats(path):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    chars = 0
    objs = 0
    for i in range(len(doc)):
        page = doc[i]
        tp = page.get_textpage()
        chars += len(tp.get_text_bounded() or "")
        try:
            objs += sum(1 for _ in page.get_objects())
        except Exception:
            pass
    return dict(chars=chars, lines=-1, blocks=-1, spans=-1,
                draws=objs, fonts=-1)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdfs = sorted(glob.glob(os.path.join(root, "corpus", "pdfs", "*.pdf")))
    pdfs += sorted(glob.glob(os.path.join(root, "testkit", "adv", "*.pdf")))
    pdfs += sorted(glob.glob(os.path.join(root, "testkit", "real", "*.pdf")))
    if not pdfs:
        print("no corpus; run corpus/make_corpus.py and testkit/gen_corpus.py")
        return

    print("%-24s %-9s %8s %7s %7s %7s %7s" %
          ("document", "backend", "chars", "lines", "blocks", "draws", "fonts"))
    ratios = {"lines": [], "blocks": [], "chars": [], "draws": []}
    for p in pdfs:
        name = os.path.basename(p)[:24]
        try:
            mu = pymupdf_stats(p)
        except Exception as e:
            print("%-24s pymupdf   FAILED %s" % (name, str(e)[:40]))
            continue
        print("%-24s %-9s %8d %7d %7d %7d %7d" % (
            name, "pymupdf", mu["chars"], mu["lines"], mu["blocks"],
            mu["draws"], mu["fonts"]))
        for label, fn in (("pdfminer", pdfminer_stats), ("pypdfium2", pypdfium_stats)):
            try:
                s = fn(p)
            except Exception as e:
                print("%-24s %-9s FAILED %s" % ("", label, str(e)[:46]))
                continue
            print("%-24s %-9s %8d %7s %7s %7d %7s" % (
                "", label, s["chars"],
                s["lines"] if s["lines"] >= 0 else "-",
                s["blocks"] if s["blocks"] >= 0 else "-",
                s["draws"], s["fonts"] if s["fonts"] >= 0 else "-"))
            if label == "pdfminer":
                for k in ("lines", "blocks", "chars", "draws"):
                    if mu[k] > 0 and s[k] > 0:
                        ratios[k].append(s[k] / mu[k])

    print("\n== pdfminer.six relative to PyMuPDF (1.00 = identical) ==")
    for k, v in ratios.items():
        if v:
            print("  %-8s median %.2f   range %.2f - %.2f   (n=%d)" %
                  (k, st.median(v), min(v), max(v), len(v)))


if __name__ == "__main__":
    main()
