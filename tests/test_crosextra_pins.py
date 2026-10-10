"""The gate image's Carlito/Caladea are the files the converter's widths came from (WP31).

`exactdoc/_clone_widths.py` is generated from Carlito and Caladea font files and
records each file's SHA-256 in SOURCES. The canonical renderer now has those
families too (docker/gate-carlito.Dockerfile, docker/gate.Dockerfile,
scripts/bootstrap.sh), and the two must be the SAME build: measured 2026-10-06,
noble's fonts-crosextra-caladea 20200211 differs from Cambria's advances on
135-173 WinAnsi codepoints per face (proportional figures: "1" is 362 units
where Cambria's tabular figures are 554), so a renderer with that build would
wrap differently from every prediction the ladder makes. Three files pin the
digests by hand; this keeps them one set.

It also parses scripts/fonts.conf as XML. A double hyphen inside its comment is
legal-looking prose and invalid XML, and fontconfig's response to an invalid
config is to ignore it and load the system defaults -- every pinned family
silently gone. That happened once while writing WP31.

    python -m unittest tests.test_crosextra_pins
"""
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from exactdoc import _clone_widths as C                       # noqa: E402

PINNED = ("docker/gate-carlito.Dockerfile", "docker/gate.Dockerfile",
          "scripts/bootstrap.sh")
_LINE = re.compile(r"([0-9a-f]{64})  ((?:Carlito|Caladea)-\w+\.ttf)")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class DigestsAreOneSet(unittest.TestCase):
    def test_every_pin_names_the_clone_width_sources(self):
        want = {fname: sha for fname, sha in C.SOURCES.values()}
        self.assertEqual(len(want), 8)
        for rel in PINNED:
            got = {f: sha for sha, f in _LINE.findall(_read(rel))}
            self.assertEqual(got, want, "%s pins different Carlito/Caladea "
                             "files than exactdoc/_clone_widths.py SOURCES" % rel)


class FontsConf(unittest.TestCase):
    def setUp(self):
        self.root = ET.fromstring(_read("scripts/fonts.conf"))

    def test_is_well_formed_and_lists_the_crosextra_directory(self):
        dirs = [d.text for d in self.root.findall("dir")]
        self.assertIn("/usr/share/fonts/truetype/crosextra", dirs)

    def test_maps_exactly_the_two_office_names_onto_their_clones(self):
        got = {}
        for m in self.root.findall("match"):
            test = m.find("test/string")
            edit = m.find("edit/string")
            if test is not None and edit is not None:
                got[test.text] = edit.text
        self.assertEqual(got.get("Calibri"), "Carlito")
        self.assertEqual(got.get("Cambria"), "Caladea")
        # No metric-compatible face exists for these; mapping them would be a
        # guess presented as a substitution.
        self.assertNotIn("Calibri Light", got)
        # The pre-existing core mappings are untouched.
        self.assertEqual(got.get("Arial"), "Liberation Sans")
        self.assertEqual(got.get("Times New Roman"), "Liberation Serif")
        self.assertEqual(got.get("Courier New"), "Liberation Mono")


if __name__ == "__main__":
    unittest.main()
