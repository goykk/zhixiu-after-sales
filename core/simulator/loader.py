"""C-SIM@1 B.2：场景集加载与留出切分。

场景文件是合成数据，校验只覆盖契约要求的结构约束（数量/变体数/枚举/型号/
留出比例）；校验失败统一抛 `ValueError`，由调用方决定是否中断。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.diagnosis.evidence import POLARITIES, SOURCE_TYPES
from core.diagnosis.hypotheses import DIAGNOSIS_RULES, GENERAL_RULES
from core.parts.catalog import PART_CATALOG

DATASET_VERSION = "v1"
VARIANT_IDS: tuple[str, ...] = ("text_only", "with_photo", "with_probe_result")
SCENARIO_MIN = 60
SCENARIO_MAX = 80
VARIANTS_PER_SCENARIO = 3
HOLDOUT_SHARE = 0.2
HOLDOUT_TOLERANCE = 0.01
SPLITS: tuple[str, ...] = ("holdout", "train", "all")

DEVICE_MODELS: frozenset[str] = frozenset(PART_CATALOG)
CAUSE_CODES: frozenset[str] = frozenset(
    {rule.cause_code for rules in DIAGNOSIS_RULES.values() for rule in rules}
    | {rule.cause_code for rule in GENERAL_RULES}
)


@dataclass(frozen=True)
class Variant:
    id: str
    symptom: str
    evidence: tuple[dict[str, str], ...]
    probe_answers: dict[str, str] = field(default_factory=dict)
    expected_probe_codes: tuple[str, ...] = ()
    expected_escalation: bool = False
    expected_evidence_manual_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    id: str
    device_model: str
    error_code: str
    true_cause_code: str
    confusable_causes: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    holdout: bool = False
    variants: tuple[Variant, ...] = ()


@dataclass(frozen=True)
class ScenarioCase:
    """一个待模拟的最小单元：场景 + 其中一个变体。"""

    scenario: Scenario
    variant: Variant

    @property
    def scenario_id(self) -> str:
        return self.scenario.id

    @property
    def variant_id(self) -> str:
        return self.variant.id


def load_scenarios(path: str | Path) -> list[Scenario]:
    data_path = Path(path)
    if not data_path.is_file():
        raise ValueError(f"scenario dataset not found: {data_path}")
    try:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"scenario dataset is not readable JSON: {data_path}") from exc

    if not isinstance(payload, dict):
        raise ValueError("scenario dataset must be a JSON object")
    version = payload.get("dataset_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("dataset_version must be a non-empty string")
    raw_scenarios = payload.get("scenarios")
    if not isinstance(raw_scenarios, list):
        raise ValueError("scenarios must be a list")
    if not SCENARIO_MIN <= len(raw_scenarios) <= SCENARIO_MAX:
        raise ValueError(
            f"scenario count must be within {SCENARIO_MIN}-{SCENARIO_MAX}, got {len(raw_scenarios)}"
        )

    scenarios = [_parse_scenario(item, index) for index, item in enumerate(raw_scenarios)]
    _reject_duplicates([item.id for item in scenarios], "scenario id")

    holdout_share = sum(1 for item in scenarios if item.holdout) / len(scenarios)
    if abs(holdout_share - HOLDOUT_SHARE) > HOLDOUT_TOLERANCE:
        raise ValueError(
            f"holdout share must be {HOLDOUT_SHARE:.0%}±{HOLDOUT_TOLERANCE:.0%}, "
            f"got {holdout_share:.2%}"
        )
    return scenarios


def split_scenarios(scenarios: list[Scenario], split: str = "holdout") -> list[Scenario]:
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, got {split!r}")
    if split == "all":
        return list(scenarios)
    want_holdout = split == "holdout"
    return [item for item in scenarios if item.holdout is want_holdout]


def iter_cases(scenarios: list[Scenario]) -> list[ScenarioCase]:
    return [
        ScenarioCase(scenario=scenario, variant=variant)
        for scenario in scenarios
        for variant in scenario.variants
    ]


def _parse_scenario(raw: Any, index: int) -> Scenario:
    if not isinstance(raw, dict):
        raise ValueError(f"scenario #{index} must be a JSON object")
    scenario_id = _text(raw.get("id"), f"scenario #{index} id")
    prefix = f"scenario {scenario_id}"
    device_model = _text(raw.get("device_model"), f"{prefix} device_model")
    if device_model not in DEVICE_MODELS:
        raise ValueError(f"{prefix} device_model not in demo models: {device_model}")
    error_code = _text(raw.get("error_code"), f"{prefix} error_code").upper()
    true_cause = _text(raw.get("true_cause_code"), f"{prefix} true_cause_code")
    if true_cause not in CAUSE_CODES:
        raise ValueError(f"{prefix} true_cause_code not in frozen causes: {true_cause}")
    confusable = _code_tuple(raw.get("confusable_causes"), f"{prefix} confusable_causes")
    risk_flags = _text_tuple(raw.get("risk_flags"), f"{prefix} risk_flags")
    holdout = raw.get("holdout")
    if not isinstance(holdout, bool):
        raise ValueError(f"{prefix} holdout must be a boolean")

    raw_variants = raw.get("variants")
    if not isinstance(raw_variants, list):
        raise ValueError(f"{prefix} variants must be a list")
    if len(raw_variants) != VARIANTS_PER_SCENARIO:
        raise ValueError(
            f"{prefix} must have {VARIANTS_PER_SCENARIO} variants, got {len(raw_variants)}"
        )
    variants = tuple(_parse_variant(item, prefix) for item in raw_variants)
    _reject_duplicates([item.id for item in variants], f"{prefix} variant id")
    if {item.id for item in variants} != set(VARIANT_IDS):
        raise ValueError(f"{prefix} variant ids must be exactly {VARIANT_IDS}")

    return Scenario(
        id=scenario_id,
        device_model=device_model,
        error_code=error_code,
        true_cause_code=true_cause,
        confusable_causes=confusable,
        risk_flags=risk_flags,
        holdout=holdout,
        variants=variants,
    )


def _parse_variant(raw: Any, scenario_prefix: str) -> Variant:
    if not isinstance(raw, dict):
        raise ValueError(f"{scenario_prefix} variant must be a JSON object")
    variant_id = _text(raw.get("id"), f"{scenario_prefix} variant id")
    if variant_id not in VARIANT_IDS:
        raise ValueError(f"{scenario_prefix} variant id must be one of {VARIANT_IDS}")
    prefix = f"{scenario_prefix} variant {variant_id}"
    symptom = raw.get("symptom")
    if not isinstance(symptom, str):
        raise ValueError(f"{prefix} symptom must be a string")

    raw_evidence = raw.get("evidence")
    if not isinstance(raw_evidence, list):
        raise ValueError(f"{prefix} evidence must be a list")
    evidence: list[dict[str, str]] = []
    for item in raw_evidence:
        if not isinstance(item, dict):
            raise ValueError(f"{prefix} evidence item must be a JSON object")
        source_type = _text(item.get("source_type"), f"{prefix} evidence source_type")
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"{prefix} evidence source_type must be one of {SOURCE_TYPES}")
        polarity = _text(item.get("polarity"), f"{prefix} evidence polarity")
        if polarity not in POLARITIES:
            raise ValueError(f"{prefix} evidence polarity must be one of {POLARITIES}")
        quote = _text(item.get("quote"), f"{prefix} evidence quote")
        evidence.append({"source_type": source_type, "polarity": polarity, "quote": quote})

    probe_answers = raw.get("probe_answers")
    if not isinstance(probe_answers, dict):
        raise ValueError(f"{prefix} probe_answers must be an object")
    answers = {
        str(code): _text(value, f"{prefix} probe answer {code}")
        for code, value in probe_answers.items()
    }
    expected_escalation = raw.get("expected_escalation", False)
    if not isinstance(expected_escalation, bool):
        raise ValueError(f"{prefix} expected_escalation must be a boolean")

    return Variant(
        id=variant_id,
        symptom=symptom,
        evidence=tuple(evidence),
        probe_answers=answers,
        expected_probe_codes=_text_tuple(
            raw.get("expected_probe_codes"), f"{prefix} expected_probe_codes"
        ),
        expected_escalation=expected_escalation,
        expected_evidence_manual_ids=_text_tuple(
            raw.get("expected_evidence_manual_ids"),
            f"{prefix} expected_evidence_manual_ids",
        ),
    )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _text_tuple(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of strings")
    return tuple(_text(item, label) for item in value)


def _code_tuple(value: Any, label: str) -> tuple[str, ...]:
    codes = _text_tuple(value, label)
    unknown = [code for code in codes if code not in CAUSE_CODES]
    if unknown:
        raise ValueError(f"{label} contains unknown cause codes: {unknown}")
    return codes


def _reject_duplicates(values: list[str], label: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"duplicate {label}: {sorted(set(duplicates))}")