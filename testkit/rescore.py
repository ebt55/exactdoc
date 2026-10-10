"""Re-score saved renders with the current reading, converting nothing.

    python testkit/rescore.py sweep IN.sweep.json RENDERS OUT.sweep.json
    python testkit/rescore.py rows  IN.jsonl RENDERS OUT.jsonl --pattern "{stem}.gdocs.pdf"
    python testkit/rescore.py gate  BATCH_DIR [--json OUT.json]

A measurement, never a gate and never a re-record. The harness's reading of a
PDF changed (WP29, 2026-10-06: leader runs, symbol-font PUA, brackets and
operators -- see `harness.page_words`); a render made before that change is
still a valid render, so its numbers can be re-read without converting or
rendering anything. Only the metrics that depend on the reading are replaced:
`harness.WORD_METRICS` and the character recalls. Page counts, SSIM, live text
and editability are copied as they were.

Each re-scored row also carries `before` ({metric: old value}) and `control`
-- the old reading recomputed here -- so a difference between machines or
PyMuPDF builds is visible as a control mismatch instead of being credited to
the new reading.

    sweep   a quality sweep; RENDERS is the KEEP_DOCX folder sweep.sh wrote
            (<RENDERS>/<stem>/<stem>.pdf beside each kept DOCX).
    rows    Docs-live or Word-lane JSONL; RENDERS holds one render per
            document named by --pattern ("{stem}.gdocs.pdf", "{stem}.word.pdf").
    gate    a runall batch folder (lane_<x>/results.json + rendered/): each
            lane re-scored and handed to gate.check against the COMMITTED
            baseline, exactly as runall would -- reported, nothing written to
            the baseline.
"""
import _paths  # noqa: F401
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import corpus_manifest
import harness
import quality_sweep as qs

READ = harness.WORD_METRICS + ("char_recall", "char_doc_recall")


def source_of(doc):
    """The frozen fixture for a document name ('y26_bash_reference.pdf')."""
    doc = os.path.basename(doc)
    if not doc.endswith(".pdf"):
        doc += ".pdf"
    gated = corpus_manifest.load()["documents"]
    if doc in gated:
        return corpus_manifest.fixture_path(doc, corpus_manifest.load())
    return corpus_manifest.expansion_fixture_path(doc)


def reread(src, pdf, normalise):
    out = harness.word_metrics(src, pdf, normalise=normalise)
    out["char_recall"], out["char_doc_recall"] = qs.char_recall(src, pdf, normalise=normalise)
    return out


def rescore_row(row, src, pdf):
    """`row` with every reading-dependent metric it carries re-read from `pdf`."""
    new = dict(row)
    after, control = reread(src, pdf, True), reread(src, pdf, False)
    keys = [k for k in READ if k in row]
    new["before"] = {k: row[k] for k in keys}
    new["control"] = {k: control.get(k) for k in keys}
    for k in keys:
        if k in after:
            new[k] = after[k]
        else:
            new.pop(k, None)              # e.g. no drift once nothing matches
    if "worst_pages_dy90" in row:
        new["worst_pages_dy90"] = sorted((after.get("page_dy_p90") or {}).items(),
                                         key=lambda kv: -kv[1])[:5]
    new["scorer"] = harness.HARNESS_READING
    return new


def _job(args):
    row, src, pdf = args
    try:
        return rescore_row(row, src, pdf)
    except Exception as e:                # a broken render is reported, not fatal
        return dict(row, rescore_error="%s: %s" % (type(e).__name__, e))


def _rescore_all(items, jobs):
    """items: [(row, src, pdf or None)] -> rows in the same order."""
    todo = [(i, (r, s, p)) for i, (r, s, p) in enumerate(items) if p]
    out = [r for r, _, _ in items]
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for (i, _), res in zip(todo, ex.map(_job, [t for _, t in todo])):
            out[i] = res
    return out


def _measured(row):
    return ("error" not in row and "refused" not in row
            and isinstance(row.get("out_pages"), int))


def rescore_sweep(path, renders, out_path, jobs=4):
    data = json.load(open(path, encoding="utf-8"))
    items = []
    for r in data["documents"]:
        stem = os.path.splitext(r["document"])[0]
        pdf = os.path.join(renders, stem, stem + ".pdf")
        items.append((r, source_of(r["document"]),
                      pdf if _measured(r) and os.path.exists(pdf) else None))
    data["documents"] = _rescore_all(items, jobs)
    data["summary"] = qs.summarise(data["documents"])
    data["rescored"] = {"from": os.path.abspath(path), "renders": os.path.abspath(renders),
                        "scorer": harness.HARNESS_READING}
    data["reading"] = harness.reading()          # replaces the reading it was swept in
    _write_json(out_path, data)
    return data


def rescore_rows(path, renders, out_path, pattern, jobs=4):
    rows = []
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    items = []
    for r in rows:
        doc = r.get("doc") or r.get("document")
        stem = os.path.splitext(os.path.basename(doc))[0]
        pdf = os.path.join(renders, pattern.format(stem=stem))
        items.append((r, source_of(doc),
                      pdf if _measured(r) and os.path.exists(pdf) else None))
    rows = _rescore_all(items, jobs)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return rows


def rescore_gate(batch, jobs=4):
    """{lane: {"results": [...], "verdict": {...}}} under the current reading,
    judged by gate.check against the committed baseline."""
    import gate
    manifest = gate.load_manifest()
    out = {}
    for lane in ("raw", "product"):
        d = os.path.join(batch, "lane_" + lane)
        results = json.load(open(os.path.join(d, "results.json"), encoding="utf-8"))
        items = []
        for r in results:
            stem = os.path.splitext(r.get("src", ""))[0]
            pdf = os.path.join(d, "rendered", stem + ".pdf")
            ok = not any(k in r for k in gate.FATAL_KEYS) and os.path.exists(pdf)
            items.append((r, source_of(r["src"]) if r.get("src") else None,
                          pdf if ok else None))
        new = _rescore_all(items, jobs)
        clean = [{k: v for k, v in r.items() if k not in ("before", "control", "scorer")}
                 for r in new]
        verdict = gate.check(lane, clean, manifest=manifest, baseline=gate.load_lane(lane))
        out[lane] = {"results": new, "verdict": verdict.as_dict(),
                     "report": verdict.report()}
    return out


def _write_json(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sweep")
    s.add_argument("sweep"); s.add_argument("renders"); s.add_argument("out")
    r = sub.add_parser("rows")
    r.add_argument("rows"); r.add_argument("renders"); r.add_argument("out")
    r.add_argument("--pattern", required=True)
    g = sub.add_parser("gate")
    g.add_argument("batch"); g.add_argument("--json")
    for p in (s, r, g):
        p.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    if a.cmd == "sweep":
        data = rescore_sweep(a.sweep, a.renders, a.out, a.jobs)
        print(json.dumps(data["summary"], indent=1))
    elif a.cmd == "rows":
        rows = rescore_rows(a.rows, a.renders, a.out, a.pattern, a.jobs)
        print("%d rows, %d re-scored" % (len(rows), sum(1 for x in rows if "scorer" in x)))
    else:
        res = rescore_gate(a.batch, a.jobs)
        for lane, v in sorted(res.items()):
            print("== lane %s\n%s" % (lane, v["report"]))
        if a.json:
            _write_json(a.json, res)
        return 0 if all(v["verdict"]["ok"] for v in res.values()) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
