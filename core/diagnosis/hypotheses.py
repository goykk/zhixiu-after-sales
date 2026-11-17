"""规则诊断树、候选根因、支持/反对证据计数与置信级别（C-HYPOTHESIS@1）。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from core.cases.service import load_case_for_actor
from core.db.models import AuditLog, DiagnosticStep, Evidence, Hypothesis, utcnow
from core.policy.rbac import Actor
from core.workflow.states import CaseStatus, assert_transition
from services.api.app.errors import ApiError

HYPOTHESIS_STATUSES = ("open", "supported", "rejected")
CONFIDENCE_LEVELS = ("high", "medium", "low")

GENUINE_POLARITIES = ("support", "refute")


@dataclass(frozen=True)
class Rule:
    cause_code: str
    label: str
    keywords: tuple[str, ...]


DIAGNOSIS_RULES: dict[str, tuple[Rule, ...]] = {
    "E101": (
        Rule(
            "POWER_SUPPLY",
            "供电电压/电源输出异常",
            ("断电", "跳闸", "电压", "电源", "无输出", "breaker", "voltage", "power", "supply"),
        ),
        Rule(
            "POWER_WIRING",
            "接线/插头接触不良",
            ("插头", "接线", "松动", "接触不良", "线束", "虚接", "plug", "wire", "loose", "connector"),
        ),
    ),
    "E103": (
        Rule(
            "NETWORK_CONFIG",
            "网络配置异常（连接/配网失败）",
            ("配网", "联网", "网络", "连接失败", "wifi", "wi-fi", "未连接", "配置", "network", "connect"),
        ),
        Rule(
            "NETWORK_MODULE",
            "网络通信模块硬件异常",
            ("模块", "通信板", "网卡", "信号弱", "断连", "module", "modem", "antenna"),
        ),
    ),
    "E105": (
        Rule(
            "COMPRESSOR_FAULT",
            "压缩机故障（不启动/过热）",
            ("压缩机", "压机", "不启动", "过热", "嗡嗡", "compressor"),
        ),
        Rule(
            "CONDENSER_BLOCKED",
            "冷凝器/滤网堵塞散热不良",
            ("冷凝器", "散热", "滤网", "堵塞", "积尘", "condenser", "blocked", "filter"),
        ),
        Rule(
            "REFRIGERANT_LEAK",
            "制冷剂泄漏/压力不足",
            ("制冷剂", "冷媒", "泄漏", "压力低", "不制冷", "refrigerant", "leak", "pressure"),
        ),
    ),
    "E106": (
        Rule(
            "FAN_BLOCKED",
            "风扇卡阻（异物/积尘）",
            (
                "风扇",
                "扇叶",
                "叶片",
                "异响",
                "摩擦",
                "卡住",
                "卡阻",
                "异物",
                "积尘",
                "灰尘",
                "抖动",
                "噪音",
                "blocked",
                "debris",
                "blade",
                "rattle",
                "noise",
            ),
        ),
        Rule(
            "FAN_MOTOR",
            "风扇电机/轴承磨损",
            ("轴承", "电机", "转速", "磨损", "老化", "嗡嗡", "bearing", "motor", "rpm", "worn"),
        ),
        Rule(
            "FAN_DRIVER",
            "风扇驱动板/供电异常",
            ("驱动", "驱动板", "供电", "电压", "驱动芯片", "driver", "voltage", "supply"),
        ),
    ),
    "E108": (
        Rule(
            "SENSOR_FAULT",
            "温度/压力传感器失效",
            ("传感器", "读数", "偏差", "失准", "报错值", "sensor", "reading", "drift"),
        ),
        Rule(
            "SENSOR_WIRING",
            "传感器信号线路异常",
            ("信号线", "线束", "插接", "短路", "断路", "屏蔽", "signal", "harness", "short"),
        ),
    ),
}

GENERAL_RULES: tuple[Rule, ...] = (
    Rule(
        "GENERAL_POWER",
        "电源/供电异常",
        ("电源", "供电", "断电", "跳闸", "电压", "power", "supply", "voltage"),
    ),
    Rule(
        "GENERAL_CONTROL",
        "控制/程序设置异常",
        ("控制", "程序", "设置", "面板", "无响应", "control", "setting", "panel", "firmware"),
    ),
)

_RULE_INDEX: dict[str, Rule] = {
    rule.cause_code: rule for rules in DIAGNOSIS_RULES.values() for rule in rules
}
_RULE_INDEX.update({rule.cause_code: rule for rule in GENERAL_RULES})


def rules_for(error_code: str | None) -> tuple[Rule, ...]:
    """按故障码取规则树；未知或缺失故障码回退到通用根因。"""
    key = (error_code or "").strip().upper()
    return DIAGNOSIS_RULES.get(key) or GENERAL_RULES


def confidence_of(support: int, refute: int) -> tuple[str, str, float]:
    """置信规则唯一决策点：返回 (status, confidence_level, confidence_score)。"""
    score = round(min(1.0, max(0.0, 0.2 + 0.25 * support - 0.35 * refute)), 4)
    if support >= 2 and refute == 0:
        return "supported", "high", score
    if support >= 1 and refute == 0:
        return "open", "medium", score
    if refute > support:
        return "rejected", "low", score
    return "open", "low", score


def _matches(quote: str, rule: Rule) -> bool:
    text = (quote or "").lower()
    return any(keyword in text for keyword in rule.keywords)


def _matches_cause(quote: str, cause_code: str) -> bool:
    rule = _RULE_INDEX.get(cause_code)
    return bool(rule) and _matches(quote, rule)


def _recompute(hypothesis: Hypothesis) -> Hypothesis:
    support = len(hypothesis.support_evidence_ids or [])
    refute = len(hypothesis.refute_evidence_ids or [])
    hypothesis.status, hypothesis.confidence_level, hypothesis.confidence_score = confidence_of(support, refute)
    hypothesis.rationale = (
        f"支持证据 {support} 条，反对证据 {refute} 条；"
        f"证据版本 {hypothesis.evidence_version}，置信级别 {hypothesis.confidence_level}"
    )
    hypothesis.updated_at = utcnow()
    return hypothesis


def _payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _case_evidences(db: Session, case_id: str) -> list[Evidence]:
    rows = (
        db.query(Evidence)
        .filter(Evidence.case_id == case_id)
        .order_by(Evidence.created_at.asc())
        .all()
    )
    # 模型推测只用于展示，不参与支持/反对计数。
    return [e for e in rows if e.source_type != "model"]


def generate_hypotheses(db: Session, *, case_id: str, actor: Actor) -> list[Hypothesis]:
    """按规则树初始化/刷新候选根因，并把案例从 EVIDENCE_READY 推进到 HYPOTHESIZING。"""
    case = load_case_for_actor(db, case_id, actor)
    if case.status not in (CaseStatus.EVIDENCE_READY.value, CaseStatus.HYPOTHESIZING.value):
        raise ApiError(
            409,
            "ILLEGAL_TRANSITION",
            f"hypotheses require EVIDENCE_READY or HYPOTHESIZING, current status={case.status}",
        )

    rules = rules_for(case.error_code)
    existing = {h.cause_code: h for h in db.query(Hypothesis).filter(Hypothesis.case_id == case_id).all()}
    evidences = _case_evidences(db, case_id)

    hypotheses: list[Hypothesis] = []
    for rule in rules:
        hypothesis = existing.get(rule.cause_code)
        if hypothesis is None:
            hypothesis = Hypothesis(
                case_id=case_id,
                cause_code=rule.cause_code,
                label=rule.label,
                status="open",
                confidence_level="low",
                confidence_score=confidence_of(0, 0)[2],
                evidence_version=int(case.evidence_version or 0),
                support_evidence_ids=[],
                refute_evidence_ids=[],
                rationale="",
            )
            db.add(hypothesis)
        else:
            hypothesis.label = rule.label

        support_ids: list[str] = []
        refute_ids: list[str] = []
        for evidence in evidences:
            if evidence.polarity not in GENUINE_POLARITIES or not _matches(evidence.quote, rule):
                continue
            target = support_ids if evidence.polarity == "support" else refute_ids
            if evidence.id not in target:
                target.append(evidence.id)

        # 幂等重算会丢失检查结果这类不含关键词但已显式绑定的证据，这里保留既有绑定。
        for evidence in evidences:
            if evidence.id in (hypothesis.support_evidence_ids or []) and evidence.polarity == "support":
                if evidence.id not in support_ids:
                    support_ids.append(evidence.id)
            elif evidence.id in (hypothesis.refute_evidence_ids or []) and evidence.polarity == "refute":
                if evidence.id not in refute_ids:
                    refute_ids.append(evidence.id)

        hypothesis.support_evidence_ids = support_ids
        hypothesis.refute_evidence_ids = refute_ids
        _recompute(hypothesis)
        hypotheses.append(hypothesis)

    if case.status == CaseStatus.EVIDENCE_READY.value:
        assert_transition(case.status, CaseStatus.HYPOTHESIZING.value)
        case.status = CaseStatus.HYPOTHESIZING.value
        case.updated_at = utcnow()

    hypotheses.sort(key=hypothesis_rank_key)
    payload = {
        "case_id": case_id,
        "error_code": case.error_code,
        "hypotheses": [h.cause_code for h in hypotheses],
    }
    db.add(
        DiagnosticStep(
            case_id=case_id,
            step_type="hypotheses_generated",
            input={"error_code": case.error_code, "evidence_count": len(evidences)},
            output={
                "hypotheses": [
                    {
                        "cause_code": h.cause_code,
                        "status": h.status,
                        "confidence_level": h.confidence_level,
                        "confidence_score": h.confidence_score,
                    }
                    for h in hypotheses
                ]
            },
        )
    )
    db.add(
        AuditLog(
            actor_id=actor.actor_id,
            action="hypotheses.generated",
            resource_id=case_id,
            payload_hash=_payload_hash(payload),
            payload=payload,
        )
    )
    db.commit()
    for hypothesis in hypotheses:
        db.refresh(hypothesis)
    return hypotheses


def apply_evidence(
    db: Session,
    *,
    case_id: str,
    evidence: Evidence,
    cause_codes: list[str] | None = None,
) -> list[Hypothesis]:
    """把一条证据挂到目标假设上并重算置信；不做提交，由调用方维护单事务。"""
    if evidence.source_type == "model" or evidence.polarity not in GENUINE_POLARITIES:
        return []
    if evidence.id is None:
        db.flush()

    hypotheses = db.query(Hypothesis).filter(Hypothesis.case_id == case_id).all()
    if not hypotheses:
        return []

    if cause_codes:
        wanted = {code for code in cause_codes if code}
        targets = [h for h in hypotheses if h.cause_code in wanted]
    else:
        targets = [h for h in hypotheses if h.status == "open" and _matches_cause(evidence.quote, h.cause_code)]

    affected: list[Hypothesis] = []
    field = "support_evidence_ids" if evidence.polarity == "support" else "refute_evidence_ids"
    for hypothesis in targets:
        ids = list(getattr(hypothesis, field) or [])
        if evidence.id in ids:
            # 同一条证据重复应用不重复计数，也不虚增证据版本。
            affected.append(hypothesis)
            continue
        ids.append(evidence.id)
        setattr(hypothesis, field, ids)
        hypothesis.evidence_version = int(hypothesis.evidence_version or 0) + 1
        _recompute(hypothesis)
        affected.append(hypothesis)

    db.flush()
    return affected


def list_hypotheses(db: Session, case_id: str) -> list[Hypothesis]:
    rows = db.query(Hypothesis).filter(Hypothesis.case_id == case_id).all()
    return sorted(rows, key=hypothesis_rank_key)


def hypothesis_rank_key(
    hypothesis: Hypothesis, history_weights: dict[str, int] | None = None
) -> tuple[float, int, str]:
    """候选排序唯一口径：分数降序 → 历史计数降序 → cause_code 升序。

    ``history_weights`` 仅由消融 D 显式传入，用于同分时优先历史高频根因；
    普通诊断链路不传，等价于“同分按 cause_code 升序”。
    """
    history_count = (history_weights or {}).get(hypothesis.cause_code, 0)
    return (
        -(hypothesis.confidence_score or 0.0),
        -history_count,
        hypothesis.cause_code,
    )