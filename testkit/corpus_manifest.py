"""Verify -- or re-measure -- the corpus manifest.

    python testkit/corpus_manifest.py verify     # is this the recorded corpus?
    python testkit/corpus_manifest.py update     # fill in the measured fields

The manifest exists because the corpus is *generated*, and a generated corpus is
a moving target. Every published number is measured against 16 documents that no
longer exist as files anywhere -- they are rebuilt from `gen_corpus.py` and
`make_corpus.py` before each run, by whatever Chromium and ReportLab happen to
be installed. Nothing checked that the rebuild produced the same 16 documents.
Measured in a bare container: the generator produced 3 of 16, printed "the
corpus is incomplete", exited 0, and the gate went on to score those 3 against a
16-document baseline and report a pass.

What can honestly be pinned, and what cannot:

  * the document set -- exactly, and that is the check that was missing;
  * the generator that owns each document, and its dialect;
  * the source page count, which is the cheapest identity fact that moves when a
    generator change alters a document;
  * NOT a content hash. Both generators embed a creation timestamp, so the bytes
    differ on every run. A hash here would fail every time and be deleted within
    a week, which is worse than no hash at all.
"""
import json
import os
import sys

import _paths  # noqa: F401
from _paths import PROJECT

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "corpus_manifest.json")


def load(path=PATH):
    with open(path) as f:
        return json.load(f)


def _page_count(path):
    """Page count via whichever parser is installed. Both agree on this."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(path)
        try:
            return len(doc)
        finally:
            doc.close()
    except ImportError:
        pass
    import fitz
    doc = fitz.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def verify(manifest=None, path=PATH):
    """-> list of (kind, document, detail). Empty means the corpus matches."""
    manifest = manifest or load(path)
    problems, seen = [], {}
    for doc_id, spec in sorted(manifest.get("documents", {}).items()):
        p = os.path.join(PROJECT, spec["path"], doc_id)
        if doc_id in seen:
            problems.append(("duplicate", doc_id, "two entries share a basename"))
            continue
        seen[doc_id] = p
        if not os.path.exists(p):
            problems.append(("missing", doc_id, "expected at %s (generator: %s)"
                             % (spec["path"], spec.get("generator", "?"))))
            continue
        want = spec.get("src_pages")
        if want is None:
            problems.append(("unmeasured", doc_id,
                             "src_pages is null -- run `corpus_manifest.py "
                             "update` on the canonical environment"))
            continue
        got = _page_count(p)
        if got != want:
            problems.append(("identity", doc_id,
                             "%d source pages, manifest says %d -- the generator "
                             "changed this document, so every number measured "
                             "from it was re-based" % (got, want)))
    for d in sorted(set(s["path"] for s in manifest.get("documents", {}).values())):
        import glob
        for p in sorted(glob.glob(os.path.join(PROJECT, d, "*.pdf"))):
            if os.path.basename(p) not in seen:
                problems.append(("unexpected", os.path.basename(p),
                                 "present in %s but not in the manifest" % d))
    return problems


def update(path=PATH):
    manifest = load(path)
    changed = []
    for doc_id, spec in sorted(manifest["documents"].items()):
        p = os.path.join(PROJECT, spec["path"], doc_id)
        if not os.path.exists(p):
            print("  SKIP    %-28s not present" % doc_id)
            continue
        got = _page_count(p)
        if spec.get("src_pages") != got:
            changed.append((doc_id, spec.get("src_pages"), got))
            spec["src_pages"] = got
        print("  %-28s %d pages" % (doc_id, got))
    with open(path, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
        f.write("\n")
    for doc_id, was, now in changed:
        print("CHANGED %-28s %s -> %s" % (doc_id, was, now))
    if changed:
        print("\n%d document(s) changed identity. Re-record the gate baseline in "
              "the same commit, or the numbers describe the previous corpus."
              % len(changed))
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "verify"
    if cmd == "update":
        return update()
    if cmd != "verify":
        print(__doc__)
        return 2
    problems = verify()
    m = load()
    print("corpus manifest: %d documents" % len(m.get("documents", {})))
    for kind, doc, why in problems:
        print("  %-11s %-28s %s" % (kind, doc[:28], why))
    if problems:
        print("\n%d problem(s). Numbers from a corpus that is not the recorded "
              "corpus are not comparable to the baseline." % len(problems))
        return 1
    print("  every document present, and each is the document on record")
    return 0


if __name__ == "__main__":
    sys.exit(main())
