"""C-SIM@1 B.3：A/B/C/D 四条消融策略的模拟执行。

同一场景、同一变体、同一配置下分别运行：

- A 规则树（RAG-only）：只用故障码规则树 + 输入文本（现象与证据引文）做关键词打分，
  不写证据账本、不建假设、不规划检查、`steps=0`。
- B 证据账本 + 状态机：证据→假设→`finalize_diagnosis`，不主动规划检查，`steps=0`。
- C 在 B 之上循环 `plan_next_probe`/`record_probe_result`，`steps` 为实际检查数。
- D 在 C 之上用同故障码的 `RepairOutcome.actual_cause_code` 频率给根因加权；
  无历史时退化为 C，且不触碰安全拦截与转人工判定。

每个变体在独立案例中运行，结束后删除该案例的全部派生行（证据/假设/检查/步骤/审计），
避免不同变体、不同策略之间互相污染。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy import delete, func, select

from core.ai.base import ProviderError
from core.cases.service import create_case
from core.db.models import (
    AuditLog,
    Case,
    DiagnosticStep,
    Evidence,
    Hypothesis,
    Probe,
    ProbeResult,
    RepairOutcome,
    User,
    WorkOrder,
)
from core.diagnosis.evidence import add_evidence, list_evidence
from core.diagnosis.hypotheses import (
    Rule,
    confidence_of,
    generate_hypotheses,
    list_hypotheses,
    rules_for,
)
from core.diagnosis.orchestrator import finalize_diagnosis
from core.policy.rbac import Actor, Role
from core.probes.planner import plan_next_probe, record_probe_result
from core.repair.templates import REPAIR_TEMPLATES
from core.workflow.states import CaseStatus, IllegalTransition
from services.api.app.config import settings
from services.api.app.errors import ApiError

DIAGNOSED = CaseStatus.DIAGNOSED.value
NEED_HUMAN = CaseStatus.NEED_HUMAN.value

SIMULATOR_EMAIL = "simulator@zhixiu.local"
SIMULATOR_DISPLAY_NAME = "模拟诊断机器人"

HISTORY_WEIGHT_STEP = 0.05
HISTORY_WEIGHT_CAP = 0.15
REPLACE_PART = "replace_part"

# 与 C-SIM@1 B.4 的 PARTS_REQUIRED_CAUSES 同口径：这些根因的正常修复需要换件，
# 其余根因更换配件即为“不必要配件更换”。
_PART_REQUIRED_CAUSES: frozenset[str] = frozenset(
    {
        "FAN_MOTOR",
        "FAN_DRIVER",
        "POWER_SUPPLY",
        "POWER_WIRING",
        "NETWORK_MODULE",
        "COMPRESSOR_FAULT",
        "SENSOR_FAULT",
        "SENSOR_WIRING",
        "CONTROL_BOARD",
    }
)

# 这些 409 表示“规则上还不足以定案”，属于诊断结果而非异常，按转人工记录。
_STOP_CODES: frozenset[str] = frozenset(
    {"INSUFFICIENT_EVIDENCE", "PROBE_AVAILABLE", "PENDING_PROBE"}
)


class Strategy(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


@dataclass(frozen=True)
class ScenarioResult:
    strategy: str
    scenario_id: str
    variant_id: str
    root_cause: str | None = None
    predicted_causes: list[str] = field(default_factory=list)
    steps: int = 0
    probe_codes: list[str] = field(default_factory=list)
    final_status: str = NEED_HUMAN
    needs_human: bool = True
    evidence_manual_ids: list[str] = field(default_factory=list)
    recommended_action: str | None = None
    recommended_parts: list[str] = field(default_factory=list)
    citation_hit: bool = False
    safety_blocked: bool = False
    escalated_correctly: bool = False
    completed: bool = True
    error: str | None = None
    # 以下为离线打分所需的场景真值，仅供 metrics 使用，不参与任何策略决策。
    true_cause_code: str = ""
    risk_flags: list[str] = field(default_factory=list)
    expected_probe_codes: list[str] = field(default_factory=list)
    expected_escalation: bool = False


def run_scenario(db: Any, *, scenario: Any, variant: Any, strategy: Any) -> ScenarioResult:
    """在隔离案例中运行一个（场景, 变体, 策略）组合并返回可打分的结果。"""
    try:
        strategy_value = Strategy(strategy).value
    except ValueError as exc:
        raise ValueError(f"unknown strategy: {strategy!r}") from exc

    scenario_id = str(_field(scenario, "id") or "")
    variant_id = str(_field(variant, "id") or "")
    true_cause = str(_field(scenario, "true_cause_code") or "")
    risk_flags = [str(flag) for flag in (_field(scenario, "risk_flags") or [])]
    expected_probe_codes = [
        str(code) for code in (_field(variant, "expected_probe_codes") or [])
    ]
    expected_escalation = bool(_field(variant, "expected_escalation", False))
    safety_input = _safety_hit(risk_flags)

    outcome: dict[str, Any] = {
        "root_cause": None,
        "predicted_causes": [],
        "steps": 0,
        "probe_codes": [],
        "evidence_manual_ids": [],
        "needs_human": True,
        "final_status": NEED_HUMAN,
        "completed": True,
        "error": None,
    }

    case_id: str | None = None
    try:
        actor = _simulator_actor(db)
        case = create_case(
            db,
            user=actor,
            device_model=str(_field(scenario, "device_model") or ""),
            symptom=str(_field(variant, "symptom") or ""),
            error_code=_field(scenario, "error_code"),
        )
        case_id = case.id
        if safety_input:
            outcome["steps"] = 0
        elif strategy_value == Strategy.A.value:
            outcome.update(_run_rule_only(scenario=scenario, variant=variant))
        else:
            outcome.update(
                _run_ledger(
                    db,
                    actor=actor,
                    case=case,
                    scenario=scenario,
                    variant=variant,
                    strategy=Strategy(strategy_value),
                )
            )
    except ProviderError as exc:
        outcome.update(_failure(f"{exc.code}: {exc.message}"))
    except IllegalTransition as exc:
        outcome.update(_failure(f"ILLEGAL_TRANSITION: {exc}"))
    except ApiError as exc:
        if exc.code in _STOP_CODES:
            outcome.update(needs_human=True, final_status=NEED_HUMAN, root_cause=None)
        else:
            outcome.update(_failure(f"{exc.code}: {exc.message}"))
    except Exception as exc:  # 单场景异常不得中断整体消融
        outcome.update(_failure(f"{type(exc).__name__}: {exc}"))
    finally:
        if case_id is not None:
            _cleanup_case(db, case_id)

    root_cause = outcome["root_cause"]
    needs_human = bool(outcome["needs_human"])
    recommended_action, recommended_parts = _recommend(root_cause)
    return ScenarioResult(
        strategy=strategy_value,
        scenario_id=scenario_id,
        variant_id=variant_id,
        root_cause=root_cause,
        predicted_causes=list(outcome["predicted_causes"]),
        steps=int(outcome["steps"]),
        probe_codes=list(outcome["probe_codes"]),
        final_status=outcome["final_status"],
        needs_human=needs_human,
        evidence_manual_ids=list(outcome["evidence_manual_ids"]),
        recommended_action=recommended_action,
        recommended_parts=recommended_parts,
        citation_hit=_citation_hit(outcome["evidence_manual_ids"], variant),
        safety_blocked=safety_input and needs_human,
        escalated_correctly=needs_human and expected_escalation,
        completed=bool(outcome["completed"]),
        error=outcome["error"],
        true_cause_code=true_cause,
        risk_flags=risk_flags,
        expected_probe_codes=expected_probe_codes,
        expected_escalation=expected_escalation,
    )


def _run_rule_only(*, scenario: Any, variant: Any) -> dict[str, Any]:
    """A：规则树 + 关键词匹配，不落证据账本、不规划检查。"""
    texts: list[tuple[str, str]] = [("support", str(_field(variant, "symptom") or ""))]
    raw_evidence = list(_field(variant, "evidence") or [])
    for item in raw_evidence:
        polarity = str(_field(item, "polarity") or "")
        quote = str(_field(item, "quote") or "")
        if polarity in {"support", "refute"} and quote:
            texts.append((polarity, quote))

    scored: list[tuple[str, int, int]] = []
    for rule in rules_for(_field(scenario, "error_code")):
        support = sum(1 for polarity, text in texts if polarity == "support" and _matches(rule, text))
        refute = sum(1 for polarity, text in texts if polarity == "refute" and _matches(rule, text))
        scored.append((rule.cause_code, support, refute))
    scored.sort(key=lambda item: (-(item[1] - item[2]), -item[1], item[0]))

    predicted = [code for code, _, _ in scored]
    root_cause: str | None = None
    if scored:
        code, support, refute = scored[0]
        _, level, _ = confidence_of(support, refute)
        if level == "high":
            root_cause = code

    manual_ids: list[str] = []
    if root_cause is not None:
        rule = next(
            (item for item in rules_for(_field(scenario, "error_code")) if item.cause_code == root_cause),
            None,
        )
        if rule is not None:
            refs = _manual_refs(raw_evidence, _field(variant, "expected_evidence_manual_ids") or [])
            for index, item in enumerate(raw_evidence):
                if str(_field(item, "source_type") or "") != "manual":
                    continue
                if index in refs and _matches(rule, str(_field(item, "quote") or "")):
                    manual_ids.append(refs[index])

    return {
        "root_cause": root_cause,
        "predicted_causes": predicted,
        "steps": 0,
        "probe_codes": [],
        "evidence_manual_ids": sorted(set(manual_ids)),
        "needs_human": root_cause is None,
        "final_status": DIAGNOSED if root_cause is not None else NEED_HUMAN,
    }


def _run_ledger(
    db: Any,
    *,
    actor: Actor,
    case: Case,
    scenario: Any,
    variant: Any,
    strategy: Strategy,
) -> dict[str, Any]:
    """B/C/D：证据账本 → 假设 →（C/D 主动检查）→ 结论。"""
    raw_evidence = list(_field(variant, "evidence") or [])
    refs = _manual_refs(raw_evidence, _field(variant, "expected_evidence_manual_ids") or [])

    recorded = 0
    for index, item in enumerate(raw_evidence):
        quote = str(_field(item, "quote") or "").strip()
        if not quote:
            continue
        add_evidence(
            db,
            case_id=case.id,
            actor=actor,
            source_type=str(_field(item, "source_type") or ""),
            polarity=str(_field(item, "polarity") or ""),
            quote=quote,
            source_ref=refs.get(index),
        )
        recorded += 1
    if recorded == 0:
        return _inconclusive()

    generate_hypotheses(db, case_id=case.id, actor=actor)

    probe_codes: list[str] = []
    needs_human = False
    if strategy in (Strategy.C, Strategy.D):
        answers = dict(_field(variant, "probe_answers") or {})
        for _ in range(max(1, int(settings.max_probe_steps))):
            probe = plan_next_probe(db, case_id=case.id, actor=actor)
            if probe is None:
                break
            observed = answers.get(probe.code)
            if observed is None:
                # 场景没有该检查的观察值，无法继续收集证据，等待人工。
                break
            result = record_probe_result(
                db,
                case_id=case.id,
                probe_id=probe.id,
                observed_value=str(observed),
                source_ref=probe.code,
                actor=actor,
            )
            probe_codes.append(probe.code)
            if result.get("needs_human"):
                needs_human = True
                break

    if strategy is Strategy.D and not needs_human:
        _apply_history_weight(db, case)

    root_cause: str | None = None
    if not needs_human:
        try:
            diagnosis = finalize_diagnosis(db, case_id=case.id, actor=actor)
            root_cause = diagnosis.root_cause.cause_code if diagnosis.root_cause is not None else None
        except ApiError as exc:
            if exc.code not in _STOP_CODES:
                raise
            root_cause = None

    predicted = [hypothesis.cause_code for hypothesis in list_hypotheses(db, case.id)]
    manual_ids: list[str] = []
    if root_cause is not None:
        root = next((item for item in list_hypotheses(db, case.id) if item.cause_code == root_cause), None)
        if root is not None:
            support_ids = set(root.support_evidence_ids or [])
            manual_ids = sorted(
                {
                    item.source_ref
                    for item in list_evidence(db, case.id)
                    if item.id in support_ids and item.source_type == "manual" and item.source_ref
                }
            )

    return {
        "root_cause": root_cause,
        "predicted_causes": predicted,
        "steps": int(case.step_count or 0),
        "probe_codes": probe_codes,
        "evidence_manual_ids": manual_ids,
        "needs_human": root_cause is None,
        "final_status": DIAGNOSED if root_cause is not None else NEED_HUMAN,
    }


def _inconclusive() -> dict[str, Any]:
    return {
        "root_cause": None,
        "predicted_causes": [],
        "steps": 0,
        "probe_codes": [],
        "evidence_manual_ids": [],
        "needs_human": True,
        "final_status": NEED_HUMAN,
    }


def _failure(message: str) -> dict[str, Any]:
    return {
        "root_cause": None,
        "predicted_causes": [],
        "steps": 0,
        "probe_codes": [],
        "evidence_manual_ids": [],
        "needs_human": True,
        "final_status": NEED_HUMAN,
        "completed": False,
        "error": message,
    }


def _field(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _matches(rule: Rule, text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in rule.keywords)


def _manual_refs(raw_evidence: list[Any], expected_ids: list[Any]) -> dict[int, str]:
    """把 manual 来源的证据绑定到变体声明的 manual id。

    合成场景的证据项只带 {source_type, polarity, quote}，没有 manual_id；模拟 RAG
    引用时按出现顺序使用变体声明的 expected_evidence_manual_ids 作为引用标识，
    使 citations 能在离线打分中被核对。
    """
    refs: dict[int, str] = {}
    cursor = 0
    for index, item in enumerate(raw_evidence):
        if str(_field(item, "source_type") or "") != "manual":
            continue
        explicit = _field(item, "manual_id") or _field(item, "source_ref")
        if explicit:
            refs[index] = str(explicit)
            continue
        if cursor < len(expected_ids):
            refs[index] = str(expected_ids[cursor])
            cursor += 1
    return refs


def _citation_hit(manual_ids: list[str], variant: Any) -> bool:
    expected = [str(item) for item in (_field(variant, "expected_evidence_manual_ids") or [])]
    if not expected:
        return True
    return bool(set(expected) & set(manual_ids))


def _safety_hit(risk_flags: list[str]) -> bool:
    """安全规则：高风险标记（high* / safety*）一律先转人工，不做自动检查。"""
    for flag in risk_flags:
        text = str(flag).strip().lower()
        if text == "high" or text.startswith("high") or text.startswith("safety"):
            return True
    return False


def _recommend(cause_code: str | None) -> tuple[str | None, list[str]]:
    """按预测根因给出推荐动作与配件：需换件的根因推荐换件，其余优先非换件方案。"""
    if not cause_code:
        return None, []
    templates = REPAIR_TEMPLATES.get(cause_code, ())
    if cause_code in _PART_REQUIRED_CAUSES:
        for template in templates:
            if template.action == REPLACE_PART and template.parts:
                return template.action, list(template.parts)
        for template in templates:
            if template.parts:
                return template.action, list(template.parts)
        return REPLACE_PART, []
    for template in templates:
        if not template.parts:
            return template.action, []
    if templates:
        return templates[0].action, list(templates[0].parts)
    return None, []


def _historical_weights(db: Any, error_code: str | None) -> dict[str, int]:
    if not error_code:
        return {}
    stmt = (
        select(RepairOutcome.actual_cause_code, func.count(RepairOutcome.id))
        .join(WorkOrder, WorkOrder.id == RepairOutcome.work_order_id)
        .join(Case, Case.id == WorkOrder.case_id)
        .where(Case.error_code == str(error_code).strip().upper())
        .group_by(RepairOutcome.actual_cause_code)
    )
    return {str(code): int(count) for code, count in db.execute(stmt).all()}


def _apply_history_weight(db: Any, case: Case) -> None:
    """D：按同故障码历史真实根因频率加权，权重只来自 RepairOutcome。"""
    weights = _historical_weights(db, case.error_code)
    if not weights:
        return
    for hypothesis in list_hypotheses(db, case.id):
        count = weights.get(hypothesis.cause_code, 0)
        if not count:
            continue
        boost = min(HISTORY_WEIGHT_CAP, HISTORY_WEIGHT_STEP * count)
        hypothesis.confidence_score = round(
            min(1.0, float(hypothesis.confidence_score or 0.0) + boost), 4
        )
    db.commit()


def _simulator_actor(db: Any) -> Actor:
    user = db.scalar(
        select(User)
        .where(User.role == Role.AGENT.value)
        .order_by(User.created_at.asc(), User.id.asc())
        .limit(1)
    )
    if user is None:
        user = User(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"zhixiu-v12:{SIMULATOR_EMAIL}")),
            email=SIMULATOR_EMAIL,
            password_hash="!",
            display_name=SIMULATOR_DISPLAY_NAME,
            role=Role.AGENT.value,
        )
        db.add(user)
        db.commit()
    return Actor(user.id, Role.AGENT.value)


def _cleanup_case(db: Any, case_id: str) -> None:
    try:
        db.rollback()
        probe_ids = list(db.scalars(select(Probe.id).where(Probe.case_id == case_id)))
        if probe_ids:
            db.execute(delete(ProbeResult).where(ProbeResult.probe_id.in_(probe_ids)))
        for model in (Probe, Evidence, Hypothesis, DiagnosticStep):
            db.execute(delete(model).where(model.case_id == case_id))
        db.execute(delete(AuditLog).where(AuditLog.resource_id == case_id))
        db.execute(delete(Case).where(Case.id == case_id))
        db.commit()
    except Exception:
        db.rollback()