"""FastAPI interface for DocWeave reconciliation and persistent history."""

import hashlib
import hmac
import json
import os
import tempfile
import time
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text
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




# API routes require a configured bearer token. Keep /health public so a
# platform health probe can check that the process is alive.
bearer_scheme = HTTPBearer(auto_error=False)
MAX_TOTAL_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_JSON_REQUEST_BYTES = 1 * 1024 * 1024
MAX_PDF_REQUEST_BODY_BYTES = MAX_TOTAL_UPLOAD_BYTES + 2 * 1024 * 1024
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("DOCWEAVE_RATE_LIMIT_REQUESTS", "120"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("DOCWEAVE_RATE_LIMIT_WINDOW_SECONDS", "60"))
if RATE_LIMIT_MAX_REQUESTS < 1 or RATE_LIMIT_WINDOW_SECONDS < 1:
    raise RuntimeError("DocWeave API rate-limit settings must be positive integers")

_rate_limit_state: dict[str, tuple[float, int]] = {}
_rate_limit_lock = Lock()


def require_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    """Reject protected API calls unless a configured bearer token matches."""
    expected = os.getenv("DOCWEAVE_API_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="API authentication is not configured; set DOCWEAVE_API_TOKEN.",
        )
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials, expected)
    ):
        raise HTTPException(
            status_code=401,
            detail="A valid bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


class RequestBodyTooLarge(Exception):
    """Raised when streamed API request bytes exceed the route's cap."""


class APIRequestSecurityMiddleware:
    """Pure ASGI request checks, including bodies without Content-Length."""

    def __init__(self, app):
        self.app = app

    async def _send_json(self, scope, receive, send, status, detail, headers=None):
        from starlette.responses import JSONResponse
        response_headers = headers or {}
        response = JSONResponse(status_code=status, content={"detail": detail}, headers=response_headers)
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        max_body_bytes = (
            MAX_PDF_REQUEST_BODY_BYTES
            if path == "/api/v1/reconcile/three-way/pdf"
            else MAX_JSON_REQUEST_BYTES
        )
        raw_content_length = next(
            (value for key, value in scope.get("headers", []) if key.lower() == b"content-length"),
            None,
        )
        if raw_content_length is not None:
            try:
                declared_length = int(raw_content_length.decode("ascii"))
            except (ValueError, UnicodeDecodeError):
                await self._send_json(scope, receive, send, 400, "Invalid Content-Length header.")
                return
            if declared_length < 0:
                await self._send_json(scope, receive, send, 400, "Invalid Content-Length header.")
                return
            if declared_length > max_body_bytes:
                await self._send_json(
                    scope, receive, send, 413,
                    "Request body exceeds the configured size limit.",
                )
                return

        client = scope.get("client")
        client_host = client[0] if client else "unknown"
        now = time.monotonic()
        retry_after = 0
        with _rate_limit_lock:
            previous = _rate_limit_state.get(client_host)
            if previous is None or now - previous[0] >= RATE_LIMIT_WINDOW_SECONDS:
                _rate_limit_state[client_host] = (now, 1)
            elif previous[1] >= RATE_LIMIT_MAX_REQUESTS:
                retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - previous[0])))
            else:
                _rate_limit_state[client_host] = (previous[0], previous[1] + 1)

            if len(_rate_limit_state) > 4096:
                expired = [
                    host for host, (started, _count) in _rate_limit_state.items()
                    if now - started >= RATE_LIMIT_WINDOW_SECONDS
                ]
                for host in expired:
                    _rate_limit_state.pop(host, None)
                while len(_rate_limit_state) > 4096:
                    _rate_limit_state.pop(next(iter(_rate_limit_state)))

        if retry_after:
            await self._send_json(
                scope, receive, send, 429,
                "API rate limit exceeded; retry after the window resets.",
                headers={"Retry-After": str(retry_after)},
            )
            return

        body_bytes = 0
        response_started = False

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        async def limited_receive():
            nonlocal body_bytes
            message = await receive()
            if message.get("type") == "http.request":
                body_bytes += len(message.get("body", b""))
                if body_bytes > max_body_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            # FastAPI parses request bodies before calling handlers, so an
            # oversized body should be rejected before a response has started.
            if not response_started:
                await self._send_json(
                    scope, receive, send, 413,
                    "Request body exceeds the configured size limit.",
                )


# Register this pure-ASGI middleware before any later BaseHTTPMiddleware so
# the receive-byte limit applies while multipart/JSON bodies are being parsed.
app.add_middleware(APIRequestSecurityMiddleware)


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


def _fingerprint_files(
    paths: dict[str, Path],
    options: dict[str, Any] | None = None,
) -> str:
    """Fingerprint PDF bytes and every option that changes processing."""
    file_hashes = {
        role: hashlib.sha256(path.read_bytes()).hexdigest()
        for role, path in sorted(paths.items())
    }
    return _request_fingerprint({
        "files": file_hashes,
        "options": options or {},
    })


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


@app.get("/ready")
def readiness(db: Session = Depends(get_db)):
    """Check whether the service can execute a query against its database.

    /health reports process liveness; /ready reports database readiness.
    This endpoint intentionally remains public for platform readiness probes.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail="Database readiness check failed.",
        ) from error
    return {"status": "ready", "service": "docweave-api", "database": "ok"}


@app.post("/api/v1/reconcile/two-way/json", dependencies=[Depends(require_api_token)])
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


@app.post("/api/v1/reconcile/three-way/json", dependencies=[Depends(require_api_token)])
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


@app.get("/api/v1/reconciliations", dependencies=[Depends(require_api_token)])
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


@app.get("/api/v1/reconciliations/{reconciliation_id}", dependencies=[Depends(require_api_token)])
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


async def _save_pdf_upload(
    upload: UploadFile,
    destination: Path,
    previously_uploaded_bytes: int = 0,
) -> int:
    """Save one PDF with per-file and aggregate limits; return its byte size."""
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
                if previously_uploaded_bytes + total > MAX_TOTAL_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="The combined size of all PDFs must not exceed 50 MiB",
                    )
                output.write(chunk)

        if total == 0:
            raise HTTPException(
                status_code=400,
                detail=f"{filename} is empty",
            )
        return total
    finally:
        await upload.close()


@app.post("/api/v1/reconcile/three-way/pdf", dependencies=[Depends(require_api_token)])
async def reconcile_three_way_pdf(
    purchase_order: UploadFile = File(...),
    invoice: UploadFile = File(...),
    goods_receipt_note: UploadFile = File(...),
    enable_ocr: bool = Query(
        default=False,
        description=(
            "Enable optional OCR for scanned PDFs; requires the OCR runtime "
            "to be installed on the server."
        ),
    ),
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

        total_upload_bytes = 0
        for role, upload in uploads.items():
            destination = root / f"{role}.pdf"
            total_upload_bytes += await _save_pdf_upload(
                upload, destination, previously_uploaded_bytes=total_upload_bytes
            )
            saved[role] = destination

        report = reconcile_pdf_documents(
            saved["purchase_order"],
            saved["invoice"],
            saved["goods_receipt_note"],
            enable_ocr=enable_ocr,
        )
        return _save_report(
            db,
            report,
            "three_way_pdf",
            idempotency_key=idempotency_key,
            request_fingerprint=(
                _fingerprint_files(saved, options={"enable_ocr": enable_ocr})
                if idempotency_key is not None else None
            ),
        )
