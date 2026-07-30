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
import hashlib
import json
import os
import platform
import re
import subprocess
import sys

import _paths  # noqa: F401
from _paths import CHROME, PROJECT, SOFFICE

# Schema 2: exact environment identity. Schema 1 called an environment
# "canonical" on a Python *minor*, a LibreOffice version *prefix*, a *subset* of
# required fonts, and a merely non-empty FONTCONFIG_FILE -- and it computed a
# fingerprint it then never compared against anything. Four ways to be a
# different environment and still report `canonical: true`. See CANONICAL_REF.
SCHEMA = 2

# The recorded canonical environment, written by `evidence.py --record-canonical`
# from a run that IS canonical. Keeping it as recorded data rather than constants
# in this file is deliberate: the exact LibreOffice build, the exact font set and
# the exact dependency versions are *measurements*, and a hand-maintained constant
# is one edit away from describing an environment nobody ran.
CANONICAL_REF = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "canonical_env.json")


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
    # Every family the renderer can see, not just the Latin ones. Recording only
    # `Liberation \w+` was why two environments with wildly different CJK and RTL
    # coverage both looked identical here -- and c4_i18n is a CJK + Arabic +
    # Hebrew document whose numbers moved 14x between them.
    fonts = _run(["fc-list", ":", "family"])
    families = sorted(set(
        f.strip() for line in fonts.splitlines() for f in line.split(",")
        if f.strip() and f.strip().isascii())) if fonts else []
    return {"soffice_path": SOFFICE,
            "soffice_version": lo.splitlines()[0] if lo else None,
            "chrome_path": CHROME,
            "chrome_version": ch.splitlines()[0] if ch else None,
            "fontconfig_file": os.environ.get("FONTCONFIG_FILE"),
            "font_families": families,
            "font_count": len(families),
            "metric_fonts": sorted(set(re.findall(r"(Liberation \w+)", fonts)))}


def _sha256_file(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def fonts_conf_identity():
    """The font *policy*, hashed -- and whether the renderer is really using it.

    Schema 1 asked only whether FONTCONFIG_FILE was non-empty. That is satisfied
    by pointing it at any file on the machine, including one that adds the
    system's fonts back. The variable that moved `c4_i18n`'s within2pt 0.416 ->
    0.038 was not the presence of a config, it was *which* config: scripts/
    fonts.conf REPLACES fontconfig's search path rather than extending it.

    So record the repository's own fonts.conf digest, and record whether the
    environment variable actually resolves to that exact file.
    """
    repo_conf = os.path.join(PROJECT, "scripts", "fonts.conf")
    active = os.environ.get("FONTCONFIG_FILE") or None
    out = {"repo_path": repo_conf if os.path.exists(repo_conf) else None,
           "repo_sha256": _sha256_file(repo_conf),
           "active_path": active,
           "active_sha256": _sha256_file(active) if active else None}
    # Same *content* is the test, not the same string: CI passes an absolute
    # $GITHUB_WORKSPACE path and the container passes /work, and both are correct.
    out["active_is_repo_conf"] = bool(
        out["active_sha256"] and out["active_sha256"] == out["repo_sha256"])
    return out


def font_file_inventory():
    """Every font FILE the renderer can see, by basename and digest.

    Families are not enough. Two machines can both report "DejaVu Sans" and
    resolve it to different builds with different metrics, and the family list
    cannot tell them apart. Basenames rather than full paths because the same
    canonical font set lives at different prefixes in a container and on a
    runner, and the path is not what moves a metric.
    """
    listing = _run(["fc-list", "--format=%{file}\n"])
    files = sorted({l.strip() for l in listing.splitlines() if l.strip()})
    entries, unreadable = [], []
    for p in files:
        d = _sha256_file(p)
        if d is None:
            unreadable.append(os.path.basename(p))
        else:
            entries.append({"file": os.path.basename(p), "sha256": d})
    entries.sort(key=lambda e: (e["file"], e["sha256"]))
    combined = hashlib.sha256(
        "|".join("%s:%s" % (e["file"], e["sha256"]) for e in entries).encode()
    ).hexdigest() if entries else None
    return {"files": entries, "count": len(entries),
            "unreadable": unreadable, "digest": combined}


def image_identity():
    """The canonical OCI image this run declares, if any.

    A reviewed image referenced by immutable digest is the only way to make
    LibreOffice's build a constant instead of whatever the runner image happens
    to ship this week. Recorded from the environment rather than probed, because
    a process cannot reliably discover the digest of the image containing it.
    """
    return {"ref": os.environ.get("EXACTDOC_GATE_IMAGE") or None,
            "digest": os.environ.get("EXACTDOC_GATE_IMAGE_DIGEST") or None,
            "base_digest": os.environ.get("EXACTDOC_BASE_IMAGE_DIGEST") or None}


# Exactly what the fingerprint covers, in order. Explicit rather than "everything
# in the dict" so that adding a provenance-only field (Chromium, paths, machine)
# cannot silently invalidate every recorded baseline.
#
# Chromium is deliberately absent: the corpus is frozen and pinned by SHA-256
# (corpus_manifest.py), so the browser no longer touches a measured number. It is
# recorded for provenance and does not gate.
def fingerprint(env):
    """A digest of everything that can move a measured number. Exact, not minor.

    Schema 1 hashed the Python *minor* and no font digests, so 3.12.3 and 3.12.13
    -- an actual, metric-moving difference in this repository's history -- produced
    the same fingerprint. It also never compared the result against anything.
    """
    oracles = env.get("oracles") or {}
    deps = env.get("dependencies") or {}
    fc = env.get("fonts_conf") or {}
    fonts = env.get("font_files") or {}
    img = env.get("image") or {}
    parts = [
        env.get("os"),
        env.get("python"),                       # exact, not minor
        oracles.get("soffice_version"),          # exact build string
        fc.get("repo_sha256"),
        fonts.get("digest"),                     # every visible font file
        ",".join(sorted(oracles.get("font_families") or [])),
        img.get("digest"), img.get("base_digest"),
        deps.get("pymupdf"), deps.get("pypdfium2"), deps.get("mupdf"),
        deps.get("pdfium"), deps.get("python-docx"), deps.get("numpy"),
        deps.get("pillow"), deps.get("lxml"),
    ]
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def canonical_reference(path=CANONICAL_REF):
    """The recorded canonical environment, or None if none has been recorded."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# What must match the recorded reference exactly, as (dotted path, label).
_EXACT = (
    ("os", "os"),
    ("python", "python"),
    ("oracles.soffice_version", "LibreOffice"),
    ("fonts_conf.repo_sha256", "scripts/fonts.conf digest"),
    ("font_files.digest", "visible font files digest"),
    ("dependencies.pymupdf", "pymupdf"),
    ("dependencies.pypdfium2", "pypdfium2"),
    ("dependencies.mupdf", "mupdf"),
    ("dependencies.pdfium", "pdfium"),
    ("dependencies.python-docx", "python-docx"),
    ("dependencies.numpy", "numpy"),
    ("dependencies.pillow", "pillow"),
    ("dependencies.lxml", "lxml"),
)


def _dig(d, dotted):
    cur = d
    for k in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def environment_identity(env, ref=None):
    """-> (matches_canonical, [mismatch, ...]). What actually differs, named.

    Every comparison here is an equality against a *recorded* canonical run. No
    prefixes, no minors, no subsets -- each of those was a way to be a different
    environment and still be called canonical, and each one has a mutation test.
    """
    if ref is None:
        ref = canonical_reference()
    if not ref:
        return False, ["no canonical environment has been recorded; run "
                       "`evidence.py --record-canonical` on a canonical run "
                       "(see .github/workflows/gate.yml)"]

    bad = []
    for dotted, label in _EXACT:
        want, got = _dig(ref, dotted), _dig(env, dotted)
        if want is None:
            continue                     # the reference does not pin this field
        if got != want:
            bad.append("%s %r != recorded %r" % (label, got, want))

    # The font set must match EXACTLY in both directions. Schema 1 checked only
    # that the required families were present, so a runner shipping a large font
    # collection on top of them still read as canonical -- and that is precisely
    # what moved c4_i18n's dy_p50 from 0.15pt to 2.1pt with the corpus already
    # frozen byte-for-byte. Installing the right fonts is half the job; seeing no
    # others is the other half.
    want_fams = set((_dig(ref, "oracles.font_families") or []))
    got_fams = set((_dig(env, "oracles.font_families") or []))
    if want_fams:
        missing = sorted(want_fams - got_fams)
        extra = sorted(got_fams - want_fams)
        if missing:
            bad.append("font families missing: %s" % ", ".join(missing))
        if extra:
            bad.append("UNEXPECTED font families visible (the renderer can "
                       "resolve runs to faces the record does not describe): %s"
                       % ", ".join(extra))

    # A config that is merely set is not a config that is applied.
    fc = env.get("fonts_conf") or {}
    if not fc.get("active_path"):
        bad.append("FONTCONFIG_FILE is unset, so the renderer can see whatever "
                   "fonts this machine happens to carry (scripts/fonts.conf)")
    elif not fc.get("active_is_repo_conf"):
        bad.append("FONTCONFIG_FILE=%r is not this repository's scripts/fonts.conf "
                   "(digest %s != %s)" % (fc.get("active_path"),
                                          fc.get("active_sha256"),
                                          fc.get("repo_sha256")))

    if env.get("font_files", {}).get("unreadable"):
        bad.append("font file(s) could not be hashed: %s"
                   % ", ".join(env["font_files"]["unreadable"][:8]))

    # The reference's own fingerprint is the last word: if every field above
    # matched and this still differs, the fingerprint covers something the field
    # list does not, and that is a bug in _EXACT rather than a pass.
    want_fp = ref.get("fingerprint")
    got_fp = env.get("fingerprint")
    if want_fp and got_fp and got_fp != want_fp:
        bad.append("environment fingerprint %s != recorded %s"
                   % (got_fp[:16], want_fp[:16]))
    return (not bad), bad


def environment():
    env = {
        "os": platform.system().lower(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "dependencies": dependency_versions(),
        "oracles": oracle_versions(),
        "fonts_conf": fonts_conf_identity(),
        "font_files": font_file_inventory(),
        "image": image_identity(),
    }
    # Fingerprint first: identity now *enforces* the recorded fingerprint, and it
    # cannot compare a field that has not been computed yet. Schema 1 set it after
    # the check, which is one reason the check could never have used it.
    env["fingerprint"] = fingerprint(env)
    env["schema"] = SCHEMA
    ok, mismatches = environment_identity(env)
    env["canonical"] = ok
    env["canonical_mismatches"] = mismatches
    return env


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
        out.append("not the canonical environment: %s"
                   % "; ".join(env.get("canonical_mismatches") or ["unknown"]))
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
           "env     %s %s, python %s  fp=%s%s" % (
               e.get("os"), e.get("machine"), e.get("python"),
               (e.get("fingerprint") or "?")[:16],
               "" if e.get("canonical") else "  [NOT canonical: %s]"
               % "; ".join(e.get("canonical_mismatches") or [])),
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
    ap.add_argument("--record-canonical", action="store_true",
                    help="write this environment to testkit/canonical_env.json "
                         "as the definition of `canonical`. Refused off Linux, "
                         "without the repository's fonts.conf applied, or with "
                         "any oracle or font digest missing.")
    ap.add_argument("--force", action="store_true",
                    help="with --record-canonical, replace an existing record. "
                         "Redefining canonical invalidates every recorded "
                         "baseline and policy floor bound to the old "
                         "fingerprint, so it is not the default.")
    a = ap.parse_args()

    if a.record_canonical:
        env = environment()
        refuse = []
        if env["os"] != "linux":
            refuse.append("os is %r, not linux -- CI Linux is the number of "
                          "record (Windows renders with real Arial/Times and "
                          "wraps differently)" % env["os"])
        if not (env.get("fonts_conf") or {}).get("active_is_repo_conf"):
            refuse.append("scripts/fonts.conf is not the applied FONTCONFIG_FILE, "
                          "so the visible font set is not the pinned one")
        if not (env.get("oracles") or {}).get("soffice_version"):
            refuse.append("no LibreOffice version -- the renderer decides the "
                          "numbers and this record would not name it")
        if not (env.get("font_files") or {}).get("digest"):
            refuse.append("no font file digest; fc-list returned nothing")
        if (env.get("font_files") or {}).get("unreadable"):
            refuse.append("font file(s) could not be hashed: %s"
                          % ", ".join(env["font_files"]["unreadable"][:8]))
        for dep in ("pymupdf", "pypdfium2"):
            if not (env.get("dependencies") or {}).get(dep):
                refuse.append("no %s version recorded" % dep)
        if refuse:
            print("REFUSED -- this is not a canonical environment:")
            for r in refuse:
                print("  - %s" % r)
            raise SystemExit(2)
        if os.path.exists(CANONICAL_REF) and not a.force:
            old = canonical_reference() or {}
            print("REFUSED -- %s already exists." % CANONICAL_REF)
            print("  recorded fingerprint %s" % (old.get("fingerprint") or "?")[:16])
            print("  this environment     %s" % env["fingerprint"][:16])
            if (old.get("fingerprint") or "") == env["fingerprint"]:
                print("  they match; nothing to do.")
            else:
                print("  they differ. Re-recording redefines `canonical` and "
                      "invalidates every baseline and policy floor bound to the "
                      "old fingerprint. Pass --force only with a deliberate "
                      "baseline migration (see plan §17 rule 2).")
            raise SystemExit(3)
        env["recorded_by"] = "evidence.py --record-canonical"
        env["recorded_at_commit"] = (git_state() or {}).get("commit")
        with open(CANONICAL_REF, "w") as f:
            json.dump(env, f, indent=1, sort_keys=True)
        print("recorded %s" % CANONICAL_REF)
        print("  fingerprint  %s" % env["fingerprint"])
        print("  LibreOffice  %s" % (env["oracles"] or {}).get("soffice_version"))
        print("  python       %s" % env["python"])
        print("  font files   %d (digest %s)"
              % (env["font_files"]["count"], env["font_files"]["digest"][:16]))
        print("  families     %d" % len(env["oracles"].get("font_families") or []))
        raise SystemExit(0)

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
