import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ThreeWayCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "docweave.three_way_cli", *args],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_sample_documents_match(self):
        r = self.run_cli(
            "data/purchase_order.json", "data/invoice.json",
            "data/goods_receipt_note.json",
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        report = json.loads(r.stdout)
        self.assertEqual(report["status"], "MATCH")
        self.assertIn("goods_receipt_note", report["sources"])

    def test_argument_count(self):
        self.assertEqual(self.run_cli("one.json").returncode, 2)

    def test_missing_file(self):
        r = self.run_cli(
            "data/purchase_order.json", "data/invoice.json",
            "data/missing-grn.json",
        )
        self.assertEqual(r.returncode, 2)
        self.assertEqual(json.loads(r.stdout)["error"]["code"], "FILE_READ_ERROR")


if __name__ == "__main__":
    unittest.main()
