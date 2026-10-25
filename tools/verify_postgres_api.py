"""Exercise the real PostgreSQL-backed DocWeave API without dropping data.

Usage:
  python tools/verify_postgres_api.py

DATABASE_URL must point to a dedicated verification database, or be present
in DOCWEAVE_DATABASE_ENV_FILE (defaults to /tmp/docweave-pg-new.env).
The runner applies forward migrations, verifies schema, creates uniquely named
test records through HTTP, checks retrieval/idempotency, then deletes only
records created by this run. It never drops tables or truncates history.
"""
from __future__ import annotations

import os
import secrets
import shlex
import subprocess
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Running ``python tools/verify_postgres_api.py`` puts tools/, not the repo root,
# at sys.path[0]. Add the root so the local ``docweave`` package is importable.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if value:
        return value

    env_file = Path(
        os.environ.get(
            "DOCWEAVE_DATABASE_ENV_FILE",
            "/tmp/docweave-pg-new.env",
        )
    )
    if not env_file.is_file():
        raise RuntimeError(
            "DATABASE_URL is not set and the private database settings file "
            f"was not found at {env_file}. Set DATABASE_URL or "
            "DOCWEAVE_DATABASE_ENV_FILE."
        )

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):]
        key, separator, raw_value = stripped.partition("=")
        if separator and key.strip() == "DATABASE_URL":
            parsed = shlex.split(raw_value.strip(), posix=True)
            if parsed:
                return parsed[0]
    raise RuntimeError(f"No DATABASE_URL assignment found in {env_file}.")


def run_command(args: list[str], env: dict[str, str], label: str) -> None:
    print(f"\n=== {label} ===", flush=True)
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.returncode:
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}.")



def make_text_pdf(texts: list[str]) -> bytes:
    """Create a tiny standards-compliant PDF fixture with selectable text."""
    objects = []

    def add_object(value):
        objects.append(value.encode("latin-1"))
        return len(objects)

    catalog_id = add_object("<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add_object("")

    page_ids = []
    content_ids = []

    for _ in texts:
        page_ids.append(add_object(""))
        content_ids.append(add_object(""))

    font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(texts)} >>".encode()
    )

    for index, value in enumerate(texts):
        safe = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1")
        content_id = content_ids[index]
        objects[content_id - 1] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream + b"\nendstream"
        )
        page_id = page_ids[index]
        objects[page_id - 1] = (
            f"<< /Type /Page /Parent {pages_id} 0 R "
            f"/MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode()

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())

    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(output)


def main() -> int:
    try:
        database_url = load_database_url()
        normalized = database_url.lower()
        if not (
            normalized.startswith("postgresql://")
            or normalized.startswith("postgresql+psycopg://")
            or normalized.startswith("postgres://")
        ):
            raise RuntimeError(
                "Refusing to run: DATABASE_URL must point to PostgreSQL, "
                "not SQLite or another database."
            )

        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env.setdefault("DOCWEAVE_API_TOKEN", secrets.token_urlsafe(32))
        env.setdefault("DOCWEAVE_RATE_LIMIT_REQUESTS", "10000")
        env.setdefault("DOCWEAVE_RATE_LIMIT_WINDOW_SECONDS", "60")

        # The migration/schema subprocesses receive `env`, but the API runs
        # in this process. Set the same values before importing storage/api,
        # because SQLAlchemy creates its engine at module import time.
        for key in (
            "DATABASE_URL",
            "DOCWEAVE_API_TOKEN",
            "DOCWEAVE_RATE_LIMIT_REQUESTS",
            "DOCWEAVE_RATE_LIMIT_WINDOW_SECONDS",
        ):
            os.environ[key] = env[key]

        run_command(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env,
            "Apply forward migrations",
        )
        run_command(
            [sys.executable, "tools/verify_database_schema.py"],
            env,
            "Verify PostgreSQL schema",
        )

        # Import only after DATABASE_URL and API configuration are set.
        from fastapi.testclient import TestClient
        from sqlalchemy import delete, select
        from docweave.api import app
        from docweave.storage import (
            IdempotencyRecord,
            ReconciliationRecord,
            SessionLocal,
        )

        marker = uuid.uuid4().hex[:12]
        key = f"pgverify-{marker}-same"
        conflict_key = f"pgverify-{marker}-conflict"
        pdf_key = f"pgverify-{marker}-pdf"
        owned_keys = [key, conflict_key, pdf_key]
        owned_record_ids: set[str] = set()
        token = env["DOCWEAVE_API_TOKEN"]

        def document(document_id: str, quantity: int = 2) -> dict:
            return {
                "document_id": document_id,
                "supplier_id": f"SUP-{marker}",
                "currency": "INR",
                "lines": [
                    {"item_id": "ITEM-A", "quantity": quantity, "unit_price": 10}
                ],
                "total": quantity * 10,
            }

        payload = {
            "purchase_order": document(f"PO-{marker}"),
            "invoice": document(f"INV-{marker}"),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": key,
        }

        run_failed = False
        try:
            print("\n=== PostgreSQL-backed API integration ===", flush=True)
            with TestClient(app) as client:
                first = client.post(
                    "/api/v1/reconcile/two-way/json",
                    json=payload,
                    headers=headers,
                )
                if first.status_code != 200:
                    raise RuntimeError(
                        f"Initial API submission failed ({first.status_code}): "
                        f"{first.text}"
                    )
                first_json = first.json()
                if first_json.get("status") != "MATCH":
                    raise RuntimeError(
                        f"Expected MATCH from test documents, got "
                        f"{first_json.get('status')!r}."
                    )
                record_id = first_json.get("reconciliation_id")
                if not record_id:
                    raise RuntimeError("API response omitted reconciliation_id.")
                owned_record_ids.add(record_id)
                print("PASS: API created and committed a MATCH record.")

                replay = client.post(
                    "/api/v1/reconcile/two-way/json",
                    json=payload,
                    headers=headers,
                )
                if replay.status_code != 200 or replay.json() != first_json:
                    raise RuntimeError(
                        "Idempotent retry did not return the exact original "
                        f"response: status={replay.status_code}, body={replay.text}"
                    )
                print("PASS: Idempotent retry returned the original response.")

                changed_payload = {
                    "purchase_order": payload["purchase_order"],
                    "invoice": document(f"INV-{marker}", quantity=1),
                }
                conflict = client.post(
                    "/api/v1/reconcile/two-way/json",
                    json=changed_payload,
                    headers=headers,
                )
                if conflict.status_code != 409:
                    raise RuntimeError(
                        "Reusing a key for changed input should return 409; "
                        f"got {conflict.status_code}: {conflict.text}"
                    )
                print("PASS: Reusing the key with changed input returned HTTP 409.")

                detail = client.get(
                    f"/api/v1/reconciliations/{record_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if detail.status_code != 200:
                    raise RuntimeError(
                        f"History detail failed ({detail.status_code}): {detail.text}"
                    )
                detail_json = detail.json()
                if (
                    detail_json.get("reconciliation_id") != record_id
                    or detail_json.get("report", {}).get("status") != "MATCH"
                    or detail_json.get("document_ids", {}).get("purchase_order_id")
                    != payload["purchase_order"]["document_id"]
                ):
                    raise RuntimeError("Retrieved history did not match submitted data.")
                print("PASS: Saved record was retrieved through the API.")

                listing = client.get(
                    "/api/v1/reconciliations",
                    params={"workflow": "two_way_json", "limit": 100},
                    headers={"Authorization": f"Bearer {token}"},
                )
                if listing.status_code != 200:
                    raise RuntimeError(
                        f"History listing failed ({listing.status_code}): {listing.text}"
                    )
                if not any(
                    item.get("reconciliation_id") == record_id
                    for item in listing.json().get("items", [])
                ):
                    raise RuntimeError("New record was absent from the history listing.")
                print("PASS: Saved record appeared in the history listing.")

                # Verify a distinct key can independently persist the same payload.
                scoped = client.post(
                    "/api/v1/reconcile/two-way/json",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Idempotency-Key": conflict_key,
                    },
                )
                if scoped.status_code != 200:
                    raise RuntimeError(
                        f"Second independent key failed ({scoped.status_code}): "
                        f"{scoped.text}"
                    )
                second_id = scoped.json().get("reconciliation_id")
                if second_id:
                    owned_record_ids.add(second_id)
                print("PASS: A separate idempotency key created its own record.")

                # Exercise the actual PDF intake -> extraction -> reconciliation
                # -> persistence path using synthetic selectable-text documents.
                po_pdf = make_text_pdf([
                    f"PO Number: PO-{marker}",
                    f"Supplier ID: SUP-{marker}",
                    "Currency: INR",
                    "Total Amount: 20",
                    "Item ID | Description | Quantity | Unit Price",
                    "A | Widget | 2 | 10",
                ])
                invoice_pdf = make_text_pdf([
                    f"Invoice No: INV-{marker}",
                    f"Supplier ID: SUP-{marker}",
                    "Currency: INR",
                    "Grand Total: 20",
                    "Item ID | Description | Quantity | Unit Price",
                    "A | Widget | 2 | 10",
                ])
                grn_pdf = make_text_pdf([
                    f"GRN No: GRN-{marker}",
                    f"Supplier ID: SUP-{marker}",
                    "Item ID | Description | Received Quantity",
                    "A | Widget | 2",
                ])

                def pdf_uploads():
                    return {
                        "purchase_order": (
                            "purchase_order.pdf", po_pdf, "application/pdf"
                        ),
                        "invoice": ("invoice.pdf", invoice_pdf, "application/pdf"),
                        "goods_receipt_note": (
                            "goods_receipt_note.pdf", grn_pdf, "application/pdf"
                        ),
                    }

                pdf_headers = {
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": pdf_key,
                }
                pdf_response = client.post(
                    "/api/v1/reconcile/three-way/pdf",
                    files=pdf_uploads(),
                    headers=pdf_headers,
                )
                if pdf_response.status_code != 200:
                    raise RuntimeError(
                        f"PDF API submission failed ({pdf_response.status_code}): "
                        f"{pdf_response.text}"
                    )
                pdf_json = pdf_response.json()
                if pdf_json.get("status") != "MATCH":
                    raise RuntimeError(
                        "Synthetic PDF reconciliation should MATCH, got "
                        f"{pdf_json.get('status')!r}: {pdf_json}"
                    )
                pdf_record_id = pdf_json.get("reconciliation_id")
                if not pdf_record_id:
                    raise RuntimeError("PDF API response omitted reconciliation_id.")
                owned_record_ids.add(pdf_record_id)
                print("PASS: Three PDFs were extracted, reconciled and persisted.")

                pdf_replay = client.post(
                    "/api/v1/reconcile/three-way/pdf",
                    files=pdf_uploads(),
                    headers=pdf_headers,
                )
                if pdf_replay.status_code != 200 or pdf_replay.json() != pdf_json:
                    raise RuntimeError(
                        "PDF idempotent retry did not return the original response."
                    )
                print("PASS: PDF idempotent retry returned the original response.")

                pdf_option_conflict = client.post(
                    "/api/v1/reconcile/three-way/pdf",
                    params={"enable_ocr": "true"},
                    files=pdf_uploads(),
                    headers=pdf_headers,
                )
                if pdf_option_conflict.status_code != 409:
                    raise RuntimeError(
                        "Changing the OCR option with the same PDF idempotency key "
                        f"should return 409, got {pdf_option_conflict.status_code}."
                    )
                print("PASS: Changing the OCR option with the same key returned HTTP 409.")
        except Exception:
            run_failed = True
            raise
        finally:
            print("\n=== Clean up verification records ===", flush=True)
            try:
                with SessionLocal() as db:
                    saved_keys = db.scalars(
                        select(IdempotencyRecord).where(
                            IdempotencyRecord.idempotency_key.in_(owned_keys)
                        )
                    ).all()
                    for saved in saved_keys:
                        saved_id = (
                            saved.response.get("reconciliation_id")
                            if isinstance(saved.response, dict) else None
                        )
                        if saved_id:
                            owned_record_ids.add(saved_id)

                    if owned_keys:
                        db.execute(
                            delete(IdempotencyRecord).where(
                                IdempotencyRecord.idempotency_key.in_(owned_keys)
                            )
                        )
                    if owned_record_ids:
                        db.execute(
                            delete(ReconciliationRecord).where(
                                ReconciliationRecord.id.in_(owned_record_ids)
                            )
                        )
                    db.commit()
                print(
                    "Cleanup completed for only this run's idempotency keys "
                    "and reconciliation IDs."
                )
            except Exception as cleanup_error:
                print(
                    "WARNING: automatic cleanup could not be confirmed. "
                    "Inspect only records associated with the unique pgverify "
                    f"marker {marker}. Error type: {type(cleanup_error).__name__}",
                    file=sys.stderr,
                )
                if not run_failed:
                    raise

        print("\nALL POSTGRESQL API VERIFICATION STEPS PASSED.")
        return 0
    except Exception as error:
        print(f"\nPOSTGRESQL API VERIFICATION FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
