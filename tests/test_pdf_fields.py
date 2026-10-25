import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from test_pdf_ingest import make_text_pdf
from docweave.pdf_fields import extract_pdf_fields
from docweave.pdf_fields_cli import main


class PDFFieldExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_pdf(self, name, pages):
        path = self.root / name
        make_text_pdf(path, pages)
        return path

    def test_extracts_invoice_fields_and_page_evidence(self):
        path = self.write_pdf("invoice.pdf", [
            "Invoice No: INV-2001",
            "Supplier ID: SUP-001",
            "Currency: INR",
            "Grand Total: 230.00",
            "Item ID | Description | Quantity | Unit Price | Line Total",
            "ITEM-A | Steel bolts | 2 | 100.00 | 200.00",
            "ITEM-B | Nuts | 1 | 30.00 | 30.00",
        ])
        report = extract_pdf_fields(path, "invoice")

        self.assertEqual(report["status"], "EXTRACTED")
        self.assertEqual(report["document"]["document_id"], "INV-2001")
        self.assertEqual(report["document"]["supplier_id"], "SUP-001")
        self.assertEqual(report["document"]["currency"], "INR")
        self.assertEqual(report["document"]["total"], "230.00")
        self.assertEqual(len(report["document"]["lines"]), 2)
        self.assertEqual(
            report["fields"]["document_id"]["evidence"]["page_number"], 1
        )
        self.assertIn(
            "Invoice No: INV-2001",
            report["fields"]["document_id"]["evidence"]["snippet"],
        )
        self.assertIn("ITEM-A", report["line_items"][0]["evidence"]["snippet"])

    def test_extracts_purchase_order_aliases(self):
        path = self.write_pdf("po.pdf", [
            "PO Number: PO-9",
            "Vendor Code: V-2",
            "Currency: USD",
            "Total Amount: 45.00",
            "Item Code | Description | Qty | Unit Cost",
            "X-1 | Cable | 3 | 15.00",
        ])
        report = extract_pdf_fields(path, "purchase_order")
        self.assertEqual(report["status"], "EXTRACTED")
        self.assertEqual(report["document"]["document_id"], "PO-9")
        self.assertEqual(report["document"]["supplier_id"], "V-2")

    def test_extracts_grn_without_currency_or_unit_price(self):
        path = self.write_pdf("grn.pdf", [
            "GRN No: GRN-8",
            "Supplier ID: SUP-8",
            "Item ID | Description | Received Quantity",
            "ITEM-A | Bolts | 4",
        ])
        report = extract_pdf_fields(path, "goods_receipt_note")
        self.assertEqual(report["status"], "EXTRACTED")
        self.assertEqual(report["document"]["document_id"], "GRN-8")
        self.assertEqual(report["document"]["lines"], [
            {"item_id": "ITEM-A", "quantity": "4"}
        ])
        self.assertNotIn("currency", report["document"])

    def test_missing_field_requires_review_and_withholds_document(self):
        path = self.write_pdf("missing.pdf", [
            "Invoice No: INV-1",
            "Currency: INR",
            "Grand Total: 10.00",
            "Item ID | Description | Quantity | Unit Price",
            "A | Item | 1 | 10.00",
        ])
        report = extract_pdf_fields(path, "invoice")
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertIsNone(report["document"])
        self.assertIn("MISSING_FIELD:supplier_id", report["review_reasons"])

    def test_conflicting_document_ids_are_ambiguous(self):
        path = self.write_pdf("conflict.pdf", [
            "Invoice No: INV-1",
            "Document ID: INV-2",
            "Supplier ID: SUP-1",
            "Currency: INR",
            "Total: 10.00",
            "Item ID | Description | Quantity | Unit Price",
            "A | Item | 1 | 10.00",
        ])
        report = extract_pdf_fields(path, "invoice")
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertIsNone(report["fields"]["document_id"]["value"])
        self.assertIn("AMBIGUOUS_FIELD:document_id", report["review_reasons"])
        self.assertEqual(
            len(report["fields"]["document_id"]["candidates"]), 2
        )

    def test_unrecognized_table_is_not_guessed(self):
        path = self.write_pdf("unknown.pdf", [
            "Invoice No: INV-1",
            "Supplier ID: SUP-1",
            "Currency: INR",
            "Total: 10.00",
            "A 1 10.00",
        ])
        report = extract_pdf_fields(path, "invoice")
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertIn(
            "MISSING_OR_UNRECOGNIZED_LINE_ITEM_TABLE",
            report["review_reasons"],
        )

    def test_malformed_table_rows_require_review_instead_of_being_skipped(self):
        common = [
            "Invoice No: INV-1",
            "Supplier ID: SUP-1",
            "Currency: INR",
            "Total: 20.00",
            "Item ID | Description | Quantity | Unit Price",
            "A | Valid item | 1 | 10.00",
        ]
        malformed_rows = [
            ("short-row", "B | Truncated item | 1"),
            ("missing-item-id", " | Item without identifier | 1 | 10.00"),
        ]

        for name, malformed_row in malformed_rows:
            with self.subTest(name=name):
                path = self.write_pdf(
                    f"{name}.pdf",
                    common + [malformed_row, "C | Another valid item | 1 | 10.00"],
                )
                report = extract_pdf_fields(path, "invoice")
                self.assertEqual(report["status"], "NEEDS_REVIEW")
                self.assertIsNone(report["document"])
                self.assertIn(
                    "MALFORMED_LINE_ITEM_ROW",
                    report["review_reasons"],
                )

    def test_invalid_quantity_requires_review(self):
        path = self.write_pdf("bad-qty.pdf", [
            "Invoice No: INV-1",
            "Supplier ID: SUP-1",
            "Currency: INR",
            "Total: 10.00",
            "Item ID | Description | Quantity | Unit Price",
            "A | Item | many | 10.00",
        ])
        report = extract_pdf_fields(path, "invoice")
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertIn("INVALID_QUANTITY:A", report["review_reasons"])

    def test_cli_emits_json_and_nonzero_review_exit(self):
        path = self.write_pdf("cli.pdf", [
            "Invoice No: INV-1",
            "Supplier ID: SUP-1",
            "Currency: INR",
            "Total: 10.00",
            "Item ID | Description | Quantity | Unit Price",
            "A | Item | 1 | 10.00",
        ])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(path), "--role", "invoice"])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "EXTRACTED")

    def test_unsupported_role_is_rejected(self):
        path = self.write_pdf("role.pdf", ["Example text"])
        with self.assertRaises(ValueError):
            extract_pdf_fields(path, "contract")


if __name__ == "__main__":
    unittest.main()
