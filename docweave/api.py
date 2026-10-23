"""FastAPI interface for DocWeave reconciliation workflows."""

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

from docweave.engine import reconcile
from docweave.three_way import reconcile_three_way
from docweave.pdf_three_way import reconcile_pdf_documents


MAX_UPLOAD_BYTES = 25 * 1024 * 1024

app = FastAPI(
    title="DocWeave API",
    description=(
        "Evidence-grounded purchase-order, invoice and goods-receipt "
        "reconciliation."
    ),
    version="1.0.0",
)


class TwoWayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purchase_order: dict[str, Any]
    invoice: dict[str, Any]


class ThreeWayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purchase_order: dict[str, Any]
    invoice: dict[str, Any]
    goods_receipt_note: dict[str, Any]


@app.get("/health")
def health():
    """Simple process-health endpoint."""
    return {"status": "ok", "service": "docweave-api"}


@app.post("/api/v1/reconcile/two-way/json")
def reconcile_two_way_json(request: TwoWayRequest):
    """Reconcile a structured purchase order and invoice."""
    return reconcile(request.purchase_order, request.invoice)


@app.post("/api/v1/reconcile/three-way/json")
def reconcile_three_way_json(request: ThreeWayRequest):
    """Reconcile a structured purchase order, invoice and receipt."""
    return reconcile_three_way(
        request.purchase_order,
        request.invoice,
        request.goods_receipt_note,
    )


async def _save_pdf_upload(upload: UploadFile, destination: Path) -> None:
    """Save one PDF with an extension check and a per-file size limit."""
    try:
        filename = upload.filename or ""
        if Path(filename).suffix.lower() != ".pdf":
            raise HTTPException(
                status_code=400,
                detail=f"{filename or 'Uploaded file'} must have a .pdf filename",
            )

        total = 0
        with destination.open("wb") as output:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Each PDF must be no larger than 25 MiB",
                    )
                output.write(chunk)

        if total == 0:
            raise HTTPException(
                status_code=400,
                detail=f"{filename} is empty",
            )
    finally:
        await upload.close()


@app.post("/api/v1/reconcile/three-way/pdf")
async def reconcile_three_way_pdf(
    purchase_order: UploadFile = File(...),
    invoice: UploadFile = File(...),
    goods_receipt_note: UploadFile = File(...),
):
    """Extract and reconcile three PDFs, stopping safely on review cases."""
    uploads = {
        "purchase_order": purchase_order,
        "invoice": invoice,
        "goods_receipt_note": goods_receipt_note,
    }

    with tempfile.TemporaryDirectory(prefix="docweave_api_") as temporary:
        root = Path(temporary)
        saved = {}

        for role, upload in uploads.items():
            destination = root / f"{role}.pdf"
            await _save_pdf_upload(upload, destination)
            saved[role] = destination

        return reconcile_pdf_documents(
            saved["purchase_order"],
            saved["invoice"],
            saved["goods_receipt_note"],
        )
