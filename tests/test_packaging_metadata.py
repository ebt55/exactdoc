"""The declared dependency set must match the one that was audited.

`docs/license-audit.md` is a claim about exactly which packages exactdoc pulls
in, and therefore about which licences reach a user. A claim like that decays
the moment someone adds a dependency, and nothing noticed -- so this turns the
audit's §1 and §2 tables into an executable comparison. Add a dependency, move
one between core and an extra, or rename an extra, and this goes red naming the
difference.

**pyproject.toml is the source of truth here, deliberately, and installed
metadata is NOT.** That is not a stylistic preference; it is a measured fact
about this repository. At the time of writing, the editable install in the
development virtualenv reported:

    pypdfium2>=4.25                      <- core
    pymupdf>=1.23; extra == "mupdf"      <- an extra

while `pyproject.toml` declared the exact inverse -- PyMuPDF core, pypdfium2
behind the `pdfium` extra, and no `mupdf` extra at all. A `.dist-info` is frozen
at install time and an editable install does not refresh it when the source
tree's metadata changes. Anyone auditing licences through `importlib.metadata`
in that environment would have concluded that the AGPL dependency was already
optional -- the single most consequential thing it is possible to be wrong about
here, wrong in the reassuring direction.

So the installed distribution is *reported* by this module and never asserted
against. See `test_installed_metadata_is_reported_never_trusted`.

**Residual gap, stated rather than papered over.** The strongest version of this
check reads `Requires-Dist` out of a freshly *built* wheel, because the wheel is
what a user installs and it is the only artifact whose metadata is guaranteed to
have been generated from the current `pyproject.toml`. That is not done here:
`build`, `setuptools` and `wheel` are all absent from the pinned virtualenv, and
installing them into a shared environment to satisfy a test is a change to
everyone's toolchain that a test should not make silently. What is asserted
instead is the declaration that a build would consume, which catches every edit
to that declaration and does not catch a build backend that mistranslates it.
Closing the gap needs build tooling in the environment, and it is recorded in
`docs/license-audit.md` §8 as the outstanding item it is.

    python -m unittest tests.test_packaging_metadata
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(ROOT, "pyproject.toml")


# The audited set: docs/license-audit.md §1 (core) and §2 (extras). Names only
# -- version floors move for reasons that are not licence reasons, and pinning
# them here would make this test noisy about the one thing it does not audit.
AUDITED_CORE = {"pymupdf", "python-docx", "numpy", "pillow", "lxml"}
AUDITED_EXTRAS = {
    "test": {"reportlab", "fpdf2"},
    "pdfium": {"pypdfium2"},
    "gdocs": {"google-api-python-client", "google-auth-httplib2",
              "google-auth-oauthlib"},
}
# Audited as carrying a copyleft term that governs distribution of exactdoc
# itself. fpdf2 (LGPL) and certifi (MPL) are excluded on the reasoning in the
# audit: neither is imported by anything exactdoc ships.
AUDITED_AGPL = {"pymupdf"}


def normalise(name):
    """PEP 503 name normalisation, so python_docx and python-docx are one name."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def requirement_name(requirement):
    """The distribution name from a requirement string.

    `pymupdf>=1.23` -> `pymupdf`; `reportlab>=4.0; extra == "test"` ->
    `reportlab`; `pillow[extra]>=10` -> `pillow`.
    """
    head = re.split(r"[\[<>=!~;\s]", requirement.strip(), 1)[0]
    return normalise(head)


def _quoted_strings(block):
    return re.findall(r"[\"']([^\"']+)[\"']", block)


def _balanced_list(text, start):
    """The text of the `[...]` list beginning at `start`, brackets balanced."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_pyproject_text(text):
    """-> (core, {extra: set}) without a TOML parser.

    Deliberately dependency-free: the package declares
    `requires-python = ">=3.9"`, and `tomllib` arrived in 3.11. A test that only
    runs on new interpreters is a test that is absent exactly where an old
    interpreter is doing something surprising.  `test_both_parsers_agree` checks
    this against `tomllib` wherever `tomllib` exists, so the hand-rolled path is
    not the untested one.
    """
    match = re.search(r"^dependencies\s*=\s*\[", text, re.M)
    core = set()
    if match:
        block = _balanced_list(text, match.end() - 1)
        core = {requirement_name(s) for s in _quoted_strings(block or "")}

    extras = {}
    section = re.search(r"^\[project\.optional-dependencies\]\s*$", text, re.M)
    if section:
        rest = text[section.end():]
        nxt = re.search(r"^\[", rest, re.M)
        rest = rest[:nxt.start()] if nxt else rest
        for m in re.finditer(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*\[", rest, re.M):
            block = _balanced_list(rest, m.end() - 1)
            extras[normalise(m.group(1))] = {
                requirement_name(s) for s in _quoted_strings(block or "")}
    return core, extras


def parse_pyproject_tomllib(text):
    """The same, via tomllib. Returns None where tomllib is unavailable."""
    try:
        import tomllib
    except ImportError:
        return None
    data = tomllib.loads(text)
    project = data.get("project", {})
    core = {requirement_name(r) for r in project.get("dependencies", [])}
    extras = {normalise(k): {requirement_name(r) for r in v}
              for k, v in (project.get("optional-dependencies") or {}).items()}
    return core, extras


def read_pyproject():
    with open(PYPROJECT, encoding="utf-8") as fh:
        return fh.read()


class PackagingMetadataTests(unittest.TestCase):

    def setUp(self):
        self.text = read_pyproject()
        self.core, self.extras = parse_pyproject_text(self.text)

    # -- the audit, as an executable comparison ---------------------------
    def test_core_dependencies_match_the_audit(self):
        self.assertEqual(
            self.core, AUDITED_CORE,
            "pyproject's core dependencies no longer match docs/license-audit.md "
            "§1. Added: %s. Removed: %s. A dependency that reaches users without "
            "reaching the audit is the failure this test exists for -- update "
            "the audit (licence, role, Apache-2.0 compatibility) and then this "
            "set." % (sorted(self.core - AUDITED_CORE),
                      sorted(AUDITED_CORE - self.core)))

    def test_extras_match_the_audit(self):
        self.assertEqual(
            set(self.extras), set(AUDITED_EXTRAS),
            "the set of optional-dependency extras changed: %r against the "
            "audited %r" % (sorted(self.extras), sorted(AUDITED_EXTRAS)))
        for name in sorted(AUDITED_EXTRAS):
            self.assertEqual(
                self.extras.get(name), AUDITED_EXTRAS[name],
                "extra %r no longer matches docs/license-audit.md §2. Added: %s. "
                "Removed: %s."
                % (name, sorted(self.extras.get(name, set()) - AUDITED_EXTRAS[name]),
                   sorted(AUDITED_EXTRAS[name] - self.extras.get(name, set()))))

    def test_no_dependency_is_declared_twice(self):
        """A package in core and in an extra installs from core regardless.

        Which makes the extra a comment rather than a switch -- and if that
        package is the AGPL one, a `pip install exactdoc` that looks like it
        excluded it does not.
        """
        for name, members in sorted(self.extras.items()):
            overlap = members & self.core
            self.assertFalse(
                overlap,
                "extra %r also appears in core: %s. An extra cannot make a core "
                "dependency optional." % (name, sorted(overlap)))

    # -- the relicence position, asserted rather than described -----------
    def test_pymupdf_is_still_core_and_is_the_licence_blocker(self):
        """The AGPL position, in the file that decides it.

        Asserting today's state rather than the desired one is deliberate: when
        this goes red, the relicence has *moved*, and moving it should require
        looking at this test, `tests/test_no_pymupdf.py` and the audit together
        rather than none of them.
        """
        self.assertEqual(
            AUDITED_AGPL & self.core, AUDITED_AGPL,
            "PyMuPDF is no longer a core dependency. That is the relicensing "
            "goal, so this is not necessarily wrong -- but it means "
            "docs/license-audit.md §1, its gate (c), and the base-wheel check "
            "in tests/test_no_pymupdf.py all need updating in the same change.")
        for extra, members in sorted(self.extras.items()):
            self.assertFalse(
                AUDITED_AGPL & members,
                "an AGPL package appears in extra %r as well as core; see "
                "test_no_dependency_is_declared_twice" % extra)

    def test_declared_licence_still_matches_the_dependency_position(self):
        """AGPL in core and a non-AGPL project licence cannot both be right."""
        declared = re.search(r"^license\s*=\s*(.+)$", self.text, re.M)
        self.assertIsNotNone(declared, "pyproject declares no license")
        text = declared.group(1)
        self.assertIn(
            "AGPL", text,
            "the project licence is %s while PyMuPDF is still a core "
            "dependency. Either the relicence landed without its gates, or the "
            "dependency moved without this file following." % text.strip())

    # -- the hand-rolled parser, checked against a real one ----------------
    def test_both_parsers_agree(self):
        viaint = parse_pyproject_tomllib(self.text)
        if viaint is None:
            self.skipTest("tomllib unavailable (Python < 3.11)")
        self.assertEqual((self.core, self.extras), viaint,
                         "the dependency-free parser disagrees with tomllib")

    # -- installed metadata: reported, never trusted -----------------------
    def test_installed_metadata_is_reported_never_trusted(self):
        """Report divergence loudly; assert nothing against it.

        A `.dist-info` is frozen at install time, and an editable install does
        not refresh it when pyproject changes. Failing the suite on that would
        be failing it for a stale virtualenv rather than for anything in the
        repository -- and passing *because* of it would be worse, which is the
        real point: when this was written the installed metadata claimed
        PyMuPDF was an optional extra and pypdfium2 was core, the exact inverse
        of the truth.

        So this test always passes and prints. It exists so the divergence is
        visible in test output rather than discovered during a licence review.
        """
        try:
            import importlib.metadata as md
            dist = md.distribution("exactdoc")
            requires = dist.metadata.get_all("Requires-Dist") or []
        except Exception as exc:                       # noqa: BLE001
            print("\n  [packaging] exactdoc is not installed (%s); "
                  "nothing to compare." % type(exc).__name__)
            return

        installed_core, installed_extras = set(), {}
        for raw in requires:
            name = requirement_name(raw)
            marker = re.search(r"extra\s*==\s*[\"']([^\"']+)[\"']", raw)
            if marker:
                installed_extras.setdefault(normalise(marker.group(1)),
                                            set()).add(name)
            else:
                installed_core.add(name)

        if installed_core == self.core and installed_extras == self.extras:
            print("\n  [packaging] installed metadata agrees with pyproject.")
            return

        print("\n  [packaging] INSTALLED METADATA DIVERGES FROM pyproject.toml.")
        print("    This is NOT asserted -- a .dist-info is frozen at install "
              "time and an editable install does not refresh it.")
        print("    core   pyproject: %s" % sorted(self.core))
        print("    core   installed: %s" % sorted(installed_core))
        if installed_extras != self.extras:
            print("    extras pyproject: %s"
                  % {k: sorted(v) for k, v in sorted(self.extras.items())})
            print("    extras installed: %s"
                  % {k: sorted(v) for k, v in sorted(installed_extras.items())})
        agpl_core_installed = AUDITED_AGPL & installed_core
        if not agpl_core_installed and AUDITED_AGPL & self.core:
            print("    NOTE: the installed metadata implies the AGPL dependency "
                  "is optional. pyproject says it is core. Trusting the former "
                  "would understate the licence obligation -- re-run `uv sync` "
                  "before reading dependency licences out of this environment.")


if __name__ == "__main__":
    unittest.main()
