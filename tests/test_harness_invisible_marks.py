"""The harness reads a word without the invisible marks Google Docs exports.

Google Docs' PDF exporter writes U+200B where a tab or a soft line break ends a
text segment ("800-63B\\u200b" before a running head's tab, the end of every
soft-broken code line): 16,526 of the 990,342 words of the 2c1c68f live sweep's
exports carried one, and each then matched no source word -- a correctly placed
word scored as missing (WP19).
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))

import harness  # noqa: E402


class _Page:
    def __init__(self, words):
        self._w = words

    def get_textpage(self, **_kw):
        return None

    def get_text(self, kind, textpage=None):
        if kind == "rawdict":                # no character layer: box tops
            return {"blocks": []}
        assert kind == "words"
        return list(self._w)


class _Doc(list):
    def close(self):
        pass


class InvisibleMarks(unittest.TestCase):
    def test_a_zero_width_space_is_not_part_of_the_word(self):
        words = [(72.0, 35.2, 94.8, 46.4, "NIST", 0, 0, 0),
                 (113.7, 35.2, 154.2, 46.4, "800-63B\u200b", 0, 0, 2),
                 (160.0, 35.2, 161.0, 46.4, "\u200b", 0, 0, 3),
                 (170.0, 35.2, 190.0, 46.4, "\ufeffTerms", 0, 0, 4)]
        with mock.patch.object(harness.fitz, "open",
                               return_value=_Doc([_Page(words)])):
            got = harness.page_words("x.pdf")
        self.assertEqual([w[0] for w in got[0]], ["NIST", "800-63B", "Terms"])
        self.assertEqual(got[0][1][1:5], (113.7, 35.2, 154.2, 46.4))


if __name__ == "__main__":
    unittest.main()
