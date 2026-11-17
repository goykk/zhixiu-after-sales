"""确定性生成 80 个合成诊断场景（C-SIM@1 B.1）。

结构：60 基础（5 演示型号 × 12 冻结 cause_code）+ 10 困难 + 5 安全 + 5 边界，
每场景 3 变体，按序号每 5 个标记 1 个 holdout（16/80 = 20%）。

probe 答案从 `PROBE_CATALOG` 的 `expected_outcomes` 反推，保证与检查库一致：
优先选择支持真根因的观察值，其次选择对真根因既不支持也不反对的观察值。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.probes.catalog import PROBE_CATALOG  # noqa: E402

DATASET_VERSION = "v1"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "scenarios" / "v1" / "scenarios.json"

HOLDOUT_INTERVAL = 5
VARIANT_IDS = ("text_only", "with_photo", "with_probe_result")
SOURCE_TYPES = ("customer", "media", "manual", "probe", "model")
POLARITIES = ("support", "refute", "neutral")

DEVICE_MODELS: tuple[str, ...] = (
    "AuroraHome AC-Pro 1200",
    "AuroraHome AC-Mini 600",
    "NovaDesk PX-220",
    "NovaDesk PX-450",
    "VentoCool FZ-30",
)

CAUSES_BY_ERROR_CODE: dict[str, tuple[str, ...]] = {
    "E101": ("POWER_SUPPLY", "POWER_WIRING"),
    "E103": ("NETWORK_CONFIG", "NETWORK_MODULE"),
    "E105": ("COMPRESSOR_FAULT", "CONDENSER_BLOCKED", "REFRIGERANT_LEAK"),
    "E106": ("FAN_BLOCKED", "FAN_MOTOR", "FAN_DRIVER"),
    "E108": ("SENSOR_FAULT", "SENSOR_WIRING"),
}
ALL_CAUSE_CODES: tuple[str, ...] = tuple(
    cause for causes in CAUSES_BY_ERROR_CODE.values() for cause in causes
)

SUPPORT_QUOTES: dict[str, tuple[str, str]] = {
    "POWER_SUPPLY": (
        "上电后电源模块无输出，面板指示灯不亮。",
        "断开主电源后测量进线电压只有 0V，供电单元没有任何输出。",
    ),
    "POWER_WIRING": (
        "插头松动，接线端子有接触不良的痕迹。",
        "线束末端虚接，插头和插座之间明显松动。",
    ),
    "NETWORK_CONFIG": (
        "手机配网反复失败，面板显示未连接。",
        "设备联网时提示连接失败，wifi 配置无法保存。",
    ),
    "NETWORK_MODULE": (
        "通信模块信号弱，天线有断连现象。",
        "通信模块焊点开裂，天线断连、信号弱无法上线。",
    ),
    "COMPRESSOR_FAULT": (
        "压缩机过热保护后不启动，只听到嗡嗡声。",
        "压机完全不启动，压缩机外壳温度很高。",
    ),
    "CONDENSER_BLOCKED": (
        "冷凝器翅片积尘堵塞，散热明显变差。",
        "滤网长时间未清洗，冷凝器被堵塞导致散热不良。",
    ),
    "REFRIGERANT_LEAK": (
        "冷媒泄漏，系统压力低，完全不制冷。",
        "制冷剂有泄漏点，压力低且不制冷。",
    ),
    "FAN_BLOCKED": (
        "风扇区域异响，扇叶被异物卡住。",
        "叶片上有积尘和异物，风扇转动时抖动明显。",
    ),
    "FAN_MOTOR": (
        "电机转速不稳，轴承磨损严重并伴随嗡嗡声。",
        "电机老化，转速下降，轴承有磨损。",
    ),
    "FAN_DRIVER": (
        "驱动板供电电压异常，驱动芯片无输出。",
        "驱动板稳压失效，供电电压偏低，驱动芯片无输出。",
    ),
    "SENSOR_FAULT": (
        "温度传感器读数偏差大，明显失准。",
        "传感器报错值异常，读数持续漂移。",
    ),
    "SENSOR_WIRING": (
        "温度探头信号线插接松动，线束存在断路。",
        "温度探头信号线被屏蔽层短路，线束插接不良。",
    ),
}

REFUTE_QUOTES: dict[str, str] = {
    "POWER_SUPPLY": "供电电压测量正常，电源输出稳定。",
    "POWER_WIRING": "插头与接线检查正常，无松动或接触不良。",
    "NETWORK_CONFIG": "配网流程与账号配置均正常。",
    "NETWORK_MODULE": "通信模块与天线检查正常，未发现信号弱或断连。",
    "COMPRESSOR_FAULT": "压缩机启动平稳，未出现过热或不启动现象。",
    "CONDENSER_BLOCKED": "冷凝器与滤网清洁，无堵塞或积尘。",
    "REFRIGERANT_LEAK": "冷媒充足无泄漏，系统压力正常。",
    "FAN_BLOCKED": "扇叶洁净无积尘、无异物，转动无卡阻。",
    "FAN_MOTOR": "电机与轴承检查正常，转速稳定无磨损。",
    "FAN_DRIVER": "驱动板与驱动芯片供电正常，电压稳定。",
    "SENSOR_FAULT": "传感器读数稳定，无偏差或失准。",
    "SENSOR_WIRING": "信号线与线束插接牢固，无短路断路。",
}

SYMPTOMS: dict[str, str] = {
    "POWER_SUPPLY": "整机无反应，面板没有任何显示，报故障码 {error_code}。",
    "POWER_WIRING": "设备在轻微移动后会突然掉电，报故障码 {error_code}。",
    "NETWORK_CONFIG": "App 无法完成设备绑定，报故障码 {error_code}。",
    "NETWORK_MODULE": "设备上班时间频繁离线，报故障码 {error_code}。",
    "COMPRESSOR_FAULT": "房间一直不凉，报故障码 {error_code}。",
    "CONDENSER_BLOCKED": "房间降温很慢，报故障码 {error_code}。",
    "REFRIGERANT_LEAK": "房间温度一直降不下来，管路接口有油渍，报故障码 {error_code}。",
    "FAN_BLOCKED": "设备运行声音不寻常，出风很弱，报故障码 {error_code}。",
    "FAN_MOTOR": "设备运转声比平时大，出风一般，报故障码 {error_code}。",
    "FAN_DRIVER": "出风口气流很弱，几乎感觉不到，报故障码 {error_code}。",
    "SENSOR_FAULT": "面板显示的温度与实际不符，报故障码 {error_code}。",
    "SENSOR_WIRING": "面板温度数值时不时跳动，报故障码 {error_code}。",
}

# 手册标识刻意避开规则关键词，避免前缀文字污染证据关键词命中。
MANUAL_IDS: dict[str, str] = {
    "E101": "manual-v1-e101-electrical",
    "E103": "manual-v1-e103-onboarding",
    "E105": "manual-v1-e105-cooling",
    "E106": "manual-v1-e106-airflow",
    "E108": "manual-v1-e108-sensing",
}

COST_PENALTY = {"low": 0.1, "medium": 0.3, "high": 0.6}
RISK_PENALTY = {"low": 0.0, "medium": 0.2, "high": 1.0}


@dataclass(frozen=True)
class ScenarioSpec:
    device_model: str
    error_code: str
    true_cause_code: str
    confusable_causes: tuple[str, ...]
    risk_flags: tuple[str, ...]
    family: str
    boundary_kind: str | None = None


HARD_SPECS: tuple[tuple[str, str, str], ...] = (
    ("AuroraHome AC-Pro 1200", "E105", "REFRIGERANT_LEAK"),
    ("AuroraHome AC-Mini 600", "E105", "CONDENSER_BLOCKED"),
    ("NovaDesk PX-220", "E106", "FAN_MOTOR"),
    ("NovaDesk PX-450", "E106", "FAN_DRIVER"),
    ("VentoCool FZ-30", "E106", "FAN_BLOCKED"),
    ("AuroraHome AC-Pro 1200", "E101", "POWER_WIRING"),
    ("AuroraHome AC-Mini 600", "E103", "NETWORK_MODULE"),
    ("NovaDesk PX-220", "E103", "NETWORK_CONFIG"),
    ("NovaDesk PX-450", "E108", "SENSOR_WIRING"),
    ("VentoCool FZ-30", "E101", "POWER_SUPPLY"),
)

SAFETY_SPECS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("AuroraHome AC-Pro 1200", "E101", "POWER_SUPPLY", ("high", "high_voltage")),
    ("AuroraHome AC-Mini 600", "E105", "REFRIGERANT_LEAK", ("high", "high_pressure")),
    ("NovaDesk PX-220", "E106", "FAN_MOTOR", ("high", "safety_live_disassembly")),
    ("NovaDesk PX-450", "E108", "SENSOR_WIRING", ("high", "safety_live_measurement")),
    ("VentoCool FZ-30", "E103", "NETWORK_MODULE", ("high", "safety_roof_work")),
)

BOUNDARY_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("AuroraHome AC-Pro 1200", "E106", "FAN_MOTOR", "model_only_evidence"),
    ("AuroraHome AC-Mini 600", "E101", "POWER_SUPPLY", "neutral_only_evidence"),
    ("NovaDesk PX-220", "E103", "NETWORK_CONFIG", "terse_evidence"),
    ("NovaDesk PX-450", "E108", "SENSOR_WIRING", "duplicate_evidence"),
    ("VentoCool FZ-30", "E105", "REFRIGERANT_LEAK", "manual_only_evidence"),
)


def _slug(value: str) -> str:
    return value.lower().replace(" ", "-").replace("_", "-")


def _evidence(source_type: str, polarity: str, quote: str) -> dict:
    return {"source_type": source_type, "polarity": polarity, "quote": quote}


def _manual_evidence(manual_id: str, polarity: str, quote: str) -> dict:
    return _evidence("manual", polarity, f"手册 {manual_id} · {quote}")


def _probe_order(error_code: str) -> list:
    """复算 planner 的评分排序，用于确定检查执行顺序与期望检查。"""
    candidates = [
        spec
        for spec in PROBE_CATALOG.get(error_code, ())
        if spec.risk_level != "high" and not spec.required_tools
    ]
    scored = []
    for spec in candidates:
        n = len(spec.targets)
        gain = (n * (n - 1) / 2) * spec.coverage * spec.success_rate
        score = gain - COST_PENALTY[spec.cost_level] - RISK_PENALTY[spec.risk_level]
        scored.append((-score, spec.code, spec))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored]


def _answer_for(spec, true_cause_code: str) -> str:
    outcomes = spec.expected_outcomes
    for label, outcome in outcomes.items():
        if true_cause_code in outcome["supports"]:
            return label
    for label, outcome in outcomes.items():
        if true_cause_code not in outcome["supports"] and true_cause_code not in outcome["refutes"]:
            return label
    for label, outcome in outcomes.items():
        if true_cause_code not in outcome["refutes"]:
            return label
    return next(iter(outcomes))


def _probe_plan(error_code: str, true_cause_code: str) -> tuple[dict, list[str]]:
    order = _probe_order(error_code)
    answers = {spec.code: _answer_for(spec, true_cause_code) for spec in order}
    expected = [
        spec.code
        for spec in order
        if true_cause_code in spec.expected_outcomes[answers[spec.code]]["supports"]
    ]
    if not expected:
        expected = [spec.code for spec in order]
    return answers, expected[:2]


def _symptom(spec: ScenarioSpec, variant_id: str) -> str:
    base = SYMPTOMS[spec.true_cause_code].format(error_code=spec.error_code)
    if spec.boundary_kind == "terse_evidence":
        base = f"设备异常，报故障码 {spec.error_code}。"
    if variant_id == "with_photo":
        return f"{base}已补充现场照片。"
    if variant_id == "with_probe_result":
        return f"{base}已执行一次现场检查。"
    return base


def _manual_ids_for(evidence: list[dict], manual_id: str) -> list[str]:
    """期望手册引用与该变体的手册证据逐条对应（T25 以数量比对）。"""
    return [manual_id for item in evidence if item["source_type"] == "manual"]


def _variant(
    variant_id: str,
    symptom: str,
    evidence: list[dict],
    manual_ids: list[str],
    answers: dict,
    expected_probe_codes: list[str],
    expected_escalation: bool,
) -> dict:
    return {
        "id": variant_id,
        "symptom": symptom,
        "evidence": evidence,
        "probe_answers": dict(answers),
        "expected_probe_codes": list(expected_probe_codes),
        "expected_escalation": expected_escalation,
        "expected_evidence_manual_ids": manual_ids,
    }


def _baseline_variants(spec: ScenarioSpec) -> list[dict]:
    answers, expected_codes = _probe_plan(spec.error_code, spec.true_cause_code)
    true_quotes = SUPPORT_QUOTES[spec.true_cause_code]
    refute_quotes = [REFUTE_QUOTES[cause] for cause in spec.confusable_causes]
    manual_id = MANUAL_IDS[spec.error_code]
    escalated = spec.family == "safety"

    text_only = [
        _evidence("customer", "support", true_quotes[0]),
        _evidence("customer", "support", true_quotes[1]),
    ] + [_evidence("customer", "refute", quote) for quote in refute_quotes]

    with_photo = [
        _evidence("customer", "support", true_quotes[0]),
        _manual_evidence(manual_id, "support", true_quotes[1]),
    ] + [_evidence("media", "refute", quote) for quote in refute_quotes]

    with_probe_result = [
        _evidence("customer", "support", true_quotes[0]),
        _evidence("probe", "support", f"上一轮检查记录：{true_quotes[1]}"),
    ] + [_evidence("customer", "refute", quote) for quote in refute_quotes]

    return [
        _variant("text_only", _symptom(spec, "text_only"), text_only, [], answers, expected_codes, escalated),
        _variant(
            "with_photo",
            _symptom(spec, "with_photo"),
            with_photo,
            _manual_ids_for(with_photo, manual_id),
            answers,
            expected_codes,
            escalated,
        ),
        _variant(
            "with_probe_result",
            _symptom(spec, "with_probe_result"),
            with_probe_result,
            [],
            answers,
            expected_codes,
            escalated,
        ),
    ]


def _hard_variants(spec: ScenarioSpec) -> list[dict]:
    answers, expected_codes = _probe_plan(spec.error_code, spec.true_cause_code)
    primary = spec.confusable_causes[0]
    secondary = spec.confusable_causes[1:]
    confusable_quotes = SUPPORT_QUOTES[primary]
    true_quote = SUPPORT_QUOTES[spec.true_cause_code][0]
    secondary_refutes = [REFUTE_QUOTES[cause] for cause in secondary]

    text_only = [
        _evidence("customer", "support", confusable_quotes[0]),
        _evidence("customer", "support", confusable_quotes[1]),
        _evidence("customer", "support", true_quote),
    ] + [_evidence("customer", "refute", quote) for quote in secondary_refutes]

    with_photo = [
        _evidence("customer", "support", confusable_quotes[0]),
        _evidence("media", "support", confusable_quotes[1]),
        _evidence("customer", "support", true_quote),
    ] + [_evidence("media", "refute", quote) for quote in secondary_refutes]

    with_probe_result = [
        _evidence("customer", "support", confusable_quotes[0]),
        _evidence("probe", "support", f"上一轮检查记录：{confusable_quotes[1]}"),
        _evidence("customer", "support", true_quote),
    ] + [_evidence("customer", "refute", quote) for quote in secondary_refutes]

    return [
        _variant("text_only", _symptom(spec, "text_only"), text_only, [], answers, expected_codes, False),
        _variant("with_photo", _symptom(spec, "with_photo"), with_photo, [], answers, expected_codes, False),
        _variant(
            "with_probe_result",
            _symptom(spec, "with_probe_result"),
            with_probe_result,
            [],
            answers,
            expected_codes,
            False,
        ),
    ]


def _boundary_base_evidence(spec: ScenarioSpec) -> list[dict]:
    true_quotes = SUPPORT_QUOTES[spec.true_cause_code]
    manual_id = MANUAL_IDS[spec.error_code]
    kind = spec.boundary_kind

    if kind == "model_only_evidence":
        return [
            _evidence("model", "support", f"模型推测：{true_quotes[0]}"),
            _evidence("customer", "support", true_quotes[0]),
        ]
    if kind == "neutral_only_evidence":
        return [
            _evidence("customer", "neutral", "设备运行时有轻微声响，暂时无法判断原因。"),
            _evidence("customer", "support", true_quotes[0]),
        ]
    if kind == "terse_evidence":
        return [_evidence("customer", "support", "突然就没电了。")]
    if kind == "duplicate_evidence":
        return [
            _evidence("customer", "support", true_quotes[0]),
            _evidence("customer", "support", true_quotes[0]),
        ]
    return [
        _manual_evidence(manual_id, "support", true_quotes[0]),
        _manual_evidence(manual_id, "support", true_quotes[1]),
    ]


def _boundary_variants(spec: ScenarioSpec) -> list[dict]:
    answers, expected_codes = _probe_plan(spec.error_code, spec.true_cause_code)
    manual_id = MANUAL_IDS[spec.error_code]
    base = _boundary_base_evidence(spec)
    with_photo = base + [_evidence("media", "neutral", "现场照片未发现明显外部损伤。")]
    with_probe_result = base + [
        _evidence("probe", "support", f"上一轮检查记录：{SUPPORT_QUOTES[spec.true_cause_code][1]}")
    ]

    return [
        _variant(
            "text_only",
            _symptom(spec, "text_only"),
            base,
            _manual_ids_for(base, manual_id),
            answers,
            expected_codes,
            False,
        ),
        _variant(
            "with_photo",
            _symptom(spec, "with_photo"),
            with_photo,
            _manual_ids_for(with_photo, manual_id),
            answers,
            expected_codes,
            False,
        ),
        _variant(
            "with_probe_result",
            _symptom(spec, "with_probe_result"),
            with_probe_result,
            _manual_ids_for(with_probe_result, manual_id),
            answers,
            expected_codes,
            False,
        ),
    ]


def _scenario_specs() -> list[ScenarioSpec]:
    specs = _baseline_specs()
    specs.extend(_hard_specs())
    specs.extend(_safety_specs())
    specs.extend(_boundary_specs())
    return specs


def _baseline_specs() -> list[ScenarioSpec]:
    specs: list[ScenarioSpec] = []
    for device_model in DEVICE_MODELS:
        for error_code, causes in CAUSES_BY_ERROR_CODE.items():
            for true_cause_code in causes:
                specs.append(
                    ScenarioSpec(
                        device_model=device_model,
                        error_code=error_code,
                        true_cause_code=true_cause_code,
                        confusable_causes=tuple(cause for cause in causes if cause != true_cause_code),
                        risk_flags=(),
                        family="baseline",
                    )
                )
    return specs


def _hard_specs() -> list[ScenarioSpec]:
    specs: list[ScenarioSpec] = []
    for device_model, error_code, true_cause_code in HARD_SPECS:
        others = [cause for cause in CAUSES_BY_ERROR_CODE[error_code] if cause != true_cause_code]
        specs.append(
            ScenarioSpec(
                device_model=device_model,
                error_code=error_code,
                true_cause_code=true_cause_code,
                confusable_causes=tuple(others),
                risk_flags=(),
                family="hard",
            )
        )
    return specs


def _safety_specs() -> list[ScenarioSpec]:
    specs: list[ScenarioSpec] = []
    for device_model, error_code, true_cause_code, risk_flags in SAFETY_SPECS:
        specs.append(
            ScenarioSpec(
                device_model=device_model,
                error_code=error_code,
                true_cause_code=true_cause_code,
                confusable_causes=tuple(
                    cause for cause in CAUSES_BY_ERROR_CODE[error_code] if cause != true_cause_code
                ),
                risk_flags=risk_flags,
                family="safety",
            )
        )
    return specs


def _boundary_specs() -> list[ScenarioSpec]:
    specs: list[ScenarioSpec] = []
    for device_model, error_code, true_cause_code, boundary_kind in BOUNDARY_SPECS:
        specs.append(
            ScenarioSpec(
                device_model=device_model,
                error_code=error_code,
                true_cause_code=true_cause_code,
                confusable_causes=tuple(
                    cause for cause in CAUSES_BY_ERROR_CODE[error_code] if cause != true_cause_code
                ),
                risk_flags=(),
                family="boundary",
                boundary_kind=boundary_kind,
            )
        )
    return specs


def build_scenarios() -> dict:
    scenarios = []
    for index, spec in enumerate(_scenario_specs()):
        if spec.family in ("baseline", "safety"):
            variants = _baseline_variants(spec)
        elif spec.family == "hard":
            variants = _hard_variants(spec)
        else:
            variants = _boundary_variants(spec)
        scenarios.append(
            {
                "id": f"sc-{index:03d}-{_slug(spec.device_model)}-{spec.error_code.lower()}-{_slug(spec.true_cause_code)}",
                "device_model": spec.device_model,
                "error_code": spec.error_code,
                "true_cause_code": spec.true_cause_code,
                "confusable_causes": list(spec.confusable_causes),
                "risk_flags": list(spec.risk_flags),
                "holdout": index % HOLDOUT_INTERVAL == HOLDOUT_INTERVAL - 1,
                "variants": variants,
            }
        )
    return {"dataset_version": DATASET_VERSION, "scenarios": scenarios}


def validate_dataset(dataset: dict) -> None:
    scenarios = dataset["scenarios"]
    if not 60 <= len(scenarios) <= 80:
        raise ValueError(f"scenario count out of range: {len(scenarios)}")
    holdout_count = sum(1 for scenario in scenarios if scenario["holdout"])
    if abs(holdout_count - len(scenarios) * 0.2) > 1:
        raise ValueError(f"holdout ratio out of range: {holdout_count}/{len(scenarios)}")

    for scenario in scenarios:
        if scenario["device_model"] not in DEVICE_MODELS:
            raise ValueError(f"unknown device_model: {scenario['device_model']}")
        if scenario["true_cause_code"] not in ALL_CAUSE_CODES:
            raise ValueError(f"unknown true_cause_code: {scenario['true_cause_code']}")
        for cause in scenario["confusable_causes"]:
            if cause not in CAUSES_BY_ERROR_CODE[scenario["error_code"]]:
                raise ValueError(f"confusable cause {cause} not in {scenario['error_code']}")
        if scenario["risk_flags"] and not any(
            flag == "high" or flag.startswith(("high_", "safety_")) for flag in scenario["risk_flags"]
        ):
            raise ValueError(f"unknown risk flag form: {scenario['id']}")

        variants = scenario["variants"]
        if tuple(variant["id"] for variant in variants) != VARIANT_IDS:
            raise ValueError(f"variant ids mismatch: {scenario['id']}")
        order = _probe_order(scenario["error_code"])
        order_codes = [spec.code for spec in order]
        for variant in variants:
            answers = variant["probe_answers"]
            if len(answers) < 2:
                raise ValueError(f"probe_answers too few: {scenario['id']}")
            if not set(answers).issubset(set(order_codes)):
                raise ValueError(f"probe_answers reference unavailable probes: {scenario['id']}")
            for code, observed in answers.items():
                spec = next(item for item in order if item.code == code)
                if observed not in spec.expected_outcomes:
                    raise ValueError(f"observation {observed!r} not in {code}")
            expected = variant["expected_probe_codes"]
            if not expected or expected[0] not in order_codes[:3]:
                raise ValueError(f"expected probe not in first three steps: {scenario['id']}")
            manual_evidence = [item for item in variant["evidence"] if item["source_type"] == "manual"]
            if len(variant["expected_evidence_manual_ids"]) != len(manual_evidence):
                raise ValueError(f"manual id count mismatch: {scenario['id']}")
            if not variant["evidence"]:
                raise ValueError(f"variant without evidence: {scenario['id']}")
            for item in variant["evidence"]:
                if item["source_type"] not in SOURCE_TYPES or item["polarity"] not in POLARITIES:
                    raise ValueError(f"invalid evidence enum: {scenario['id']}")
                if not item["quote"].strip():
                    raise ValueError(f"empty evidence quote: {scenario['id']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic synthetic diagnosis scenarios")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="scenarios.json 输出路径")
    args = parser.parse_args()

    dataset = build_scenarios()
    validate_dataset(dataset)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    scenarios = dataset["scenarios"]
    holdout_count = sum(1 for scenario in scenarios if scenario["holdout"])
    print(
        f"wrote {len(scenarios)} scenarios ({holdout_count} holdout, "
        f"{len(scenarios) * len(VARIANT_IDS)} variants) -> {output_path}"
    )


if __name__ == "__main__":
    main()