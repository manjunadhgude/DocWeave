import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from test_pdf_ingest import make_text_pdf
from docweave.pdf_three_way import reconcile_pdf_documents
from docweave.pdf_three_way_cli import main


def invoice_pages(document_id="INV-1", supplier="SUP-1", quantity="2", total="20.00"):
    return [
        f"Invoice No: {document_id}",
        f"Supplier ID: {supplier}",
        "Currency: INR",
        f"Grand Total: {total}",
        "Item ID | Description | Quantity | Unit Price",
        f"A | Example item | {quantity} | 10.00",
    ]


def po_pages():
    return [
        "PO Number: PO-1",
        "Supplier ID: SUP-1",
        "Currency: INR",
        "Total Amount: 20.00",
        "Item ID | Description | Quantity | Unit Price",
        "A | Example item | 2 | 10.00",
    ]


def grn_pages(quantity="2"):
    return [
        "GRN No: GRN-1",
        "Supplier ID: SUP-1",
        "Item ID | Description | Received Quantity",
        f"A | Example item | {quantity}",
    ]


class PDFThreeWayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.po = self.write_pdf("po.pdf", po_pages())
        self.invoice = self.write_pdf("invoice.pdf", invoice_pages())
        self.grn = self.write_pdf("grn.pdf", grn_pages())

    def write_pdf(self, name, pages):
        path = self.root / name
        make_text_pdf(path, pages)
        return path

    def run_workflow(self, po=None, invoice=None, grn=None):
        return reconcile_pdf_documents(
            po or self.po,
            invoice or self.invoice,
            grn or self.grn,
        )

    def test_matching_three_pdfs_reconcile(self):
        report = self.run_workflow()
        self.assertEqual(report["status"], "MATCH")
        self.assertEqual(report["workflow"], "pdf_three_way")
        self.assertEqual(report["purchase_order_id"], "PO-1")
        self.assertEqual(report["invoice_id"], "INV-1")
        self.assertEqual(report["goods_receipt_note_id"], "GRN-1")
        self.assertEqual(len(report["documents"]), 3)

    def test_pdf_page_evidence_is_attached_to_finding(self):
        invoice = self.write_pdf(
            "overbilled.pdf", invoice_pages(quantity="3", total="30.00")
        )
        report = self.run_workflow(invoice=invoice)
        self.assertEqual(report["status"], "DISCREPANCY")

        finding = next(
            f for f in report["findings"]
            if f["code"] == "INVOICE_EXCEEDS_RECEIVED_QUANTITY"
        )
        actual = finding["evidence"]["actual"]
        self.assertEqual(actual["document_role"], "invoice")
        self.assertEqual(actual["pdf_evidence"]["page_number"], 6)
        self.assertIn("A | Example item | 3 | 10.00", actual["pdf_evidence"]["snippet"])

    def test_incomplete_pdf_stops_before_reconciliation(self):
        bad_invoice = self.write_pdf(
            "incomplete.pdf",
            [
                "Invoice No: INV-2",
                "Currency: INR",
                "Grand Total: 20.00",
                "Item ID | Description | Quantity | Unit Price",
                "A | Example item | 2 | 10.00",
            ],
        )
        report = self.run_workflow(invoice=bad_invoice)
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertIn("invoice", report["review_reasons"])
        self.assertEqual(report["findings"], [])
        self.assertIsNone(report.get("purchase_order_id"))

    def test_invalid_pdf_stops_before_reconciliation(self):
        bad_pdf = self.root / "bad.pdf"
        bad_pdf.write_bytes(b"not a PDF")
        report = self.run_workflow(grn=bad_pdf)
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertIn("goods_receipt_note", report["extraction_errors"])
        self.assertEqual(report["findings"], [])

    def test_supplier_mismatch_is_detected(self):
        invoice = self.write_pdf(
            "wrong-supplier.pdf", invoice_pages(supplier="SUP-OTHER")
        )
        report = self.run_workflow(invoice=invoice)
        self.assertEqual(report["status"], "DISCREPANCY")
        self.assertIn("SUPPLIER_MISMATCH", [f["code"] for f in report["findings"]])

    def test_cli_emits_json_and_match_exit_code(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(self.po), str(self.invoice), str(self.grn)])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "MATCH")
        self.assertEqual(report["workflow"], "pdf_three_way")

    def test_cli_returns_review_exit_code_for_bad_pdf(self):
        bad_pdf = self.root / "bad-cli.pdf"
        bad_pdf.write_bytes(b"not a PDF")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(self.po), str(self.invoice), str(bad_pdf)])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "NEEDS_REVIEW")


    def test_cli_passes_ocr_flag_to_workflow(self):
        from unittest.mock import patch

        report = {"status": "NEEDS_REVIEW", "workflow": "pdf_three_way"}
        output = io.StringIO()
        with (
            patch(
                "docweave.pdf_three_way_cli.reconcile_pdf_documents",
                return_value=report,
            ) as workflow,
            contextlib.redirect_stdout(output),
        ):
            code = main([
                str(self.po), str(self.invoice), str(self.grn), "--ocr"
            ])

        self.assertEqual(code, 2)
        self.assertTrue(workflow.call_args.kwargs["enable_ocr"])


if __name__ == "__main__":
    unittest.main()
