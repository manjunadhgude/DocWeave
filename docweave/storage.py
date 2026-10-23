"""Database models and session management for persistent reconciliation history."""

import os
import uuid
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import JSON, DateTime, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./docweave.db")

# Support common PostgreSQL URL formats while explicitly using psycopg 3.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

engine_options = {}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    **engine_options,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class ReconciliationRecord(Base):
    """One saved reconciliation result; source documents are not stored."""

    __tablename__ = "reconciliation_records"

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid.uuid4().hex,
    )
    workflow: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    document_ids: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_metadata: Mapped[dict] = mapped_column(JSON, nullable=False)
    report: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )



class IdempotencyRecord(Base):
    """Persist the result associated with one client submission key."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "workflow",
            "idempotency_key",
            name="uq_idempotency_workflow_key",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid.uuid4().hex,
    )
    workflow: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


def get_db() -> Generator[Session, None, None]:
    """Provide one database session per API request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def timestamp_iso(value: datetime) -> str:
    """Serialize timestamps consistently, including SQLite's naive datetimes."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def extract_document_ids(report: dict) -> dict:
    """Keep document identifiers, not the original input documents."""
    fields = (
        "purchase_order_id",
        "invoice_id",
        "goods_receipt_note_id",
    )
    return {
        field: report[field]
        for field in fields
        if report.get(field) is not None
    }


def extract_source_metadata(report: dict) -> dict:
    """Keep useful PDF provenance without retaining temporary file paths."""
    result = {}
    documents = report.get("documents", {})

    if not isinstance(documents, dict):
        return result

    allowed = {"document_role", "sha256", "byte_size", "page_count"}

    for role, document in documents.items():
        if not isinstance(document, dict):
            continue
        source = document.get("source")
        if not isinstance(source, dict):
            continue

        safe_source = {
            key: source[key]
            for key in allowed
            if key in source
        }
        if safe_source:
            result[role] = safe_source

    return result


def record_summary(record: ReconciliationRecord) -> dict:
    """Return list-friendly metadata without duplicating the complete report."""
    return {
        "reconciliation_id": record.id,
        "workflow": record.workflow,
        "status": record.status,
        "created_at": timestamp_iso(record.created_at),
        "document_ids": record.document_ids,
        "source_metadata": record.source_metadata,
    }


def record_detail(record: ReconciliationRecord) -> dict:
    """Return a saved report and its metadata."""
    result = record_summary(record)
    result["report"] = record.report
    return result
