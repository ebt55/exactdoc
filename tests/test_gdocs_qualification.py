"""Hermetic policy tests for the Google Docs qualification harness.

Run with ``python tests/test_gdocs_qualification.py``.  The fakes exercise the
Drive request shape but never import a Google package or open a network socket.
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import gdocs_oracle as oracle  # noqa: E402


class _Request:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.value


class _Files:
    def __init__(self, export_error=None, delete_error=None):
        self.export_error = export_error
        self.delete_error = delete_error
        self.deleted = []

    def create(self, **_kwargs):
        return _Request({"id": "remote-id-must-never-escape"})

    def export(self, **_kwargs):
        return _Request(b"pdf", self.export_error)

    def delete(self, fileId):
        self.deleted.append(fileId)
        return _Request(None, self.delete_error)


class _Service:
    def __init__(self, **kwargs):
        self._files = _Files(**kwargs)

    def files(self):
        return self._files


def _media(*_args, **_kwargs):
    return object()


class GDocsQualificationTests(unittest.TestCase):
    def make_corpus(self, root, source_bytes=b"frozen source"):
        fixtures = os.path.join(root, "fixtures")
        docxs = os.path.join(root, "docxs")
        os.mkdir(fixtures)
        os.mkdir(docxs)
        source = os.path.join(fixtures, "case.pdf")
        with open(source, "wb") as fh:
            fh.write(source_bytes)
        with open(os.path.join(docxs, "case.docx"), "wb") as fh:
            fh.write(b"candidate")
        manifest = {"fixtures_dir": "fixtures", "documents": {
            "case.pdf": {"sha256": hashlib.sha256(source_bytes).hexdigest()}}}
        manifest_path = os.path.join(root, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        identity, plan = oracle._source_plan(manifest_path)
        oracle._atomic_json(
            os.path.join(docxs, oracle.PREPARATION_NAME),
            oracle._preparation_payload(identity, plan, docxs,
                                        oracle.CANDIDATE_PROFILE_ID))
        return manifest_path, docxs

    def assert_preflight_rejects_without_service(self, manifest, docxs, work):
        calls = []
        passed, evidence = oracle.run_qualification(
            docxs, os.path.join(work, "out"), manifest,
            service_factory=lambda **_kwargs: calls.append(True),
            allow_cloud_upload=True)
        self.assertFalse(passed)
        self.assertEqual(evidence["failure_stage"], "preflight")
        self.assertEqual(calls, [])

    def make_quality_policy(self, root, manifest_path):
        identity = oracle._manifest_identity(manifest_path)
        policy = {"schema": oracle.QUALITY_POLICY_SCHEMA,
                  "candidate_profile": oracle.CANDIDATE_PROFILE_ID,
                  "manifest": identity,
                  "review": {"status": "ratified", "rationale": "owner reviewed",
                             "approved_by": "owner", "approved_on": "2026-08-02"},
                  "tiers": {"ordinary_digital": {"blocking": True, "documents": ["case.pdf"], "per_document": {
                      "page_match": {"equals": True},
                      "live_text_cov": {"min": 0.90},
                      "doc_recall": {"min": 0.90},
                      "word_recall": {"min": 0.90},
                      "mean_ssim": {"min": 0.70}, "dx_p50": {"max": 10.0},
                      "dy_p50": {"max": 10.0}}},
                  "designed_stress": {"blocking": False, "documents": [], "per_document": {
                      "page_match": {"equals": True}, "live_text_cov": {"min": .9},
                      "doc_recall": {"min": .9}, "word_recall": {"min": .9},
                      "mean_ssim": {"min": .7}, "dx_p50": {"max": 10.}, "dy_p50": {"max": 10.}}},
                  "unsupported": {"blocking": False, "expected": "reject-before-qualification", "documents": []}}}
        path = os.path.join(root, "quality-policy.json")
        oracle._atomic_json(path, policy)
        return path

    def test_no_consent_does_not_construct_service_or_write_output(self):
        with tempfile.TemporaryDirectory() as work:
            output = os.path.join(work, "out")
            called = []
            old_service = oracle._service
            try:
                oracle._service = lambda **_kwargs: called.append(True)
                code = oracle.main(["run", os.path.join(work, "no-docxs"), "--out", output])
            finally:
                oracle._service = old_service
            self.assertEqual(code, 2)
            self.assertEqual(called, [])
            self.assertFalse(os.path.exists(output))

    def test_hash_mismatch_rejects_before_service(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            with open(manifest, encoding="utf-8") as fh:
                data = json.load(fh)
            data["documents"]["case.pdf"]["sha256"] = "0" * 64
            with open(manifest, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            calls = []
            passed, evidence = oracle.run_qualification(
                docxs, os.path.join(work, "out"), manifest,
                service_factory=lambda **_kwargs: calls.append(True),
                allow_cloud_upload=True)
            self.assertFalse(passed)
            self.assertEqual(evidence["failure_stage"], "preflight")
            self.assertEqual(calls, [])

    def test_exact_docx_set_rejects_extra_before_service(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            with open(os.path.join(docxs, "unexpected.docx"), "wb") as fh:
                fh.write(b"extra")
            calls = []
            passed, evidence = oracle.run_qualification(
                docxs, os.path.join(work, "out"), manifest,
                service_factory=lambda **_kwargs: calls.append(True),
                allow_cloud_upload=True)
            self.assertFalse(passed)
            self.assertEqual(evidence["failure_stage"], "preflight")
            self.assertEqual(calls, [])

    def test_existing_orphan_prevents_service_and_pass(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            ledger = os.path.join(work, ".gdocs_orphans.json")
            with open(ledger, "w", encoding="utf-8") as fh:
                json.dump({"schema": "exactdoc.gdocs-orphan-ledger.v1",
                           "file_ids": ["never-leak-this-id"]}, fh)
            calls = []
            passed, evidence = oracle.run_qualification(
                docxs, os.path.join(work, "out"), manifest,
                service_factory=lambda **_kwargs: calls.append(True),
                allow_cloud_upload=True, orphan_ledger_path=ledger)
            self.assertFalse(passed)
            self.assertFalse(evidence["overall_pass"])
            self.assertEqual(evidence["failure_stage"], "preflight")
            self.assertEqual(calls, [])
            self.assertNotIn("never-leak-this-id", json.dumps(evidence))

    def test_export_failure_still_attempts_remote_deletion(self):
        with tempfile.TemporaryDirectory() as work:
            service = _Service(export_error=RuntimeError("export down"))
            with self.assertRaises(oracle.RoundtripError) as raised:
                oracle.roundtrip(service, os.path.join(work, "case.docx"),
                                 os.path.join(work, "out.pdf"), media_factory=_media)
            self.assertEqual(raised.exception.stage, "export")
            self.assertEqual(service._files.deleted, ["remote-id-must-never-escape"])

    def test_cleanup_failure_records_recovery_ledger_without_id_leakage(self):
        with tempfile.TemporaryDirectory() as work:
            service = _Service(delete_error=RuntimeError("delete down"))
            ledger = os.path.join(work, ".gdocs_orphans.json")
            with self.assertRaises(oracle.RoundtripError) as raised:
                oracle.roundtrip(service, os.path.join(work, "case.docx"),
                                 os.path.join(work, "out.pdf"), media_factory=_media,
                                 orphan_recorder=lambda fid: oracle._record_orphan(fid, ledger))
            self.assertEqual(raised.exception.stage, "cleanup")
            self.assertEqual(service._files.deleted, ["remote-id-must-never-escape"])
            with open(ledger, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["file_ids"], ["remote-id-must-never-escape"])
            self.assertNotIn("remote-id-must-never-escape", str(raised.exception))

    def test_missing_policy_collects_operational_evidence_but_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            out = os.path.join(work, "out")
            services = []

            def service_factory(**_kwargs):
                service = _Service()
                services.append(service)
                return service

            def fake_roundtrip(service, _docx, out_pdf):
                # Use the real cleanup protocol in this fake run, without Google.
                return oracle.roundtrip(service, _docx, out_pdf, media_factory=_media)

            def evaluator(_source, _docx, _out, **_kwargs):
                return {"src": _source, "docx": _docx, "render_pdf": "C:/secret.pdf",
                        "live_text_cov": 0.99, "page_match": True, "src_chars": 12}

            passed, evidence = oracle.run_qualification(
                docxs, out, manifest, service_factory=service_factory,
                roundtrip_fn=fake_roundtrip, evaluator=evaluator,
                allow_cloud_upload=True,
                quality_policy_path=os.path.join(work, "missing-policy.json"))
            self.assertFalse(passed)
            self.assertFalse(evidence["overall_pass"])
            self.assertTrue(evidence["operational_pass"])
            self.assertFalse(evidence["quality_pass"])
            self.assertEqual(evidence["failure_stage"], "quality-policy")
            self.assertEqual(evidence["quality"]["status"], "missing")
            row = evidence["documents"][0]
            self.assertEqual(row["source"], "case.pdf")
            self.assertEqual(row["docx"], "case.docx")
            self.assertTrue(row["attempted"] and row["succeeded"])
            self.assertNotIn("src", row["metrics"])
            self.assertNotIn("render_pdf", row["metrics"])
            self.assertEqual(services[0]._files.deleted, ["remote-id-must-never-escape"])
            with open(os.path.join(out, oracle.EVIDENCE_NAME), encoding="utf-8") as fh:
                on_disk = json.load(fh)
            self.assertEqual(on_disk, evidence)
            self.assertNotIn("remote-id-must-never-escape", json.dumps(on_disk))
            self.assertNotIn(work, json.dumps(on_disk))
            self.assertEqual(on_disk["candidate_profile"], oracle.CANDIDATE_PROFILE_ID)
            self.assertEqual(on_disk["preparation"]["name"], oracle.PREPARATION_NAME)

    def test_preparation_uses_named_candidate_not_environment_or_product(self):
        with tempfile.TemporaryDirectory() as work:
            fixtures = os.path.join(work, "fixtures")
            os.mkdir(fixtures)
            with open(os.path.join(fixtures, "case.pdf"), "wb") as fh:
                fh.write(b"frozen source")
            manifest = os.path.join(work, "manifest.json")
            with open(manifest, "w", encoding="utf-8") as fh:
                json.dump({"fixtures_dir": "fixtures", "documents": {
                    "case.pdf": {"sha256": hashlib.sha256(b"frozen source").hexdigest()}}}, fh)
            seen = []
            old = os.environ.get("EXACTDOC_BACKEND")
            os.environ["EXACTDOC_BACKEND"] = "pymupdf"
            try:
                def convert(source, destination, *, options):
                    seen.append((source, destination, options))
                    with open(destination, "wb") as fh:
                        fh.write(b"candidate")
                result = oracle.prepare(os.path.join(work, "prepared"), manifest,
                                        converter=convert)
            finally:
                if old is None:
                    del os.environ["EXACTDOC_BACKEND"]
                else:
                    os.environ["EXACTDOC_BACKEND"] = old
            self.assertEqual(result["profile"], oracle.CANDIDATE_PROFILE_ID)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0][2].profile_id(), oracle.CANDIDATE_PROFILE_ID)
            self.assertTrue(os.path.isfile(os.path.join(work, "prepared", oracle.PREPARATION_NAME)))

    def test_tampered_docx_or_wrong_profile_record_rejects_before_service(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            with open(os.path.join(docxs, "case.docx"), "ab") as fh:
                fh.write(b"tampered")
            self.assert_preflight_rejects_without_service(manifest, docxs, work)
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            record = os.path.join(docxs, oracle.PREPARATION_NAME)
            with open(record, encoding="utf-8") as fh:
                payload = json.load(fh)
            payload["candidate_profile"] = "pymupdf/standard/libreoffice/refine3@240dpi"
            oracle._atomic_json(record, payload)
            self.assert_preflight_rejects_without_service(manifest, docxs, work)

    def test_partial_prepare_failure_leaves_no_qualifiable_target(self):
        with tempfile.TemporaryDirectory() as work:
            fixtures = os.path.join(work, "fixtures")
            os.mkdir(fixtures)
            source = os.path.join(fixtures, "case.pdf")
            with open(source, "wb") as fh:
                fh.write(b"frozen source")
            manifest = os.path.join(work, "manifest.json")
            with open(manifest, "w", encoding="utf-8") as fh:
                json.dump({"fixtures_dir": "fixtures", "documents": {
                    "case.pdf": {"sha256": hashlib.sha256(b"frozen source").hexdigest()}}}, fh)
            class Candidate:
                def profile_id(self): return oracle.CANDIDATE_PROFILE_ID
            target = os.path.join(work, "prepared")
            with self.assertRaises(RuntimeError):
                oracle.prepare(target, manifest,
                               converter=lambda *_args, **_kw: (_ for _ in ()).throw(RuntimeError("fail")),
                               candidate_options=Candidate())
            self.assertFalse(os.path.exists(target))
            self.assert_preflight_rejects_without_service(manifest, target, work)

    def test_complete_fake_prepare_then_qualification_succeeds(self):
        with tempfile.TemporaryDirectory() as work:
            fixtures = os.path.join(work, "fixtures")
            os.mkdir(fixtures)
            source_bytes = b"frozen source"
            with open(os.path.join(fixtures, "case.pdf"), "wb") as fh:
                fh.write(source_bytes)
            manifest = os.path.join(work, "manifest.json")
            with open(manifest, "w", encoding="utf-8") as fh:
                json.dump({"fixtures_dir": "fixtures", "documents": {
                    "case.pdf": {"sha256": hashlib.sha256(source_bytes).hexdigest()}}}, fh)
            class Candidate:
                def profile_id(self): return oracle.CANDIDATE_PROFILE_ID
            docxs = os.path.join(work, "prepared")
            def convert(_source, destination, *, options):
                self.assertEqual(options.profile_id(), oracle.CANDIDATE_PROFILE_ID)
                with open(destination, "wb") as fh:
                    fh.write(b"candidate")
            oracle.prepare(docxs, manifest, converter=convert, candidate_options=Candidate())
            service = _Service()
            policy = self.make_quality_policy(work, manifest)
            passed, _ = oracle.run_qualification(
                docxs, os.path.join(work, "out"), manifest,
                service_factory=lambda **_kwargs: service,
                roundtrip_fn=lambda svc, path, out: oracle.roundtrip(svc, path, out, media_factory=_media),
                evaluator=lambda *_args, **_kw: {"page_match": True, "live_text_cov": 1.0,
                                                  "doc_recall": 1.0, "word_recall": 1.0,
                                                  "mean_ssim": 1.0, "dx_p50": 0., "dy_p50": 0.},
                allow_cloud_upload=True, quality_policy_path=policy)
            self.assertTrue(passed)

    def test_bad_finite_metrics_cannot_pass_a_valid_policy(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            policy = self.make_quality_policy(work, manifest)
            service = _Service()
            passed, evidence = oracle.run_qualification(
                docxs, os.path.join(work, "out"), manifest,
                service_factory=lambda **_kwargs: service,
                roundtrip_fn=lambda svc, path, out: oracle.roundtrip(svc, path, out, media_factory=_media),
                evaluator=lambda *_args, **_kw: {"page_match": False, "live_text_cov": 0.1,
                                                  "doc_recall": 0.1, "word_recall": 0.1,
                                                  "mean_ssim": 0.1, "dx_p50": 20., "dy_p50": 20.},
                allow_cloud_upload=True, quality_policy_path=policy)
            self.assertFalse(passed)
            self.assertTrue(evidence["operational_pass"])
            self.assertFalse(evidence["quality_pass"])
            self.assertEqual(evidence["failure_stage"], "quality-policy")
            self.assertEqual({finding["reason"] for finding in evidence["quality"]["findings"]},
                             {"mismatch", "out-of-bounds"})

    def test_draft_evaluates_but_never_passes(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            policy = self.make_quality_policy(work, manifest)
            with open(policy, encoding="utf-8") as fh:
                payload = json.load(fh)
            payload["review"].update({"status": "draft", "approved_by": None, "approved_on": None})
            oracle._atomic_json(policy, payload)
            passed, evidence = oracle.run_qualification(
                docxs, os.path.join(work, "out"), manifest, service_factory=lambda **_k: _Service(),
                roundtrip_fn=lambda svc, path, out: oracle.roundtrip(svc, path, out, media_factory=_media),
                evaluator=lambda *_a, **_k: {"page_match": True, "live_text_cov": 1., "doc_recall": 1.,
                                              "word_recall": 1., "mean_ssim": 1., "dx_p50": 0., "dy_p50": 0.},
                allow_cloud_upload=True, quality_policy_path=policy)
            self.assertFalse(passed)
            self.assertEqual(evidence["quality"]["status"], "valid")
            self.assertEqual(evidence["quality"]["reason"], "policy-not-ratified")

    def test_stress_only_finding_is_reported_nonblocking(self):
        checks = {"page_match": {"equals": True}, "live_text_cov": {"min": .9},
                  "doc_recall": {"min": .9}, "word_recall": {"min": .9},
                  "mean_ssim": {"min": .7}, "dx_p50": {"max": 10.}, "dy_p50": {"max": 10.}}
        rows = [{"source": "ordinary.pdf", "docx": "ordinary.docx", "metrics": dict(
            page_match=True, live_text_cov=1., doc_recall=1., word_recall=1., mean_ssim=1., dx_p50=0., dy_p50=0.)},
                {"source": "stress.pdf", "docx": "stress.docx", "metrics": dict(
            page_match=True, live_text_cov=.1, doc_recall=1., word_recall=1., mean_ssim=1., dx_p50=0., dy_p50=0.)}]
        quality = oracle._evaluate_quality(rows, {"ordinary_digital": {"blocking": True,
            "documents": {"ordinary.pdf"}, "checks": checks}, "designed_stress": {"blocking": False,
            "documents": {"stress.pdf"}, "checks": checks}}, {"status": "valid", "review": {"status": "ratified"}})
        self.assertTrue(quality["passed"])
        self.assertFalse(quality["tiers"]["designed_stress"]["passed"])
        self.assertFalse(quality["findings"][0]["blocking"])

    def test_v2_policy_rejects_tier_and_review_misuse(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, _ = self.make_corpus(work)
            path = self.make_quality_policy(work, manifest)
            identity, plan = oracle._source_plan(manifest)
            cases = []
            with open(path, encoding="utf-8") as fh:
                base = json.load(fh)
            altered = json.loads(json.dumps(base)); altered["schema"] = "exactdoc.gdocs-quality-policy.v1"; cases.append(altered)
            altered = json.loads(json.dumps(base)); del altered["tiers"]["designed_stress"]; cases.append(altered)
            altered = json.loads(json.dumps(base)); altered["tiers"]["designed_stress"]["documents"] = ["case.pdf"]; cases.append(altered)
            altered = json.loads(json.dumps(base)); altered["tiers"]["ordinary_digital"]["documents"] = ["unknown.pdf"]; cases.append(altered)
            altered = json.loads(json.dumps(base)); altered["tiers"]["unsupported"]["documents"] = ["case.pdf"]; cases.append(altered)
            altered = json.loads(json.dumps(base)); altered["review"]["status"] = "draft"; cases.append(altered)
            altered = json.loads(json.dumps(base)); altered["review"] = {"status": "ratified", "rationale": "x", "approved_by": None, "approved_on": None}; cases.append(altered)
            for payload in cases:
                oracle._atomic_json(path, payload)
                self.assertIn(oracle._load_quality_policy(path, identity, plan)[1]["status"], {"mismatch", "malformed"})

    def test_v2_policy_rejects_bad_max_rules(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, _ = self.make_corpus(work)
            path = self.make_quality_policy(work, manifest)
            identity, plan = oracle._source_plan(manifest)
            for metric, rule in (("dx_p50", {"max": -1}), ("dy_p50", {"max": float("inf")} ),
                                 ("dx_p50", {"max": float("nan")} ), ("dy_p50", {"max": 1, "min": 0})):
                with open(path, encoding="utf-8") as fh:
                    payload = json.load(fh)
                payload["tiers"]["ordinary_digital"]["per_document"][metric] = rule
                oracle._atomic_json(path, payload)
                self.assertEqual(oracle._load_quality_policy(path, identity, plan)[1]["status"], "malformed")
                self.make_quality_policy(work, manifest)

    def test_assess_is_offline_hash_bound_and_nonmutating(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            policy = self.make_quality_policy(work, manifest)
            _, evidence = oracle.run_qualification(
                docxs, os.path.join(work, "out"), manifest, service_factory=lambda **_k: _Service(),
                roundtrip_fn=lambda svc, path, out: oracle.roundtrip(svc, path, out, media_factory=_media),
                evaluator=lambda *_a, **_k: {"page_match": True, "live_text_cov": 1., "doc_recall": 1.,
                                              "word_recall": 1., "mean_ssim": 1., "dx_p50": 0., "dy_p50": 0.},
                allow_cloud_upload=True, quality_policy_path=policy)
            path = os.path.join(work, "out", oracle.EVIDENCE_NAME)
            with open(path, "rb") as fh:
                before = fh.read()
            with mock.patch.object(oracle, "_service", side_effect=AssertionError("offline")):
                passed, assessment = oracle.assess(path, manifest, policy)
            self.assertTrue(passed)
            with open(path, "rb") as fh:
                self.assertEqual(before, fh.read())
            self.assertEqual(assessment["source_evidence"]["sha256"], hashlib.sha256(before).hexdigest())
            with mock.patch.object(oracle, "_service", side_effect=AssertionError("offline")):
                self.assertEqual(oracle.main(["assess", path, "--manifest", manifest,
                                              "--quality-policy", policy]), 0)
            with self.assertRaises(SystemExit):
                oracle.main(["assess", path, "--manifest", manifest,
                             "--quality-policy", policy, "--allow-cloud-upload"])
            with open(policy, encoding="utf-8") as fh:
                draft = json.load(fh)
            draft["review"].update({"status": "draft", "approved_by": None, "approved_on": None})
            oracle._atomic_json(policy, draft)
            self.assertEqual(oracle.main(["assess", path, "--manifest", manifest,
                                          "--quality-policy", policy]), 1)
            with open(path, encoding="utf-8") as fh:
                tampered = json.load(fh)
            tampered["candidate_profile"] = "wrong"
            oracle._atomic_json(path, tampered)
            with self.assertRaises(oracle.QualificationError):
                oracle.assess(path, manifest, policy)
            self.assertEqual(oracle.main(["assess", path, "--manifest", manifest,
                                          "--quality-policy", policy]), 2)

    def test_assess_rejects_collisions_and_bad_operational_records(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            policy = self.make_quality_policy(work, manifest)
            _, _ = oracle.run_qualification(docxs, os.path.join(work, "out"), manifest,
                service_factory=lambda **_k: _Service(), roundtrip_fn=lambda svc, path, out: oracle.roundtrip(svc, path, out, media_factory=_media),
                evaluator=lambda *_a, **_k: {"page_match": True, "live_text_cov": 1., "doc_recall": 1., "word_recall": 1., "mean_ssim": 1., "dx_p50": 0., "dy_p50": 0.},
                allow_cloud_upload=True, quality_policy_path=policy)
            evidence = os.path.join(work, "out", oracle.EVIDENCE_NAME)
            with open(evidence, "rb") as fh: before = fh.read()
            for collision in (evidence, manifest, policy):
                with self.assertRaises(oracle.QualificationError): oracle.assess(evidence, manifest, policy, collision)
            with open(evidence, "rb") as fh:
                self.assertEqual(before, fh.read())
            with self.assertRaises(oracle.QualificationError): oracle.assess(evidence, manifest, policy, os.path.join(work, "absent", "x.json"))
            with open(evidence, encoding="utf-8") as fh: payload = json.load(fh)
            payload["documents"][0]["attempted"] = "yes"
            oracle._atomic_json(evidence, payload)
            with self.assertRaises(oracle.QualificationError): oracle.assess(evidence, manifest, policy)

    def test_policy_mismatch_and_missing_required_metrics_cannot_pass(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            policy = self.make_quality_policy(work, manifest)
            with open(policy, encoding="utf-8") as fh:
                payload = json.load(fh)
            payload["manifest"]["sha256"] = "0" * 64
            oracle._atomic_json(policy, payload)
            passed, evidence = oracle.run_qualification(
                docxs, os.path.join(work, "out"), manifest,
                service_factory=lambda **_kwargs: _Service(),
                roundtrip_fn=lambda svc, path, out: oracle.roundtrip(svc, path, out, media_factory=_media),
                evaluator=lambda *_args, **_kw: {"page_match": True, "live_text_cov": 1.0},
                allow_cloud_upload=True, quality_policy_path=policy)
            self.assertFalse(passed)
            self.assertTrue(evidence["operational_pass"])
            self.assertEqual(evidence["quality"]["status"], "mismatch")
            self.assertIn("policy", evidence["quality"])
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            policy = self.make_quality_policy(work, manifest)
            passed, evidence = oracle.run_qualification(
                docxs, os.path.join(work, "out"), manifest,
                service_factory=lambda **_kwargs: _Service(),
                roundtrip_fn=lambda svc, path, out: oracle.roundtrip(svc, path, out, media_factory=_media),
                evaluator=lambda *_args, **_kw: {"page_match": True, "live_text_cov": 1.0},
                allow_cloud_upload=True, quality_policy_path=policy)
            self.assertFalse(passed)
            self.assertTrue(evidence["operational_pass"])
            self.assertEqual({f["reason"] for f in evidence["quality"]["findings"]}, {"missing"})

    def test_perverse_or_malformed_policy_rules_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            policy = self.make_quality_policy(work, manifest)
            for metric, rule in (("page_match", {"equals": False}),
                                 ("live_text_cov", {"max": 1.0}),
                                 ("doc_recall", {"min": -0.1}),
                                 ("word_recall", {"min": 1.1}),
                                 ("mean_ssim", {"min": 0.2, "max": 1.0})):
                with open(policy, encoding="utf-8") as fh:
                    payload = json.load(fh)
                payload["tiers"]["ordinary_digital"]["per_document"][metric] = rule
                oracle._atomic_json(policy, payload)
                passed, evidence = oracle.run_qualification(
                    docxs, os.path.join(work, "out_" + metric), manifest,
                    service_factory=lambda **_kwargs: _Service(),
                    roundtrip_fn=lambda svc, path, out: oracle.roundtrip(svc, path, out, media_factory=_media),
                    evaluator=lambda *_args, **_kw: {"page_match": True, "live_text_cov": 1.0,
                                                      "doc_recall": 1.0, "word_recall": 1.0,
                                                      "mean_ssim": 1.0, "dx_p50": 0., "dy_p50": 0.},
                    allow_cloud_upload=True, quality_policy_path=policy)
                self.assertFalse(passed)
                self.assertEqual(evidence["quality"]["status"], "malformed")
                self.make_quality_policy(work, manifest)

    def test_qualification_output_must_stay_outside_prepared_inputs(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            with self.assertRaises(oracle.QualificationError):
                oracle.run_qualification(docxs, os.path.join(docxs, "gdocs"), manifest,
                                         allow_cloud_upload=True)
            self.assertFalse(os.path.exists(os.path.join(docxs, "gdocs")))
            self.assertEqual(oracle.qualification_output_dir(docxs),
                             os.path.abspath(docxs) + ".gdocs-qualification")

    def test_sibling_output_allows_retry_without_mutating_prepared_set(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            out = oracle.qualification_output_dir(docxs)
            before = set(os.listdir(docxs))
            for _ in range(2):
                passed, evidence = oracle.run_qualification(
                    docxs, out, manifest, service_factory=lambda **_kwargs: _Service(),
                    roundtrip_fn=lambda svc, path, rendered: oracle.roundtrip(
                        svc, path, rendered, media_factory=_media),
                    evaluator=lambda *_args, **_kw: {"page_match": True},
                    allow_cloud_upload=True)
                self.assertFalse(passed)  # no real policy can qualify the run
                self.assertTrue(evidence["operational_pass"])
            self.assertEqual(set(os.listdir(docxs)), before)

    def test_preflight_permission_errors_do_not_construct_service_or_leak_paths(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            calls = []
            with mock.patch.object(oracle.os, "listdir", side_effect=PermissionError("private path")):
                passed, evidence = oracle.run_qualification(
                    docxs, os.path.join(work, "out"), manifest,
                    service_factory=lambda **_kwargs: calls.append(True),
                    allow_cloud_upload=True)
            self.assertFalse(passed)
            self.assertEqual(evidence["failure_stage"], "preflight")
            self.assertEqual(calls, [])
            self.assertNotIn(work, json.dumps(evidence))
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            calls = []
            with mock.patch.object(oracle.os, "stat", side_effect=PermissionError("private path")):
                passed, evidence = oracle.run_qualification(
                    docxs, os.path.join(work, "out"), manifest,
                    service_factory=lambda **_kwargs: calls.append(True),
                    allow_cloud_upload=True)
            self.assertFalse(passed)
            self.assertEqual(evidence["failure_stage"], "preflight")
            self.assertEqual(calls, [])
            self.assertNotIn(work, json.dumps(evidence))
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            calls = []
            with mock.patch("builtins.open", side_effect=PermissionError("private path")):
                passed, evidence = oracle.run_qualification(
                    docxs, os.path.join(work, "out"), manifest,
                    service_factory=lambda **_kwargs: calls.append(True),
                    allow_cloud_upload=True)
            self.assertFalse(passed)
            self.assertEqual(evidence["failure_stage"], "preflight")
            self.assertEqual(calls, [])
            self.assertNotIn(work, json.dumps(evidence))

    def test_cli_preflight_permission_error_is_clean_exit_two(self):
        with tempfile.TemporaryDirectory() as work:
            manifest, docxs = self.make_corpus(work)
            stderr = StringIO()
            with mock.patch.object(oracle.os, "listdir", side_effect=PermissionError("private path")), \
                    redirect_stderr(stderr):
                code = oracle.main(["run", docxs, "--manifest", manifest,
                                    "--out", os.path.join(work, "out"),
                                    "--allow-cloud-upload"])
            self.assertEqual(code, 2)
            self.assertIn("error: qualification inputs cannot be accessed (permission denied)",
                          stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertNotIn(work, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
