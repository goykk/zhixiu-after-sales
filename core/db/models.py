from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("brand", "model", name="uq_devices_brand_model"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    brand: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    hardware_version: Mapped[str | None] = mapped_column(String(64))
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Manual(Base):
    __tablename__ = "manuals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("devices.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    source_url: Mapped[str | None] = mapped_column(String(512))
    checksum: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    object_key: Mapped[str | None] = mapped_column(String(512))
    content_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    manual_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("manuals.id"), nullable=False, index=True
    )
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    section: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(JSON)
    meta: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=False, index=True
    )
    device_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("devices.id"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="DRAFT", index=True
    )
    symptom: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(32))
    environment: Mapped[Any | None] = mapped_column(JSON)
    attempted_steps: Mapped[Any | None] = mapped_column(JSON)
    extracted: Mapped[Any | None] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(32))
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_fields: Mapped[Any | None] = mapped_column(JSON)
    last_question: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class DiagnosticStep(Base):
    __tablename__ = "diagnostic_steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cases.id"), nullable=False, index=True
    )
    step_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input: Mapped[Any | None] = mapped_column(JSON)
    output: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cases.id"), nullable=False, index=True
    )
    chunk_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("document_chunks.id"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    polarity: Mapped[str] = mapped_column(String(32), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_ref: Mapped[str | None] = mapped_column(String(512))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    __table_args__ = (
        UniqueConstraint("case_id", "cause_code", name="uq_hypothesis_case_cause"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cases.id"), nullable=False, index=True
    )
    cause_code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    confidence_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="low"
    )
    confidence_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    evidence_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    support_evidence_ids: Mapped[Any | None] = mapped_column(JSON, default=list)
    refute_evidence_ids: Mapped[Any | None] = mapped_column(JSON, default=list)
    rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class Probe(Base):
    __tablename__ = "probes"
    __table_args__ = (UniqueConstraint("case_id", "code", name="uq_probe_case_code"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cases.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    probe_type: Mapped[str] = mapped_column(String(32), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    target_hypotheses: Mapped[Any | None] = mapped_column(JSON)
    expected_outcomes: Mapped[Any | None] = mapped_column(JSON)
    cost_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rationale: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ProbeResult(Base):
    __tablename__ = "probe_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    probe_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("probes.id"), nullable=False, unique=True
    )
    observed_value: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class EvalScenario(Base):
    __tablename__ = "eval_scenarios"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    device_model: Mapped[str] = mapped_column(String(128), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(32))
    true_cause_code: Mapped[str] = mapped_column(String(64), nullable=False)
    variants: Mapped[Any | None] = mapped_column(JSON)
    risk_flags: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    payload_hash: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

class Part(Base):
    __tablename__ = "parts"
    __table_args__ = (
        UniqueConstraint("device_id", "part_no", name="uq_parts_device_partno"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("devices.id"), nullable=False, index=True
    )
    part_no: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stock_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown"
    )
    hardware_range: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class PartCompatibility(Base):
    __tablename__ = "part_compatibilities"
    __table_args__ = (
        UniqueConstraint("source_part_no", "target_part_no", name="uq_part_compat_pair"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    source_part_no: Mapped[str] = mapped_column(String(64), nullable=False)
    target_part_no: Mapped[str] = mapped_column(String(64), nullable=False)
    compatibility_type: Mapped[str] = mapped_column(String(32), nullable=False)
    hardware_range: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    evidence_source: Mapped[str] = mapped_column(
        String(128), nullable=False, default="catalog"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cases.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    assignee: Mapped[str | None] = mapped_column(String(128))
    external_id: Mapped[str | None] = mapped_column(String(128))
    resolution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cases.id"), nullable=False, index=True
    )
    approver_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class RepairOutcome(Base):
    __tablename__ = "repair_outcomes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    work_order_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("work_orders.id"), nullable=False, unique=True
    )
    technician_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_cause_code: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    parts_replaced: Mapped[Any | None] = mapped_column(JSON, default=list)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

class EvalRunRecord(Base):
    __tablename__ = "eval_run_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    dataset_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="v1"
    )
    split: Mapped[str] = mapped_column(String(32), nullable=False, default="holdout")
    strategies: Mapped[Any | None] = mapped_column(JSON, default=list)
    metrics: Mapped[Any | None] = mapped_column(JSON, default=dict)
    gate: Mapped[Any | None] = mapped_column(JSON, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    report_paths: Mapped[Any | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )