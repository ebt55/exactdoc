"""The Word oracle's batching and cleanup, with COM mocked out.

`testkit/word_oracle.py` drives desktop Word through a PowerShell worker on the
owner's own machine, where Word may be in use. What must never go wrong is
local and testable without Word: documents are batched into sessions, a hung
document times out and its session's instance is ended ONLY when that instance
is proven ours, an instance holding a document the oracle did not open is left
alone, a window Word shows during a hang stops the sweep, and a failure on the
Python side asks the worker to quit Word rather than orphaning it. The worker is
replaced by a fake that speaks the same line protocol.

    python -m unittest tests.test_word_oracle
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import word_oracle as wo  # noqa: E402


class _FakeProc:
    """A worker: emits `lines`, then exits -- or, with `hang`, blocks until
    killed, like a PowerShell stuck in a COM call."""

    def __init__(self, lines, hang=False):
        self._lines, self._hang = list(lines), hang
        self.killed = threading.Event()
        self.stdout = self._gen()

    def _gen(self):
        for line in self._lines:
            yield line + "\n"
        if self._hang:
            self.killed.wait(30)

    def kill(self):
        self.killed.set()

    def wait(self, timeout=None):
        return 0


class _Hooks:
    """Records every side effect the oracle asks for."""

    def __init__(self, script, alive_after_quit=False, titles=()):
        self.script = script            # f(session_no, jobs) -> (lines, hang)
        self.sessions = []
        self.killed_pids = []
        self.alive_after_quit = alive_after_quit
        self.titles = list(titles)
        self.stop_files = []
        self.clock = time.monotonic
        self.sleep = lambda s: time.sleep(min(s, 0.01))

    def spawn(self, script, jobs_file):
        with open(jobs_file, encoding="utf-8") as f:
            jobs = json.load(f)
        self.sessions.append(jobs)
        lines, hang = self.script(len(self.sessions), jobs, jobs_file, self)
        return _FakeProc(lines, hang)

    def kill_pid(self, pid):
        self.killed_pids.append(pid)

    def pid_alive(self, pid):
        return self.alive_after_quit and pid not in self.killed_pids

    def window_titles(self, pid):
        return self.titles


def _healthy(pid=4242):
    def script(n, jobs, jobs_file, hooks):
        out = ["PID %d" % (pid + n), "ENV 16.0.20430 addins=0 comaddins=0"]
        for j in jobs:
            out.append("BEGIN %d" % j["i"])
            if j["i"] == 0:
                out.append("VERIFIED %d" % (pid + n))
            out.append("DONE %d 3 900" % j["i"])
        out.append("QUIT ok")
        return out, False
    return script


def _pairs(n, d):
    return [(os.path.join(d, "d%02d.docx" % i), os.path.join(d, "d%02d.pdf" % i))
            for i in range(n)]


class WordOracleBatching(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patches = [mock.patch.object(wo, "GAP_TIMEOUT_S", 2),
                   mock.patch.object(wo, "QUIT_GRACE_S", 0.2)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_documents_are_batched_into_sessions(self):
        hooks = _Hooks(_healthy())
        seen = []
        res = wo.render(_pairs(5, self.tmp), self.tmp, batch=2, hooks=hooks,
                        on_result=lambda d, r: seen.append(d))
        self.assertEqual([len(s) for s in hooks.sessions], [2, 2, 1])
        self.assertEqual(len(res), 5)
        self.assertTrue(all(r["pages"] == 3 and r["render_s"] == 0.9 for r in res.values()))
        self.assertEqual(len(seen), 5)
        self.assertEqual(hooks.killed_pids, [], "a clean Quit needs no kill")
        with open(os.path.join(self.tmp, "word_worker.ps1"), encoding="utf-8-sig") as f:
            script = f.read()
        self.assertIn("Documents.Open([string]$j.docx, $false, $true, $false)", script)

    def test_a_hung_document_times_out_and_only_our_instance_is_killed(self):
        def script(n, jobs, jobs_file, hooks):
            if n == 1:                  # document 1 never comes back
                return ["PID 77", "ENV x", "BEGIN 0", "VERIFIED 77", "DONE 0 1 10",
                        "BEGIN 1"], True
            return _healthy(900)(n, jobs, jobs_file, hooks)
        hooks = _Hooks(script)
        res = wo.render(_pairs(4, self.tmp), self.tmp, batch=4, doc_timeout=0.3,
                        hooks=hooks)
        hung = res[os.path.abspath(_pairs(4, self.tmp)[1][0])]
        self.assertTrue(hung.get("hang"))
        self.assertIn("timeout", hung["error"])
        self.assertEqual(hooks.killed_pids, [77])
        # the documents after the hang went to a fresh instance, the hung one did not
        self.assertEqual([j["docx"] for j in hooks.sessions[1]],
                         [os.path.abspath(p[0]) for p in _pairs(4, self.tmp)[2:]])
        self.assertEqual(sum(1 for r in res.values() if "pages" in r), 3)

    def test_an_instance_not_proven_ours_is_never_killed(self):
        def script(n, jobs, jobs_file, hooks):
            if n == 1:                  # two WINWORDs appeared: whose is whose?
                return ["PIDAMBIGUOUS 5,6", "ENV x", "BEGIN 0"], True
            return _healthy()(n, jobs, jobs_file, hooks)
        hooks = _Hooks(script)
        res = wo.render(_pairs(2, self.tmp), self.tmp, doc_timeout=0.3, hooks=hooks)
        self.assertEqual(hooks.killed_pids, [])
        self.assertTrue(res[os.path.abspath(_pairs(2, self.tmp)[0][0])]["hang"])

    def test_a_window_mismatch_revokes_the_proof(self):
        def script(n, jobs, jobs_file, hooks):
            return ["PID 8", "ENV x", "BEGIN 0", "MISMATCH 9"], True
        hooks = _Hooks(script)
        res = wo.render(_pairs(1, self.tmp), self.tmp, doc_timeout=0.2, hooks=hooks)
        self.assertTrue(res[os.path.abspath(_pairs(1, self.tmp)[0][0])]["hang"])
        self.assertEqual(hooks.killed_pids, [], "pid 8 does not own the window")

    def test_a_document_we_did_not_open_stops_the_sweep_and_is_left_alone(self):
        def script(n, jobs, jobs_file, hooks):
            return ["PID 31", "ENV x", "BEGIN 0", "VERIFIED 31", "DONE 0 2 5",
                    "FOREIGN", "FOREIGNKEPT"], False
        hooks = _Hooks(script, alive_after_quit=True)
        with self.assertRaises(wo.WordDialog):
            wo.render(_pairs(3, self.tmp), self.tmp, hooks=hooks)
        self.assertEqual(hooks.killed_pids, [], "the user's document must survive")
        self.assertEqual(len(hooks.sessions), 1)

    def test_a_dialog_during_a_hang_is_reported_and_stops_the_sweep(self):
        def script(n, jobs, jobs_file, hooks):
            return ["PID 12", "ENV x", "BEGIN 0", "VERIFIED 12"], True
        hooks = _Hooks(script, titles=["Microsoft Word"])
        with self.assertRaises(wo.WordDialog) as cm:
            wo.render(_pairs(3, self.tmp), self.tmp, doc_timeout=0.3, hooks=hooks)
        self.assertIn("Microsoft Word", str(cm.exception))
        self.assertEqual(hooks.killed_pids, [12])
        self.assertEqual(len(hooks.sessions), 1, "never retried behind a dialog")

    def test_word_that_will_not_start_twice_is_unavailable(self):
        def script(n, jobs, jobs_file, hooks):
            return ["SESSIONFAIL Retrieving the COM class factory failed"], False
        hooks = _Hooks(script)
        with self.assertRaises(wo.WordUnavailable):
            wo.render(_pairs(3, self.tmp), self.tmp, hooks=hooks)
        self.assertEqual(len(hooks.sessions), 2)

    def test_a_startup_hang_is_bounded(self):
        def script(n, jobs, jobs_file, hooks):
            return [], True
        hooks = _Hooks(script)
        t0 = time.monotonic()
        with self.assertRaises(wo.WordUnavailable):
            wo.render(_pairs(1, self.tmp), self.tmp, start_timeout=0.2, hooks=hooks)
        self.assertLess(time.monotonic() - t0, 10)

    def test_an_instance_outliving_quit_is_ended(self):
        hooks = _Hooks(_healthy(500), alive_after_quit=True)
        wo.render(_pairs(1, self.tmp), self.tmp, hooks=hooks)
        self.assertEqual(hooks.killed_pids, [501])

    def test_a_failure_on_this_side_asks_the_worker_to_quit_word(self):
        state = {}

        def script(n, jobs, jobs_file, hooks):
            state["stop"] = jobs_file + ".stop"
            return ["PID 40", "ENV x", "BEGIN 0", "DONE 0 1 5", "STOPPED", "QUIT ok"], False

        def boom(line):                 # a bug while reading the protocol
            if "DONE" in line:
                raise RuntimeError("parser crashed")
        hooks = _Hooks(script)
        with self.assertRaises(RuntimeError):
            wo.render(_pairs(3, self.tmp), self.tmp, hooks=hooks, log=boom)
        self.assertTrue(os.path.exists(state["stop"]))
        self.assertEqual(hooks.killed_pids, [], "the worker quit Word itself")


class WordOracleSurface(unittest.TestCase):
    def test_unavailable_off_windows(self):
        with mock.patch.object(wo.sys, "platform", "linux"):
            self.assertFalse(wo.available())
            with redirect_stdout(StringIO()) as out:
                self.assertEqual(wo.main(["sweep", tempfile.mkdtemp(), "--profile", "raw"]), 0)
            self.assertIn("SKIP", out.getvalue())

    def test_worker_script_is_read_only_and_always_quits(self):
        s = wo.WORKER_PS1
        self.assertIn("$w.DisplayAlerts = 0", s)
        self.assertIn("$w.AutomationSecurity = 3", s)
        self.assertIn("$w.Quit([ref]0)", s)
        self.assertIn("} finally {", s)
        self.assertNotIn(".Options.", s, "Word persists Options; never touch them")
        self.assertNotIn(".Save(", s)
        self.assertIn("$before -notcontains $_", s)

    def test_rows_report_what_word_saw(self):
        def script(n, jobs, jobs_file, hooks):
            return ["PID 3", "ENV 16.0.20430 addins=0 comaddins=0", "BEGIN 0",
                    "OPENED 0 14", "VERIFIED 3", "DONE 0 2 100",
                    "BEGIN 1", "FAIL 1 Word found unreadable content in x.docx",
                    "QUIT ok"], False
        tmp = tempfile.mkdtemp()
        res = wo.render(_pairs(2, tmp), tmp, hooks=_Hooks(script))
        ok, bad = (res[os.path.abspath(p[0])] for p in _pairs(2, tmp))
        self.assertEqual((ok["opened"], ok["compat_mode"], ok["word_version"],
                          ok["repair_prompt"]), (True, 14, "16.0.20430", False))
        self.assertEqual((bad["opened"], bad["repair_prompt"]), (False, True))

    def test_font_census_and_stock_view(self):
        import zipfile
        import docx
        tmp = tempfile.mkdtemp()
        d = docx.Document()
        for face, text in (("Figtree", "designed"), ("Arial", "plain text")):
            r = d.add_paragraph().add_run(text)
            r.font.name = face
        src = os.path.join(tmp, "f.docx")
        d.save(src)
        fonts = wo.declared_fonts(src)
        self.assertEqual(fonts["Figtree"], len("designed"))
        self.assertEqual(fonts["Arial"], len("plain text"))
        self.assertIn("Figtree", wo.absent_fonts(fonts))
        self.assertNotIn("Arial", wo.absent_fonts(fonts))
        out = os.path.join(tmp, "g.docx")
        self.assertIn("Figtree", wo.stock_view(src, out))
        with zipfile.ZipFile(out) as z:
            body = z.read("word/document.xml").decode("utf-8")
        self.assertIn('w:ascii="%s"' % wo.absent_name("Figtree"), body)
        self.assertNotIn("Figtree", body)
        self.assertIn('w:ascii="Arial"', body)
        # the copy is what Word would be handed; the original is untouched
        self.assertIn("Figtree", wo.declared_fonts(src))

    def test_summary_has_the_beta_bar_shape(self):
        rows = [
            {"doc": "a.pdf", "tier": "ordinary_digital", "src_pages": 2, "out_pages": 2,
             "char_recall": 1.0, "word_recall": 1.0},
            {"doc": "b.pdf", "tier": "ordinary_digital", "src_pages": 4, "out_pages": 5,
             "char_recall": 0.6, "word_recall": 0.5},
            {"doc": "c.pdf", "tier": "scanned", "src_pages": 1, "out_pages": 1,
             "char_recall": 0.97, "word_recall": 0.9},
            {"doc": "d.pdf", "tier": "ordinary_digital", "error": "timeout", "hang": True},
        ]
        s = wo.summarise(rows)
        self.assertEqual(s["ordinary_digital_page_exact"], 1)
        self.assertEqual(s["ordinary_digital"], 2)
        self.assertEqual(s["char_recall_ge_095"], 2)
        self.assertEqual(s["char_recall_ge_095_share"], round(2 / 3, 3))
        self.assertEqual(s["hangs"], 1)
        self.assertEqual(s["worst"][0]["doc"], "b.pdf")


if __name__ == "__main__":
    unittest.main()
