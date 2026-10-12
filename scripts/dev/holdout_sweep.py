"""Run testkit/quality_sweep.py over a holdout set instead of the corpus (in the container).

    HOLD_DIR=/hold HOLD_MANIFEST=/hold/<manifest>.json [HOLD_CLI_EXITS=/work/cli_exits.json] \\
        python -I holdout_sweep.py --json /work/sweep.json --profile product --jobs 4

Everything -- conversion, harness scoring, char recall, editability, payload,
provenance -- is quality_sweep's own code; only `select()` is replaced, as the
holdout-1 runner did (C:\\lotmp\\rv_hold\\scripts\\holdout_sweep.py). A row is
named by the manifest's `file` (`h2_01_....pdf`), the shape of a corpus row, so
its DOCX lands at testkit/sweep/<profile>/<stem>/<stem>.docx. Every PDF's
SHA-256 is checked against the manifest before anything is converted.

With HOLD_CLI_EXITS set, every document the sweep recorded as refused is then
run through the real command line (`exactdoc PDF -o X.docx --max-pages 0`,
the sweep's own page cap) and the exit status it returns is written beside the
exit code its exception's `code` maps to (beta-bar.md amendment 6, R1: "every
refusal has its typed exit code").
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, "/work/testkit")
os.chdir("/work")
import quality_sweep as qs  # noqa: E402

HOLD = os.environ.get("HOLD_DIR", "/hold")
# The exam's manifest, named by holdout_exam.sh from its EXAMS row: never a
# default, so one set's sweep can never read another set's manifest.
MANIFEST = os.environ.get("HOLD_MANIFEST")
if not MANIFEST:
    raise SystemExit("HOLD_MANIFEST is not set (holdout_exam.sh names the exam's manifest)")


def _documents():
    with open(MANIFEST, encoding="utf-8") as fh:
        man = json.load(fh)
    for key, spec in sorted(man["documents"].items()):
        yield (spec.get("file") or key), spec


def select(corpus, only, include_unsupported):
    out = []
    for name, spec in _documents():
        if only and not any(s in name for s in only):
            continue
        path = os.path.join(HOLD, "pdfs", name)
        if qs.corpus_manifest.sha256(path) != spec["sha256"]:
            raise SystemExit("holdout bytes do not match the manifest: %s" % name)
        out.append((name, path, "ordinary_digital", spec.get("producer", "")))
    return out


def confirm_cli(sweep_json, out_path):
    from exactdoc import errors
    from exactdoc.cli import EXIT_CODES
    with open(sweep_json, encoding="utf-8") as fh:
        rows = json.load(fh)["documents"]
    res = {}
    for r in rows:
        if "refused" not in r:
            continue
        name = r["document"]
        cls = getattr(errors, r["refused"], None)
        code = getattr(cls, "code", None)
        tmp = tempfile.mkdtemp(prefix="cli_")
        cmd = [sys.executable, "-c",
               "import sys; from exactdoc.cli import main; sys.exit(main())",
               os.path.join(HOLD, "pdfs", name), "-o", os.path.join(tmp, "out.docx"),
               "--max-pages", "0"]
        try:
            p = subprocess.run(cmd, cwd="/work", capture_output=True, text=True, timeout=3600)
            rc, err = p.returncode, (p.stderr or "")[-300:]
        except subprocess.TimeoutExpired:
            rc, err = None, "timeout after 3600 s"
        res[name] = {"refused": r["refused"], "code": code,
                     "expected_exit": EXIT_CODES.get(code, 1), "exit": rc, "stderr_tail": err}
        print("cli %s: %s -> exit %s (typed %s)" % (name, r["refused"], rc,
                                                   EXIT_CODES.get(code, 1)), flush=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"schema": "exactdoc.holdout-cli-exits.v1", "documents": res}, fh,
                  indent=1, sort_keys=True)
        fh.write("\n")


def main(argv):
    qs.select = select
    rc = qs.main(argv)
    cli_out = os.environ.get("HOLD_CLI_EXITS")
    if cli_out and "--json" in argv and os.path.exists(argv[argv.index("--json") + 1]):
        confirm_cli(argv[argv.index("--json") + 1], cli_out)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
