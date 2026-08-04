"""Grade a Google Docs live pass against predictions committed before it ran.

    python testkit/livepass_verify.py <gdocs_qualification.json>
    python testkit/livepass_verify.py <evidence.json> --predictions <file> --strict

A prediction recorded after the fact is not a prediction, so
`testkit/livepass_predictions.json` pins the expected per-document `dy_p50`
and the claim they rest on -- A-approx-zero, "Google Docs adds ~0pt of its own
at a flow-element boundary" -- before live pass #2 exists. This module is the
other half: it reads a fresh qualification evidence file and reports, per
document, predicted versus actual, and whether the claim survived.

Three things it deliberately does NOT do:

* No cloud calls, no credentials, no imports from `gdocs_oracle`. Grading is
  arithmetic over two JSON files and must stay runnable by anyone, offline,
  on evidence somebody else collected.
* No reading of the corpus, the fixtures, or the writer. If grading needed the
  converter it would be marking its own homework.
* It does not fail on a miss. A missed prediction is model error; only the
  falsification rule in the predictions file -- two or more *discriminating*
  documents landing closer to the retired model than to this one -- is fatal.
  `--strict` additionally fails on any non-advisory miss, for CI that wants the
  tighter contract.

Grading the 2026-08-04 evidence reports PRE-FIX BASELINE rather than a wall of
falsifications: that run had the compensation active, which is the state the
predictions are measured *from*. Detecting this is not politeness, it is the
difference between "the claim is wrong" and "you graded the wrong run".
"""
import argparse
import hashlib
import json
import os
import sys

SCHEMA = "exactdoc.livepass-predictions.v1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PREDICTIONS = os.path.join(HERE, "livepass_predictions.json")

# Exit codes. 1 is reserved for "the claim did not survive"; a merely
# inaccurate prediction is not the same event and must not share a code.
EXIT_OK = 0
EXIT_FALSIFIED = 1
EXIT_USAGE = 2
EXIT_MISSED = 3


class VerifyError(Exception):
    """Malformed or unusable input. Never raised for a failing prediction."""


# --------------------------------------------------------------------- load
def _read_json(path, what):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise VerifyError("cannot read %s: %s" % (what, exc.strerror or exc))
    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (ValueError, UnicodeDecodeError) as exc:
        raise VerifyError("%s is not valid JSON: %s" % (what, exc))


def load_predictions(path=None):
    payload, _ = _read_json(path or DEFAULT_PREDICTIONS, "predictions")
    if payload.get("schema") != SCHEMA:
        raise VerifyError("predictions schema is %r, expected %r"
                          % (payload.get("schema"), SCHEMA))
    for key in ("documents", "checks", "claim", "falsification_rule"):
        if key not in payload:
            raise VerifyError("predictions file has no %r section" % key)
    return payload


def load_evidence(path):
    payload, digest = _read_json(path, "evidence")
    docs = payload.get("documents")
    if not isinstance(docs, list):
        raise VerifyError("evidence has no 'documents' list")
    by_name = {}
    for row in docs:
        name = row.get("docx") or row.get("source") or ""
        stem = os.path.splitext(name)[0]
        if stem:
            by_name[stem] = row.get("metrics") or {}
    if not by_name:
        raise VerifyError("evidence contains no named documents")
    return payload, by_name, digest


# ---------------------------------------------------------------- pre-fix
def detect_state(preds, evidence, by_name, digest):
    """Is this the run the predictions were measured FROM, or a test of them?

    Two independent signals, because either alone can mislead: the recorded
    hash is exact but breaks the moment anyone reformats the file, and the
    value comparison is robust but could in principle coincide.
    """
    base = preds.get("baseline_evidence") or {}
    if base.get("sha256") and digest == base["sha256"]:
        return "pre-fix", "evidence sha256 matches the recorded pre-fix baseline"

    docs = preds["documents"]
    same = total = 0
    for name, spec in docs.items():
        actual = (by_name.get(name) or {}).get("dy_p50")
        baseline = spec.get("baseline_dy_p50")
        if actual is None or baseline is None:
            continue
        total += 1
        # values are recorded to 2dp, so equality is a tight window
        if abs(float(actual) - float(baseline)) <= 0.51:
            same += 1
    if total and same / total >= 0.6:
        return "pre-fix", ("%d of %d documents still report their pre-fix "
                           "dy_p50" % (same, total))
    return "post-fix", "evidence differs from the recorded pre-fix baseline"


# ---------------------------------------------------------------- grading
def _dy_rows(preds, by_name):
    rows = []
    for name, spec in sorted(preds["documents"].items()):
        predicted = spec.get("predicted_dy_p50")
        metrics = by_name.get(name)
        actual = None if metrics is None else metrics.get("dy_p50")
        tol = spec.get("tolerance_pt")
        if tol is None:
            tol = (preds.get("tolerance") or {}).get("default_pt", 4.0)
        row = {
            "document": name,
            "tier": spec.get("tier"),
            "baseline": spec.get("baseline_dy_p50"),
            "predicted": predicted,
            "actual": actual,
            "tolerance": tol,
            "discriminating": bool(spec.get("discriminating")),
            "falsifies_above": spec.get("falsifies_A0_above_pt"),
            "expect": spec.get("expect"),
            "confidence": spec.get("confidence"),
            "note": spec.get("note"),
        }
        if predicted is None:
            row["verdict"] = "no-prediction"
        elif actual is None:
            row["verdict"] = "absent"
        else:
            row["delta"] = round(float(actual) - float(predicted), 2)
            row["verdict"] = ("pass" if abs(row["delta"]) <= float(tol)
                              else "miss")
        rows.append(row)
    return rows


def _falsification(preds, rows):
    rule = preds["falsification_rule"]
    need = int(rule.get("min_documents_to_falsify", 2))
    exceeded = []
    for row in rows:
        thr = row["falsifies_above"]
        if not row["discriminating"] or thr is None:
            continue
        if row["actual"] is None:
            continue
        if float(row["actual"]) > float(thr):
            exceeded.append(row)
    return {
        "rule": rule.get("statement"),
        "min_documents_to_falsify": need,
        "exceeded": [r["document"] for r in exceeded],
        "falsified": len(exceeded) >= need,
        "warn_single": 0 < len(exceeded) < need,
    }


def _run_checks(preds, by_name, rows):
    by_doc = {r["document"]: r for r in rows}
    out = []
    for spec in preds["checks"]:
        kind = spec.get("kind")
        res = {"id": spec.get("id"), "kind": kind,
               "advisory": bool(spec.get("advisory")),
               "description": spec.get("description"),
               "details": [], "status": "pass"}
        if kind == "dy_prediction":
            bound = spec.get("bound_pt")
            for name in spec.get("documents", []):
                row = by_doc.get(name)
                if row is None or row["actual"] is None:
                    res["details"].append("%s: absent from evidence" % name)
                    res["status"] = "incomplete"
                    continue
                bits = ["%s: predicted %.2f actual %.2f (%s)"
                        % (name, row["predicted"], row["actual"],
                           row["verdict"])]
                if row["verdict"] == "miss":
                    res["status"] = "miss"
                if bound is not None and float(row["actual"]) > float(bound):
                    bits.append("OVER bound %.1f" % bound)
                    if row["expect"] not in ("improves-but-still-blocking",
                                             "worsens-crosses-bound",
                                             "worsens-within-existing-failure"):
                        res["status"] = "miss"
                res["details"].append(" ".join(bits))
        elif kind == "page_match":
            for name in spec.get("documents", []):
                metrics = by_name.get(name)
                if metrics is None:
                    res["details"].append("%s: absent from evidence" % name)
                    res["status"] = "incomplete"
                    continue
                ok = metrics.get("page_match") is True
                res["details"].append("%s: page_match=%s" % (name, metrics.get("page_match")))
                if not ok:
                    res["status"] = "miss"
        elif kind == "metric_improves":
            name, metric = spec.get("document"), spec.get("metric")
            metrics = by_name.get(name) or {}
            actual = metrics.get(metric)
            base = spec.get("baseline")
            if actual is None:
                res["details"].append("%s: %s absent" % (name, metric))
                res["status"] = "incomplete"
            else:
                up = spec.get("direction", "up") == "up"
                ok = (float(actual) > float(base)) if up else (float(actual) < float(base))
                res["details"].append("%s %s: baseline %.4f actual %.4f (%s)"
                                      % (name, metric, float(base), float(actual),
                                         "improved" if ok else "did not improve"))
                if not ok:
                    res["status"] = "miss"
        elif kind == "page_ssim_split":
            name = spec.get("document")
            metrics = by_name.get(name) or {}
            pages = {str(p.get("page")): p.get("ssim")
                     for p in (metrics.get("pages") or [])}
            tol = float(spec.get("unchanged_tolerance", 0.05))
            for pno, was in (spec.get("unchanged_pages") or {}).items():
                now = pages.get(str(pno))
                if now is None:
                    res["details"].append("p%s: absent" % pno)
                    res["status"] = "incomplete"
                    continue
                moved = abs(float(now) - float(was))
                res["details"].append(
                    "p%s expected ~unchanged: was %.4f now %.4f (%s)"
                    % (pno, float(was), float(now),
                       "as predicted" if moved <= tol else "moved %.4f" % moved))
            for pno, was in (spec.get("improved_pages") or {}).items():
                now = pages.get(str(pno))
                if now is None:
                    res["details"].append("p%s: absent" % pno)
                    res["status"] = "incomplete"
                    continue
                ok = float(now) > float(was)
                res["details"].append("p%s expected improvement: was %.4f now %.4f (%s)"
                                      % (pno, float(was), float(now),
                                         "improved" if ok else "did not improve"))
                if not ok:
                    res["status"] = "miss"
        elif kind == "expected_blocking":
            name = spec.get("document")
            metrics = by_name.get(name) or {}
            for metric, rule in (spec.get("metrics") or {}).items():
                actual = metrics.get(metric)
                if actual is None:
                    res["details"].append("%s %s: absent" % (name, metric))
                    res["status"] = "incomplete"
                    continue
                near, tol = float(rule.get("expect_near")), float(rule.get("tolerance", 10.0))
                moved = abs(float(actual) - near)
                res["details"].append(
                    "%s %s: expected ~%.2f actual %.2f (%s)"
                    % (name, metric, near, float(actual),
                       "as expected" if moved <= tol else "moved %.2f" % moved))
        else:
            res["status"] = "unknown-kind"
            res["details"].append("no handler for kind %r" % kind)
        out.append(res)
    return out


def grade(preds, evidence, by_name, digest):
    rows = _dy_rows(preds, by_name)
    state, why = detect_state(preds, evidence, by_name, digest)
    report = {
        "schema": "exactdoc.livepass-verification.v1",
        "state": state,
        "state_reason": why,
        "claim": preds["claim"]["id"],
        "evidence_sha256": digest,
        "candidate_profile": evidence.get("candidate_profile"),
        "documents": rows,
        "checks": _run_checks(preds, by_name, rows),
    }
    if state == "pre-fix":
        # The predictions are measured FROM this run; grading it against them
        # would report every improvement as a failure. Relabel rather than
        # score: a "miss" here would mean the fix had run and fallen short,
        # and it has not run at all.
        for row in rows:
            if row["verdict"] in ("pass", "miss"):
                row["verdict"] = "baseline"
            if row["predicted"] is not None and row["actual"] is not None:
                row["expected_move"] = round(
                    float(row["predicted"]) - float(row["actual"]), 2)
            row.pop("delta", None)
        for check in report["checks"]:
            check["status"] = "baseline"
        report["falsification"] = {
            "falsified": False,
            "skipped": True,
            "reason": "evidence predates the change under test",
        }
    else:
        report["falsification"] = _falsification(preds, rows)
    return report


# ----------------------------------------------------------------- render
def render(report, preds):
    L = []
    add = L.append
    add("live pass verification -- claim under test: %s" % report["claim"])
    add("state: %s (%s)" % (report["state"].upper(), report["state_reason"]))
    add("evidence sha256: %s" % report["evidence_sha256"][:16])
    if report["state"] == "pre-fix":
        add("")
        add("This is the PRE-FIX BASELINE run: the compensation was still active,")
        add("and these predictions describe what should happen once it is gone.")
        add("Reporting current numbers as the baseline; nothing is graded.")
    pre = report["state"] == "pre-fix"
    last = "must move" if pre else "delta"
    add("")
    add("%-22s %5s %9s %9s %8s %9s  %s"
        % ("document", "tier", "baseline", "predicted", "actual", last, "verdict"))
    add("-" * 89)
    for r in report["documents"]:
        tier = "ord" if r["tier"] == "ordinary_digital" else "str"
        if pre:
            tail = "-" if "expected_move" not in r else "%+.2f" % r["expected_move"]
        else:
            tail = "-" if "delta" not in r else "%+.2f" % r["delta"]
        add("%-22s %5s %9s %9s %8s %9s  %s%s" % (
            r["document"], tier,
            "-" if r["baseline"] is None else "%.2f" % r["baseline"],
            "-" if r["predicted"] is None else "%.2f" % r["predicted"],
            "-" if r["actual"] is None else "%.2f" % r["actual"],
            tail, r["verdict"],
            " *" if r["discriminating"] else ""))
    add("-" * 89)
    add("* = discriminating: separates this claim from the retired 3pt model")
    if pre:
        add("'must move' is how far the fix has to shift each document to hit prediction.")

    add("")
    add("checks (recorded, graded on the next pass)" if pre else "checks")
    for c in report["checks"]:
        add("  [%s]%s %s" % (c["status"], " (advisory)" if c["advisory"] else "",
                             c["id"]))
        for d in c["details"]:
            add("      %s" % d)

    f = report["falsification"]
    add("")
    if f.get("skipped"):
        add("falsification: not evaluated -- %s" % f["reason"])
    elif f["falsified"]:
        add("FALSIFIED: %s" % f["rule"])
        add("  discriminating documents above threshold: %s"
            % ", ".join(f["exceeded"]))
        add("  %s is not supported by this run." % report["claim"])
    elif f["warn_single"]:
        add("claim survives, with a warning.")
        add("  one discriminating document above threshold: %s"
            % ", ".join(f["exceeded"]))
        add("  %d are needed to falsify; treat as a reflow artefact unless it repeats."
            % f["min_documents_to_falsify"])
    else:
        add("claim survives: no discriminating document exceeded its threshold.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Grade a Google Docs live pass against committed predictions.")
    ap.add_argument("evidence", help="a gdocs_qualification.json from a live pass")
    ap.add_argument("--predictions", default=None,
                    help="predictions file (default: testkit/livepass_predictions.json)")
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    ap.add_argument("--strict", action="store_true",
                    help="also exit nonzero when a non-advisory prediction misses")
    args = ap.parse_args(argv)

    try:
        preds = load_predictions(args.predictions)
        evidence, by_name, digest = load_evidence(args.evidence)
    except VerifyError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_USAGE

    report = grade(preds, evidence, by_name, digest)
    print(json.dumps(report, indent=1, sort_keys=True) if args.json
          else render(report, preds))

    if report["falsification"].get("falsified"):
        return EXIT_FALSIFIED
    if args.strict and report["state"] != "pre-fix":
        missed = [c["id"] for c in report["checks"]
                  if c["status"] == "miss" and not c["advisory"]]
        if missed:
            sys.stderr.write("strict: checks missed: %s\n" % ", ".join(missed))
            return EXIT_MISSED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
