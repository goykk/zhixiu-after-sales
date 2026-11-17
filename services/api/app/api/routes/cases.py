"""C-CASE@1 routes: case creation, listing, detail and intake."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.cases.service import case_detail, case_out, create_case, intake
from core.db.base import get_db
from core.db.models import Case, WorkOrder
from core.policy.rbac import Actor, can, can_access_case
from core.tasks.dispatch import dispatch
from core.tasks.handlers import advance_case_handler
from core.workflow.engine_factory import get_engine
from core.workflow.states import CaseStatus
from services.api.app.api.routes.tasks import (
    TASK_ADVANCE_CASE,
    TaskAcceptedOut,
    async_enabled,
)
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(prefix="/cases", tags=["cases"])


class CaseCreateIn(BaseModel):
    device_model: str = Field(min_length=1)
    symptom: str = Field(min_length=1)
    error_code: str | None = None


class IntakeIn(BaseModel):
    user_text: str = ""


@router.post("", status_code=201)
def create_case_endpoint(
    payload: CaseCreateIn,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> dict:
    case = create_case(
        db,
        user=current_user,
        device_model=payload.device_model.strip(),
        symptom=payload.symptom.strip(),
        error_code=payload.error_code,
    )
    return case_out(db, case)


@router.get("")
def list_cases_endpoint(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> dict:
    actor = actor_of(current_user)
    stmt = select(Case)
    if status:
        try:
            wanted = CaseStatus(str(status).strip().upper()).value
        except ValueError as exc:
            raise ApiError(
                422, "INVALID_STATUS", f"unknown case status: {status}"
            ) from exc
        stmt = stmt.where(Case.status == wanted)
    if not can(actor.role, "case:read_all"):
        stmt = stmt.where(Case.user_id == actor.actor_id)
    stmt = (
        stmt.order_by(Case.created_at.desc(), Case.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    return {"items": [case_out(db, case) for case in rows]}


@router.get("/{case_id}")
def get_case_endpoint(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> dict:
    return case_detail(db, case_id, actor_of(current_user))


@router.post("/{case_id}/intake")
def intake_endpoint(
    case_id: str,
    payload: IntakeIn | None = None,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> dict:
    user_text = payload.user_text if payload is not None else ""
    return intake(db, case_id=case_id, actor=actor_of(current_user), user_text=user_text)

@router.post("/{case_id}/diagnose")
def diagnose_case_endpoint(
    case_id: str,
    response: Response,
    async_: bool = Query(False, alias="async"),
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> dict[str, Any] | TaskAcceptedOut:
    actor = actor_of(current_user)
    case = _require_case_access(db, case_id, actor)
    if async_enabled(async_, endpoint="cases.diagnose"):
        info = dispatch(
            TASK_ADVANCE_CASE,
            {"case_id": case.id},
            owner_id=actor.actor_id,
            sync_handler=lambda: advance_case_handler(db, case.id),
        )
        if info.status == "PENDING":
            response.status_code = 202
            return TaskAcceptedOut(
                task_id=info.task_id, status=info.status, backend=info.backend
            )
        return info.result or {}
    return get_engine(db).advance(case.id)


def _require_case_access(db: Session, case_id: str, actor: Actor) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", "case not found")
    workorder = db.execute(
        select(WorkOrder).where(WorkOrder.case_id == case.id).limit(1)
    ).scalar_one_or_none()
    if not can_access_case(
        actor,
        case_user_id=case.user_id,
        assigned_to=getattr(case, "assigned_to", None),
        workorder_assignee=getattr(workorder, "assignee", None),
    ):
        raise ApiError(403, "FORBIDDEN", "forbidden")
    return case