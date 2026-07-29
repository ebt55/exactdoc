"""The gate's decision, separated from the run that produces the numbers.

Everything here is a pure function over already-measured results. That is the
point: a gate whose only expression is inside a 200-line runner that converts 16
documents and shells out to LibreOffice cannot be tested, and an untested gate
is a claim. `tests/test_gate_mutations.py` feeds this module synthetic result
sets -- a deleted document, a renderer error, a missing metric, a known failure
sliding further -- and asserts each one comes back red. None of those tests need
an oracle, a corpus, or a minute.

What the previous gate could not see, all of it measured or read off the code:

  * `harness.evaluate()` returns `{"error": ...}` when the render fails, and
    nothing looked for that key. A renderer that died on every document scored
    zero failures.
  * A metric that was absent was skipped (`if v is None: continue`), so losing
    `within2pt` removed the check instead of failing it.
  * The baseline stored only the NAMES of failing metrics. `04_exec_brief`'s
    live-text coverage was recorded as "known failing" at 0.941; it could have
    fallen to 0.10 and stayed exactly as green.
  * `page_match` is a boolean, so a document already failing it could go from
    one page over to forty and register no change.
  * Nothing checked that the 16 expected documents were the 16 documents
    measured. The corpus generator exits 0 after skipping 8 of them.
  * `REFINE=lanes` returned only the refined lane's status, so a raw-lane
    regression could not fail the build.

The rule set below is deliberately three separate questions, because they have
different answers:

    regression   is anything worse than the number on record, beyond tolerance?
                 Applies to every document and every metric, passing or not.
                 This is the pull-request gate.
    absolute     does every document clear the release threshold? Documents
                 recorded BELOW a threshold are known shortfalls and must carry
                 a defect ID. This is the release-qualification gate.
    stale        does a recorded shortfall now pass? Then the record is wrong,
                 and a wrong record silently re-admits the regression it exists
                 to catch.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE_PATH = os.path.join(HERE, "gate_baseline.json")
MANIFEST_PATH = os.path.join(HERE, "corpus_manifest.json")

# Metric direction and how much cross-environment noise is tolerated.
#
# `threshold` is the absolute release bar. `None` means "not ratified yet": the
# metric is still gated against its recorded number, but no absolute claim is
# made about it. Writing a number here is a product decision, so an unratified
# one is left visibly empty rather than guessed at -- an invented threshold that
# the corpus happens to pass is indistinguishable from no threshold at all.
#
# `tol` is the regression slack, sized from measurement: three environments
# (CI Linux, a local ubuntu:24.04 container, Windows) agree on every structural
# number and differ in the third decimal of within2pt (STATUS.md §1). The
# tolerances are an order of magnitude above that noise and an order of
# magnitude below any regression this project has actually shipped.
#
# `rel` adds a proportional term, and `dy_p50` needs one. It is the only gated
# metric that is not a fraction in [0, 1]: it runs from 0.04pt on
# `02_research_paper` to 101pt on `c1_whitepaper` in the raw lane. A flat 0.5pt
# slack is generous at the bottom of that range and absurdly tight at the top,
# where two LibreOffice builds can disagree by more than that on a drift already
# two orders of magnitude past the threshold anyone cares about. The tolerance is
# max(tol, rel x recorded), so the absolute floor governs the small numbers and
# the proportional term governs the large ones.
HIGHER, LOWER, BOOL = "higher", "lower", "bool"
METRICS = {
    "page_err":      {"dir": LOWER,  "threshold": 0,    "tol": 0},
    "live_text_cov": {"dir": HIGHER, "threshold": 0.95, "tol": 0.010},
    "doc_recall":    {"dir": HIGHER, "threshold": 0.95, "tol": 0.010},
    "word_recall":   {"dir": HIGHER, "threshold": 0.90, "tol": 0.020},
    "within2pt":     {"dir": HIGHER, "threshold": None, "tol": 0.050},
    "dy_p50":        {"dir": LOWER,  "threshold": None, "tol": 0.500,
                      "rel": 0.10},
    "raster_frac":   {"dir": LOWER,  "threshold": None, "tol": 0.020},
}


def tolerance(spec, reference):
    """The slack allowed against `reference`, absolute and proportional."""
    tol = spec.get("tol", 0.0)
    rel = spec.get("rel")
    if rel and isinstance(reference, (int, float)):
        return max(tol, rel * abs(reference))
    return tol

# Aggregates are the headline numbers -- the ones that reach the README -- so
# they are gated as well. A set of per-document changes that each stay inside
# tolerance can still move the mean, and the mean is what gets published.
AGGREGATES = {
    "page_match_count": {"dir": HIGHER, "threshold": None, "tol": 0},
    "mean_within2pt":   {"dir": HIGHER, "threshold": None, "tol": 0.020},
    "mean_live_text":   {"dir": HIGHER, "threshold": None, "tol": 0.005},
    "median_dy_p50":    {"dir": LOWER,  "threshold": None, "tol": 0.300},
}

# Keys harness.evaluate() must have produced for a result to be scoreable at
# all. Absence is a failure, never a skip.
REQUIRED_KEYS = ("src_pages", "out_pages", "live_text_cov", "doc_recall",
                 "word_recall", "within2pt", "dy_p50", "raster_frac",
                 "mean_ssim", "renderer")

FATAL_KEYS = ("convert_error", "eval_error", "error")


class Verdict(object):
    """What the gate decided, and why. `ok` is the exit code's only source."""

    def __init__(self, lane):
        self.lane = lane
        self.failures = []          # (kind, document, detail)
        self.notes = []

    def fail(self, kind, doc, detail):
        self.failures.append((kind, doc, detail))

    def note(self, text):
        self.notes.append(text)

    @property
    def ok(self):
        return not self.failures

    def kinds(self):
        return sorted(set(k for k, _, _ in self.failures))

    def report(self):
        out = []
        for n in self.notes:
            out.append("  %s" % n)
        for kind, doc, detail in self.failures:
            out.append("  %-12s %-30s %s" % (kind, (doc or "-")[:30], detail))
        if not self.failures:
            out.append("  gate PASS (%s)" % self.lane)
        else:
            out.append("  gate FAIL (%s): %d finding(s) -- %s"
                       % (self.lane, len(self.failures), ", ".join(self.kinds())))
        return "\n".join(out)

    def as_dict(self):
        return {"lane": self.lane, "ok": self.ok,
                "failures": [{"kind": k, "document": d, "detail": v}
                             for k, d, v in self.failures],
                "notes": list(self.notes)}


# --------------------------------------------------------------- derived facts
def metric_values(result):
    """The gated metrics of one harness result, including derived ones.

    `page_err` is derived rather than read: `page_match` is a boolean, and a
    boolean cannot record that a document went from one page over to forty. The
    magnitude is the thing that has to be gated.
    """
    vals = {}
    for k in METRICS:
        if k == "page_err":
            if "src_pages" in result and "out_pages" in result:
                vals[k] = abs(int(result["out_pages"]) - int(result["src_pages"]))
            continue
        if k in result and isinstance(result[k], (int, float)):
            vals[k] = float(result[k])
    return vals


def worse(direction, value, reference, tol=0.0):
    """Is `value` worse than `reference` by more than `tol`?"""
    if direction == LOWER:
        return value > reference + tol
    if direction == BOOL:
        return bool(reference) and not bool(value)
    return value < reference - tol


def clears(direction, value, threshold):
    if threshold is None:
        return True
    if direction == LOWER:
        return value <= threshold
    if direction == BOOL:
        return bool(value) is bool(threshold)
    return value >= threshold


def aggregates(results):
    """Lane-level numbers, computed only from results that scored."""
    import statistics as st
    ok = [r for r in results if not any(k in r for k in FATAL_KEYS)]
    if not ok:
        return {}
    def mean(key):
        vals = [r[key] for r in ok if isinstance(r.get(key), (int, float))]
        return round(st.mean(vals), 4) if vals else None
    dys = [r["dy_p50"] for r in ok if isinstance(r.get("dy_p50"), (int, float))]
    return {
        "n": len(ok),
        "page_match_count": sum(1 for r in ok if r.get("page_match") is True),
        # "13/16 passed" is the number the README quotes, so it comes from here
        # rather than from a reader counting rows. It is not in AGGREGATES: it is
        # a function of the per-document thresholds, every one of which is
        # already gated, so gating it again would only double-report.
        "gate_pass_count": sum(1 for r in ok if all(
            clears(spec["dir"], v, spec["threshold"])
            for name, spec in METRICS.items()
            for v in [metric_values(r).get(name)] if v is not None)),
        "mean_within2pt": mean("within2pt"),
        "mean_live_text": mean("live_text_cov"),
        "median_dy_p50": round(st.median(dys), 3) if dys else None,
    }


# ------------------------------------------------------------------- the gate
def check(lane, results, manifest=None, baseline=None, absolute=False):
    """Score one lane. Returns a Verdict.

    `absolute` adds the release-qualification questions to the pull-request
    ones: without it a known shortfall may stay below its threshold, with it
    every document must clear every ratified threshold. CI runs both -- the
    regression form as a required check, the absolute form as the release gate
    -- because they answer different questions and conflating them is how "the
    gate is green" came to mean "nothing got measurably worse today".
    """
    v = Verdict(lane)
    baseline = baseline or {}
    docs_baseline = baseline.get("documents", {})
    defects = baseline.get("shortfall_defects", {})
    by_id = {}

    # 1. identity. Two inputs with the same basename overwrite each other's
    #    DOCX and each other's result row, so the second silently replaces the
    #    first and the count still looks right.
    for r in results:
        rid = r.get("src")
        if not rid:
            v.fail("malformed", None, "a result has no 'src' key")
            continue
        if rid in by_id:
            v.fail("duplicate", rid, "measured twice -- output and result "
                                     "identity collide on the basename")
            continue
        by_id[rid] = r

    if manifest:
        expected = set(manifest.get("documents", {}))
        for missing in sorted(expected - set(by_id)):
            v.fail("missing", missing, "in the corpus manifest, not in the run")
        for extra in sorted(set(by_id) - expected):
            v.fail("unexpected", extra, "measured but not in the corpus manifest")
        for doc_id, spec in sorted(manifest.get("documents", {}).items()):
            r = by_id.get(doc_id)
            want = spec.get("src_pages")
            if r is not None and want is not None and "src_pages" in r \
                    and int(r["src_pages"]) != int(want):
                v.fail("identity", doc_id,
                       "source is %s pages, manifest says %s -- this is not the "
                       "document the baseline was recorded against"
                       % (r["src_pages"], want))

    # 2. integrity. A result that carries an error key is a failure, not a row
    #    to be skipped: the renderer dying on every document used to score zero.
    for doc_id, r in sorted(by_id.items()):
        fatal = [k for k in FATAL_KEYS if k in r]
        if fatal:
            v.fail("error", doc_id, "%s: %s" % (fatal[0], str(r[fatal[0]])[:120]))
            continue
        for k in REQUIRED_KEYS:
            if k not in r:
                v.fail("no-metric", doc_id,
                       "required metric %r absent -- a metric that cannot be "
                       "computed is a failure, not a skip" % k)

    # 3. per-document thresholds and floors.
    for doc_id, r in sorted(by_id.items()):
        if any(k in r for k in FATAL_KEYS):
            continue
        recorded = docs_baseline.get(doc_id)
        vals = metric_values(r)
        if recorded is None:
            v.fail("unrecorded", doc_id,
                   "no numeric baseline for this document in lane %r -- record "
                   "one with GATE_BASELINE=update on the canonical environment"
                   % lane)
        for name, spec in sorted(METRICS.items()):
            if name not in vals:
                continue
            value = vals[name]
            ref = (recorded or {}).get(name)
            known_shortfall = (ref is not None
                               and not clears(spec["dir"], ref, spec["threshold"]))

            tol = tolerance(spec, ref)
            if ref is not None and worse(spec["dir"], value, ref, tol):
                v.fail("regression", doc_id,
                       "%s %.4g -> %.4g (recorded %.4g, tolerance %.3g)"
                       % (name, ref, value, ref, tol))
            elif ref is None and recorded is not None:
                # The document is on record but this metric is not: the record
                # predates the metric, and an ungated metric is how within2pt
                # once hid a 0.510 -> 0.291 regression in plain sight.
                v.fail("unrecorded", doc_id, "%s has no recorded value" % name)

            if not clears(spec["dir"], value, spec["threshold"]):
                if not known_shortfall:
                    v.fail("threshold", doc_id,
                           "%s %.4g misses %s and is not a recorded shortfall"
                           % (name, value, spec["threshold"]))
                elif doc_id not in defects:
                    v.fail("undocumented", doc_id,
                           "recorded below the %s threshold with no defect ID; "
                           "add one to shortfall_defects and to STATUS.md" % name)
            elif known_shortfall:
                v.fail("stale", doc_id,
                       "%s %.4g now clears %s but is recorded as %.4g -- a stale "
                       "record re-admits the regression it exists to catch"
                       % (name, value, spec["threshold"], ref))

            if absolute and not clears(spec["dir"], value, spec["threshold"]):
                v.fail("unqualified", doc_id,
                       "%s %.4g misses the release threshold %s"
                       % (name, value, spec["threshold"]))

    # 4. aggregates -- the published numbers.
    agg, ref_agg = aggregates(results), baseline.get("aggregate", {})
    for name, spec in sorted(AGGREGATES.items()):
        value, ref = agg.get(name), ref_agg.get(name)
        if value is None:
            v.fail("no-metric", None, "aggregate %r could not be computed" % name)
            continue
        if ref is None:
            v.fail("unrecorded", None, "aggregate %r has no recorded value" % name)
            continue
        tol = tolerance(spec, ref)
        if worse(spec["dir"], value, ref, tol):
            v.fail("regression", None,
                   "aggregate %s %.4g -> %.4g (tolerance %.3g)"
                   % (name, ref, value, tol))
        if absolute and not clears(spec["dir"], value, spec["threshold"]):
            v.fail("unqualified", None,
                   "aggregate %s %.4g misses the release threshold %s"
                   % (name, value, spec["threshold"]))

    v.note("%d document(s) measured, %d expected"
           % (len(by_id), len(manifest.get("documents", {})) if manifest else len(by_id)))
    return v


# ------------------------------------------------------------------- baseline
def record(lane, results):
    """The numeric record for one lane: every gated metric, every document."""
    docs = {}
    for r in results:
        if any(k in r for k in FATAL_KEYS) or not r.get("src"):
            continue
        docs[r["src"]] = {k: round(v, 4) for k, v in metric_values(r).items()}
    return {"documents": docs, "aggregate": aggregates(results)}


def load(path=BASELINE_PATH):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def load_lane(lane, path=BASELINE_PATH):
    return load(path).get("lanes", {}).get(lane, {})


def load_manifest(path=MANIFEST_PATH):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_lane(lane, data, path=BASELINE_PATH, environment=None):
    """Write one lane's record, preserving the others and the defect IDs."""
    doc = load(path) or {}
    doc["schema"] = 2
    doc["_note"] = (
        "Numeric per-document baseline for every gated metric, per lane, "
        "measured on the canonical environment (see .github/workflows/gate.yml). "
        "The gate asks three questions of it: nothing worse than these numbers "
        "beyond tolerance (regression), everything clears its threshold unless "
        "recorded below it (absolute), and nothing recorded below a threshold "
        "now passes (stale). Regenerate deliberately with GATE_BASELINE=update, "
        "never to silence a failure, and say so in the commit message.")
    lanes = doc.setdefault("lanes", {})
    prev = lanes.get(lane, {})
    entry = {"documents": data["documents"], "aggregate": data["aggregate"]}
    # Defect IDs are human knowledge and survive a re-record; the numbers do not.
    entry["shortfall_defects"] = prev.get("shortfall_defects", {})
    if environment:
        entry["environment"] = environment
    lanes[lane] = entry
    with open(path, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
    return path
