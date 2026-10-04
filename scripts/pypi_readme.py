"""Point README.md's relative links at GitHub before a build, for PyPI.

    python scripts/pypi_readme.py --ref v0.3.0b1      # rewrites README.md in place

README.md is written for GitHub, where `docs/usage.md` and
`docs/images/hero-whitepaper.png` resolve against the repository. PyPI renders
the same file as the project page (pyproject's `readme`), resolves nothing, and
shows every picture broken and every link dead. The release workflow runs this
in its own checkout just before `python -m build`, so the uploaded description
links to the files AT THE TAG being released -- the page cannot drift when
`main` moves on -- while the README in the repository stays relative.

Rewritten: Markdown links and images `](path)` and HTML `src="path"` /
`href="path"`. Left alone: absolute URLs, `#anchors`, `mailto:`. Pictures go to
raw.githubusercontent.com (an image URL must serve the bytes), everything else
to the github.com file view.
"""
import argparse
import os
import re
import sys

REPO = "ebt55/exactdoc"
_IMAGE = re.compile(r"\.(png|jpe?g|gif|svg|webp)$", re.I)
_MD_LINK = re.compile(r"(!?\[[^\]]*\]\()([^)\s]+)(\))")
_HTML_ATTR = re.compile(r"""((?:src|href)=")([^"]+)(")""")


def _absolute(target, ref, image=False):
    if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith(("#", "/")):
        return target
    path = target[2:] if target.startswith("./") else target
    if image or _IMAGE.search(path.split("#")[0]):
        return "https://raw.githubusercontent.com/%s/%s/%s" % (REPO, ref, path)
    return "https://github.com/%s/blob/%s/%s" % (REPO, ref, path)


def rewrite(text, ref):
    text = _MD_LINK.sub(
        lambda m: m.group(1) + _absolute(m.group(2), ref,
                                         image=m.group(1).startswith("!"))
        + m.group(3), text)
    text = _HTML_ATTR.sub(
        lambda m: m.group(1) + _absolute(m.group(2), ref,
                                         image=m.group(1).startswith("src"))
        + m.group(3), text)
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref", required=True,
                    help="the git tag or commit the links should point at")
    ap.add_argument("--readme", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "README.md"))
    a = ap.parse_args(argv)
    with open(a.readme, encoding="utf-8") as fh:
        before = fh.read()
    after = rewrite(before, a.ref)
    with open(a.readme, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(after)
    changed = sum(1 for x, y in zip(before.splitlines(), after.splitlines()) if x != y)
    print("README.md: %d line(s) now link to %s at %s" % (changed, REPO, a.ref))
    return 0


if __name__ == "__main__":
    sys.exit(main())
