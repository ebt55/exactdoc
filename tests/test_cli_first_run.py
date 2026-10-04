"""What a first-time user sees: one clear line and a stable exit code.

Each failure below is one a tester hits in the first five minutes -- a typo in
the file name, a folder instead of a file, a web page saved as .pdf, a
password, a scan, a form, a folder they cannot write to, and the default output
name landing on the Word document the PDF was exported from. Before WP20 three
of them were tracebacks (missing input, folder input, read-only folder), one
silently replaced the user's own file, and the default command failed with exit
11 on every machine without LibreOffice.

Every test here needs neither LibreOffice nor the canonical fonts, so it runs
in the install-check CI job on all three operating systems.

    python -m unittest tests.test_cli_first_run
"""
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import cli                                      # noqa: E402
from exactdoc.errors import InputNotFoundError, OutputWriteError  # noqa: E402
from exactdoc.io import check_writable                       # noqa: E402

HAVE_REPORTLAB = importlib.util.find_spec("reportlab") is not None


def _text_pdf(path, text="A short first page for the command line tests.",
              pages=1):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=(612, 792))
    for i in range(pages):
        c.setFont("Helvetica", 11)
        c.drawString(72, 700, "%s (%d)" % (text, i + 1))
        c.showPage()
    c.save()
    return path


def _scan_pdf(path, image_path):
    from PIL import Image
    from reportlab.pdfgen import canvas
    Image.new("RGB", (300, 400), "gray").save(image_path)
    c = canvas.Canvas(path, pagesize=(612, 792))
    c.drawImage(image_path, 0, 0, 612, 792)
    c.showPage()
    c.save()
    return path


def _form_pdf(path, fields=16):
    """One page dense with fillable text fields: scan.FORM_PAGE_WIDGETS is 12."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=(612, 792))
    c.drawString(72, 740, "Application form")
    for i in range(fields):
        c.acroForm.textfield(name="field%d" % i, x=72, y=700 - 36 * i,
                             width=300, height=20)
    c.showPage()
    c.save()
    return path


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _cli(*args, cwd=None):
    """Run the console entry point as a user would, in a fresh interpreter."""
    env = dict(os.environ, PYTHONPATH=ROOT)
    return subprocess.run([sys.executable, "-m", "exactdoc.cli"] + list(args),
                          cwd=cwd or ROOT, env=env, text=True,
                          capture_output=True, check=False)


class _TempDir(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def path(self, name):
        return os.path.join(self.dir, name)

    def assertOneLineError(self, proc, code, *needles):
        self.assertEqual(proc.returncode, code, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        first = proc.stderr.strip().splitlines()[0]
        self.assertTrue(first.startswith("error: "), proc.stderr)
        for needle in needles:
            self.assertIn(needle, first)
        # The message names files, never the folder they live in.
        self.assertNotIn(self.dir, proc.stderr)


class HelpAndVersion(unittest.TestCase):
    def test_version(self):
        import exactdoc
        proc = _cli("--version")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "exactdoc %s" % exactdoc.__version__)

    def test_help_shows_examples_and_exit_codes(self):
        out = cli.build_parser().format_help()
        for needle in ("examples:", "exactdoc report.pdf", "--diagnose",
                       "LibreOffice is optional", "exit codes:", "--version",
                       "21 input file not found"):
            self.assertIn(needle, out)

    def test_no_arguments_is_a_short_usage_error(self):
        proc = _cli()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("give a PDF to convert", proc.stderr)
        # the usage is the three-line summary, not every flag
        self.assertLess(len(proc.stderr.splitlines()), 8, proc.stderr)

    def test_new_exit_code_extends_the_table(self):
        self.assertEqual(cli.EXIT_CODES["input-not-found"], 21)
        self.assertEqual(len(set(cli.EXIT_CODES.values())), len(cli.EXIT_CODES))


class InputErrors(_TempDir):
    def test_missing_input(self):
        proc = _cli(self.path("no-such-report.pdf"), "--refine", "0")
        self.assertOneLineError(proc, 21, "no such file: no-such-report.pdf")

    def test_a_folder_is_not_a_pdf(self):
        sub = self.path("pdfs")
        os.mkdir(sub)
        proc = _cli(sub, "--refine", "0")
        self.assertOneLineError(proc, 21, "is a folder", "--input-dir")

    def test_a_typo_in_a_later_name_fails_before_anything_converts(self):
        good = self.path("good.pdf")
        with open(good, "wb") as fh:
            fh.write(b"%PDF-1.7\n")           # never reached: the check is first
        proc = _cli(good, self.path("tpyo.pdf"), "--refine", "0")
        self.assertOneLineError(proc, 21, "tpyo.pdf")
        self.assertFalse(os.path.exists(self.path("good.docx")))

    def test_a_web_page_saved_as_pdf(self):
        src = self.path("download.pdf")
        with open(src, "w") as fh:
            fh.write("<!doctype html><title>Not found</title>\n")
        proc = _cli(src, "--refine", "0", "-o", self.path("o.docx"))
        self.assertOneLineError(proc, 6, "not a PDF")

    def test_an_empty_file(self):
        src = self.path("empty.pdf")
        open(src, "wb").close()
        proc = _cli(src, "--refine", "0", "-o", self.path("o.docx"))
        self.assertOneLineError(proc, 6, "empty")

    def test_a_truncated_pdf(self):
        src = self.path("cut.pdf")
        with open(src, "wb") as fh:
            fh.write(b"%PDF-1.7\n")
        proc = _cli(src, "--refine", "0", "-o", self.path("o.docx"))
        self.assertOneLineError(proc, 6, "malformed or truncated")

    def test_encrypted(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_input_errors import ENCRYPTED_PDF
        src = self.path("locked.pdf")
        with open(src, "wb") as fh:
            fh.write(ENCRYPTED_PDF)
        proc = _cli(src, "--refine", "0", "-o", self.path("o.docx"))
        self.assertOneLineError(proc, 5, "password-protected")
        self.assertIn("hint:", proc.stderr)

    @unittest.skipUnless(HAVE_REPORTLAB, "reportlab is a test dependency")
    def test_scanned_without_a_text_layer(self):
        src = _scan_pdf(self.path("scan.pdf"), self.path("scan.png"))
        proc = _cli(src, "--refine", "0", "-o", self.path("o.docx"))
        self.assertOneLineError(proc, 17, "OCR")
        self.assertIn("hint: run it through an OCR tool", proc.stderr)
        self.assertFalse(os.path.exists(self.path("o.docx")))

    @unittest.skipUnless(HAVE_REPORTLAB, "reportlab is a test dependency")
    def test_fillable_form(self):
        src = _form_pdf(self.path("form.pdf"))
        proc = _cli(src, "--refine", "0", "-o", self.path("o.docx"))
        self.assertOneLineError(proc, 19, "interactive form")
        self.assertFalse(os.path.exists(self.path("o.docx")))

    def test_the_api_error_is_still_a_file_not_found_error(self):
        from exactdoc.convert import convert
        with self.assertRaises(FileNotFoundError) as raised:
            convert(self.path("nope.pdf"), self.path("o.docx"),
                    refine_rounds=0, oracle="none")
        self.assertIsInstance(raised.exception, InputNotFoundError)
        self.assertEqual(raised.exception.code, "input-not-found")
        self.assertNotIn(self.dir, raised.exception.message)


@unittest.skipUnless(HAVE_REPORTLAB, "reportlab is a test dependency")
class OutputErrors(_TempDir):
    def setUp(self):
        super().setUp()
        self.src = _text_pdf(self.path("report.pdf"))

    def test_the_output_is_a_folder(self):
        proc = _cli(self.src, "--refine", "0", "-o", self.dir)
        self.assertOneLineError(proc, 8, "folder")

    def test_the_output_folder_cannot_be_created(self):
        blocker = self.path("notes.txt")
        with open(blocker, "w") as fh:
            fh.write("a file where a folder would have to go")
        proc = _cli(self.src, "--refine", "0", "-o",
                    os.path.join(blocker, "out", "report.docx"))
        self.assertOneLineError(proc, 8, "report.docx")

    def test_the_output_would_replace_the_input(self):
        before = _read(self.src)
        proc = _cli(self.src, "--refine", "0", "-o", self.src)
        self.assertOneLineError(proc, 3, "replace the input PDF")
        self.assertEqual(_read(self.src), before)

    def test_default_name_never_replaces_an_existing_document(self):
        mine = self.path("report.docx")
        with open(mine, "wb") as fh:
            fh.write(b"the user's own Word document")
        proc = _cli(self.src, "--refine", "0")
        self.assertOneLineError(proc, 3, "report.docx already exists",
                                "--overwrite")
        self.assertEqual(_read(mine), b"the user's own Word document")
        proc = _cli(self.src, "--refine", "0", "--overwrite")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotEqual(_read(mine), b"the user's own Word document")

    def test_default_name_and_the_wrote_line(self):
        proc = _cli(self.src, "--refine", "0")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.exists(self.path("report.docx")))
        line = proc.stdout.strip().splitlines()[-1]
        self.assertTrue(line.startswith("wrote "), line)
        self.assertIn("report.docx  (1 page, ", line)
        # no progress line off a terminal, and no note when the layout check
        # was switched off by name
        self.assertNotIn("\r", proc.stderr)
        self.assertNotIn("note:", proc.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_the_docx_gets_ordinary_permissions(self):
        # mkstemp's private 0600 used to survive os.replace onto the output
        out = self.path("perm.docx")
        proc = _cli(self.src, "--refine", "0", "-o", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        umask = os.umask(0)
        os.umask(umask)
        self.assertEqual(os.stat(out).st_mode & 0o777, 0o666 & ~umask)

    def test_check_writable_creates_nothing(self):
        target = os.path.join(self.dir, "a", "b", "c.docx")
        check_writable(target)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "a")))
        self.assertEqual(sorted(os.listdir(self.dir)), ["report.pdf"])
        with self.assertRaises(OutputWriteError):
            check_writable(self.dir)


@unittest.skipUnless(HAVE_REPORTLAB, "reportlab is a test dependency")
class WithoutLibreOffice(_TempDir):
    """The default command must work on a machine with no office suite."""

    def setUp(self):
        super().setUp()
        self.src = _text_pdf(self.path("memo.pdf"))

    def _main(self, *args):
        err, out = io.StringIO(), io.StringIO()
        with mock.patch("exactdoc.verify.SOFFICE", None), \
                redirect_stderr(err), redirect_stdout(out):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_default_falls_back_to_one_pass_and_says_so(self):
        out_path = self.path("memo.docx")
        code, out, err = self._main(self.src, "-o", out_path)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(out_path))
        self.assertIn("note: LibreOffice was not found", err)
        self.assertIn("--refine 0", err)
        self.assertIn("wrote ", out)

    def test_refinement_asked_for_by_name_is_still_exit_11(self):
        for args in (("--refine", "3"), ("--oracle", "libreoffice")):
            with self.subTest(args=args):
                code, _, err = self._main(self.src, "-o", self.path("x.docx"),
                                          *args)
                self.assertEqual(code, 11, err)
                self.assertIn("hint: install LibreOffice", err)
                self.assertFalse(os.path.exists(self.path("x.docx")))

    def test_fallback_runs_the_raw_profile(self):
        seen = {}

        def fake(pdf, out, **kw):
            seen.update(kw)
            raise SystemExit(0)

        with mock.patch("exactdoc.convert.convert_result", side_effect=fake):
            with self.assertRaises(SystemExit):
                self._main(self.src, "-o", self.path("y.docx"))
        self.assertEqual(seen["refine_rounds"], 0)
        self.assertEqual(seen["oracle"], "none")


class Robustness(_TempDir):
    def test_an_internal_error_asks_for_a_report(self):
        src = self.path("in.pdf")
        with open(src, "wb") as fh:
            fh.write(b"%PDF-1.7\n")
        err, out = io.StringIO(), io.StringIO()
        with mock.patch("exactdoc.convert.convert_result",
                        side_effect=RuntimeError("a bug")), \
                redirect_stderr(err), redirect_stdout(out):
            code = cli.main([src, "--refine", "0", "-o", self.path("o.docx")])
        self.assertEqual(code, 1)
        self.assertIn("RuntimeError: a bug", err.getvalue())
        self.assertIn("This is a bug", err.getvalue())
        self.assertIn(cli.ISSUES_URL, err.getvalue())

    def test_progress_draws_on_a_terminal_and_clears_itself(self):
        stream = io.StringIO()
        p = cli._Progress("big.pdf", stream=stream, enabled=True)
        p.t0 -= 5                                  # as if 5s had passed

        def drawn(needle, timeout=10.0):
            # the ticker draws every 0.5s; poll rather than guess a sleep, so
            # a slow CI runner is not a flaky one
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if needle in stream.getvalue():
                    return True
                time.sleep(0.05)
            return False

        p("read", {"pages": 126})
        self.assertTrue(drawn("big.pdf: reading 126 pages ... "),
                        repr(stream.getvalue()))
        p("refine", {"round": 1, "rounds": 4})
        self.assertTrue(drawn("checking the layout in LibreOffice, pass 2 of "
                              "at most 4"), repr(stream.getvalue()))
        p.close()
        text = stream.getvalue()
        self.assertTrue(text.endswith("\r"), repr(text[-40:]))
        self.assertEqual(p.pages, 126)

    def test_progress_is_silent_off_a_terminal(self):
        stream = io.StringIO()
        p = cli._Progress("x.pdf", stream=stream)       # StringIO is no tty
        p.t0 -= 5
        p("read", {"pages": 2})
        time.sleep(0.7)
        p.close()
        self.assertEqual(stream.getvalue(), "")

    def test_fmt_seconds(self):
        self.assertEqual(cli._fmt_s(4.24), "4.2s")
        self.assertEqual(cli._fmt_s(409.6), "6m50s")


@unittest.skipUnless(HAVE_REPORTLAB, "reportlab is a test dependency")
class Diagnose(_TempDir):
    def test_diagnose_reports_structure_and_none_of_the_text(self):
        secret = "Zebra quartz invoice for Ms Placeholder"
        src = _text_pdf(self.path("Confidential-Report.pdf"), text=secret,
                        pages=2)
        proc = _cli("--diagnose", src)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        for needle in ("pages         2", "Letter", "ReportLab", "Helvetica",
                       "class         digital", "layout found"):
            self.assertIn(needle, out)
        for word in ("Zebra", "quartz", "invoice", "Placeholder",
                     "Confidential-Report", self.dir):
            self.assertNotIn(word, out)
        self.assertEqual(os.listdir(self.dir), ["Confidential-Report.pdf"])

    def test_diagnose_names_the_refusal(self):
        src = _form_pdf(self.path("form.pdf"))
        proc = _cli("--diagnose", src)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("refused (interactive-form)", proc.stdout)

    def test_diagnose_takes_one_pdf_and_writes_nothing(self):
        proc = _cli("--diagnose", "a.pdf", "-o", "b.docx")
        self.assertEqual(proc.returncode, 2)
        proc = _cli("--diagnose", self.path("missing.pdf"))
        self.assertOneLineError(proc, 21, "missing.pdf")


if __name__ == "__main__":
    unittest.main()
