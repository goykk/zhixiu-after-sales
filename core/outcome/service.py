"""C-OUTCOME@1: 真实维修结果回收与案例关闭。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.models import (
    AuditLog,
    Case,
    DiagnosticStep,
    Hypothesis,
    RepairOutcome,
    User,
    WorkOrder,
    new_id,
    utcnow,
)
from core.policy.rbac import Actor, can, can_access_case
from core.workflow.states import (
    ALLOWED_TRANSITIONS,
    CaseStatus,
    assert_transition,
    coerce_status,
)
from services.api.app.errors import ApiError

OUTCOME_WRITE = "outcome:write"
CLOSE_ACTIONS = ("approval:decide", "workorder:update")
CONSISTENCY_VALUES = ("match", "mismatch", "unknown")


@dataclass(frozen=True)
class OutcomeResult:
    outcome: RepairOutcome
    consistency: str


def _as_actor(value: Any) -> Actor:
    if isinstance(value, Actor):
        return value
    actor_id = getattr(value, "actor_id", None) or getattr(value, "id", None)
    return Actor(actor_id, getattr(value, "role", None))


def _payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _for_update(db: Session, stmt: Select) -> Select:
    if db.get_bind().dialect.name == "sqlite":
        return stmt
    return stmt.with_for_update()


def _lock_case(db: Session, case_id: str) -> Case:
    case = db.execute(_for_update(db, select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", "case not found")
    return case


def _lock_work_order(db: Session, work_order_id: str) -> WorkOrder:
    stmt = _for_update(db, select(WorkOrder).where(WorkOrder.id == work_order_id))
    work_order = db.execute(stmt).scalar_one_or_none()
    if work_order is None:
        raise ApiError(404, "WORK_ORDER_NOT_FOUND", "work order not found")
    return work_order


def _require_outcome_writer(db: Session, technician_id: str) -> User | None:
    """The persisted actor role decides; unknown ids are treated as external records."""
    user = db.get(User, technician_id)
    if user is not None and not can(user.role, OUTCOME_WRITE):
        raise ApiError(403, "FORBIDDEN", "outcome:write permission required")
    return user


def _ensure_case_access(case: Case, actor: Actor, work_order: WorkOrder) -> None:
    if not can_access_case(
        actor,
        case_user_id=case.user_id,
        workorder_assignee=work_order.assignee,
    ):
        raise ApiError(403, "FORBIDDEN", "forbidden")


def _supported_cause_codes(db: Session, case_id: str) -> set[str]:
    stmt = select(Hypothesis.cause_code).where(
        Hypothesis.case_id == case_id, Hypothesis.status == "supported"
    )
    return set(db.execute(stmt).scalars().all())


def _existing_outcome(db: Session, work_order_id: str) -> RepairOutcome | None:
    stmt = select(RepairOutcome).where(RepairOutcome.work_order_id == work_order_id)
    return db.execute(stmt).scalar_one_or_none()


def record_outcome(
    db: Session,
    *,
    work_order_id: str,
    technician_id: str,
    actual_cause_code: str,
    action: str,
    parts_replaced: list[str],
    resolved: bool,
    note: str = "",
) -> OutcomeResult:
    technician = _require_outcome_writer(db, technician_id)

    work_order = db.get(WorkOrder, work_order_id)
    if work_order is None:
        raise ApiError(404, "WORK_ORDER_NOT_FOUND", "work order not found")

    case = _lock_case(db, work_order.case_id)
    work_order = _lock_work_order(db, work_order.id)
    if technician is not None:
        _ensure_case_access(case, Actor(technician_id, technician.role), work_order)

    # A recorded outcome is immutable: revisions must go through a new work order.
    if _existing_outcome(db, work_order.id) is not None:
        raise ApiError(409, "OUTCOME_EXISTS", "outcome already recorded for this work order")

    try:
        current = coerce_status(case.status)
    except ValueError as exc:
        raise ApiError(
            409, "ILLEGAL_TRANSITION", f"unknown case status: {case.status}"
        ) from exc
    if current != CaseStatus.WORK_ORDER_CREATED:
        raise ApiError(
            409,
            "ILLEGAL_TRANSITION",
            f"case status must be WORK_ORDER_CREATED, got {current.value}",
        )
    assert_transition(current, CaseStatus.OUTCOME_PENDING)

    supported = _supported_cause_codes(db, case.id)
    if not supported:
        consistency = "unknown"
    elif actual_cause_code in supported:
        consistency = "match"
    else:
        consistency = "mismatch"

    parts = list(parts_replaced or [])
    outcome = RepairOutcome(
        id=new_id(),
        work_order_id=work_order.id,
        technician_id=technician_id,
        actual_cause_code=actual_cause_code,
        action=action,
        parts_replaced=parts,
        resolved=bool(resolved),
        note=note or None,
    )
    db.add(outcome)

    work_order.status = "resolved"
    work_order.updated_at = utcnow()

    case.status = CaseStatus.OUTCOME_PENDING.value
    case.updated_at = utcnow()

    payload = {
        "work_order_id": work_order.id,
        "technician_id": technician_id,
        "actual_cause_code": actual_cause_code,
        "action": action,
        "parts_replaced": parts,
        "resolved": bool(resolved),
        "consistency": consistency,
        "status": CaseStatus.OUTCOME_PENDING.value,
    }
    db.add(
        DiagnosticStep(
            id=new_id(),
            case_id=case.id,
            step_type="outcome_recorded",
            input={"work_order_id": work_order.id, "technician_id": technician_id},
            output={
                "actual_cause_code": actual_cause_code,
                "action": action,
                "parts_replaced": parts,
                "resolved": bool(resolved),
                "consistency": consistency,
            },
        )
    )
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=technician_id,
            action="outcome.recorded",
            resource_id=case.id,
            payload_hash=_payload_hash(payload),
            payload=payload,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(
            409, "OUTCOME_EXISTS", "outcome already recorded for this work order"
        ) from exc
    db.refresh(outcome)
    return OutcomeResult(outcome=outcome, consistency=consistency)



def list_outcomes(db: Session, case_id: str) -> list[RepairOutcome]:
    stmt = (
        select(RepairOutcome)
        .join(WorkOrder, WorkOrder.id == RepairOutcome.work_order_id)
        .where(WorkOrder.case_id == case_id)
        .order_by(RepairOutcome.created_at.asc(), RepairOutcome.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def close_case(db: Session, *, case_id: str, actor: Actor) -> Case:
    actor_obj = _as_actor(actor)
    if not any(can(actor_obj.role, permission) for permission in CLOSE_ACTIONS):
        raise ApiError(403, "FORBIDDEN", "close requires approval:decide or workorder:update")

    case = _lock_case(db, case_id)
    if not can_access_case(actor_obj, case_user_id=case.user_id):
        raise ApiError(403, "FORBIDDEN", "forbidden")

    try:
        current = coerce_status(case.status)
    except ValueError as exc:
        raise ApiError(
            409, "ILLEGAL_TRANSITION", f"unknown case status: {case.status}"
        ) from exc
    if current == CaseStatus.CLOSED:
        return case
    if CaseStatus.CLOSED not in ALLOWED_TRANSITIONS[current]:
        raise ApiError(
            409,
            "ILLEGAL_TRANSITION",
            f"{current.value} -> CLOSED is not allowed",
        )
    assert_transition(current, CaseStatus.CLOSED)

    case.status = CaseStatus.CLOSED.value
    case.updated_at = utcnow()
    payload = {"from_status": current.value, "to_status": CaseStatus.CLOSED.value}
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=actor_obj.actor_id,
            action="case.closed",
            resource_id=case.id,
            payload_hash=_payload_hash(payload),
            payload=payload,
        )
    )
    db.commit()
    db.refresh(case)
    return case