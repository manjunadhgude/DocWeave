"""Initial DocWeave persistent-history schema.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workflow", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reconciliation_records_created_at",
        "reconciliation_records",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_reconciliation_records_status",
        "reconciliation_records",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_reconciliation_records_workflow",
        "reconciliation_records",
        ["workflow"],
        unique=False,
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workflow", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow",
            "idempotency_key",
            name="uq_idempotency_workflow_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_index(
        "ix_reconciliation_records_workflow",
        table_name="reconciliation_records",
    )
    op.drop_index(
        "ix_reconciliation_records_status",
        table_name="reconciliation_records",
    )
    op.drop_index(
        "ix_reconciliation_records_created_at",
        table_name="reconciliation_records",
    )
    op.drop_table("reconciliation_records")
