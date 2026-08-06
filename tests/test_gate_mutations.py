"""Mutation tests: every way the gate used to report a false green must be red.

A gate is a claim about what cannot get past it, and this project has already
paid twice for believing such a claim unverified -- once when the parity harness
omitted `within2pt` and reported 0 regressions on a swap that cost 0.510 -> 0.291,
and once when a gate that could not run at all (an undeclared `pypdfium2`) looked
exactly like a gate that passed.

So each test below starts from a *healthy* result set, breaks exactly one thing,
and asserts the verdict turns red for the expected reason. If a check is ever
weakened or deleted, one of these fails. They need no corpus, no LibreOffice and
no PDF: the decision under test is a pure function of already-measured numbers,
which is the reason it was extracted into `testkit/gate.py` in the first place.

    python tests/test_gate_mutations.py
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "testkit"))

import gate  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print("  %-4s %s%s" % ("ok" if cond else "FAIL", name,
                           "" if cond else "   <-- " + detail))
    if not cond:
        FAILED.append(name)


# ------------------------------------------------------------------- fixtures
# Two documents is enough to exercise every rule, and small enough that a
# failure names the cause instead of requiring a bisect. `good` passes every
# threshold; `known` is a recorded shortfall carrying a defect ID, modelled on
# 04_exec_brief, whose live-text coverage has never reached 0.95.
def result(src, pages=(3, 3), live=0.99, doc=0.99, word=0.97, w2=0.60,
           dy=0.50, raster=0.01):
    return {"src": src, "src_pages": pages[0], "out_pages": pages[1],
            "page_match": pages[0] == pages[1], "live_text_cov": live,
            "doc_recall": doc, "word_recall": word, "within2pt": w2,
            "dy_p50": dy, "dy_p90": dy * 3, "raster_frac": raster,
            "mean_ssim": 0.80, "mean_iou": 0.70, "renderer": "libreoffice",
            "src_words": 900, "n_media": 0}


def healthy():
    return [result("good.pdf"),
            result("known.pdf", live=0.941, doc=0.944)]


MANIFEST = {"documents": {"good.pdf": {"path": "corpus/pdfs", "src_pages": 3},
                          "known.pdf": {"path": "corpus/pdfs", "src_pages": 3}}}


def baseline_for(results):
    rec = gate.record("product", results)
    rec["shortfall_defects"] = {"known.pdf": "D-test"}
    return rec


def verdict(results, baseline=None, manifest=None, absolute=False):
    return gate.check("product", results,
                      manifest=manifest if manifest is not None else MANIFEST,
                      baseline=baseline if baseline is not None
                      else baseline_for(healthy()),
                      absolute=absolute)


def kinds(v):
    return set(v.kinds())


# ----------------------------------------------------------------------- tests
def test_healthy_passes():
    v = verdict(healthy())
    check("a healthy lane passes", v.ok, v.report())


def test_removed_document():
    """`gen_corpus.py` exits 0 after skipping 8 of 16 documents."""
    r = [x for x in healthy() if x["src"] != "known.pdf"]
    v = verdict(r)
    check("removing a corpus document fails", "missing" in kinds(v), v.report())


def test_unexpected_document():
    r = healthy() + [result("stranger.pdf")]
    v = verdict(r)
    check("an unmanifested document fails", "unexpected" in kinds(v), v.report())


def test_duplicate_document():
    """Two inputs with one basename overwrite each other's output and row."""
    r = healthy() + [result("good.pdf", w2=0.10)]
    v = verdict(r)
    check("a duplicated document fails", "duplicate" in kinds(v), v.report())


def test_identity_change():
    """A generator change that alters a document re-bases every number."""
    r = healthy()
    r[0]["src_pages"] = 4
    r[0]["out_pages"] = 4
    v = verdict(r)
    check("a changed source page count fails", "identity" in kinds(v), v.report())


def test_render_error():
    """harness.evaluate() returns {'error': ...}; nothing used to look."""
    r = healthy()
    r[0] = {"src": "good.pdf", "error": "LibreOffice produced no PDF",
            "live_text_cov": 0.99}
    v = verdict(r)
    check("a render error fails", "error" in kinds(v), v.report())


def test_convert_error():
    r = healthy()
    r[0] = {"src": "good.pdf", "convert_error": "ValueError: document closed"}
    v = verdict(r)
    check("a conversion error fails", "error" in kinds(v), v.report())


def test_missing_metric():
    """An absent metric used to be skipped: `if v is None: continue`."""
    for metric in ("within2pt", "dy_p50", "live_text_cov", "word_recall"):
        r = healthy()
        del r[0][metric]
        v = verdict(r)
        check("deleting %s fails" % metric,
              "no-metric" in kinds(v) or "unrecorded" in kinds(v), v.report())


def test_known_failure_sliding_further():
    """The old baseline stored metric NAMES: 0.941 could fall to 0.10 unseen."""
    r = healthy()
    r[1]["live_text_cov"] = 0.10
    v = verdict(r)
    check("a known failure sliding to 0.10 fails", "regression" in kinds(v),
          v.report())


def test_known_failure_inside_tolerance():
    r = healthy()
    r[1]["live_text_cov"] = 0.941 - gate.METRICS["live_text_cov"]["tol"] / 2
    v = verdict(r)
    check("a known failure inside tolerance still passes", v.ok, v.report())


def test_page_error_magnitude():
    """page_match is a boolean: 1 page over and 40 over looked identical."""
    base = healthy()
    base[1]["out_pages"] = 4                      # already failing page_err
    bl = baseline_for(base)
    bl["shortfall_defects"] = {"known.pdf": "D-test"}
    worse = copy.deepcopy(base)
    worse[1]["out_pages"] = 40
    v = gate.check("product", worse, manifest=MANIFEST, baseline=bl)
    check("a page error growing 1 -> 37 fails", "regression" in kinds(v),
          v.report())


def test_stale_record():
    """A recorded shortfall that now passes silently re-admits the regression."""
    r = healthy()
    r[1]["live_text_cov"] = 0.97
    r[1]["doc_recall"] = 0.98
    v = verdict(r)
    check("a stale record fails", "stale" in kinds(v), v.report())


def test_undocumented_shortfall():
    """A recorded shortfall with no defect ID is an unexplained number."""
    bl = gate.record("product", healthy())        # no shortfall_defects
    v = verdict(healthy(), baseline=bl)
    check("a shortfall with no defect ID fails", "undocumented" in kinds(v),
          v.report())


def test_new_threshold_failure():
    r = healthy()
    r[0]["word_recall"] = 0.50
    v = verdict(r)
    check("a new threshold failure fails",
          "threshold" in kinds(v) and "regression" in kinds(v), v.report())


def test_unrecorded_document():
    bl = gate.record("product", [healthy()[0]])
    bl["shortfall_defects"] = {"known.pdf": "D-test"}
    v = verdict(healthy(), baseline=bl)
    check("a document with no numeric baseline fails",
          "unrecorded" in kinds(v), v.report())


def test_unrecorded_metric():
    bl = baseline_for(healthy())
    del bl["documents"]["good.pdf"]["within2pt"]
    v = verdict(healthy(), baseline=bl)
    check("a metric with no recorded value fails", "unrecorded" in kinds(v),
          v.report())


def test_aggregate_regression():
    """Per-document moves can each stay in tolerance and still move the mean."""
    bl = baseline_for(healthy())
    r = healthy()
    for x in r:
        x["within2pt"] -= 0.045                   # under the per-doc tolerance
    v = gate.check("product", r, manifest=MANIFEST, baseline=bl)
    check("an aggregate-only regression fails", "regression" in kinds(v),
          v.report())


def test_absolute_mode_flags_known_shortfall():
    v = verdict(healthy(), absolute=True)
    check("release mode refuses a known shortfall",
          "unqualified" in kinds(v), v.report())
    check("regression mode accepts the same shortfall", verdict(healthy()).ok)


def test_both_lanes_gate():
    """The runner exit code must require both current named lanes."""
    import runall
    src = open(runall.__file__).read()
    check("the runner gates on every lane it ran",
          "all(v.ok for v in verdicts.values())" in src,
          "runall.main() must not return one lane's status")


def test_shipped_default_is_the_measured_default():
    """The API, the CLI and the product lane must be one configuration."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    from exactdoc.cli import build_parser
    from exactdoc.options import LANES, PRODUCT, RAW, validate_lanes
    defaults = {a.dest: a.default for a in build_parser()._actions}
    check("CLI refine default == PRODUCT",
          defaults["refine"] == PRODUCT.refine_rounds,
          "CLI %r vs profile %r" % (defaults["refine"], PRODUCT.refine_rounds))
    check("CLI output_profile default == PRODUCT",
          defaults["output_profile"] == PRODUCT.output_profile,
          "CLI %r vs profile %r" % (defaults.get("output_profile"),
                                    PRODUCT.output_profile))
    check("CLI oracle default == PRODUCT",
          defaults["oracle"] == PRODUCT.oracle,
          "CLI %r vs profile %r" % (defaults.get("oracle"), PRODUCT.oracle))
    check("CLI backend default == PRODUCT", defaults["backend"] == PRODUCT.backend)
    check("CLI dpi default == PRODUCT", defaults["dpi"] == PRODUCT.dpi)
    # Consent is off unless asked for, and cannot be defaulted on by a profile.
    check("CLI does not default to allowing a cloud upload",
          defaults["allow_cloud_upload"] is False,
          repr(defaults.get("allow_cloud_upload")))
    # The deprecated flag must default to "unset" rather than to a real value,
    # or it would silently outrank the new pair on every invocation.
    check("CLI --target defaults to unset", defaults["target"] is None,
          repr(defaults.get("target")))
    check("the product lane is the shipped profile",
          LANES["product"] is PRODUCT)
    # Pinned to the exact shipped profile, deliberately: this assertion exists
    # so that changing what ships is a decision somebody makes here rather than
    # a side effect somewhere else. It said `pymupdf/...` until 2026-08-06, when
    # the parser default flipped to PDFium and this string was not updated with
    # it -- so the whole mutation suite went red and stayed red through the 1.0.0
    # release, which is the one state a guard-rail suite must never be in, since
    # a suite nobody can run green is a suite nobody reads.
    check("the shipping profile is the measured quality-first profile",
          PRODUCT.profile_id()
          == "pdfium/standard/libreoffice/refine3@240dpi",
          PRODUCT.profile_id())
    check("the gate exposes exactly raw and product",
          set(LANES) == {"raw", "product"}, repr(LANES))
    check("lane profile IDs are unique",
          len({p.profile_id() for p in LANES.values()}) == len(LANES),
          repr({name: p.profile_id() for name, p in LANES.items()}))
    check("raw is the open-loop control for the shipping profile",
          LANES["raw"] is RAW
          and RAW.backend == PRODUCT.backend
          and RAW.output_profile == PRODUCT.output_profile
          and RAW.oracle == "none"
          and RAW.refine_rounds == 0)
    check("the active lane contract validates", validate_lanes() is True)
    try:
        validate_lanes({"raw": PRODUCT, "product": PRODUCT})
        check("collapsed lane profiles are rejected", False)
    except Exception:
        check("collapsed lane profiles are rejected", True)


# ------------------------------------------------------- the parity policy
# `backend_parity.adjudicate()` is pure for the same reason `gate.check()` is,
# and it needs the same treatment: the policy it applies used to live in a
# docstring while the code exited on a different rule entirely.
PARITY_FP = "f" * 64          # the environment the fixture's floors were measured under
PARITY_PROFILE_ID = "pdfium/gdocs/libreoffice/refine3@240dpi"


def _binding(**over):
    """The four fields every floor must name, per DET-02.

    A floor that does not say which environment, corpus and commit produced it
    cannot be told apart from a regression when one of those changes -- which is
    not hypothetical: three `c4_i18n` floors survived scripts/fonts.conf pinning
    the font set and then failed CI as though the backend had moved.
    """
    b = {"environment_fingerprint": PARITY_FP,
         "corpus_manifest_sha256": "c" * 64,
         "measured_commit": "d" * 40,
         "profile_id": PARITY_PROFILE_ID}
    b.update(over)
    return b


def _ratification(**over):
    """What makes a shortfall ratified rather than merely visible: a person, a
    date, an issue, and a condition under which it is revisited."""
    r = {"ratified_by": "test owner", "ratified_on": "2026-07-30",
         "issue": "https://example.invalid/1",
         "review_condition": "revisit at the Google Docs checkpoint"}
    r.update(over)
    return r


def parity_fixture():
    """Reference and candidate results, plus a policy that waives two docs."""
    # `diverges.pdf` must differ by MORE than the margin, or it is not a
    # divergence at all -- which the stale check now says out loud.
    ref = {"good.pdf": result("good.pdf", w2=0.60),
           "accepted.pdf": result("accepted.pdf", w2=0.72),
           "diverges.pdf": result("diverges.pdf", live=0.71, doc=0.71)}
    cand = {"good.pdf": result("good.pdf", w2=0.60),
            "accepted.pdf": result("accepted.pdf", w2=0.53),
            "diverges.pdf": result("diverges.pdf", live=0.60, doc=0.60)}
    bounds = {"page_err": 0, "live_text_cov": 0.55, "doc_recall": 0.55,
              "word_recall": 0.60, "within2pt": 0.10, "dy_p50": 1.0,
              "raster_frac": 0.40}
    policy = {
        "reference_backend": "pymupdf", "candidate_backend": "pdfium",
        "profile_id": PARITY_PROFILE_ID,
        "margins": {"page_err": 0, "live_text_cov": 0.05, "doc_recall": 0.05,
                    "word_recall": 0.05, "within2pt": 0.08, "dy_p50": 0.5,
                    "raster_frac": 0.02},
        "expected_divergence": {"diverges.pdf": dict(
            _binding(),
            reason="verified visually", verified="rendered side by side",
            floors=dict(bounds))},
        # Ratified, not merely "accepted": the fixture's healthy case has to be a
        # state that can actually authorise a swap, and after DET-02 that means
        # carrying an owner and an expiry.
        "ratified_shortfalls": {"accepted.pdf": dict(
            _binding(), **_ratification(),
            defect="D2",
            floors=dict(bounds, within2pt=0.53, live_text_cov=0.99,
                        doc_recall=0.99, word_recall=0.97))},
    }
    return ref, cand, policy


PARITY_MANIFEST = {"documents": {"good.pdf": {}, "accepted.pdf": {},
                                 "diverges.pdf": {}}}


def parity_kinds(ref, cand, policy, subset=False, manifest=PARITY_MANIFEST,
                 env_fingerprint=PARITY_FP):
    import backend_parity
    _, summary = backend_parity.adjudicate(
        ref, cand, policy, subset=subset,
        manifest=None if subset else manifest,
        profile_id=PARITY_PROFILE_ID,
        env_fingerprint=env_fingerprint)
    return summary, set(f["kind"] for f in summary["failures"])


def test_parity_uses_named_complete_profiles():
    import backend_parity
    import inspect
    from exactdoc.options import (PDFIUM_GDOCS_CANDIDATE,
                                  PDFIUM_GDOCS_CANDIDATE_REFINED, PRODUCT)
    parser = backend_parity.build_parser()
    check("parity defaults to the candidate profile",
          parser.parse_args([]).profile == "candidate")
    check("the parity names resolve to canonical full profiles",
          backend_parity.conversion_profile("product") is PRODUCT
          and backend_parity.conversion_profile("candidate")
          is PDFIUM_GDOCS_CANDIDATE
          and backend_parity.conversion_profile("candidate-refined")
          is PDFIUM_GDOCS_CANDIDATE_REFINED)
    body = inspect.getsource(backend_parity.run)
    check("parity changes only backend on the selected profile",
          "profile.replace(backend=backend)" in body
          and "refine_rounds=" not in body, body[:600])


def test_parity_healthy_passes():
    ref, cand, policy = parity_fixture()
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("the ratified policy passes", summary["ok"], str(summary["failures"]))
    check("a ratified policy is release-ready", summary["release_ready"],
          str(summary))
    check("the ratified shortfall is not counted a regression",
          summary["regressions"] == 0, str(summary))
    check("the expected divergence is not counted a regression",
          summary["expected_div"] == 1, str(summary))


def test_parity_accepted_shortfall_worsening():
    """An unbounded acceptance is an acceptance of anything."""
    ref, cand, policy = parity_fixture()
    cand["accepted.pdf"]["within2pt"] = 0.20
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a ratified shortfall falling past its floor fails",
          "below-floor" in kinds_, str(summary["failures"]))


def test_parity_stale_acceptance():
    """A document accepted as worse that is no longer worse hides the next one."""
    ref, cand, policy = parity_fixture()
    cand["accepted.pdf"]["within2pt"] = 0.72
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a stale acceptance fails", "stale" in kinds_,
          str(summary["failures"]))


def test_parity_unbounded_acceptance():
    ref, cand, policy = parity_fixture()
    policy["ratified_shortfalls"]["accepted.pdf"]["floors"] = None
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("an acceptance with no numeric floors fails", "unrecorded" in kinds_,
          str(summary["failures"]))


# --- DET-02: the provisional state, and the identity a floor must carry -------
#
# Schema 1 had ONE waiver section whose own note called it RATIFIED while every
# prose document called the same four documents provisional. The executable rule
# and the written rule disagreed about whether a release was authorised, and the
# gate could not tell you which it meant. Each mutation below is one way that
# ambiguity used to pass.

def test_parity_provisional_cannot_authorise():
    """Rule 4: provisional findings never count as a pass."""
    ref, cand, policy = parity_fixture()
    spec = policy["ratified_shortfalls"].pop("accepted.pdf")
    for k in ("ratified_by", "ratified_on", "issue", "review_condition"):
        spec.pop(k)
    policy["provisional_shortfalls"] = {"accepted.pdf": spec}
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a provisional shortfall is counted provisional",
          summary["provisional"] == 1, str(summary))
    check("a provisional shortfall does not pass", not summary["ok"],
          str(summary["failures"]))
    check("a provisional shortfall is not release-ready",
          not summary["release_ready"], str(summary))
    check("a provisional shortfall is NOT reported as a regression",
          summary["regressions"] == 0, str(summary))
    check("the provisional document is named",
          summary["provisional_documents"] == ["accepted.pdf"], str(summary))


def test_parity_ratified_needs_an_owner():
    """"Ratified" without a person and a date is an unbounded waiver wearing the
    word. All four fields are required, and each is checked on its own."""
    for field in ("ratified_by", "ratified_on", "issue", "review_condition"):
        ref, cand, policy = parity_fixture()
        del policy["ratified_shortfalls"]["accepted.pdf"][field]
        summary, kinds_ = parity_kinds(ref, cand, policy)
        check("a ratification missing %s fails" % field,
              "unratified" in kinds_, str(summary["failures"]))


def test_parity_retired_section_is_refused():
    """The migration is deliberate, so an unmigrated file is refused rather than
    silently read as one state or the other."""
    ref, cand, policy = parity_fixture()
    policy["accepted_shortfalls"] = {
        "accepted.pdf": policy.pop("ratified_shortfalls")["accepted.pdf"]}
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("the retired accepted_shortfalls section fails",
          "policy-unmigrated" in kinds_, str(summary["failures"]))


def test_parity_floor_must_name_its_environment():
    ref, cand, policy = parity_fixture()
    policy["ratified_shortfalls"]["accepted.pdf"]["environment_fingerprint"] = None
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a floor naming no environment fails", "unbound" in kinds_,
          str(summary["failures"]))


def test_parity_floor_from_another_environment_is_refused():
    """The c4_i18n stale-floor failure, stated as logic: floors measured before
    the font set was pinned describe a different environment, and comparing them
    reported a regression that had not happened."""
    ref, cand, policy = parity_fixture()
    summary, kinds_ = parity_kinds(ref, cand, policy,
                                   env_fingerprint="9" * 64)
    check("a floor measured under another environment fails",
          "environment-mismatch" in kinds_, str(summary["failures"]))


def test_parity_new_regression():
    ref, cand, policy = parity_fixture()
    cand["good.pdf"]["within2pt"] = 0.20
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a new regression fails", "regression" in kinds_ and
          summary["regressions"] == 1, str(summary["failures"]))


def test_parity_missing_document():
    """One-sided absence. Reported as `unmeasurable`, which names the asymmetry;
    absence from *both* sides is `missing`, and the two are worth telling apart."""
    ref, cand, policy = parity_fixture()
    del cand["good.pdf"]
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a document scored under one backend only fails",
          not summary["ok"] and kinds_ & {"unmeasurable", "missing"},
          str(summary["failures"]))
    check("the failure names the document",
          any(f["document"] == "good.pdf" for f in summary["failures"]),
          str(summary["failures"]))


def test_parity_subset_cannot_pass():
    ref, cand, policy = parity_fixture()
    summary, _ = parity_kinds(ref, cand, policy, subset=True)
    check("a --only subset can never report the swap acceptable",
          not summary["ok"], str(summary))


# --- DET-02: exact environment identity --------------------------------------
#
# Schema 1 called an environment "canonical" on a Python *minor*, a LibreOffice
# version *prefix*, a *subset* of required fonts, and a merely non-empty
# FONTCONFIG_FILE -- then computed a fingerprint it never compared against
# anything. Four ways to be a different environment and still report
# `canonical: true`, and this repository has been burnt by two of them: Chromium
# 149 vs 150 moved a gated metric 5x, and an unpinned font set moved c4_i18n's
# within2pt 0.416 -> 0.038. Each mutation below is one of those ways.

def canonical_env_pair():
    """(recorded reference, live environment) that are the same environment."""
    import evidence
    ref = {
        "os": "linux",
        "python": "3.12.13",
        "oracles": {"soffice_version": "LibreOffice 24.2.7.2 420(Build:2)",
                    "font_families": ["DejaVu Sans", "FreeSerif", "IPAGothic",
                                      "Liberation Mono", "Liberation Sans",
                                      "Liberation Serif", "WenQuanYi Zen Hei"]},
        "fonts_conf": {"repo_sha256": "a" * 64, "active_path": "/w/fonts.conf",
                       "active_sha256": "a" * 64, "active_is_repo_conf": True},
        "font_files": {"digest": "b" * 64, "count": 59, "unreadable": []},
        "dependencies": {"pymupdf": "1.28.0", "pypdfium2": "5.12.0",
                         "mupdf": "1.28.0", "pdfium": "152.0.7947.0",
                         "python-docx": "1.1.2", "numpy": "2.1.0",
                         "pillow": "11.0.0", "lxml": "5.3.0"},
    }
    import copy
    live = copy.deepcopy(ref)
    fp = evidence.fingerprint(ref)
    ref["fingerprint"] = fp
    live["fingerprint"] = fp
    return ref, live


def env_identity(ref, live):
    import evidence
    ok, bad = evidence.environment_identity(live, ref=ref)
    return ok, " | ".join(bad)


def test_hashed_files_have_one_spelling():
    """Any file whose BYTES are hashed by anything must be stored with one line
    ending, or the digest is platform-dependent.

    Measured twice, the same way both times. First: `scripts/fonts.conf` is hashed
    into the environment fingerprint, `.gitattributes` pinned `*.sh`/`*.yml`/
    `*.yaml` to LF but not `*.conf`, and a Windows checkout therefore produced
    CRLF. A canonical reference recorded from that checkout hashed to 924510e8...
    where every Linux checkout -- CI included -- computes 84d4357a..., so the
    reference was invalid in both places it has to work.

    Then the identical defect in JSON, which is hashed as FILE BYTES in three
    separate places: `expansion_policy._sha256` pins testkit/corpus_expansion.json,
    `gdocs_oracle._manifest_identity` pins testkit/corpus_manifest.json by exact
    bytes, and `livepass_verify._read_json` digests whatever evidence it grades.
    It broke in BOTH directions at once, which is what makes the class worth a
    test rather than two fixes. corpus_expansion.json was pinned from Linux at
    7a2f15d6... and hashed ad3d2624... on Windows, failing three tests on the
    host while the container passed; corpus_manifest.json was pinned from Windows
    at cc4dd4c1... and hashes 2bedb5bd... on Linux, so the Google Docs
    qualification refused outright in the canonical environment and no test on a
    Windows desk could see it.

    The content was never wrong in any of these; only the checkout was. That is
    exactly the kind of defect a digest is supposed to catch and cannot catch
    about itself.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hashed = ["scripts/fonts.conf",
              "testkit/corpus_expansion.json",
              "testkit/corpus_manifest.json",
              "testkit/gdocs_quality_policy.json",
              "testkit/expansion_parity_policy.json",
              "testkit/livepass_predictions.json"]
    for rel in hashed:
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            check("%s exists to be hashed" % rel, False, "missing")
            continue
        with open(p, "rb") as fh:
            raw = fh.read()
        check("%s is checked out LF-only" % rel, b"\r\n" not in raw,
              "contains CRLF, so its sha256 differs from the same file on Linux; "
              "add a `text eol=lf` rule for it in .gitattributes")

    # Every committed evidence artifact too: livepass_predictions.json pins its
    # baselines by the digest of these files, so one CRLF checkout turns a
    # recorded baseline into an ungradeable run.
    evid = os.path.join(root, "docs", "evidence")
    for name in sorted(os.listdir(evid)) if os.path.isdir(evid) else []:
        if not name.endswith(".json"):
            continue
        with open(os.path.join(evid, name), "rb") as fh:
            raw = fh.read()
        check("docs/evidence/%s is checked out LF-only" % name,
              b"\r\n" not in raw,
              "contains CRLF, so livepass_verify digests it differently here "
              "than on Linux")

    # And the rules that keep it that way must actually be present, so the checks
    # above cannot start passing by accident on a machine that happens to be Linux.
    ga = os.path.join(root, ".gitattributes")
    rules = open(ga).read() if os.path.exists(ga) else ""
    for pattern in ("*.conf text eol=lf", "*.json text eol=lf"):
        check(".gitattributes pins %s" % pattern.split()[0], pattern in rules,
              "a Linux-only CI would pass the byte checks above while a Windows "
              "contributor kept recording unreproducible digests")


def test_env_identity_matching_pair_is_canonical():
    ref, live = canonical_env_pair()
    ok, why = env_identity(ref, live)
    check("an identical environment is canonical", ok, why)


def test_env_identity_rejects_patch_version_drift():
    """3.12.3 vs 3.12.13 is a real, metric-moving difference in this repository's
    history, and a minor-version check cannot see it."""
    for field, value in (("python", "3.12.3"),):
        ref, live = canonical_env_pair()
        live[field] = value
        live["fingerprint"] = __import__("evidence").fingerprint(live)
        ok, why = env_identity(ref, live)
        check("python patch drift is not canonical", not ok, why)

    ref, live = canonical_env_pair()
    live["oracles"]["soffice_version"] = "LibreOffice 24.2.1.2 420(Build:1)"
    live["fingerprint"] = __import__("evidence").fingerprint(live)
    ok, why = env_identity(ref, live)
    check("a LibreOffice build difference is not canonical", not ok, why)


def test_env_identity_rejects_unexpected_fonts():
    """The half that schema 1 missed. Installing the right fonts is half the job;
    seeing no others is the other half -- a runner image shipping extra faces
    moved c4_i18n's dy_p50 0.15pt -> 2.1pt with the corpus already frozen."""
    ref, live = canonical_env_pair()
    live["oracles"]["font_families"] = sorted(
        live["oracles"]["font_families"] + ["Noto Sans CJK JP"])
    live["fingerprint"] = __import__("evidence").fingerprint(live)
    ok, why = env_identity(ref, live)
    check("an EXTRA visible font is not canonical", not ok, why)
    check("the extra font is named", "Noto Sans CJK JP" in why, why)


def test_env_identity_rejects_missing_font():
    ref, live = canonical_env_pair()
    live["oracles"]["font_families"] = [
        f for f in live["oracles"]["font_families"] if f != "IPAGothic"]
    live["fingerprint"] = __import__("evidence").fingerprint(live)
    ok, why = env_identity(ref, live)
    check("a missing visible font is not canonical", not ok, why)


def test_env_identity_rejects_changed_fonts_conf():
    ref, live = canonical_env_pair()
    live["fonts_conf"]["repo_sha256"] = "9" * 64
    live["fingerprint"] = __import__("evidence").fingerprint(live)
    ok, why = env_identity(ref, live)
    check("a changed scripts/fonts.conf is not canonical", not ok, why)


def test_env_identity_rejects_unapplied_fonts_conf():
    """A config that is merely set is not a config that is applied. Schema 1
    accepted any non-empty FONTCONFIG_FILE, including one adding the system's
    fonts back."""
    ref, live = canonical_env_pair()
    live["fonts_conf"] = dict(live["fonts_conf"],
                              active_path="/etc/fonts/fonts.conf",
                              active_sha256="e" * 64,
                              active_is_repo_conf=False)
    ok, why = env_identity(ref, live)
    check("FONTCONFIG_FILE pointing elsewhere is not canonical", not ok, why)

    ref, live = canonical_env_pair()
    live["fonts_conf"] = dict(live["fonts_conf"], active_path=None,
                              active_sha256=None, active_is_repo_conf=False)
    ok, why = env_identity(ref, live)
    check("an unset FONTCONFIG_FILE is not canonical", not ok, why)


def test_env_identity_rejects_font_file_drift():
    """Two machines can both report "DejaVu Sans" and resolve it to different
    builds with different metrics. The family list cannot tell them apart."""
    ref, live = canonical_env_pair()
    live["font_files"]["digest"] = "7" * 64
    live["fingerprint"] = __import__("evidence").fingerprint(live)
    ok, why = env_identity(ref, live)
    check("a different font FILE set is not canonical", not ok, why)


def test_env_identity_rejects_unhashable_font():
    ref, live = canonical_env_pair()
    live["font_files"] = dict(live["font_files"], unreadable=["Broken.ttf"])
    ok, why = env_identity(ref, live)
    check("a font file that cannot be hashed is not canonical", not ok, why)


def test_env_identity_enforces_the_recorded_fingerprint():
    """The check schema 1 could never have performed: it set `fingerprint` AFTER
    calling the identity function, so the value was not there to compare."""
    ref, live = canonical_env_pair()
    live["fingerprint"] = "0" * 64
    ok, why = env_identity(ref, live)
    check("a fingerprint mismatch is not canonical", not ok, why)
    check("the mismatch says it is a fingerprint", "fingerprint" in why, why)


def test_env_identity_without_a_reference_is_not_canonical():
    """Fail closed: no recorded canonical environment means nothing can claim to
    be it. The alternative -- treating "no reference" as "matches" -- is how an
    unenforced fingerprint behaves."""
    import evidence
    _, live = canonical_env_pair()
    ok, bad = evidence.environment_identity(live, ref=None)
    check("no recorded reference means not canonical", not ok)
    check("and it says how to record one",
          any("record-canonical" in b for b in bad), " | ".join(bad))


def test_env_identity_rejects_dependency_drift():
    import evidence
    for dep in ("pymupdf", "pypdfium2", "pdfium", "mupdf", "lxml"):
        ref, live = canonical_env_pair()
        live["dependencies"][dep] = "0.0.1"
        live["fingerprint"] = evidence.fingerprint(live)
        ok, why = env_identity(ref, live)
        check("%s version drift is not canonical" % dep, not ok, why)


def test_parity_policy_can_actually_be_recorded():
    """`--update-policy` is the documented way to record floors, and it raised
    NameError before writing anything: `record_policy` referenced `refine`, which
    exists only as a local in `main`. So the one command the policy file tells you
    to run could never have run.

    That is why the stale `c4_i18n` floors were never remeasured after the font
    set was pinned -- not because nobody tried, but because trying crashed. A
    recording path with no test is a recording path nobody has executed.
    """
    import json
    import tempfile
    import backend_parity
    ref, cand, policy = parity_fixture()
    env = {"os": "linux", "canonical": True, "fingerprint": PARITY_FP,
           "python": "3.12.3",
           "oracles": {"soffice_version": "LibreOffice 24.2.7.2 420(Build:2)"},
           "dependencies": {"pymupdf": "1.28.0", "pdfium": "152.0.7947.0"},
           "fonts_conf": {"repo_sha256": "a" * 64},
           "font_files": {"digest": "b" * 64}}
    manifest = {"documents": {k: {"sha256": "a" * 64} for k in PARITY_MANIFEST["documents"]}}
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "parity_policy.json")
        try:
            backend_parity.record_policy(
                ref, cand, policy, manifest, env,
                profile_id=PARITY_PROFILE_ID, path=path)
            wrote = os.path.exists(path)
            err = ""
        except Exception as e:
            wrote, err = False, "%s: %s" % (type(e).__name__, e)
        check("the documented --update-policy path runs at all", wrote, err)
        if not wrote:
            return
        written = json.load(open(path))
        spec = (written.get("ratified_shortfalls") or {}).get("accepted.pdf") or {}
        check("a recorded floor names its environment",
              spec.get("environment_fingerprint") == PARITY_FP,
              repr(spec.get("environment_fingerprint")))
        check("a recorded floor names its corpus",
              bool(spec.get("corpus_manifest_sha256")),
              repr(spec.get("corpus_manifest_sha256")))
        check("a recorded floor names its profile",
              bool(spec.get("profile_id")), repr(spec.get("profile_id")))
        check("the policy records the full profile measured",
              written.get("profile_id") == PARITY_PROFILE_ID,
              repr(written.get("profile_id")))
        check("the refine-only legacy binding is removed",
              "recorded_refine_rounds" not in written,
              repr(written.get("recorded_refine_rounds")))


def test_policy_update_refuses_profile_migration_without_writing():
    import backend_parity
    import tempfile
    _, _, policy = parity_fixture()
    policy.pop("profile_id")
    policy["recorded_refine_rounds"] = 3
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "parity_policy.json")
        before = (json.dumps(policy, indent=1, sort_keys=True) + "\n").encode()
        with open(path, "wb") as f:
            f.write(before)
        rc = backend_parity.main([
            "--profile", "candidate-refined", "--update-policy", "--policy", path])
        with open(path, "rb") as f:
            after = f.read()
    check("profile-mismatched update is refused", rc == 2, repr(rc))
    check("refused update preserves policy bytes", after == before)


def test_measurement_mode_is_read_only_and_cannot_pass():
    import backend_parity
    import tempfile
    ref, cand, policy = parity_fixture()
    policy.pop("profile_id")
    policy["recorded_refine_rounds"] = 3
    captured, writes = {}, []

    old_manifest = backend_parity.gate.load_manifest
    old_resolve = backend_parity.runall.resolve_corpus
    old_run = backend_parity.run
    old_environment = backend_parity.evidence.environment
    old_merge = backend_parity.evidence.merge
    old_record = backend_parity.record_policy
    try:
        backend_parity.gate.load_manifest = lambda: PARITY_MANIFEST
        backend_parity.runall.resolve_corpus = lambda manifest: (
            [os.path.join("fixtures", name)
             for name in PARITY_MANIFEST["documents"]], [])
        backend_parity.run = lambda backend, srcs, out, profile: \
            copy.deepcopy(ref if backend == "pymupdf" else cand)
        backend_parity.evidence.environment = lambda: {"fingerprint": PARITY_FP}
        backend_parity.evidence.merge = lambda path, **sections: \
            captured.update(sections) or path
        backend_parity.record_policy = lambda *a, **kw: writes.append((a, kw))

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "parity_policy.json")
            before = (json.dumps(policy, indent=1, sort_keys=True) + "\n").encode()
            with open(path, "wb") as f:
                f.write(before)
            rc = backend_parity.main([
                "--measure", "--profile", "candidate-refined", "--policy", path,
                "--out", td, "--evidence", os.path.join(td, "evidence.json")])
            with open(path, "rb") as f:
                after = f.read()
    finally:
        backend_parity.gate.load_manifest = old_manifest
        backend_parity.runall.resolve_corpus = old_resolve
        backend_parity.run = old_run
        backend_parity.evidence.environment = old_environment
        backend_parity.evidence.merge = old_merge
        backend_parity.record_policy = old_record

    summary = captured.get("parity") or {}
    check("measurement mode always exits nonzero", rc == 2, repr(rc))
    check("measurement mode cannot claim success",
          summary.get("ok") is False
          and summary.get("release_ready") is False
          and summary.get("measurement_only") is True, repr(summary))
    check("measurement reports unadjudicated profile mismatch",
          {"unadjudicated", "profile-mismatch"}
          <= set(summary.get("failure_kinds") or []), repr(summary))
    check("measurement never calls the policy writer", not writes, repr(writes))
    check("measurement preserves policy bytes", after == before)


def test_measure_and_update_are_mutually_exclusive():
    import backend_parity
    try:
        backend_parity.build_parser().parse_args(
            ["--measure", "--update-policy"])
        code = None
    except SystemExit as e:
        code = e.code
    check("measure and update cannot be combined", code == 2, repr(code))


def test_committed_parity_policy_is_wellformed():
    import backend_parity
    policy = backend_parity.load_policy()

    def entries(section):
        return {k: v for k, v in (policy.get(section) or {}).items()
                if not k.startswith("_")}

    check("the policy names its two backends",
          policy.get("reference_backend") and policy.get("candidate_backend"))
    check("the policy is schema 2 or later", (policy.get("schema") or 0) >= 2,
          "schema=%r -- the provisional/ratified split is schema 2"
          % policy.get("schema"))
    check("the policy has migrated off `accepted_shortfalls`",
          not entries("accepted_shortfalls"),
          "still present: %s" % sorted(entries("accepted_shortfalls")))

    provisional = entries("provisional_shortfalls")
    ratified = entries("ratified_shortfalls")
    waived = dict(provisional)
    waived.update(ratified)

    # Rule 5: zero-test execution is a failure. Reading the section and looping
    # over nothing is how this check would silently stop checking -- which is
    # exactly what happened to it when `accepted_shortfalls` was renamed and the
    # loop body simply never ran.
    check("there is at least one waived document to check", bool(waived),
          "no provisional or ratified shortfalls found; this test would "
          "otherwise pass by executing zero assertions")

    for doc_id, spec in sorted(waived.items()):
        check("waived %s carries a defect ID" % doc_id, bool(spec.get("defect")))
        check("waived %s carries numeric floors" % doc_id,
              isinstance(spec.get("floors"), dict) and bool(spec["floors"]),
              "floors=%r -- record them with --update-policy" % spec.get("floors"))

    for doc_id, spec in sorted(ratified.items()):
        for field in ("ratified_by", "ratified_on", "issue", "review_condition"):
            check("ratified %s names %s" % (doc_id, field), bool(spec.get(field)),
                  "a ratification needs a named owner and a way to expire")

    for doc_id, spec in sorted(entries("expected_divergence").items()):
        check("divergence %s carries rendered evidence" % doc_id,
              bool(spec.get("verified")))

    # `f1_fpdf_brief` is unwaived on purpose. If it appears in any waiver
    # section, the product decision was made by an edit rather than by the
    # owner, and that is the thing this policy exists to prevent.
    #
    # `05_memo` was in this list until 2026-08-05 and is deliberately no longer.
    # The guard did its job: it held the line through three batches, and the
    # last one was stopped BY it -- the ratification arrived, the guard refused,
    # and the decision went back to the owner rather than being taken by an
    # edit. It was then granted explicitly, so the entry exists because someone
    # with the authority said so, which is exactly the outcome the guard was
    # built to force. Removing it now is not weakening the rule; it is the rule
    # having worked. f1 keeps its bar because no such decision has been made
    # about f1.
    for doc_id in ("f1_fpdf_brief.pdf",):
        check("%s is in no waiver section" % doc_id,
              doc_id not in waived and doc_id not in entries("expected_divergence"),
              "attribution is not authorisation; widening a waiver is a product "
              "decision scheduled for the Google Docs checkpoint (DEC-D2)")
    # 05_memo may now be waived, but only with the full ratification shape --
    # the bar moved from "never" to "only by a named owner with a way out".
    memo = waived.get("05_memo.pdf")
    if memo is not None:
        for field in ("ratified_by", "ratified_on", "issue", "review_condition"):
            check("05_memo's ratification names %s" % field, bool(memo.get(field)),
                  "the guard was removed on an owner decision; the entry it "
                  "allows must still carry one")
        check("05_memo is ratified, never merely provisional",
              "05_memo.pdf" in ratified, "a provisional 05_memo would be the "
              "old failure wearing a new section")


# ------------------------------------------------- value hygiene (audit round 2)
# "Present" is not "well-formed". Every case below reached a comparison operator
# and was scored, because the gate only ever asked whether a number cleared a
# threshold -- never whether it was a number.
def test_none_metric_fails():
    r = healthy()
    r[0]["within2pt"] = None
    v = verdict(r)
    check("a None metric fails", not v.ok, v.report())


def test_boolean_metric_fails():
    """isinstance(True, int) is True, and page_match is a bool living next door."""
    r = healthy()
    r[0]["live_text_cov"] = True
    v = verdict(r)
    check("a boolean metric fails", "malformed" in kinds(v), v.report())


def test_nan_metric_fails():
    """Every comparison against NaN is False, so NaN passes every check."""
    r = healthy()
    r[0]["within2pt"] = float("nan")
    v = verdict(r)
    check("a NaN metric fails", not v.ok, v.report())
    check("NaN is not treated as a number", not gate.is_number(float("nan")))


def test_infinite_metric_fails():
    r = healthy()
    r[0]["dy_p50"] = float("inf")
    v = verdict(r)
    check("an infinite metric fails", not v.ok, v.report())


def test_out_of_range_metric_fails():
    """A coverage of 1.7 clears every threshold and means the harness is broken."""
    r = healthy()
    r[0]["live_text_cov"] = 1.7
    v = verdict(r)
    check("a fraction above 1.0 fails", "out-of-range" in kinds(v), v.report())
    r2 = healthy()
    r2[0]["doc_recall"] = -0.2
    check("a negative fraction fails", "out-of-range" in kinds(verdict(r2)))


def test_page_count_inconsistency_fails():
    r = healthy()
    r[0]["page_match"] = True
    r[0]["out_pages"] = 5                      # contradicts src_pages=3
    v = verdict(r)
    check("page_match contradicting the page counts fails",
          "inconsistent" in kinds(v), v.report())


def test_nonsense_page_count_fails():
    for bad in (0, -1, 2.5, None, True):
        r = healthy()
        r[0]["out_pages"] = bad
        v = verdict(r)
        check("out_pages=%r fails" % (bad,), not v.ok, v.report())


def test_missing_or_wrong_renderer_fails():
    r = healthy()
    del r[0]["renderer"]
    check("a result that does not name its renderer fails",
          "no-oracle" in kinds(verdict(r)) or "no-metric" in kinds(verdict(r)))
    r2 = healthy()
    r2[0]["renderer"] = "some-other-oracle"
    check("a result scored against a different oracle fails",
          "wrong-oracle" in kinds(verdict(r2)), verdict(r2).report())


# ------------------------------------------------ parity coverage and dimensions
def test_parity_document_failing_under_both_backends_fails():
    """The hole an intersection cannot see: dropped on both sides, so sets match."""
    ref, cand, policy = parity_fixture()
    del ref["good.pdf"]
    del cand["good.pdf"]
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a document missing from BOTH backends fails",
          "missing" in kinds_, str(summary["failures"]))


def test_parity_structured_failure_is_not_a_silent_drop():
    ref, cand, policy = parity_fixture()
    cand["good.pdf"] = {"src": "good.pdf", "convert_error": "ValueError: boom"}
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a recorded conversion failure fails", "unmeasurable" in kinds_,
          str(summary["failures"]))


def test_parity_improvement_cannot_hide_a_regression():
    """The short-circuit: one gain suppressed every loss ordered after it."""
    ref, cand, policy = parity_fixture()
    cand["good.pdf"]["page_err"] = 0
    cand["good.pdf"]["src_pages"] = 3
    cand["good.pdf"]["out_pages"] = 3
    ref["good.pdf"]["src_pages"] = 3
    ref["good.pdf"]["out_pages"] = 4          # reference is a page out, candidate is not
    ref["good.pdf"]["page_match"] = False
    cand["good.pdf"]["within2pt"] = 0.10      # ... and candidate placement collapsed
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a gain on one dimension does not mask a loss on another",
          "regression" in kinds_, str(summary["failures"]))
    check("both directions are reported",
          summary["regressions"] == 1, str(summary))


def test_parity_every_gated_dimension_is_compared():
    import backend_parity
    missing = [m for m in gate.METRICS if m not in backend_parity.DIMENSIONS]
    check("parity compares every metric the gate gates", not missing,
          "not compared: %s" % missing)


# --- the dy_p50 absolute-magnitude exemption (task #22) ----------------------
# A rule that can excuse a regression has to be tested like one. The condition
# on within2pt is the load-bearing half: without it this is "small numbers do
# not count", which would excuse a document whose placement genuinely degraded.
def _dy_exemption(**over):
    spec = {"both_arms_below_pt": 2.0, "conditioned_on": ["within2pt"],
            "reason": "base-14 ascent reporting artifact",
            "clears_at_record": ["good.pdf"], "measured_on": "2026-08-05",
            "evidence": "docs/evidence/parity-expanded-2026-08-05.json"}
    spec.update(over)
    return spec


def _with_exemption(spec=None, profile=PARITY_PROFILE_ID):
    ref, cand, policy = parity_fixture()
    policy["dy_absolute_exemption"] = {profile: _dy_exemption() if spec is None
                                       else spec}
    return ref, cand, policy


def test_parity_dy_exemption_clears_a_tiny_symmetric_move():
    ref, cand, policy = _with_exemption()
    ref["good.pdf"]["dy_p50"], cand["good.pdf"]["dy_p50"] = 0.10, 1.40
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a sub-2pt dy move with within2pt steady is not a regression",
          summary["regressions"] == 0, str(summary["failures"]))


def test_parity_dy_exemption_refuses_when_within2pt_degraded():
    """The x02 case: dy and within2pt move independently, so dy alone lies."""
    ref, cand, policy = _with_exemption()
    ref["good.pdf"]["dy_p50"], cand["good.pdf"]["dy_p50"] = 0.10, 1.40
    cand["good.pdf"]["within2pt"] = 0.40            # from 0.60, past the margin
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("a tiny dy move does NOT excuse a document losing within2pt",
          "regression" in kinds_, str(summary["failures"]))
    dims_ = {f["detail"].split()[2] for f in summary["failures"]
             if f["kind"] == "regression"}
    check("and the dy regression is reported too, not swallowed",
          "dy_p50:" in " ".join(f["detail"] for f in summary["failures"]),
          str(summary["failures"]))


def test_parity_dy_exemption_refuses_above_its_ceiling():
    for ref_dy, cand_dy, label in ((2.5, 4.0, "both arms above"),
                                   (0.1, 2.6, "candidate above"),
                                   (2.1, 2.9, "reference above")):
        ref, cand, policy = _with_exemption()
        ref["good.pdf"]["dy_p50"], cand["good.pdf"]["dy_p50"] = ref_dy, cand_dy
        summary, kinds_ = parity_kinds(ref, cand, policy)
        check("dy exemption does not apply when %s the ceiling" % label,
              "regression" in kinds_, str(summary["failures"]))


def test_parity_malformed_dy_exemption_is_an_error_not_an_absence():
    """Present-but-unreadable must fail, or the file and the gate disagree."""
    bad = {
        "unconditioned": _dy_exemption(conditioned_on=[]),
        "conditioned on the wrong metric": _dy_exemption(conditioned_on=["dx_p50"]),
        "negative ceiling": _dy_exemption(both_arms_below_pt=-1),
        "non-numeric ceiling": _dy_exemption(both_arms_below_pt="2.0"),
        "empty reason": _dy_exemption(reason="  "),
        "not an object": ["nope"],
    }
    for label, spec in bad.items():
        ref, cand, policy = _with_exemption(spec)
        summary, kinds_ = parity_kinds(ref, cand, policy)
        check("a %s dy exemption fails" % label,
              "malformed-exemption" in kinds_, str(summary["failures"]))
    for field in ("both_arms_below_pt", "conditioned_on", "reason",
                  "clears_at_record", "measured_on", "evidence"):
        spec = _dy_exemption()
        del spec[field]
        ref, cand, policy = _with_exemption(spec)
        summary, kinds_ = parity_kinds(ref, cand, policy)
        check("a dy exemption missing %s fails" % field,
              "malformed-exemption" in kinds_, str(summary["failures"]))


def test_parity_dy_exemption_is_bound_to_its_own_profile():
    """A ceiling calibrated at one profile says nothing about another."""
    ref, cand, policy = _with_exemption(
        profile="pymupdf/standard/libreoffice/refine3@240dpi")
    ref["good.pdf"]["dy_p50"], cand["good.pdf"]["dy_p50"] = 0.10, 1.40
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("an exemption recorded for another profile is inert here",
          "regression" in kinds_, str(summary["failures"]))


def test_committed_parity_policy_dy_exemption_is_conditioned():
    """The shipped rule, not a fixture: it must never be unconditioned."""
    import backend_parity
    policy = backend_parity.load_policy()
    block = policy.get(backend_parity.DY_EXEMPTION_SECTION) or {}
    entries = {k: v for k, v in block.items() if not k.startswith("_")}
    check("the committed policy records a dy exemption", bool(entries),
          "no %s section" % backend_parity.DY_EXEMPTION_SECTION)
    for profile, spec in sorted(entries.items()):
        loaded, errors = backend_parity.dy_exemption_for(policy, profile)
        check("committed dy exemption for %s is well-formed" % profile,
              loaded is not None and not errors, repr(errors))
        check("committed dy exemption for %s is conditioned on within2pt"
              % profile, spec.get("conditioned_on") == ["within2pt"],
              repr(spec.get("conditioned_on")))
        check("committed dy exemption for %s stays at 2.0pt" % profile,
              spec.get("both_arms_below_pt") == 2.0,
              "widening this ceiling blinds the policy to structural "
              "divergences an order of magnitude larger")


def test_parity_expected_divergence_is_bounded():
    """A waiver names a known difference; it is not a licence for unknown ones.

    `c5_graphics` is waived because PDFium keeps a gradient band PyMuPDF drops.
    Unbounded, that waiver also excused every *other* metric on the document,
    forever.
    """
    ref, cand, policy = parity_fixture()
    cand["diverges.pdf"]["within2pt"] = 0.01
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("an expected divergence falling past its floor fails",
          "below-floor" in kinds_, str(summary["failures"]))


def test_parity_unbounded_expected_divergence_fails():
    ref, cand, policy = parity_fixture()
    policy["expected_divergence"]["diverges.pdf"]["floors"] = None
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("an expected divergence with no floors fails", "unrecorded" in kinds_,
          str(summary["failures"]))


def test_parity_floors_are_profile_scoped():
    """Floors measured at one full profile say nothing about another.

    Backend, output profile, oracle, refinement and DPI can all move the result.
    A mismatch must reject the policy before any waiver or floor is applied.
    """
    import backend_parity
    ref, cand, policy = parity_fixture()
    cand["accepted.pdf"]["within2pt"] = 0.01          # far below its floor
    _, at_recorded = backend_parity.adjudicate(
        ref, cand, policy, manifest=PARITY_MANIFEST,
        profile_id=PARITY_PROFILE_ID)
    _, at_other = backend_parity.adjudicate(
        ref, cand, policy, manifest=PARITY_MANIFEST,
        profile_id="pdfium/gdocs/none/refine0@240dpi")
    kinds_recorded = set(f["kind"] for f in at_recorded["failures"])
    kinds_other = set(f["kind"] for f in at_other["failures"])
    check("floors apply at the profile they were recorded at",
          "below-floor" in kinds_recorded, str(at_recorded["failures"]))
    check("a different full profile fails closed before floor comparison",
          kinds_other == {"profile-mismatch"}, str(at_other["failures"]))
    check("a profile mismatch cannot be release-ready",
          not at_other["ok"] and not at_other["release_ready"], str(at_other))


def test_parity_rejects_mismatched_per_document_floor_binding():
    import backend_parity
    ref, cand, policy = parity_fixture()
    policy["ratified_shortfalls"]["accepted.pdf"]["profile_id"] = \
        "pdfium/gdocs/none/refine0@240dpi"
    rows, summary = backend_parity.adjudicate(
        ref, cand, policy, manifest=PARITY_MANIFEST,
        profile_id=PARITY_PROFILE_ID)
    check("a mismatched floor binding stops adjudication",
          not rows and summary["failure_kinds"] == ["profile-mismatch"],
          repr(summary))


def test_committed_policy_cannot_govern_product_without_full_profile():
    import backend_parity
    policy = backend_parity.load_policy()
    from exactdoc.options import PRODUCT
    errors = backend_parity._policy_profile_errors(
        policy, PRODUCT.profile_id())
    check("the legacy policy cannot govern the shipping product profile",
          bool(errors) and "profile_id" in errors[0], repr(errors))


def test_parity_stale_expected_divergence_fails():
    """A waiver for a difference that no longer exists still excuses the document."""
    ref, cand, policy = parity_fixture()
    cand["diverges.pdf"] = copy.deepcopy(ref["diverges.pdf"])   # identical now
    policy["expected_divergence"]["diverges.pdf"]["floors"]["live_text_cov"] = 0.70
    policy["expected_divergence"]["diverges.pdf"]["floors"]["doc_recall"] = 0.70
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("an expected divergence that no longer diverges fails",
          "stale" in kinds_, str(summary["failures"]))


def test_parity_divergence_needs_rendered_evidence():
    ref, cand, policy = parity_fixture()
    del policy["expected_divergence"]["diverges.pdf"]["verified"]
    summary, kinds_ = parity_kinds(ref, cand, policy)
    check("an expected divergence with no rendered evidence fails",
          "undocumented" in kinds_, str(summary["failures"]))


# ------------------------------------------------------- recording preconditions
def test_baseline_recording_refused_off_canonical():
    rec = {"raw": gate.record("raw", healthy()),
           "product": gate.record("product", healthy())}
    try:
        gate.check_recordable(rec, MANIFEST, {"canonical": False, "os": "windows"})
        check("recording off the canonical environment is refused", False)
    except gate.RecordRefused:
        check("recording off the canonical environment is refused", True)


def test_baseline_recording_refused_on_partial_corpus():
    rec = {"raw": gate.record("raw", healthy()),
           "product": gate.record("product", [healthy()[0]])}
    try:
        gate.check_recordable(rec, MANIFEST, {"canonical": True, "os": "linux"})
        check("recording a partial corpus is refused", False)
    except gate.RecordRefused:
        check("recording a partial corpus is refused", True)


def test_baseline_recording_allowed_when_complete_and_canonical():
    rec = {"raw": gate.record("raw", healthy()),
           "product": gate.record("product", healthy())}
    try:
        gate.check_recordable(rec, MANIFEST, {"canonical": True, "os": "linux"})
        check("a complete canonical run may be recorded", True)
    except gate.RecordRefused as e:
        check("a complete canonical run may be recorded", False, str(e))


def test_runner_refuses_single_lane_recording():
    import runall
    src = open(runall.__file__).read()
    check("the runner refuses to record one lane alone",
          "refusing to record a baseline for one lane" in src)


def test_parity_forbids_subset_policy_update():
    import backend_parity
    src = open(backend_parity.__file__).read()
    check("--only cannot record floors",
          "--only cannot be combined with --update-policy" in src)


# ---------------------------------------------------------- backend precedence
def test_backend_precedence():
    """explicit keyword > supplied options > environment > PRODUCT."""
    import os as _os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from exactdoc.options import PRODUCT, resolve

    prev = _os.environ.get("EXACTDOC_BACKEND")
    _os.environ["EXACTDOC_BACKEND"] = "pdfium"
    try:
        # Mirrors convert()'s resolution exactly; asserting on the rule itself.
        def resolved(backend=None, options=None):
            if backend is None and options is None:
                backend = _os.environ.get("EXACTDOC_BACKEND", "").strip() or None
            return resolve(options, backend=backend).backend

        check("environment is used when nothing else is given",
              resolved() == "pdfium")
        check("an explicit keyword beats the environment",
              resolved(backend="pymupdf") == "pymupdf")
        check("a supplied profile beats the environment",
              resolved(options=PRODUCT.replace(backend="pymupdf")) == "pymupdf")
        check("an explicit keyword beats a supplied profile",
              resolved(backend="pdfium",
                       options=PRODUCT.replace(backend="pymupdf")) == "pdfium")
    finally:
        if prev is None:
            _os.environ.pop("EXACTDOC_BACKEND", None)
        else:
            _os.environ["EXACTDOC_BACKEND"] = prev


def test_parity_lanes_cannot_be_redirected_by_environment():
    """The gate that compares two backends must not be steerable by a variable."""
    import backend_parity
    src = open(backend_parity.__file__).read()
    check("parity passes an explicit profile to convert()",
          "convert(s, dx, options=options)" in src)
    import inspect
    # The SUBMODULE, imported as one. This used to say `from exactdoc import
    # convert as convert_mod` and reach `convert_mod.convert`, which only
    # worked because the package's lazy loader was handing back the module
    # instead of the function it advertises -- the same accident that made the
    # one usage the README documents raise "'module' object is not callable".
    # Asking for the module explicitly says what this test means and survives
    # the fix.
    import exactdoc.convert as convert_mod
    body = inspect.getsource(convert_mod.convert)
    check("convert() consults the environment only when nothing was supplied",
          "if backend is None and options is None:" in body, body[:400])


def _release_evidence(lanes):
    return {
        "git": {"available": True, "clean": True},
        "environment": {
            "canonical": True,
            "oracles": {"soffice_version": "LibreOffice test"},
            "dependencies": {"pymupdf": "1", "pypdfium2": "1"},
        },
        "corpus": {"resolved": 2, "manifest_documents": 2, "problems": []},
        "lanes": lanes,
        "parity": {"ok": True, "regressions": 0},
    }


def test_evidence_requires_each_named_lane():
    import evidence
    passed = {"verdict": {"ok": True}}
    for missing, present in (("product", "raw"),
                             ("raw", "product")):
        problems = evidence.validate(_release_evidence({present: passed}))
        check("missing %s lane is reported" % missing,
              "lane %r missing" % missing in problems, repr(problems))


def test_evidence_reports_failure_in_each_named_lane():
    import evidence
    for failed in ("raw", "product"):
        lanes = {name: {"verdict": {"ok": name != failed}}
                 for name in ("raw", "product")}
        problems = evidence.validate(_release_evidence(lanes))
        check("failing %s lane is reported" % failed,
              "lane %r did not pass" % failed in problems, repr(problems))


def test_evidence_diagnostic_lanes_cannot_substitute_for_raw():
    import evidence
    passed = {"verdict": {"ok": True}}
    for extra in ("candidate", "refined"):
        problems = evidence.validate(_release_evidence(
            {"product": passed, extra: passed}))
        check("%s does not satisfy the raw requirement" % extra,
              "lane 'raw' missing" in problems, repr(problems))
        check("%s is rejected as an unexpected release lane" % extra,
              any("unexpected lane %r" % extra in p for p in problems),
              repr(problems))


def test_evidence_merge_never_empties_a_section():
    """The artifact is the single source of a release claim. Nothing may blank it.

    Measured on a full green run: the final `evidence.py --out` step, whose job is
    to fill in the environment, passed the empty template's `parity: None` over
    the verdict the previous step had recorded, and the run finished with an
    evidence file that had forgotten its own parity result.
    """
    import tempfile
    import evidence
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "evidence.json")
        evidence.merge(p, parity={"ok": True, "regressions": 0},
                       lanes={"product": {"verdict": {"ok": True}}},
                       corpus={"resolved": 16})
        evidence.merge(p, parity=None, corpus=None, lanes={},
                       environment={"os": "linux"})
        with open(p) as f:
            doc = json.load(f)
    check("a None section does not overwrite a recorded one",
          doc.get("parity", {}).get("ok") is True, json.dumps(doc.get("parity")))
    check("an empty lanes dict does not drop recorded lanes",
          "product" in (doc.get("lanes") or {}), str(doc.get("lanes")))
    check("the corpus section survives", (doc.get("corpus") or {}).get("resolved") == 16)
    check("a later section still merges in", doc["environment"]["os"] == "linux")


def test_complete_lane_snapshot_replaces_stale_contract_only():
    import tempfile
    import evidence
    passed = {"verdict": {"ok": True}}
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "evidence.json")
        with open(p, "w") as f:
            json.dump({"schema": evidence.SCHEMA,
                       "lanes": {"raw": {"generation": 1},
                                 "product": {"generation": 1},
                                 "refined": passed,
                                 "candidate": passed}}, f)
        evidence.merge(p, lanes={"raw": {"generation": 2},
                                 "product": {"generation": 2}})
        with open(p) as f:
            complete = json.load(f)
        evidence.merge(p, lanes={"product": {"generation": 3}})
        evidence.merge(p, lanes={})
        with open(p) as f:
            incremental = json.load(f)
    check("a complete current snapshot drops stale diagnostic lanes",
          set(complete["lanes"]) == {"raw", "product"},
          repr(complete["lanes"]))
    check("a partial update preserves the other current lane",
          incremental["lanes"]["raw"]["generation"] == 2
          and incremental["lanes"]["product"]["generation"] == 3,
          repr(incremental["lanes"]))
    check("empty lane update preserves current evidence",
          set(incremental["lanes"]) == {"raw", "product"},
          repr(incremental["lanes"]))


def test_relative_tolerance():
    """dy_p50 spans 0.04pt to 101pt; one absolute slack cannot serve both."""
    small = gate.tolerance(gate.METRICS["dy_p50"], 0.6)
    large = gate.tolerance(gate.METRICS["dy_p50"], 101.0)
    check("the absolute floor governs a small drift", abs(small - 0.5) < 1e-9,
          str(small))
    check("the proportional term governs a large drift", large > 10.0, str(large))
    check("a fraction metric stays absolute",
          gate.tolerance(gate.METRICS["within2pt"], 0.9) == 0.05)


def test_committed_baseline_is_wellformed():
    """The committed record must satisfy the schema the gate reads."""
    doc = gate.load()
    if not doc:
        check("a baseline is committed", False, "no gate_baseline.json")
        return
    errors = gate.baseline_contract_errors(doc)
    # This checkout intentionally preserves pre-transition numbers rather than
    # relabelling them as the restored raw/product contract. Until canonical Linux
    # re-records both profiles, runall must reject it loudly.
    if errors:
        check("stale baseline is rejected clearly",
              any("raw/product" in error or "baseline lanes" in error
                  for error in errors), repr(errors))
        return
    check("baseline is schema 3", doc.get("schema") == 3, str(doc.get("schema")))
    from exactdoc.options import LANES
    for lane in LANES:
        entry = doc.get("lanes", {}).get(lane)
        check("lane %r is recorded" % lane, bool(entry),
              "lanes present: %s" % sorted(doc.get("lanes", {})))
        if not entry:
            continue
        docs = entry.get("documents", {})
        manifest = gate.load_manifest() or {"documents": {}}
        check("lane %r records every manifest document" % lane,
              set(docs) == set(manifest["documents"]),
              "record %d, manifest %d" % (len(docs), len(manifest["documents"])))
        for doc_id, metrics in sorted(docs.items()):
            missing = [m for m in gate.METRICS if m not in metrics]
            check("lane %r %s records every gated metric" % (lane, doc_id),
                  not missing, "missing %s" % missing)
            for name, value in sorted(metrics.items()):
                spec = gate.METRICS.get(name)
                if spec and not gate.clears(spec["dir"], value, spec["threshold"]):
                    check("lane %r %s shortfall has a defect ID" % (lane, doc_id),
                          doc_id in entry.get("shortfall_defects", {}),
                          "%s=%s below %s" % (name, value, spec["threshold"]))


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print("gate mutation tests (%d)" % len(tests))
    for t in tests:
        print("\n%s" % t.__name__)
        t()
    print("\n%s" % ("all clear" if not FAILED else
                    "%d FAILED: %s" % (len(FAILED), ", ".join(FAILED))))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
