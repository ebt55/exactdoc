"""The acceptance test for replacing the parser -- and the policy it enforces.

The swap is done when pypdfium2 is not WORSE than PyMuPDF, not when it is
perfect. Several corpus documents already fail on PyMuPDF (nested tables,
rasterised SVG charts), and chasing those while believing they are swap
regressions would burn the schedule on pre-existing bugs.

So this converts both backends over the manifest corpus with the same profile
and marks each document REGRESSION / same / BETTER / expected-div / accepted.

    python testkit/backend_parity.py
    python testkit/backend_parity.py --profile candidate --measure
    python testkit/backend_parity.py --profile candidate-refined --measure
    python testkit/backend_parity.py --profile candidate-refined --measure --only c7_code
    python testkit/backend_parity.py --profile product --update-policy  # matching policy only

**The policy is `parity_policy.json`, not this docstring.** It used to be the
other way round: the code exited on `regressions == 0` while ROADMAP §3.2 and
STATUS D2 said two named documents were formally accepted divergences. An
executable rule that contradicts the ratified rule has one outcome -- the step
gets marked `continue-on-error` so the build stays usable, which is what
happened, and from then on nothing was gated at all. Two accepted shortfalls now
live in the policy file with numeric floors: worsening past a floor fails, and
so does clearing the divergence entirely, because an acceptance that no longer
describes reality is a stale record.

--only takes substrings and narrows the run. The full run converts 16 documents
twice and renders both, which is minutes; a single document is seconds. It exists
so a hypothesis about one document costs that document. `--only` can never report
the swap as acceptable: the verdict needs the whole corpus, and the exit code
says so.
"""
import argparse
import json
import os
import re
import sys

import _paths  # noqa: F401
import evidence
import gate
import harness
import runall

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(ROOT)
POLICY_PATH = os.path.join(ROOT, "parity_policy.json")

# Every gated dimension, evaluated INDEPENDENTLY.
#
# This used to compare in priority order and return on the first dimension outside
# its margin, so a document that gained a page and lost a third of its fine
# placement was reported by its page gain alone -- an improvement anywhere
# suppressed every regression below it. Priority is the right way to *describe* a
# result and the wrong way to decide one: a regression is a regression whatever
# else improved beside it.
#
# The set is the gate's own, so a dimension cannot be gated in one place and
# ignored in the other. Leaving within2pt out of this comparison was a real hole:
# a swap this harness called clean cost within-2pt 0.510 -> 0.291 and median drift
# 0.69pt -> 2.02pt, invisibly.
DIMENSIONS = ("page_err", "live_text_cov", "doc_recall", "word_recall",
              "within2pt", "dy_p50", "raster_frac")
LOWER_IS_BETTER = ("page_err", "dy_p50", "raster_frac")
PROFILE_NAMES = ("product", "candidate", "candidate-refined")


def profile_labels(profile, ref_name, cand_name):
    """Profile ids for the run and for BOTH arms, each naming its own backend.

    A parity run swaps the backend and holds everything else fixed, so a single
    `profile_id` describes the settings but not the two things being compared.
    Its backend token is whatever the named profile carries, and a reader who
    takes it for the arm it is not concludes the wrong configuration was
    measured.

    Which arm it coincides with is not fixed and must not be assumed. Before the
    parser flip the `product` profile carried `pymupdf`, so `profile_id` read as
    the REFERENCE; it now carries `pdfium`, so it reads as the CANDIDATE. Both
    arm labels are derived from their own backend name here precisely so that
    neither reading is ever load-bearing.

    That is not hypothetical. `docs/evidence/parity-expanded-2026-08-04b.json`
    records `gated16_product.candidate_profile_id` as
    `pymupdf/standard/libreoffice/refine3@240dpi` while its own sibling `_note`
    says the run was "pymupdf/... against pdfium/...", because this function did
    not exist and the field was filled in by hand from `profile_id`. Eight
    documents then read as MAJOR "under the shipping profile" when what was
    measured was a PDFium swap. Emitting both arms here is what stops the label
    and the measurement from disagreeing again; the historical files stay as
    recorded.

    `parity_expansion.py` already derives its own labels this way.
    """
    return {"profile_id": profile.profile_id(),
            "reference_profile_id": profile.replace(backend=ref_name).profile_id(),
            "candidate_profile_id": profile.replace(backend=cand_name).profile_id()}
PROFILE_ID_RE = re.compile(r"^[^/]+/[^/]+/[^/]+/refine\d+@\d+dpi$")


def conversion_profile(name):
    """The complete, validated profile selected by the parity CLI."""
    from exactdoc.options import (PDFIUM_GDOCS_CANDIDATE,
                                  PDFIUM_GDOCS_CANDIDATE_REFINED, PRODUCT)
    return {"product": PRODUCT,
            "candidate": PDFIUM_GDOCS_CANDIDATE,
            "candidate-refined": PDFIUM_GDOCS_CANDIDATE_REFINED}[name]


def load_policy(path=None):
    path = path or POLICY_PATH
    with open(path) as f:
        return json.load(f)


def _clean(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def dims(res):
    """The comparable dimensions of a result, or {} if it is not measurable.

    Delegates to `gate.metric_values`, which rejects booleans, NaN and infinities
    rather than coercing them -- so a dimension that arrived malformed is absent
    here and shows up as an unmeasurable document, not as a score of zero.
    """
    return gate.metric_values(res)


def margin_for(name, margins, reference):
    """How much worse the candidate may be on `name` before it counts.

    `dy_p50` is the one dimension that is not a fraction -- it runs from 0.04pt to
    101pt across this corpus -- so its margin is proportional as well as absolute,
    reusing the gate's own rule rather than inventing a second one.
    """
    m = margins.get(name, 0)
    spec = gate.METRICS.get(name)
    if spec and spec.get("rel") and gate.is_number(reference):
        return max(m, spec["rel"] * abs(reference))
    return m


DY_EXEMPTION_SECTION = "dy_absolute_exemption"
_DY_EXEMPTION_FIELDS = {"both_arms_below_pt", "conditioned_on", "reason",
                        "clears_at_record", "measured_on", "evidence"}


def dy_exemption_for(policy, profile_id):
    """-> (spec, errors): the absolute-magnitude dy rule bound to THIS profile.

    Keyed by full profile ID and never borrowed across profiles, for the same
    reason floors are not: `dy_p50` at the shipping settings and at the
    candidate profile are different distributions measured through different
    renderers, and a ceiling calibrated on one says nothing about the other. A
    policy may record a section for a profile it does not govern -- the entry is
    then simply never selected, because `adjudicate` refuses a profile mismatch
    long before it gets here.

    A malformed section is an ERROR, not an absence. Silently ignoring a rule
    that is present but unreadable would mean the file says one thing and the
    gate does another, which is the failure this whole policy exists to prevent.
    """
    block = policy.get(DY_EXEMPTION_SECTION)
    if block is None:
        return None, []
    if not isinstance(block, dict):
        return None, ["%s is not an object" % DY_EXEMPTION_SECTION]
    spec = _clean(block).get(profile_id)
    if spec is None:
        return None, []
    if not isinstance(spec, dict) or set(spec) != _DY_EXEMPTION_FIELDS:
        return None, ["%s/%s must carry exactly %s"
                      % (DY_EXEMPTION_SECTION, profile_id,
                         ", ".join(sorted(_DY_EXEMPTION_FIELDS)))]
    ceiling = spec["both_arms_below_pt"]
    if not gate.is_number(ceiling) or ceiling <= 0:
        return None, ["%s/%s: both_arms_below_pt must be a positive number"
                      % (DY_EXEMPTION_SECTION, profile_id)]
    if spec["conditioned_on"] != ["within2pt"]:
        return None, ["%s/%s: conditioned_on must be exactly [\"within2pt\"] -- "
                      "an unconditioned magnitude rule would excuse a document "
                      "whose placement genuinely degraded"
                      % (DY_EXEMPTION_SECTION, profile_id)]
    for field in ("reason", "measured_on", "evidence"):
        if not isinstance(spec[field], str) or not spec[field].strip():
            return None, ["%s/%s: %s must be a non-empty string"
                          % (DY_EXEMPTION_SECTION, profile_id, field)]
    if not isinstance(spec["clears_at_record"], list):
        return None, ["%s/%s: clears_at_record must be a list"
                      % (DY_EXEMPTION_SECTION, profile_id)]
    return spec, []


def apply_dy_exemption(worse, da, db, spec):
    """-> (worse, fired): drop `dy_p50` when both arms are already tiny.

    `dy_p50` is a median in points, and the margin that governs it is
    proportional (10% of the reference) with a 0.5pt floor. Near zero that floor
    is the whole rule, so a document can move 0.04pt -> 1.29pt and be graded a
    regression on a difference that is a fraction of one line's leading. Below
    a couple of points the metric is measuring the ascent convention of whoever
    reported the glyph tops, not the placement a reader would see -- see
    docs/dy-ascent-artifact.md.

    The condition is what keeps this honest, and it is not optional. `within2pt`
    counts the words actually landing within 2pt of source, so it is the direct
    statement of the thing `dy_p50` only proxies. If it moved adversely on the
    same document, the placement really did degrade and the magnitude rule must
    not excuse it -- `02_research_paper` and `03_tech_report_code` are exactly
    that case, both inside the 2pt ceiling and both losing ~0.18 of within2pt,
    and both keep their regression because of this clause.
    """
    if not spec or not any(w[0] == "dy_p50" for w in worse):
        return worse, False
    ceiling = spec["both_arms_below_pt"]
    ref, cand = da.get("dy_p50"), db.get("dy_p50")
    if not (gate.is_number(ref) and gate.is_number(cand)):
        return worse, False
    if not (abs(ref) < ceiling and abs(cand) < ceiling):
        return worse, False
    if any(w[0] == "within2pt" for w in worse):
        return worse, False
    return [w for w in worse if w[0] != "dy_p50"], True


def compare(a, b, margins):
    """-> (worse, better): the dimensions that moved, each judged on its own.

    Both lists are returned. A document is a regression if `worse` is non-empty,
    *regardless* of what is in `better` -- which is the whole point: the previous
    version stopped at the first dimension outside its margin, so one improvement
    hid every regression ordered after it.
    """
    da, db = dims(a), dims(b)
    worse, better = [], []
    for name in DIMENSIONS:
        if name not in da or name not in db:
            worse.append((name, None, None))       # unmeasurable is not "equal"
            continue
        delta = db[name] - da[name]
        if abs(delta) <= margin_for(name, margins, da[name]):
            continue
        got_worse = (delta > 0) if name in LOWER_IS_BETTER else (delta < 0)
        (worse if got_worse else better).append((name, da[name], db[name]))
    return worse, better


def run(backend, srcs, out_root, profile):
    """Convert the corpus with one backend. No monkey-patching, nothing dropped.

    This used to reassign `exactdoc.convert.parse_pdf`, so the gate measured a
    module it had mutated rather than the product, and the mutation silently
    bypassed whatever backend selection `convert()` would have done itself.

    Failures are *recorded*, not printed and discarded. A document that failed to
    convert or score simply vanished from the returned mapping -- and if it failed
    under **both** backends it vanished from both, so the two sets still matched,
    the comparison never mentioned it, and a document that no longer converts at
    all read as a document with nothing to say about it. Now it comes back with a
    `convert_error` or `eval_error` key, which `adjudicate` treats as a failure on
    both sides.

    `options=` is passed explicitly, and since backend precedence puts an explicit
    profile above the environment, an exported `EXACTDOC_BACKEND` can no longer
    redirect either lane of the gate that exists to compare them.
    """
    from exactdoc.convert import convert

    # The two comparison arms differ on exactly one axis. In particular, never
    # mutate refine_rounds independently: its valid oracle and output profile
    # come from the selected named profile as one validated unit.
    options = profile.replace(backend=backend)
    out = os.path.join(out_root, backend)
    os.makedirs(out, exist_ok=True)
    pairs, res = [], {}
    for s in srcs:
        doc_id = os.path.basename(s)
        n = os.path.splitext(doc_id)[0]
        dx = os.path.join(out, n + ".docx")
        try:
            convert(s, dx, options=options)
            pairs.append((s, dx, n))
        except Exception as e:
            res[doc_id] = {"src": doc_id,
                           "convert_error": "%s: %s" % (type(e).__name__, e)}
            print("  CONVERT FAIL [%s] %-22s %s" % (backend, n[:22], str(e)[:50]))
    harness.batch_docx_to_pdf([p[1] for p in pairs], os.path.join(out, "r"))
    for s, dx, n in pairs:
        doc_id = os.path.basename(s)
        try:
            res[doc_id] = harness.evaluate(s, dx, os.path.join(out, "r"),
                                           save_images=False)
        except Exception as e:
            res[doc_id] = {"src": doc_id,
                           "eval_error": "%s: %s" % (type(e).__name__, e)}
            print("  EVAL FAIL [%s] %-22s %s" % (backend, n[:22], str(e)[:50]))
    return res


def _check_floors(doc_id, cand_result, spec, failures, label,
                  env_fingerprint=None):
    """Numeric bounds on a waived document, in both directions.

    Applies to expected divergences as well as accepted shortfalls. They were
    unbounded: a document listed under `expected_divergence` was excused from the
    comparison entirely and forever, so `c5_graphics` could have lost every
    remaining metric and still reported "expected-div". A waiver names a *known*
    difference; it cannot also be a licence for unknown ones.

    Full-profile binding is checked before adjudication starts. A mismatch is a
    hard failure, so this function never receives floors measured for a different
    backend/output-profile/oracle/refinement/DPI combination.
    """
    floors = spec.get("floors")
    if floors is None:
        failures.append(("unrecorded", doc_id,
                         "%s with no numeric floors -- record them with "
                         "--update-policy on the canonical environment. An "
                         "unbounded waiver is a waiver of anything" % label))
        return

    # A floor that does not name the environment it was measured under cannot be
    # detected as describing a different one. That is not hypothetical: three
    # `c4_i18n` floors survived scripts/fonts.conf pinning the visible font set
    # and then failed CI as though the backend had regressed, because nothing in
    # the file recorded which font environment produced them.
    recorded_fp = spec.get("environment_fingerprint")
    if not recorded_fp:
        failures.append(("unbound", doc_id,
                         "%s floors name no environment_fingerprint, so a "
                         "changed toolchain cannot be told from a regression. "
                         "Remeasure with --update-policy on the canonical "
                         "environment" % label))
    elif env_fingerprint and recorded_fp != env_fingerprint:
        failures.append(("environment-mismatch", doc_id,
                         "%s floors were measured under environment %s and this "
                         "run is %s. These numbers do not describe this "
                         "environment; remeasure rather than compare"
                         % (label, recorded_fp[:16], env_fingerprint[:16])))
    cd = dims(cand_result)
    for name, floor in sorted(_clean(floors).items()):
        v = cd.get(name)
        if v is None:
            failures.append(("no-metric", doc_id,
                             "%s is bounded on %s but the candidate did not "
                             "produce it" % (label, name)))
            continue
        tol = gate.tolerance(gate.METRICS.get(name, {}), floor)
        bad = (v > floor + tol) if name in LOWER_IS_BETTER else (v < floor - tol)
        if bad:
            failures.append(("below-floor", doc_id,
                             "%s %.4g against the %s floor of %.4g"
                             % (name, v, label, floor)))


def _policy_profile_errors(policy, profile_id):
    """Why `policy` cannot govern `profile_id`; empty means fully bound."""
    if not isinstance(profile_id, str) or not PROFILE_ID_RE.match(profile_id):
        return ["selected conversion profile has no full profile ID: %r"
                % profile_id]
    recorded = policy.get("profile_id")
    if not recorded:
        legacy = policy.get("recorded_refine_rounds")
        return [
            "policy has no full profile_id%s; refine rounds alone do not bind "
            "backend, output profile, oracle and DPI. Use --measure to collect "
            "raw differences, then create and review a policy explicitly bound "
            "to this named profile; --update-policy does not migrate findings"
            % (" (legacy recorded_refine_rounds=%r)" % legacy
               if legacy is not None else "")]
    if recorded != profile_id:
        # Names the field, `profile_id`, and not merely the two values. Both
        # refusal messages in this function have to say which key is wrong,
        # because the reader's next act is to edit that key -- and
        # `test_committed_policy_cannot_govern_product_without_full_profile`
        # asserts the token is present, so dropping it is a red test rather
        # than a quietly less useful message.
        return [
            "policy profile_id is %r but this run selected %r. Use --measure "
            "for raw differences, then create and review a separately bound "
            "policy; --update-policy does not migrate findings"
            % (recorded, profile_id)]

    errors = []
    for section in ("provisional_shortfalls", "ratified_shortfalls",
                    "expected_divergence"):
        for doc_id, spec in _clean(policy.get(section, {})).items():
            bound = spec.get("profile_id")
            if bound != profile_id:
                errors.append(
                    "%s/%s floors are bound to %r, expected %r"
                    % (section, doc_id, bound, profile_id))
    return errors


def _profile_failure_summary(errors, subset=False):
    counts = {"regressions": 0, "same": 0, "better": 0,
              "expected_div": 0, "provisional": 0, "ratified": 0,
              "accepted": 0, "missing": 0}
    failures = [{"kind": "profile-mismatch", "document": "-", "detail": e}
                for e in errors]
    return dict(counts, ok=False, subset=subset, release_ready=False,
                provisional_documents=[], failure_kinds=["profile-mismatch"],
                failures=failures)


def _measurement_summary(summary, profile_errors):
    """Mark raw comparison output as diagnostic and never authoritative."""
    summary = dict(summary)
    failures = list(summary.get("failures") or [])
    failures.extend({"kind": "profile-mismatch", "document": "-",
                     "detail": error}
                    for error in profile_errors)
    failures.append({
        "kind": "unadjudicated", "document": "-",
        "detail": "measurement mode did not apply policy waivers or floors; "
                  "these raw differences cannot authorise a release"})
    summary.update({
        "ok": False,
        "release_ready": False,
        "measurement_only": True,
        "policy_profile_errors": list(profile_errors),
        "failure_kinds": sorted(set(summary.get("failure_kinds") or [])
                                | {f["kind"] for f in failures}),
        "failures": failures,
    })
    return summary


def adjudicate(ref, cand, policy, subset=False, manifest=None, profile_id=None,
               env_fingerprint=None):
    """Apply the policy. -> (rows, summary dict).

    Coverage is anchored on the **manifest**, not on the intersection of what the
    two runs happened to produce. Comparing `set(ref)` with `set(cand)` alone is
    satisfied by two runs that both dropped the same document -- which is exactly
    what happened when a conversion failed under both backends.

    `profile_id` is the complete named conversion profile used by both runs before
    their backend field is replaced. A missing or different policy binding returns
    immediately with `profile-mismatch`; no profile-specific waiver is applied.
    """
    profile_errors = _policy_profile_errors(policy, profile_id)
    if profile_errors:
        return [], _profile_failure_summary(profile_errors, subset=subset)

    margins = _clean(policy.get("margins", {}))
    dy_exemption, dy_errors = dy_exemption_for(policy, profile_id)
    divergence = _clean(policy.get("expected_divergence", {}))
    provisional = _clean(policy.get("provisional_shortfalls", {}))
    ratified = _clean(policy.get("ratified_shortfalls", {}))
    rows, failures = [], []
    counts = {"regressions": 0, "same": 0, "better": 0, "expected_div": 0,
              "provisional": 0, "ratified": 0, "accepted": 0, "missing": 0}
    for detail in dy_errors:
        failures.append(("malformed-exemption", "-", detail))

    # The retired section. Schema 1 called all four D2 documents
    # `accepted_shortfalls`, and its own note called them RATIFIED, while every
    # prose document called them provisional -- so the executable rule and the
    # written rule disagreed about whether a release was authorised. Migrating is
    # a deliberate act, not something to infer, so an unmigrated file is refused
    # rather than guessed at.
    retired = _clean(policy.get("accepted_shortfalls", {}))
    if retired:
        failures.append(("policy-unmigrated", "-",
                         "policy still uses the retired `accepted_shortfalls` "
                         "section for %d document(s): %s. Move each to "
                         "`provisional_shortfalls` (visible, release-blocking) or "
                         "`ratified_shortfalls` (named owner, date, issue, review "
                         "condition). 'Accepted' did not say which, and that "
                         "ambiguity is what let four documents read as ratified."
                         % (len(retired), ", ".join(sorted(retired)))))
    expected_ids = set(manifest.get("documents", {})) if manifest else None
    universe = set(ref) | set(cand)
    if expected_ids is not None:
        for missing in sorted(expected_ids - universe):
            failures.append(("missing", missing,
                             "in the corpus manifest and measured under neither "
                             "backend -- a document that fails on both sides "
                             "disappears from an intersection but not from here"))
            rows.append({"document": missing, "verdict": "MISSING"})
            counts["missing"] += 1
        for extra in sorted(universe - expected_ids):
            failures.append(("unexpected", extra,
                             "compared but not in the corpus manifest"))
        universe = universe | expected_ids

    for doc_id in sorted(universe):
        if expected_ids is not None and doc_id not in expected_ids:
            continue                                  # already reported
        A, B = ref.get(doc_id), cand.get(doc_id)
        if A is None and B is None:
            continue                                  # already reported missing
        broken = []
        for side, r in (("reference", A), ("candidate", B)):
            if r is None:
                broken.append("%s did not produce a result" % side)
            else:
                fatal = [k for k in gate.FATAL_KEYS if k in r]
                if fatal:
                    broken.append("%s %s: %s"
                                  % (side, fatal[0], str(r[fatal[0]])[:80]))
        if broken:
            counts["missing"] += 1
            failures.append(("unmeasurable", doc_id, "; ".join(broken)))
            rows.append({"document": doc_id, "verdict": "MISSING",
                         "detail": "; ".join(broken)})
            continue

        worse, better = compare(A, B, margins)
        worse, dy_exempted = apply_dy_exemption(worse, dims(A), dims(B),
                                                dy_exemption)
        row = {"document": doc_id, "reference": dims(A), "candidate": dims(B),
               "worse": [w[0] for w in worse], "better": [b[0] for b in better]}
        if dy_exempted:
            # Recorded on the row, never silent. An exemption that does not show
            # up in the output is indistinguishable from a document that never
            # moved, and the two need to be told apart by a reader.
            row["dy_exempt"] = True

        if doc_id in divergence:
            row["verdict"] = "expected-div"
            counts["expected_div"] += 1
            spec = divergence[doc_id]
            if not spec.get("verified"):
                failures.append(("undocumented", doc_id,
                                 "expected divergence with no rendered evidence"))
            _check_floors(doc_id, B, spec, failures, "expected divergence",
                          env_fingerprint=env_fingerprint)
            if not worse and not better:
                # The waiver says these two backends disagree here on purpose. If
                # they now agree on every dimension, it describes nothing -- and
                # it is still excusing the document from the comparison, so the
                # next real divergence on it would pass unremarked.
                failures.append(("stale", doc_id,
                                 "waived as an expected divergence, but the two "
                                 "backends no longer differ on any dimension"))
        elif doc_id in provisional or doc_id in ratified:
            is_prov = doc_id in provisional
            spec = provisional[doc_id] if is_prov else ratified[doc_id]
            label = "provisional shortfall" if is_prov else "ratified shortfall"
            row["verdict"] = "provisional" if is_prov else "ratified"
            row["defect"] = spec.get("defect")
            counts["provisional" if is_prov else "ratified"] += 1
            counts["accepted"] += 1        # the union, for output compatibility
            if not spec.get("defect"):
                failures.append(("undocumented", doc_id,
                                 "%s with no defect ID" % label))
            _check_floors(doc_id, B, spec, failures, label,
                          env_fingerprint=env_fingerprint)
            if not worse:
                failures.append(("stale", doc_id,
                                 "%s recorded as worse, but no dimension is "
                                 "worse any more. A stale waiver hides the next "
                                 "real regression on this document" % label))
            if is_prov:
                # Rule 4: provisional findings never count as a pass. Visible,
                # bounded and attributed is not the same as authorised, and the
                # difference has to be in the exit code or it is not a rule.
                failures.append(("provisional", doc_id,
                                 "shortfall is PROVISIONAL and cannot authorise a "
                                 "backend swap or a release. Fix it, or ratify it "
                                 "with a named owner, date, issue and review "
                                 "condition."))
            else:
                # A ratification is a person taking responsibility on a date, with
                # a way to revisit it. Without those it is an unbounded waiver
                # wearing the word "ratified", which is the exact failure this
                # section was split to prevent.
                missing = [k for k in ("ratified_by", "ratified_on", "issue",
                                       "review_condition")
                           if not spec.get(k)]
                if missing:
                    failures.append(("unratified", doc_id,
                                     "in `ratified_shortfalls` but missing %s. A "
                                     "ratification needs a named owner and a way "
                                     "to expire." % ", ".join(missing)))
        elif worse:
            row["verdict"] = "REGRESSION"
            counts["regressions"] += 1
            for name, a_v, b_v in worse:
                failures.append(("regression", doc_id,
                                 "worse on %s: %s -> %s"
                                 % (name,
                                    "n/a" if a_v is None else "%.4g" % a_v,
                                    "n/a" if b_v is None else "%.4g" % b_v)))
        elif better:
            row["verdict"] = "BETTER"
            counts["better"] += 1
        else:
            row["verdict"] = "same"
            counts["same"] += 1
        rows.append(row)

    ok = not failures and not subset
    summary = dict(counts)
    kinds = {k for k, _, _ in failures}
    summary.update({"ok": ok, "subset": subset,
                    # Explicit, not inferred from `ok`. A reader asking "may this
                    # authorise the licence swap?" should not have to reconstruct
                    # the answer from a failure list, and a provisional entry is
                    # exactly the case where "no regressions" and "release-ready"
                    # come apart.
                    "release_ready": bool(ok and not counts["provisional"]
                                          and not subset),
                    "provisional_documents": sorted(
                        d for k, d, _ in failures if k == "provisional"),
                    "failure_kinds": sorted(kinds),
                    "failures": [{"kind": k, "document": d, "detail": v}
                                 for k, d, v in failures]})
    return rows, summary


def corpus_identity(manifest):
    """A digest of WHICH 16 documents these floors were measured over.

    Derived from the per-document input hashes rather than from the manifest
    file's bytes, so reordering keys or editing a `why` note does not read as a
    different corpus -- while replacing a single input does. The corpus was never
    byte-reproducible (ReportLab and Chromium stamp a creation time into every
    file), so the inputs' own recorded hashes are the only stable identity
    available.
    """
    import hashlib
    docs = (manifest or {}).get("documents") or {}
    parts = []
    for doc_id in sorted(k for k in docs if not k.startswith("_")):
        entry = docs[doc_id] or {}
        parts.append("%s:%s" % (doc_id, entry.get("sha256")))
    if not parts:
        return None
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def record_policy(ref, cand, policy, manifest, environment, profile_id,
                  path=POLICY_PATH):
    """Write measured floors for every waived document. Full corpus only.

    Same preconditions as the gate baseline, for the same reason: this file
    decides whether the licence swap is acceptable, and a subset run
    (`--only c7_code`) recording floors would silently re-bound the two or four
    documents it happened to touch using numbers from a corpus of one. Refused
    rather than warned about.
    """
    if not isinstance(profile_id, str) or not PROFILE_ID_RE.match(profile_id):
        raise gate.RecordRefused(
            "refusing to record parity floors without a full conversion "
            "profile ID, got %r" % profile_id)
    profile_errors = _policy_profile_errors(policy, profile_id)
    if profile_errors:
        raise gate.RecordRefused(
            "refusing to migrate parity findings between profiles: %s. "
            "Measure the selected profile first, then create or review a "
            "policy already bound to that exact profile before recording."
            % " | ".join(profile_errors))
    if not environment.get("canonical"):
        raise gate.RecordRefused(
            "refusing to record parity floors on %s: the policy is the swap's "
            "acceptance rule and is measured on Linux (see gate.yml)."
            % environment.get("os", "this platform"))
    expected = set(manifest.get("documents", {}))
    for side, got in (("reference", set(ref)), ("candidate", set(cand))):
        if got != expected:
            raise gate.RecordRefused(
                "refusing to record parity floors: the %s run covered %d of %d "
                "manifest documents (missing %s). Floors recorded from a partial "
                "run bound the corpus that was not measured."
                % (side, len(got), len(expected), sorted(expected - got) or "none"))
    for r, side in ((ref, "reference"), (cand, "candidate")):
        broken = sorted(d for d, x in r.items()
                        if any(k in x for k in gate.FATAL_KEYS))
        if broken:
            raise gate.RecordRefused(
                "refusing to record parity floors: %s failed on %s. Half a run "
                "is not a run." % (side, ", ".join(broken)))

    n = 0
    policy.pop("recorded_refine_rounds", None)
    policy["profile_id"] = profile_id
    policy["schema"] = 3
    # Every floor is bound to the exact conditions that produced it. Schema 1
    # recorded `os: linux` plus three version strings, which is why three stale
    # `c4_i18n` floors survived a font-environment change and failed CI as though
    # the backend had regressed: a floor that does not name its environment cannot
    # be detected as describing a different one.
    binding = {
        "profile_id": profile_id,
        "environment_fingerprint": environment.get("fingerprint"),
        "corpus_manifest_sha256": corpus_identity(manifest),
        "measured_commit": (evidence.git_state() or {}).get("commit"),
    }
    for section in ("provisional_shortfalls", "ratified_shortfalls",
                    "expected_divergence"):
        for doc_id, spec in policy.get(section, {}).items():
            if doc_id.startswith("_") or doc_id not in cand:
                continue
            spec["floors"] = {k: round(v, 4) for k, v in dims(cand[doc_id]).items()}
            spec["reference_at_record"] = {k: round(v, 4)
                                           for k, v in dims(ref[doc_id]).items()}
            spec["recorded_on"] = {
                "os": environment.get("os"),
                "python": environment.get("python"),
                "soffice": (environment.get("oracles") or {}).get("soffice_version"),
                "pdfium": (environment.get("dependencies") or {}).get("pdfium"),
                "pymupdf": (environment.get("dependencies") or {}).get("pymupdf"),
                "fonts_conf_sha256": (environment.get("fonts_conf") or {})
                                     .get("repo_sha256"),
                "font_files_digest": (environment.get("font_files") or {})
                                     .get("digest"),
            }
            spec.update(binding)
            n += 1

    import tempfile
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".parity_policy.", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(policy, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    print("recorded floors for %d waived document(s) in %s" % (n, path))


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", choices=PROFILE_NAMES,
                    default="candidate",
                    help="complete conversion profile used by both backends "
                         "(default: %(default)s)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", nargs="+", default=None,
                    help="substrings; run only the matching documents")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--update-policy", action="store_true",
                      help="re-record a policy already bound to the selected "
                           "full profile")
    mode.add_argument("--measure", action="store_true",
                      help="compare both backends without applying or writing "
                           "policy; always unadjudicated and nonzero")
    ap.add_argument("--policy", default=POLICY_PATH,
                    help="policy JSON to read or update (default: %(default)s)")
    ap.add_argument("--evidence", default=None,
                    help="evidence JSON to merge the parity verdict into")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)

    profile = conversion_profile(a.profile)
    profile_id = profile.profile_id()
    policy = load_policy(a.policy)
    profile_errors = _policy_profile_errors(policy, profile_id)
    if profile_errors and not a.measure:
        heading = "POLICY NOT RECORDED" if a.update_policy \
            else "POLICY PROFILE MISMATCH"
        print(heading)
        for error in profile_errors:
            print("  - %s" % error)
        if a.update_policy:
            print("Refusing to migrate existing findings to another profile.")
        else:
            print("Refusing to compare or apply floors from another profile. "
                  "Use --measure for a non-authoritative raw comparison.")
        return 2

    manifest = gate.load_manifest()
    if manifest is None:
        print("no corpus manifest -- parity cannot know which documents it "
              "should have compared")
        return 2
    srcs, problems = runall.resolve_corpus(manifest)
    for kind, doc, why in problems:
        print("CORPUS %-11s %-28s %s" % (kind, doc[:28], why))
    if not srcs:
        print("no corpus; run the generators first")
        return 2

    subset = False
    if a.only:
        if a.update_policy:
            print("--only cannot be combined with --update-policy: floors "
                  "recorded from a subset would bound documents the run never "
                  "measured.")
            return 2
        srcs = [s for s in srcs if any(k in os.path.basename(s) for k in a.only)]
        if not srcs:
            print("--only matched no document")
            return 2
        subset = True
        print("subset run: %s -- this cannot report the swap as acceptable, "
              "only the full corpus can"
              % ", ".join(os.path.basename(s) for s in srcs))

    out_root = os.path.join(a.out or os.path.join(ROOT, "parity"), a.profile)
    ref_name = policy.get("reference_backend", "pymupdf")
    cand_name = policy.get("candidate_backend", "pdfium")
    print("reference %s vs candidate %s, profile %s, %d document(s)"
          % (ref_name, cand_name, profile_id, len(srcs)))

    env = evidence.environment()
    ref = run(ref_name, srcs, out_root, profile)
    cand = run(cand_name, srcs, out_root, profile)

    if a.update_policy:
        try:
            record_policy(ref, cand, policy, manifest, env,
                          profile_id=profile_id, path=a.policy)
        except gate.RecordRefused as e:
            print("\nPOLICY NOT RECORDED\n  %s" % e)
            return 2
        policy = load_policy(a.policy)

    comparison_policy = policy
    if a.measure:
        # No inherited waivers, provisional findings or floors. Empty margins
        # make every raw movement visible; the summary is forcibly marked
        # unadjudicated below even when no regression is observed.
        comparison_policy = {"profile_id": profile_id, "margins": {}}
    rows, summary = adjudicate(ref, cand, comparison_policy, subset=subset,
                               manifest=None if subset else manifest,
                               profile_id=profile_id,
                               env_fingerprint=env.get("fingerprint"))
    if a.measure:
        summary = _measurement_summary(summary, profile_errors)
    print("\n%-22s %-22s %-22s %s"
          % ("document", ref_name, cand_name, "verdict"))
    for row in rows:
        if row["verdict"] == "MISSING":
            print("%-22s %-45s %s"
                  % (row["document"][:22], row.get("detail", "-")[:45], "MISSING"))
            continue
        r, c = row["reference"], row["candidate"]
        fmt = "pg%+d l%.2f p%.2f w%.2f"
        print("%-22s %-22s %-22s %s%s"
              % (row["document"][:22],
                 fmt % (r["page_err"], r["live_text_cov"], r["word_recall"],
                        r["within2pt"]),
                 fmt % (c["page_err"], c["live_text_cov"], c["word_recall"],
                        c["within2pt"]),
                 row["verdict"],
                 # Both lists, always: a document can be worse on one dimension
                 # and better on another, and hiding either is how a regression
                 # got suppressed by an improvement ordered above it.
                 ("  worse:%s" % ",".join(row["worse"])) if row.get("worse") else ""
                 + ("  better:%s" % ",".join(row["better"])) if row.get("better")
                 else ""))

    print("\n%d regression(s), %d same, %d better, %d expected-divergence, "
          "%d accepted, %d missing"
          % (summary["regressions"], summary["same"], summary["better"],
             summary["expected_div"], summary["accepted"], summary["missing"]))
    for f in summary["failures"]:
        print("  %-13s %-28s %s" % (f["kind"], f["document"][:28], f["detail"]))
    if subset:
        print("subset run: exit code reports findings among what it ran, and "
              "cannot report the swap as acceptable")
    if a.measure:
        print("UNADJUDICATED MEASUREMENT -- never release-ready")
    else:
        print("PASS" if summary["ok"] else "FAIL")

    ev_path = a.evidence or os.path.join(ROOT, "batch", "evidence.json")
    parity = dict(summary)
    parity.update({"reference_backend": ref_name, "candidate_backend": cand_name,
                   "profile": a.profile, "profile_id": profile_id,
                   "documents": rows,
                   "manifest_documents": len(manifest.get("documents", {}))})
    parity.update(profile_labels(profile, ref_name, cand_name))
    evidence.merge(ev_path, parity=parity)

    if a.update_policy:
        return 0
    if a.measure:
        return 2
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
