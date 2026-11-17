"""C-WORKORDER@1 routes: 幂等建单与工单查询。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import get_db
from core.db.models import Case, WorkOrder
from core.policy.idempotency import get_work_order_by_key
from core.policy.rbac import (
    CASE_READ_ALL,
    WORKORDER_CREATE,
    WORKORDER_READ,
    Actor,
    can,
    can_access_case,
)
from core.tools.gateway import ToolError
from core.tools.workorder_tool import create_work_order, work_order_out
from core.workflow.states import CaseStatus, IllegalTransition, assert_transition
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(tags=["work-orders"])


class WorkOrderCreateIn(BaseModel):
    idempotency_key: str = Field(min_length=1)
    assignee: str | None = None


def _require(actor: Actor, action: str) -> None:
    if not can(actor.role, action):
        raise ApiError(403, "FORBIDDEN", "insufficient permission")


def _load_case(db: Any, case_id: str, actor: Actor) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", "case not found")
    if not can_access_case(actor, case_user_id=case.user_id):
        raise ApiError(403, "FORBIDDEN", "forbidden")
    return case


@router.post("/cases/{case_id}/work-orders", status_code=201)
def create_work_order_endpoint(
    case_id: str,
    payload: WorkOrderCreateIn,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> dict:
    actor = actor_of(current_user)
    _require(actor, WORKORDER_CREATE)
    case = _load_case(db, case_id, actor)
    key = payload.idempotency_key.strip()

    existing = get_work_order_by_key(db, key)
    if existing is not None:
        if existing.case_id != case.id:
            raise ApiError(
                409,
                "IDEMPOTENCY_KEY_CONFLICT",
                "idempotency key already used by another case",
            )
        return {"work_order": work_order_out(existing), "created": False}

    status = str(case.status)
    if status == CaseStatus.WORK_ORDER_CREATED.value:
        raise ApiError(409, "WORK_ORDER_EXISTS", "case already has a work order")
    if status != CaseStatus.APPROVAL_PENDING.value:
        raise ApiError(
            409,
            "ILLEGAL_TRANSITION",
            f"case status {status} cannot create a work order",
        )

    try:
        work_order, created = create_work_order(
            db,
            case_id=case.id,
            actor=actor,
            idempotency_key=key,
            assignee=payload.assignee,
        )
    except ToolError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message, exc.details) from exc

    if str(case.status) == CaseStatus.APPROVAL_PENDING.value:
        try:
            assert_transition(CaseStatus.APPROVAL_PENDING, CaseStatus.WORK_ORDER_CREATED)
        except IllegalTransition as exc:  # pragma: no cover - 前置状态已校验
            raise ApiError(409, "ILLEGAL_TRANSITION", str(exc)) from exc
        case.status = CaseStatus.WORK_ORDER_CREATED.value
        db.commit()

    return {"work_order": work_order_out(work_order), "created": created}


@router.get("/work-orders")
def list_work_orders_endpoint(
    case_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> dict:
    actor = actor_of(current_user)
    _require(actor, WORKORDER_READ)

    stmt = select(WorkOrder)
    if case_id:
        case = _load_case(db, case_id, actor)
        stmt = stmt.where(WorkOrder.case_id == case.id)
    elif not can(actor.role, CASE_READ_ALL):
        stmt = stmt.where(WorkOrder.assignee == actor.actor_id)
    stmt = (
        stmt.order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    return {"items": [work_order_out(work_order) for work_order in rows]}


@router.get("/work-orders/{work_order_id}")
def get_work_order_endpoint(
    work_order_id: str,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> dict:
    actor = actor_of(current_user)
    _require(actor, WORKORDER_READ)

    work_order = db.get(WorkOrder, work_order_id)
    if work_order is None:
        raise ApiError(404, "WORK_ORDER_NOT_FOUND", "work order not found")
    if not can(actor.role, CASE_READ_ALL):
        case = db.get(Case, work_order.case_id)
        allowed = can_access_case(
            actor,
            case_user_id=case.user_id if case is not None else None,
            workorder_assignee=work_order.assignee,
        )
        if not allowed:
            raise ApiError(403, "FORBIDDEN", "forbidden")
    return work_order_out(work_order)