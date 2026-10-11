"""Does a change lift quality, leave it alone, or regress it? BASE against HEAD.

    python testkit/quality_check.py collect --side head --batch B [--sweep S.json] --out DIR
    python testkit/quality_check.py compare BASE_DIR HEAD_DIR [--json report.json]

The contributor's entry point is `scripts/dev/quality_check.sh`, which measures
two commits in ONE container and calls this file twice per commit (`collect`)
and once at the end (`compare`). This file converts nothing and renders nothing:
it reads what `runall.py` (the gate, both lanes, the gated 16) and
`quality_sweep.py` (the product profile on the expansion corpus) already wrote.

Nothing here is new policy. Better and worse are criterion 8 of the beta bar
(`beta_readiness.compare_rows`), which uses `gate.py`'s metrics and tolerances
and amendment 4's dy_p50 exemption; the gate's PASS/FAIL is `gate.check` as
`runall.py` recorded it. What this adds is the pairing:

  * Both commits are measured in the same container, so the comparison is
    valid even when the container is not the canonical environment (a
    contributor's own build of docker/gate.Dockerfile usually is not). The
    strict gate is a comparison against the recorded baseline, and that one IS
    bound to the canonical environment: off it, its binding check fails on both
    commits, and the gate is read as "findings on HEAD that BASE does not have"
    and labelled indicative.
  * A document whose DOCX is byte-identical on both commits (every part but
    docProps/) cannot have got better or worse. If its numbers moved anyway,
    that is measurement noise, and it is reported as noise, never as a verdict.
  * Run on one commit twice (`--repeat`) it is the determinism proof: every
    DOCX's word/*.xml byte-identical and every metric identical, or it says
    which were not.

Timing is reported and never judged: it depends on the machine.

Exit codes (and the verdict line):
    0  LIFTS             at least one document better beyond tolerance, nothing worse
       DETERMINISTIC     (--repeat) identical DOCX and identical numbers
    1  REGRESSES         a document worse beyond tolerance, a new crash, or a
                         gate finding on HEAD
    2  UNMEASURED        the two sides cannot be compared (missing results, a
                         different harness reading or environment, documents
                         that could not be measured)
    3  NEUTRAL           nothing better, nothing worse
    4  NONDETERMINISTIC  (--repeat) a DOCX or a number differed between runs
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import beta_readiness  # noqa: E402  (pure reading; imports nothing heavy)
import gate  # noqa: E402

SIDE_SCHEMA = "exactdoc.quality-check-side.v1"
REPORT_SCHEMA = "exactdoc.quality-check.v1"
LANES = ("raw", "product")            # runall.py's gate lanes

EXIT = {"LIFTS": 0, "DETERMINISTIC": 0, "REGRESSES": 1, "UNMEASURED": 2,
        "NEUTRAL": 3, "NONDETERMINISTIC": 4}

# Numbers that are not a measurement of the output: the machine's speed, and
# the package's size, which includes docProps/ (timestamps, compressed).
UNJUDGED_KEYS = ("convert_s", "docx_bytes")
# Row keys too bulky or too path-like to carry into the side record.
DROP_KEYS = ("pages", "trace", "render_pdf", "worst_pages_dy90")

# Paths whose change alters the measurement itself rather than the converter.
# A PR touching one needs the maintainer (CONTRIBUTING.md), so it is named.
CONTRACT_PATHS = (
    "testkit/gate_baseline.json", "testkit/canonical_env.json",
    "testkit/corpus_manifest.json", "testkit/corpus_expansion.json",
    "testkit/fixtures/", "testkit/fixtures_expansion/", "testkit/gate.py",
    "testkit/harness.py", "testkit/beta_readiness.py", "testkit/beta_waivers.json",
    "testkit/golden/", "testkit/gdocs_quality_policy.json", "uv.lock",
    "scripts/fonts.conf", "docker/",
)


# ------------------------------------------------------------------- collect
def docx_digests(path):
    """{"word_xml": sha256 over word/*.xml, "content": sha256 over every part
    but docProps/} of one DOCX, or None if it is not a readable package.

    docProps/ carries the package's timestamps, so it differs on every write;
    the same exclusion as exactdoc.refine._content_digest."""
    try:
        word, content = hashlib.sha256(), hashlib.sha256()
        with zipfile.ZipFile(path) as z:
            for name in sorted(z.namelist()):
                if name.startswith("docProps/"):
                    continue
                data = z.read(name)
                content.update(name.encode("utf-8") + b"\0" + data)
                if name.startswith("word/") and name.endswith(".xml"):
                    word.update(name.encode("utf-8") + b"\0" + data)
        return {"word_xml": word.hexdigest(), "content": content.hexdigest()}
    except (OSError, zipfile.BadZipFile, KeyError):
        return None


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def gate_row(r):
    """A runall.py result as a sweep-shaped row: `document`, and the gate's
    fatal keys folded into `error` the way quality_sweep.py spells them, so
    beta_readiness.classify_failure reads both alike (a conversion error is
    "Type: message", a scoring failure "evaluate Type: message")."""
    row = {k: v for k, v in r.items() if k not in DROP_KEYS}
    row["document"] = r.get("src")
    if "convert_error" in r:
        row["error"] = str(r["convert_error"])
    elif "eval_error" in r:
        row["error"] = "evaluate %s" % r["eval_error"]
    return row


def collect(side, batch, sweep=None, sweep_dir=None, out=None, ref=None,
            commit=None, steps=None, timing=None):
    """Read one commit's gate lanes and sweep into one side record."""
    rec = {"schema": SIDE_SCHEMA, "side": side, "ref": ref, "commit": commit,
           "steps": steps or {}, "timing": timing or {},
           "gate": {"lanes": {}, "provenance": _load(os.path.join(batch, "provenance.json"))},
           "sweep": None, "docx": {}}
    docx_out = os.path.join(out, "docx") if out else None
    for lane in LANES:
        d = os.path.join(batch, "lane_" + lane)
        results, verdict = _load(os.path.join(d, "results.json")), \
            _load(os.path.join(d, "verdict.json"))
        if results is None or verdict is None:
            rec["gate"]["lanes"][lane] = None
            continue
        rows = [gate_row(r) for r in results]
        rec["gate"]["lanes"][lane] = {"verdict": verdict, "rows": rows}
        digests = {}
        for r in rows:
            stem = os.path.splitext(r["document"] or "")[0]
            p = os.path.join(d, stem + ".docx")
            if stem and os.path.exists(p):
                digests[r["document"]] = docx_digests(p)
                if docx_out:
                    os.makedirs(os.path.join(docx_out, "gate-" + lane), exist_ok=True)
                    shutil.copy2(p, os.path.join(docx_out, "gate-" + lane, stem + ".docx"))
        rec["docx"]["gate:" + lane] = digests
    if sweep:
        data = _load(sweep)
        if data is not None:
            rows = [{k: v for k, v in r.items() if k not in DROP_KEYS}
                    for r in data.get("documents", ())]
            rec["sweep"] = {"profile": data.get("profile"), "corpus": data.get("corpus"),
                            "reading": data.get("reading"), "provenance": data.get("provenance"),
                            "jobs": data.get("jobs"), "elapsed_s": data.get("elapsed_s"),
                            "rows": rows}
            digests, kind = {}, "product"
            for r in rows:
                stem = os.path.splitext(r["document"])[0]
                p = os.path.join(sweep_dir or "", kind, stem, stem + ".docx")
                if sweep_dir and os.path.exists(p):
                    digests[r["document"]] = docx_digests(p)
                    if docx_out:
                        os.makedirs(os.path.join(docx_out, "sweep-" + kind), exist_ok=True)
                        shutil.copy2(p, os.path.join(docx_out, "sweep-" + kind, stem + ".docx"))
            rec["docx"]["sweep:" + kind] = digests
        else:
            rec["sweep"] = {"error": "no readable sweep payload at %s" % sweep, "rows": []}
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "side.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(rec, f, indent=1, sort_keys=True)
            f.write("\n")
    return rec


# ------------------------------------------------------------------- compare
def lane_rows(side):
    """{lane: rows} for every lane this side measured."""
    out = {}
    for lane in LANES:
        v = (side.get("gate") or {}).get("lanes", {}).get(lane)
        if v is not None:
            out["gate:" + lane] = v["rows"]
    sw = side.get("sweep")
    if sw and sw.get("rows"):
        out["sweep:product"] = sw["rows"]
    return out


def _numbers(row):
    return {k: v for k, v in row.items()
            if gate.is_number(v) and k not in UNJUDGED_KEYS}


def finding_key(f):
    """(kind, document, what) of a gate finding, without its numbers, so the
    same finding on two commits matches although its values differ."""
    detail = f.get("detail") or ""
    m = re.match(r"(aggregate \S+|\S+)", detail)
    return (f.get("kind"), f.get("document"), m.group(1) if m else "")


def gate_summary(base, head):
    """Per lane: each side's PASS/FAIL, the binding mode, and HEAD's findings
    that BASE does not have (the binding finding left out: it is a property of
    the environment, and it is the same on both sides)."""
    out = {}
    for lane in LANES:
        b = ((base.get("gate") or {}).get("lanes") or {}).get(lane)
        h = ((head.get("gate") or {}).get("lanes") or {}).get(lane)
        if b is None or h is None:
            out[lane] = None
            continue
        bv, hv = b["verdict"], h["verdict"]
        bf = [f for f in bv.get("failures", ()) if f.get("kind") != "binding"]
        hf = [f for f in hv.get("failures", ()) if f.get("kind") != "binding"]
        known = {finding_key(f) for f in bf}
        out[lane] = {
            "base_ok": bool(bv.get("ok")), "head_ok": bool(hv.get("ok")),
            "binding": (hv.get("baseline_binding") or {}).get("mode"),
            "base_findings": len(bf), "head_findings": len(hf),
            "new_findings": ["%s %s %s" % (f.get("kind"), f.get("document") or "-",
                                           f.get("detail")) for f in hf
                             if finding_key(f) not in known],
            "cleared_findings": ["%s %s %s" % (f.get("kind"), f.get("document") or "-",
                                               f.get("detail")) for f in bf
                                 if finding_key(f) not in {finding_key(x) for x in hf}],
        }
    return out


def compare_lane(lane, base_rows, head_rows, base_docx, head_docx):
    """Per-document better / same / worse for one lane, criterion 8's way,
    plus byte identity of the DOCX and exact identity of the numbers."""
    worse, _flags, _both, exempted, better = beta_readiness.compare_rows(
        base_rows, head_rows, gate.METRICS, gate.tolerance)
    worse_by, better_by = {}, {}
    for doc, metric, text in worse:
        worse_by.setdefault(doc, []).append(text)
    for doc, metric, text in better:
        better_by.setdefault(doc, []).append(text)
    base = {r["document"]: r for r in base_rows}
    docs = []
    for r in sorted(head_rows, key=lambda r: r["document"]):
        name = r["document"]
        b = base.get(name)
        bd, hd = (base_docx or {}).get(name), (head_docx or {}).get(name)
        fail_b = beta_readiness.classify_failure(b) if b else "missing"
        fail_h = beta_readiness.classify_failure(r)
        if bd is None and hd is None and b is not None and fail_b and fail_h:
            # No DOCX on either side (a crash or a refusal both times): nothing
            # was written twice, so nothing differs.
            same_docx = same_word = True
        else:
            same_docx = bool(bd and hd and bd["content"] == hd["content"])
            same_word = bool(bd and hd and bd["word_xml"] == hd["word_xml"])
        nb, nh = (_numbers(b) if b else {}), _numbers(r)
        moved = sorted(k for k in set(nb) | set(nh) if nb.get(k) != nh.get(k))
        entry = {"document": name, "docx_identical": same_docx,
                 "word_xml_identical": same_word, "metrics_identical": not moved and b is not None}
        if b is None:
            entry["status"] = "unmeasured"
            entry["why"] = ["not measured on BASE"]
        elif fail_h == "infra" or fail_b == "infra":
            entry["status"] = "unmeasured"
            entry["why"] = ["infrastructure failure on %s: %s" % (
                "HEAD" if fail_h == "infra" else "BASE",
                (r if fail_h == "infra" else b).get("error"))]
        elif name in worse_by:
            entry["status"], entry["why"] = "worse", worse_by[name]
        elif name in better_by:
            entry["status"], entry["why"] = "better", better_by[name]
        else:
            entry["status"] = "same"
        if same_docx and entry["status"] in ("better", "worse"):
            # The converter wrote the same document twice; whatever moved was the
            # renderer or the reading, not the change under test.
            entry["noise"] = entry.pop("why")
            entry["status"] = "same"
        if moved and entry["status"] == "same" and not entry.get("noise") and same_docx:
            entry["noise"] = ["numbers moved inside tolerance on an identical DOCX: %s"
                              % ", ".join(moved)]
        if moved:
            entry["moved"] = {k: [nb.get(k), nh.get(k)] for k in moved}
        docs.append(entry)
    for name in sorted(set(base) - {r["document"] for r in head_rows}):
        docs.append({"document": name, "status": "unmeasured",
                     "why": ["not measured on HEAD"], "docx_identical": False,
                     "word_xml_identical": False, "metrics_identical": False})
    return {"lane": lane, "documents": docs,
            "exempted": [e["detail"] for e in exempted],
            "counts": {s: sum(1 for d in docs if d["status"] == s)
                       for s in ("better", "same", "worse", "unmeasured")}}


def _reading(side):
    """The harness reading each part of one side was scored in."""
    out = set()
    prov = (side.get("gate") or {}).get("provenance") or {}
    if prov.get("reading"):
        out.add(json.dumps(prov["reading"], sort_keys=True))
    sw = side.get("sweep") or {}
    if sw.get("reading"):
        out.add(json.dumps(sw["reading"], sort_keys=True))
    return out


def _fingerprint(side):
    return ((side.get("gate") or {}).get("provenance") or {}).get("environment_fingerprint")


def contract_changes(changed):
    return sorted(p for p in changed or ()
                  if any(p == c or (c.endswith("/") and p.startswith(c))
                         for c in CONTRACT_PATHS))


def _lock_without_self(text):
    """uv.lock without exactdoc's own version line: a release bump rewrites it
    and changes no dependency."""
    out, prev = [], ""
    for line in (text or "").splitlines():
        if prev.strip() == 'name = "exactdoc"' and line.strip().startswith("version ="):
            prev = line
            continue
        out.append(line)
        prev = line
    return "\n".join(out)


def dependencies_differ(base_lock, head_lock):
    """Do the two commits' uv.lock files pin different dependencies? None
    (unknown) when either is missing."""
    if base_lock is None or head_lock is None:
        return None
    return _lock_without_self(base_lock) != _lock_without_self(head_lock)


def compare(base, head, changed=None, repeat=False, locks=None):
    """The report: per-lane document verdicts, the gate, and one overall line."""
    problems = []          # reasons the two sides cannot be compared
    for name, side in (("BASE", base), ("HEAD", head)):
        for lane in LANES:
            if ((side.get("gate") or {}).get("lanes") or {}).get(lane) is None:
                problems.append("%s: no gate results for lane %s (see its log)" % (name, lane))
        sw = side.get("sweep")
        if sw is not None and sw.get("error"):
            problems.append("%s: %s" % (name, sw["error"]))
    rb, rh = _reading(base), _reading(head)
    if len({json.loads(x)["scorer"] for x in rb | rh}) > 1:
        problems.append("the harness reading differs (BASE %s, HEAD %s): the numbers "
                        "are not comparable; a reading change needs the maintainer"
                        % (sorted(rb), sorted(rh)))
    warnings = []
    if len(rb | rh) > 1 and not any("harness reading" in p for p in problems):
        warnings.append("the harness reading code differs under one name (%s vs %s): "
                        "check that harness.HARNESS_READING was bumped"
                        % (sorted(rb), sorted(rh)))
    if locks and dependencies_differ(*locks):
        problems.append("uv.lock pins different dependencies on BASE and HEAD: both were "
                        "measured with the image's installed dependencies, so the numbers "
                        "do not describe HEAD; a dependency change is measured by the "
                        "maintainer in a rebuilt image")
    fb, fh = _fingerprint(base), _fingerprint(head)
    if fb and fh and fb != fh:
        problems.append("BASE and HEAD were measured in different environments "
                        "(%s vs %s): a dependency or font change is measured by the "
                        "maintainer in a rebuilt image" % (fb[:8], fh[:8]))

    lanes = {}
    lb, lh = lane_rows(base), lane_rows(head)
    for lane in sorted(set(lb) & set(lh)):
        lanes[lane] = compare_lane(lane, lb[lane], lh[lane],
                                   (base.get("docx") or {}).get(lane),
                                   (head.get("docx") or {}).get(lane))
    gates = gate_summary(base, head)
    canonical = all(g and g["binding"] == "bound" for g in gates.values()) and bool(gates)
    gate_regress = []
    for lane, g in sorted(gates.items()):
        if g is None:
            continue
        if canonical and not g["head_ok"]:
            gate_regress.append("gate %s FAILS on HEAD (strict, canonical environment)" % lane)
        elif not canonical and g["new_findings"]:
            gate_regress.append("gate %s: %d finding(s) on HEAD that BASE does not have "
                                "(indicative: not the canonical environment)"
                                % (lane, len(g["new_findings"])))

    worse = [(l, d) for l, v in lanes.items() for d in v["documents"] if d["status"] == "worse"]
    better = [(l, d) for l, v in lanes.items() for d in v["documents"] if d["status"] == "better"]
    unmeasured = [(l, d) for l, v in lanes.items() for d in v["documents"]
                  if d["status"] == "unmeasured"]
    noise = [(l, d) for l, v in lanes.items() for d in v["documents"] if d.get("noise")]

    determinism = None
    if repeat:
        alld = [d for v in lanes.values() for d in v["documents"]]
        determinism = {
            "docx_word_xml_identical": "%d/%d" % (sum(d["word_xml_identical"] for d in alld), len(alld)),
            "docx_content_identical": "%d/%d" % (sum(d["docx_identical"] for d in alld), len(alld)),
            "metrics_identical": "%d/%d" % (sum(d["metrics_identical"] for d in alld), len(alld)),
            "gate_findings_identical": all(g and not g["new_findings"] and not g["cleared_findings"]
                                           and g["base_ok"] == g["head_ok"]
                                           for g in gates.values()),
            "differing": ["%s %s%s%s" % (l, d["document"],
                                          "" if d["word_xml_identical"] else " word/*.xml",
                                          "" if d["metrics_identical"] else
                                          " numbers %s" % ",".join(sorted(d.get("moved", {}))))
                          for l, v in lanes.items() for d in v["documents"]
                          if not (d["word_xml_identical"] and d["metrics_identical"])],
        }

    if problems:
        verdict = "UNMEASURED"
    elif repeat:
        verdict = ("DETERMINISTIC" if not determinism["differing"]
                   and determinism["gate_findings_identical"] else "NONDETERMINISTIC")
    elif worse or gate_regress:
        verdict = "REGRESSES"
    elif unmeasured:
        verdict = "UNMEASURED"
    elif better:
        verdict = "LIFTS"
    else:
        verdict = "NEUTRAL"

    def side_info(s):
        prov = (s.get("gate") or {}).get("provenance") or {}
        return {"ref": s.get("ref"), "commit": s.get("commit"), "steps": s.get("steps"),
                "timing_s": s.get("timing"),
                "convert_s_total": {l: round(sum(r.get("convert_s") or 0 for r in rows), 1)
                                    for l, rows in lane_rows(s).items()}}

    prov = (head.get("gate") or {}).get("provenance") or {}
    report = {
        "schema": REPORT_SCHEMA, "verdict": verdict, "exit_code": EXIT[verdict],
        "mode": "repeat" if repeat else "base-vs-head",
        "base": side_info(base), "head": side_info(head),
        "environment": {"fingerprint": (prov.get("environment_fingerprint") or "")[:16] or None,
                        "canonical": prov.get("canonical"), "image_ref": prov.get("image_ref"),
                        "image_id": (prov.get("image_id") or "")[:19] or None,
                        "reading": prov.get("reading")},
        "gate": gates,
        "gate_canonical": canonical,
        "lanes": {l: {"counts": v["counts"],
                      "better": {d["document"]: d["why"] for d in v["documents"]
                                 if d["status"] == "better"},
                      "worse": {d["document"]: d["why"] for d in v["documents"]
                                if d["status"] == "worse"},
                      "unmeasured": {d["document"]: d["why"] for d in v["documents"]
                                     if d["status"] == "unmeasured"},
                      "docx_changed": sorted(d["document"] for d in v["documents"]
                                             if not d["docx_identical"]),
                      "noise": {d["document"]: d["noise"] for d in v["documents"]
                                if d.get("noise")},
                      "exempt_amendment_4": v["exempted"]}
                  for l, v in sorted(lanes.items())},
        "regressions": [("%s %s: %s" % (l, d["document"], "; ".join(d["why"])))
                        for l, d in worse] + gate_regress,
        "problems": problems, "warnings": warnings,
        "contract_changes": contract_changes(changed),
        "determinism": determinism,
        "timing_note": "informational only: timing depends on the machine and is never judged",
    }
    return report, lanes


def render(report, lanes):
    out = []
    b, h = report["base"], report["head"]
    out.append("exactdoc quality check (%s)" % report["mode"])
    out.append("  BASE %s  %s" % ((b["commit"] or "?")[:12], b["ref"] or ""))
    out.append("  HEAD %s  %s" % ((h["commit"] or "?")[:12], h["ref"] or ""))
    env = report["environment"]
    out.append("  environment %s (%s), image %s"
               % (env["fingerprint"] or "?",
                  "canonical" if env["canonical"] else "NOT canonical: the gate is indicative",
                  env["image_ref"] or "?"))
    out.append("")
    out.append("Gated 16, per lane (testkit/runall.py, gate.py)")
    for lane, g in sorted(report["gate"].items()):
        if g is None:
            out.append("  %-8s not measured" % lane)
            continue
        out.append("  %-8s BASE %-4s HEAD %-4s binding %-9s new findings on HEAD: %d%s"
                   % (lane, "PASS" if g["base_ok"] else "FAIL",
                      "PASS" if g["head_ok"] else "FAIL", g["binding"] or "?",
                      len(g["new_findings"]),
                      ", cleared: %d" % len(g["cleared_findings"]) if g["cleared_findings"] else ""))
        for f in g["new_findings"][:12]:
            out.append("      + %s" % f)
        for f in g["cleared_findings"][:12]:
            out.append("      - %s" % f)
    for lane, v in sorted(lanes.items()):
        c = v["counts"]
        out.append("")
        out.append("%s: better %d, same %d, worse %d, unmeasured %d"
                   % (lane, c["better"], c["same"], c["worse"], c["unmeasured"]))
        for d in v["documents"]:
            mark = {"better": "+", "worse": "-", "unmeasured": "?"}.get(d["status"])
            if mark:
                out.append("  %s %-34s %s" % (mark, d["document"][:34], "; ".join(d["why"])))
            elif d.get("noise"):
                out.append("  ~ %-34s noise: %s" % (d["document"][:34], "; ".join(d["noise"])))
        for e in v["exempted"]:
            out.append("  (exempt, amendment 4) %s" % e)
        changed = sum(1 for d in v["documents"] if not d["docx_identical"])
        out.append("  DOCX changed on %d of %d documents" % (changed, len(v["documents"])))
    if report["determinism"]:
        d = report["determinism"]
        out.append("")
        out.append("Determinism: word/*.xml identical %s, whole DOCX %s, numbers identical %s, "
                   "gate findings identical %s" % (d["docx_word_xml_identical"],
                                                   d["docx_content_identical"],
                                                   d["metrics_identical"],
                                                   "yes" if d["gate_findings_identical"] else "NO"))
        for x in d["differing"][:30]:
            out.append("  differs: %s" % x)
    if report["contract_changes"]:
        out.append("")
        out.append("Measurement contract changed (the maintainer must review these):")
        for p in report["contract_changes"]:
            out.append("  %s" % p)
    for w in report["warnings"]:
        out.append("WARNING %s" % w)
    for p in report["problems"]:
        out.append("CANNOT COMPARE: %s" % p)
    out.append("")
    t = ["%s %s" % (k, v) for k, v in sorted((b.get("timing_s") or {}).items())]
    u = ["%s %s" % (k, v) for k, v in sorted((h.get("timing_s") or {}).items())]
    out.append("Timing (information only, never judged): BASE %s | HEAD %s"
               % (", ".join(t) or "-", ", ".join(u) or "-"))
    out.append("")
    out.append("VERDICT %s (exit %d)" % (report["verdict"], report["exit_code"]))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="read one commit's gate lanes and sweep")
    c.add_argument("--side", required=True)
    c.add_argument("--batch", required=True, help="runall.py --out directory")
    c.add_argument("--sweep", default=None, help="quality_sweep.py --json payload")
    c.add_argument("--sweep-dir", default=None, help="quality_sweep.py --out directory")
    c.add_argument("--out", required=True)
    c.add_argument("--ref", default=None)
    c.add_argument("--commit", default=None)
    c.add_argument("--step", action="append", default=[], metavar="NAME=RC",
                   help="an exit code to record, e.g. gate=0")
    c.add_argument("--timing", action="append", default=[], metavar="NAME=SECONDS")
    k = sub.add_parser("compare", help="BASE against HEAD")
    k.add_argument("base")
    k.add_argument("head")
    k.add_argument("--json", default=None, help="write the report here")
    k.add_argument("--changed-files", default=None,
                   help="`git diff --name-only BASE HEAD`, one path per line")
    k.add_argument("--repeat", action="store_true",
                   help="the two sides are one commit measured twice: judge determinism")
    k.add_argument("--locks", nargs=2, default=None, metavar=("BASE_LOCK", "HEAD_LOCK"),
                   help="the two commits' uv.lock files: differing dependencies are UNMEASURED")
    a = ap.parse_args(argv)

    def pairs(items, conv):
        out = {}
        for it in items:
            name, _, val = it.partition("=")
            try:
                out[name] = conv(val)
            except ValueError:
                out[name] = val
        return out

    if a.cmd == "collect":
        rec = collect(a.side, a.batch, a.sweep, a.sweep_dir, a.out, a.ref, a.commit,
                      pairs(a.step, int), pairs(a.timing, float))
        n = {l: len(v["rows"]) if v else 0 for l, v in rec["gate"]["lanes"].items()}
        print("collected %s: gate %s, sweep %s" % (
            a.side, n, len((rec["sweep"] or {}).get("rows", ())) if rec["sweep"] else "-"))
        return 0

    def side(p):
        p = os.path.join(p, "side.json") if os.path.isdir(p) else p
        d = _load(p)
        if d is None:
            return {"side": p, "gate": {"lanes": {}}, "sweep": None, "docx": {}}
        return d
    changed = None
    if a.changed_files:
        with open(a.changed_files, encoding="utf-8") as f:
            changed = [l.strip() for l in f if l.strip()]
    locks = None
    if a.locks:
        def read(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return None
        locks = (read(a.locks[0]), read(a.locks[1]))
    report, lanes = compare(side(a.base), side(a.head), changed, a.repeat, locks)
    print(render(report, lanes))
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, indent=1, sort_keys=True)
            f.write("\n")
        print("report: %s" % a.json)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
