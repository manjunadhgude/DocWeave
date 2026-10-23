import io
import os
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from pathlib import Path

# Keep automated API tests isolated from any real PostgreSQL database.
# This environment setting applies only to the test process.
os.environ["DATABASE_URL"] = "sqlite:///./docweave_test.db"

from fastapi.testclient import TestClient

from docweave.api import app
from docweave.storage import Base, IdempotencyRecord, ReconciliationRecord, SessionLocal, engine
from test_pdf_ingest import make_text_pdf


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
    def setUp(self):
        # Test-only schema setup. Production schema changes use Alembic.
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

        # Each test begins with empty history, without dropping the schema.
        with SessionLocal() as db:
            db.query(IdempotencyRecord).delete()
            db.query(ReconciliationRecord).delete()
            db.commit()

    def post_two_way(self, invoice=None, headers=None):
        return self.client.post(
            "/api/v1/reconcile/two-way/json",
            json={
                "purchase_order": make_document("PO-1"),
                "invoice": invoice or make_document("INV-1"),
            },
            headers=headers,
        )

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_two_way_match_is_persisted(self):
        response = self.post_two_way()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["status"], "MATCH")
        self.assertTrue(result["reconciliation_id"])
        self.assertTrue(result["created_at"])

        detail = self.client.get(
            f"/api/v1/reconciliations/{result['reconciliation_id']}"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["report"]["status"], "MATCH")
        self.assertEqual(detail.json()["workflow"], "two_way_json")
        self.assertEqual(
            detail.json()["document_ids"]["purchase_order_id"], "PO-1"
        )

    def test_discrepancy_is_also_saved(self):
        response = self.post_two_way(make_document("INV-1", quantity=1))
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["status"], "DISCREPANCY")

        detail = self.client.get(
            f"/api/v1/reconciliations/{result['reconciliation_id']}"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["status"], "DISCREPANCY")

    def test_list_history_and_filter_by_workflow(self):
        self.post_two_way()
        self.client.post(
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

        all_records = self.client.get("/api/v1/reconciliations")
        self.assertEqual(all_records.status_code, 200)
        self.assertEqual(all_records.json()["total"], 2)

        filtered = self.client.get(
            "/api/v1/reconciliations",
            params={"workflow": "two_way_json", "limit": 10, "offset": 0},
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["total"], 1)
        self.assertEqual(filtered.json()["items"][0]["workflow"], "two_way_json")

    def test_history_status_filter_and_pagination(self):
        self.post_two_way()
        self.post_two_way(make_document("INV-1", quantity=1))

        matches = self.client.get(
            "/api/v1/reconciliations", params={"status": "MATCH"}
        )
        self.assertEqual(matches.status_code, 200)
        self.assertEqual(matches.json()["total"], 1)

        page = self.client.get(
            "/api/v1/reconciliations", params={"limit": 1, "offset": 1}
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.json()["items"]), 1)

    def test_unknown_record_returns_404(self):
        response = self.client.get("/api/v1/reconciliations/not-a-real-id")
        self.assertEqual(response.status_code, 404)

    def test_invalid_pagination_is_rejected(self):
        response = self.client.get(
            "/api/v1/reconciliations", params={"limit": 1000}
        )
        self.assertEqual(response.status_code, 422)

    def test_three_way_json_match_is_saved(self):
        response = self.client.post(
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
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "MATCH")
        self.assertTrue(response.json()["reconciliation_id"])

    def test_missing_request_field_is_rejected(self):
        response = self.client.post(
            "/api/v1/reconcile/two-way/json",
            json={"purchase_order": make_document("PO-1")},
        )
        self.assertEqual(response.status_code, 422)

    def test_unknown_request_field_is_rejected(self):
        response = self.client.post(
            "/api/v1/reconcile/two-way/json",
            json={
                "purchase_order": make_document("PO-1"),
                "invoice": make_document("INV-1"),
                "unexpected": True,
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_three_way_pdf_match_is_saved_with_fingerprints(self):
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
        response = self.client.post(
            "/api/v1/reconcile/three-way/pdf", files=files
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["status"], "MATCH")
        self.assertEqual(result["workflow"], "pdf_three_way")
        self.assertTrue(result["reconciliation_id"])

        detail = self.client.get(
            f"/api/v1/reconciliations/{result['reconciliation_id']}"
        )
        self.assertEqual(detail.status_code, 200)
        metadata = detail.json()["source_metadata"]
        self.assertIn("purchase_order", metadata)
        self.assertTrue(metadata["purchase_order"]["sha256"])

    def test_three_way_pdf_overbilling_is_detected_and_saved(self):
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
        response = self.client.post(
            "/api/v1/reconcile/three-way/pdf", files=files
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "DISCREPANCY")
        self.assertTrue(response.json()["reconciliation_id"])

    def test_invalid_pdf_review_report_is_saved(self):
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
        response = self.client.post(
            "/api/v1/reconcile/three-way/pdf", files=files
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "NEEDS_REVIEW")
        self.assertTrue(response.json()["reconciliation_id"])

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
        response = self.client.post(
            "/api/v1/reconcile/three-way/pdf", files=files
        )
        self.assertEqual(response.status_code, 400)


    def test_idempotency_retry_returns_original_response_without_duplicate(self):
        headers = {"Idempotency-Key": "retry-test-001"}

        first = self.post_two_way(headers=headers)
        second = self.post_two_way(headers=headers)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json(), second.json())

        with SessionLocal() as db:
            self.assertEqual(db.query(ReconciliationRecord).count(), 1)
            self.assertEqual(db.query(IdempotencyRecord).count(), 1)

    def test_reusing_key_for_different_json_returns_conflict(self):
        headers = {"Idempotency-Key": "retry-conflict-001"}

        first = self.post_two_way(headers=headers)
        second = self.post_two_way(
            invoice=make_document("INV-1", quantity=1),
            headers=headers,
        )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 409, second.text)

        with SessionLocal() as db:
            self.assertEqual(db.query(ReconciliationRecord).count(), 1)
            self.assertEqual(db.query(IdempotencyRecord).count(), 1)

    def test_same_key_is_scoped_to_workflow(self):
        headers = {"Idempotency-Key": "workflow-scope-001"}

        two_way = self.post_two_way(headers=headers)
        three_way = self.client.post(
            "/api/v1/reconcile/three-way/json",
            headers=headers,
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

        self.assertEqual(two_way.status_code, 200, two_way.text)
        self.assertEqual(three_way.status_code, 200, three_way.text)

        with SessionLocal() as db:
            self.assertEqual(db.query(ReconciliationRecord).count(), 2)
            self.assertEqual(db.query(IdempotencyRecord).count(), 2)

    def test_invalid_idempotency_key_is_rejected(self):
        response = self.post_two_way(
            headers={"Idempotency-Key": "not a valid key"}
        )
        self.assertEqual(response.status_code, 422)

    def test_idempotent_save_failure_rolls_back_both_records(self):
        headers = {"Idempotency-Key": "save-failure-test-001"}

        with patch.object(
            Session,
            "commit",
            side_effect=SQLAlchemyError("simulated commit failure"),
        ):
            response = self.post_two_way(headers=headers)

        self.assertEqual(response.status_code, 503, response.text)

        # The history row and idempotency row must not be partially saved.
        with SessionLocal() as db:
            self.assertEqual(db.query(ReconciliationRecord).count(), 0)
            self.assertEqual(db.query(IdempotencyRecord).count(), 0)

    def test_idempotency_unique_conflict_returns_winning_response(self):
        headers = {"Idempotency-Key": "simulated-race-test-001"}
        winning_response = {
            "status": "MATCH",
            "reconciliation_id": "winning-record-id",
            "created_at": "2026-01-01T00:00:00",
        }

        # Simulate this request finding no prior key, then losing the
        # database uniqueness race to another request that saved first.
        conflict = IntegrityError(
            "INSERT",
            {},
            Exception("simulated unique-key conflict"),
        )

        with (
            patch(
                "docweave.api._find_replay",
                side_effect=[None, winning_response],
            ),
            patch.object(Session, "commit", side_effect=conflict),
        ):
            response = self.post_two_way(headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), winning_response)

        # Our losing transaction must have rolled back its own history row.
        with SessionLocal() as db:
            self.assertEqual(db.query(ReconciliationRecord).count(), 0)
            self.assertEqual(db.query(IdempotencyRecord).count(), 0)

    def test_pdf_idempotency_retry_returns_original_response(self):
        headers = {"Idempotency-Key": "pdf-retry-test-001"}

        def make_uploads():
            return {
                "purchase_order": (
                    "po.pdf",
                    io.BytesIO(make_pdf_bytes(po_lines())),
                    "application/pdf",
                ),
                "invoice": (
                    "invoice.pdf",
                    io.BytesIO(make_pdf_bytes(invoice_lines())),
                    "application/pdf",
                ),
                "goods_receipt_note": (
                    "grn.pdf",
                    io.BytesIO(make_pdf_bytes(grn_lines())),
                    "application/pdf",
                ),
            }

        first = self.client.post(
            "/api/v1/reconcile/three-way/pdf",
            files=make_uploads(),
            headers=headers,
        )
        second = self.client.post(
            "/api/v1/reconcile/three-way/pdf",
            files=make_uploads(),
            headers=headers,
        )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json(), second.json())

        with SessionLocal() as db:
            self.assertEqual(db.query(ReconciliationRecord).count(), 1)
            self.assertEqual(db.query(IdempotencyRecord).count(), 1)


if __name__ == "__main__":
    unittest.main()
