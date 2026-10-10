"""One Word batch on the machine at a time, enforced by the oracle (WP43).

word_oracle.sweep holds a named kernel mutex for the whole batch and still
honours and writes C:\\lotmp\\word.lock for agents on older trees: a lock file
that exists, is younger than 30 minutes and is not ours is waited for, and on
exit only a lock file this batch wrote (it still carries our token) is
deleted. Nothing here needs Word; the mutex tests need Windows.

    python -m unittest tests.test_word_lock
"""
import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import word_oracle as W  # noqa: E402


class Clock(object):
    """A clock that `sleep` advances, so waiting costs no real time."""

    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class TheLockFile(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._td.name, "word.lock")

    def tearDown(self):
        self._td.cleanup()

    def _lock(self, **kw):
        clock = kw.pop("clock", None) or Clock()
        return W.WordBatchLock(path=self.path, mutex=None, clock=clock, sleep=clock.sleep,
                               say=lambda s: None, **kw)

    def _foreign(self, age_s, text="WP99"):
        with open(self.path, "w") as fh:
            fh.write(text)
        t = time.time() - age_s
        os.utime(self.path, (t, t))

    def test_written_and_removed_by_its_batch(self):
        lock = self._lock()
        with lock:
            with open(self.path) as fh:
                self.assertEqual(fh.read().strip(), lock.token)
        self.assertFalse(os.path.exists(self.path))

    def test_a_fresh_foreign_lock_is_waited_for_then_refused(self):
        self._foreign(age_s=60)
        with self.assertRaises(W.WordBusy):
            with self._lock(wait_s=120, poll_s=10):
                self.fail("entered while another batch held the lock")
        with open(self.path) as fh:
            self.assertEqual(fh.read(), "WP99")      # never ours, never deleted

    def test_a_foreign_lock_released_while_waiting(self):
        self._foreign(age_s=60)
        clock = Clock()

        def sleep(s):
            clock.sleep(s)
            if os.path.exists(self.path):
                os.remove(self.path)                  # the other batch finishes
        lock = W.WordBatchLock(path=self.path, mutex=None, clock=clock, sleep=sleep,
                               say=lambda s: None, wait_s=600, poll_s=10)
        with lock:
            self.assertTrue(lock.wrote_file)
        self.assertFalse(os.path.exists(self.path))

    def test_a_stale_lock_is_not_honoured(self):
        self._foreign(age_s=31 * 60)
        with self._lock(wait_s=0):
            pass
        self.assertFalse(os.path.exists(self.path))   # replaced by ours, then removed

    def test_a_lock_someone_else_rewrote_is_left_alone(self):
        lock = self._lock()
        with lock:
            with open(self.path, "w") as fh:
                fh.write("WP42 took over")
        with open(self.path) as fh:
            self.assertEqual(fh.read(), "WP42 took over")

    def test_sweep_holds_the_lock_for_the_whole_batch(self):
        seen = {}
        lock = self._lock()

        def body(*a, **k):
            seen["held"] = os.path.exists(self.path)
            return "rows.jsonl"
        with mock.patch.object(W, "available", return_value=True), \
                mock.patch.object(W, "_sweep", side_effect=body):
            self.assertEqual(W.sweep("out", lock=lock), "rows.jsonl")
        self.assertTrue(seen["held"])
        self.assertFalse(os.path.exists(self.path))


@unittest.skipUnless(os.name == "nt", "a Windows named mutex")
class TheMutex(unittest.TestCase):
    def test_a_second_holder_waits_and_is_refused(self):
        name = "Local\\exactdoc-test-%s" % uuid.uuid4().hex
        d = tempfile.mkdtemp()
        first = W.WordBatchLock(path=os.path.join(d, "a.lock"), mutex=name,
                                say=lambda s: None)
        got = {}

        def second():
            try:
                with W.WordBatchLock(path=os.path.join(d, "b.lock"), mutex=name,
                                     wait_s=0.5, poll_s=0.1, say=lambda s: None):
                    got["entered"] = True
            except W.WordBusy:
                got["busy"] = True
        with first:
            t = threading.Thread(target=second)
            t.start()
            t.join(10)
        self.assertEqual(got, {"busy": True})
        # released: the next one gets it
        t = threading.Thread(target=second)
        t.start()
        t.join(10)
        self.assertEqual(got, {"busy": True, "entered": True})


if __name__ == "__main__":
    unittest.main()
