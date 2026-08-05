"""A parity run must label both arms by the backend each actually used.

Run with ``python tests/test_parity_evidence_labels.py``.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "testkit"))

from exactdoc.options import PRODUCT  # noqa: E402

import backend_parity  # noqa: E402


class ProfileLabelTests(unittest.TestCase):
    def setUp(self):
        self.labels = backend_parity.profile_labels(PRODUCT, "pymupdf", "pdfium")

    def test_the_candidate_label_names_the_candidate_backend(self):
        """The regression this exists for.

        `profile_id` for the product profile is
        pymupdf/standard/libreoffice/refine3@240dpi -- its backend token is the
        REFERENCE. Recording that as the candidate's profile is what made eight
        documents read as MAJOR "under the shipping profile" when the run had
        measured a PDFium swap.
        """
        self.assertTrue(self.labels["candidate_profile_id"].startswith("pdfium/"),
                        self.labels["candidate_profile_id"])
        self.assertNotEqual(self.labels["candidate_profile_id"],
                            self.labels["profile_id"])

    def test_the_reference_label_names_the_reference_backend(self):
        self.assertTrue(self.labels["reference_profile_id"].startswith("pymupdf/"),
                        self.labels["reference_profile_id"])

    def test_the_two_arms_differ_only_in_the_backend(self):
        ref = self.labels["reference_profile_id"].split("/", 1)[1]
        cand = self.labels["candidate_profile_id"].split("/", 1)[1]
        self.assertEqual(ref, cand)

    def test_the_run_label_is_the_profile_it_was_asked_for(self):
        self.assertEqual(self.labels["profile_id"], PRODUCT.profile_id())

    def test_it_follows_the_backends_it_is_given(self):
        # nothing is hard-coded: swap the roles and the labels swap with them
        swapped = backend_parity.profile_labels(PRODUCT, "pdfium", "pymupdf")
        self.assertTrue(swapped["reference_profile_id"].startswith("pdfium/"))
        self.assertTrue(swapped["candidate_profile_id"].startswith("pymupdf/"))

    def test_every_named_profile_can_be_labelled(self):
        for name in backend_parity.PROFILE_NAMES:
            prof = backend_parity.conversion_profile(name)
            got = backend_parity.profile_labels(prof, "pymupdf", "pdfium")
            self.assertTrue(got["candidate_profile_id"].startswith("pdfium/"), name)
            self.assertTrue(got["reference_profile_id"].startswith("pymupdf/"), name)


if __name__ == "__main__":
    unittest.main()
