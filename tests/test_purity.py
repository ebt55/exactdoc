"""write_docx must not modify the layout it is given.

The cover-band path shifts every page-1 element by the bleed delta with
accumulating assignments. Before this was fixed, writing the same layout twice
produced a different (double-shifted) second document -- silently, and only for
cover-band documents, so 2 of 16 corpus documents were affected and nobody
noticed. refine.py writes the same layout once per round, so this class of bug
corrupts exactly the code path that is hardest to eyeball.

    python -m pytest tests/ -q          (or just: python tests/test_purity.py)
"""
import glob
import hashlib
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exactdoc.parse import parse_pdf          # noqa: E402
from exactdoc.dialect import normalize        # noqa: E402
from exactdoc.infer import infer              # noqa: E402
from exactdoc.docxout import write_docx       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _xml_digest(path):
    """Digest the XML parts only; zip timestamps differ harmlessly."""
    with zipfile.ZipFile(path) as z:
        return {n: hashlib.sha256(z.read(n)).hexdigest()
                for n in sorted(z.namelist()) if n.endswith(".xml")}


def corpus():
    """The frozen fixtures first, then whatever this machine happens to have.

    `testkit/fixtures/` was missing from this list and it is the only corpus
    directory that exists in a clean checkout -- `corpus/pdfs/` and
    `testkit/adv/` are both generated and both gitignored. So on a fresh clone
    this returned nothing, and the __main__ path below then reported success
    having tested zero documents. Deduplicated with the frozen copy winning, so
    a stale generated file cannot shadow the SHA-256-pinned input.
    """
    seen, pdfs = set(), []
    for d in ("testkit/fixtures", "corpus/pdfs", "testkit/adv"):
        for p in sorted(glob.glob(os.path.join(ROOT, d, "*.pdf"))):
            name = os.path.basename(p)
            if name not in seen:
                seen.add(name)
                pdfs.append(p)
    return pdfs


def check(pdf, tmpdir):
    lay = infer(normalize(parse_pdf(pdf)))
    a = os.path.join(tmpdir, "a.docx")
    b = os.path.join(tmpdir, "b.docx")
    write_docx(lay, a)
    write_docx(lay, b)          # same object, deliberately not copied
    return _xml_digest(a) == _xml_digest(b)


def test_write_docx_is_pure(tmp_path=None):
    import tempfile
    pdfs = corpus()
    assert pdfs, "no corpus PDFs; run corpus/make_corpus.py and testkit/gen_corpus.py"
    td = str(tmp_path) if tmp_path else tempfile.mkdtemp()
    bad = [os.path.basename(p) for p in pdfs if not check(p, td)]
    assert not bad, "write_docx mutated its input for: %s" % ", ".join(bad)


if __name__ == "__main__":
    import tempfile
    td = tempfile.mkdtemp()
    pdfs = corpus()
    # Zero documents is a FAILURE, not a quiet pass. This is the path CI runs
    # (`uv run python tests/test_purity.py`), and with no documents it printed
    # "0/0 documents reproducible" and exited 0 -- a purity proof that had
    # written nothing twice. The pytest entry point above asserted; this one did
    # not, and CI uses this one.
    if not pdfs:
        print("no corpus PDFs found. testkit/fixtures/ holds the 16 frozen "
              "inputs and is the only corpus directory present in a clean "
              "checkout; a run with nothing to write proves nothing.")
        sys.exit(1)
    bad = []
    for p in pdfs:
        ok = check(p, td)
        print("%-28s %s" % (os.path.basename(p)[:28], "pure" if ok else "MUTATED"))
        if not ok:
            bad.append(os.path.basename(p))
    print("\n%d/%d documents reproducible on a second write" % (len(pdfs) - len(bad),
                                                                len(pdfs)))
    sys.exit(1 if bad else 0)
