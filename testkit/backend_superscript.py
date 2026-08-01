"""Does PDFium's hardcoded `superscript=False` cost anything?

`parse_pdfium.py` reports `superscript=False` for every span, where `parse.py`
reads PyMuPDF's font flag. ROADMAP §3.1 queued "implement it in the backend"
ahead of the licence flip. But the writer does not read the parser's flag -- it
reads the *layout*, and two shared stages set the flag themselves from geometry
alone: `dialect._merge_row_lines` and `infer` both promote a small fragment
sitting above its host line's baseline (measured inside the em box, raised more
than 0.12x the host size). Neither looks at the backend.

So the question is not "does PDFium report superscript" but "does the DOCX carry
the same superscript runs either way", and that is measurable before writing any
backend code. This script answers it at both levels:

    parse   spans flagged by the parser itself
    layout  runs flagged after normalize() + infer(), which is what reaches the
            writer, plus the text of those runs so a count that matches by
            accident is still visible as a mismatch

    python testkit/backend_superscript.py
    python testkit/backend_superscript.py --only 02_research_paper

Exit non-zero if the layout-level flags disagree: that is the only level where
disagreement can reach a user.
"""
import argparse
import os
import sys

import _paths  # noqa: F401
import gate
import runall


def parse_level(backend, path):
    from exactdoc.backend import get_backend
    ir = get_backend(backend).parse_pdf(path, keep_image_data=False)
    hits = []
    for p in ir.pages:
        for b in p.blocks:
            for l in b.lines:
                for s in l.spans:
                    if s.superscript:
                        hits.append((p.number, s.text))
    return ir, hits


def layout_level(ir):
    """Superscript runs as the writer will see them: after the shared stages."""
    from exactdoc.dialect import normalize
    from exactdoc.infer import infer
    lay = infer(normalize(ir))
    hits = []
    for pg in lay.pages:
        for ch in pg.chunks:
            for el in ch.elements:
                for r in getattr(el, "runs", ()) or ():
                    if getattr(r, "superscript", False):
                        hits.append((getattr(el, "page_no", pg.number), r.text))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="+", default=None)
    ap.add_argument("--reference", default="pymupdf")
    ap.add_argument("--candidate", default="pdfium")
    a = ap.parse_args(argv)

    manifest = gate.load_manifest()
    if manifest is None:
        print("no corpus manifest")
        return 2
    srcs, problems = runall.resolve_corpus(manifest)
    for kind, doc, why in problems:
        print("CORPUS %-11s %-28s %s" % (kind, doc[:28], why))
    if a.only:
        srcs = [s for s in srcs if any(k in os.path.basename(s) for k in a.only)]
    if not srcs:
        print("no documents to compare")
        return 2

    print("%-24s %-17s %-17s %s"
          % ("document", "parse ref/cand", "layout ref/cand", "verdict"))
    disagree = []
    for s in srcs:
        name = os.path.basename(s)
        try:
            ir_a, pa = parse_level(a.reference, s)
            ir_b, pb = parse_level(a.candidate, s)
            la, lb = layout_level(ir_a), layout_level(ir_b)
        except Exception as e:
            print("%-24s %s: %s" % (name[:24], type(e).__name__, str(e)[:40]))
            disagree.append((name, "error"))
            continue
        ta = sorted(t.strip() for _, t in la if t.strip())
        tb = sorted(t.strip() for _, t in lb if t.strip())
        same = ta == tb
        verdict = "same" if same else "DIFFERS"
        if not same:
            disagree.append((name, "%d vs %d runs" % (len(ta), len(tb))))
        print("%-24s %-17s %-17s %s"
              % (name[:24], "%d/%d" % (len(pa), len(pb)),
                 "%d/%d" % (len(la), len(lb)), verdict))
        if not same:
            only_a = [t for t in ta if t not in tb][:6]
            only_b = [t for t in tb if t not in ta][:6]
            if only_a:
                print("    only %s: %s" % (a.reference, only_a))
            if only_b:
                print("    only %s: %s" % (a.candidate, only_b))

    print("\n%d of %d document(s) disagree at the layout level"
          % (len(disagree), len(srcs)))
    if not disagree:
        print("The parser flag is not load-bearing: normalize() and infer() "
              "recover superscript from geometry, so the backend hardcode costs "
              "nothing that reaches a DOCX. ROADMAP §3.1 is answered by "
              "measurement rather than by implementation.")
        return 0
    for name, why in disagree:
        print("  %-28s %s" % (name[:28], why))
    print("\nThe flag IS load-bearing on the documents above: implement it in "
          "the candidate backend, then re-run this.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
