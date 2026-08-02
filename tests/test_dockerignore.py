"""Hermetic checks that Docker's build context excludes local secrets/state.

    python tests/test_dockerignore.py
"""
import fnmatch
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IGNORE = os.path.join(ROOT, ".dockerignore")
FAILED = []


def check(name, condition, detail=""):
    print("  %-4s %s%s" % ("ok" if condition else "FAIL", name,
                           "" if condition else "   <-- " + detail))
    if not condition:
        FAILED.append(name)


def patterns():
    """Read active, non-comment Docker patterns without touching secret files."""
    with open(IGNORE, encoding="utf-8") as f:
        return [line.strip().replace("\\", "/") for line in f
                if line.strip() and not line.lstrip().startswith("#")]


def excluded(path, rules):
    """Small positive-pattern matcher for this no-negation context policy.

    The production file intentionally has no ``!`` re-inclusions, so checking
    its allow/deny paths does not require a Docker daemon or its private files.
    """
    path = path.replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    for rule in rules:
        rule = rule.rstrip("/")
        if path == rule or path.startswith(rule + "/"):
            return True
        if fnmatch.fnmatchcase(path, rule):
            return True
        # Docker patterns without a slash also match a basename at any depth.
        if "/" not in rule and any(fnmatch.fnmatchcase(part, rule)
                                  for part in path.split("/")):
            return True
    return False


def test_private_paths_are_excluded():
    rules = patterns()
    private = [
        ".git/objects/pack/secret.pack", ".venv/Lib/site.py",
        ".venv.stale-20260802/pyvenv.cfg", "venv/bin/python",
        ".uv-cache/wheels/cache", "exactdoc.egg-info/PKG-INFO",
        "exactdoc/__pycache__/options.cpython-312.pyc", "credentials.json",
        "token.json", "client_secret_123.apps.googleusercontent.com.json",
        "service.pem", ".env.production", "my_samples/private.pdf",
        "testkit/batch/lane_product/results.json", "testkit/adv/case.pdf",
        "corpus/pdfs/generated.pdf", ".claude/state.json", ".tools/tool",
        "exactdoc — Execution Plan.md", "ESCALATION_RULING_LINEBOX.md",
        "release-plan.md",
    ]
    for path in private:
        check("context excludes %s" % path, excluded(path, rules), repr(rules))


def test_canonical_gate_inputs_remain_in_context():
    rules = patterns()
    required = [
        "docker/gate.Dockerfile", "pyproject.toml", "uv.lock",
        "exactdoc/options.py", "scripts/bootstrap.sh", "scripts/fonts.conf",
        "testkit/runall.py", "testkit/gate.py", "testkit/corpus_manifest.json",
        "testkit/fixtures/01_whitepaper_market.pdf",
        ".github/workflows/gate.yml",
    ]
    for path in required:
        check("context includes %s" % path, not excluded(path, rules), repr(rules))


def test_policy_has_no_dangerous_reinclusions():
    rules = patterns()
    check("context policy has no negated exclusions",
          not [rule for rule in rules if rule.startswith("!")], repr(rules))
    check("Dockerfile remains available", os.path.exists(
        os.path.join(ROOT, "docker", "gate.Dockerfile")))


def main():
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_")]
    print("dockerignore tests (%d)" % len(tests))
    for test in tests:
        print("\n%s" % test.__name__)
        test()
    print("\n%s" % ("all clear" if not FAILED else "%d FAILED: %s" %
                       (len(FAILED), ", ".join(FAILED))))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
