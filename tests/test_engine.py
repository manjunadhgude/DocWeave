import unittest
from copy import deepcopy

from docweave.engine import reconcile


def documents():
    po = {
        "document_id": "PO-1",
        "supplier_id": "SUP-1",
        "currency": "INR",
        "lines": [
            {"item_id": "A", "quantity": "2", "unit_price": "100.00"}
        ],
        "total": "200.00",
    }
    return po, {
        **deepcopy(po),
        "document_id": "INV-1",
    }


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.po, self.invoice = documents()

    def test_matching_documents(self):
        self.assertEqual(reconcile(self.po, self.invoice)["status"], "MATCH")

    def test_price_mismatch(self):
        self.invoice["lines"][0]["unit_price"] = "110.00"
        self.invoice["total"] = "220.00"
        result = reconcile(self.po, self.invoice)
        self.assertEqual(result["status"], "DISCREPANCY")
        self.assertIn("UNIT_PRICE_MISMATCH",
                      [x["code"] for x in result["findings"]])

    def test_quantity_mismatch(self):
        self.invoice["lines"][0]["quantity"] = "3"
        self.invoice["total"] = "300.00"
        result = reconcile(self.po, self.invoice)
        self.assertIn("QUANTITY_MISMATCH",
                      [x["code"] for x in result["findings"]])

    def test_missing_item(self):
        self.invoice["lines"] = [
            {"item_id": "B", "quantity": "2", "unit_price": "100.00"}
        ]
        result = reconcile(self.po, self.invoice)
        self.assertIn("ITEM_MISSING_FROM_INVOICE",
                      [x["code"] for x in result["findings"]])

    def test_unexpected_item(self):
        self.invoice["lines"].append(
            {"item_id": "B", "quantity": "1", "unit_price": "10.00"}
        )
        self.invoice["total"] = "210.00"
        result = reconcile(self.po, self.invoice)
        self.assertIn("UNEXPECTED_INVOICE_ITEM",
                      [x["code"] for x in result["findings"]])

    def test_supplier_mismatch(self):
        self.invoice["supplier_id"] = "OTHER"
        self.assertIn("SUPPLIER_MISMATCH",
                      [x["code"] for x in reconcile(
                          self.po, self.invoice)["findings"]])

    def test_currency_mismatch(self):
        self.invoice["currency"] = "USD"
        self.assertIn("CURRENCY_MISMATCH",
                      [x["code"] for x in reconcile(
                          self.po, self.invoice)["findings"]])

    def test_invalid_quantity_needs_review(self):
        self.invoice["lines"][0]["quantity"] = "-1"
        result = reconcile(self.po, self.invoice)
        self.assertEqual(result["status"], "NEEDS_REVIEW")

    def test_incorrect_declared_total_needs_review(self):
        self.invoice["total"] = "999.00"
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_duplicate_item_needs_review(self):
        self.invoice["lines"].append(dict(self.invoice["lines"][0]))
        result = reconcile(self.po, self.invoice)
        self.assertEqual(result["status"], "NEEDS_REVIEW")

    def test_missing_document_field_needs_review(self):
        del self.invoice["supplier_id"]
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_non_object_needs_review(self):
        self.assertEqual(
            reconcile(None, self.invoice)["status"], "NEEDS_REVIEW"
        )


if __name__ == "__main__":
    unittest.main()
