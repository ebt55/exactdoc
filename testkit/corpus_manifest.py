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
  * a **content fingerprint** over page geometry and normalised text -- which is
    what page count alone was missing. A generator change that rewords a heading,
    restyles a table or shifts a margin leaves the page count identical and
    re-bases every number measured from the document. Page count catches a
    document being added or dropped; only content catches it being edited.
  * NOT a hash of the file bytes. Both generators embed a creation timestamp and
    a document ID, so the bytes differ on every run; a byte hash would fail every
    time and be deleted within a week, which is worse than no hash at all. The
    fingerprint is computed from extracted content instead, which carries no
    timestamp.

The fingerprint is recorded **per extractor**, because the two parsers do not
extract identical text -- that is the subject of half this repository. Verifying
compares only against the extractor doing the verifying, and an extractor with no
recorded fingerprint is a failure rather than a pass, so a machine with a
different parser cannot quietly skip the check.
"""
import hashlib
import json
import os
import re
import sys

import _paths  # noqa: F401
from _paths import PROJECT

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "corpus_manifest.json")


def load(path=PATH):
    with open(path) as f:
        return json.load(f)


def _extractors():
    """{name: fn(path) -> [(w, h, text), ...]} for every parser installed here."""
    out = {}
    try:
        import pypdfium2  # noqa: F401

        def pdfium_pages(path):
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(path)
            try:
                pages = []
                for i in range(len(doc)):
                    page = doc[i]
                    try:
                        tp = page.get_textpage()
                        try:
                            pages.append((page.get_width(), page.get_height(),
                                          tp.get_text_bounded()))
                        finally:
                            tp.close()
                    finally:
                        page.close()
                return pages
            finally:
                doc.close()
        out["pdfium"] = pdfium_pages
    except ImportError:
        pass
    try:
        import fitz  # noqa: F401

        def mupdf_pages(path):
            import fitz
            doc = fitz.open(path)
            try:
                return [(p.rect.width, p.rect.height, p.get_text("text"))
                        for p in doc]
            finally:
                doc.close()
        out["pymupdf"] = mupdf_pages
    except ImportError:
        pass
    return out


def fingerprint(path, pages_fn):
    """sha256 over per-page geometry and whitespace-normalised text."""
    h = hashlib.sha256()
    for w, ph, text in pages_fn(path):
        h.update(("%.1fx%.1f|" % (w, ph)).encode("utf-8"))
        h.update(re.sub(r"\s+", " ", text or "").strip().encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:32]


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
    extractors = _extractors()
    problems, seen = [], {}
    if not extractors:
        problems.append(("no-extractor", "-",
                         "neither pypdfium2 nor PyMuPDF is importable, so corpus "
                         "identity cannot be checked at all"))
        return problems
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
            continue

        recorded = spec.get("fingerprints") or {}
        if not recorded:
            problems.append(("unmeasured", doc_id,
                             "no content fingerprint -- page count alone cannot "
                             "see a document that was edited without changing "
                             "length. Run `corpus_manifest.py update`"))
            continue
        for name, fn in sorted(extractors.items()):
            if name not in recorded:
                problems.append(("unmeasured", doc_id,
                                 "no fingerprint recorded for the %r extractor "
                                 "available here; an unverifiable document is "
                                 "not a verified one" % name))
                continue
            got_fp = fingerprint(p, fn)
            if got_fp != recorded[name]:
                problems.append(("identity", doc_id,
                                 "%s content fingerprint %s, manifest says %s -- "
                                 "same page count, different document"
                                 % (name, got_fp, recorded[name])))
    for d in sorted(set(s["path"] for s in manifest.get("documents", {}).values())):
        import glob
        for p in sorted(glob.glob(os.path.join(PROJECT, d, "*.pdf"))):
            if os.path.basename(p) not in seen:
                problems.append(("unexpected", os.path.basename(p),
                                 "present in %s but not in the manifest" % d))
    return problems


def update(path=PATH):
    """Re-measure every manifest document. All or nothing.

    Refuses a partial write: a manifest describing 12 of 16 documents is a
    manifest the gate will then happily verify against, and the four it forgot
    stop being checked at all.
    """
    manifest = load(path)
    extractors = _extractors()
    if not extractors:
        print("neither pypdfium2 nor PyMuPDF is importable; cannot measure")
        return 2
    changed, absent = [], []
    for doc_id, spec in sorted(manifest["documents"].items()):
        p = os.path.join(PROJECT, spec["path"], doc_id)
        if not os.path.exists(p):
            absent.append(doc_id)
            print("  ABSENT  %-28s %s" % (doc_id, spec["path"]))
            continue
        got = _page_count(p)
        fps = {name: fingerprint(p, fn) for name, fn in sorted(extractors.items())}
        if spec.get("src_pages") != got:
            changed.append((doc_id, "src_pages", spec.get("src_pages"), got))
        for name, fp in sorted(fps.items()):
            was = (spec.get("fingerprints") or {}).get(name)
            if was != fp:
                changed.append((doc_id, name, was, fp))
        spec["src_pages"] = got
        # Preserve fingerprints for extractors not installed here rather than
        # dropping them: a machine with only one parser must not silently narrow
        # the manifest to what it happens to be able to measure.
        merged = dict(spec.get("fingerprints") or {})
        merged.update(fps)
        spec["fingerprints"] = merged
        print("  %-28s %d pages  %s" % (doc_id, got,
              "  ".join("%s=%s" % (k, v[:12]) for k, v in sorted(fps.items()))))

    if absent:
        print("\nrefusing to write: %d document(s) are not present (%s). A "
              "manifest recorded over a partial corpus stops checking what it "
              "forgot." % (len(absent), ", ".join(absent)))
        return 2

    import tempfile
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".corpus_manifest.", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(manifest, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    for doc_id, field, was, now in changed:
        print("CHANGED %-28s %-8s %s -> %s" % (doc_id, field, was, now))
    if changed:
        print("\n%d identity change(s). Re-record the gate baseline in the same "
              "commit, or the numbers describe the previous corpus." % len(changed))
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
