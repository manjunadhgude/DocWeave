import unittest

from docweave.engine import reconcile
from docweave.three_way import reconcile_three_way


def make_documents():
    po = {
        "document_id": "PO-HARDEN",
        "supplier_id": "SUP-1",
        "currency": "INR",
        "lines": [{"item_id": "A", "quantity": 5, "unit_price": 100}],
        "total": 500,
    }
    invoice = {
        "document_id": "INV-HARDEN",
        "supplier_id": "SUP-1",
        "currency": "INR",
        "lines": [{"item_id": "A", "quantity": 5, "unit_price": 100}],
        "total": 500,
    }
    grn = {
        "document_id": "GRN-HARDEN",
        "supplier_id": "SUP-1",
        "lines": [{"item_id": "A", "quantity": 5}],
    }
    return po, invoice, grn


class PolicyHardeningTests(unittest.TestCase):
    def codes(self, report):
        return {item["code"] for item in report.get("findings", [])}

    def test_partial_receipt_is_not_mistaken_for_overbilling(self):
        po, invoice, grn = make_documents()
        invoice["lines"][0]["quantity"] = 3
        invoice["total"] = 300
        grn["lines"][0]["quantity"] = 3

        report = reconcile_three_way(po, invoice, grn)

        # The current policy still flags invoice-vs-PO differences.
        # It must not falsely claim the invoice exceeds recorded receipt.
        self.assertNotIn(
            "INVOICE_EXCEEDS_RECEIVED_QUANTITY", self.codes(report)
        )
        self.assertIn("QUANTITY_MISMATCH", self.codes(report))
        self.assertEqual(report["status"], "DISCREPANCY")

    def test_missing_receipt_item_has_explicit_absence_evidence(self):
        po, invoice, grn = make_documents()
        grn["lines"] = [{"item_id": "B", "quantity": 1}]

        report = reconcile_three_way(po, invoice, grn)
        finding = next(
            f for f in report["findings"]
            if f["code"] == "INVOICE_EXCEEDS_RECEIVED_QUANTITY"
        )

        self.assertEqual(
            finding["evidence"]["expected"]["document_role"],
            "goods_receipt_note",
        )
        self.assertEqual(
            finding["evidence"]["expected"]["json_pointer"], "/lines"
        )
        self.assertIsNone(finding["evidence"]["expected"]["value"])

    def test_invalid_boolean_quantity_needs_review(self):
        po, invoice, grn = make_documents()
        grn["lines"][0]["quantity"] = True

        report = reconcile_three_way(po, invoice, grn)
        self.assertEqual(report["status"], "NEEDS_REVIEW")

    def test_invalid_decimal_quantity_needs_review(self):
        po, invoice, grn = make_documents()
        grn["lines"][0]["quantity"] = "not-a-number"

        report = reconcile_three_way(po, invoice, grn)
        self.assertEqual(report["status"], "NEEDS_REVIEW")

    def test_missing_receipt_lines_needs_review(self):
        po, invoice, grn = make_documents()
        grn["lines"] = []

        report = reconcile_three_way(po, invoice, grn)
        self.assertEqual(report["status"], "NEEDS_REVIEW")

    def test_non_object_purchase_order_needs_review(self):
        report = reconcile_three_way(None, {}, {})
        self.assertEqual(report["status"], "NEEDS_REVIEW")

    def test_currency_mismatch_does_not_compare_money_directly(self):
        po, invoice, _ = make_documents()
        invoice["currency"] = "USD"

        report = reconcile(po, invoice)
        codes = self.codes(report)

        self.assertIn("CURRENCY_MISMATCH", codes)
        self.assertNotIn("UNIT_PRICE_MISMATCH", codes)
        self.assertNotIn("TOTAL_MISMATCH", codes)

    def test_missing_invoice_item_is_explicit(self):
        po, invoice, grn = make_documents()
        invoice["lines"] = [{"item_id": "B", "quantity": 5, "unit_price": 100}]
        invoice["total"] = 500

        report = reconcile_three_way(po, invoice, grn)
        codes = self.codes(report)

        self.assertIn("ITEM_MISSING_FROM_INVOICE", codes)
        self.assertIn("UNEXPECTED_INVOICE_ITEM", codes)
        self.assertEqual(report["status"], "DISCREPANCY")

    def test_receipt_supplier_mismatch_retains_evidence(self):
        po, invoice, grn = make_documents()
        grn["supplier_id"] = "SUP-OTHER"

        report = reconcile_three_way(po, invoice, grn)
        finding = next(
            f for f in report["findings"]
            if f["code"] == "RECEIPT_SUPPLIER_MISMATCH"
        )

        self.assertEqual(
            finding["evidence"]["expected"]["json_pointer"], "/supplier_id"
        )
        self.assertEqual(
            finding["evidence"]["actual"]["document_role"],
            "goods_receipt_note",
        )

    def test_overdelivery_and_overbilling_are_separate_findings(self):
        po, invoice, grn = make_documents()
        invoice["lines"][0]["quantity"] = 7
        invoice["total"] = 700
        grn["lines"][0]["quantity"] = 6

        report = reconcile_three_way(po, invoice, grn)
        codes = self.codes(report)

        self.assertIn("INVOICE_EXCEEDS_RECEIVED_QUANTITY", codes)
        self.assertIn("RECEIPT_EXCEEDS_ORDERED_QUANTITY", codes)


if __name__ == "__main__":
    unittest.main()
