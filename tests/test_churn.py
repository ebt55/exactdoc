"""testkit/churn.py splits two renders' matched words honestly.

A synthetic source of six distinct words, one per line, and two "renders" of
it drawn with PyMuPDF: the accepted one places four of the words, the current
one four as well, but not the same four. What is pinned: which words are
common, lost and gained; each set's drift is read in the render it belongs to;
the "all" figures are exactly the harness's own (so they reproduce a sweep's
word_recall and dy_p50); a common word that moved between the renders is
counted; frequent tokens are counted from the source; the three PDFs are
hashed; and `--require` / `--check-y37` turn figures into an exit code.

    python -m unittest tests.test_churn
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))
sys.path.insert(0, os.path.join(ROOT, "tests"))               # mupdf_extra

import mupdf_extra  # noqa: E402

if not mupdf_extra.AVAILABLE:                                  # pragma: no cover
    raise unittest.SkipTest(mupdf_extra.REASON)

import fitz  # noqa: E402
import churn  # noqa: E402
import harness  # noqa: E402

WORDS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")


def _pdf(path, placed):
    """One Letter page; `placed` is {word: dy} -- each word on its own line at
    y = 100 + 30 * index, moved down by dy points. Absent words are not drawn."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for i, w in enumerate(WORDS):
        if w in placed:
            page.insert_text((72, 100 + 30 * i + placed[w]), w, fontsize=10)
    doc.save(path)
    doc.close()
    return path


class Churn(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        d = self._td.name
        self.src = _pdf(os.path.join(d, "src.pdf"), {w: 0 for w in WORDS})
        # accepted: alpha, bravo in place; charlie 10pt low; delta 3pt low
        self.acc = _pdf(os.path.join(d, "acc.pdf"),
                        {"alpha": 0, "bravo": 0, "charlie": 10, "delta": 3})
        # current: charlie back to 1pt; delta lost; echo gained 6pt low
        self.cur = _pdf(os.path.join(d, "cur.pdf"),
                        {"alpha": 0, "bravo": 0, "charlie": 1, "echo": 6})
        self.dir = d

    def tearDown(self):
        self._td.cleanup()

    def test_common_lost_and_gained(self):
        r = churn.churn(self.src, self.acc, self.cur)
        self.assertEqual(r["src_words"], 6)
        self.assertEqual(r["matched"], {"accepted": 4, "current": 4, "common": 3,
                                        "lost": 1, "gained": 1})
        self.assertEqual(r["word_recall"], {"accepted": 0.6667, "current": 0.6667})
        # common words read in each render: [0, 0, 10] and [0, 0, 1]
        self.assertEqual(r["dy_p50"]["common_accepted"], 0.0)
        self.assertEqual(r["dy_le5_share"]["common_accepted"], 0.6667)
        self.assertEqual(r["dy_le5_share"]["common_current"], 1.0)
        self.assertEqual(r["within2pt"]["common_accepted"], 0.6667)
        self.assertEqual(r["within2pt"]["common_current"], 1.0)
        # lost delta was 3pt low in the accepted render; gained echo 6pt low
        self.assertAlmostEqual(r["dy_p50"]["lost"], 3.0, places=2)
        self.assertAlmostEqual(r["dy_p50"]["gained"], 6.0, places=2)
        # charlie moved 9pt between the renders: 1 of the 3 common words
        self.assertEqual(r["moved_gt2pt"], {"n": 1, "share": 0.3333})
        self.assertEqual(r["schema"], "exactdoc.churn.v1")

    def test_the_all_figures_are_the_harness_own(self):
        r = churn.churn(self.src, self.acc, self.cur)
        for role, pdf in (("accepted", self.acc), ("current", self.cur)):
            h = harness.word_metrics(self.src, pdf)
            self.assertEqual(r["word_recall"][role], h["word_recall"])
            self.assertEqual(r["dy_p50"][role], h["dy_p50"])
            self.assertEqual(r["within2pt"][role], h["within2pt"])
        self.assertEqual(r["within2pt"]["drop"],
                         round(r["within2pt"]["accepted"] - r["within2pt"]["current"], 4))

    def test_frequent_tokens_and_hashes(self):
        with mock.patch.object(churn, "FREQUENT", 1):        # every token is frequent
            r = churn.churn(self.src, self.acc, self.cur)
        self.assertEqual(r["frequent_tokens"], {"min_count": 1, "lost": 1.0,
                                                "gained": 1.0, "common": 1.0})
        r = churn.churn(self.src, self.acc, self.cur)
        self.assertEqual(r["frequent_tokens"]["lost"], 0.0)  # each word occurs once
        for role, path in (("source", self.src), ("accepted", self.acc),
                           ("current", self.cur)):
            with open(path, "rb") as fh:
                self.assertEqual(r["pdfs"][role]["sha256"],
                                 hashlib.sha256(fh.read()).hexdigest())

    def test_requirements(self):
        r = churn.churn(self.src, self.acc, self.cur)
        self.assertEqual(churn.parse_require("word_recall.current>=0.347"),
                         ("word_recall.current", ">=", 0.347))
        with self.assertRaises(ValueError):
            churn.parse_require("word_recall.current > 0.3")
        got = churn.check(r, [("word_recall.current", ">=", 0.6),
                              ("dy_p50.gained", "<=", 5.0),
                              ("no.such.figure", "<=", 1.0)])
        self.assertEqual([c["ok"] for c in got], [True, False, False])
        # the y37 preset is DECISION.md condition d, the tolerance read from gate.py
        paths = [(p, op, bound) for p, op, bound, _why in churn.y37_requirements()]
        self.assertEqual(paths, [("word_recall.current", ">=", 0.347),
                                 ("dy_p50.common_current", "<=", 23.5),
                                 ("within2pt.drop", "<=", 0.05)])

    def test_main_exit_code_and_json(self):
        out = os.path.join(self.dir, "churn.json")
        with mock.patch("sys.stdout", new=io.StringIO()) as printed:
            rc = churn.main([self.src, self.acc, self.cur, "--json", out,
                             "--require", "word_recall.current>=0.6"])
        self.assertEqual(rc, 0)
        self.assertIn("common 3, lost 1, gained 1", printed.getvalue())
        with open(out, "rb") as fh:
            raw = fh.read()
        self.assertNotIn(b"\r\n", raw)
        self.assertEqual(json.loads(raw)["checks"][0]["ok"], True)
        with mock.patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(churn.main([self.src, self.acc, self.cur, "--check-y37"]), 0)
            self.assertEqual(churn.main([self.src, self.acc, self.cur,
                                         "--require", "dy_p50.gained<=5"]), 1)


if __name__ == "__main__":
    unittest.main()
