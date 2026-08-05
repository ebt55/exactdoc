"""Mutation tests for the expansion-corpus acceptance policy.

Same discipline as `test_gate_mutations.py`: start from a policy that is
well-formed, break exactly one thing, and assert the reader refuses for the
expected reason. A policy reader that fails open is worse than no policy, because
it produces the appearance of a rule.

The artifact ships EMPTY, so almost everything here runs against synthetic
policies. That is deliberate -- the rules have to be proven before the first
entry relies on them, not after.

    python -m unittest tests.test_expansion_policy
"""
import copy
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import expansion_policy as EP  # noqa: E402

CANDIDATE = "pdfium/gdocs/none/refine0@240dpi"
PRODUCT = "pymupdf/standard/libreoffice/refine3@240dpi"
DOC = "y06_irs_1040_instructions.pdf"


def entry(**over):
    e = {"dimensions": ["page_err", "dy_p50"],
         "floors": {"page_err": 217, "dy_p50": 41.05},
         "reference_at_record": {"page_err": 133, "dy_p50": 36.45},
         "tier": "ordinary_digital",
         "defect": "D-cellgap",
         "reason": "cell gap and column gutter are indistinguishable at this "
                   "geometry; documented since BLOCK_SAME_ROW_EM",
         "evidence": "docs/evidence/parity-expanded-2026-08-05f.json",
         "measured_on": "2026-08-05",
         "measured_commit": "0" * 40,
         "environment_fingerprint": "3ca438f1" + "0" * 56,
         "recorded_on": {"os": "linux", "pdfium": "152.0.7947.0",
                         "pymupdf": "1.28.0", "python": "3.12.3"},
         "ratified_by": "Ebin Babu Thomas",
         "ratified_on": "2026-08-05",
         "issue": "DEC-D2",
         "review_condition": "retire when cell-vs-gutter separation lands",
         "authorization_provenance": "relayed grant, adjudicated by the "
                                     "orchestrating session"}
    e.update(over)
    return e


def policy(**over):
    p = {"schema": EP.SCHEMA,
         "status": "populated",
         "gating": False,
         "reference_backend": "pymupdf",
         "candidate_backend": "pdfium",
         "corpus": {"name": "corpus_expansion.json", "sha256": None},
         "profiles": {CANDIDATE: {"ratified_findings": {DOC: entry()}},
                      PRODUCT: {"ratified_findings": {}}}}
    p.update(over)
    return p


def row(document=DOC, worse=("page_err", "dy_p50"), **cand):
    metrics = {"page_err": 217, "dy_p50": 41.05}
    metrics.update(cand)
    return {"document": document, "verdict": "MAJOR", "worse": list(worse),
            "reference": {"page_err": 133, "dy_p50": 36.45},
            "candidate": metrics}


class Loading(unittest.TestCase):
    """Everything that must stop the file being read at all."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.corpus = os.path.join(self.dir.name, "corpus_expansion.json")
        with open(self.corpus, "w", encoding="utf-8") as fh:
            fh.write('{"documents": {}}')
        self.digest = EP._sha256(self.corpus)
        self.addCleanup(self.dir.cleanup)

    def write(self, payload):
        path = os.path.join(self.dir.name, "policy.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def load(self, payload):
        return EP.load(self.write(payload), corpus_path=self.corpus)

    def good(self, **over):
        p = policy(**over)
        p["corpus"]["sha256"] = self.digest
        return p

    def test_a_missing_policy_is_not_an_error(self):
        """Non-gating corpus: having no ratified findings is a real state."""
        self.assertIsNone(EP.load(os.path.join(self.dir.name, "absent.json"),
                                  corpus_path=self.corpus))

    def test_a_wellformed_policy_loads(self):
        self.assertIsNotNone(self.load(self.good()))

    def test_the_gated_policy_is_refused_as_this_one(self):
        """The contamination this artifact was split out to prevent."""
        for stray in sorted(EP._GATED_ONLY_KEYS):
            p = self.good()
            p[stray] = {}
            with self.assertRaises(EP.PolicyError) as caught:
                self.load(p)
            self.assertIn("GATED", str(caught.exception))

    def test_a_moved_corpus_is_refused_naming_both_hashes(self):
        p = self.good()
        p["corpus"]["sha256"] = "0" * 64
        with self.assertRaises(EP.PolicyError) as caught:
            self.load(p)
        message = str(caught.exception)
        self.assertIn("0" * 64, message)
        self.assertIn(self.digest, message)
        self.assertNotIn(self.dir.name, message)      # no absolute paths

    def test_an_unpinned_or_wrongly_schemad_policy_is_refused(self):
        for label, mutate in (
                ("no corpus pin", lambda p: p.pop("corpus")),
                ("corpus pin is not an object", lambda p: p.update(corpus=[])),
                ("wrong schema", lambda p: p.update(schema="something.else")),
                ("no profiles", lambda p: p.pop("profiles")),
                ("profiles is not an object", lambda p: p.update(profiles=[]))):
            p = self.good()
            mutate(p)
            with self.assertRaises(EP.PolicyError, msg=label):
                self.load(p)

    def test_a_section_key_must_be_a_full_profile_id(self):
        for bad in ("candidate", "pdfium/gdocs", "pdfium/gdocs/none/refine0"):
            p = self.good()
            p["profiles"][bad] = {"ratified_findings": {}}
            with self.assertRaises(EP.PolicyError, msg=bad):
                self.load(p)

    def test_unreadable_json_is_an_error_not_an_absence(self):
        path = os.path.join(self.dir.name, "broken.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        with self.assertRaises(EP.PolicyError):
            EP.load(path, corpus_path=self.corpus)


class Entries(unittest.TestCase):
    """Everything an entry must carry before it may excuse anything."""

    DOCS = {DOC: {"tier": "ordinary_digital"}}

    def entries(self, p, profile_id=CANDIDATE, documents=None):
        return EP.entries_for(p, profile_id,
                              self.DOCS if documents is None else documents)

    def test_a_wellformed_entry_is_returned(self):
        got = self.entries(policy())
        self.assertEqual(set(got), {DOC})

    def test_only_the_matching_profile_section_is_read(self):
        """A finding at one profile says nothing about another."""
        self.assertEqual(self.entries(policy(), PRODUCT), {})
        p = policy()
        p["profiles"][PRODUCT]["ratified_findings"] = {DOC: entry()}
        self.assertEqual(set(self.entries(p, PRODUCT)), {DOC})

    def test_a_run_profile_must_be_a_full_profile_id(self):
        with self.assertRaises(EP.PolicyError):
            self.entries(policy(), "candidate")

    def test_an_entry_naming_an_absent_document_is_refused(self):
        with self.assertRaises(EP.PolicyError) as caught:
            self.entries(policy(), CANDIDATE, documents={})
        self.assertIn("not in the expansion corpus", str(caught.exception))

    def test_every_field_is_required(self):
        for field in sorted(EP._ENTRY_FIELDS):
            e = entry()
            del e[field]
            p = policy()
            p["profiles"][CANDIDATE]["ratified_findings"] = {DOC: e}
            with self.assertRaises(EP.PolicyError, msg=field):
                self.entries(p)

    def test_an_extra_field_is_refused(self):
        p = policy()
        p["profiles"][CANDIDATE]["ratified_findings"] = {
            DOC: entry(surprise="extra")}
        with self.assertRaises(EP.PolicyError):
            self.entries(p)

    def test_dimensions_must_be_real_distinct_and_nonempty(self):
        for bad in ([], ["invented"], ["page_err", "page_err"], "page_err",
                    ["page_err", "invented"]):
            p = policy()
            p["profiles"][CANDIDATE]["ratified_findings"] = {
                DOC: entry(dimensions=bad)}
            with self.assertRaises(EP.PolicyError, msg=repr(bad)):
                self.entries(p)

    def test_every_named_dimension_must_be_floored(self):
        p = policy()
        p["profiles"][CANDIDATE]["ratified_findings"] = {
            DOC: entry(floors={"page_err": 217})}       # dy_p50 unfloored
        with self.assertRaises(EP.PolicyError) as caught:
            self.entries(p)
        self.assertIn("unbounded waiver", str(caught.exception))

    def test_floors_must_be_gated_numeric_metrics(self):
        for bad in ({"invented": 1.0}, {"page_err": "217"},
                    {"page_err": float("nan")}, {"page_err": True}, {}):
            p = policy()
            p["profiles"][CANDIDATE]["ratified_findings"] = {
                DOC: entry(floors=bad, dimensions=["page_err"])}
            with self.assertRaises(EP.PolicyError, msg=repr(bad)):
                self.entries(p)

    def test_dates_must_be_iso(self):
        for field in ("measured_on", "ratified_on"):
            p = policy()
            p["profiles"][CANDIDATE]["ratified_findings"] = {
                DOC: entry(**{field: "5 August"})}
            with self.assertRaises(EP.PolicyError, msg=field):
                self.entries(p)

    def test_recorded_on_must_be_a_non_empty_object(self):
        """A floor that does not name its toolchain cannot be told from a
        regression when the toolchain moves -- three stale c4_i18n floors
        already survived a font change and failed CI as though the backend had."""
        for bad in ({}, "linux", None, []):
            p = policy()
            p["profiles"][CANDIDATE]["ratified_findings"] = {
                DOC: entry(recorded_on=bad)}
            with self.assertRaises(EP.PolicyError, msg=repr(bad)):
                self.entries(p)

    def test_prose_fields_must_be_non_empty(self):
        for field in ("tier", "defect", "reason", "evidence", "ratified_by",
                      "issue", "review_condition", "authorization_provenance",
                      "measured_commit", "environment_fingerprint"):
            p = policy()
            p["profiles"][CANDIDATE]["ratified_findings"] = {
                DOC: entry(**{field: "   "})}
            with self.assertRaises(EP.PolicyError, msg=field):
                self.entries(p)

    def test_an_unsafe_document_name_is_refused(self):
        p = policy()
        p["profiles"][CANDIDATE]["ratified_findings"] = {"../x.pdf": entry()}
        with self.assertRaises(EP.PolicyError):
            self.entries(p, documents={"../x.pdf": {}})


class Applying(unittest.TestCase):
    """What an entry does, and the two directions it fails in."""

    DOCS = {DOC: {"tier": "ordinary_digital"}}

    def apply(self, rows, p=None):
        return EP.apply(rows, p or policy(), CANDIDATE, documents=self.DOCS)

    def test_a_ratified_row_is_annotated_never_passed(self):
        rows, failures = self.apply([row()])
        self.assertEqual(failures, [])
        self.assertTrue(rows[0]["ratified"])
        self.assertEqual(rows[0]["ratified_dimensions"], ["page_err", "dy_p50"])
        check = "the measured verdict is untouched -- this annotates, it does " \
                "not adjudicate"
        self.assertEqual(rows[0]["verdict"], "MAJOR", check)

    def test_a_regression_past_the_floor_fails(self):
        rows, failures = self.apply([row(page_err=400)])
        kinds = {k for _, k, _ in failures}
        self.assertIn("below-floor", kinds)

    def test_a_finding_that_stopped_describing_anything_fails(self):
        """Same rule as the gated policy: a dead waiver hides the next one."""
        rows, failures = self.apply([row(worse=[])])
        kinds = {k for _, k, _ in failures}
        self.assertIn("stale", kinds)

    def test_a_partially_stale_entry_is_not_stale(self):
        """Still worse on one covered dimension, so the entry still describes."""
        rows, failures = self.apply([row(worse=["page_err"])])
        self.assertNotIn("stale", {k for _, k, _ in failures})

    def test_an_uncovered_dimension_is_left_alone(self):
        """The whole point: ratifying a dimension is not ratifying a document."""
        rows, failures = self.apply(
            [row(worse=["page_err", "dy_p50", "word_recall"])])
        self.assertNotIn("stale", {k for _, k, _ in failures})
        self.assertEqual(rows[0]["worse"],
                         ["page_err", "dy_p50", "word_recall"],
                         "an unratified dimension must remain reported")

    def test_a_ratified_document_nobody_measured_fails(self):
        rows, failures = self.apply([row(document="x01_lo_memo_pageno.pdf")])
        self.assertIn("unmeasured", {k for _, k, _ in failures})

    def test_a_missing_metric_fails(self):
        bad = row()
        del bad["candidate"]["dy_p50"]
        rows, failures = self.apply([bad])
        self.assertIn("no-metric", {k for _, k, _ in failures})


class Committed(unittest.TestCase):
    """The artifact as shipped."""

    def test_the_committed_policy_loads_and_every_entry_validates(self):
        p = EP.load()
        self.assertIsNotNone(p, "the expansion policy artifact is missing")
        self.assertEqual(p["schema"], EP.SCHEMA)
        self.assertFalse(p.get("gating"), "this corpus does not gate")
        exp = json.load(open(EP.CORPUS_PATH, encoding="utf-8"))
        docs = {k: v for k, v in exp["documents"].items()
                if not k.startswith("_")}
        total = 0
        for profile_id in (CANDIDATE, PRODUCT):
            got = EP.entries_for(p, profile_id, docs)   # raises if malformed
            total += len(got)
            for doc_id, e in got.items():
                self.assertIn(EP.SCHEMA.split(".")[1][:9], "expansion")
                self.assertTrue(e["evidence"].startswith("docs/evidence/"),
                                "%s must cite a committed measurement" % doc_id)
                for dim in e["dimensions"]:
                    self.assertIn(dim, e["floors"],
                                  "%s: %s unfloored" % (doc_id, dim))
        self.assertTrue(total, "the artifact now carries entries")

    def test_the_committed_policy_pins_the_real_corpus(self):
        p = EP.load()
        self.assertEqual(p["corpus"]["sha256"], EP._sha256(EP.CORPUS_PATH))

    def test_the_two_artifacts_stay_distinct(self):
        """Neither file may be read as the other, in either direction."""
        import backend_parity
        with open(backend_parity.POLICY_PATH, encoding="utf-8") as fh:
            gated = json.load(fh)
        self.assertNotEqual(gated.get("schema"), EP.SCHEMA)
        self.assertTrue(EP._GATED_ONLY_KEYS & set(gated),
                        "the gated policy must remain identifiable as such")
        expansion = EP.load()
        self.assertFalse(EP._GATED_ONLY_KEYS & set(expansion))
        self.assertNotIn("margins", expansion,
                         "margins are the gated policy's statement, not this "
                         "artifact's")


if __name__ == "__main__":
    unittest.main()
