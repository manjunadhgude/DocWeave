import unittest
from docweave.three_way import reconcile_three_way


def documents(billed=5, received=5):
    po = {
        "document_id": "PO-1", "supplier_id": "SUP-1", "currency": "INR",
        "lines": [{"item_id": "A", "quantity": 5, "unit_price": 100}],
        "total": 500,
    }
    invoice = {
        "document_id": "INV-1", "supplier_id": "SUP-1", "currency": "INR",
        "lines": [{"item_id": "A", "quantity": billed, "unit_price": 100}],
        "total": billed * 100,
    }
    grn = {
        "document_id": "GRN-1", "supplier_id": "SUP-1",
        "lines": [{"item_id": "A", "quantity": received}],
    }
    return po, invoice, grn


class ThreeWayTests(unittest.TestCase):
    def codes(self, report):
        return {f["code"] for f in report["findings"]}

    def test_matching_documents(self):
        r = reconcile_three_way(*documents())
        self.assertEqual(r["status"], "MATCH")
        self.assertEqual(r["goods_receipt_note_id"], "GRN-1")

    def test_invoice_exceeds_receipt(self):
        r = reconcile_three_way(*documents(received=3))
        self.assertIn("INVOICE_EXCEEDS_RECEIVED_QUANTITY", self.codes(r))

    def test_receipt_exceeds_order(self):
        r = reconcile_three_way(*documents(received=6))
        self.assertIn("RECEIPT_EXCEEDS_ORDERED_QUANTITY", self.codes(r))

    def test_receipt_supplier_mismatch(self):
        po, inv, grn = documents()
        grn["supplier_id"] = "OTHER"
        self.assertIn(
            "RECEIPT_SUPPLIER_MISMATCH",
            self.codes(reconcile_three_way(po, inv, grn)),
        )

    def test_received_item_not_ordered(self):
        po, inv, grn = documents()
        grn["lines"].append({"item_id": "B", "quantity": 1})
        self.assertIn(
            "RECEIVED_ITEM_NOT_ORDERED",
            self.codes(reconcile_three_way(po, inv, grn)),
        )

    def test_invalid_receipt_needs_review(self):
        po, inv, grn = documents()
        grn["lines"][0]["quantity"] = 0
        self.assertEqual(
            reconcile_three_way(po, inv, grn)["status"], "NEEDS_REVIEW"
        )

    def test_duplicate_receipt_item_needs_review(self):
        po, inv, grn = documents()
        grn["lines"].append({"item_id": "A", "quantity": 1})
        self.assertEqual(
            reconcile_three_way(po, inv, grn)["status"], "NEEDS_REVIEW"
        )

    def test_mismatch_has_source_evidence(self):
        r = reconcile_three_way(*documents(received=3))
        f = next(x for x in r["findings"]
                 if x["code"] == "INVOICE_EXCEEDS_RECEIVED_QUANTITY")
        self.assertEqual(
            f["evidence"]["expected"]["document_role"], "goods_receipt_note"
        )
        self.assertEqual(
            f["evidence"]["actual"]["document_role"], "invoice"
        )
        self.assertEqual(
            f["evidence"]["expected"]["json_pointer"], "/lines/0/quantity"
        )

    def test_existing_po_invoice_mismatch_is_preserved(self):
        po, inv, grn = documents()
        inv["supplier_id"] = "OTHER"
        self.assertIn(
            "SUPPLIER_MISMATCH",
            self.codes(reconcile_three_way(po, inv, grn)),
        )

    def test_invalid_po_needs_review(self):
        po, inv, grn = documents()
        po["total"] = 999
        self.assertEqual(
            reconcile_three_way(po, inv, grn)["status"], "NEEDS_REVIEW"
        )


if __name__ == "__main__":
    unittest.main()
