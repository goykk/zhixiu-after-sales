"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-14

与 ``core.db.base.create_all()`` 建出相同表结构：12 张 V1.2 业务表 + 多模态 uploads 表。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)

    op.create_table(
        "devices",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("brand", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("hardware_version", sa.String(length=64), nullable=True),
        sa.Column("firmware_version", sa.String(length=64), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand", "model", name="uq_devices_brand_model"),
    )

    op.create_table(
        "eval_scenarios",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("device_model", sa.String(length=128), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("true_cause_code", sa.String(length=64), nullable=False),
        sa.Column("variants", sa.JSON(), nullable=True),
        sa.Column("risk_flags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "uploads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_uploads_case_id"), "uploads", ["case_id"], unique=False)
    op.create_index(op.f("ix_uploads_sha256"), "uploads", ["sha256"], unique=False)

    op.create_table(
        "cases",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("symptom", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("environment", sa.JSON(), nullable=True),
        sa.Column("attempted_steps", sa.JSON(), nullable=True),
        sa.Column("extracted", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("risk_level", sa.String(length=32), nullable=True),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("evidence_version", sa.Integer(), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=True),
        sa.Column("last_question", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cases_device_id"), "cases", ["device_id"], unique=False)
    op.create_index(op.f("ix_cases_status"), "cases", ["status"], unique=False)
    op.create_index(op.f("ix_cases_user_id"), "cases", ["user_id"], unique=False)

    op.create_table(
        "manuals",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_manuals_device_id"), "manuals", ["device_id"], unique=False)

    op.create_table(
        "diagnostic_steps",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("step_type", sa.String(length=64), nullable=False),
        sa.Column("input", sa.JSON(), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_diagnostic_steps_case_id"), "diagnostic_steps", ["case_id"], unique=False
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("manual_id", sa.String(length=64), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["manual_id"], ["manuals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_chunks_manual_id"), "document_chunks", ["manual_id"], unique=False
    )

    op.create_table(
        "hypotheses",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("cause_code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confidence_level", sa.String(length=16), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("evidence_version", sa.Integer(), nullable=False),
        sa.Column("support_evidence_ids", sa.JSON(), nullable=True),
        sa.Column("refute_evidence_ids", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "cause_code", name="uq_hypothesis_case_cause"),
    )
    op.create_index(op.f("ix_hypotheses_case_id"), "hypotheses", ["case_id"], unique=False)

    op.create_table(
        "probes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("probe_type", sa.String(length=32), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("target_hypotheses", sa.JSON(), nullable=True),
        sa.Column("expected_outcomes", sa.JSON(), nullable=True),
        sa.Column("cost_level", sa.String(length=16), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rationale", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "code", name="uq_probe_case_code"),
    )
    op.create_index(op.f("ix_probes_case_id"), "probes", ["case_id"], unique=False)

    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("polarity", sa.String(length=32), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evidence_case_id"), "evidence", ["case_id"], unique=False)
    op.create_index(op.f("ix_evidence_chunk_id"), "evidence", ["chunk_id"], unique=False)

    op.create_table(
        "probe_results",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("probe_id", sa.String(length=64), nullable=False),
        sa.Column("observed_value", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["probe_id"], ["probes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("probe_id"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("payload_hash", sa.String(length=128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_actor_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("probe_results")
    op.drop_index(op.f("ix_evidence_chunk_id"), table_name="evidence")
    op.drop_index(op.f("ix_evidence_case_id"), table_name="evidence")
    op.drop_table("evidence")
    op.drop_index(op.f("ix_probes_case_id"), table_name="probes")
    op.drop_table("probes")
    op.drop_index(op.f("ix_hypotheses_case_id"), table_name="hypotheses")
    op.drop_table("hypotheses")
    op.drop_index(op.f("ix_document_chunks_manual_id"), table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index(op.f("ix_diagnostic_steps_case_id"), table_name="diagnostic_steps")
    op.drop_table("diagnostic_steps")
    op.drop_index(op.f("ix_manuals_device_id"), table_name="manuals")
    op.drop_table("manuals")
    op.drop_index(op.f("ix_cases_user_id"), table_name="cases")
    op.drop_index(op.f("ix_cases_status"), table_name="cases")
    op.drop_index(op.f("ix_cases_device_id"), table_name="cases")
    op.drop_table("cases")
    op.drop_index(op.f("ix_uploads_sha256"), table_name="uploads")
    op.drop_index(op.f("ix_uploads_case_id"), table_name="uploads")
    op.drop_table("uploads")
    op.drop_table("eval_scenarios")
    op.drop_table("devices")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")