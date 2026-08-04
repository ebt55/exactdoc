"""Contracts for the live-pass prediction comparator.

Run with ``python tests/test_livepass_verify.py``.  Every case is synthetic
evidence built in a temp directory: the comparator must never need a corpus, a
renderer, or a network, and these tests would fail loudly if it did.
"""
import json
import os
import socket
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import livepass_verify as V  # noqa: E402


def _predictions(**over):
    """Two discriminating documents, one that cannot discriminate."""
    payload = {
        "schema": V.SCHEMA,
        "claim": {"id": "A-approx-zero", "statement": "Docs adds ~0pt"},
        "baseline_evidence": {"sha256": "0" * 64, "state": "pre-fix"},
        "tolerance": {"default_pt": 4.0},
        "falsification_rule": {
            "statement": "two or more discriminating documents above threshold",
            "min_documents_to_falsify": 2,
            "discriminating_documents": ["D1", "D2"],
        },
        "documents": {
            "D1": {"tier": "ordinary_digital", "baseline_dy_p50": 26.0,
                   "predicted_dy_p50": 2.0, "tolerance_pt": 4.0,
                   "discriminating": True, "falsifies_A0_above_pt": 14.0,
                   "expect": "improves"},
            "D2": {"tier": "ordinary_digital", "baseline_dy_p50": 12.0,
                   "predicted_dy_p50": 1.0, "tolerance_pt": 4.0,
                   "discriminating": True, "falsifies_A0_above_pt": 6.5,
                   "expect": "improves"},
            "N1": {"tier": "ordinary_digital", "baseline_dy_p50": 5.0,
                   "predicted_dy_p50": 4.0, "tolerance_pt": 4.0,
                   "discriminating": False, "falsifies_A0_above_pt": None,
                   "expect": "improves"},
        },
        "checks": [
            {"id": "dy", "kind": "dy_prediction", "documents": ["D1", "D2"],
             "bound_pt": 10.0, "description": "d"},
            {"id": "pm", "kind": "page_match", "documents": ["D1"],
             "description": "p"},
            {"id": "adv", "kind": "dy_prediction", "documents": ["N1"],
             "bound_pt": 10.0, "advisory": True, "description": "a"},
        ],
    }
    payload.update(over)
    return payload


def _evidence(d1, d2, n1, page_match=True):
    def row(name, dy):
        return {"docx": name + ".docx",
                "metrics": {"dy_p50": dy, "page_match": page_match,
                            "mean_ssim": 0.8, "dx_p50": 1.0}}
    return {"candidate_profile": "pdfium/gdocs/none/refine0@240dpi",
            "documents": [row("D1", d1), row("D2", d2), row("N1", n1)]}


class LivePassVerifyTests(unittest.TestCase):
    def _write(self, root, preds, evid):
        p = os.path.join(root, "preds.json")
        e = os.path.join(root, "evidence.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(preds, fh)
        with open(e, "w", encoding="utf-8") as fh:
            json.dump(evid, fh)
        return p, e

    def _grade(self, root, preds, evid):
        p, e = self._write(root, preds, evid)
        loaded = V.load_predictions(p)
        evidence, by_name, digest = V.load_evidence(e)
        return V.grade(loaded, evidence, by_name, digest), p, e

    # ------------------------------------------------------------ pre-fix
    def test_pre_fix_by_recorded_hash_is_not_graded(self):
        with tempfile.TemporaryDirectory() as work:
            evid = _evidence(26.0, 12.0, 5.0)
            p, e = self._write(work, _predictions(), evid)
            with open(e, "rb") as fh:
                import hashlib
                digest = hashlib.sha256(fh.read()).hexdigest()
            preds = _predictions()
            preds["baseline_evidence"]["sha256"] = digest
            report, _, e2 = self._grade(work, preds, evid)
            self.assertEqual(report["state"], "pre-fix")
            self.assertTrue(report["falsification"]["skipped"])
            self.assertFalse(report["falsification"]["falsified"])
            # every row is relabelled, and nothing is scored as a miss
            self.assertEqual({r["verdict"] for r in report["documents"]},
                             {"baseline"})
            self.assertEqual({c["status"] for c in report["checks"]}, {"baseline"})
            self.assertEqual(V.main([e2, "--predictions", p]), V.EXIT_OK)

    def test_a_superseded_baseline_still_grades_as_baseline(self):
        """Once a claim is settled the baseline moves forward.

        The older evidence is still the run an earlier set of predictions was
        measured from, so re-grading it must report a baseline rather than a
        wall of missed predictions.
        """
        import hashlib
        with tempfile.TemporaryDirectory() as work:
            evid = _evidence(2.0, 1.0, 3.8)      # nothing like the baselines
            p, e = self._write(work, _predictions(), evid)
            with open(e, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            preds = _predictions()
            preds["superseded_baselines"] = [
                {"sha256": digest, "state": "pass 1, pre-boundary-fix"}]
            report, _, e2 = self._grade(work, preds, evid)
            self.assertEqual(report["state"], "pre-fix")
            self.assertIn("superseded baseline", report["state_reason"])
            self.assertTrue(report["falsification"]["skipped"])
            self.assertEqual(V.main([e2, "--predictions",
                                     self._write(work, preds, evid)[0]]),
                             V.EXIT_OK)

    def test_pre_fix_detected_by_values_when_hash_differs(self):
        # The recorded hash breaks the moment anyone reformats the file, so the
        # value agreement has to stand on its own.
        with tempfile.TemporaryDirectory() as work:
            report, _, _ = self._grade(work, _predictions(),
                                       _evidence(26.0, 12.0, 5.0))
            self.assertEqual(report["state"], "pre-fix")
            self.assertIn("baseline", report["state_reason"])

    def test_the_majority_heuristic_still_applies_with_no_movers(self):
        # nothing is predicted to move, so only the majority vote is left
        with tempfile.TemporaryDirectory() as work:
            preds = _predictions()
            for spec in preds["documents"].values():
                spec["predicted_dy_p50"] = spec["baseline_dy_p50"]
            report, _, _ = self._grade(work, preds, _evidence(26.0, 12.0, 5.0))
            self.assertEqual(report["state"], "pre-fix")
            self.assertIn("still report their pre-fix", report["state_reason"])

    def test_untouched_documents_cannot_outvote_a_document_that_moved(self):
        """The wart live pass 3 exposed.

        A pass typically changes a few documents and leaves the rest byte-
        identical, so "most documents reproduce their baseline" is the normal
        shape of a POST-fix run. Pass 3 had 13 of 16 untouched and their
        unanimous vote outranked a sha that already said post-fix. Only the
        documents a prediction expects to move can tell the two states apart.
        """
        with tempfile.TemporaryDirectory() as work:
            preds = _predictions()
            # D1 is expected to move 26 -> 2; D2 and N1 are not expected to move
            preds["documents"]["D2"]["predicted_dy_p50"] = 12.0
            preds["documents"]["N1"]["predicted_dy_p50"] = 5.0
            # D1 moved, the other two sit on their baselines
            report, _, _ = self._grade(work, preds, _evidence(2.0, 12.0, 5.0))
            self.assertEqual(report["state"], "post-fix")
            self.assertIn("D1 moved off its baseline", report["state_reason"])

    def test_a_run_where_nothing_expected_to_move_moved_is_pre_fix(self):
        with tempfile.TemporaryDirectory() as work:
            preds = _predictions()
            preds["documents"]["D2"]["predicted_dy_p50"] = 12.0
            preds["documents"]["N1"]["predicted_dy_p50"] = 5.0
            report, _, _ = self._grade(work, preds, _evidence(26.0, 12.0, 5.0))
            self.assertEqual(report["state"], "pre-fix")
            self.assertIn("expect to move is still on its baseline",
                          report["state_reason"])

    def test_pre_fix_reports_how_far_each_document_must_move(self):
        with tempfile.TemporaryDirectory() as work:
            report, _, _ = self._grade(work, _predictions(),
                                       _evidence(26.0, 12.0, 5.0))
            moves = {r["document"]: r.get("expected_move")
                     for r in report["documents"]}
            self.assertEqual(moves["D1"], -24.0)
            self.assertEqual(moves["D2"], -11.0)

    # ----------------------------------------------------------- post-fix
    def test_predictions_met_leaves_the_claim_standing(self):
        with tempfile.TemporaryDirectory() as work:
            report, p, e = self._grade(work, _predictions(),
                                       _evidence(2.1, 1.2, 3.8))
            self.assertEqual(report["state"], "post-fix")
            self.assertFalse(report["falsification"]["falsified"])
            self.assertEqual(report["falsification"]["exceeded"], [])
            self.assertEqual({r["verdict"] for r in report["documents"]}, {"pass"})
            self.assertEqual(V.main([e, "--predictions", p]), V.EXIT_OK)
            self.assertEqual(V.main([e, "--predictions", p, "--strict"]), V.EXIT_OK)

    def test_two_discriminating_documents_above_threshold_falsify(self):
        with tempfile.TemporaryDirectory() as work:
            # both stay at their pre-fix magnitude: what A~3 predicts
            report, p, e = self._grade(work, _predictions(),
                                       _evidence(25.0, 11.5, 3.8))
            self.assertEqual(report["state"], "post-fix")
            self.assertTrue(report["falsification"]["falsified"])
            self.assertEqual(sorted(report["falsification"]["exceeded"]),
                             ["D1", "D2"])
            self.assertEqual(V.main([e, "--predictions", p]), V.EXIT_FALSIFIED)

    def test_one_discriminating_document_warns_but_does_not_falsify(self):
        with tempfile.TemporaryDirectory() as work:
            report, p, e = self._grade(work, _predictions(),
                                       _evidence(25.0, 1.2, 3.8))
            self.assertFalse(report["falsification"]["falsified"])
            self.assertTrue(report["falsification"]["warn_single"])
            self.assertEqual(report["falsification"]["exceeded"], ["D1"])
            self.assertEqual(V.main([e, "--predictions", p]), V.EXIT_OK)
            self.assertIn("with a warning",
                          V.render(report, _predictions()))

    def test_a_non_discriminating_document_can_never_falsify(self):
        # N1 far off its prediction, both discriminating documents on target.
        with tempfile.TemporaryDirectory() as work:
            report, p, e = self._grade(work, _predictions(),
                                       _evidence(2.0, 1.0, 90.0))
            self.assertFalse(report["falsification"]["falsified"])
            self.assertEqual(V.main([e, "--predictions", p]), V.EXIT_OK)

    # ------------------------------------------------------------- strict
    def test_strict_fails_on_a_non_advisory_miss_only(self):
        with tempfile.TemporaryDirectory() as work:
            # D2 misses its prediction but stays under its falsification
            # threshold: the claim survives, the model was inaccurate.
            preds, evid = _predictions(), _evidence(2.0, 6.0, 3.8)
            p, e = self._write(work, preds, evid)
            self.assertEqual(V.main([e, "--predictions", p]), V.EXIT_OK)
            self.assertEqual(V.main([e, "--predictions", p, "--strict"]),
                             V.EXIT_MISSED)

    def test_strict_ignores_advisory_checks(self):
        with tempfile.TemporaryDirectory() as work:
            # only N1 (advisory check) is wrong
            preds, evid = _predictions(), _evidence(2.0, 1.0, 9.5)
            p, e = self._write(work, preds, evid)
            self.assertEqual(V.main([e, "--predictions", p, "--strict"]),
                             V.EXIT_OK)

    def test_strict_never_fires_on_pre_fix_evidence(self):
        with tempfile.TemporaryDirectory() as work:
            preds, evid = _predictions(), _evidence(26.0, 12.0, 5.0)
            p, e = self._write(work, preds, evid)
            self.assertEqual(V.main([e, "--predictions", p, "--strict"]),
                             V.EXIT_OK)

    # -------------------------------------------------------------- checks
    def test_page_match_regression_is_reported(self):
        with tempfile.TemporaryDirectory() as work:
            report, _, _ = self._grade(work, _predictions(),
                                       _evidence(2.0, 1.0, 3.8, page_match=False))
            pm = [c for c in report["checks"] if c["id"] == "pm"][0]
            self.assertEqual(pm["status"], "miss")

    def test_absent_document_is_incomplete_not_a_crash(self):
        with tempfile.TemporaryDirectory() as work:
            evid = _evidence(2.0, 1.0, 3.8)
            evid["documents"] = [r for r in evid["documents"]
                                 if not r["docx"].startswith("D2")]
            report, _, _ = self._grade(work, _predictions(), evid)
            row = [r for r in report["documents"] if r["document"] == "D2"][0]
            self.assertEqual(row["verdict"], "absent")
            dy = [c for c in report["checks"] if c["id"] == "dy"][0]
            self.assertEqual(dy["status"], "incomplete")
            self.assertFalse(report["falsification"]["falsified"])

    def test_metric_and_page_ssim_checks(self):
        with tempfile.TemporaryDirectory() as work:
            preds = _predictions()
            preds["checks"] = [
                {"id": "ssim", "kind": "metric_improves", "document": "D1",
                 "metric": "mean_ssim", "baseline": 0.65, "direction": "up",
                 "description": "s"},
                {"id": "split", "kind": "page_ssim_split", "document": "D1",
                 "unchanged_pages": {"1": 0.60}, "unchanged_tolerance": 0.05,
                 "improved_pages": {"2": 0.70}, "description": "x"},
            ]
            evid = _evidence(2.0, 1.0, 3.8)
            evid["documents"][0]["metrics"]["pages"] = [
                {"page": 1, "ssim": 0.61}, {"page": 2, "ssim": 0.75}]
            report, _, _ = self._grade(work, preds, evid)
            status = {c["id"]: c["status"] for c in report["checks"]}
            self.assertEqual(status["ssim"], "pass")
            self.assertEqual(status["split"], "pass")

            evid["documents"][0]["metrics"]["mean_ssim"] = 0.4
            evid["documents"][0]["metrics"]["pages"] = [
                {"page": 1, "ssim": 0.61}, {"page": 2, "ssim": 0.62}]
            report, _, _ = self._grade(work, preds, evid)
            status = {c["id"]: c["status"] for c in report["checks"]}
            self.assertEqual(status["ssim"], "miss")
            self.assertEqual(status["split"], "miss")

    # ------------------------------------------------------------- inputs
    def test_metric_max_check_grades_a_capped_metric(self):
        with tempfile.TemporaryDirectory() as work:
            preds = _predictions()
            preds["checks"] = [{"id": "cap", "kind": "metric_max",
                                "document": "D1", "metric": "dx_p50",
                                "max": 10.0, "description": "c"}]
            evid = _evidence(2.0, 1.0, 3.8)
            report, _, _ = self._grade(work, preds, evid)
            self.assertEqual(report["checks"][0]["status"], "pass")

            evid["documents"][0]["metrics"]["dx_p50"] = 63.65
            report, _, _ = self._grade(work, preds, evid)
            self.assertEqual(report["checks"][0]["status"], "miss")
            self.assertIn("OVER", report["checks"][0]["details"][0])

            del evid["documents"][0]["metrics"]["dx_p50"]
            report, _, _ = self._grade(work, preds, evid)
            self.assertEqual(report["checks"][0]["status"], "incomplete")

    def test_malformed_inputs_are_usage_errors_not_verdicts(self):
        with tempfile.TemporaryDirectory() as work:
            good_e = os.path.join(work, "e.json")
            with open(good_e, "w", encoding="utf-8") as fh:
                json.dump(_evidence(2.0, 1.0, 3.8), fh)

            bad = os.path.join(work, "bad.json")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            self.assertEqual(V.main([good_e, "--predictions", bad]), V.EXIT_USAGE)
            self.assertEqual(V.main([bad]), V.EXIT_USAGE)
            self.assertEqual(V.main([os.path.join(work, "absent.json")]),
                             V.EXIT_USAGE)

            wrong = os.path.join(work, "wrong.json")
            preds = _predictions()
            preds["schema"] = "something.else.v9"
            with open(wrong, "w", encoding="utf-8") as fh:
                json.dump(preds, fh)
            self.assertEqual(V.main([good_e, "--predictions", wrong]), V.EXIT_USAGE)

            for missing in ("documents", "checks", "claim", "falsification_rule"):
                path = os.path.join(work, "m_%s.json" % missing)
                payload = _predictions()
                del payload[missing]
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
                with self.assertRaises(V.VerifyError):
                    V.load_predictions(path)

            empty = os.path.join(work, "empty.json")
            with open(empty, "w", encoding="utf-8") as fh:
                json.dump({"documents": []}, fh)
            with self.assertRaises(V.VerifyError):
                V.load_evidence(empty)

    def test_grading_opens_no_socket(self):
        with tempfile.TemporaryDirectory() as work:
            preds, evid = _predictions(), _evidence(2.0, 1.0, 3.8)
            p, e = self._write(work, preds, evid)
            with mock.patch.object(socket, "socket",
                                   side_effect=AssertionError("offline")):
                self.assertEqual(V.main([e, "--predictions", p]), V.EXIT_OK)


class CommittedPredictionsTests(unittest.TestCase):
    """The data file is the artefact under review; keep it self-consistent."""

    def setUp(self):
        self.preds = V.load_predictions()

    def test_discriminating_documents_agree_with_the_rule(self):
        flagged = {n for n, s in self.preds["documents"].items()
                   if s.get("discriminating")}
        listed = set(self.preds["falsification_rule"]["discriminating_documents"])
        self.assertEqual(flagged, listed)

    def test_every_discriminating_threshold_is_the_stated_midpoint(self):
        for name in self.preds["falsification_rule"]["discriminating_documents"]:
            spec = self.preds["documents"][name]
            mid = (spec["baseline_dy_p50"] + spec["predicted_dy_p50"]) / 2.0
            self.assertAlmostEqual(spec["falsifies_A0_above_pt"], mid, places=2,
                                   msg="%s threshold is not the midpoint" % name)

    def test_only_well_separated_documents_may_discriminate(self):
        # The rule says >=8pt of separation; a document that cannot tell the
        # two models apart must not be allowed to condemn either.
        for name, spec in self.preds["documents"].items():
            pred = spec.get("predicted_dy_p50")
            if pred is None:
                self.assertFalse(spec.get("discriminating"))
                continue
            sep = spec["baseline_dy_p50"] - pred
            if spec.get("discriminating"):
                self.assertGreaterEqual(sep, 8.0, "%s separation too small" % name)
            else:
                self.assertIsNone(spec.get("falsifies_A0_above_pt"))

    def test_checks_only_reference_documents_that_exist(self):
        known = set(self.preds["documents"])
        for check in self.preds["checks"]:
            named = list(check.get("documents", []))
            if check.get("document"):
                named.append(check["document"])
            for name in named:
                self.assertIn(name, known,
                              "check %s names unknown %s" % (check["id"], name))

    def test_documents_without_a_prediction_declare_why(self):
        for name, spec in self.preds["documents"].items():
            if spec.get("predicted_dy_p50") is None:
                self.assertEqual(spec.get("expect"), "no-prediction")
                self.assertTrue(spec.get("note"), "%s must say why" % name)

    def test_the_recorded_baseline_run_grades_as_pre_fix(self):
        """The 2026-08-04 evidence must never read as a falsification.

        It is the run the predictions were measured FROM. If a future edit made
        the comparator grade it, every predicted improvement would be reported
        as a failed prediction and the claim would look dead on arrival.
        """
        with tempfile.TemporaryDirectory() as work:
            # reconstruct just enough of that run from the committed baselines
            rows = []
            for name, spec in self.preds["documents"].items():
                rows.append({"docx": name + ".docx",
                             "metrics": {"dy_p50": spec["baseline_dy_p50"],
                                         "page_match": True}})
            path = os.path.join(work, "evidence.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"documents": rows}, fh)
            evidence, by_name, digest = V.load_evidence(path)
            report = V.grade(self.preds, evidence, by_name, digest)
            self.assertEqual(report["state"], "pre-fix")
            self.assertTrue(report["falsification"]["skipped"])
            self.assertEqual(V.main([path]), V.EXIT_OK)
            self.assertEqual(V.main([path, "--strict"]), V.EXIT_OK)


if __name__ == "__main__":
    unittest.main()
