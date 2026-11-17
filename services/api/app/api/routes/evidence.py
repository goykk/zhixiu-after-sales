"""案例证据账本接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.cases.service import evidence_out, load_case_for_actor
from core.db.base import get_db
from core.db.models import User
from core.diagnosis.evidence import add_evidence, list_evidence
from core.policy.rbac import can
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(tags=["evidence"])


class EvidenceIn(BaseModel):
    source_type: str
    polarity: str
    quote: str
    chunk_id: str | None = None
    page: int = 1
    relevance_score: float = 0.0
    source_ref: str | None = None


@router.post("/cases/{case_id}/evidence", status_code=201)
def create_evidence(
    case_id: str,
    body: EvidenceIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    actor = actor_of(user)
    if not can(actor.role, "evidence:write"):
        raise ApiError(403, "FORBIDDEN", "evidence:write permission required")
    evidence = add_evidence(
        db,
        case_id=case_id,
        actor=actor,
        source_type=body.source_type,
        polarity=body.polarity,
        quote=body.quote,
        chunk_id=body.chunk_id,
        page=body.page,
        relevance_score=body.relevance_score,
        source_ref=body.source_ref,
    )
    return evidence_out(evidence)


@router.get("/cases/{case_id}/evidence")
def get_evidence(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    actor = actor_of(user)
    load_case_for_actor(db, case_id, actor)
    return {"items": [evidence_out(item) for item in list_evidence(db, case_id)]}