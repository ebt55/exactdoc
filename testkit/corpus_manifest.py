"""Verify -- or re-measure -- the frozen corpus fixtures.

    python testkit/corpus_manifest.py verify     # is this the corpus on record?
    python testkit/corpus_manifest.py update     # re-freeze from the generators

**The metric corpus is 16 frozen PDFs, pinned by SHA-256, committed to the
repository.** It used to be regenerated before every gate run, and that is why the
numbers were not reproducible: the generators depend on whatever Chromium,
ReportLab and fpdf2 happen to be installed.

Measured, and this is the whole argument. The gate baseline was recorded against a
corpus built with Chromium 149. GitHub Actions runs `ubuntu-24.04`, which ships
Chromium 150. One document changed -- `c4_i18n`, the CJK/RTL page, exactly where a
browser's font fallback would move -- and its vertical drift went 0.15pt to 0.7pt.
That is a **5x change in a gated metric caused by nothing in this repository**, and
it failed three pull requests. The other fifteen documents were byte-identical, so
this is not noise: it is one input file being a different file.

A generated corpus cannot be a measurement baseline. Either the generator is
pinned exactly -- which means pinning a browser by digest, forever, against its
own security updates -- or the inputs are frozen. Freezing is cheaper, stronger
and honest: the bytes the numbers describe are the bytes in the repository, at
563 KB total, and anyone can check the hash.

What the generators are still for: `tests/test_corpus_generation.py` runs them and
checks they still *work*. Drift between a fresh generation and the frozen fixture
is reported there as information -- it says the tooling moved, which is worth
knowing and is not a regression in this converter. Re-freezing is deliberate,
reviewable in the diff as changed binaries, and re-bases every number, so it comes
with a baseline re-record in the same commit.

What is pinned where, with no overlap:

    SHA-256 of the input bytes     this file      -- corpus identity
    environment fingerprint        evidence.py    -- toolchain identity
    golden IR digests              golden_ir.py   -- parser output identity
"""
import hashlib
import json
import os
import sys

import _paths  # noqa: F401
from _paths import PROJECT

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "corpus_manifest.json")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(path=PATH):
    with open(path) as f:
        return json.load(f)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fixture_path(doc_id, manifest=None):
    """Where the frozen input lives. Absolute."""
    return os.path.join(FIXTURES, doc_id)


# ------------------------------------------------------------ content identity
# A second, weaker identity used by ONE caller for ONE question, and never by the
# gate: `tests/test_corpus_generation.py` asks whether the generators still make
# the same documents. It cannot ask that with SHA-256, because ReportLab and
# Chromium stamp a creation time and a document ID into every file -- measured,
# regenerating on the exact machine that produced the fixtures changes all 16
# hashes. Byte drift is therefore 100% noise and says nothing.
#
# This digest covers page geometry and whitespace-normalised text, which carry no
# timestamp, so it moves only when a document really changes -- as `c4_i18n` did
# between Chromium 149 and 150.
#
#   sha256               the gate       are these the exact bytes measured?
#   content fingerprint  generation     did the toolchain change the documents?
def content_fingerprint(path, pages_fn=None):
    if pages_fn is None:
        pages_fn = _default_pages
    import re
    h = hashlib.sha256()
    for w, ph, text in pages_fn(path):
        h.update(("%.1fx%.1f|" % (w, ph)).encode("utf-8"))
        h.update(re.sub(r"\s+", " ", text or "").strip().encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:32]


def _default_pages(path):
    try:
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
    except ImportError:
        pass
    import fitz
    doc = fitz.open(path)
    try:
        return [(p.rect.width, p.rect.height, p.get_text("text")) for p in doc]
    finally:
        doc.close()


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
    """-> list of (kind, document, detail). Empty means the corpus matches.

    SHA-256 over the file bytes. Exact, cheap, and needs no PDF library, so a
    corpus identity failure can never be confused with a parser difference.
    """
    manifest = manifest or load(path)
    problems, seen = [], set()
    for doc_id, spec in sorted(manifest.get("documents", {}).items()):
        p = fixture_path(doc_id, manifest)
        if doc_id in seen:
            problems.append(("duplicate", doc_id, "two entries share a basename"))
            continue
        seen.add(doc_id)
        if not os.path.exists(p):
            problems.append(("missing", doc_id,
                             "frozen fixture absent from testkit/fixtures/"))
            continue
        want = spec.get("sha256")
        if not want:
            problems.append(("unmeasured", doc_id,
                             "no sha256 recorded -- run `corpus_manifest.py "
                             "update`"))
            continue
        got = sha256(p)
        if got != want:
            problems.append(("identity", doc_id,
                             "sha256 %s, manifest says %s -- this is not the "
                             "document every recorded number was measured from"
                             % (got[:16], want[:16])))
            continue
        size = os.path.getsize(p)
        if spec.get("bytes") is not None and size != spec["bytes"]:
            problems.append(("identity", doc_id,
                             "%d bytes, manifest says %d" % (size, spec["bytes"])))
    for name in sorted(os.listdir(FIXTURES)) if os.path.isdir(FIXTURES) else []:
        if name.endswith(".pdf") and name not in manifest.get("documents", {}):
            problems.append(("unexpected", name,
                             "present in testkit/fixtures/ but not in the manifest"))
    return problems


def update(path=PATH, source_dirs=("testkit/adv", "corpus/pdfs"), seal=False):
    """Re-freeze every fixture from the generated corpus. All or nothing.

    Deliberate and disruptive by design: it rewrites committed binaries and
    re-bases every recorded number, so it must be followed by a baseline
    re-record in the same commit.

    `seal=True` (`--seal`) records the hashes of the fixtures **already present**
    instead of re-copying from a generated corpus. That is the one-time adoption
    path, and the path after a fixture is replaced by hand. It is a separate flag
    rather than a silent fallback because the two are not the same act: `update`
    says "the generators produced this", `--seal` says "I am asserting these
    bytes". Both show up in the diff as changed binaries either way.
    """
    manifest = load(path)
    os.makedirs(FIXTURES, exist_ok=True)
    found, absent, changed = {}, [], []
    for doc_id in sorted(manifest["documents"]):
        cands = [os.path.join(PROJECT, d, doc_id) for d in source_dirs]
        if seal:
            cands.append(fixture_path(doc_id, manifest))
        for cand in cands:
            if os.path.exists(cand):
                found[doc_id] = cand
                break
        else:
            absent.append(doc_id)
    if absent:
        print("refusing to re-freeze: %d document(s) were not generated (%s). "
              "Generate the whole corpus first -- a partial re-freeze silently "
              "mixes two toolchains." % (len(absent), ", ".join(absent)))
        return 2

    import shutil
    for doc_id, src in sorted(found.items()):
        dst = fixture_path(doc_id, manifest)
        was = manifest["documents"][doc_id].get("sha256")
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copyfile(src, dst)
        now = sha256(dst)
        manifest["documents"][doc_id]["sha256"] = now
        manifest["documents"][doc_id]["bytes"] = os.path.getsize(dst)
        manifest["documents"][doc_id].pop("fingerprints", None)
        manifest["documents"][doc_id].pop("path", None)
        manifest["documents"][doc_id]["src_pages"] = _page_count(dst)
        manifest["documents"][doc_id]["content"] = content_fingerprint(dst)
        if was != now:
            changed.append((doc_id, was, now))
        print("  %-28s %8d bytes  %s" % (doc_id, manifest["documents"][doc_id]["bytes"],
                                         now[:16]))

    manifest["fixtures_dir"] = "testkit/fixtures"
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

    for doc_id, was, now in changed:
        print("CHANGED %-28s %s -> %s" % (doc_id, (was or "none")[:16], now[:16]))
    if changed:
        print("\n%d fixture(s) re-frozen. Every recorded number describes the "
              "PREVIOUS bytes until the gate baseline is re-recorded in this same "
              "commit." % len(changed))
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "verify"
    if cmd == "update":
        return update(seal="--seal" in argv)
    if cmd != "verify":
        print(__doc__)
        return 2
    problems = verify()
    m = load()
    print("corpus manifest: %d frozen fixtures" % len(m.get("documents", {})))
    for kind, doc, why in problems:
        print("  %-11s %-28s %s" % (kind, doc[:28], why))
    if problems:
        print("\n%d problem(s). Numbers from a corpus that is not the recorded "
              "corpus are not comparable to the baseline." % len(problems))
        return 1
    print("  every fixture present and byte-identical to the record")
    return 0


if __name__ == "__main__":
    sys.exit(main())
