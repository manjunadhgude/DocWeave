import io
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from docweave.api import app
from test_pdf_ingest import make_text_pdf


client = TestClient(app)


def make_document(document_id, quantity=2, unit_price=10):
    return {
        "document_id": document_id,
        "supplier_id": "SUP-1",
        "currency": "INR",
        "lines": [
            {
                "item_id": "A",
                "quantity": quantity,
                "unit_price": unit_price,
            }
        ],
        "total": quantity * unit_price,
    }


def make_pdf_bytes(lines):
    """Build a small digital PDF using the project's existing test helper."""
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "fixture.pdf"
        make_text_pdf(path, lines)
        return path.read_bytes()


def po_lines():
    return [
        "PO Number: PO-1",
        "Supplier ID: SUP-1",
        "Currency: INR",
        "Total Amount: 20",
        "Item ID | Description | Quantity | Unit Price",
        "A | Widget | 2 | 10",
    ]


def invoice_lines(quantity=2, total=20):
    return [
        "Invoice No: INV-1",
        "Supplier ID: SUP-1",
        "Currency: INR",
        f"Grand Total: {total}",
        "Item ID | Description | Quantity | Unit Price",
        f"A | Widget | {quantity} | 10",
    ]


def grn_lines(quantity=2):
    return [
        "GRN No: GRN-1",
        "Supplier ID: SUP-1",
        "Item ID | Description | Received Quantity",
        f"A | Widget | {quantity}",
    ]


class DocWeaveAPITests(unittest.TestCase):
    def test_health(self):
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_two_way_json_match(self):
        response = client.post(
            "/api/v1/reconcile/two-way/json",
            json={
                "purchase_order": make_document("PO-1"),
                "invoice": make_document("INV-1"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "MATCH")

    def test_two_way_json_discrepancy(self):
        invoice = make_document("INV-1", quantity=1)
        response = client.post(
            "/api/v1/reconcile/two-way/json",
            json={
                "purchase_order": make_document("PO-1"),
                "invoice": invoice,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "DISCREPANCY")

    def test_three_way_json_match(self):
        response = client.post(
            "/api/v1/reconcile/three-way/json",
            json={
                "purchase_order": make_document("PO-1"),
                "invoice": make_document("INV-1"),
                "goods_receipt_note": {
                    "document_id": "GRN-1",
                    "supplier_id": "SUP-1",
                    "lines": [{"item_id": "A", "quantity": 2}],
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "MATCH")

    def test_missing_required_request_field_is_rejected(self):
        response = client.post(
            "/api/v1/reconcile/two-way/json",
            json={"purchase_order": make_document("PO-1")},
        )
        self.assertEqual(response.status_code, 422)

    def test_unknown_request_field_is_rejected(self):
        response = client.post(
            "/api/v1/reconcile/two-way/json",
            json={
                "purchase_order": make_document("PO-1"),
                "invoice": make_document("INV-1"),
                "unexpected": True,
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_three_way_pdf_match(self):
        files = {
            "purchase_order": (
                "po.pdf", io.BytesIO(make_pdf_bytes(po_lines())), "application/pdf"
            ),
            "invoice": (
                "invoice.pdf", io.BytesIO(make_pdf_bytes(invoice_lines())),
                "application/pdf"
            ),
            "goods_receipt_note": (
                "grn.pdf", io.BytesIO(make_pdf_bytes(grn_lines())),
                "application/pdf"
            ),
        }
        response = client.post(
            "/api/v1/reconcile/three-way/pdf", files=files
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "MATCH")
        self.assertEqual(response.json()["workflow"], "pdf_three_way")

    def test_three_way_pdf_overbilling_is_detected(self):
        files = {
            "purchase_order": (
                "po.pdf", io.BytesIO(make_pdf_bytes(po_lines())), "application/pdf"
            ),
            "invoice": (
                "invoice.pdf",
                io.BytesIO(make_pdf_bytes(invoice_lines(quantity=3, total=30))),
                "application/pdf"
            ),
            "goods_receipt_note": (
                "grn.pdf", io.BytesIO(make_pdf_bytes(grn_lines(quantity=2))),
                "application/pdf"
            ),
        }
        response = client.post(
            "/api/v1/reconcile/three-way/pdf", files=files
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "DISCREPANCY")

    def test_invalid_pdf_returns_review_report(self):
        files = {
            "purchase_order": (
                "po.pdf", io.BytesIO(b"not a PDF"), "application/pdf"
            ),
            "invoice": (
                "invoice.pdf", io.BytesIO(make_pdf_bytes(invoice_lines())),
                "application/pdf"
            ),
            "goods_receipt_note": (
                "grn.pdf", io.BytesIO(make_pdf_bytes(grn_lines())),
                "application/pdf"
            ),
        }
        response = client.post(
            "/api/v1/reconcile/three-way/pdf", files=files
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "NEEDS_REVIEW")

    def test_non_pdf_filename_is_rejected(self):
        files = {
            "purchase_order": (
                "po.txt", io.BytesIO(b"anything"), "text/plain"
            ),
            "invoice": (
                "invoice.pdf", io.BytesIO(make_pdf_bytes(invoice_lines())),
                "application/pdf"
            ),
            "goods_receipt_note": (
                "grn.pdf", io.BytesIO(make_pdf_bytes(grn_lines())),
                "application/pdf"
            ),
        }
        response = client.post(
            "/api/v1/reconcile/three-way/pdf", files=files
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
