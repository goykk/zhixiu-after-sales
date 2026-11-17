"""证据账本：来源/极性/冲突保留的证据写入与查询。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.cases.service import load_case_for_actor
from core.db.models import AuditLog, DiagnosticStep, Evidence, new_id, utcnow
from core.policy.rbac import Actor
from core.workflow.states import CaseStatus, IllegalTransition, assert_transition
from services.api.app.errors import ApiError

SOURCE_TYPES: tuple[str, ...] = ("customer", "media", "manual", "probe", "model")
POLARITIES: tuple[str, ...] = ("support", "refute", "neutral")


def add_evidence(
    db: Session,
    *,
    case_id: str,
    actor: Actor,
    source_type: str,
    polarity: str,
    quote: str,
    chunk_id: str | None = None,
    page: int = 1,
    relevance_score: float = 0.0,
    source_ref: str | None = None,
    observed_at: datetime | None = None,
) -> Evidence:
    """追加一条证据，不做去重/覆盖，并推进案例到 EVIDENCE_READY。"""
    _validate(source_type=source_type, polarity=polarity, quote=quote)
    case = load_case_for_actor(db, case_id, actor)

    try:
        _advance_to_evidence_ready(case)

        payload = {
            "case_id": case.id,
            "source_type": source_type,
            "polarity": polarity,
            "quote": quote.strip(),
            "chunk_id": chunk_id,
            "page": page,
            "relevance_score": relevance_score,
            "source_ref": source_ref,
            "case_status": case.status,
        }
        evidence = Evidence(
            id=new_id(),
            case_id=case.id,
            chunk_id=chunk_id,
            source_type=source_type,
            polarity=polarity,
            quote=payload["quote"],
            page=page,
            relevance_score=relevance_score,
            source_ref=source_ref,
            observed_at=observed_at or utcnow(),
        )
        db.add(evidence)
        db.add(
            DiagnosticStep(
                id=new_id(),
                case_id=case.id,
                step_type="evidence",
                input={
                    "source_type": source_type,
                    "polarity": polarity,
                    "quote": payload["quote"],
                    "chunk_id": chunk_id,
                },
                output={"evidence_id": evidence.id, "case_status": case.status},
            )
        )
        db.add(
            AuditLog(
                id=new_id(),
                actor_id=actor.actor_id,
                action="evidence.added",
                resource_id=case.id,
                payload_hash=_payload_hash(payload),
                payload=payload,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(evidence)
    return evidence


def list_evidence(db: Session, case_id: str) -> list[Evidence]:
    stmt = (
        select(Evidence)
        .where(Evidence.case_id == case_id)
        .order_by(Evidence.created_at.asc(), Evidence.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def _validate(*, source_type: str, polarity: str, quote: str) -> None:
    if source_type not in SOURCE_TYPES:
        raise ApiError(
            422,
            "INVALID_EVIDENCE",
            f"source_type must be one of {SOURCE_TYPES}",
            {"source_type": source_type},
        )
    if polarity not in POLARITIES:
        raise ApiError(
            422,
            "INVALID_EVIDENCE",
            f"polarity must be one of {POLARITIES}",
            {"polarity": polarity},
        )
    if not isinstance(quote, str) or not quote.strip():
        raise ApiError(422, "INVALID_EVIDENCE", "quote must be a non-empty string")


def _advance_to_evidence_ready(case) -> None:
    try:
        status = CaseStatus(case.status)
    except ValueError:
        return
    if status is CaseStatus.DRAFT:
        _transition(case, CaseStatus.COLLECTING_INFO)
        status = CaseStatus.COLLECTING_INFO
    if status is CaseStatus.COLLECTING_INFO:
        _transition(case, CaseStatus.EVIDENCE_READY)


def _transition(case, to_status: CaseStatus) -> None:
    try:
        assert_transition(case.status, to_status)
    except IllegalTransition as exc:
        raise ApiError(
            409,
            "ILLEGAL_TRANSITION",
            f"cannot move case from {exc.from_status} to {exc.to_status}",
            {"from": str(exc.from_status), "to": str(exc.to_status)},
        ) from exc
    case.status = to_status.value


def _payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()