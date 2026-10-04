"""Is exactdoc ready for its first public beta? The bar, against the latest numbers.

    python testkit/beta_readiness.py --runs <dir> [--runs <dir> ...]
    python testkit/beta_readiness.py --raw R.sweep.json --product P.sweep.json \\
        --gdocs rows.jsonl --gate <dir holding lane_raw/ and lane_product/>
    python testkit/beta_readiness.py ... --json readiness.json

A READING of measurements, never a measurement and never a gate: it converts
nothing, renders nothing, uploads nothing, and the CI gate does not call it. It
reads what the measuring tools already wrote --

    quality sweeps   testkit/quality_sweep.py --json (schema
                     exactdoc.quality-sweep.v1); the profile is read from the
                     file, so `--runs` finds the newest raw and product sweeps
                     that cover the whole corpus (`--corpus both`)
    Google Docs live rows.jsonl from the live sweep, one JSON object per
                     document ({"doc", "src_pages", "out_pages", "page_match",
                     "char_recall", ... or "error"})
    gate verdicts    lane_raw/verdict.json and lane_product/verdict.json from
                     testkit/runall.py (testkit/batch/, or a copied <run>.batch/)

-- and prints PASS / FAIL / UNKNOWN per criterion, naming each input file, its
age and the documents that miss. A criterion whose input is missing is UNKNOWN,
never PASS. Exit 0 only when every criterion passes.

**The bar below is a proposal the owner has not ratified.** It lives in `BAR`
so that changing a threshold is a one-line, reviewable edit. Tiers come from the
corpus manifests (`tier`), not from this file.
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)

# ----------------------------------------------------------------- the bar
BAR = {
    # Zero conversions that crash, across every corpus document any input
    # covers. Typed refusals (form, scan, over the page cap) are not crashes; a
    # harness or upload failure is reported but is not the converter's.
    "max_crashes": 0,
    # No conversion slower than this for a document shorter than
    # `slow_pages_below`, in each listed sweep profile. "product" is what a bare
    # `exactdoc file.pdf` runs when LibreOffice is installed; "raw" is what it
    # runs without (and what --refine 0 runs).
    "max_convert_s": 60.0,
    "slow_pages_below": 100,
    "speed_profiles": ("raw", "product"),
    # The ordinary-document tier: page-exact share in LibreOffice (the raw
    # sweep) and in Google Docs live.
    "tier": "ordinary_digital",
    "min_page_exact_share": 0.80,
    # ... and the share of those documents whose characters survive onto the
    # right page (quality_sweep's char_recall, segmentation-free).
    "char_recall_at_least": 0.95,
    "min_char_recall_share": 0.90,
    # The 16 gated documents pass both gate lanes.
    "gate_lanes": ("raw", "product"),
    "gate_documents": 16,
    # Word itself has never measured a DOCX here. Until a Word sweep exists this
    # criterion is UNKNOWN by construction; give --word a results file to grade.
    "require_word": True,
}

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
_REFUSALS = ("InteractiveFormError", "PageLimitError", "OcrRequiredError",
             "UnsupportedInputError")


# ------------------------------------------------------------- the corpus
def corpus():
    """{doc: tier} for every manifest document, gated and expansion."""
    tiers = {}
    for name in ("corpus_manifest.json", "corpus_expansion.json"):
        path = os.path.join(HERE, name)
        try:
            with open(path, encoding="utf-8") as fh:
                docs = json.load(fh).get("documents", {})
        except (OSError, ValueError):
            continue
        for doc, spec in docs.items():
            tiers[doc] = spec.get("tier", "ordinary_digital")
    return tiers


# ------------------------------------------------------------- the inputs
def _when(path):
    return datetime.datetime.fromtimestamp(os.path.getmtime(path))


def _profile_kind(profile):
    """'pdfium/standard/none/refine0@240dpi' -> 'raw', etc. None if unknown."""
    parts = (profile or "").split("/")
    if len(parts) < 4:
        return None
    _, out_profile, oracle, rest = parts[:4]
    refine0 = rest.startswith("refine0")
    if out_profile == "standard" and oracle == "none" and refine0:
        return "raw"
    if out_profile == "standard" and oracle == "libreoffice" and not refine0:
        return "product"
    if out_profile == "gdocs" and oracle == "none" and refine0:
        return "gdocs-lo"
    return None


def load_sweep(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("schema") != "exactdoc.quality-sweep.v1":
        raise ValueError("%s is not a quality sweep" % path)
    return data


def find_sweeps(dirs, tiers):
    """{kind: (path, data)}: the newest sweep per profile covering the corpus.

    "Covering" is at least 90% of the manifest documents a default sweep runs
    (every tier but `unsupported`); a targeted `--only` sweep is not a reading
    of the product.
    """
    want = sum(1 for t in tiers.values() if t != "unsupported")
    best = {}
    for d in dirs:
        for path in glob.glob(os.path.join(d, "*.sweep.json")):
            try:
                data = load_sweep(path)
            except (OSError, ValueError):
                continue
            kind = _profile_kind(data.get("profile"))
            if kind is None or len(data.get("documents", ())) < 0.9 * want:
                continue
            if kind not in best or os.path.getmtime(path) > os.path.getmtime(best[kind][0]):
                best[kind] = (path, data)
    return best


def load_rows(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def find_gdocs_rows(dirs, tiers):
    """(path, rows) for the newest rows.jsonl covering half the corpus, or None."""
    best = None
    want = sum(1 for t in tiers.values() if t != "unsupported")
    for d in dirs:
        for root, subdirs, files in os.walk(d):
            subdirs[:] = [s for s in subdirs if not s.startswith(_NO_DESCEND)]
            if "rows.jsonl" not in files:
                continue
            path = os.path.join(root, "rows.jsonl")
            try:
                rows = load_rows(path)
            except (OSError, ValueError):
                continue
            n = sum(1 for r in rows if r.get("doc") in tiers)
            if n < 0.5 * want:
                continue
            if best is None or os.path.getmtime(path) > os.path.getmtime(best[0]):
                best = (path, rows)
    return best


def load_gate(path):
    """{lane: verdict dict} from a directory holding lane_<lane>/verdict.json."""
    out = {}
    for lane in BAR["gate_lanes"]:
        p = os.path.join(path, "lane_%s" % lane, "verdict.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                out[lane] = json.load(fh)
    return out


def find_gate(dirs):
    """(dir, verdicts) for the newest directory holding every lane's verdict."""
    best = None
    for d in dirs:
        for root, subdirs, _files in os.walk(d):
            matched = all("lane_%s" % lane in subdirs for lane in BAR["gate_lanes"])
            # never descend into per-document output (renders, comparisons)
            subdirs[:] = [s for s in subdirs if not s.startswith(_NO_DESCEND)]
            if not matched:
                continue
            verdicts = load_gate(root)
            if len(verdicts) != len(BAR["gate_lanes"]):
                continue
            newest = max(os.path.getmtime(os.path.join(root, "lane_%s" % lane,
                                                       "verdict.json"))
                         for lane in BAR["gate_lanes"])
            if best is None or newest > best[2]:
                best = (root, verdicts, newest)
    return (best[0], best[1]) if best else None


_NO_DESCEND = ("lane_", "cmp_", "rendered", "_tmp", "qs_")


# ------------------------------------------------------------- the reading
def _is_ok_row(r):
    return "page_ratio" in r or ("src_pages" in r and "out_pages" in r and
                                 "error" not in r)


def classify_failures(rows, key="document"):
    """-> (crashes, refusals, infra) lists of (doc, message)."""
    crashes, refusals, infra = [], [], []
    for r in rows:
        doc = r.get(key) or r.get("doc") or r.get("document")
        if "refused" in r:
            refusals.append((doc, r["refused"]))
            continue
        err = r.get("error")
        if not err:
            continue
        if err.startswith(_REFUSALS):
            refusals.append((doc, err.split(":", 1)[0]))
        elif err.startswith(("evaluate ", "RoundtripError", "worker: ")):
            infra.append((doc, err[:80]))
        else:
            crashes.append((doc, err[:120]))
    return crashes, refusals, infra


def _share(n, d):
    return (n / d) if d else None


def _fmt_share(n, d):
    return "%d/%d = %.1f%%" % (n, d, 100.0 * n / d) if d else "0 documents"


def evaluate(tiers, sweeps, gdocs, gate, word=None, now=None):
    """-> {"inputs": [...], "criteria": [...], "verdict": str}."""
    now = now or datetime.datetime.now()
    inputs, criteria = [], []

    def note_input(label, path, extra):
        if path is None:
            inputs.append({"input": label, "path": None, "detail": "not found"})
            return
        age = now - _when(path)
        inputs.append({"input": label, "path": path,
                       "modified": _when(path).strftime("%Y-%m-%d %H:%M"),
                       "age_h": round(age.total_seconds() / 3600.0, 1),
                       "detail": extra})

    for kind in ("raw", "product", "gdocs-lo"):
        if kind in sweeps:
            path, data = sweeps[kind]
            note_input("%s sweep" % kind, path, "%s, %d documents" % (
                data.get("profile"), len(data.get("documents", ()))))
        elif kind in ("raw", "product"):
            note_input("%s sweep" % kind, None, None)
    if gdocs:
        path, rows = gdocs
        n = sum(1 for r in rows if r.get("doc") in tiers)
        note_input("gdocs live", path, "%d rows, %d corpus documents" % (len(rows), n))
    else:
        note_input("gdocs live", None, None)
    if gate:
        path, verdicts = gate
        lane_files = [os.path.join(path, "lane_%s" % l, "verdict.json")
                      for l in verdicts]
        note_input("gate verdicts", max(lane_files, key=os.path.getmtime),
                   ", ".join("%s %s" % (l, "ok" if v.get("ok") else "FAILED")
                             for l, v in sorted(verdicts.items())))
    else:
        note_input("gate verdicts", None, None)

    def crit(name, status, detail, misses=None):
        criteria.append({"criterion": name, "status": status, "detail": detail,
                         "misses": misses or []})

    # 1. crashes
    all_crashes, all_infra, ran = [], [], set()
    for kind, (path, data) in sweeps.items():
        c, _r, i = classify_failures(data.get("documents", ()))
        all_crashes += [("%s: %s" % (kind, d), m) for d, m in c]
        all_infra += [("%s: %s" % (kind, d), m) for d, m in i]
        ran.update(r.get("document") for r in data.get("documents", ()))
    if gdocs:
        corpus_rows = [r for r in gdocs[1] if r.get("doc") in tiers]
        c, _r, i = classify_failures(corpus_rows, key="doc")
        all_crashes += [("gdocs live: %s" % d, m) for d, m in c]
        all_infra += [("gdocs live: %s" % d, m) for d, m in i]
        ran.update(r.get("doc") for r in corpus_rows)
    not_run = sorted(d for d in tiers if d not in ran)
    if not sweeps and not gdocs:
        crit("no crashes", UNKNOWN, "no sweep found")
    else:
        detail = "%d crash(es)" % len(all_crashes)
        if all_infra:
            detail += "; %d measurement/upload failure(s) not counted" % len(all_infra)
        if not_run:
            detail += "; %d corpus document(s) in no input (%s)" % (
                len(not_run), ", ".join(d.split("_")[0] for d in not_run))
        crit("no crashes", PASS if len(all_crashes) <= BAR["max_crashes"] else FAIL,
             detail, ["%s -- %s" % cm for cm in all_crashes] +
             ["(not counted) %s -- %s" % im for im in all_infra])

    # 2. speed
    for kind in BAR["speed_profiles"]:
        name = "no conversion over %gs under %d pages (%s)" % (
            BAR["max_convert_s"], BAR["slow_pages_below"], kind)
        if kind not in sweeps:
            crit(name, UNKNOWN, "no full %s sweep found" % kind)
            continue
        rows = [r for r in sweeps[kind][1].get("documents", ())
                if "convert_s" in r and (r.get("src_pages") or 0) < BAR["slow_pages_below"]]
        slow = sorted((r for r in rows if r["convert_s"] > BAR["max_convert_s"]),
                      key=lambda r: -r["convert_s"])
        slowest = max(sweeps[kind][1].get("documents", ()),
                      key=lambda r: r.get("convert_s") or 0, default=None)
        detail = "%d of %d over" % (len(slow), len(rows))
        if slowest is not None and slowest.get("convert_s"):
            detail += "; slowest overall %s %.0fs (%s pages)" % (
                slowest["document"], slowest["convert_s"], slowest.get("src_pages"))
        crit(name, PASS if not slow else FAIL, detail,
             ["%s %.0fs, %s pages" % (r["document"], r["convert_s"], r["src_pages"])
              for r in slow])

    # 3-4. ordinary tier: page-exact and char recall, LibreOffice raw + Docs live
    tier = BAR["tier"]
    readings = []
    if "raw" in sweeps:
        rows = [r for r in sweeps["raw"][1].get("documents", ())
                if tiers.get(r.get("document"), r.get("tier")) == tier and _is_ok_row(r)]
        readings.append(("LibreOffice raw", rows, "document"))
    else:
        readings.append(("LibreOffice raw", None, "document"))
    if gdocs:
        rows = [r for r in gdocs[1]
                if tiers.get(r.get("doc")) == tier and _is_ok_row(r)]
        readings.append(("Google Docs live", rows, "doc"))
    else:
        readings.append(("Google Docs live", None, "doc"))
    for label, rows, key in readings:
        name = "%s page-exact >= %d%% (%s)" % (
            tier, round(100 * BAR["min_page_exact_share"]), label)
        if rows is None:
            crit(name, UNKNOWN, "no input")
        else:
            miss = [r for r in rows if r.get("src_pages") != r.get("out_pages")]
            n = len(rows) - len(miss)
            share = _share(n, len(rows))
            crit(name, PASS if share is not None and share >= BAR["min_page_exact_share"]
                 else FAIL, _fmt_share(n, len(rows)),
                 ["%s %s->%s" % (r[key], r.get("src_pages"), r.get("out_pages"))
                  for r in sorted(miss, key=lambda r: r[key])])
        name = "%s char_recall >= %.2f on >= %d%% (%s)" % (
            tier, BAR["char_recall_at_least"],
            round(100 * BAR["min_char_recall_share"]), label)
        if rows is None:
            crit(name, UNKNOWN, "no input")
            continue
        scored = [r for r in rows if r.get("char_recall") is not None]
        miss = [r for r in scored if r["char_recall"] < BAR["char_recall_at_least"]]
        n = len(scored) - len(miss)
        share = _share(n, len(scored))
        crit(name, PASS if share is not None and share >= BAR["min_char_recall_share"]
             else FAIL, _fmt_share(n, len(scored)),
             ["%s %.3f" % (r[key], r["char_recall"])
              for r in sorted(miss, key=lambda r: r["char_recall"])])

    # 5. the gate
    name = "the gated %d pass both gate lanes" % BAR["gate_documents"]
    if not gate:
        crit(name, UNKNOWN, "no lane verdicts found")
    else:
        _path, verdicts = gate
        bad = []
        for lane in BAR["gate_lanes"]:
            v = verdicts.get(lane)
            if v is None:
                bad.append("%s: no verdict" % lane)
                continue
            if not v.get("ok"):
                bad.append("%s: %s" % (lane, "; ".join(map(str, v.get("failures", [])))[:200]))
            measured = re.search(r"(\d+) document\(s\) measured, (\d+) expected",
                                 " ".join(map(str, v.get("notes", []))))
            if measured and int(measured.group(1)) != BAR["gate_documents"]:
                bad.append("%s: %s documents measured" % (lane, measured.group(1)))
        crit(name, PASS if not bad else FAIL,
             "both lanes ok" if not bad else "%d problem(s)" % len(bad), bad)

    # 6. Word
    name = "Word measured"
    if not BAR["require_word"]:
        crit(name, PASS, "not required by BAR")
    elif word is None:
        crit(name, UNKNOWN, "placeholder: no Word results yet (Word is not "
                            "installed on the measuring machine)")
    else:
        crit(name, PASS, "results file: %s" % word)

    statuses = [c["status"] for c in criteria]
    if FAIL in statuses:
        verdict = "NOT READY"
    elif UNKNOWN in statuses:
        verdict = "INCOMPLETE"
    else:
        verdict = "READY"
    return {"bar": dict(BAR, speed_profiles=list(BAR["speed_profiles"]),
                        gate_lanes=list(BAR["gate_lanes"])),
            "ratified": False, "evaluated": now.strftime("%Y-%m-%d %H:%M"),
            "inputs": inputs, "criteria": criteria, "verdict": verdict}


def render(result, show_misses=8):
    lines = ["exactdoc beta readiness -- PROPOSED bar, not ratified (%s)"
             % result["evaluated"], "", "inputs"]
    for i in result["inputs"]:
        if i["path"] is None:
            lines.append("  %-14s not found" % i["input"])
        else:
            lines.append("  %-14s %s" % (i["input"], i["path"]))
            lines.append("  %-14s %s; modified %s (%.1fh ago)" % (
                "", i["detail"], i["modified"], i["age_h"]))
    lines += ["", "criteria"]
    for c in result["criteria"]:
        lines.append("  %-7s %s" % (c["status"], c["criterion"]))
        lines.append("  %-7s   %s" % ("", c["detail"]))
        for m in c["misses"][:show_misses]:
            lines.append("  %-7s     - %s" % ("", m))
        if len(c["misses"]) > show_misses:
            lines.append("  %-7s     ... and %d more" % ("", len(c["misses"]) - show_misses))
    counts = {s: sum(1 for c in result["criteria"] if c["status"] == s)
              for s in (PASS, FAIL, UNKNOWN)}
    lines += ["", "verdict: %s  (%d pass, %d fail, %d unknown)" % (
        result["verdict"], counts[PASS], counts[FAIL], counts[UNKNOWN])]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", action="append", default=[],
                    help="directory to search for sweeps, rows.jsonl and gate "
                         "verdicts (repeatable; also EXACTDOC_RUNS, "
                         "os.pathsep-separated; default testkit/sweep and "
                         "testkit/batch)")
    ap.add_argument("--raw", help="a raw-profile quality sweep JSON")
    ap.add_argument("--product", help="a product-profile quality sweep JSON")
    ap.add_argument("--gdocs", help="a Google Docs live rows.jsonl")
    ap.add_argument("--gate", help="a directory holding lane_raw/ and lane_product/")
    ap.add_argument("--word", help="a Word results file (placeholder)")
    ap.add_argument("--json", help="also write the evaluation here")
    ap.add_argument("--all-misses", action="store_true",
                    help="list every missing document, not the first 8")
    a = ap.parse_args(argv)

    dirs = list(a.runs)
    dirs += [d for d in os.environ.get("EXACTDOC_RUNS", "").split(os.pathsep) if d]
    if not dirs:
        dirs = [os.path.join(HERE, "sweep"), os.path.join(HERE, "batch")]
    dirs = [d for d in dirs if os.path.isdir(d)]

    tiers = corpus()
    sweeps = find_sweeps(dirs, tiers)
    for kind, path in (("raw", a.raw), ("product", a.product)):
        if path:
            sweeps[kind] = (path, load_sweep(path))
    gdocs = (a.gdocs, load_rows(a.gdocs)) if a.gdocs else find_gdocs_rows(dirs, tiers)
    gate = (a.gate, load_gate(a.gate)) if a.gate else find_gate(dirs)
    result = evaluate(tiers, sweeps, gdocs, gate, word=a.word)
    print(render(result, show_misses=10 ** 6 if a.all_misses else 8))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
    return 0 if result["verdict"] == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
