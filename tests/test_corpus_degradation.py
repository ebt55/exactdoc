"""A missing oracle must degrade into a skip list, never a traceback.

The corpus generator drives two external tools (headless Chromium, LibreOffice)
and three pure-Python producers. When Chromium was absent it called
subprocess.run([None, ...]) and died on a bare TypeError before writing a single
file -- including the eight documents that need no Chromium at all. An executor
who cannot generate a corpus cannot run the gate, and this repository has
already learned once that a gate which cannot run looks exactly like a gate that
passes (STATUS.md §5).

So the contract is:

    tool missing  -> skip, say which documents were skipped, exit 0
    tool present but failing -> error, say what it printed, exit 1

    python -m pytest tests/ -q      (or: python tests/test_corpus_degradation.py)
"""
import contextlib
import io
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import gen_corpus as g                                    # noqa: E402


def _run(out, chrome, soffice):
    """Run the generator with the given tool availability. Returns (code, log)."""
    old = (g.OUT, g.HTML, g.CHROME, g.SOFFICE)
    g.OUT, g.HTML = out, os.path.join(out, "_html")
    g.CHROME, g.SOFFICE = chrome, soffice
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = g.main()
    finally:
        g.OUT, g.HTML, g.CHROME, g.SOFFICE = old
    return code, buf.getvalue()


def test_no_external_tools_still_generates_the_python_documents():
    with tempfile.TemporaryDirectory() as td:
        code, log = _run(td, chrome=None, soffice=None)

        assert code == 0, "a bare machine is a skip, not a failure:\n" + log
        assert "SKIPPED" in log, "the skip list is the whole point:\n" + log

        made = sorted(f for f in os.listdir(td) if f.endswith(".pdf"))
        assert made == ["f1_fpdf_brief.pdf", "r1_reportlab_report.pdf"], (
            "the documents that need no external tool must still be produced, "
            "got %s\n%s" % (made, log))

        # Every document that could not be made is named, with the reason.
        for doc in ("c1_whitepaper", "c8_toc_links", "l1_libreoffice"):
            assert doc in log, "%s was dropped without being named:\n%s" % (doc, log)
        assert "CHROME=" in log and "SOFFICE=" in log, (
            "a skip must say how to fix itself:\n" + log)

        # An incomplete corpus must not be quietly comparable to the baselines.
        assert "NOT comparable" in log, log


def test_a_present_but_broken_tool_is_an_error_not_a_skip():
    with tempfile.TemporaryDirectory() as td:
        code, log = _run(td, chrome=os.path.join(td, "not-a-real-chrome"),
                         soffice=None)
        assert code == 1, "a tool that is present and fails is a broken " \
                          "machine, not a thin one:\n" + log
        assert "FAILED" in log, log


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
            print("  ok   %s" % name)
        except AssertionError as e:
            failures += 1
            print("  FAIL %s\n%s" % (name, e))
    print("\n%d test(s) failed" % failures)
    sys.exit(1 if failures else 0)
