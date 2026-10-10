"""A worker that dies is the document's crash, unless the pool itself died (WP43).

quality_sweep.py used to record any failure out of its process pool as
"worker: <exception>", and beta_readiness read every "worker: " row as
infrastructure -- so a document that segfaulted its worker never counted
against criterion 1. Now a worker that RAISES is that document's crash; a
pool that DIES (BrokenProcessPool takes every document in flight) has its
documents run again, each in a process of its own: the one whose process
dies alone is the crash, with its exit code, and the rest get their real rows.

The stand-in workers below are module-level so a spawned child can import them.

    python -m unittest tests.test_worker_failures
"""
import io
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import beta_readiness as B  # noqa: E402
import quality_sweep as qs  # noqa: E402


def _stand_in(job):
    """'die' kills its own process; 'raise' raises; anything else succeeds."""
    doc = job[0]
    if doc.startswith("die"):
        os._exit(7)
    if doc.startswith("raise"):
        raise ValueError("boom in %s" % doc)
    return {"document": doc, "src_pages": 1, "out_pages": 1}


def _job(doc):
    return (doc, doc, "ordinary_digital", "x", "product", "out", False)


class AloneInItsOwnProcess(unittest.TestCase):
    def test_outcomes(self):
        self.assertEqual(qs._work_alone(_job("ok.pdf"), _stand_in)[:2],
                         ("ok", {"document": "ok.pdf", "src_pages": 1, "out_pages": 1}))
        self.assertEqual(qs._work_alone(_job("raise.pdf"), _stand_in)[:2],
                         ("raised", "ValueError: boom in raise.pdf"))
        self.assertEqual(qs._work_alone(_job("die.pdf"), _stand_in), ("died", None, 7))


class ThePool(unittest.TestCase):
    def _run(self, docs, jobs=2):
        with mock.patch("sys.stdout", new=io.StringIO()):
            return {r["document"]: r for r in qs._run_all([_job(d) for d in docs], jobs,
                                                         work=_stand_in)}

    def test_a_worker_that_raises_is_that_documents_crash(self):
        rows = self._run(["a.pdf", "raise.pdf"])
        self.assertNotIn("error", rows["a.pdf"])
        r = rows["raise.pdf"]
        self.assertTrue(r["error"].startswith("worker crashed: ValueError"))
        self.assertEqual(r["worker_failure"], {"type": "ValueError", "pool_broken": False})
        self.assertEqual(B.classify_failure(r), "crash")

    def test_a_dying_worker_is_found_and_the_rest_measured(self):
        rows = self._run(["a.pdf", "b.pdf", "die.pdf", "c.pdf"], jobs=2)
        die = rows["die.pdf"]
        self.assertIn("died alone (exit code 7)", die["error"])
        self.assertEqual((die["worker_failure"]["exitcode"],
                          die["worker_failure"]["pool_broken"]), (7, False))
        self.assertEqual(B.classify_failure(die), "crash")
        for d in ("a.pdf", "b.pdf", "c.pdf"):
            self.assertNotIn("error", rows[d], d)        # collateral, re-measured
        self.assertEqual(len(rows), 4)


class TheScorecard(unittest.TestCase):
    def test_classification(self):
        cases = [
            ({"error": "worker crashed: KeyError: 'x'",
              "worker_failure": {"type": "KeyError", "pool_broken": False}}, "crash"),
            ({"error": "worker: pool died (...); rerun alone impossible",
              "worker_failure": {"type": "BrokenProcessPool", "pool_broken": True}}, "infra"),
            # rows written before WP43
            ({"error": "worker: BrokenProcessPool('A process in the process pool "
                       "was terminated abruptly')"}, "infra"),
            ({"error": "worker: KeyError('x')"}, "crash"),
            ({"error": "RoundtripError: upload failed"}, "infra"),
        ]
        for row, want in cases:
            self.assertEqual(B.classify_failure(row), want, row)


if __name__ == "__main__":
    unittest.main()
