"""FastAPI interface for DocWeave reconciliation and persistent history."""

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from docweave.engine import reconcile
from docweave.pdf_three_way import reconcile_pdf_documents
from docweave.storage import (
    ReconciliationRecord,
    extract_document_ids,
    extract_source_metadata,
    get_db,
    init_db,
    record_detail,
    record_summary,
    timestamp_iso,
)
from docweave.three_way import reconcile_three_way


MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Creates missing tables. Use migrations for future schema changes.
    init_db()
    yield


app = FastAPI(
    title="DocWeave API",
    description=(
        "Evidence-grounded purchase-order, invoice and goods-receipt "
        "reconciliation with persistent result history."
    ),
    version="1.1.0",
    lifespan=lifespan,
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


def _save_report(
    db: Session,
    report: dict,
    workflow: str,
) -> dict:
    """Persist the report before returning a successful API response."""
    record = ReconciliationRecord(
        workflow=workflow,
        status=str(report.get("status", "UNKNOWN")),
        document_ids=extract_document_ids(report),
        source_metadata=extract_source_metadata(report),
        report=report,
    )

    try:
        db.add(record)
        db.commit()
        db.refresh(record)
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=(
                "The reconciliation result could not be saved. "
                "Check database availability and retry carefully."
            ),
        ) from error

    # Keep the existing response shape and add persistent record identifiers.
    response = dict(report)
    response["reconciliation_id"] = record.id
    response["created_at"] = timestamp_iso(record.created_at)
    return response


@app.get("/health")
def health():
    """Basic API process-health endpoint; does not verify database readiness."""
    return {"status": "ok", "service": "docweave-api"}


@app.post("/api/v1/reconcile/two-way/json")
def reconcile_two_way_json(
    request: TwoWayRequest,
    db: Session = Depends(get_db),
):
    """Reconcile JSON documents and save the resulting report."""
    report = reconcile(request.purchase_order, request.invoice)
    return _save_report(db, report, "two_way_json")


@app.post("/api/v1/reconcile/three-way/json")
def reconcile_three_way_json(
    request: ThreeWayRequest,
    db: Session = Depends(get_db),
):
    """Reconcile JSON PO, invoice and receipt, then save the report."""
    report = reconcile_three_way(
        request.purchase_order,
        request.invoice,
        request.goods_receipt_note,
    )
    return _save_report(db, report, "three_way_json")


@app.get("/api/v1/reconciliations")
def list_reconciliations(
    status: str | None = None,
    workflow: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List saved records, newest first, with optional filters and pagination."""
    conditions = []
    if status:
        conditions.append(ReconciliationRecord.status == status)
    if workflow:
        conditions.append(ReconciliationRecord.workflow == workflow)

    count_statement = select(func.count()).select_from(ReconciliationRecord)
    records_statement = select(ReconciliationRecord)

    if conditions:
        count_statement = count_statement.where(*conditions)
        records_statement = records_statement.where(*conditions)

    try:
        total = db.scalar(count_statement)
        records = db.scalars(
            records_statement
            .order_by(
                ReconciliationRecord.created_at.desc(),
                ReconciliationRecord.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail="Reconciliation history is temporarily unavailable.",
        ) from error

    return {
        "items": [record_summary(record) for record in records],
        "total": total or 0,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/v1/reconciliations/{reconciliation_id}")
def get_reconciliation(
    reconciliation_id: str,
    db: Session = Depends(get_db),
):
    """Retrieve one saved reconciliation by its unique identifier."""
    try:
        record = db.get(ReconciliationRecord, reconciliation_id)
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail="Reconciliation history is temporarily unavailable.",
        ) from error

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Reconciliation record not found.",
        )
    return record_detail(record)


async def _save_pdf_upload(upload: UploadFile, destination: Path) -> None:
    """Save one PDF with a filename check and a per-file size limit."""
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
    db: Session = Depends(get_db),
):
    """Extract, reconcile and persist the report from three digital PDFs."""
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

        report = reconcile_pdf_documents(
            saved["purchase_order"],
            saved["invoice"],
            saved["goods_receipt_note"],
        )
        return _save_report(db, report, "three_way_pdf")
