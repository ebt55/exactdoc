"""One artifact that every published number traces to.

The README, ROADMAP and STATUS each carried numbers, each with prose about
which environment and profile produced them, and they had already drifted apart:
one said `12 same / 2 better` where another said `13 same / 1 better`, and the
README's headline within-2pt was measured on a refine profile that no shipping
surface actually ran. Prose cannot be diffed and cannot be verified, so the fix
is not more careful prose -- it is a machine-readable record, addressed by
commit, that the docs quote and CI attaches to the run.

    python testkit/evidence.py                  # environment only, to stdout
    python testkit/evidence.py --out evidence.json

`runall.py` and `backend_parity.py` fold their lanes into the same file, so a
release can be checked against exactly one artifact:

    commit + dirty flag        what code produced this
    environment               OS, Python, dependency versions, oracle versions
    profile                   the ConversionOptions actually measured
    corpus                    the manifest, and whether it verified
    lanes                     per-document metrics and the gate verdict
    parity                    the backend comparison verdict
    package                   the installed-artifact smoke status
"""
import json
import os
import platform
import re
import subprocess
import sys

import _paths  # noqa: F401
from _paths import CHROME, PROJECT, SOFFICE

SCHEMA = 1


def _run(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return (p.stdout or b"").decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def git_state():
    """Commit, branch and whether the tree was clean when this was measured.

    A dirty tree is recorded, not rejected: measuring uncommitted work is the
    normal development loop. It is a release gate's job to refuse it, and it
    cannot refuse what it was never told.

    `available` distinguishes "the tree was clean" from "there was no git here to
    ask" -- the measurement container holds a *copy* of the tree with no
    repository, and a missing commit that reads as an empty string would let an
    artifact claim provenance it does not have. Stamp such a run from the real
    checkout with `evidence.py --stamp-git`.
    """
    def g(*args):
        return _run(["git", "-C", PROJECT] + list(args))
    commit = g("rev-parse", "HEAD")
    if not commit:
        return {"available": False, "clean": None, "commit": None, "short": None,
                "branch": None,
                "note": "no git repository at the measurement location; stamp "
                        "this artifact from the checkout with --stamp-git"}
    status = g("status", "--porcelain")
    return {"available": True,
            "commit": commit,
            "short": g("rev-parse", "--short", HEAD_REF),
            "branch": g("rev-parse", "--abbrev-ref", HEAD_REF),
            "clean": not status,
            "dirty": bool(status),
            "dirty_paths": sorted(l[3:] for l in status.splitlines())[:40]}


HEAD_REF = "HEAD"


def dependency_versions():
    """Installed versions of everything whose output can move a metric."""
    out = {}
    for name in ("pymupdf", "pypdfium2", "python-docx", "numpy", "pillow",
                 "lxml", "reportlab", "fpdf2"):
        try:
            from importlib.metadata import PackageNotFoundError, version
            out[name] = version(name)
        except Exception:
            out[name] = None
    # The bundled native libraries matter more than the wrapper versions: the
    # goldens are pinned to a PyMuPDF version because 1.26 and 1.28 group the
    # same page differently (STATUS.md §5).
    try:
        import fitz
        out["mupdf"] = getattr(fitz, "mupdf_version", None) or \
            getattr(fitz, "VersionBind", None)
    except Exception:
        out["mupdf"] = None
    try:
        import pypdfium2
        out["pdfium"] = str(getattr(pypdfium2, "PDFIUM_INFO", ""))or None
    except Exception:
        out["pdfium"] = None
    return out


def oracle_versions():
    """The renderers. Their build decides the fidelity numbers, so name it."""
    lo = _run([SOFFICE, "--version"]) if SOFFICE else ""
    ch = _run([CHROME, "--version"]) if CHROME else ""
    fonts = _run(["fc-list"])
    liberation = sorted(set(
        re.findall(r"(Liberation \w+)", fonts)))[:6] if fonts else []
    return {"soffice_path": SOFFICE, "soffice_version": lo.splitlines()[0] if lo else None,
            "chrome_path": CHROME, "chrome_version": ch.splitlines()[0] if ch else None,
            "metric_fonts": liberation}


def environment():
    return {
        "os": platform.system().lower(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "dependencies": dependency_versions(),
        "oracles": oracle_versions(),
        "canonical": platform.system().lower() == "linux",
    }


def new(profile=None):
    """A fresh evidence document. Lanes and verdicts are added as they run."""
    return {"schema": SCHEMA, "git": git_state(), "environment": environment(),
            "profile": profile, "corpus": None, "lanes": {}, "parity": None,
            "package": None}


def merge(path, **sections):
    """Fold sections into the evidence file at `path`, creating it if absent.

    Separate processes produce the lanes, the parity verdict and the package
    smoke result, and a release needs them in one artifact. Merging rather than
    rewriting is what lets CI run them as independent steps without one step's
    success erasing another's.

    A `None` section is *skipped*, not written. Without that, the plain
    `evidence.py --out` step -- which exists to fill in the environment when
    nothing else has -- passed the empty template's `parity: None` and
    `corpus: None` straight over the verdicts the two preceding steps had already
    recorded. Measured: a full green run ended with an evidence file that had
    forgotten its own parity result. An artifact whose job is to be the single
    source of a release claim must not have a write path that quietly empties it.
    """
    doc = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                doc = json.load(f)
        except ValueError:
            doc = {}
    if not doc:
        doc = new()
    for k, v in sections.items():
        if v is None:
            continue
        if k == "lanes" and isinstance(v, dict):
            doc.setdefault("lanes", {}).update(v)
        else:
            doc[k] = v
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
    return path


def validate(doc, expect_documents=None):
    """-> [problem, ...]. Is this artifact fit to support a release claim?

    An evidence file is only useful if its *absences* are visible. A release
    reviewer reading a summary cannot tell "parity passed" from "parity never
    ran", and the two look identical in a document that simply lacks the section.
    """
    out = []
    g = doc.get("git") or {}
    if not g.get("available"):
        out.append("no commit recorded -- stamp with `evidence.py --stamp-git` "
                   "from the checkout")
    elif not g.get("clean"):
        out.append("measured against a DIRTY tree (%d path(s) modified); the "
                   "commit does not describe what ran"
                   % len(g.get("dirty_paths") or []))
    env = doc.get("environment") or {}
    if not env.get("canonical"):
        out.append("not measured on the canonical environment (os=%s)"
                   % env.get("os"))
    if not (env.get("oracles") or {}).get("soffice_version"):
        out.append("no LibreOffice version recorded")
    deps = env.get("dependencies") or {}
    for name in ("pymupdf", "pypdfium2"):
        if not deps.get(name):
            out.append("no %s version recorded" % name)

    corpus = doc.get("corpus") or {}
    n = corpus.get("resolved")
    want = expect_documents if expect_documents is not None \
        else corpus.get("manifest_documents")
    if n is None:
        out.append("no corpus section")
    elif want is not None and n != want:
        out.append("corpus covered %s of %s manifest documents" % (n, want))
    if corpus.get("problems"):
        out.append("corpus had %d problem(s)" % len(corpus["problems"]))

    lanes = doc.get("lanes") or {}
    for lane in ("raw", "product"):
        if lane not in lanes:
            out.append("lane %r missing" % lane)
        elif not (lanes[lane].get("verdict") or {}).get("ok"):
            out.append("lane %r did not pass" % lane)
    p = doc.get("parity")
    if not p:
        out.append("no parity section -- absent and failed look the same")
    elif not p.get("ok"):
        out.append("parity did not pass (%s unwaived regression(s))"
                   % p.get("regressions"))
    return out


def summarise(doc):
    """The lines a human should read before believing a release claim."""
    g, e = doc.get("git", {}), doc.get("environment", {})
    if not g.get("available"):
        commit = "(unstamped -- no git at the measurement location)"
    else:
        commit = "%s%s on %s" % (g.get("short"),
                                 "" if g.get("clean") else " (DIRTY TREE)",
                                 g.get("branch"))
    out = ["commit  %s" % commit,
           "env     %s %s, python %s%s" % (
               e.get("os"), e.get("machine"), e.get("python"),
               "" if e.get("canonical") else "  [NOT the canonical environment]"),
           "oracle  %s" % ((e.get("oracles") or {}).get("soffice_version") or "none")]
    if doc.get("profile"):
        out.append("profile %s" % doc["profile"].get("profile_id", "?"))
    for lane, data in sorted((doc.get("lanes") or {}).items()):
        agg = data.get("aggregate") or {}
        verdict = data.get("verdict") or {}
        out.append("lane    %-8s %s  pagematch %s/%s  <2pt %s  live %s  dy50 %s"
                   % (lane, "PASS" if verdict.get("ok") else "FAIL",
                      agg.get("page_match_count"), agg.get("n"),
                      agg.get("mean_within2pt"), agg.get("mean_live_text"),
                      agg.get("median_dy_p50")))
    p = doc.get("parity") or {}
    if p:
        out.append("parity  %s  %s regression(s), %s same, %s better"
                   % ("PASS" if p.get("ok") else "FAIL", p.get("regressions"),
                      p.get("same"), p.get("better")))
    pk = doc.get("package") or {}
    if pk:
        out.append("package %s  %s" % ("PASS" if pk.get("ok") else "FAIL",
                                       pk.get("detail", "")))
    problems = validate(doc)
    if problems:
        out.append("NOT RELEASE-GRADE EVIDENCE:")
        out.extend("  - %s" % p for p in problems)
    else:
        out.append("release-grade: commit, clean tree, canonical environment, "
                   "full corpus, both lanes and parity all present and passing")
    return "\n".join(out)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=None, help="write/merge JSON here")
    ap.add_argument("--stamp-git", action="store_true",
                    help="merge ONLY this checkout's git state into --out. For "
                         "an artifact measured somewhere without a repository "
                         "(a container holding a copy of the tree): run it from "
                         "the real checkout so the commit and clean-tree marker "
                         "come from the authority on them, and the measurement "
                         "environment is left untouched.")
    a = ap.parse_args()

    if a.stamp_git:
        if not a.out:
            ap.error("--stamp-git needs --out")
        state = git_state()
        if not state.get("available"):
            print("no git repository here either; nothing to stamp")
            raise SystemExit(2)
        merge(a.out, git=state)
        with open(a.out) as f:
            doc = json.load(f)
        print("stamped %s with %s%s"
              % (a.out, state["short"], "" if state["clean"] else " (DIRTY)"))
        print(summarise(doc))
        raise SystemExit(0)

    doc = new()
    if a.out:
        merge(a.out, **{k: v for k, v in doc.items() if k != "schema"})
        with open(a.out) as f:
            doc = json.load(f)          # summarise the artifact, not the template
        print("wrote", a.out)
    print(summarise(doc))
    if not a.out:
        print(json.dumps(doc, indent=1, sort_keys=True))
