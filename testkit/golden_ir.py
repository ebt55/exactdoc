"""Freeze and verify backend-specific parser-IR digests.

Goldens are a microscope for a selected parser, not a cross-backend acceptance
rule (that is ``backend_parity.py``). Shipping PyMuPDF retains the legacy flat
``testkit/golden/*.json`` contract; candidate backends live under
``testkit/golden/<backend>/`` and can never reuse those files.

    python testkit/golden_ir.py freeze --backend pdfium
    python testkit/golden_ir.py verify                 # PRODUCT backend
    python testkit/golden_ir.py verify --backend pdfium
"""
import argparse
import glob
import hashlib
import json
import os
import sys

import _paths  # noqa: F401

from exactdoc.backend import get_backend
from exactdoc.options import BACKENDS, PRODUCT, canonical_backend

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")

# Coordinates are rounded to 0.1pt before hashing, so an exact match means
# agreement well inside a point.
TOL = {"n_lines": 0.02, "n_blocks": 0.05, "n_draws": 0.05, "chars": 0.005}
BACKEND_PACKAGES = {"pdfium": "pypdfium2", "pymupdf": "pymupdf"}
INPUT_PACKAGES = ("reportlab", "fpdf2")
STABLE_PRODUCERS = ("reportlab", "fpdf", "py-pdf")


def _h(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:12]


def selected_backend(name=None):
    """Canonical selected backend, defaulting exactly to PRODUCT.backend."""
    return canonical_backend(name or PRODUCT.backend)


def gold_dir(backend=None):
    chosen = selected_backend(backend)
    return GOLD if chosen == "pymupdf" else os.path.join(GOLD, chosen)


def golden_path(name, backend=None):
    return os.path.join(gold_dir(backend), name + ".json")


def manifest(backend=None):
    """Environment facts that affect this backend's digest and its PDFs."""
    import platform
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - Python 3.9+ is supported
        return {"backend": selected_backend(backend), "platform": platform.system()}
    chosen = selected_backend(backend)
    out = {"backend": chosen}
    for pkg in (BACKEND_PACKAGES[chosen],) + INPUT_PACKAGES:
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "absent"
    out["python"] = "%d.%d" % sys.version_info[:2]
    out["platform"] = platform.system()
    return out


def manifest_delta(frozen, running):
    if not frozen:
        return ["(golden carries no manifest -- frozen before this was recorded)"]
    return ["%s %s->%s" % (k, frozen.get(k, "?"), running.get(k, "?"))
            for k in sorted(set(frozen) | set(running))
            if frozen.get(k) != running.get(k)]


def digest(path, backend=None):
    """Digest ``path`` through the selected backend seam, never parse directly."""
    chosen = selected_backend(backend)
    parser = get_backend(chosen)
    ir = parser.parse_pdf(path, keep_image_data=False)
    pages = []
    for p in ir.pages:
        lines = []
        for b in p.blocks:
            for ln in b.lines:
                sp = ln.spans[0]
                lines.append([
                    [round(v, 1) for v in ln.bbox], round(ln.baseline, 1),
                    _h(ln.text), sp.font, round(sp.size, 2),
                    int(sp.bold) * 2 + int(sp.italic),
                ])
        draws = [[d.shape, [round(v, 1) for v in d.bbox], d.fill, d.stroke]
                 for d in p.drawings]
        pages.append({
            "size": [round(p.width, 1), round(p.height, 1)],
            "n_blocks": len(p.blocks), "n_lines": len(lines),
            "n_spans": sum(len(l.spans) for b in p.blocks for l in b.lines),
            "n_draws": len(p.drawings), "n_images": len(p.images),
            "n_links": len(p.links),
            "chars": sum(len(l.text) for b in p.blocks for l in b.lines),
            "lines": lines, "draws": draws,
        })
    return {"backend": parser.name, "manifest": manifest(chosen), "pages": pages,
            "ir_metadata": dict(ir.meta or {})}


def _stable(path, backend=None):
    """Use selected-backend IR metadata; unknown producers are permissive."""
    ir = get_backend(selected_backend(backend)).parse_pdf(path,
                                                          keep_image_data=False)
    meta = {str(k).lower(): str(v).lower() for k, v in (ir.meta or {}).items()}
    producer = " ".join(meta.get(k, "") for k in ("producer", "creator"))
    return not producer or any(token in producer for token in STABLE_PRODUCERS)


def corpus(backend=None):
    pdfs = sorted(glob.glob(os.path.join(ROOT, "corpus", "pdfs", "*.pdf")))
    pdfs += sorted(glob.glob(os.path.join(ROOT, "testkit", "adv", "*.pdf")))
    return [p for p in pdfs if _stable(p, backend)]


def freeze(backend=None):
    chosen = selected_backend(backend)
    os.makedirs(gold_dir(chosen), exist_ok=True)
    pdfs = corpus(chosen)
    if not pdfs:
        print("no corpus; run corpus/make_corpus.py and testkit/gen_corpus.py")
        return 2
    for p in pdfs:
        name = os.path.splitext(os.path.basename(p))[0]
        d = digest(p, chosen)
        with open(golden_path(name, chosen), "w") as f:
            json.dump(d, f, separators=(",", ":"), sort_keys=True)
        tot = sum(pg["n_lines"] for pg in d["pages"])
        print("  froze %-26s %2d pages %5d lines" % (name[:26], len(d["pages"]), tot))
    print("%d %s goldens in %s" % (len(pdfs), chosen, gold_dir(chosen)))
    return 0


def verify(backend=None):
    chosen = selected_backend(backend)
    pdfs = corpus(chosen)
    if not pdfs:
        print("no corpus; run the generators first")
        return 2
    running, deltas, bad = manifest(chosen), set(), 0
    for p in pdfs:
        name = os.path.splitext(os.path.basename(p))[0]
        gp = golden_path(name, chosen)
        if not os.path.exists(gp):
            legacy = os.path.join(GOLD, name + ".json")
            suffix = (" (legacy PyMuPDF golden is archived at %s; it will not be "
                      "used for %s)" % (legacy, chosen)) if os.path.exists(legacy) else ""
            print("  MISSING %s golden for %s%s" % (chosen, name, suffix))
            bad += 1
            continue
        with open(gp) as f:
            want = json.load(f)
        if want.get("backend") != chosen:
            print("  BACKEND MISMATCH %-18s frozen for %r, requested %r"
                  % (name[:18], want.get("backend"), chosen))
            bad += 1
            continue
        if chosen == "pymupdf":
            frozen_pkg = (want.get("manifest") or {}).get(
                BACKEND_PACKAGES[chosen])
            running_pkg = running.get(BACKEND_PACKAGES[chosen])
            if not frozen_pkg or frozen_pkg != running_pkg:
                print("  EXTRACTOR MISMATCH %-16s frozen PyMuPDF %r, running %r"
                      % (name[:16], frozen_pkg, running_pkg))
                bad += 1
                continue
        got = digest(p, chosen)
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
                if ka != 0 or kb != 0:
                    if abs(kb - ka) > max(1, tol * max(ka, 1)):
                        diffs.append("p%d %s %s->%s" % (i, k.lstrip("n_"), ka, kb))
            if a["lines"] != b["lines"]:
                n = sum(1 for x, y in zip(a["lines"], b["lines"]) if x != y)
                diffs.append("p%d %d line rows differ" %
                             (i, n or abs(len(a["lines"]) - len(b["lines"]))))
        if diffs:
            bad += 1
            print("  %-26s %s" % (name[:26], "; ".join(diffs[:4])))
        else:
            print("  %-26s ok" % name[:26])
    print("\n%d/%d documents match the %s golden IR" %
          (len(pdfs) - bad, len(pdfs), chosen))
    if deltas:
        print("\nNOTE: this environment is not the one the goldens were frozen in:\n  "
              + "\n  ".join(sorted(deltas)))
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["freeze", "verify"])
    ap.add_argument("--backend", choices=BACKENDS, default=PRODUCT.backend,
                    help="parser backend (default: PRODUCT.backend)")
    args = ap.parse_args()
    sys.exit(freeze(args.backend) if args.cmd == "freeze" else verify(args.backend))
