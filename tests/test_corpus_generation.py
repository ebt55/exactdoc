"""Do the corpus generators still work? Separate from whether the numbers hold.

The metric corpus is 16 frozen PDFs pinned by SHA-256 (`testkit/corpus_manifest.py`).
The generators that originally produced them are still maintained, still run in
CI, and no longer gate a single measured number. Splitting the two is the point:

  * **generation** answers "can we still build a corpus like this?" -- a question
    about the tooling, which moves for reasons outside this repository;
  * **fixtures** answer "are the numbers describing the same inputs?" -- a
    question about evidence, which must never move by accident.

They were the same question, and it cost three red pull requests. The baseline was
recorded against a corpus built with Chromium 149; GitHub's `ubuntu-24.04` runner
ships Chromium 150; `c4_i18n` came out a different document and its vertical drift
went 0.15pt to 0.7pt. Nothing in the converter changed.

This test therefore **reports** drift and **fails** only on breakage:

    generator raises / produces nothing        FAIL -- the tooling is broken
    generator output differs from the fixture  REPORT -- the tooling moved

    python tests/test_corpus_generation.py
    python tests/test_corpus_generation.py --strict   # drift is also a failure
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import corpus_manifest  # noqa: E402

FAILED, DRIFTED = [], []


def check(name, cond, detail=""):
    print("  %-4s %s%s" % ("ok" if cond else "FAIL", name,
                           "" if cond else "   <-- " + detail))
    if not cond:
        FAILED.append(name)


def run_generators(workdir):
    """-> ({doc_id: path}, [problem, ...]).

    Both generators' exit codes are now inspected. They were discarded: a
    generator that raised on every document produced nothing, and the caller then
    reported the absences as "tool absent on this machine" and passed. The whole
    subject of this test is whether the generators still work, and it could not
    tell a broken generator from an uninstalled one.

    `gen_corpus.py` takes an output directory and is given a fresh one.
    `make_corpus.py` writes to `corpus/pdfs` unconditionally -- it has no output
    argument -- so that path is read, not chosen, and is noted here rather than
    silently relied upon.
    """
    adv = os.path.join(workdir, "adv")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(ROOT, "testkit"), ROOT, env.get("PYTHONPATH", "")])
    problems = []
    for label, cmd in (
            ("gen_corpus.py",
             [sys.executable, os.path.join(ROOT, "testkit", "gen_corpus.py"), adv]),
            ("make_corpus.py",
             [sys.executable, os.path.join(ROOT, "corpus", "make_corpus.py")])):
        try:
            p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                               timeout=1800)
        except subprocess.TimeoutExpired:
            problems.append((label, "timed out after 1800s"))
            continue
        if p.returncode != 0:
            tail = (p.stderr or b"").decode("utf-8", "replace").strip()
            problems.append((label, "exit %d: %s"
                             % (p.returncode, tail[-400:] or "(no stderr)")))
    made = {}
    for d in (adv, os.path.join(ROOT, "corpus", "pdfs")):
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if n.endswith(".pdf"):
                made.setdefault(n, os.path.join(d, n))
    return made, problems


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    strict = "--strict" in argv
    manifest = corpus_manifest.load()
    expected = set(manifest["documents"])

    print("corpus generation (the fixtures are frozen; this checks the tooling)\n")
    with tempfile.TemporaryDirectory() as td:
        made, problems = run_generators(td)

        # A generator process that failed is a broken generator, whatever it left
        # behind. Checked first, because every absence below is explained by it.
        for label, detail in problems:
            check("%s exited cleanly" % label, False, detail)

        produced = set(made) & expected
        missing = sorted(expected - produced)

        # In strict mode -- which the canonical workflow always uses -- the exact
        # 16-document set is required. The old floor was three pure-Python
        # documents, so thirteen of sixteen could vanish and this still passed;
        # combined with discarded exit codes, a totally broken Chromium path was
        # indistinguishable from a healthy run.
        #
        # Non-strict stays permissive on purpose: a contributor without the
        # optional local oracles should still be able to run this and learn
        # something. That is why CI passes --strict.
        if strict:
            check("the generators produced the exact expected 16-document set",
                  produced == expected,
                  "produced %d of %d; missing %s"
                  % (len(produced), len(expected), ", ".join(missing) or "none"))
            check("no unexpected document was generated",
                  not (set(made) - expected),
                  "unexpected: %s" % ", ".join(sorted(set(made) - expected)))
        else:
            check("the generators produced at least the pure-Python documents",
                  {"r1_reportlab_report.pdf", "f1_fpdf_brief.pdf",
                   "05_memo.pdf"} <= produced,
                  "produced %d of %d expected" % (len(produced), len(expected)))

        # Rule 5: a loop over nothing is not a pass.
        check("there is at least one generated document to validate",
              bool(produced),
              "the generators produced none of the %d manifest documents"
              % len(expected))

        for doc_id in sorted(produced):
            p = made[doc_id]
            size = os.path.getsize(p)
            try:
                with open(p, "rb") as fh:
                    magic = fh.read(5)
            except OSError as e:
                magic, size = b"", -1
                print("       unreadable: %s" % e)
            check("%s is a readable, non-trivial PDF" % doc_id,
                  size > 500 and magic == b"%PDF-",
                  "%d bytes, magic %r" % (size, magic))

        if missing and not strict:
            print("\n  not generated here (tool absent on this machine): %s"
                  % ", ".join(missing))

        # CONTENT drift, not byte drift. ReportLab and Chromium stamp a creation
        # time and a document ID into every file, so the SHA-256 of a fresh
        # generation differs on every run -- measured, regenerating on the exact
        # machine that produced the fixtures changes all 16 hashes. Byte drift is
        # pure noise; a report that is always 16/16 carries no information. The
        # content digest covers page geometry and normalised text, so it moves
        # only when a document really changed.
        print("\ncontent drift against the frozen fixtures")
        for doc_id in sorted(produced):
            want = manifest["documents"][doc_id].get("content")
            if not want:
                continue
            got = corpus_manifest.content_fingerprint(made[doc_id])
            if got != want:
                DRIFTED.append(doc_id)
                print("  DRIFT %-28s %s != %s" % (doc_id, got[:16], want[:16]))
        if not DRIFTED:
            print("  none -- this toolchain still produces the frozen documents")
        else:
            print("\n  %d document(s) differ in CONTENT from the frozen fixtures. "
                  "That is a statement\n  about the generator toolchain on this "
                  "machine, not about the converter -- this is\n  exactly how "
                  "Chromium 150 changed c4_i18n. Re-freezing is deliberate:\n  "
                  "`corpus_manifest.py update` plus a baseline re-record, in one "
                  "commit." % len(DRIFTED))

    ok = not FAILED and (not strict or not DRIFTED)
    print("\n%s" % ("all clear" if ok else
                    "%d failure(s), %d drift(s)" % (len(FAILED), len(DRIFTED))))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
