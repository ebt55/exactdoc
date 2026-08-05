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

        `profile_id` names the settings of the run; its backend token is
        whatever the named profile carries. Recording that as the *candidate's*
        profile is what made eight documents read as MAJOR "under the shipping
        profile" when the run had measured a PDFium swap.

        This used to also assert `candidate_profile_id != profile_id`, which was
        a true statement about the world rather than about this function: the
        product profile's backend was `pymupdf`, so the candidate token always
        differed. The parser flip made the shipping backend `pdfium`, and the
        two are now legitimately EQUAL -- the candidate arm of a product-profile
        parity run is the shipping backend. Asserting inequality would have
        demanded a wrong label.

        What is checked instead is the property that was actually wanted: each
        label carries the backend it was *given*, derived rather than copied.
        `test_a_differing_arm_is_still_distinguished` keeps the copy-from-
        profile_id regression itself detectable.
        """
        self.assertTrue(self.labels["candidate_profile_id"].startswith("pdfium/"),
                        self.labels["candidate_profile_id"])
        self.assertEqual(self.labels["candidate_profile_id"],
                         PRODUCT.replace(backend="pdfium").profile_id())

    def test_a_differing_arm_is_still_distinguished(self):
        """A label must not be `profile_id` copied under another name.

        Exercised through the arm that now differs from the shipping profile.
        Copying `profile_id` into both arm fields would pass every same-backend
        check and fail here, which is the original defect.
        """
        labels = backend_parity.profile_labels(PRODUCT, "pymupdf", "pdfium")
        self.assertNotEqual(labels["reference_profile_id"], labels["profile_id"])
        self.assertTrue(labels["reference_profile_id"].startswith("pymupdf/"),
                        labels["reference_profile_id"])

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
