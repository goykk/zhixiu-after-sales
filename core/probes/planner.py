"""主动证据规划与结果回写（C-PROBE@1）。

规划是确定性的：硬过滤 → 信息增益评分 → 按分数降序、code 升序选一个。
唯一约束 `(case_id, code)` 保证同一检查不会被重复推荐。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select

from core.cases.service import hypothesis_out, load_case_for_actor, probe_out
from core.db.models import (
    AuditLog,
    DiagnosticStep,
    Evidence,
    Hypothesis,
    Probe,
    ProbeResult,
    new_id,
    utcnow,
)
from core.diagnosis.hypotheses import apply_evidence, list_hypotheses
from core.policy.rbac import Actor
from core.probes.catalog import PROBE_CATALOG, ProbeSpec
from core.workflow.states import CaseStatus, assert_transition
from services.api.app.config import settings
from services.api.app.errors import ApiError

COST_PENALTY = {"low": 0.1, "medium": 0.3, "high": 0.6}
RISK_PENALTY = {"low": 0.0, "medium": 0.2, "high": 1.0}

HYPOTHESIZING = CaseStatus.HYPOTHESIZING.value
PROBE_PENDING = CaseStatus.PROBE_PENDING.value
PROBE_EVALUATING = CaseStatus.PROBE_EVALUATING.value
NEED_HUMAN = CaseStatus.NEED_HUMAN.value


def _normalize(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _fault_code(case) -> str:
    return (case.error_code or "").strip().upper()


def _payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _add_audit(db, *, actor: Actor, action: str, case_id: str, payload: dict) -> None:
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=actor.actor_id,
            action=action,
            resource_id=case_id,
            payload_hash=_payload_hash(payload),
            payload=payload,
            created_at=utcnow(),
        )
    )


def _add_step(
    db, *, case_id: str, step_type: str, input_data: dict, output: dict
) -> None:
    db.add(
        DiagnosticStep(
            id=new_id(),
            case_id=case_id,
            step_type=step_type,
            input=input_data,
            output=output,
            created_at=utcnow(),
        )
    )


def _evaluate(spec: ProbeSpec) -> tuple[float, float]:
    n = len(spec.targets)
    gain = (n * (n - 1) / 2) * spec.coverage * spec.success_rate
    score = (
        gain
        - COST_PENALTY.get(spec.cost_level, COST_PENALTY["medium"])
        - RISK_PENALTY.get(spec.risk_level, RISK_PENALTY["medium"])
    )
    return score, gain


def _clone_outcomes(outcomes: dict[str, dict]) -> dict[str, dict]:
    return {
        key: {
            "supports": list(value.get("supports") or []),
            "refutes": list(value.get("refutes") or []),
        }
        for key, value in outcomes.items()
    }


def _case_hypotheses(db, case_id: str) -> list[Hypothesis]:
    return list(
        db.scalars(
            select(Hypothesis)
            .where(Hypothesis.case_id == case_id)
            .order_by(Hypothesis.confidence_score.desc())
        )
    )


def plan_next_probe(db, *, case_id: str, actor: Actor) -> Probe | None:
    case = load_case_for_actor(db, case_id, actor)
    status = str(case.status)
    if status not in {HYPOTHESIZING, PROBE_PENDING}:
        raise ApiError(
            409,
            "ILLEGAL_TRANSITION",
            f"当前状态 {status} 不允许规划检查",
            {"from": status, "allowed": [HYPOTHESIZING, PROBE_PENDING]},
        )

    if status == PROBE_PENDING:
        pending = db.scalar(
            select(Probe).where(Probe.case_id == case_id, Probe.status == "pending")
        )
        if pending is not None:
            return pending

    specs = PROBE_CATALOG.get(_fault_code(case), ())
    executed_codes = set(db.scalars(select(Probe.code).where(Probe.case_id == case_id)))
    hypotheses = _case_hypotheses(db, case_id)
    active_causes = {h.cause_code for h in hypotheses if h.status != "rejected"}

    scored: list[tuple[ProbeSpec, float, float]] = []
    alternatives: list[dict] = []
    for spec in specs:
        if spec.risk_level == "high":
            alternatives.append({"code": spec.code, "reason": "HIGH_RISK"})
            continue
        if spec.code in executed_codes:
            alternatives.append({"code": spec.code, "reason": "ALREADY_EXECUTED"})
            continue
        if spec.required_tools:
            alternatives.append(
                {
                    "code": spec.code,
                    "reason": "MISSING_TOOL",
                    "required_tools": list(spec.required_tools),
                }
            )
            continue
        if not set(spec.targets) & active_causes:
            alternatives.append({"code": spec.code, "reason": "NO_ACTIVE_TARGET"})
            continue
        score, gain = _evaluate(spec)
        scored.append((spec, score, gain))

    if not scored:
        _add_step(
            db,
            case_id=case_id,
            step_type="probe_exhausted",
            input_data={"fault_code": _fault_code(case)},
            output={"alternatives": alternatives},
        )
        db.commit()
        return None

    spec, score, gain = sorted(scored, key=lambda item: (-item[1], item[0].code))[0]
    targets = list(spec.targets)
    rationale: dict[str, Any] = {
        "why": (
            f"该检查可区分 {'、'.join(targets)}；"
            f"信息增益 {gain:.2f}，成本 {spec.cost_level}，风险 {spec.risk_level}"
        ),
        "alternatives": alternatives,
        "targets": targets,
    }
    probe = Probe(
        id=new_id(),
        case_id=case_id,
        code=spec.code,
        probe_type=spec.probe_type,
        question=spec.question,
        target_hypotheses=targets,
        expected_outcomes=_clone_outcomes(spec.expected_outcomes),
        cost_level=spec.cost_level,
        risk_level=spec.risk_level,
        status="pending",
        score=score,
        rationale=rationale,
        created_at=utcnow(),
    )
    db.add(probe)

    if status == HYPOTHESIZING:
        assert_transition(status, PROBE_PENDING)
        case.status = PROBE_PENDING

    _add_step(
        db,
        case_id=case_id,
        step_type="probe_planned",
        input_data={
            "fault_code": _fault_code(case),
            "active_causes": sorted(active_causes),
            "candidates": [
                {"code": item[0].code, "score": item[1]}
                for item in sorted(scored, key=lambda item: (-item[1], item[0].code))
            ],
        },
        output={"probe_id": probe.id, "code": spec.code, "score": score},
    )
    _add_audit(
        db,
        actor=actor,
        action="probe.planned",
        case_id=case_id,
        payload={"probe_id": probe.id, "code": spec.code, "score": score},
    )
    db.commit()
    db.refresh(probe)
    return probe


def probe_card(probe: Probe, hypotheses: list[Hypothesis]) -> dict:
    labels = {h.cause_code: h.label for h in hypotheses}
    targets = list(probe.target_hypotheses or [])
    return {
        "probe_id": probe.id,
        "code": probe.code,
        "probe_type": probe.probe_type,
        "question": probe.question,
        "target_labels": [labels.get(code, code) for code in targets],
        "expected_outcomes": probe.expected_outcomes or {},
        "cost_level": probe.cost_level,
        "risk_level": probe.risk_level,
        "score": probe.score,
        "rationale": probe.rationale or {},
    }


def record_probe_result(
    db,
    *,
    case_id: str,
    probe_id: str,
    observed_value: str,
    source_ref: str | None,
    actor: Actor,
) -> dict:
    case = load_case_for_actor(db, case_id, actor)
    probe = db.get(Probe, probe_id)
    if probe is None or probe.case_id != case_id:
        raise ApiError(404, "NOT_FOUND", "检查不存在", {"probe_id": probe_id})

    case_status = str(case.status)
    if probe.status != "pending" or case_status != PROBE_PENDING:
        raise ApiError(
            409,
            "PROBE_NOT_PENDING",
            "该检查不在待执行状态或案例状态不允许回写结果",
            {"probe_status": probe.status, "case_status": case_status},
        )

    observed = (observed_value or "").strip()
    if not observed:
        raise ApiError(422, "INVALID_OBSERVATION", "观察值不能为空")

    expected = probe.expected_outcomes or {}
    matched_key = next(
        (key for key in expected if _normalize(key) == _normalize(observed)), None
    )
    if matched_key is None:
        raise ApiError(
            422,
            "INVALID_OBSERVATION",
            "观察值不匹配该检查的任何预期结果",
            {"observed_value": observed, "expected_outcomes": sorted(expected)},
        )

    outcome = expected[matched_key] or {}
    supports = list(outcome.get("supports") or [])
    refutes = list(outcome.get("refutes") or [])
    if supports:
        polarity, cause_codes = "support", supports
    elif refutes:
        polarity, cause_codes = "refute", refutes
    else:
        polarity, cause_codes = "neutral", None

    try:
        now = utcnow()
        db.add(
            ProbeResult(
                id=new_id(),
                probe_id=probe.id,
                observed_value=observed,
                source_ref=source_ref,
                created_at=now,
            )
        )
        probe.status = "done"
        probe.executed_at = now

        evidence = Evidence(
            id=new_id(),
            case_id=case_id,
            source_type="probe",
            polarity=polarity,
            quote=f"{probe.question} → {observed}",
            source_ref=probe.id,
            observed_at=now,
            created_at=now,
        )
        db.add(evidence)
        db.flush()

        if cause_codes:
            apply_evidence(
                db, case_id=case_id, evidence=evidence, cause_codes=cause_codes
            )

        case.evidence_version = (case.evidence_version or 0) + 1
        case.step_count = (case.step_count or 0) + 1

        assert_transition(PROBE_PENDING, PROBE_EVALUATING)
        case.status = PROBE_EVALUATING
        assert_transition(PROBE_EVALUATING, HYPOTHESIZING)
        case.status = HYPOTHESIZING

        needs_human = False
        if (case.step_count or 0) >= settings.max_probe_steps:
            assert_transition(HYPOTHESIZING, NEED_HUMAN)
            case.status = NEED_HUMAN
            needs_human = True

        _add_step(
            db,
            case_id=case_id,
            step_type="probe_result",
            input_data={
                "probe_id": probe.id,
                "observed_value": observed,
                "source_ref": source_ref,
            },
            output={
                "matched_outcome": matched_key,
                "polarity": polarity,
                "cause_codes": cause_codes or [],
                "step_count": case.step_count,
                "needs_human": needs_human,
            },
        )
        _add_audit(
            db,
            actor=actor,
            action="probe.result",
            case_id=case_id,
            payload={
                "probe_id": probe.id,
                "code": probe.code,
                "observed_value": observed,
                "polarity": polarity,
                "cause_codes": cause_codes or [],
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(probe)
    hypotheses = list_hypotheses(db, case_id)
    return {
        "probe": probe_out(probe),
        "hypotheses": [hypothesis_out(h) for h in hypotheses],
        "case_status": str(case.status),
        "needs_human": needs_human,
    }


def list_probes(db, case_id: str) -> list[Probe]:
    return list(
        db.scalars(
            select(Probe)
            .where(Probe.case_id == case_id)
            .order_by(Probe.created_at.asc(), Probe.code.asc())
        )
    )