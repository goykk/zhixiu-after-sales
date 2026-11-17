"""检查规划与结果回写接口（C-PROBE@1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.cases.service import load_case_for_actor, probe_out
from core.db.base import get_db
from core.diagnosis.hypotheses import list_hypotheses
from core.policy.rbac import can
from core.probes.planner import (
    list_probes,
    plan_next_probe,
    probe_card,
    record_probe_result,
)
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(prefix="/cases", tags=["probes"])


class ProbeResultIn(BaseModel):
    observed_value: str
    source_ref: str | None = None


def _require_probe_write(actor) -> None:
    if not can(actor.role, "probe:write"):
        raise ApiError(403, "FORBIDDEN", "无权限执行检查规划或回写结果")


@router.post("/{case_id}/probes/plan")
def plan_probe(
    case_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    actor = actor_of(user)
    _require_probe_write(actor)
    case = load_case_for_actor(db, case_id, actor)
    probe = plan_next_probe(db, case_id=case_id, actor=actor)
    db.refresh(case)
    if probe is None:
        return {"case_status": str(case.status), "probe": None}
    return {
        "case_status": str(case.status),
        "probe": probe_card(probe, list_hypotheses(db, case_id)),
    }


@router.post("/{case_id}/probes/{probe_id}/result")
def submit_probe_result(
    case_id: str,
    probe_id: str,
    payload: ProbeResultIn,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    actor = actor_of(user)
    _require_probe_write(actor)
    return record_probe_result(
        db,
        case_id=case_id,
        probe_id=probe_id,
        observed_value=payload.observed_value,
        source_ref=payload.source_ref,
        actor=actor,
    )


@router.get("/{case_id}/probes")
def get_probes(
    case_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    actor = actor_of(user)
    load_case_for_actor(db, case_id, actor)
    return {"items": [probe_out(probe) for probe in list_probes(db, case_id)]}