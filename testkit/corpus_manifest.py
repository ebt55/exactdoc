"""Verify -- or re-measure -- the frozen corpus fixtures.

    python testkit/corpus_manifest.py verify     # is this the corpus on record?
    python testkit/corpus_manifest.py update     # re-freeze from the generators
    python testkit/corpus_manifest.py expansion-seal <dir>   # freeze a new tranche

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

There is a SECOND, non-gating corpus: `corpus_expansion.json` over
`testkit/fixtures_expansion/`, verified here and consumed only by
`testkit/expansion.py`. It is a separate file rather than a key in the manifest
above because `gdocs_quality_policy.json` pins THIS file's SHA-256, so any edit
here re-binds the Google Docs quality policy. That pin used to fail open --
`gdocs_oracle._load_quality_policy` returned no tiers and evaluation silently
stopped; it now raises `QualificationError` naming both hashes. Editing this
file therefore fails loudly rather than quietly disabling the quality gate.
See `docs/corpus-expansion.md` §2.

The split is enforced by which function a caller reaches for. `verify()` answers
only for the gated 16 and is what `runall.py` calls; `verify_expansion()`
answers only for the expansion set; the CLI `verify` command runs both and
reports them separately. The gate therefore cannot see an expansion problem.
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

# ------------------------------------------------------------ expansion corpus
EXPANSION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "corpus_expansion.json")
EXPANSION_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "fixtures_expansion")
EXPANSION_SCHEMA = "exactdoc.corpus-expansion.v1"
# The vocabulary of gdocs_quality_policy.json, checked so a typo cannot invent a
# fourth tier that no policy will ever evaluate.
TIERS = ("ordinary_digital", "designed_stress", "unsupported")


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


# ------------------------------------------------------ expansion verification
def load_expansion(path=EXPANSION_PATH):
    """The expansion manifest, or an empty one. Absence is not a failure.

    An expansion corpus is optional by construction: a checkout with no
    `corpus_expansion.json` is a valid checkout whose gate still works. Only a
    manifest that exists and disagrees with the bytes is a problem.
    """
    if not os.path.exists(path):
        return {"schema": EXPANSION_SCHEMA, "documents": {},
                "fixtures_dir": "testkit/fixtures_expansion"}
    with open(path) as f:
        return json.load(f)


def expansion_fixture_path(doc_id):
    return os.path.join(EXPANSION_FIXTURES, doc_id)


def _iso_date(value):
    if not isinstance(value, str):
        return False
    try:
        import datetime
        datetime.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _provenance_problems(spec):
    """-> [reason, ...]. Where a document came from, checkably.

    `origin` is exclusive-or by construction: exactly one of `recipe` and
    `source_url` may be set. That is what stops "we generated this" and "we
    downloaded this" from blurring together after a year, which is precisely the
    state in which a licence audit becomes impossible.
    """
    prov = spec.get("provenance")
    if not isinstance(prov, dict):
        return ["no provenance object"]
    out = []
    origin = prov.get("origin")
    recipe, url = prov.get("recipe"), prov.get("source_url")
    if origin == "generated":
        if not isinstance(recipe, str) or "::" not in recipe:
            out.append("generated but no `path::function` recipe")
        if url is not None:
            out.append("generated but also carries a source_url")
    elif origin == "downloaded":
        if not isinstance(url, str) or not url.startswith("https://"):
            out.append("downloaded but no https source_url")
        if recipe is not None:
            out.append("downloaded but also carries a recipe")
    else:
        out.append("origin is %r, not 'generated' or 'downloaded'" % (origin,))
    lic = prov.get("license")
    if not isinstance(lic, str) or not lic.strip():
        out.append("no license recorded")
    elif lic.strip().lower() in ("unknown", "none", "tbd", "n/a"):
        # An unlicensed file cannot be redistributed, and this repository
        # redistributes every fixture it commits. "unknown" is not a licence.
        out.append("license is %r -- an unlicensed file does not enter the corpus"
                   % lic)
    if not _iso_date(prov.get("acquired")):
        out.append("acquired is not an ISO YYYY-MM-DD date")
    return out


def verify_expansion(manifest=None, path=EXPANSION_PATH, gate_manifest=None):
    """-> list of (kind, document, detail). Empty means the expansion corpus matches.

    Deliberately a separate function from `verify()`, not a flag on it.
    `runall.py` calls `verify(manifest)` and turns anything it returns into a
    gate problem; if expansion checks lived in there, a provenance typo in a
    non-gating document would fail the gate. Two functions, two questions.
    """
    manifest = manifest if manifest is not None else load_expansion(path)
    documents = manifest.get("documents") or {}
    problems, seen = [], set()

    if documents and manifest.get("schema") != EXPANSION_SCHEMA:
        problems.append(("schema", os.path.basename(path),
                         "schema is %r, expected %r"
                         % (manifest.get("schema"), EXPANSION_SCHEMA)))

    # A name may not exist in both corpora. `expansion.py` and `runall.py`
    # resolve a basename against different directories, so a shared name is two
    # different files answering to one identifier.
    try:
        gated = set((gate_manifest or load()).get("documents", {}))
    except (OSError, ValueError):
        gated = set()

    for doc_id, spec in sorted(documents.items()):
        if doc_id in seen:
            problems.append(("duplicate", doc_id, "two entries share a basename"))
            continue
        seen.add(doc_id)
        if doc_id in gated:
            problems.append(("collision", doc_id,
                             "also named in corpus_manifest.json -- one basename "
                             "cannot mean two files"))
            continue
        if not isinstance(spec, dict):
            problems.append(("malformed", doc_id, "entry is not an object"))
            continue
        p = expansion_fixture_path(doc_id)
        if not os.path.exists(p):
            problems.append(("missing", doc_id,
                             "frozen fixture absent from testkit/fixtures_expansion/"))
            continue
        want = spec.get("sha256")
        if not want:
            problems.append(("unmeasured", doc_id,
                             "no sha256 recorded -- run `corpus_manifest.py "
                             "expansion-seal <dir>`"))
            continue
        got = sha256(p)
        if got != want:
            problems.append(("identity", doc_id,
                             "sha256 %s, manifest says %s -- these are not the "
                             "bytes the record describes" % (got[:16], want[:16])))
            continue
        size = os.path.getsize(p)
        if spec.get("bytes") is not None and size != spec["bytes"]:
            problems.append(("identity", doc_id,
                             "%d bytes, manifest says %d" % (size, spec["bytes"])))
        if spec.get("tier") not in TIERS:
            problems.append(("tier", doc_id,
                             "tier is %r, not one of %s"
                             % (spec.get("tier"), ", ".join(TIERS))))
        for reason in _provenance_problems(spec):
            problems.append(("provenance", doc_id, reason))

    if os.path.isdir(EXPANSION_FIXTURES):
        for name in sorted(os.listdir(EXPANSION_FIXTURES)):
            if name.endswith(".pdf") and name not in documents:
                problems.append(("unexpected", name,
                                 "present in testkit/fixtures_expansion/ but not "
                                 "in corpus_expansion.json"))
    return problems


def expansion_seal(source_dir, path=EXPANSION_PATH):
    """Freeze a generated tranche: copy the bytes in, then pin what they are.

    The generator writes `expansion_provenance.json` -- tier, dialect, rationale,
    licence, recipe, toolchain -- and this computes sha256, size, page count and
    content fingerprint. A human authors the claims and the tool computes the
    identity, so neither can forge the other. Documents already sealed are left
    alone unless the source directory carries them again.
    """
    import shutil
    if not source_dir or not os.path.isdir(source_dir):
        print("expansion-seal needs the generator's output directory")
        return 2
    side = os.path.join(source_dir, "expansion_provenance.json")
    if not os.path.isfile(side):
        print("no expansion_provenance.json in %s -- run gen_expansion.py first. "
              "Sealing bytes with no provenance would put a document in the "
              "corpus that nobody can account for." % source_dir)
        return 2
    with open(side) as f:
        claims = json.load(f).get("documents", {})

    incoming = sorted(n for n in os.listdir(source_dir) if n.endswith(".pdf"))
    if not incoming:
        print("no PDFs in %s" % source_dir)
        return 2
    undocumented = [n for n in incoming if n not in claims]
    if undocumented:
        print("refusing to seal: %d document(s) have no provenance entry (%s)"
              % (len(undocumented), ", ".join(undocumented)))
        return 2

    manifest = load_expansion(path)
    manifest.setdefault("schema", EXPANSION_SCHEMA)
    manifest.setdefault("documents", {})
    manifest["fixtures_dir"] = "testkit/fixtures_expansion"
    manifest["gating"] = False
    os.makedirs(EXPANSION_FIXTURES, exist_ok=True)
    for doc_id in incoming:
        src = os.path.join(source_dir, doc_id)
        dst = expansion_fixture_path(doc_id)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copyfile(src, dst)
        entry = dict(claims[doc_id])
        entry["sha256"] = sha256(dst)
        entry["bytes"] = os.path.getsize(dst)
        entry["src_pages"] = _page_count(dst)
        entry["content"] = content_fingerprint(dst)
        manifest["documents"][doc_id] = entry
        print("  %-30s %8d bytes  %s  %s"
              % (doc_id, entry["bytes"], entry["sha256"][:16], entry["tier"]))

    import tempfile
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".corpus_expansion.", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(manifest, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    print("\n%d expansion fixture(s) sealed. These are NON-GATING: no baseline "
          "describes them and testkit/gate.py never sees them. Promotion is a "
          "deliberate commit -- docs/corpus-expansion.md §7." % len(incoming))
    return 0


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
    if cmd == "expansion-seal":
        return expansion_seal(argv[1] if len(argv) > 1 else None)
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
    else:
        print("  every fixture present and byte-identical to the record")

    # The expansion corpus is reported in its own section and its own sentence.
    # It shares this command because identity belongs in one place, and shares
    # nothing else: it has no baseline, and `verify()` above never saw it.
    x = load_expansion()
    xdocs = x.get("documents", {})
    xproblems = verify_expansion(x, gate_manifest=m)
    print("\nexpansion corpus: %d frozen fixtures (non-gating)" % len(xdocs))
    for kind, doc, why in xproblems:
        print("  %-11s %-30s %s" % (kind, doc[:30], why))
    if xproblems:
        print("\n%d expansion problem(s). No gated number is affected; "
              "testkit/expansion.py will refuse to run." % len(xproblems))
    elif xdocs:
        tiers = {}
        for spec in xdocs.values():
            tiers[spec.get("tier")] = tiers.get(spec.get("tier"), 0) + 1
        print("  every fixture present, pinned, tiered and attributed (%s)"
              % ", ".join("%s %d" % (t, n) for t, n in sorted(tiers.items())))
    else:
        print("  none recorded")
    return 1 if (problems or xproblems) else 0


if __name__ == "__main__":
    sys.exit(main())
