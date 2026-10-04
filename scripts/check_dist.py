"""Check a built sdist and wheel before anyone installs or uploads them.

    python -m build && python scripts/check_dist.py dist/

Fails (exit 1) naming every problem when:

  * there is not exactly one sdist and one wheel, or their version is not
    pyproject.toml's;
  * the wheel is missing a module the source tree has, or carries anything but
    the `exactdoc` package and its metadata;
  * the sdist carries anything outside its allow-list (MANIFEST.in explains
    the list): no tests, no testkit batch or sweep output, no corpus, no
    DOCX/PDF/image files;
  * any member's path or text holds an absolute path from a developer machine
    (a home directory on Windows, macOS or Linux), or matches a pattern in
    EXACTDOC_DIST_DENY.

The allow-list is what keeps documents out: only `exactdoc/*.py` and metadata
can ship, so no PDF, DOCX or image can. The names of private documents are
deliberately NOT written here -- a public deny-list would publish them. A
maintainer who wants them checked by name sets EXACTDOC_DIST_DENY to a
`os.pathsep`-separated list of regular expressions in their own shell.

Standard library only, so it runs in the bare build environment of the CI and
release workflows before the package is installed anywhere.
"""
import glob
import os
import re
import sys
import tarfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SDIST_ALLOWED = re.compile(
    r"^(PKG-INFO|setup\.cfg|pyproject\.toml|README\.md|LICENSE|MANIFEST\.in"
    r"|exactdoc/[A-Za-z0-9_]+\.py"
    r"|exactdoc\.egg-info/[A-Za-z_.-]+)$")
WHEEL_ALLOWED = re.compile(
    r"^(exactdoc/[A-Za-z0-9_]+\.py"
    r"|exactdoc-[^/]+\.dist-info/(METADATA|WHEEL|RECORD|entry_points\.txt"
    r"|top_level\.txt|licenses/LICENSE))$")
# Never in a distribution, in a path or in text.
FORBIDDEN = [
    (re.compile(r"[A-Za-z]:\\+Users\\+[^\\\s\"']+", re.I), "a Windows home directory"),
    (re.compile(r"/home/[a-z][a-z0-9_-]*/"), "a Linux home directory"),
    (re.compile(r"/Users/[A-Za-z][A-Za-z0-9_-]*/"), "a macOS home directory"),
]


def _forbidden():
    extra = [p for p in os.environ.get("EXACTDOC_DIST_DENY", "").split(os.pathsep)
             if p.strip()]
    return FORBIDDEN + [(re.compile(p, re.I), "a denied pattern (%s)" % p)
                        for p in extra]


def _version():
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
        m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
    return m.group(1) if m else None


def _scan_text(label, name, data, problems):
    forbidden = _forbidden()
    for rx, what in forbidden:
        if rx.search(name):
            problems.append("%s: %s in a member path (%s)" % (label, what, name))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        problems.append("%s: %s is not UTF-8 text" % (label, name))
        return
    for rx, what in forbidden:
        m = rx.search(text)
        if m:
            problems.append("%s: %s in %s: %r" % (label, what, name, m.group(0)))


def check(dist_dir):
    problems = []
    version = _version()
    sdists = glob.glob(os.path.join(dist_dir, "*.tar.gz"))
    wheels = glob.glob(os.path.join(dist_dir, "*.whl"))
    if len(sdists) != 1 or len(wheels) != 1:
        return ["expected one sdist and one wheel in %s, found %d and %d"
                % (dist_dir, len(sdists), len(wheels))], {}
    sdist, wheel = sdists[0], wheels[0]
    for path in (sdist, wheel):
        if "exactdoc-%s" % version not in os.path.basename(path):
            problems.append("%s is not version %s (pyproject.toml)"
                            % (os.path.basename(path), version))

    with tarfile.open(sdist) as tf:
        members = [m for m in tf.getmembers() if m.isfile()]
        names = []
        for m in members:
            name = m.name.split("/", 1)[1] if "/" in m.name else m.name
            names.append(name)
            if not SDIST_ALLOWED.match(name):
                problems.append("sdist: unexpected member %s" % name)
                continue
            _scan_text("sdist", name, tf.extractfile(m).read(), problems)

    source = sorted(os.path.basename(p) for p in
                    glob.glob(os.path.join(ROOT, "exactdoc", "*.py")))
    with zipfile.ZipFile(wheel) as zf:
        wnames = zf.namelist()
        for name in wnames:
            if not WHEEL_ALLOWED.match(name):
                problems.append("wheel: unexpected member %s" % name)
                continue
            _scan_text("wheel", name, zf.read(name), problems)
        meta = next((n for n in wnames if n.endswith(".dist-info/METADATA")), None)
        if meta:
            text = zf.read(meta).decode("utf-8")
            if "Description-Content-Type: text/markdown" not in text:
                problems.append("wheel: METADATA does not declare a Markdown README")
            if "Version: %s" % version not in text:
                problems.append("wheel: METADATA version is not %s" % version)
    shipped = sorted(n.split("/", 1)[1] for n in wnames
                     if n.startswith("exactdoc/"))
    missing = sorted(set(source) - set(shipped))
    if missing:
        problems.append("wheel: missing modules %s" % ", ".join(missing))
    sdist_modules = sorted(n.split("/", 1)[1] for n in names
                           if n.startswith("exactdoc/"))
    if sorted(set(source) - set(sdist_modules)):
        problems.append("sdist: missing modules %s"
                        % ", ".join(sorted(set(source) - set(sdist_modules))))
    return problems, {"sdist": (os.path.basename(sdist), len(names)),
                      "wheel": (os.path.basename(wheel), len(wnames))}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    dist_dir = argv[0] if argv else os.path.join(ROOT, "dist")
    problems, info = check(dist_dir)
    for kind, (name, n) in sorted(info.items()):
        print("%-5s %s (%d files)" % (kind, name, n))
    if problems:
        print("DIST CHECK FAILED:")
        for p in problems:
            print("  - " + p)
        return 1
    print("dist check passed: contents are the package, its metadata, README "
          "and LICENSE, and nothing personal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
