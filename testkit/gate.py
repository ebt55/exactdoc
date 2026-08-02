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
  * The two-lane runner once allowed a diagnostic regression to evade the
    build because only one lane's status controlled the exit code.

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
# `02_research_paper` to 101pt on `c1_whitepaper`. A flat 0.5pt
# slack is generous at the bottom of that range and absurdly tight at the top,
# where two LibreOffice builds can disagree by more than that on a drift already
# two orders of magnitude past the threshold anyone cares about. The tolerance is
# max(tol, rel x recorded), so the absolute floor governs the small numbers and
# the proportional term governs the large ones.
HIGHER, LOWER, BOOL = "higher", "lower", "bool"
# `range` is the semantic domain of the metric, and it is checked rather than
# assumed. A fraction outside [0, 1] is not a bad score, it is a broken
# measurement, and the two must not be confused: a `live_text_cov` of 1.7 would
# have sailed past every threshold in this file while meaning the harness had
# lost track of its own denominator.
METRICS = {
    "page_err":      {"dir": LOWER,  "threshold": 0,    "tol": 0,
                      "range": (0, None)},
    "live_text_cov": {"dir": HIGHER, "threshold": 0.95, "tol": 0.010,
                      "range": (0.0, 1.0)},
    "doc_recall":    {"dir": HIGHER, "threshold": 0.95, "tol": 0.010,
                      "range": (0.0, 1.0)},
    "word_recall":   {"dir": HIGHER, "threshold": 0.90, "tol": 0.020,
                      "range": (0.0, 1.0)},
    "within2pt":     {"dir": HIGHER, "threshold": None, "tol": 0.050,
                      "range": (0.0, 1.0)},
    "dy_p50":        {"dir": LOWER,  "threshold": None, "tol": 0.500,
                      "rel": 0.10, "range": (0.0, None)},
    "raster_frac":   {"dir": LOWER,  "threshold": None, "tol": 0.020,
                      "range": (0.0, 1.0)},
}

# The renderer a result must have been produced by. `harness.evaluate()` records
# "libreoffice" or "supplied"; a lane scored against a *different* oracle than the
# baseline is not comparable to it, and nothing checked. A missing key is a
# failure too -- it means the result predates the field or came from somewhere
# that does not identify itself.
EXPECTED_RENDERER = "libreoffice"


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


# --------------------------------------------------------------- value hygiene
def is_number(v):
    """A real, finite number. `True` is not one, and neither is NaN.

    `isinstance(True, int)` is True in Python, so a metric that arrived as a
    boolean would be silently scored as 1.0 or 0.0 -- and `page_match` *is* a
    boolean living next to these, so a one-key slip produces a perfect score
    rather than an error. NaN is worse than either: every comparison against it
    is False, so a NaN metric passes its threshold, passes its regression check,
    and passes its stale check, all by failing to be greater or less than
    anything.
    """
    import math
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return math.isfinite(v)


def metric_values(result):
    """The gated metrics of one harness result, including derived ones.

    Only well-formed values are returned. A malformed one is *omitted*, which
    makes it a missing metric, which `check()` fails on -- rather than being
    coerced and scored.

    `page_err` is derived rather than read: `page_match` is a boolean, and a
    boolean cannot record that a document went from one page over to forty. The
    magnitude is the thing that has to be gated.
    """
    vals = {}
    for k in METRICS:
        if k == "page_err":
            a, b = result.get("src_pages"), result.get("out_pages")
            if is_number(a) and is_number(b):
                vals[k] = abs(int(b) - int(a))
            continue
        v = result.get(k)
        if is_number(v):
            vals[k] = float(v)
    return vals


def validate_result(doc_id, result, expected_renderer=EXPECTED_RENDERER):
    """-> [(kind, detail)] structural problems with one measured result.

    Separate from thresholds on purpose. A threshold answers "is this good
    enough"; this answers "is this a measurement at all". The gate was asking
    only the first question, so a `live_text_cov` of `None`, `True`, `NaN` or
    `1.7` reached the comparison operators and was scored.
    """
    bad = []
    for key in ("src_pages", "out_pages"):
        v = result.get(key)
        if not is_number(v) or int(v) != v or int(v) < 1:
            bad.append(("malformed", "%s is %r; expected a positive integer"
                        % (key, v)))
    if is_number(result.get("src_pages")) and is_number(result.get("out_pages")):
        match = result.get("page_match")
        if not isinstance(match, bool):
            bad.append(("malformed", "page_match is %r; expected a bool" % (match,)))
        elif match != (int(result["src_pages"]) == int(result["out_pages"])):
            bad.append(("inconsistent",
                        "page_match=%s contradicts %s source vs %s rendered pages"
                        % (match, result["src_pages"], result["out_pages"])))

    renderer = result.get("renderer")
    if not renderer:
        bad.append(("no-oracle", "the result does not say which renderer produced "
                                 "it, so it cannot be compared to a baseline"))
    elif expected_renderer and renderer != expected_renderer:
        bad.append(("wrong-oracle",
                    "scored against %r, baseline recorded against %r"
                    % (renderer, expected_renderer)))

    for name, spec in sorted(METRICS.items()):
        if name == "page_err":
            continue
        if name not in result:
            continue                      # absence is `check()`'s no-metric case
        v = result[name]
        if not is_number(v):
            bad.append(("malformed", "%s is %r; expected a finite number"
                        % (name, v)))
            continue
        lo, hi = spec.get("range", (None, None))
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            bad.append(("out-of-range",
                        "%s=%r outside its domain [%s, %s] -- a broken "
                        "measurement, not a bad score" % (name, v, lo, hi)))
    return bad


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
    # Same well-formedness rule as everywhere else: a boolean or a NaN must not
    # be averaged into a headline number. A single NaN would make every mean NaN,
    # and NaN compares False against its own tolerance, so the aggregate gate
    # would pass while reporting nothing.
    def mean(key):
        vals = [r[key] for r in ok if is_number(r.get(key))]
        return round(st.mean(vals), 4) if vals else None
    dys = [r["dy_p50"] for r in ok if is_number(r.get("dy_p50"))]
    per_doc = [(r, metric_values(r)) for r in ok]
    return {
        "n": len(ok),
        "page_match_count": sum(1 for r in ok if r.get("page_match") is True),
        # "13/16 passed" is the number the README quotes, so it comes from here
        # rather than from a reader counting rows. It is not in AGGREGATES: it is
        # a function of the per-document thresholds, every one of which is
        # already gated, so gating it again would only double-report.
        "gate_pass_count": sum(
            1 for _, vals in per_doc
            if all(clears(spec["dir"], vals[name], spec["threshold"])
                   for name, spec in METRICS.items() if name in vals)),
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
    #    Then the values themselves: present is not the same as well-formed.
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
        for kind, detail in validate_result(doc_id, r):
            v.fail(kind, doc_id, detail)

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


class BaselineInvalid(Exception):
    """A committed baseline cannot describe the active lane contract."""


def baseline_contract_errors(doc):
    """Return fail-closed reasons a baseline cannot be compared safely."""
    from exactdoc.options import LANES, validate_lanes

    try:
        validate_lanes()
    except Exception as e:
        return ["active lane contract is invalid: %s" % e]
    if doc.get("schema") != 3:
        return ["baseline schema %r is obsolete; expected schema 3 for the "
                "raw/product lane contract" % doc.get("schema")]
    stored = doc.get("lanes")
    if not isinstance(stored, dict) or set(stored) != set(LANES):
        return ["baseline lanes %s do not match required lanes %s"
                % (sorted(stored or {}), sorted(LANES))]
    errors = []
    for lane, options in sorted(LANES.items()):
        actual = (stored.get(lane) or {}).get("profile_id")
        expected = options.profile_id()
        if actual != expected:
            errors.append("baseline lane %r is %r, active profile is %r"
                          % (lane, actual, expected))
    return errors


def load_lane(lane, path=BASELINE_PATH):
    doc = load(path)
    errors = baseline_contract_errors(doc)
    if errors:
        raise BaselineInvalid(
            "invalid gate baseline: %s. Re-record both lanes on canonical Linux "
            "with GATE_BASELINE=update uv run python testkit/runall.py"
            % "; ".join(errors))
    return doc["lanes"][lane]


def load_manifest(path=MANIFEST_PATH):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


class RecordRefused(Exception):
    """A baseline write that would have produced a record nobody can trust."""


def check_recordable(records, manifest, environment):
    """Raise unless this run is fit to become the number of record.

    A baseline is the thing every later run is judged against, so recording one
    is the single most consequential write in the repository -- and it had no
    preconditions at all. `GATE_BASELINE=update` on a laptop, over a subset of the
    corpus, with a renderer failure in the middle, would happily overwrite the
    canonical record with numbers describing none of it, and every subsequent run
    would then agree with it.

    Three preconditions, all fail-closed:

      canonical    Linux, matching .github/workflows/gate.yml. Local Windows
                   renders with real Arial and wraps differently; those are
                   legitimate numbers and they are not *the* numbers.
      complete     every manifest document, in every lane. A subset record is
                   worse than no record: it looks authoritative and covers a
                   corpus that was never measured.
      clean        no result carrying a conversion or evaluation error. Half a
                   lane is not a lane.
    """
    from exactdoc.options import LANES, validate_lanes

    try:
        validate_lanes()
    except Exception as e:
        raise RecordRefused("refusing to record invalid lane contract: %s" % e)
    if set(records) != set(LANES):
        raise RecordRefused(
            "refusing to record lanes %s; must record raw and product "
            "together" % sorted(records))
    if not environment.get("canonical"):
        raise RecordRefused(
            "refusing to record on %s: the baseline is the number of record and "
            "is measured on Linux (see .github/workflows/gate.yml). Local runs "
            "render with different fonts and are indicative, not authoritative."
            % environment.get("os", "this platform"))
    expected = set(manifest.get("documents", {}))
    for lane, rec in sorted(records.items()):
        got = set(rec.get("documents", {}))
        missing, extra = expected - got, got - expected
        if missing or extra:
            raise RecordRefused(
                "refusing to record lane %r over %d of %d manifest documents "
                "(missing %s; unexpected %s). A partial baseline looks "
                "authoritative and describes a corpus nobody measured."
                % (lane, len(got), len(expected),
                   sorted(missing) or "none", sorted(extra) or "none"))
    return True


def save_lanes(records, path=BASELINE_PATH, environment=None):
    """Write every lane at once, or write nothing.

    Transactional because a baseline half-written is a baseline that disagrees
    with itself: product and the correction-loop diagnostic must describe the
    same code. Serialised in full, then moved into place with `os.replace`, so
    an interrupted write cannot leave a truncated JSON file where the record
    used to be.
    """
    import tempfile
    from exactdoc.options import LANES, validate_lanes

    validate_lanes()
    if set(records) != set(LANES):
        raise RecordRefused("refusing to save partial lane set %s" % sorted(records))
    doc = load(path) or {}
    doc["schema"] = 3
    doc["_note"] = (
        "Numeric per-document baseline for every gated metric, per lane, "
        "measured on the canonical environment (see .github/workflows/gate.yml). "
        "The gate asks three questions of it: nothing worse than these numbers "
        "beyond tolerance (regression), everything clears its threshold unless "
        "recorded below it (absolute), and nothing recorded below a threshold "
        "now passes (stale). Regenerate deliberately with GATE_BASELINE=update, "
        "never to silence a failure, and say so in the commit message. Recording "
        "is refused off the canonical environment or over an incomplete corpus.")
    lanes = {}
    for lane, data in sorted(records.items()):
        prev = (doc.get("lanes") or {}).get(lane, {})
        entry = {"documents": data["documents"], "aggregate": data["aggregate"],
                 "profile_id": LANES[lane].profile_id()}
        # Defect IDs are human knowledge and survive a re-record; numbers do not.
        entry["shortfall_defects"] = prev.get("shortfall_defects", {})
        if environment:
            entry["environment"] = environment
        lanes[lane] = entry
    doc["lanes"] = lanes

    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".gate_baseline.", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
        os.replace(tmp, path)             # same filesystem: atomic
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path
