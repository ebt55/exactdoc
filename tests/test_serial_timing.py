"""testkit/serial_timing.py writes what beta_readiness reads for criterion 2.

    python -m unittest tests.test_serial_timing
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "testkit"))
sys.path.insert(0, ROOT)


class SerialTiming(unittest.TestCase):
    def test_a_run_is_readable_by_beta_readiness(self):
        import beta_readiness
        import serial_timing
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "x.timing.json")
            rc = serial_timing.main(["--profile", "raw", "--docs", "05_memo.pdf",
                                     "--repeat", "2", "--json", out])
            self.assertEqual(rc, 0)
            data = json.load(open(out, encoding="utf-8"))
            self.assertEqual(data["schema"], "exactdoc.serial-timing.v1")
            self.assertEqual((data["jobs"], data["repeat"]), (1, 2))
            row = data["documents"][0]
            self.assertEqual(row["document"], "05_memo.pdf")
            self.assertEqual(row["convert_s"], min(row["all_s"]))
            self.assertTrue(row["outputs_agree"])
            self.assertIn("word/document.xml", row["parts"])
            found = beta_readiness.find_timings([d])
            self.assertEqual(list(found), ["raw"])


if __name__ == "__main__":
    unittest.main()
