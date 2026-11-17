"""诊断编排：停止条件、结论生成与诊断汇总（C-DIAG-ORCH@1）。

本模块是状态机进入 `DIAGNOSED` 的唯一入口，结论必须绑定假设的
`support_evidence_ids`，不得只返回模型文本。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from core.cases.service import (
    case_out,
    evidence_out,
    hypothesis_out,
    load_case_for_actor,
    probe_out,
)
from core.db.models import AuditLog, DiagnosticStep, Evidence, Hypothesis, Probe, new_id, utcnow
from core.diagnosis.evidence import list_evidence
from core.diagnosis.hypotheses import list_hypotheses
from core.policy.rbac import Actor, can
from core.probes.planner import list_probes, plan_next_probe
from core.workflow.states import CaseStatus, IllegalTransition, assert_transition
from services.api.app.config import settings
from services.api.app.errors import ApiError

FINALIZABLE_STATUSES: tuple[CaseStatus, ...] = (
    CaseStatus.HYPOTHESIZING,
    CaseStatus.PROBE_PENDING,
)
ROOT_CONFIDENCE_LEVELS = ("high", "medium")


@dataclass(frozen=True)
class DiagnosisResult:
    case_id: str
    case_status: str
    root_cause: Hypothesis | None
    evidence_chain: list[Evidence]
    unresolved: list[str]
    rationale: str


def finalize_diagnosis(db: Session, *, case_id: str, actor: Actor) -> DiagnosisResult:
    """在满足停止条件时定案；否则按 PENDING_PROBE / INSUFFICIENT_EVIDENCE / PROBE_AVAILABLE 拒绝。"""
    if not can(actor.role, "diagnosis:finalize"):
        raise ApiError(403, "FORBIDDEN", "diagnosis:finalize permission required")

    case = load_case_for_actor(db, case_id, actor)
    status = _status_of(case)
    if status is CaseStatus.DIAGNOSED:
        # §2.3：重复定案返回既有结论，不重复落库、不迁移状态。
        return _existing_result(db, case)
    if status not in FINALIZABLE_STATUSES:
        raise ApiError(
            409,
            "ILLEGAL_TRANSITION",
            f"diagnosis requires HYPOTHESIZING or PROBE_PENDING, current status={case.status}",
            {"from": case.status},
        )

    if status is CaseStatus.PROBE_PENDING:
        pending = _pending_probe(db, case_id)
        if pending is not None:
            raise ApiError(
                409,
                "PENDING_PROBE",
                "a planned probe is still pending; submit its result first",
                {"probe_id": pending.id, "code": pending.code},
            )
        # PROBE_PENDING 无法直达 DIAGNOSED，先按状态机退回假设阶段。
        _transition(case, CaseStatus.HYPOTHESIZING)

    hypotheses = list_hypotheses(db, case_id)
    root_cause = _select_root_cause(hypotheses)
    if root_cause is None:
        raise ApiError(
            409,
            "INSUFFICIENT_EVIDENCE",
            "no root cause reaches supported with high/medium confidence",
            {
                "hypotheses": [
                    {
                        "cause_code": item.cause_code,
                        "status": item.status,
                        "confidence_level": item.confidence_level,
                    }
                    for item in hypotheses
                ]
            },
        )

    open_hypotheses = [item for item in hypotheses if item.status == "open"]
    step_count = int(case.step_count or 0)
    if open_hypotheses and step_count < settings.max_probe_steps:
        # 规划器只在存在可执行且有区分度的检查时返回 Probe；此时应先把检查做完。
        probe = plan_next_probe(db, case_id=case_id, actor=actor)
        if probe is not None:
            raise ApiError(
                409,
                "PROBE_AVAILABLE",
                "a more discriminative probe is available before concluding",
                {"probe_id": probe.id, "code": probe.code, "case_status": case.status},
            )

    _transition(case, CaseStatus.DIAGNOSED)
    evidence_chain = _evidence_chain(db, case_id, root_cause)
    unresolved = [item.label for item in hypotheses if item.status != "supported"]
    rationale = _build_rationale(
        case=case,
        hypotheses=hypotheses,
        root_cause=root_cause,
        evidence_chain=evidence_chain,
        unresolved=unresolved,
    )

    payload = {
        "case_id": case.id,
        "error_code": case.error_code,
        "cause_code": root_cause.cause_code,
        "confidence_level": root_cause.confidence_level,
        "confidence_score": root_cause.confidence_score,
        "evidence_ids": [item.id for item in evidence_chain],
        "case_status": case.status,
    }
    db.add(
        DiagnosticStep(
            id=new_id(),
            case_id=case.id,
            step_type="diagnosis_finalized",
            input={
                "error_code": case.error_code,
                "step_count": step_count,
                "hypothesis_count": len(hypotheses),
            },
            output={
                "cause_code": root_cause.cause_code,
                "confidence_level": root_cause.confidence_level,
                "evidence_ids": payload["evidence_ids"],
                "unresolved": unresolved,
            },
        )
    )
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=actor.actor_id,
            action="case.diagnosed",
            resource_id=case.id,
            payload_hash=_payload_hash(payload),
            payload=payload,
        )
    )
    case.updated_at = utcnow()
    db.commit()

    return DiagnosisResult(
        case_id=case.id,
        case_status=case.status,
        root_cause=root_cause,
        evidence_chain=evidence_chain,
        unresolved=unresolved,
        rationale=rationale,
    )


def diagnosis_summary(db: Session, *, case_id: str, actor: Actor) -> dict:
    """返回案例、证据账本、候选根因、检查与当前根因证据链的汇总视图。"""
    case = load_case_for_actor(db, case_id, actor)
    evidence = list_evidence(db, case_id)
    hypotheses = list_hypotheses(db, case_id)
    probes = list_probes(db, case_id)
    root_cause = _best_supported(hypotheses)
    evidence_chain = _chain_of(evidence, root_cause)
    return {
        "case": case_out(db, case),
        "evidence": [evidence_out(item) for item in evidence],
        "hypotheses": [hypothesis_out(item) for item in hypotheses],
        "probes": [probe_out(item) for item in probes],
        "root_cause": hypothesis_out(root_cause) if root_cause is not None else None,
        "evidence_chain": [evidence_out(item) for item in evidence_chain],
    }


def _status_of(case) -> CaseStatus | None:
    try:
        return CaseStatus(case.status)
    except ValueError:
        return None


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


def _pending_probe(db: Session, case_id: str) -> Probe | None:
    return (
        db.query(Probe)
        .filter(Probe.case_id == case_id, Probe.status == "pending")
        .order_by(Probe.created_at.asc())
        .first()
    )


def _select_root_cause(hypotheses: list[Hypothesis]) -> Hypothesis | None:
    candidates = [
        item
        for item in hypotheses
        if item.status == "supported" and item.confidence_level in ROOT_CONFIDENCE_LEVELS
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.confidence_score or 0.0, item.cause_code))


def _best_supported(hypotheses: list[Hypothesis]) -> Hypothesis | None:
    candidates = [item for item in hypotheses if item.status == "supported"]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.confidence_score or 0.0, item.cause_code))


def _existing_result(db: Session, case) -> DiagnosisResult:
    """已定案案例的幂等返回：按当前 supported 最高分假设重建既有结论。"""
    hypotheses = list_hypotheses(db, case.id)
    root_cause = _best_supported(hypotheses)
    evidence_chain = _chain_of(list_evidence(db, case.id), root_cause)
    unresolved = [item.label for item in hypotheses if item.status != "supported"]
    if root_cause is None:
        rationale = "案例已处于 DIAGNOSED，但未找到 supported 假设（already_diagnosed）。"
    else:
        rationale = (
            _build_rationale(
                case=case,
                hypotheses=hypotheses,
                root_cause=root_cause,
                evidence_chain=evidence_chain,
                unresolved=unresolved,
            )
            + "（already_diagnosed：返回既有结论，未重复落库）"
        )
    return DiagnosisResult(
        case_id=case.id,
        case_status=case.status,
        root_cause=root_cause,
        evidence_chain=evidence_chain,
        unresolved=unresolved,
        rationale=rationale,
    )


def _chain_of(evidence: list[Evidence], root_cause: Hypothesis | None) -> list[Evidence]:
    if root_cause is None:
        return []
    support_ids = set(root_cause.support_evidence_ids or [])
    return [item for item in evidence if item.id in support_ids]


def _evidence_chain(db: Session, case_id: str, root_cause: Hypothesis) -> list[Evidence]:
    return _chain_of(list_evidence(db, case_id), root_cause)


def _build_rationale(
    *,
    case,
    hypotheses: list[Hypothesis],
    root_cause: Hypothesis,
    evidence_chain: list[Evidence],
    unresolved: list[str],
) -> str:
    sources = sorted({item.source_type for item in evidence_chain})
    unresolved_text = "、".join(unresolved) if unresolved else "无"
    return (
        f"故障码 {case.error_code or '未提供'}；"
        f"根因 {root_cause.label}（{root_cause.cause_code}）"
        f"达到 {root_cause.confidence_level} 置信级别，"
        f"依据 {len(evidence_chain)} 条支持证据"
        f"（来源：{'、'.join(sources) if sources else '无'}；"
        f"证据版本 {root_cause.evidence_version}），"
        f"共 {len(hypotheses)} 个候选根因中未解决：{unresolved_text}；"
        f"已执行检查 {int(case.step_count or 0)} 步，无更高增益的安全检查。"
    )


def _payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()