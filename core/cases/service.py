"""C-CASE@1: case use-cases — creation, intake and serialisation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import Select, select

from core.ai.factory import get_llm, get_ocr
from core.db.models import (
    AuditLog,
    Case,
    Device,
    DiagnosticStep,
    Evidence,
    Hypothesis,
    Probe,
    WorkOrder,
    new_id,
    utcnow,
)
from core.devices import find_device_by_model
from core.multimodal.extract import extract_fields
from core.multimodal.uploads import Upload
from core.policy.rbac import Actor, can, can_access_case
from core.workflow.states import (
    ALLOWED_TRANSITIONS,
    CaseStatus,
    assert_transition,
    coerce_status,
)
from services.api.app.errors import ApiError

_MISSING_LABELS = {
    "device_model": "设备型号",
    "error_code": "故障码",
    "symptom": "故障现象",
}


def _actor(value: Any) -> Actor:
    if isinstance(value, Actor):
        return value
    actor_id = getattr(value, "actor_id", None) or getattr(value, "id", None)
    return Actor(actor_id, getattr(value, "role", None))


def _status_value(value: CaseStatus | str) -> str:
    return value.value if isinstance(value, CaseStatus) else str(value)


def _device_model_name(device: Any) -> str | None:
    if device is None:
        return None
    brand = (getattr(device, "brand", "") or "").strip()
    model = (getattr(device, "model", "") or "").strip()
    if not brand or not model or model.lower().startswith(brand.lower()):
        return model or None
    return f"{brand} {model}".strip() or None


def _normalise_error_code(code: str | None) -> str | None:
    if not code:
        return None
    text = str(code).strip().upper()
    return text or None


def _write_audit(db: Any, actor: Actor, action: str, resource_id: str, payload: dict) -> None:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8"))
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=actor.actor_id,
            action=action,
            resource_id=resource_id,
            payload_hash=digest.hexdigest(),
            payload=payload,
        )
    )


def _for_update(db: Any, stmt: Select) -> Select:
    if db.get_bind().dialect.name == "sqlite":
        return stmt
    return stmt.with_for_update()


def _lock_case(db: Any, case_id: str) -> Case:
    stmt = _for_update(db, select(Case).where(Case.id == case_id))
    case = db.execute(stmt).scalar_one_or_none()
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", "case not found")
    return case


def _ensure_access(db: Any, case: Case, actor: Actor) -> None:
    workorder = db.execute(
        select(WorkOrder).where(WorkOrder.case_id == case.id).limit(1)
    ).scalar_one_or_none()
    workorder_assignee = getattr(workorder, "assignee", None) if workorder is not None else None
    if not can_access_case(
        actor,
        case_user_id=case.user_id,
        assigned_to=getattr(case, "assigned_to", None),
        workorder_assignee=workorder_assignee,
    ):
        raise ApiError(403, "FORBIDDEN", "forbidden")


def _advance(case: Case, target: CaseStatus) -> bool:
    try:
        current = coerce_status(case.status)
    except ValueError as exc:
        raise ApiError(
            409, "ILLEGAL_TRANSITION", f"unknown case status: {case.status}"
        ) from exc
    if current == target or target not in ALLOWED_TRANSITIONS[current]:
        return False
    assert_transition(current, target)
    case.status = target.value
    return True


def _case_uploads(db: Any, case_id: str) -> list[Upload]:
    stmt = (
        select(Upload)
        .where(Upload.case_id == case_id)
        .order_by(Upload.created_at.asc(), Upload.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def _merge_user_text(device: Any, symptom: str | None, user_text: str) -> str:
    parts: list[str] = []
    model_name = _device_model_name(device)
    if model_name:
        parts.append(f"型号 {model_name}")
    if symptom:
        parts.append(symptom)
    if user_text:
        parts.append(user_text)
    return "\n".join(parts)


def _missing_fields(device: Any, case: Case) -> list[str]:
    missing: list[str] = []
    if device is None:
        missing.append("device_model")
    if not case.error_code:
        missing.append("error_code")
    if not case.symptom:
        missing.append("symptom")
    return missing


def _last_question(missing: list[str], needs_human: bool) -> str | None:
    if missing:
        labels = "、".join(_MISSING_LABELS.get(key, key) for key in missing)
        return f"请补充{labels}，以便继续诊断。"
    if needs_human:
        return "自动识别置信度不足，请人工确认设备型号与故障现象。"
    return None


def create_case(
    db: Any,
    *,
    user: Any,
    device_model: str,
    symptom: str,
    error_code: str | None = None,
) -> Case:
    actor = _actor(user)
    if not can(actor.role, "case:write"):
        raise ApiError(403, "FORBIDDEN", "forbidden")

    device = find_device_by_model(db, device_model)
    case = Case(
        id=new_id(),
        user_id=actor.actor_id,
        device_id=getattr(device, "id", None),
        status=CaseStatus.DRAFT.value,
        symptom=symptom,
        error_code=_normalise_error_code(error_code),
        extracted=None,
        confidence=None,
        risk_level=None,
        step_count=0,
        evidence_version=0,
        missing_fields=[],
        last_question=None,
    )
    db.add(case)
    db.flush()
    _write_audit(
        db,
        actor,
        "case.created",
        case.id,
        {"device_model": device_model, "error_code": case.error_code},
    )
    db.commit()
    db.refresh(case)
    return case


def get_case(db: Any, case_id: str) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", "case not found")
    return case


def load_case_for_actor(db: Any, case_id: str, actor: Any) -> Case:
    case = get_case(db, case_id)
    _ensure_access(db, case, _actor(actor))
    return case


def intake(db: Any, *, case_id: str, actor: Any, user_text: str = "") -> dict:
    actor_obj = _actor(actor)
    case = _lock_case(db, case_id)
    _ensure_access(db, case, actor_obj)

    uploads = _case_uploads(db, case.id)
    device = db.get(Device, case.device_id) if case.device_id else None
    merged_text = _merge_user_text(device, case.symptom, user_text)

    fields = extract_fields(
        db, uploads, ocr=get_ocr(), llm=get_llm(), user_text=merged_text
    )

    if getattr(fields, "device_model", None):
        matched = find_device_by_model(db, fields.device_model)
        if matched is not None:
            case.device_id = getattr(matched, "id", case.device_id)
            device = matched
    needs_human = bool(getattr(fields, "needs_human", False)) or device is None

    if getattr(fields, "symptom", None):
        case.symptom = fields.symptom
    if getattr(fields, "error_code", None):
        case.error_code = _normalise_error_code(fields.error_code)
    case.extracted = asdict(fields)
    missing = _missing_fields(device, case)
    case.missing_fields = missing
    case.last_question = _last_question(missing, needs_human)
    case.updated_at = utcnow()

    target = CaseStatus.NEED_HUMAN if needs_human else CaseStatus.COLLECTING_INFO
    _advance(case, target)

    db.add(
        DiagnosticStep(
            id=new_id(),
            case_id=case.id,
            step_type="intake",
            input={"user_text": user_text, "upload_ids": [u.id for u in uploads]},
            output={
                "needs_human": needs_human,
                "missing_fields": missing,
                "status": _status_value(case.status),
            },
        )
    )
    _write_audit(
        db,
        actor_obj,
        "case.intake",
        case.id,
        {
            "status": _status_value(case.status),
            "needs_human": needs_human,
            "missing_fields": missing,
            "device_id": case.device_id,
        },
    )
    db.commit()
    db.refresh(case)
    return {
        "case": case_out(db, case),
        "extracted": asdict(fields),
        "needs_human": needs_human,
    }


def case_out(db: Any, case: Case) -> dict:
    device = db.get(Device, case.device_id) if case.device_id else None
    return {
        "id": case.id,
        "user_id": case.user_id,
        "device_id": case.device_id,
        "device_model": _device_model_name(device),
        "status": _status_value(case.status),
        "symptom": case.symptom,
        "error_code": case.error_code,
        "confidence": case.confidence,
        "risk_level": case.risk_level,
        "step_count": case.step_count,
        "evidence_version": case.evidence_version,
        "missing_fields": list(case.missing_fields or []),
        "last_question": case.last_question,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


def evidence_out(evidence: Evidence) -> dict:
    return {
        "id": evidence.id,
        "case_id": evidence.case_id,
        "chunk_id": evidence.chunk_id,
        "source_type": evidence.source_type,
        "polarity": evidence.polarity,
        "quote": evidence.quote,
        "page": evidence.page,
        "relevance_score": evidence.relevance_score,
        "source_ref": evidence.source_ref,
        "observed_at": evidence.observed_at,
        "created_at": evidence.created_at,
    }


def hypothesis_out(hypothesis: Hypothesis) -> dict:
    return {
        "id": hypothesis.id,
        "cause_code": hypothesis.cause_code,
        "label": hypothesis.label,
        "status": hypothesis.status,
        "confidence_level": hypothesis.confidence_level,
        "confidence_score": hypothesis.confidence_score,
        "evidence_version": hypothesis.evidence_version,
        "support_evidence_ids": list(hypothesis.support_evidence_ids or []),
        "refute_evidence_ids": list(hypothesis.refute_evidence_ids or []),
        "rationale": hypothesis.rationale,
        "updated_at": hypothesis.updated_at,
    }


def probe_out(probe: Probe) -> dict:
    return {
        "id": probe.id,
        "code": probe.code,
        "probe_type": probe.probe_type,
        "question": probe.question,
        "status": probe.status,
        "cost_level": probe.cost_level,
        "risk_level": probe.risk_level,
        "score": probe.score,
        "rationale": probe.rationale,
        "executed_at": probe.executed_at,
        "created_at": probe.created_at,
    }


def _step_out(step: DiagnosticStep) -> dict:
    return {
        "id": step.id,
        "case_id": step.case_id,
        "step_type": step.step_type,
        "input": step.input,
        "output": step.output,
        "created_at": step.created_at,
    }


def _upload_out(upload: Upload) -> dict:
    return {
        "id": upload.id,
        "case_id": upload.case_id,
        "filename": upload.filename,
        "content_type": upload.content_type,
        "size": upload.size,
        "sha256": upload.sha256,
        "object_key": upload.object_key,
        "status": upload.status,
        "created_at": upload.created_at,
    }


def case_detail(db: Any, case_id: str, actor: Any) -> dict:
    case = load_case_for_actor(db, case_id, actor)

    evidence = db.execute(
        select(Evidence)
        .where(Evidence.case_id == case.id)
        .order_by(Evidence.created_at.asc(), Evidence.id.asc())
    ).scalars()
    hypotheses = db.execute(
        select(Hypothesis)
        .where(Hypothesis.case_id == case.id)
        .order_by(Hypothesis.confidence_score.desc(), Hypothesis.cause_code.asc())
    ).scalars()
    probes = db.execute(
        select(Probe)
        .where(Probe.case_id == case.id)
        .order_by(Probe.created_at.asc(), Probe.id.asc())
    ).scalars()
    steps = db.execute(
        select(DiagnosticStep)
        .where(DiagnosticStep.case_id == case.id)
        .order_by(DiagnosticStep.created_at.asc(), DiagnosticStep.id.asc())
    ).scalars()

    return {
        "case": case_out(db, case),
        "evidence": [evidence_out(e) for e in evidence],
        "hypotheses": [hypothesis_out(h) for h in hypotheses],
        "probes": [probe_out(p) for p in probes],
        "steps": [_step_out(s) for s in steps],
        "uploads": [_upload_out(u) for u in _case_uploads(db, case.id)],
    }