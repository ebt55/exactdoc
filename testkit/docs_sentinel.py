"""The Google Docs drift sentinel: one frozen DOCX flown first in every live run.

    python testkit/docs_sentinel.py fly OUT [--record]   # round-trip it once (Google creds)
    python testkit/docs_sentinel.py check ROWS.jsonl     # compare a run's sentinel row
    python testkit/docs_sentinel.py make [--force]       # (re)build the fixture -- never casually

Google Docs is not versioned: its import and PDF export change under us, and a
live run measured on a day Google changed something reads as our regression or
our win. So every live run (scripts/dev/gdsweep.py, scripts/dev/flypairs.py)
first flies the SAME bytes -- testkit/fixtures_sentinel/sentinel.gdocs.docx,
converted once from sentinel.pdf and frozen by SHA-256 -- and compares the
export's pages, word_recall, within2pt and dy_p50 with the row recorded the
first time (`expected` in sentinel.json), each inside a tight tolerance. A
difference is DRIFT: printed loudly, recorded in the run's rows (the sentinel
row carries `drift`), and the run continues -- its numbers are then read with
that in mind, not thrown away.

The expected row is recorded by flying it once with `fly --record` (the
coordinator, who holds the Google credentials). Until then a run reports
"sentinel: no expected row recorded" and compares nothing.
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
DIR = os.path.join(HERE, "fixtures_sentinel")
SPEC = os.path.join(DIR, "sentinel.json")
SOURCE = os.path.join(DIR, "sentinel.pdf")
DOCX = os.path.join(DIR, "sentinel.gdocs.docx")
DOC = "_sentinel.pdf"          # the row's "doc": never a corpus document's name
KEYS = ("src_pages", "out_pages", "word_recall", "within2pt", "dy_p50",
        "doc_recall", "mean_ssim")
# What counts as drift: pages exactly; the rest inside these (absolute). Tight
# on purpose: a frozen DOCX through an unchanged service reproduces its export
# to the byte, so any movement here is Google's.
TOLERANCE = {"out_pages": 0, "word_recall": 0.005, "within2pt": 0.02, "dy_p50": 0.5}


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load(path=None):
    with open(path or SPEC, encoding="utf-8") as fh:
        return json.load(fh)


def verify(spec=None):
    """[] when the fixture is the frozen one, else why not."""
    spec = spec or load()
    bad = []
    for key, path in (("source", SOURCE), ("docx", DOCX)):
        want = (spec.get(key) or {}).get("sha256")
        got = sha256(path) if os.path.exists(path) else None
        if got != want:
            bad.append("%s %s is %s, recorded %s" % (key, os.path.basename(path),
                                                      (got or "missing")[:12],
                                                      (want or "none")[:12]))
    return bad


def compare(row, spec=None):
    """(status, [drift]): status "ok", "DRIFT", "unrecorded" or "error"."""
    spec = spec or load()
    if "error" in row:
        return "error", ["the sentinel did not fly: %s" % row["error"]]
    expected = spec.get("expected")
    if not expected:
        return "unrecorded", []
    tol = dict(TOLERANCE, **(spec.get("tolerance") or {}))
    drift = []
    for key, limit in sorted(tol.items()):
        a, b = expected.get(key), row.get(key)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            if a != b:
                drift.append("%s %s -> %s" % (key, a, b))
            continue
        if abs(b - a) > limit + 1e-9:
            drift.append("%s %s -> %s (tolerance %s)" % (key, a, b, limit))
    return ("DRIFT" if drift else "ok"), drift


def announce(row, spec=None, say=print):
    """Compare, print loudly on drift, and put the verdict into `row`."""
    status, drift = compare(row, spec)
    row["sentinel"] = status
    row["drift"] = drift
    if status == "DRIFT":
        say("!" * 78)
        say("DRIFT: Google Docs no longer renders the frozen sentinel as recorded: %s"
            % "; ".join(drift))
        say("DRIFT: this run continues; read its numbers with Google's change in mind")
        say("!" * 78)
    elif status == "unrecorded":
        say("sentinel: no expected row recorded (python testkit/docs_sentinel.py fly OUT "
            "--record)")
    elif status == "error":
        say("sentinel: %s" % drift[0])
    else:
        say("sentinel: ok, Google Docs renders the frozen sentinel as recorded")
    return status


def fly(svc, out):
    """Round-trip the frozen sentinel through Google Docs once -> its row."""
    import gdocs_oracle as go
    import harness
    os.makedirs(out, exist_ok=True)
    pdf = os.path.join(out, "_sentinel.gdocs.pdf")
    row = {"doc": DOC, "sentinel_docx_sha256": sha256(DOCX), "utc": utc_now()}
    try:
        go.roundtrip(svc, DOCX, pdf)
        res = harness.evaluate(SOURCE, DOCX, out, save_images=False, rendered_pdf=pdf)
        row.update({k: res.get(k) for k in KEYS})
        row["scorer"] = harness.HARNESS_READING
    except Exception as exc:                                 # noqa: BLE001
        row["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    return row


def first(svc, out, say=print):
    """What a live run does before its documents: fly, compare, announce."""
    bad = verify()
    row = fly(svc, out) if not bad else {"doc": DOC, "utc": utc_now(),
                                         "error": "fixture changed: " + "; ".join(bad)}
    announce(row, say=say)
    return row


def record(row, path=None):
    path = path or SPEC
    spec = load(path)
    if "error" in row:
        raise SystemExit("refusing to record a sentinel row that did not fly: %s"
                         % row["error"])
    spec["expected"] = {k: row.get(k) for k in KEYS}
    spec["recorded"] = {"utc": row.get("utc"), "scorer": row.get("scorer")}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(spec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return spec


def make(force=False):
    """Build sentinel.pdf (a one-page memo: heading, paragraphs, a list and a
    small ruled table, base-14 fonts) and its gdocs-candidate DOCX, and pin
    both. Frozen once committed: rebuilding it starts a new baseline."""
    if os.path.exists(SPEC) and not force:
        raise SystemExit("%s exists; --force starts a new sentinel baseline" % SPEC)
    import fitz
    os.makedirs(DIR, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    y = 90
    page.insert_text((72, y), "Drift sentinel", fontname="hebo", fontsize=20)
    y += 34
    body = ("This one-page memo is converted once and frozen. Every live Google Docs "
            "run uploads the same bytes first and compares the export with the row "
            "recorded the first time, so a change on Google's side is seen as one.")
    for para in (body, "A second paragraph gives the export a line pitch to keep: "
                       "pages, word recall, words within two points and the median "
                       "vertical drift are compared."):
        rect = fitz.Rect(72, y, 540, y + 80)
        page.insert_textbox(rect, para, fontname="helv", fontsize=11)
        y += 70
    for i, item in enumerate(("Pages must match exactly.",
                              "Recall and placement must stay inside a tight tolerance.",
                              "Drift is printed, recorded and the run continues."), 1):
        page.insert_text((90, y), "%d.  %s" % (i, item), fontname="helv", fontsize=11)
        y += 18
    y += 14
    cells = (("Metric", "Tolerance"), ("pages", "exact"), ("word recall", "0.005"),
             ("within 2pt", "0.02"), ("dy p50", "0.5pt"))
    for r, (a, b) in enumerate(cells):
        top = y + 20 * r
        page.draw_rect(fitz.Rect(72, top, 300, top + 20), color=(0, 0, 0), width=0.5)
        page.draw_rect(fitz.Rect(300, top, 420, top + 20), color=(0, 0, 0), width=0.5)
        font = "hebo" if r == 0 else "helv"
        page.insert_text((78, top + 14), a, fontname=font, fontsize=10)
        page.insert_text((306, top + 14), b, fontname=font, fontsize=10)
    doc.set_metadata({"title": "exactdoc drift sentinel", "creator": "docs_sentinel.py",
                      "producer": "PyMuPDF"})
    doc.save(SOURCE, garbage=4, deflate=True, no_new_id=True)
    doc.close()
    sys.path.insert(0, os.path.dirname(HERE))
    from exactdoc import options as O
    from exactdoc.convert import convert
    convert(SOURCE, DOCX, options=O.PDFIUM_GDOCS_CANDIDATE)
    spec = {"schema": "exactdoc.docs-sentinel.v1",
            "source": {"file": os.path.basename(SOURCE), "sha256": sha256(SOURCE)},
            "docx": {"file": os.path.basename(DOCX), "sha256": sha256(DOCX),
                     "profile": O.PDFIUM_GDOCS_CANDIDATE.profile_id()},
            "tolerance": dict(TOLERANCE), "expected": None, "recorded": None}
    with open(SPEC, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(spec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return spec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fly", help="round-trip the sentinel once and compare")
    f.add_argument("out")
    f.add_argument("--record", action="store_true",
                   help="record this flight as the expected row")
    c = sub.add_parser("check", help="compare the sentinel row of a run's rows")
    c.add_argument("rows")
    m = sub.add_parser("make", help="(re)build the frozen fixture")
    m.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "make":
        spec = make(force=a.force)
        print(json.dumps(spec, indent=1))
        return 0
    if a.cmd == "check":
        with open(a.rows, encoding="utf-8") as fh:
            text = fh.read()
        rows = json.loads(text) if text.lstrip().startswith("[") else \
            [json.loads(l) for l in text.splitlines() if l.strip()]
        found = [r for r in rows if r.get("doc") == DOC]
        if not found:
            print("no sentinel row in %s" % a.rows)
            return 2
        return 0 if announce(dict(found[-1])) in ("ok", "unrecorded") else 1
    import gdocs_oracle as go
    row = first(go._service(interactive=False), a.out)
    print(json.dumps(row, indent=1))
    if a.record:
        record(row)
        print("recorded the expected sentinel row in %s" % SPEC)
    return 0 if row.get("sentinel") in ("ok", "unrecorded") else 1


if __name__ == "__main__":
    sys.exit(main())
