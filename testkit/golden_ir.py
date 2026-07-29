"""Freeze the parser's output, so swapping the parser becomes verifiable.

exactdoc is AGPL only because PyMuPDF is. Moving to a permissive parser means
reimplementing the glyph->span->line->block clustering that every downstream
threshold was tuned against -- measured divergence between backends is up to
3.67x on block counts (testkit/backend_probe.py). Without a reference, such a
port is a rewrite that has to be re-tuned by hand and re-argued from scratch.

With one, it is a diff. These goldens record what the current backend produces
on every corpus document; a replacement backend is correct when it reproduces
them within tolerance. The existing tuning stops being a liability and becomes
the specification.

Stored as a compact structural digest rather than a full dump: page geometry,
element counts, and per-line rounded bbox + baseline + text hash + font/size.
That is what inference actually consumes, and it keeps the goldens small
enough to live in git and to diff by eye.

**The canonical freeze environment is CI Linux** (`.github/workflows/gate.yml`:
ubuntu-24.04 + fonts-liberation), for the same reason CI is the number of
record everywhere else in this project. A golden is a comparison between two
runs, and the corpus is *regenerated* on every machine: ReportLab and fpdf2 are
deterministic in their layout, but the library versions that produce the PDFs
and the PyMuPDF version that reads them are not fixed by this repository. So
each golden carries a manifest of the versions it was frozen with, and `verify`
says so when the running environment differs -- otherwise environment drift
arrives looking exactly like parser breakage, and the natural response to that
is to "fix" a parser that was never broken.

    python testkit/golden_ir.py freeze     # write goldens (+ env manifest)
    python testkit/golden_ir.py verify     # compare, exit non-zero on drift
"""
import argparse
import glob
import hashlib
import json
import os
import sys

import _paths  # noqa: F401

from exactdoc.parse import parse_pdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")

# Tolerances for a replacement backend. Coordinates are rounded to 0.1pt
# before hashing, so an exact match means agreement well inside a point.
TOL = {"n_lines": 0.02, "n_blocks": 0.05, "n_draws": 0.05, "chars": 0.005}


def _h(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:12]


# Everything that can legitimately change a golden without the parser changing.
# pymupdf reads the PDFs; reportlab and fpdf2 WRITE them, so their versions are
# part of the input, not of the environment around it.
MANIFEST_PKGS = ("pymupdf", "reportlab", "fpdf2")


def manifest():
    import platform
    try:
        from importlib.metadata import version, PackageNotFoundError
    except ImportError:                                   # py<3.8
        return {"platform": platform.system()}
    out = {}
    for pkg in MANIFEST_PKGS:
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "absent"
    out["python"] = "%d.%d" % sys.version_info[:2]
    out["platform"] = platform.system()
    return out


def manifest_delta(frozen, running):
    """Keys whose value differs, as 'key frozen->running'. Empty if identical."""
    if not frozen:
        return ["(golden carries no manifest -- frozen before this was recorded)"]
    return ["%s %s->%s" % (k, frozen.get(k, "?"), running.get(k, "?"))
            for k in sorted(set(frozen) | set(running))
            if frozen.get(k) != running.get(k)]


def digest(path):
    ir = parse_pdf(path, keep_image_data=False)
    pages = []
    for p in ir.pages:
        lines = []
        for b in p.blocks:
            for ln in b.lines:
                sp = ln.spans[0]
                lines.append([
                    [round(v, 1) for v in ln.bbox],
                    round(ln.baseline, 1),
                    _h(ln.text),
                    sp.font, round(sp.size, 2),
                    int(sp.bold) * 2 + int(sp.italic),
                ])
        draws = [[d.shape, [round(v, 1) for v in d.bbox], d.fill, d.stroke]
                 for d in p.drawings]
        pages.append({
            "size": [round(p.width, 1), round(p.height, 1)],
            "n_blocks": len(p.blocks),
            "n_lines": len(lines),
            "n_spans": sum(len(l.spans) for b in p.blocks for l in b.lines),
            "n_draws": len(p.drawings),
            "n_images": len(p.images),
            "n_links": len(p.links),
            "chars": sum(len(l.text) for b in p.blocks for l in b.lines),
            "lines": lines,
            "draws": draws,
        })
    return {"backend": "pymupdf", "manifest": manifest(), "pages": pages}


# The corpus is REGENERATED on each machine, so a golden is only meaningful
# for producers whose output is deterministic across platforms. ReportLab and
# fpdf2 lay out with metric-defined core-14 fonts and are stable. Chromium
# (Skia) depends on the browser build and the system font stack, and
# LibreOffice on its own version -- their PDFs legitimately differ between a
# Windows workstation and a Linux runner, so freezing them makes CI fail for
# reasons that have nothing to do with the parser. Found exactly that way: the
# first CI run rejected eight Skia documents.
#
# This costs nothing that matters. The golden guards the PARSER, and the
# parser does not know which producer made its input.
STABLE_PRODUCERS = ("reportlab", "fpdf", "py-pdf")


def _stable(path):
    import fitz
    d = fitz.open(path)
    prod = ((d.metadata or {}).get("producer") or "").lower()
    creator = ((d.metadata or {}).get("creator") or "").lower()
    d.close()
    if not prod and not creator:
        return True                      # fpdf2 writes no producer
    return any(s in prod or s in creator for s in STABLE_PRODUCERS)


def corpus():
    pdfs = sorted(glob.glob(os.path.join(ROOT, "corpus", "pdfs", "*.pdf")))
    pdfs += sorted(glob.glob(os.path.join(ROOT, "testkit", "adv", "*.pdf")))
    return [p for p in pdfs if _stable(p)]


def freeze():
    os.makedirs(GOLD, exist_ok=True)
    pdfs = corpus()
    if not pdfs:
        print("no corpus; run corpus/make_corpus.py and testkit/gen_corpus.py")
        return 2
    for p in pdfs:
        name = os.path.splitext(os.path.basename(p))[0]
        d = digest(p)
        with open(os.path.join(GOLD, name + ".json"), "w") as f:
            json.dump(d, f, separators=(",", ":"), sort_keys=True)
        tot = sum(pg["n_lines"] for pg in d["pages"])
        print("  froze %-26s %2d pages %5d lines" % (name[:26], len(d["pages"]), tot))
    print("%d goldens in %s" % (len(pdfs), GOLD))
    return 0


def verify():
    pdfs = corpus()
    if not pdfs:
        print("no corpus; run the generators first")
        return 2
    running = manifest()
    deltas = set()
    bad = 0
    for p in pdfs:
        name = os.path.splitext(os.path.basename(p))[0]
        gp = os.path.join(GOLD, name + ".json")
        if not os.path.exists(gp):
            print("  MISSING golden for %s" % name)
            bad += 1
            continue
        want = json.load(open(gp))
        got = digest(p)
        deltas.update(manifest_delta(want.get("manifest"), running))
        if len(want["pages"]) != len(got["pages"]):
            print("  %-26s page count %d -> %d" %
                  (name[:26], len(want["pages"]), len(got["pages"])))
            bad += 1
            continue
        diffs = []
        for i, (a, b) in enumerate(zip(want["pages"], got["pages"]), 1):
            for k, tol in TOL.items():
                ka, kb = a[k], b[k]
                if ka == 0 and kb == 0:
                    continue
                if abs(kb - ka) > max(1, tol * max(ka, 1)):
                    diffs.append("p%d %s %s->%s" % (i, k.lstrip("n_"), ka, kb))
            if a["lines"] != b["lines"]:
                n = sum(1 for x, y in zip(a["lines"], b["lines"]) if x != y)
                diffs.append("p%d %d line rows differ" % (i, n or abs(
                    len(a["lines"]) - len(b["lines"]))))
        if diffs:
            bad += 1
            print("  %-26s %s" % (name[:26], "; ".join(diffs[:4])))
        else:
            print("  %-26s ok" % name[:26])
    print("\n%d/%d documents match the golden IR" % (len(pdfs) - bad, len(pdfs)))
    if deltas:
        print("\nNOTE: this environment is not the one the goldens were frozen "
              "in:\n  " + "\n  ".join(sorted(deltas)))
        print("  Running:  " + ", ".join("%s=%s" % kv for kv in sorted(running.items())))
        if bad:
            print("  Drift above may be attributable to that and NOT to the "
                  "parser. Re-freeze only on the canonical environment "
                  "(CI Linux), never to make a failure go away.")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["freeze", "verify"])
    sys.exit(freeze() if ap.parse_args().cmd == "freeze" else verify())
