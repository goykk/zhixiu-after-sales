"""A/B/C/D 策略消融指标（C-SIM@1 B.4）。

场景真值（`true_cause_code`、`risk_flags`、`expected_probe_codes`）不在
`ScenarioResult` 中，因此由 `aggregate` 的 `scenarios` 参数按
`scenario_id`/`variant_id` 回填；缺失真值的变体不计入对应指标的分母，
避免把"无法判定"误记为失败。比例为 0/0 时统一返回 0.0。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.simulator.loader import Scenario
    from core.simulator.strategies import ScenarioResult

PARTS_REQUIRED_CAUSES: frozenset[str] = frozenset(
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

HIGH_RISK_FLAG = "high"
REPLACE_PART_ACTION = "replace_part"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _cause_code(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    code = _get(value, "cause_code")
    return code if isinstance(code, str) else None


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def _scenario_index(
    scenarios: Mapping[str, Scenario] | Sequence[Scenario] | None,
) -> Mapping[str, Scenario] | None:
    if scenarios is None:
        return None
    if isinstance(scenarios, Mapping):
        return scenarios
    return {scenario.id: scenario for scenario in scenarios}


def _find_variant(scenario: Any, variant_id: str | None) -> Any | None:
    for variant in _as_sequence(_get(scenario, "variants")):
        if _get(variant, "id") == variant_id:
            return variant
    return None


def _resolve_context(
    result: Any, index: Mapping[str, Scenario] | None
) -> tuple[Any | None, Any | None]:
    scenario = index.get(_get(result, "scenario_id")) if index else None
    if scenario is None:
        scenario = _get(result, "scenario")
    variant = None
    if scenario is not None:
        variant = _find_variant(scenario, _get(result, "variant_id"))
        if variant is None:
            candidate = _get(result, "variant")
            if _get(candidate, "id") == _get(result, "variant_id"):
                variant = candidate
    else:
        variant = _get(result, "variant")
    return scenario, variant


def _true_cause(result: Any, scenario: Any | None) -> str | None:
    cause = _cause_code(_get(scenario, "true_cause_code")) if scenario is not None else None
    if cause is not None:
        return cause
    return _cause_code(_get(result, "true_cause_code")) or _cause_code(
        _get(result, "true_cause")
    )


def _risk_flags(result: Any, scenario: Any | None) -> tuple[str, ...]:
    flags = _get(scenario, "risk_flags") if scenario is not None else None
    if flags is None:
        flags = _get(result, "risk_flags")
    return _as_sequence(flags)


def _expected_probe_codes(result: Any, variant: Any | None) -> tuple[str, ...]:
    codes = _get(variant, "expected_probe_codes") if variant is not None else None
    if not codes:
        codes = _get(result, "expected_probe_codes")
    return tuple(code for code in _as_sequence(codes) if isinstance(code, str))


def _expected_escalation(result: Any, variant: Any | None) -> bool:
    value = _get(variant, "expected_escalation") if variant is not None else None
    if value is None:
        value = _get(result, "expected_escalation")
    return bool(value)


def _rate(numerator: float, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def aggregate(
    results: Iterable[ScenarioResult],
    *,
    scenarios: Mapping[str, Scenario] | Sequence[Scenario] | None = None,
) -> dict[str, float | int]:
    """把逐变体结果汇总为 B.4 的 8 项指标与 3 个规模计数。"""
    rows = list(results)
    index = _scenario_index(scenarios)

    scenario_ids: set[str] = set()
    failed_count = 0
    steps_total = 0.0

    scored_count = 0
    top1_hits = 0
    top3_hits = 0
    diagnosable_count = 0
    diagnosable_top1_hits = 0
    diagnosable_top3_hits = 0
    early_probe_count = 0
    early_probe_hits = 0
    parts_count = 0
    unnecessary_parts = 0
    high_risk_count = 0
    safety_blocks = 0
    escalation_count = 0
    escalation_hits = 0
    citation_count = 0
    citation_hits = 0
    completion_count = 0
    completion_hits = 0

    for result in rows:
        scenario, variant = _resolve_context(result, index)

        scenario_id = _get(result, "scenario_id")
        if scenario_id is not None:
            scenario_ids.add(scenario_id)

        if _get(result, "error"):
            failed_count += 1

        steps = _get(result, "steps", 0)
        steps_total += steps if isinstance(steps, (int, float)) else 0

        cause = _true_cause(result, scenario)
        expected_escalation = _expected_escalation(result, variant)
        if cause is not None:
            scored_count += 1
            top1_hit = _cause_code(_get(result, "root_cause")) == cause
            if top1_hit:
                top1_hits += 1
            predicted = [_cause_code(item) for item in _as_sequence(_get(result, "predicted_causes"))]
            top3_hit = cause in predicted[:3]
            if top3_hit:
                top3_hits += 1
            # 应转人工变体按契约不产出根因，另用“可诊断”口径统计，避免双重惩罚。
            if not expected_escalation:
                diagnosable_count += 1
                diagnosable_top1_hits += int(top1_hit)
                diagnosable_top3_hits += int(top3_hit)

            expected = _expected_probe_codes(result, variant)
            if expected:
                early_probe_count += 1
                probed = set(
                    _as_sequence(_get(result, "probe_codes"))[:3]
                )
                if probed & set(expected):
                    early_probe_hits += 1

            parts_count += 1
            if (
                _get(result, "recommended_action") == REPLACE_PART_ACTION
                and cause not in PARTS_REQUIRED_CAUSES
            ):
                unnecessary_parts += 1

        if HIGH_RISK_FLAG in _risk_flags(result, scenario):
            high_risk_count += 1
            if bool(_get(result, "safety_blocked")):
                safety_blocks += 1

        if expected_escalation:
            escalation_count += 1
            escalation_hits += int(bool(_get(result, "escalated_correctly")))

        citation = _get(result, "citation_hit")
        if citation is not None:
            citation_count += 1
            citation_hits += int(bool(citation))

        completed = _get(result, "completed")
        if completed is not None:
            completion_count += 1
            completion_hits += int(bool(completed))

    return {
        "scenario_count": len(scenario_ids),
        "variant_count": len(rows),
        "failed_count": failed_count,
        "safety_variant_count": high_risk_count,
        "escalation_variant_count": escalation_count,
        "top1_rate": _rate(top1_hits, scored_count),
        "top3_rate": _rate(top3_hits, scored_count),
        "diagnosable_variant_count": diagnosable_count,
        "top1_rate_diagnosable": _rate(diagnosable_top1_hits, diagnosable_count),
        "top3_rate_diagnosable": _rate(diagnosable_top3_hits, diagnosable_count),
        "avg_steps": _rate(steps_total, len(rows)),
        "early_probe_rate": _rate(early_probe_hits, early_probe_count),
        "unnecessary_parts_rate": _rate(unnecessary_parts, parts_count),
        "safety_block_rate": _rate(safety_blocks, high_risk_count),
        "escalation_rate": _rate(escalation_hits, escalation_count),
        "citation_accuracy": _rate(citation_hits, citation_count),
        "completion_rate": _rate(completion_hits, completion_count),
    }