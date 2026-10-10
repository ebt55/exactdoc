"""Re-score saved renders with the current reading, converting nothing.

    python testkit/rescore.py sweep IN.sweep.json RENDERS OUT.sweep.json
    python testkit/rescore.py rows  IN.jsonl RENDERS OUT.jsonl --pattern "{stem}.gdocs.pdf"
                                    [--docx-pattern "{stem}.docx"]
    python testkit/rescore.py gate  BATCH_DIR [--json OUT.json]

A measurement, never a gate and never a re-record. The harness's reading of a
PDF changed (WP29, 2026-10-06: leader runs, symbol-font PUA, brackets and
operators; amendment 3, 2026-10-10: a word's vertical position is its baseline
and live text is read the same way -- see `harness.page_words` and
`harness.live_text_cov`); a render made before a change is still a valid
render, so its numbers can be re-read without converting or rendering
anything. Only the metrics that depend on the reading are replaced:
`harness.WORD_METRICS`, the character recalls, and `live_text_cov` /
`raster_frac` re-read from the kept DOCX (copied, and flagged
`live_text_copied`, when the DOCX is not there). Page counts, SSIM and
editability are copied as they were.

Each re-scored row also carries `before` ({metric: value as recorded}) and
`control` -- the reading in force before the newest amendment (WP29's, word
box tops and live text read raw), recomputed here from the same extraction --
so `after - control` is what the newest amendment alone moved, and a
difference between machines or PyMuPDF builds shows as `control` against a
row recorded under that reading instead of being credited to the new one.

    sweep   a quality sweep; RENDERS is the KEEP_DOCX folder sweep.sh wrote
            (<RENDERS>/<stem>/<stem>.pdf and .docx).
    rows    Docs-live or Word-lane JSONL; RENDERS holds one render per
            document named by --pattern ("{stem}.gdocs.pdf", "{stem}.word.pdf")
            and the DOCX by --docx-pattern ("{stem}.docx" beside a Docs
            export; "_docx/{stem}.word-in.docx" in a Word-lane folder).
    gate    a runall batch folder (lane_<x>/results.json, <stem>.docx and
            rendered/): each lane re-scored and handed to gate.check against
            the COMMITTED baseline, exactly as runall would, with the lane
            record GATE_BASELINE=update would write from it -- reported,
            nothing written to the baseline.
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
LIVE = ("live_text_cov", "raster_frac")
SCORER = "wp36"


def source_of(doc):
    """The frozen fixture for a document name ('y26_bash_reference.pdf')."""
    doc = os.path.basename(doc)
    if not doc.endswith(".pdf"):
        doc += ".pdf"
    gated = corpus_manifest.load()["documents"]
    if doc in gated:
        return corpus_manifest.fixture_path(doc, corpus_manifest.load())
    return corpus_manifest.expansion_fixture_path(doc)


def reread(src, pdf, docx=None):
    """(after, control): the current reading of one render and the reading
    before amendment 3, the word metrics of both from one extraction."""
    sw, ow = harness.page_words(src), harness.page_words(pdf)
    after = harness.drift_metrics(sw, ow)
    control = harness.drift_metrics(harness.box_top(sw), harness.box_top(ow))
    chars = qs.char_recall(src, pdf)           # amendment 3 does not touch it
    for d in (after, control):
        d["char_recall"], d["char_doc_recall"] = chars
    if docx:
        after["live_text_cov"] = harness.live_text_cov(src, docx)
        control["live_text_cov"] = harness.live_text_cov(src, docx, normalise=False)
        for d in (after, control):
            d["raster_frac"] = round(1 - d["live_text_cov"], 4)
    return after, control


def rescore_row(row, src, pdf, docx=None):
    """`row` with every reading-dependent metric it carries re-read from `pdf`
    (and its live text from `docx`, when there is one)."""
    new = dict(row)
    after, control = reread(src, pdf, docx)
    keys = [k for k in READ if k in row] + [k for k in LIVE if k in row and docx]
    new["before"] = {k: row[k] for k in keys}
    new["control"] = {k: control.get(k) for k in keys}
    for k in keys:
        if k in after:
            new[k] = after[k]
        else:
            new.pop(k, None)              # e.g. no drift once nothing matches
    if "live_text_cov" in row and not docx:
        new["live_text_copied"] = True    # no DOCX kept: the recorded value stands
    if "worst_pages_dy90" in row:
        new["worst_pages_dy90"] = sorted((after.get("page_dy_p90") or {}).items(),
                                         key=lambda kv: -kv[1])[:5]
    new["scorer"] = SCORER
    return new


def _job(args):
    row, src, pdf, docx = args
    try:
        return rescore_row(row, src, pdf, docx)
    except Exception as e:                # a broken render is reported, not fatal
        return dict(row, rescore_error="%s: %s" % (type(e).__name__, e))


def _rescore_all(items, jobs):
    """items: [(row, src, pdf or None, docx or None)] -> rows in the same order."""
    todo = [(i, t) for i, t in enumerate(items) if t[2]]
    out = [t[0] for t in items]
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for (i, _), res in zip(todo, ex.map(_job, [t for _, t in todo])):
            out[i] = res
    return out


def _exists(path):
    return path if path and os.path.exists(path) else None


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
                      _exists(pdf) if _measured(r) else None,
                      _exists(os.path.join(renders, stem, stem + ".docx"))))
    data["documents"] = _rescore_all(items, jobs)
    data["summary"] = qs.summarise(data["documents"])
    data["rescored"] = {"from": os.path.abspath(path), "renders": os.path.abspath(renders),
                        "scorer": SCORER}
    _write_json(out_path, data)
    return data


def rescore_rows(path, renders, out_path, pattern, jobs=4, docx_pattern="{stem}.docx"):
    rows = []
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    items = []
    for r in rows:
        doc = r.get("doc") or r.get("document")
        stem = os.path.splitext(os.path.basename(doc))[0]
        pdf = os.path.join(renders, pattern.format(stem=stem))
        items.append((r, source_of(doc), _exists(pdf) if _measured(r) else None,
                      _exists(os.path.join(renders, docx_pattern.format(stem=stem)))))
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
                          pdf if ok else None, _exists(os.path.join(d, stem + ".docx"))))
        new = _rescore_all(items, jobs)
        clean = [{k: v for k, v in r.items()
                  if k not in ("before", "control", "scorer", "live_text_copied")}
                 for r in new]
        verdict = gate.check(lane, clean, manifest=manifest, baseline=gate.load_lane(lane))
        out[lane] = {"results": new, "verdict": verdict.as_dict(),
                     "report": verdict.report(),
                     # what GATE_BASELINE=update would record from these renders
                     # (shown, never written)
                     "record": gate.record(lane, clean)}
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
    r.add_argument("--docx-pattern", default="{stem}.docx",
                   help="the kept DOCX under RENDERS, for live text")
    g = sub.add_parser("gate")
    g.add_argument("batch"); g.add_argument("--json")
    for p in (s, r, g):
        p.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    if a.cmd == "sweep":
        data = rescore_sweep(a.sweep, a.renders, a.out, a.jobs)
        print(json.dumps(data["summary"], indent=1))
    elif a.cmd == "rows":
        rows = rescore_rows(a.rows, a.renders, a.out, a.pattern, a.jobs, a.docx_pattern)
        print("%d rows, %d re-scored, %d live text copied" % (
            len(rows), sum(1 for x in rows if "scorer" in x),
            sum(1 for x in rows if x.get("live_text_copied"))))
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
