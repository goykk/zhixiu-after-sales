"""候选根因与假设接口（C-HYPOTHESIS@1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.cases.service import hypothesis_out, load_case_for_actor
from core.db.base import get_db
from core.diagnosis.hypotheses import generate_hypotheses, list_hypotheses
from core.policy.rbac import can
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(tags=["hypotheses"])


def _role_value(role):
    return getattr(role, "value", role)


def _has_hypothesis_write(role) -> bool:
    value = _role_value(role)
    for candidate in (role, value):
        try:
            if can(candidate, "hypothesis:write"):
                return True
        except (KeyError, TypeError, AttributeError):
            continue
    return False


def _require_owner_or_writer(case, actor) -> None:
    if case.user_id != actor.actor_id and not _has_hypothesis_write(actor.role):
        raise ApiError(403, "FORBIDDEN", "hypothesis write not permitted")


@router.post("/cases/{case_id}/hypotheses/generate")
def generate_case_hypotheses(
    case_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    actor = actor_of(user)
    case = load_case_for_actor(db, case_id, actor)
    _require_owner_or_writer(case, actor)
    items = generate_hypotheses(db, case_id=case_id, actor=actor)
    return {"case_status": case.status, "items": [hypothesis_out(item) for item in items]}


@router.get("/cases/{case_id}/hypotheses")
def list_case_hypotheses(
    case_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    actor = actor_of(user)
    load_case_for_actor(db, case_id, actor)
    return {"items": [hypothesis_out(item) for item in list_hypotheses(db, case_id)]}