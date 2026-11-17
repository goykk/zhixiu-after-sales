"""维修方案接口（C-REPAIR@1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.cases.service import load_case_for_actor
from core.db.base import get_db
from core.repair.planner import build_repair_plan, latest_repair_plan, repair_plan_out
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(prefix="/cases", tags=["repair"])


@router.post("/{case_id}/repair-plan")
def create_repair_plan(
    case_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    actor = actor_of(user)
    plan = build_repair_plan(db, case_id=case_id, actor=actor)
    return repair_plan_out(plan)


@router.get("/{case_id}/repair-plan")
def get_repair_plan(
    case_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    actor = actor_of(user)
    load_case_for_actor(db, case_id, actor)
    plan = latest_repair_plan(db, case_id)
    if plan is None:
        raise ApiError(404, "REPAIR_PLAN_NOT_FOUND", "repair plan not found")
    return repair_plan_out(plan)