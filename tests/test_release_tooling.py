"""The release tooling: README links for PyPI, and the dist contents check.

    python -m unittest tests.test_release_tooling
"""
import io
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import check_dist                                              # noqa: E402
import pypi_readme                                             # noqa: E402


class PypiReadme(unittest.TestCase):
    def test_relative_links_point_at_the_tag(self):
        src = ("![hero](docs/images/hero.png)\n"
               "[usage](docs/usage.md) and [anchor](#install) and "
               "[web](https://example.org/x)\n"
               '<td><img src="docs/images/a.png" alt="x"></td>\n'
               '<a href="./CHANGELOG.md">log</a>\n')
        out = pypi_readme.rewrite(src, "v0.3.0b1")
        self.assertIn("(https://raw.githubusercontent.com/ebt55/exactdoc/v0.3.0b1/"
                      "docs/images/hero.png)", out)
        self.assertIn("(https://github.com/ebt55/exactdoc/blob/v0.3.0b1/docs/usage.md)",
                      out)
        self.assertIn("(#install)", out)
        self.assertIn("(https://example.org/x)", out)
        self.assertIn('src="https://raw.githubusercontent.com/ebt55/exactdoc/v0.3.0b1/'
                      'docs/images/a.png"', out)
        self.assertIn('href="https://github.com/ebt55/exactdoc/blob/v0.3.0b1/'
                      'CHANGELOG.md"', out)

    def test_the_real_readme_keeps_no_relative_link(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            out = pypi_readme.rewrite(fh.read(), "v9")
        import re
        for target in re.findall(r"\]\(([^)\s]+)\)", out):
            self.assertTrue(target.startswith(("https://", "#", "mailto:")), target)
        for target in re.findall(r'(?:src|href)="([^"]+)"', out):
            self.assertTrue(target.startswith(("https://", "#")), target)


class CheckDist(unittest.TestCase):
    def _dist(self, d, sdist_extra=(), wheel_extra=(), text=b"x = 1\n"):
        version = check_dist._version()
        base = "exactdoc-%s" % version
        modules = sorted(n for n in os.listdir(os.path.join(ROOT, "exactdoc"))
                         if n.endswith(".py"))
        with tarfile.open(os.path.join(d, base + ".tar.gz"), "w:gz") as tf:
            for name in (["PKG-INFO", "pyproject.toml", "README.md", "LICENSE"] +
                         ["exactdoc/" + m for m in modules] + list(sdist_extra)):
                info = tarfile.TarInfo("%s/%s" % (base, name))
                info.size = len(text)
                tf.addfile(info, io.BytesIO(text))
        with zipfile.ZipFile(os.path.join(d, base + "-py3-none-any.whl"), "w") as zf:
            for m in modules:
                zf.writestr("exactdoc/" + m, text)
            zf.writestr(base + ".dist-info/METADATA",
                        "Version: %s\nDescription-Content-Type: text/markdown\n"
                        % version)
            for name in wheel_extra:
                zf.writestr(name, text)

    def test_a_clean_dist_passes(self):
        with tempfile.TemporaryDirectory() as d:
            self._dist(d)
            problems, _ = check_dist.check(d)
            self.assertEqual(problems, [])

    def test_tests_batch_output_and_personal_files_fail(self):
        with tempfile.TemporaryDirectory() as d:
            self._dist(d, sdist_extra=("tests/test_cli.py",
                                       "testkit/batch/lane_raw/x.docx"),
                       wheel_extra=("exactdoc/private-letter.pdf",))
            problems = "\n".join(check_dist.check(d)[0])
            self.assertIn("tests/test_cli.py", problems)
            self.assertIn("testkit/batch", problems)
            self.assertIn("private-letter.pdf", problems)

    def test_a_home_directory_in_text_fails(self):
        with tempfile.TemporaryDirectory() as d:
            self._dist(d, text=b'p = r"C:\\Users\\someone\\private\\cv.pdf"\n')
            problems = "\n".join(check_dist.check(d)[0])
            self.assertIn("Windows home directory", problems)

    def test_a_maintainer_deny_list_applies_to_text(self):
        # names of private documents live in the maintainer's shell, never here
        with tempfile.TemporaryDirectory() as d:
            self._dist(d, text=b'# measured on secret-draft-7\n')
            with mock.patch.dict(os.environ, {"EXACTDOC_DIST_DENY": "secret-draft"}):
                problems = "\n".join(check_dist.check(d)[0])
            self.assertIn("denied pattern (secret-draft)", problems)
            self.assertEqual(check_dist.check(d)[0], [])


if __name__ == "__main__":
    unittest.main()
