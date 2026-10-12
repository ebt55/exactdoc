"""The Word lane over a holdout set: testkit/word_oracle.py's own sweep, select() swapped.

    (cd TREE && PYTHONPATH=TREE python scripts/dev/holdout_word.py \\
        --manifest HOLD/<manifest>.json --pdfs HOLD/pdfs -- \\
        sweep OUT --docx-dir RUNS/<name>.<exam>/prod.docx/product --lane product)

Everything after `--` is word_oracle.py's command line, unchanged: its own Word
instance, its batch lock (the named mutex and C:\\lotmp\\word.lock), its
scoring. Only `quality_sweep.select`, which word_oracle asks for the document
list, is replaced by the holdout manifest's, with every PDF's SHA-256 checked;
rows are named by the manifest's `file`, as the container sweep names them.
The PDFs are read, never written.
"""
import argparse
import hashlib
import json
import os
import sys


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def make_select(manifest, pdfs):
    def select(corpus, only, include_unsupported):
        with open(manifest, encoding="utf-8") as fh:
            man = json.load(fh)
        out = []
        for key, spec in sorted(man["documents"].items()):
            name = spec.get("file") or key
            if only and not any(s in name for s in only):
                continue
            path = os.path.join(pdfs, name)
            if _sha256(path) != spec["sha256"]:
                raise SystemExit("holdout bytes do not match the manifest: %s" % name)
            out.append((name, path, "ordinary_digital", spec.get("producer", "")))
        return out
    return select


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    own = argv[:argv.index("--")] if "--" in argv else argv
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--pdfs", required=True)
    ap.add_argument("--tree", default=os.getcwd())
    a = ap.parse_args(own)
    for p in (os.path.join(a.tree, "testkit"), a.tree):
        if p not in sys.path:
            sys.path.insert(0, p)
    import quality_sweep as qs
    import word_oracle as wo
    qs.select = make_select(a.manifest, a.pdfs)
    return wo.main(rest)


if __name__ == "__main__":
    sys.exit(main())
