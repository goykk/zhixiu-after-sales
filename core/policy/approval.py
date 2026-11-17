"""维修方案提交审批与审批决定（C-APPROVAL@1）。

审批只做状态推进与留痕，不生成工单：提交后案例停在 `APPROVAL_PENDING`，
批准同样保持 `APPROVAL_PENDING`（供幂等建单消费），驳回转 `NEED_HUMAN`。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select, select

from core.db.models import Approval, AuditLog, Case, DiagnosticStep, new_id, utcnow
from core.policy.rbac import Actor, can_access_case
from core.workflow.states import (
    CaseStatus,
    assert_transition,
    coerce_status,
)
from services.api.app.errors import ApiError

DECISIONS = ("approve", "reject")

REPAIR_PLANNING = CaseStatus.REPAIR_PLANNING.value
APPROVAL_PENDING = CaseStatus.APPROVAL_PENDING.value
NEED_HUMAN = CaseStatus.NEED_HUMAN.value

APPROVAL_SUBMITTED = "case.approval_submitted"
APPROVAL_RECORDED = "case.approval"


def _payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _add_audit(db: Any, *, actor_id: str | None, action: str, case_id: str, payload: dict) -> None:
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=actor_id,
            action=action,
            resource_id=case_id,
            payload_hash=_payload_hash(payload),
            payload=payload,
            created_at=utcnow(),
        )
    )


def _add_step(db: Any, *, case_id: str, step_type: str, input_data: dict, output: dict) -> None:
    db.add(
        DiagnosticStep(
            id=new_id(),
            case_id=case_id,
            step_type=step_type,
            input=input_data,
            output=output,
            created_at=utcnow(),
        )
    )


def _for_update(db: Any, stmt: Select) -> Select:
    if db.get_bind().dialect.name == "sqlite":
        return stmt
    return stmt.with_for_update()


def _lock_case(db: Any, case_id: str) -> Case:
    case = db.execute(_for_update(db, select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", "case not found")
    return case


def _status(case: Case) -> str:
    try:
        return coerce_status(case.status).value
    except ValueError as exc:
        raise ApiError(
            409, "ILLEGAL_TRANSITION", f"unknown case status: {case.status}"
        ) from exc


def _ensure_access(case: Case, actor: Actor) -> None:
    if not can_access_case(actor, case_user_id=case.user_id):
        raise ApiError(403, "FORBIDDEN", "forbidden")


def submit_approval(db: Any, *, case_id: str, actor: Actor) -> Case:
    """`REPAIR_PLANNING -> APPROVAL_PENDING`；已在 `APPROVAL_PENDING` 时幂等返回案例。"""
    case = _lock_case(db, case_id)
    _ensure_access(case, actor)

    status = _status(case)
    if status == APPROVAL_PENDING:
        return case
    if status != REPAIR_PLANNING:
        raise ApiError(
            409,
            "ILLEGAL_TRANSITION",
            f"当前状态 {status} 不允许提交审批",
            {"from": status, "allowed": [REPAIR_PLANNING]},
        )

    try:
        assert_transition(REPAIR_PLANNING, APPROVAL_PENDING)
        case.status = APPROVAL_PENDING
        _add_step(
            db,
            case_id=case_id,
            step_type="approval_submitted",
            input_data={"from": status},
            output={"to": APPROVAL_PENDING, "submitted_by": actor.actor_id},
        )
        _add_audit(
            db,
            actor_id=actor.actor_id,
            action=APPROVAL_SUBMITTED,
            case_id=case_id,
            payload={"from": status, "to": APPROVAL_PENDING, "submitted_by": actor.actor_id},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(case)
    return case


def latest_approval(db: Any, case_id: str) -> Approval | None:
    return db.execute(
        select(Approval)
        .where(Approval.case_id == case_id)
        .order_by(Approval.created_at.desc(), Approval.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def has_approved(db: Any, case_id: str) -> bool:
    approval = latest_approval(db, case_id)
    return approval is not None and approval.decision == "approve"


def record_approval(
    db: Any,
    *,
    case_id: str,
    approver_id: str,
    decision: str,
    reason: str = "",
) -> Approval:
    """记录审批决定；同一决定重复提交返回最新记录（幂等，不重复留痕）。"""
    normalized = str(decision or "").strip().lower()
    if normalized not in DECISIONS:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            f"非法审批决定: {decision!r}",
            {"allowed": list(DECISIONS)},
        )

    case = _lock_case(db, case_id)

    latest = latest_approval(db, case_id)
    if latest is not None and latest.decision == normalized:
        # 驳回后案例已在 NEED_HUMAN，重复驳回仍按幂等返回原记录
        return latest

    status = _status(case)
    if status != APPROVAL_PENDING:
        raise ApiError(
            409,
            "ILLEGAL_TRANSITION",
            f"当前状态 {status} 不允许审批",
            {"from": status, "allowed": [APPROVAL_PENDING]},
        )

    try:
        approval = Approval(
            id=new_id(),
            case_id=case_id,
            approver_id=approver_id,
            decision=normalized,
            reason=str(reason or "").strip(),
            created_at=utcnow(),
        )
        db.add(approval)

        if normalized == "reject":
            assert_transition(APPROVAL_PENDING, NEED_HUMAN)
            case.status = NEED_HUMAN

        db.flush()
        _add_audit(
            db,
            actor_id=approver_id,
            action=APPROVAL_RECORDED,
            case_id=case_id,
            payload={
                "approval_id": approval.id,
                "decision": normalized,
                "reason": approval.reason,
                "case_status": _status(case),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(approval)
    return approval


def list_approvals(db: Any, case_id: str) -> list[Approval]:
    return list(
        db.scalars(
            select(Approval)
            .where(Approval.case_id == case_id)
            .order_by(Approval.created_at.asc(), Approval.id.asc())
        )
    )


def approval_out(approval: Approval) -> dict:
    return {
        "id": approval.id,
        "case_id": approval.case_id,
        "approver_id": approval.approver_id,
        "decision": approval.decision,
        "reason": approval.reason,
        "created_at": approval.created_at,
    }