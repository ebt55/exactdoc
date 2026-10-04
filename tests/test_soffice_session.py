"""The LibreOffice session: one kept profile, a short root, retries, no orphans.

`verify.SofficeSession` replaced a fresh-profile cold start per render. These
tests drive it against a fake `soffice` -- a shell script that records how it
was called and then writes a PDF, writes nothing, or hangs with a child -- so
the session's own behaviour is what is under test, not LibreOffice's.

POSIX-only for the process tests (the fake is a shell script and the tree kill
is a process-group kill there); the short-root choice is tested everywhere.
"""
import os
import stat
import tempfile
import textwrap
import time
import unittest
from unittest import mock

from exactdoc import verify as V

FAKE = textwrap.dedent("""\
    #!/bin/sh
    # fake soffice: log the profile, then act per $FAKE_MODE
    prof=""; outdir=""; src=""; prev=""
    for a in "$@"; do
      case "$a" in -env:UserInstallation=*) prof="${a#-env:UserInstallation=}";; esac
      if [ "$prev" = "--outdir" ]; then outdir="$a"; fi
      prev="$a"; src="$a"
    done
    echo "$prof" >> "$FAKE_LOG"
    n=$(wc -l < "$FAKE_LOG")
    stem=$(basename "$src" .docx)
    case "$FAKE_MODE" in
      ok) printf '%%PDF-1.4 fake' > "$outdir/$stem.pdf" ;;
      second) if [ "$n" -ge 2 ]; then printf '%%PDF-1.4 fake' > "$outdir/$stem.pdf"; fi ;;
      nothing) : ;;
      hang) sleep 300 & echo $! > "$FAKE_CHILD"; wait ;;
    esac
    exit 0
""")


@unittest.skipUnless(os.name == "posix", "the fake soffice is a shell script")
class SessionProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.fake = os.path.join(d, "soffice")
        with open(self.fake, "w") as fh:
            fh.write(FAKE)
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IEXEC)
        self.log = os.path.join(d, "calls.log")
        self.child = os.path.join(d, "child.pid")
        self.docx = os.path.join(d, "candidate-0.docx")
        with open(self.docx, "wb") as fh:
            fh.write(b"PK fake docx")
        self.out = os.path.join(d, "out")
        os.makedirs(self.out)
        self.env = mock.patch.dict(os.environ, {
            "FAKE_LOG": self.log, "FAKE_CHILD": self.child,
            "EXACTDOC_SOFFICE_ROOT": d})
        self.env.start()
        self.soffice = mock.patch.object(V, "SOFFICE", self.fake)
        self.soffice.start()
        # The fake answers no --version; keep the version probe from counting
        # as a render call.
        self.flt = mock.patch.object(V, "pdf_export_filter", return_value="pdf")
        self.flt.start()

    def tearDown(self):
        self.flt.stop()
        self.soffice.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return [ln.strip() for ln in fh if ln.strip()]

    def test_one_profile_serves_every_render_and_is_removed_on_close(self):
        os.environ["FAKE_MODE"] = "ok"
        s = V.SofficeSession()
        a = s.render(self.docx, self.out)
        b = s.render(self.docx, self.out)
        self.assertEqual(a, os.path.join(self.out, "candidate-0.pdf"))
        self.assertTrue(os.path.exists(b))
        calls = self._calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])        # the same profile, kept
        root = s.root
        self.assertTrue(os.path.isdir(root))
        s.close()
        self.assertFalse(os.path.exists(root))

    def test_a_render_that_writes_nothing_is_retried_then_reported(self):
        os.environ["FAKE_MODE"] = "nothing"
        with V.SofficeSession() as s:
            self.assertIsNone(s.render(self.docx, self.out))
            self.assertIn("without writing a PDF (3 attempts)", s.last_failure)
        self.assertEqual(len(self._calls()), 3)

    def test_a_transient_failure_recovers_on_retry(self):
        os.environ["FAKE_MODE"] = "second"
        with V.SofficeSession() as s:
            self.assertIsNotNone(s.render(self.docx, self.out))
            self.assertIsNone(s.last_failure)
        self.assertEqual(len(self._calls()), 2)

    def test_a_hang_is_killed_with_its_children_and_not_retried(self):
        os.environ["FAKE_MODE"] = "hang"
        with mock.patch.object(V, "RENDER_TIMEOUT_S", 2):
            t0 = time.monotonic()
            with V.SofficeSession() as s:
                self.assertIsNone(s.render(self.docx, self.out))
                self.assertIn("did not finish", s.last_failure)
            self.assertLess(time.monotonic() - t0, 30)
        self.assertEqual(len(self._calls()), 1)
        with open(self.child) as fh:
            pid = int(fh.read().strip())
        deadline = time.monotonic() + 5
        alive = True
        while alive and time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
                # a zombie still answers kill(0); check its state
                with open("/proc/%d/stat" % pid) as fh:
                    alive = fh.read().split()[2] != "Z"
            except (ProcessLookupError, FileNotFoundError):
                alive = False
            if alive:
                time.sleep(0.1)
        self.assertFalse(alive, "the hung soffice's child survived the kill")


class ExportFilterTests(unittest.TestCase):
    """The fast PDF export only where LibreOffice can parse it (7.4+)."""

    def _version(self, stdout=None, exc=None):
        V._VERSIONS.clear()
        run = mock.Mock(return_value=mock.Mock(stdout=stdout)) if exc is None \
            else mock.Mock(side_effect=exc)
        with mock.patch.object(V.subprocess, "run", run), \
                mock.patch.object(V.os.path, "exists", return_value=True):
            try:
                return V.soffice_version("/opt/lo/program/soffice"), run
            finally:
                V._VERSIONS.clear()

    def test_versions_are_read_from_the_banner(self):
        self.assertEqual(self._version("LibreOffice 24.2.7.2 420(Build:2)\n")[0], (24, 2))
        self.assertEqual(self._version("LibreOffice 7.3.7.2 30(Build:2)")[0], (7, 3))
        self.assertIsNone(self._version("")[0])
        self.assertIsNone(self._version(exc=OSError("no"))[0])

    def test_the_filter_follows_the_version(self):
        for version, fast in (((24, 2), True), ((7, 4), True), ((7, 3), False),
                              (None, False)):
            with mock.patch.object(V, "soffice_version", return_value=version):
                got = V.pdf_export_filter("/x/soffice")
            self.assertEqual(got == V.FAST_PDF_EXPORT, fast, version)
            self.assertEqual(got == "pdf", not fast, version)

    def test_the_fast_filter_is_valid_json_after_the_prefix(self):
        import json
        prefix = "pdf:writer_pdf_Export:"
        self.assertTrue(V.FAST_PDF_EXPORT.startswith(prefix))
        opts = json.loads(V.FAST_PDF_EXPORT[len(prefix):])
        self.assertEqual(opts["ReduceImageResolution"]["value"], "true")

    def test_the_version_is_asked_once_per_path(self):
        V._VERSIONS.clear()
        run = mock.Mock(return_value=mock.Mock(stdout="LibreOffice 24.2.7.2"))
        with mock.patch.object(V.subprocess, "run", run), \
                mock.patch.object(V.os.path, "exists", return_value=True):
            V.soffice_version("/a/soffice")
            V.soffice_version("/a/soffice")
        V._VERSIONS.clear()
        self.assertEqual(run.call_count, 1)

    def test_a_session_renders_with_the_chosen_filter_and_one_shot_renders_do_not(self):
        seen = []

        def popen(cmd, **kw):
            seen.append(cmd)
            raise OSError("not started")

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"EXACTDOC_SOFFICE_ROOT": d}), \
                mock.patch.object(V, "SOFFICE", "/x/soffice"), \
                mock.patch.object(V, "pdf_export_filter",
                                  return_value=V.FAST_PDF_EXPORT), \
                mock.patch.object(V.subprocess, "Popen", side_effect=popen):
            src = os.path.join(d, "a.docx")
            with open(src, "wb") as fh:
                fh.write(b"PK")
            with V.SofficeSession() as s:
                s.render(src, d)
            V.docx_to_pdf(src, d)
        flt = [c[c.index("--convert-to") + 1] for c in seen]
        self.assertEqual(flt[0], V.FAST_PDF_EXPORT)
        self.assertEqual(flt[-1], "pdf")


class ShortRootTests(unittest.TestCase):
    def test_an_explicit_root_wins(self):
        with mock.patch.dict(os.environ, {"EXACTDOC_SOFFICE_ROOT": "/x/y"}):
            self.assertEqual(V._short_root(), "/x/y")

    def test_a_long_temp_directory_is_not_used_for_the_profile(self):
        long_tmp = os.path.join(tempfile.gettempdir(), "d" * 150)
        env = {k: v for k, v in os.environ.items()
               if k != "EXACTDOC_SOFFICE_ROOT"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(V.tempfile, "gettempdir",
                                  return_value=long_tmp):
            root = V._short_root()
        self.assertNotEqual(root, long_tmp)
        self.assertLessEqual(len(root), V.SHORT_ROOT_MAX)

    def test_a_short_temp_directory_is_used_as_is(self):
        env = {k: v for k, v in os.environ.items()
               if k != "EXACTDOC_SOFFICE_ROOT"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(V.tempfile, "gettempdir",
                                  return_value="/tmp"):
            self.assertEqual(V._short_root(), "/tmp")


if __name__ == "__main__":
    unittest.main()
