"""How long does one conversion take? One document at a time, nothing beside it.

    python testkit/serial_timing.py --profile product --docs y13_irs_pub501.pdf y12_irs_pub15.pdf
    python testkit/serial_timing.py --profile product --from-sweep S.sweep.json --over-s 40
    python testkit/serial_timing.py ... --json run.timing.json

The beta bar's speed criterion (docs/beta-bar.md, criterion 2) is about what a
tester waits for, and a tester converts one document at a time. A quality
sweep converts six side by side while LibreOffice evaluates others, and its
convert_s ran 1.4-2.3x a lone conversion's (WP20b,
docs/evidence/refine-speed-2026-10-05.json). This tool times each document
alone, in the selected profile, and records the refine loop's per-round split
and the word/*.xml digests (so a timing run doubles as an output check).
beta_readiness.py prefers these numbers over a sweep's for criterion 2.

A measurement, never a gate. Output schema `exactdoc.serial-timing.v1`.
"""
import _paths  # noqa: F401  (sets sys.path)
import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import warnings
import zipfile

import corpus_manifest

SCHEMA = "exactdoc.serial-timing.v1"


def _profile(name):
    from exactdoc.options import PRODUCT, RAW, PDFIUM_GDOCS_CANDIDATE
    return {"product": PRODUCT, "raw": RAW, "gdocs": PDFIUM_GDOCS_CANDIDATE}[name]


def _paths_by_doc():
    out = {}
    man = corpus_manifest.load()
    for doc in man["documents"]:
        out[doc] = (corpus_manifest.fixture_path(doc, man),
                    man["documents"][doc].get("src_pages"))
    exp = corpus_manifest.load_expansion()
    for doc, spec in exp["documents"].items():
        out[doc] = (corpus_manifest.expansion_fixture_path(doc), spec.get("src_pages"))
    return out


def time_one(path, opts):
    from exactdoc.convert import convert_result
    from exactdoc.errors import ExactdocError, OracleDegradedWarning
    out = os.path.join(tempfile.mkdtemp(prefix="st_"), "o.docx")
    t0 = time.perf_counter()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", OracleDegradedWarning)
            res = convert_result(path, out, options=opts, max_pages=0)
    except ExactdocError as e:
        return {"refused": type(e).__name__}
    dt = time.perf_counter() - t0
    with zipfile.ZipFile(out) as z:
        parts = {n: hashlib.sha256(z.read(n)).hexdigest()
                 for n in sorted(z.namelist()) if n.startswith("word/") and n.endswith(".xml")}
    os.remove(out)
    rounds = res.refine.get("rounds", [])
    return {"convert_s": round(dt, 2), "parts": parts,
            "rounds": [{k: r[k] for k in ("round", "out_pages", "write_ms", "render_ms",
                                          "measure_ms") if k in r} for r in rounds],
            "stopped": res.refine.get("stopped")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", choices=("product", "raw", "gdocs"), default="product")
    ap.add_argument("--docs", nargs="+", default=None, help="document names")
    ap.add_argument("--from-sweep", help="take documents from this sweep ...")
    ap.add_argument("--over-s", type=float, default=40.0,
                    help="... whose convert_s there exceeds this (default 40)")
    ap.add_argument("--json", help="write the payload here (<name>.timing.json)")
    a = ap.parse_args(argv)

    paths = _paths_by_doc()
    docs = list(a.docs or [])
    if a.from_sweep:
        with open(a.from_sweep, encoding="utf-8") as fh:
            sweep = json.load(fh)
        docs += [r["document"] for r in sorted(sweep["documents"],
                                               key=lambda r: -(r.get("convert_s") or 0))
                 if (r.get("convert_s") or 0) > a.over_s and r["document"] not in docs]
    if not docs:
        print("no documents selected")
        return 1
    opts = _profile(a.profile)
    print("SERIAL TIMING -- one conversion at a time, profile %s" % opts.profile_id())
    rows = []
    t0 = time.time()
    for doc in docs:
        path, pages = paths[doc]
        r = {"document": doc, "src_pages": pages}
        r.update(time_one(path, opts))
        rows.append(r)
        print("  %-34s %4sp  %s" % (doc, pages, r.get("convert_s", r.get("refused"))), flush=True)
        if a.json:
            _write(a.json, opts, rows, t0)
    return 0


def _write(path, opts, rows, t0):
    payload = {"schema": SCHEMA, "gating": False, "profile": opts.profile_id(),
               "jobs": 1, "elapsed_s": round(time.time() - t0, 1),
               "machine": {"cpus": os.cpu_count(), "platform": sys.platform},
               "documents": rows}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


if __name__ == "__main__":
    sys.exit(main())
