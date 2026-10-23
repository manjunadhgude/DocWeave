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
    invoice = deepcopy(po)
    invoice["document_id"] = "INV-1"
    return po, invoice


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.po, self.invoice = documents()

    def codes(self, result):
        return {item["code"] for item in result["findings"]}

    def test_matching_documents(self):
        self.assertEqual(reconcile(self.po, self.invoice)["status"], "MATCH")

    def test_price_mismatch(self):
        self.invoice["lines"][0]["unit_price"] = "110.00"
        self.invoice["total"] = "220.00"
        result = reconcile(self.po, self.invoice)
        self.assertEqual(result["status"], "DISCREPANCY")
        self.assertIn("UNIT_PRICE_MISMATCH", self.codes(result))
        self.assertIn("TOTAL_MISMATCH", self.codes(result))

    def test_quantity_mismatch(self):
        self.invoice["lines"][0]["quantity"] = "3"
        self.invoice["total"] = "300.00"
        self.assertIn(
            "QUANTITY_MISMATCH",
            self.codes(reconcile(self.po, self.invoice))
        )

    def test_missing_item(self):
        self.invoice["lines"] = [
            {"item_id": "B", "quantity": "2", "unit_price": "100.00"}
        ]
        self.invoice["total"] = "200.00"
        self.assertIn(
            "ITEM_MISSING_FROM_INVOICE",
            self.codes(reconcile(self.po, self.invoice))
        )

    def test_unexpected_item(self):
        self.invoice["lines"].append(
            {"item_id": "B", "quantity": "1", "unit_price": "10.00"}
        )
        self.invoice["total"] = "210.00"
        self.assertIn(
            "UNEXPECTED_INVOICE_ITEM",
            self.codes(reconcile(self.po, self.invoice))
        )

    def test_supplier_mismatch(self):
        self.invoice["supplier_id"] = "OTHER"
        self.assertIn(
            "SUPPLIER_MISMATCH",
            self.codes(reconcile(self.po, self.invoice))
        )

    def test_currency_mismatch_skips_price_and_total_comparisons(self):
        self.invoice["currency"] = "USD"
        self.invoice["lines"][0]["unit_price"] = "150.00"
        self.invoice["total"] = "300.00"
        result = reconcile(self.po, self.invoice)
        self.assertEqual(result["status"], "DISCREPANCY")
        self.assertEqual(self.codes(result), {"CURRENCY_MISMATCH"})
        self.assertIsNone(result["summary"]["currency"])

    def test_quantity_still_compared_when_currency_differs(self):
        self.invoice["currency"] = "USD"
        self.invoice["lines"][0]["quantity"] = "3"
        self.invoice["lines"][0]["unit_price"] = "100.00"
        self.invoice["total"] = "300.00"
        self.assertIn(
            "QUANTITY_MISMATCH",
            self.codes(reconcile(self.po, self.invoice))
        )

    def test_negative_quantity_needs_review(self):
        self.invoice["lines"][0]["quantity"] = "-1"
        self.invoice["total"] = "-100.00"
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_zero_quantity_needs_review(self):
        self.invoice["lines"][0]["quantity"] = "0"
        self.invoice["total"] = "0"
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_negative_price_needs_review(self):
        self.invoice["lines"][0]["unit_price"] = "-1"
        self.invoice["total"] = "-2"
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_incorrect_declared_total_needs_review(self):
        self.invoice["total"] = "999.00"
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_duplicate_item_needs_review(self):
        self.invoice["lines"].append(dict(self.invoice["lines"][0]))
        self.invoice["total"] = "400.00"
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_missing_document_field_needs_review(self):
        del self.invoice["supplier_id"]
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_non_object_needs_review(self):
        self.assertEqual(
            reconcile(None, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_empty_lines_need_review(self):
        self.invoice["lines"] = []
        self.invoice["total"] = "0"
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_nan_needs_review(self):
        self.invoice["lines"][0]["quantity"] = "NaN"
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_infinity_needs_review(self):
        self.invoice["lines"][0]["unit_price"] = "Infinity"
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_boolean_quantity_needs_review(self):
        self.invoice["lines"][0]["quantity"] = True
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "NEEDS_REVIEW"
        )

    def test_decimal_arithmetic(self):
        self.po["lines"] = [
            {"item_id": "A", "quantity": "3", "unit_price": "0.10"}
        ]
        self.po["total"] = "0.30"
        self.invoice = deepcopy(self.po)
        self.invoice["document_id"] = "INV-1"
        self.assertEqual(
            reconcile(self.po, self.invoice)["status"], "MATCH"
        )


if __name__ == "__main__":
    unittest.main()
