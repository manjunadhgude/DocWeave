import unittest
from copy import deepcopy

from docweave.engine import reconcile


def pair():
    po = {
        "document_id": "PO-1",
        "supplier_id": "SUP-1",
        "currency": "INR",
        "lines": [
            {"item_id": "A", "quantity": "2", "unit_price": "100.00"}
        ],
        "total": "200.00",
    }
    invoice = deepcopy(po)
    invoice["document_id"] = "INV-1"
    return po, invoice


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.po, self.invoice = pair()

    def finding(self, code, report=None):
        report = report or reconcile(self.po, self.invoice)
        return next(f for f in report["findings"] if f["code"] == code)

    def test_match_has_no_findings(self):
        report = reconcile(self.po, self.invoice)
        self.assertEqual(report["status"], "MATCH")
        self.assertEqual(report["findings"], [])

    def test_price_mismatch_has_both_source_paths(self):
        self.invoice["lines"][0]["unit_price"] = "110.00"
        self.invoice["total"] = "220.00"
        item = self.finding("UNIT_PRICE_MISMATCH")
        self.assertEqual(
            item["evidence"]["expected"]["json_pointer"],
            "/lines/0/unit_price",
        )
        self.assertEqual(
            item["evidence"]["actual"]["json_pointer"],
            "/lines/0/unit_price",
        )
        self.assertEqual(item["evidence"]["expected"]["value"], "100.00")
        self.assertEqual(item["evidence"]["actual"]["value"], "110.00")

    def test_quantity_mismatch_has_source_paths(self):
        self.invoice["lines"][0]["quantity"] = "3"
        self.invoice["total"] = "300.00"
        item = self.finding("QUANTITY_MISMATCH")
        self.assertEqual(
            item["evidence"]["expected"]["json_pointer"], "/lines/0/quantity"
        )
        self.assertEqual(
            item["evidence"]["actual"]["json_pointer"], "/lines/0/quantity"
        )

    def test_supplier_mismatch_has_source_paths(self):
        self.invoice["supplier_id"] = "SUP-2"
        item = self.finding("SUPPLIER_MISMATCH")
        self.assertEqual(
            item["evidence"]["expected"]["json_pointer"], "/supplier_id"
        )
        self.assertEqual(
            item["evidence"]["actual"]["json_pointer"], "/supplier_id"
        )

    def test_currency_mismatch_has_source_paths(self):
        self.invoice["currency"] = "USD"
        self.invoice["lines"][0]["unit_price"] = "150.00"
        self.invoice["total"] = "300.00"
        item = self.finding("CURRENCY_MISMATCH")
        self.assertEqual(
            item["evidence"]["expected"]["json_pointer"], "/currency"
        )
        self.assertEqual(
            item["evidence"]["actual"]["json_pointer"], "/currency"
        )

    def test_missing_item_identifies_expected_source(self):
        self.invoice["lines"] = [
            {"item_id": "B", "quantity": "2", "unit_price": "100.00"}
        ]
        item = self.finding("ITEM_MISSING_FROM_INVOICE")
        self.assertEqual(
            item["evidence"]["expected"]["json_pointer"], "/lines/0/item_id"
        )
        self.assertIsNone(item["evidence"]["actual"])

    def test_unexpected_item_identifies_actual_source(self):
        self.invoice["lines"].append(
            {"item_id": "B", "quantity": "1", "unit_price": "10.00"}
        )
        self.invoice["total"] = "210.00"
        item = self.finding("UNEXPECTED_INVOICE_ITEM")
        self.assertIsNone(item["evidence"]["expected"])
        self.assertEqual(
            item["evidence"]["actual"]["json_pointer"], "/lines/1/item_id"
        )

    def test_total_mismatch_has_source_paths(self):
        self.invoice["lines"][0]["unit_price"] = "110.00"
        self.invoice["total"] = "220.00"
        item = self.finding("TOTAL_MISMATCH")
        self.assertEqual(item["evidence"]["expected"]["json_pointer"], "/total")
        self.assertEqual(item["evidence"]["actual"]["json_pointer"], "/total")


if __name__ == "__main__":
    unittest.main()
