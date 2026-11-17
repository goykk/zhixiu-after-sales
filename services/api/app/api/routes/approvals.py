"""维修方案提交审批与审批决定接口（C-APPROVAL@1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.cases.service import case_out, load_case_for_actor
from core.db.base import get_db
from core.db.models import User
from core.policy.approval import (
    approval_out,
    list_approvals,
    record_approval,
    submit_approval,
)
from core.policy.rbac import Actor, can
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(prefix="/cases", tags=["approvals"])


class ApprovalIn(BaseModel):
    decision: str
    reason: str | None = None


def _require(actor: Actor, action: str, message: str) -> None:
    if not can(actor.role, action):
        raise ApiError(403, "FORBIDDEN", message)


@router.post("/{case_id}/submit-approval")
def submit_case_approval(
    case_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    actor = actor_of(user)
    _require(actor, "repair:write", "无权限提交维修方案审批")
    case = submit_approval(db, case_id=case_id, actor=actor)
    return {"case": case_out(db, case), "status": str(case.status)}


@router.post("/{case_id}/approvals")
def decide_case_approval(
    case_id: str,
    payload: ApprovalIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    actor = actor_of(user)
    _require(actor, "approval:decide", "无权限审批维修方案")
    approval = record_approval(
        db,
        case_id=case_id,
        approver_id=actor.actor_id,
        decision=payload.decision,
        reason=payload.reason or "",
    )
    case = load_case_for_actor(db, case_id, actor)
    return {"case": case_out(db, case), "approval": approval_out(approval)}


@router.get("/{case_id}/approvals")
def get_case_approvals(
    case_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    actor = actor_of(user)
    load_case_for_actor(db, case_id, actor)
    return {"items": [approval_out(item) for item in list_approvals(db, case_id)]}