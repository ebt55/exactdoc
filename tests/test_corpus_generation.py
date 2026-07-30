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
    """-> {doc_id: path} for everything the generators produced here."""
    adv = os.path.join(workdir, "adv")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(ROOT, "testkit"), ROOT, env.get("PYTHONPATH", "")])
    subprocess.run([sys.executable, os.path.join(ROOT, "testkit", "gen_corpus.py"),
                    adv], cwd=ROOT, env=env, capture_output=True, timeout=1800)
    subprocess.run([sys.executable, os.path.join(ROOT, "corpus", "make_corpus.py")],
                   cwd=ROOT, env=env, capture_output=True, timeout=1800)
    made = {}
    for d in (adv, os.path.join(ROOT, "corpus", "pdfs")):
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if n.endswith(".pdf"):
                made.setdefault(n, os.path.join(d, n))
    return made


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    strict = "--strict" in argv
    manifest = corpus_manifest.load()
    expected = set(manifest["documents"])

    print("corpus generation (the fixtures are frozen; this checks the tooling)\n")
    with tempfile.TemporaryDirectory() as td:
        made = run_generators(td)

        produced = set(made) & expected
        check("the generators produced at least the pure-Python documents",
              {"r1_reportlab_report.pdf", "f1_fpdf_brief.pdf",
               "05_memo.pdf"} <= produced,
              "produced %d of %d expected" % (len(produced), len(expected)))
        for doc_id in sorted(produced):
            p = made[doc_id]
            check("%s is a non-trivial PDF" % doc_id,
                  os.path.getsize(p) > 500 and open(p, "rb").read(5) == b"%PDF-",
                  "%d bytes" % os.path.getsize(p))

        missing = sorted(expected - produced)
        if missing:
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
