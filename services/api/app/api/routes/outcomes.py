"""真实维修结果回收与案例关闭接口（C-OUTCOME@1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.cases.service import case_out, load_case_for_actor
from core.db.base import get_db
from core.db.models import RepairOutcome, User
from core.outcome.service import close_case, list_outcomes, record_outcome
from core.policy.rbac import can
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(tags=["outcome"])


class OutcomeIn(BaseModel):
    actual_cause_code: str = Field(min_length=1)
    action: str = Field(min_length=1)
    parts_replaced: list[str] = Field(default_factory=list)
    resolved: bool
    note: str = ""


def outcome_out(outcome: RepairOutcome) -> dict:
    return {
        "id": outcome.id,
        "work_order_id": outcome.work_order_id,
        "technician_id": outcome.technician_id,
        "actual_cause_code": outcome.actual_cause_code,
        "action": outcome.action,
        "parts_replaced": list(outcome.parts_replaced or []),
        "resolved": bool(outcome.resolved),
        "note": outcome.note,
        "created_at": outcome.created_at,
        "updated_at": outcome.updated_at,
    }


@router.post("/work-orders/{work_order_id}/outcome")
def create_work_order_outcome(
    work_order_id: str,
    body: OutcomeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    actor = actor_of(user)
    if not can(actor.role, "outcome:write"):
        raise ApiError(403, "FORBIDDEN", "outcome:write permission required")
    result = record_outcome(
        db,
        work_order_id=work_order_id,
        technician_id=actor.actor_id,
        actual_cause_code=body.actual_cause_code,
        action=body.action,
        parts_replaced=body.parts_replaced,
        resolved=body.resolved,
        note=body.note,
    )
    return {"outcome": outcome_out(result.outcome), "consistency": result.consistency}


@router.get("/cases/{case_id}/outcomes")
def get_case_outcomes(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    actor = actor_of(user)
    if not can(actor.role, "outcome:read"):
        raise ApiError(403, "FORBIDDEN", "outcome:read permission required")
    load_case_for_actor(db, case_id, actor)
    return {"items": [outcome_out(item) for item in list_outcomes(db, case_id)]}


@router.post("/cases/{case_id}/close")
def close_case_endpoint(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    actor = actor_of(user)
    case = close_case(db, case_id=case_id, actor=actor)
    return {"case": case_out(db, case), "status": case.status}