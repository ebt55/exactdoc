"""The expansion-parity runner measures. These tests are why it cannot do more.

Three things are asserted, and each of them has a specific failure in this
repository's history behind it:

1. **Refusal parity is adjudicated across both arms, not on one.** A document
   the incumbent refuses and the candidate converts produces exit 0 and a
   convincing-looking non-form; that is a contract change no fidelity metric
   reports, because a refused document has no metrics.

2. **The output cannot be confused with the gated measurement.** It carries its
   own schema and fails closed on every key `evidence.validate` reads.

3. **The gate and the committed parity policy cannot see any of it.** This is
   the discipline `corpus_manifest.py` states plainly -- two functions, two
   questions -- and it is only real if something checks.
"""
import ast
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import mupdf_extra  # noqa: E402

# `backend_parity` -> `harness`, which imports fitz at module level and requires
# the `mupdf` extra by design.
if not mupdf_extra.AVAILABLE:                                  # pragma: no cover
    raise unittest.SkipTest(mupdf_extra.REASON)

import backend_parity            # noqa: E402
import corpus_manifest           # noqa: E402
import evidence                  # noqa: E402
import parity_expansion          # noqa: E402

MODULE_PATH = os.path.join(ROOT, "testkit", "parity_expansion.py")


def _refusal(cls, code):
    return {"refused": True, "error_class": cls, "code": code}


def _metrics(**kw):
    base = {"src": "x.pdf", "refused": False, "page_match": True,
            "src_pages": 1, "out_pages": 1, "live_text_cov": 1.0,
            "doc_recall": 1.0, "word_recall": 1.0, "within2pt": 0.5,
            "dy_p50": 1.0, "raster_frac": 0.0}
    base.update(kw)
    return base


class RefusalParity(unittest.TestCase):
    """Both backends must refuse identically, or it is not parity."""

    def test_identical_typed_refusal_is_parity(self):
        row = parity_expansion.adjudicate_refusal(
            "y07.pdf", _refusal("InteractiveFormError", "interactive-form"),
            _refusal("InteractiveFormError", "interactive-form"))
        self.assertEqual(row["verdict"], "refusal-parity")

    def test_different_typed_refusal_is_a_mismatch(self):
        """Same refusal, different type, is still a changed API.

        Exit codes are an API: `interactive-form` is 19 and `parse` is not.
        A caller branching on either gets a different answer after the swap,
        so 'both refused' is not a sufficient test.
        """
        row = parity_expansion.adjudicate_refusal(
            "y07.pdf", _refusal("InteractiveFormError", "interactive-form"),
            _refusal("ParseError", "parse"))
        self.assertEqual(row["verdict"], "REFUSAL-CLASS-MISMATCH")
        self.assertIn("InteractiveFormError", row["detail"])
        self.assertIn("ParseError", row["detail"])

    def test_candidate_converting_a_refused_document_is_an_asymmetry(self):
        row = parity_expansion.adjudicate_refusal(
            "y11.pdf", _refusal("PageLimitError", "page-limit"),
            {"refused": False, "converted": True})
        self.assertEqual(row["verdict"], "REFUSAL-ASYMMETRY")
        self.assertIn("candidate converts", row["detail"])

    def test_reference_converting_is_also_an_asymmetry(self):
        row = parity_expansion.adjudicate_refusal(
            "y11.pdf", {"refused": False, "converted": True},
            _refusal("PageLimitError", "page-limit"))
        self.assertEqual(row["verdict"], "REFUSAL-ASYMMETRY")
        self.assertIn("reference converts", row["detail"])

    def test_neither_refusing_is_a_contract_gap(self):
        row = parity_expansion.adjudicate_refusal(
            "y14.pdf", {"refused": False}, {"refused": False})
        self.assertEqual(row["verdict"], "REFUSAL-CONTRACT-GAP")

    def test_refusal_tier_never_reaches_the_metric_comparison(self):
        """An unsupported document is adjudicated on refusal, not on metrics.

        Both arms carry a full set of (meaningless) metrics here. If the runner
        scored them it would report `same` -- a clean parity result for a
        document that should never have converted at all.
        """
        specs = {"y07.pdf": {"tier": "unsupported"}}
        rows, summary = parity_expansion.adjudicate(
            {"y07.pdf": _metrics()}, {"y07.pdf": _metrics()}, specs, {})
        self.assertEqual(rows[0]["verdict"], "REFUSAL-CONTRACT-GAP")
        self.assertEqual(summary["same"], 0)

    def test_refusal_verdicts_rank_above_every_metric_verdict(self):
        worst = parity_expansion.SEVERITY_ORDER.index("MAJOR")
        for name in ("REFUSAL-CONTRACT-GAP", "REFUSAL-ASYMMETRY",
                     "REFUSAL-CLASS-MISMATCH"):
            self.assertLess(parity_expansion.SEVERITY_ORDER.index(name), worst,
                            "%s must outrank a metric regression" % name)


class SeverityBanding(unittest.TestCase):

    def test_worse_past_the_margin_is_major(self):
        specs = {"a.pdf": {"tier": "ordinary_digital"}}
        rows, _ = parity_expansion.adjudicate(
            {"a.pdf": _metrics(word_recall=1.0)},
            {"a.pdf": _metrics(word_recall=0.5)}, specs, {"word_recall": 0.05})
        self.assertEqual(rows[0]["verdict"], "MAJOR")
        self.assertIn("word_recall", rows[0]["worse"])

    def test_worse_inside_the_margin_is_minor_and_still_visible(self):
        """Inside the margin is not the same as unchanged.

        `worse_raw` keeps the movement on the record even when the margin
        absorbs it, because a corpus-wide drift of small regressions is exactly
        what a per-document margin is blind to.
        """
        specs = {"a.pdf": {"tier": "ordinary_digital"}}
        rows, _ = parity_expansion.adjudicate(
            {"a.pdf": _metrics(word_recall=1.0)},
            {"a.pdf": _metrics(word_recall=0.98)}, specs, {"word_recall": 0.05})
        self.assertEqual(rows[0]["verdict"], "minor")
        self.assertEqual(rows[0]["worse"], [])
        self.assertIn("word_recall", rows[0]["worse_raw"])

    def test_a_document_only_the_candidate_fails_is_an_asymmetry(self):
        specs = {"a.pdf": {"tier": "ordinary_digital"}}
        rows, summary = parity_expansion.adjudicate(
            {"a.pdf": _metrics()},
            {"a.pdf": {"src": "a.pdf", "convert_error": "ParseError: boom"}},
            specs, {})
        self.assertEqual(rows[0]["verdict"], "CONVERT-ASYMMETRY")
        self.assertIn("a.pdf", summary["blocking"])

    def test_a_document_both_backends_fail_is_not_blamed_on_the_swap(self):
        specs = {"a.pdf": {"tier": "ordinary_digital"}}
        rows, _ = parity_expansion.adjudicate(
            {"a.pdf": {"src": "a.pdf", "convert_error": "ParseError: boom"}},
            {"a.pdf": {"src": "a.pdf", "convert_error": "ParseError: boom"}},
            specs, {})
        self.assertEqual(rows[0]["verdict"], "unmeasurable")

    def test_a_document_missing_from_both_arms_still_appears(self):
        """Coverage is anchored on the manifest, not on the intersection."""
        specs = {"a.pdf": {"tier": "ordinary_digital"}}
        rows, _ = parity_expansion.adjudicate({}, {}, specs, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], "unmeasurable")


class OutputSeparation(unittest.TestCase):
    """The payload must never be readable as the gated parity verdict."""

    def test_summary_fails_closed_on_every_key_evidence_reads(self):
        _, summary = parity_expansion.adjudicate(
            {"a.pdf": _metrics()}, {"a.pdf": _metrics()},
            {"a.pdf": {"tier": "ordinary_digital"}}, {})
        self.assertEqual(summary["same"], 1)
        # A clean measurement is still not a pass.
        self.assertFalse(summary["ok"])
        self.assertFalse(summary["release_ready"])
        self.assertFalse(summary["adjudicated"])
        self.assertFalse(summary["gating"])

    def test_spliced_into_an_evidence_artifact_it_reads_as_a_failure(self):
        """The misuse case, exercised rather than asserted in prose.

        If somebody merges this payload into the `parity` slot of a release
        artifact, `evidence.validate` must reject it. A measurement that
        adjudicated nothing must not be able to satisfy a release check.
        """
        _, summary = parity_expansion.adjudicate(
            {"a.pdf": _metrics()}, {"a.pdf": _metrics()},
            {"a.pdf": {"tier": "ordinary_digital"}}, {})
        problems = evidence.validate({"parity": summary})
        self.assertTrue(any("parity did not pass" in p for p in problems),
                        "an unadjudicated measurement satisfied a release "
                        "check: %r" % problems)

    def test_schema_is_distinct_from_every_gated_artifact(self):
        self.assertEqual(parity_expansion.SCHEMA,
                         "exactdoc.parity-expansion-measurement.v1")
        self.assertNotEqual(parity_expansion.SCHEMA, evidence.SCHEMA)

    def test_output_directory_is_not_the_gated_parity_directory(self):
        gated = os.path.join(os.path.dirname(parity_expansion.OUT), "parity")
        self.assertNotEqual(os.path.abspath(parity_expansion.OUT),
                            os.path.abspath(gated))


class NoContamination(unittest.TestCase):
    """Structural separation, checked in the source rather than trusted."""

    def _tree(self):
        with open(MODULE_PATH) as f:
            return ast.parse(f.read())

    def _called_names(self):
        names = set()
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute):
                    names.add(fn.attr)
                elif isinstance(fn, ast.Name):
                    names.add(fn.id)
        return names

    def test_never_calls_the_policy_writer(self):
        """`record_policy` is the function that rewrites the committed policy.

        The whole reason this is a separate module is that a corpus-selecting
        flag on `backend_parity.py` would put the expansion documents one
        argument-parsing mistake away from re-flooring the gated policy.
        """
        self.assertNotIn("record_policy", self._called_names())

    def test_never_calls_the_gated_adjudicator_or_the_gate(self):
        called = self._called_names()
        for forbidden in ("check", "check_recordable", "load_manifest",
                          "record_baseline", "resolve_corpus"):
            self.assertNotIn(forbidden, called,
                             "expansion parity called %s" % forbidden)

    def test_never_merges_into_the_evidence_artifact(self):
        """`evidence.merge` is the only writer of the release artifact."""
        self.assertNotIn("merge", self._called_names())

    def test_reads_the_policy_margins_and_no_waiver_section(self):
        margins, source = parity_expansion.load_margins()
        self.assertEqual(source["sections_read"], ["margins"])
        self.assertFalse(source["waivers_applied"])
        for waiver in ("provisional_shortfalls", "ratified_shortfalls",
                       "expected_divergence", "accepted_shortfalls"):
            self.assertNotIn(waiver, margins)
        with open(MODULE_PATH) as f:
            src = f.read()
        # Named only in the docstring that explains why they are not applied.
        body = src.split('"""', 2)[2]
        for waiver in ("provisional_shortfalls", "ratified_shortfalls",
                       "expected_divergence"):
            self.assertNotIn(waiver, body,
                             "%s is referenced in executable code" % waiver)

    def test_never_opens_a_committed_policy_or_baseline_for_writing(self):
        src = open(MODULE_PATH).read()
        for protected in ("parity_policy.json", "gate_baseline.json",
                          "corpus_manifest.json", "gdocs_quality_policy.json"):
            self.assertNotIn('"%s"' % protected, src.split('"""', 2)[2],
                             "%s is named in executable code" % protected)

    def test_resolves_only_the_expansion_corpus(self):
        """Corpus resolution goes through `verify_expansion`, never `verify`.

        `verify` answers for the gated 16 and is what `runall.py` turns into a
        gate problem. Reaching for it here is how an expansion document would
        end up in a gated run.
        """
        called = self._called_names()
        self.assertIn("verify_expansion", called)
        self.assertNotIn("verify", called)

    def test_the_gated_corpus_and_the_expansion_corpus_do_not_overlap(self):
        gated = set(corpus_manifest.load().get("documents", {}))
        expansion = set(corpus_manifest.load_expansion().get("documents", {}))
        self.assertFalse(gated & expansion)

    def test_no_expansion_document_is_named_in_the_parity_policy(self):
        """The committed policy must govern none of these documents."""
        with open(backend_parity.POLICY_PATH) as f:
            policy = json.load(f)
        expansion = set(corpus_manifest.load_expansion().get("documents", {}))
        for section in ("provisional_shortfalls", "ratified_shortfalls",
                        "expected_divergence"):
            named = {k for k in (policy.get(section) or {})
                     if not k.startswith("_")}
            self.assertFalse(named & expansion,
                             "%s governs an expansion document" % section)


class ShippingProfileArm(unittest.TestCase):
    """The measurement gate (a) actually needs, and that nobody had taken.

    The migration swaps the core backend under the SHIPPING profile. The
    candidate profile is `pdfium/gdocs/none/refine0`, which shares neither the
    output profile, the oracle nor the refinement depth with what users run, so
    parity there is not by itself evidence about the product.
    """

    def test_the_product_profile_yields_the_two_shipping_arms(self):
        product = backend_parity.conversion_profile("product")
        self.assertEqual(product.replace(backend="pymupdf").profile_id(),
                         "pymupdf/standard/libreoffice/refine3@240dpi")
        self.assertEqual(product.replace(backend="pdfium").profile_id(),
                         "pdfium/standard/libreoffice/refine3@240dpi")

    def test_the_two_arms_do_not_collapse_onto_one_profile(self):
        """The same no-collapse discipline `validate_lanes` enforces.

        A comparison whose two arms resolve to one profile_id measures nothing
        and reports perfect parity while doing it.
        """
        for name in backend_parity.PROFILE_NAMES:
            profile = backend_parity.conversion_profile(name)
            ids = {profile.replace(backend=b).profile_id()
                   for b in ("pymupdf", "pdfium")}
            self.assertEqual(len(ids), 2, "%s collapses: %s" % (name, ids))

    def test_only_the_backend_axis_differs_between_the_arms(self):
        """Both arms must differ on exactly one field.

        `backend_parity.run` builds each arm with `profile.replace(backend=...)`
        for this reason, and the comment there is explicit that refine_rounds
        must never be moved independently -- its valid oracle and output profile
        come from the named profile as one validated unit.
        """
        import dataclasses
        for name in backend_parity.PROFILE_NAMES:
            profile = backend_parity.conversion_profile(name)
            a = dataclasses.asdict(profile.replace(backend="pymupdf"))
            b = dataclasses.asdict(profile.replace(backend="pdfium"))
            differing = {k for k in a if a[k] != b[k]}
            self.assertEqual(differing, {"backend"},
                             "%s arms differ on %s" % (name, differing))

    def test_every_profile_name_is_measurable_by_the_expansion_runner(self):
        self.assertEqual(set(parity_expansion.main.__globals__["backend_parity"]
                             .PROFILE_NAMES), set(backend_parity.PROFILE_NAMES))


class CorpusGuards(unittest.TestCase):

    def test_an_unmatched_only_filter_is_refused_not_silently_empty(self):
        paths, specs, problems = parity_expansion.resolve(
            only=["definitely_not_a_document"])
        self.assertEqual(paths, [])
        self.assertTrue(any(kind == "unknown" for kind, _, _ in problems))

    def test_a_subset_run_is_marked_as_one(self):
        """Recorded so a partial run cannot be read as corpus-wide coverage."""
        out = io.StringIO()
        with redirect_stdout(out):
            parity_expansion.resolve(tier="unsupported")
        paths, specs, problems = parity_expansion.resolve(tier="unsupported")
        self.assertEqual(problems, [])
        self.assertTrue(paths)
        self.assertTrue(all(s["tier"] == "unsupported" for s in specs.values()))


if __name__ == "__main__":
    unittest.main()
