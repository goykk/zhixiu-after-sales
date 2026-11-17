"""诊断编排接口：结论生成与诊断汇总（C-DIAG-ORCH@1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.cases.service import evidence_out, hypothesis_out
from core.db.base import get_db
from core.db.models import User
from core.diagnosis.orchestrator import diagnosis_summary, finalize_diagnosis
from services.api.app.deps import actor_of, get_current_user

router = APIRouter(tags=["diagnosis"])


@router.post("/cases/{case_id}/finalize-diagnosis")
def finalize_case_diagnosis(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    actor = actor_of(user)
    result = finalize_diagnosis(db, case_id=case_id, actor=actor)
    return {
        "case_id": result.case_id,
        "case_status": result.case_status,
        "root_cause": hypothesis_out(result.root_cause) if result.root_cause else None,
        "evidence_chain": [evidence_out(item) for item in result.evidence_chain],
        "unresolved": result.unresolved,
        "rationale": result.rationale,
    }


@router.get("/cases/{case_id}/diagnosis")
def get_case_diagnosis(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    actor = actor_of(user)
    return diagnosis_summary(db, case_id=case_id, actor=actor)