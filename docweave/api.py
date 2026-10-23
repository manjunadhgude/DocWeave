"""FastAPI interface for DocWeave reconciliation and persistent history."""

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from docweave.engine import reconcile
from docweave.pdf_three_way import reconcile_pdf_documents
from docweave.storage import (
    IdempotencyRecord,
    ReconciliationRecord,
    extract_document_ids,
    extract_source_metadata,
    get_db,
    record_detail,
    record_summary,
    timestamp_iso,
)
from docweave.three_way import reconcile_three_way


MAX_UPLOAD_BYTES = 25 * 1024 * 1024


app = FastAPI(
    title="DocWeave API",
    description=(
        "Evidence-grounded purchase-order, invoice and goods-receipt "
        "reconciliation with persistent result history."
    ),
    version="1.2.0",
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


def _request_fingerprint(payload: Any) -> str:
    """Hash a stable JSON representation of a submitted request."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint_files(paths: dict[str, Path]) -> str:
    """Fingerprint the bytes of each named PDF input."""
    file_hashes = {
        role: hashlib.sha256(path.read_bytes()).hexdigest()
        for role, path in sorted(paths.items())
    }
    return _request_fingerprint(file_hashes)


def _find_replay(
    db: Session,
    workflow: str,
    idempotency_key: str,
    request_fingerprint: str,
) -> dict | None:
    """Return a previous response or reject reuse of a key for new input."""
    try:
        saved = db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.workflow == workflow,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
        )
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail="Idempotency history is temporarily unavailable.",
        ) from error

    if saved is None:
        return None

    if saved.request_fingerprint != request_fingerprint:
        raise HTTPException(
            status_code=409,
            detail=(
                "This Idempotency-Key was already used for a different "
                "request in this workflow. Use a new key for a new submission."
            ),
        )

    # Return the original response, including its original record ID.
    return dict(saved.response)


def _save_report(
    db: Session,
    report: dict,
    workflow: str,
    idempotency_key: str | None = None,
    request_fingerprint: str | None = None,
) -> dict:
    """Persist a report and, when requested, its replayable response."""
    if idempotency_key is not None:
        if request_fingerprint is None:
            raise ValueError("A request fingerprint is required with an idempotency key.")

        previous = _find_replay(
            db, workflow, idempotency_key, request_fingerprint
        )
        if previous is not None:
            return previous

    record = ReconciliationRecord(
        workflow=workflow,
        status=str(report.get("status", "UNKNOWN")),
        document_ids=extract_document_ids(report),
        source_metadata=extract_source_metadata(report),
        report=report,
    )

    try:
        db.add(record)
        # Flush assigns the record ID and creation timestamp before the
        # exact response is stored alongside the idempotency key.
        db.flush()

        response = dict(report)
        response["reconciliation_id"] = record.id
        response["created_at"] = timestamp_iso(record.created_at)

        if idempotency_key is not None:
            db.add(
                IdempotencyRecord(
                    workflow=workflow,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    response=response,
                )
            )

        # The history row and replay row commit together.
        db.commit()

    except IntegrityError as error:
        db.rollback()

        # Another concurrent request may have committed the same key first.
        if idempotency_key is not None and request_fingerprint is not None:
            previous = _find_replay(
                db, workflow, idempotency_key, request_fingerprint
            )
            if previous is not None:
                return previous

        raise HTTPException(
            status_code=503,
            detail=(
                "The reconciliation result could not be saved safely. "
                "Check database availability before retrying."
            ),
        ) from error

    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=(
                "The reconciliation result could not be saved. "
                "Check database availability and retry carefully."
            ),
        ) from error

    return response


@app.get("/health")
def health():
    """Basic API process-health endpoint; does not verify database readiness."""
    return {"status": "ok", "service": "docweave-api"}


@app.post("/api/v1/reconcile/two-way/json")
def reconcile_two_way_json(
    request: TwoWayRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
    db: Session = Depends(get_db),
):
    """Reconcile JSON documents and save the resulting report."""
    report = reconcile(request.purchase_order, request.invoice)
    return _save_report(
        db,
        report,
        "two_way_json",
        idempotency_key=idempotency_key,
        request_fingerprint=(
            _request_fingerprint(request.model_dump(mode="json"))
            if idempotency_key is not None else None
        ),
    )


@app.post("/api/v1/reconcile/three-way/json")
def reconcile_three_way_json(
    request: ThreeWayRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
    db: Session = Depends(get_db),
):
    """Reconcile JSON PO, invoice and receipt, then save the report."""
    report = reconcile_three_way(
        request.purchase_order,
        request.invoice,
        request.goods_receipt_note,
    )
    return _save_report(
        db,
        report,
        "three_way_json",
        idempotency_key=idempotency_key,
        request_fingerprint=(
            _request_fingerprint(request.model_dump(mode="json"))
            if idempotency_key is not None else None
        ),
    )


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
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
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
        return _save_report(
            db,
            report,
            "three_way_pdf",
            idempotency_key=idempotency_key,
            request_fingerprint=(
                _fingerprint_files(saved)
                if idempotency_key is not None else None
            ),
        )
