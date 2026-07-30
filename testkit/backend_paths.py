"""Which coordinate space are PDFium's path segment points in?

Written because getting this wrong cost a session. `parse_pdfium._page_paths`
took path bounding boxes from `FPDFPageObj_GetBounds` (page space, and the INK
envelope: a stroked path inflated by its line width) while `_classify`,
`_rect_pts` and the frame-edge decomposition read `FPDFPath_GetPathSegment`
points -- which PDFium reports in **object space**, before the path object's own
transform. On a Chromium document every path carries a non-identity matrix, so
those two families of numbers are not comparable, and an experiment that
replaced the bbox with a raw-points bbox silently scaled the whole page.

The failure mode is invisible at the microscope: pick two paths to eyeball and
you may well pick identity-matrix ones, which agree perfectly. It is only
visible across a corpus, which is what this measures.

    python testkit/backend_paths.py                  # the whole corpus
    python testkit/backend_paths.py 03_tech c7_code  # named documents
    python testkit/backend_paths.py --show 6 c1      # per-path detail

Reads: raw points, matrix-transformed points, and GetBounds, per path object.
Reports how often each reconstructs GetBounds, and by how much they miss.
"""
import argparse
import ctypes
import glob
import os
import sys

import pypdfium2 as pdfium
import pypdfium2.raw as raw

import _paths  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# GetBounds inflates a stroked path by its line width in each direction, so a
# geometric bbox reconstructs it only after that envelope is added back. 0.6pt
# of slack absorbs bezier control points and PDFium's own rounding.
TOL = 0.6


def _matrix(obj):
    """(a, b, c, d, e, f) for a path object, or None if unavailable."""
    try:
        m = raw.FS_MATRIX()
        if raw.FPDFPageObj_GetMatrix(obj.raw, ctypes.byref(m)):
            return (m.a, m.b, m.c, m.d, m.e, m.f)
    except Exception:
        pass
    return None


def _is_identity(m):
    if m is None:
        return True
    a, b, c, d, e, f = m
    return (abs(a - 1) < 1e-6 and abs(b) < 1e-6 and abs(c) < 1e-6
            and abs(d - 1) < 1e-6 and abs(e) < 1e-6 and abs(f) < 1e-6)


def _apply(m, x, y):
    if m is None:
        return x, y
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def _bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _miss(geom, bounds, sw):
    """How far the geometric bbox is from GetBounds once the stroke envelope
    is added back. 0.0 means it reconstructs it exactly.

    `sw` must be 0 for an unstroked path: PDFium reports a stroke WIDTH of 1.0
    on fill-only objects, which is not a stroke and does not inflate anything.
    Inflating by it regardless made every filled rect miss by exactly 1.00pt --
    a suspiciously round constant, which is what gave the mistake away.
    """
    inflated = (geom[0] - sw, geom[1] - sw, geom[2] + sw, geom[3] + sw)
    return max(abs(inflated[i] - bounds[i]) for i in range(4))


def _stroke_width(obj, m):
    """Stroke width in PAGE space, or 0.0 when the path is not stroked."""
    fillmode = ctypes.c_int(); stroke = ctypes.c_int()
    if not raw.FPDFPath_GetDrawMode(obj.raw, ctypes.byref(fillmode),
                                    ctypes.byref(stroke)):
        return 0.0
    if not stroke.value:
        return 0.0
    sa = ctypes.c_uint()
    r_ = ctypes.c_uint(); g = ctypes.c_uint(); b = ctypes.c_uint()
    raw.FPDFPageObj_GetStrokeColor(obj.raw, ctypes.byref(r_), ctypes.byref(g),
                                   ctypes.byref(b), ctypes.byref(sa))
    if sa.value == 0:
        return 0.0
    sw = ctypes.c_float()
    raw.FPDFPageObj_GetStrokeWidth(obj.raw, ctypes.byref(sw))
    w = float(sw.value)
    # The width is in object space like the points, so it scales with the matrix.
    if m is not None:
        a, b_, c, d, _, _ = m
        scale = (abs(a * d - b_ * c)) ** 0.5
        if scale > 1e-9:
            w *= scale
    return w


def report(path, show=0):
    name = os.path.splitext(os.path.basename(path))[0]
    pdf = pdfium.PdfDocument(path)
    n_paths = n_nonid = raw_ok = tx_ok = 0
    raw_worst = tx_worst = 0.0
    detail = []
    for pno in range(len(pdf)):
        page = pdf[pno]
        for obj in page.get_objects():
            try:
                if raw.FPDFPageObj_GetType(obj.raw) != raw.FPDF_PAGEOBJ_PATH:
                    continue
            except Exception:
                continue
            l = ctypes.c_float(); b = ctypes.c_float()
            r_ = ctypes.c_float(); t = ctypes.c_float()
            if not raw.FPDFPageObj_GetBounds(obj.raw, ctypes.byref(l),
                                             ctypes.byref(b), ctypes.byref(r_),
                                             ctypes.byref(t)):
                continue
            bounds = (float(l.value), float(b.value),
                      float(r_.value), float(t.value))
            pts = []
            for i in range(max(0, raw.FPDFPath_CountSegments(obj.raw))):
                seg = raw.FPDFPath_GetPathSegment(obj.raw, i)
                if not seg:
                    continue
                sx = ctypes.c_float(); sy = ctypes.c_float()
                raw.FPDFPathSegment_GetPoint(seg, ctypes.byref(sx), ctypes.byref(sy))
                pts.append((float(sx.value), float(sy.value)))
            if not pts:
                continue
            m = _matrix(obj)
            sw_page = _stroke_width(obj, m)

            n_paths += 1
            if not _is_identity(m):
                n_nonid += 1
            rb = _bbox(pts)
            tb = _bbox([_apply(m, x, y) for x, y in pts])
            rmiss = _miss(rb, bounds, sw_page)
            tmiss = _miss(tb, bounds, sw_page)
            raw_ok += rmiss <= TOL
            tx_ok += tmiss <= TOL
            raw_worst = max(raw_worst, rmiss)
            tx_worst = max(tx_worst, tmiss)
            if len(detail) < show:
                detail.append((m, rb, tb, bounds, sw_page, rmiss, tmiss))
    pdf.close()

    print("\n== %s" % name)
    print("  path objects            %d" % n_paths)
    print("  non-identity matrix     %d of %d" % (n_nonid, n_paths))
    print("  raw points reconstruct GetBounds        %d of %d   (worst miss %.2fpt)"
          % (raw_ok, n_paths, raw_worst))
    print("  matrix-transformed reconstruct GetBounds %d of %d   (worst miss %.2fpt)"
          % (tx_ok, n_paths, tx_worst))
    for m, rb, tb, bounds, sw, rmiss, tmiss in detail:
        print("    matrix %s" % (None if m is None else
                                 "(%.3f %.3f %.3f %.3f %.1f %.1f)" % m))
        print("      raw    %s  miss %.2f" % (_fmt(rb), rmiss))
        print("      matrix %s  miss %.2f" % (_fmt(tb), tmiss))
        print("      bounds %s  stroke %.2f" % (_fmt(bounds), sw))
    return {"paths": n_paths, "nonid": n_nonid, "raw_ok": raw_ok,
            "tx_ok": tx_ok, "raw_worst": raw_worst, "tx_worst": tx_worst}


def _fmt(b):
    return "x=%7.2f..%-7.2f y=%7.2f..%-7.2f" % (b[0], b[2], b[1], b[3])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--show", type=int, default=0,
                    help="print N per-path examples")
    a = ap.parse_args()
    srcs = sorted(glob.glob(os.path.join(ROOT, "corpus", "pdfs", "*.pdf")))
    srcs += sorted(glob.glob(os.path.join(ROOT, "testkit", "adv", "*.pdf")))
    if a.names:
        srcs = [s for s in srcs if any(k in os.path.basename(s) for k in a.names)]
    if not srcs:
        print("no matching corpus documents")
        return 2
    tot = {"paths": 0, "nonid": 0, "raw_ok": 0, "tx_ok": 0}
    for s in srcs:
        r = report(s, a.show)
        for k in tot:
            tot[k] += r[k]
    print("\n%-24s %d path objects, %d with a non-identity matrix"
          % ("CORPUS TOTAL", tot["paths"], tot["nonid"]))
    print("%-24s raw points reconstruct %d, matrix-transformed reconstruct %d"
          % ("", tot["raw_ok"], tot["tx_ok"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
