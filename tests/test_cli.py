import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from docweave.cli import main


def document(document_id):
    return {
        "document_id": document_id,
        "supplier_id": "SUP-1",
        "currency": "INR",
        "lines": [
            {"item_id": "A", "quantity": "2", "unit_price": "100.00"}
        ],
        "total": "200.00",
    }


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.po_path = self.root / "po.json"
        self.inv_path = self.root / "invoice.json"
        self.po_path.write_text(
            json.dumps(document("PO-1")), encoding="utf-8"
        )
        self.inv_path.write_text(
            json.dumps(document("INV-1")), encoding="utf-8"
        )

    def run_cli(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(self.po_path), str(self.inv_path)])
        return code, json.loads(output.getvalue())

    def test_matching_cli_report_contains_source_fingerprints(self):
        code, report = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "MATCH")
        self.assertEqual(
            report["sources"]["purchase_order"]["file_name"], "po.json"
        )
        self.assertEqual(
            len(report["sources"]["purchase_order"]["sha256"]), 64
        )

    def test_discrepancy_cli_report_contains_evidence(self):
        invoice = document("INV-1")
        invoice["lines"][0]["unit_price"] = "110.00"
        invoice["total"] = "220.00"
        self.inv_path.write_text(json.dumps(invoice), encoding="utf-8")
        code, report = self.run_cli()
        self.assertEqual(code, 1)
        finding = next(
            f for f in report["findings"]
            if f["code"] == "UNIT_PRICE_MISMATCH"
        )
        self.assertEqual(
            finding["evidence"]["actual"]["json_pointer"],
            "/lines/0/unit_price",
        )

    def test_invalid_json_returns_structured_error(self):
        self.inv_path.write_text('{"total": }', encoding="utf-8")
        code, report = self.run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertEqual(report["error"]["code"], "INVALID_JSON")
        self.assertIn("line", report["error"])


if __name__ == "__main__":
    unittest.main()
