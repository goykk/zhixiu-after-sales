"""场景集、四策略模拟、消融指标与运行器测试（C-TEST@3 / C-SIM@1 B.1–B.6）。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from core.cases.service import create_case
from core.db.models import RepairOutcome, User, WorkOrder, new_id, utcnow
from core.diagnosis.evidence import POLARITIES, SOURCE_TYPES
from core.probes.catalog import PROBE_CATALOG
from core.simulator.loader import (
    CAUSE_CODES,
    DATASET_VERSION,
    DEVICE_MODELS,
    SCENARIO_MAX,
    SCENARIO_MIN,
    VARIANT_IDS,
    Scenario,
    Variant,
    load_scenarios,
    split_scenarios,
)
from core.simulator.metrics import PARTS_REQUIRED_CAUSES, aggregate
from core.simulator.report import render_markdown
from core.simulator.runner import run_ablation
from core.simulator.strategies import ScenarioResult, run_scenario
from services.api.app.config import settings

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "data" / "scenarios" / "v1" / "scenarios.json"
MODEL = "AuroraHome AC-Pro 1200"

METRIC_KEYS = {
    "scenario_count",
    "variant_count",
    "failed_count",
    "safety_variant_count",
    "escalation_variant_count",
    "top1_rate",
    "top3_rate",
    "diagnosable_variant_count",
    "top1_rate_diagnosable",
    "top3_rate_diagnosable",
    "avg_steps",
    "early_probe_rate",
    "unnecessary_parts_rate",
    "safety_block_rate",
    "escalation_rate",
    "citation_accuracy",
    "completion_rate",
}


# --------------------------------------------------------------------------- #
# 构造工具
# --------------------------------------------------------------------------- #


def _make_variant(
    *,
    variant_id: str = "text_only",
    symptom: str,
    evidence: tuple[tuple[str, str, str], ...] = (),
    answers: dict[str, str] | None = None,
    expected_probe_codes: tuple[str, ...] = (),
    expected_escalation: bool = False,
    manual_ids: tuple[str, ...] = (),
) -> Variant:
    return Variant(
        id=variant_id,
        symptom=symptom,
        evidence=tuple(
            {"source_type": source, "polarity": polarity, "quote": quote}
            for source, polarity, quote in evidence
        ),
        probe_answers=dict(answers or {}),
        expected_probe_codes=expected_probe_codes,
        expected_escalation=expected_escalation,
        expected_evidence_manual_ids=manual_ids,
    )


def _make_scenario(
    *,
    scenario_id: str,
    error_code: str,
    true_cause: str,
    variants: tuple[Variant, ...],
    risk_flags: tuple[str, ...] = (),
    device_model: str = MODEL,
) -> Scenario:
    return Scenario(
        id=scenario_id,
        device_model=device_model,
        error_code=error_code,
        true_cause_code=true_cause,
        confusable_causes=(),
        risk_flags=risk_flags,
        holdout=False,
        variants=variants,
    )


def _agent(db) -> User:
    user = db.scalar(select(User).where(User.email == "sim-test@zhixiu.local"))
    if user is None:
        user = User(
            id=new_id(),
            email="sim-test@zhixiu.local",
            password_hash="!",
            display_name="sim-test",
            role="agent",
            status="active",
            created_at=utcnow(),
        )
        db.add(user)
        db.commit()
    return user


def _seed_history(db, *, error_code: str, cause_code: str, count: int) -> None:
    user = _agent(db)
    for index in range(count):
        case = create_case(
            db,
            user=user,
            device_model=MODEL,
            symptom="历史维修案例",
            error_code=error_code,
        )
        order = WorkOrder(
            id=new_id(),
            case_id=case.id,
            idempotency_key=f"hist-{error_code}-{cause_code}-{index}",
            status="closed",
        )
        db.add(order)
        db.flush()
        db.add(
            RepairOutcome(
                id=new_id(),
                work_order_id=order.id,
                technician_id=user.id,
                actual_cause_code=cause_code,
                action="replace_part",
                resolved=True,
            )
        )
    db.commit()


def _result(**overrides) -> ScenarioResult:
    base = {
        "strategy": "C",
        "scenario_id": "s1",
        "variant_id": "text_only",
        "root_cause": None,
        "predicted_causes": [],
        "steps": 0,
        "probe_codes": [],
        "final_status": "NEED_HUMAN",
        "needs_human": True,
        "evidence_manual_ids": [],
        "recommended_action": None,
        "recommended_parts": [],
        "citation_hit": False,
        "safety_blocked": False,
        "escalated_correctly": False,
        "completed": True,
        "error": None,
    }
    base.update(overrides)
    return ScenarioResult(**base)


def _dataset_payload() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def _write_dataset(tmp_path: Path, payload: dict | str, name: str = "scenarios.json") -> Path:
    path = tmp_path / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# B.1 场景数据
# --------------------------------------------------------------------------- #


def test_scenario_dataset_satisfies_b1_constraints():
    payload = _dataset_payload()
    scenarios = load_scenarios(DATASET_PATH)

    assert payload["dataset_version"] == DATASET_VERSION == "v1"
    assert SCENARIO_MIN <= len(scenarios) <= SCENARIO_MAX
    assert len(scenarios) == 80
    assert len({scenario.id for scenario in scenarios}) == 80
    assert sum(1 for scenario in scenarios if scenario.holdout) == 16

    for scenario in scenarios:
        assert scenario.device_model in DEVICE_MODELS
        assert scenario.true_cause_code in CAUSE_CODES
        assert scenario.error_code in PROBE_CATALOG
        assert set(scenario.confusable_causes) <= CAUSE_CODES
        assert scenario.true_cause_code not in scenario.confusable_causes
        assert len(scenario.variants) == 3
        assert {variant.id for variant in scenario.variants} == set(VARIANT_IDS)

        catalog = [spec.code for spec in PROBE_CATALOG[scenario.error_code]]
        for variant in scenario.variants:
            answers = set(variant.probe_answers)
            assert len(answers) >= 2
            assert answers <= set(catalog)
            # 期望检查至少有一个落在该故障码检查目录的前 3 位
            assert set(variant.expected_probe_codes) & set(catalog[:3])
            assert set(variant.expected_probe_codes) <= answers
            for item in variant.evidence:
                assert item["source_type"] in SOURCE_TYPES
                assert item["polarity"] in POLARITIES
                assert item["quote"].strip()


def test_safety_scenarios_expect_escalation():
    scenarios = load_scenarios(DATASET_PATH)
    safety = [
        scenario
        for scenario in scenarios
        if any(
            flag == "high" or flag.startswith("high") or flag.startswith("safety")
            for flag in scenario.risk_flags
        )
    ]

    assert len(safety) >= 5
    for scenario in safety:
        assert all(variant.expected_escalation for variant in scenario.variants)


# --------------------------------------------------------------------------- #
# B.2 loader 错误分支与切分
# --------------------------------------------------------------------------- #


def test_split_scenarios_partitions_by_holdout_flag():
    scenarios = load_scenarios(DATASET_PATH)

    holdout = split_scenarios(scenarios, "holdout")
    train = split_scenarios(scenarios, "train")
    everything = split_scenarios(scenarios, "all")

    assert len(holdout) == 16
    assert len(train) == 64
    assert len(everything) == 80
    assert all(scenario.holdout for scenario in holdout)
    assert not any(scenario.holdout for scenario in train)
    assert {scenario.id for scenario in holdout} | {
        scenario.id for scenario in train
    } == {scenario.id for scenario in everything}

    with pytest.raises(ValueError):
        split_scenarios(scenarios, "bogus")


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda payload: payload.__setitem__("scenarios", payload["scenarios"][:59]), id="too-few"),
        pytest.param(lambda payload: payload.__setitem__("scenarios", payload["scenarios"] * 2), id="too-many"),
        pytest.param(lambda payload: payload["scenarios"][0].__setitem__("variants", payload["scenarios"][0]["variants"][:2]), id="two-variants"),
        pytest.param(lambda payload: payload["scenarios"][0].__setitem__("true_cause_code", "UNKNOWN_CAUSE"), id="bad-cause"),
        pytest.param(lambda payload: payload["scenarios"][0].__setitem__("device_model", "Unknown Model"), id="bad-model"),
        pytest.param(lambda payload: [item.__setitem__("holdout", False) for item in payload["scenarios"]], id="no-holdout"),
        pytest.param(lambda payload: [item.__setitem__("holdout", True) for item in payload["scenarios"]], id="all-holdout"),
        pytest.param(lambda payload: payload["scenarios"][0]["variants"][0].__setitem__("id", "unknown_variant"), id="bad-variant-id"),
        pytest.param(lambda payload: payload["scenarios"][0]["variants"][0]["evidence"][0].__setitem__("source_type", "telepathy"), id="bad-source-type"),
    ],
)
def test_load_scenarios_rejects_invalid_dataset(tmp_path, mutate):
    payload = copy.deepcopy(_dataset_payload())
    mutate(payload)
    path = _write_dataset(tmp_path, payload)

    with pytest.raises(ValueError):
        load_scenarios(path)


def test_load_scenarios_rejects_missing_or_broken_file(tmp_path):
    with pytest.raises(ValueError):
        load_scenarios(tmp_path / "missing.json")

    broken = _write_dataset(tmp_path, "{not a valid json")
    with pytest.raises(ValueError):
        load_scenarios(broken)


# --------------------------------------------------------------------------- #
# B.3 A/B/C/D 策略差异
# --------------------------------------------------------------------------- #


def _power_case_fixture() -> tuple[Scenario, Variant]:
    variant = _make_variant(
        symptom="整机无反应，面板没有任何显示",
        evidence=(
            ("customer", "support", "电源模块无输出，供电电压异常"),
            ("customer", "support", "断开主电源后测量仍无输出，电压为 0V"),
            ("customer", "refute", "插头与接线检查正常，无松动或接触不良"),
            ("customer", "refute", "线束插接牢固，无虚接"),
        ),
        answers={
            "ASK_POWER_LED": "指示灯不亮",
            "CHECK_BREAKER": "开关正常但设备仍无电",
        },
        expected_probe_codes=("ASK_POWER_LED", "CHECK_BREAKER"),
    )
    scenario = _make_scenario(
        scenario_id="sim-e101", error_code="E101", true_cause="POWER_SUPPLY", variants=(variant,)
    )
    return scenario, variant


def test_strategy_a_and_b_conclude_without_probes(db):
    scenario, variant = _power_case_fixture()

    rule_only = run_scenario(db, scenario=scenario, variant=variant, strategy="A")
    ledger = run_scenario(db, scenario=scenario, variant=variant, strategy="B")

    assert rule_only.steps == 0
    assert rule_only.probe_codes == []
    assert rule_only.root_cause == "POWER_SUPPLY"
    assert rule_only.final_status == "DIAGNOSED"
    assert "POWER_SUPPLY" in rule_only.predicted_causes

    assert ledger.steps == 0
    assert ledger.probe_codes == []
    assert ledger.root_cause == "POWER_SUPPLY"
    assert ledger.final_status == "DIAGNOSED"
    assert ledger.completed is True


def test_strategy_c_executes_probes_and_isolates_cases(db):
    scenario, variant = _power_case_fixture()

    result = run_scenario(db, scenario=scenario, variant=variant, strategy="C")

    assert result.steps == len(result.probe_codes) > 0
    assert set(result.probe_codes) == {"ASK_POWER_LED", "CHECK_BREAKER"}
    assert result.root_cause == "POWER_SUPPLY"
    assert result.final_status == "DIAGNOSED"
    # 模拟案例在运行结束后被清理，不残留到其他场景/策略
    from core.db.models import Case

    assert db.scalar(select(Case).where(Case.error_code == "E101")) is None


def test_strategy_d_without_history_matches_c(db):
    scenario, variant = _power_case_fixture()

    baseline = run_scenario(db, scenario=scenario, variant=variant, strategy="C")
    weighted = run_scenario(db, scenario=scenario, variant=variant, strategy="D")

    assert (weighted.root_cause, weighted.steps, weighted.probe_codes, weighted.final_status) == (
        baseline.root_cause,
        baseline.steps,
        baseline.probe_codes,
        baseline.final_status,
    )


def _cooling_case_fixture() -> tuple[Scenario, Variant]:
    variant = _make_variant(
        symptom="制冷效果差，外机运行但室内不凉",
        evidence=(
            ("customer", "support", "冷凝器滤网积尘堵塞，散热不良"),
            ("customer", "support", "外机冷凝器翅片积尘堵塞，散热差"),
            ("customer", "support", "冷媒泄漏，系统压力低"),
            ("customer", "support", "冷媒泄漏迹象明显，测得压力低"),
            ("customer", "support", "压缩机不启动，运转时嗡嗡响"),
            ("customer", "support", "压机过热保护，压缩机不启动"),
        ),
        answers={
            "ASK_COOLING": "制冷间歇且外机吹热风",
            "PHOTO_PIPE_FROST": "接头结霜或有油渍",
            "CHECK_CONDENSER_CLEAN": "清理后制冷明显改善",
            "CHECK_COMPRESSOR_START": "启动后持续平稳运转",
        },
        expected_probe_codes=("ASK_COOLING", "PHOTO_PIPE_FROST"),
    )
    scenario = _make_scenario(
        scenario_id="sim-e105",
        error_code="E105",
        true_cause="CONDENSER_BLOCKED",
        variants=(variant,),
    )
    return scenario, variant


def test_strategy_d_history_weight_changes_root_cause(db):
    scenario, variant = _cooling_case_fixture()

    baseline = run_scenario(db, scenario=scenario, variant=variant, strategy="C")
    assert baseline.root_cause == "CONDENSER_BLOCKED"
    assert baseline.steps == 4
    assert set(baseline.probe_codes) == {
        "ASK_COOLING",
        "PHOTO_PIPE_FROST",
        "CHECK_CONDENSER_CLEAN",
        "CHECK_COMPRESSOR_START",
    }

    _seed_history(db, error_code="E105", cause_code="REFRIGERANT_LEAK", count=3)

    weighted = run_scenario(db, scenario=scenario, variant=variant, strategy="D")

    assert weighted.root_cause == "REFRIGERANT_LEAK"
    assert weighted.root_cause != baseline.root_cause
    assert weighted.steps == baseline.steps
    assert weighted.completed is True

    # C 不受历史影响：同一历史数据下再次运行仍给出同一结论
    again = run_scenario(db, scenario=scenario, variant=variant, strategy="C")
    assert again.root_cause == "CONDENSER_BLOCKED"


def test_safety_flags_block_all_strategies_and_escalate(db):
    variant = _make_variant(
        symptom="需要带电拆机检查",
        evidence=(("customer", "support", "机组漏电，需要带电拆机"),),
        answers={"ASK_SOUND": "有摩擦或刮擦声"},
        expected_escalation=True,
    )
    scenario = _make_scenario(
        scenario_id="sim-safety",
        error_code="E106",
        true_cause="FAN_BLOCKED",
        variants=(variant,),
        risk_flags=("high", "safety_live_disassembly"),
    )

    for strategy in ("A", "B", "C", "D"):
        result = run_scenario(db, scenario=scenario, variant=variant, strategy=strategy)
        assert result.safety_blocked is True, strategy
        assert result.needs_human is True, strategy
        assert result.escalated_correctly is True, strategy
        assert result.steps == 0, strategy
        assert result.root_cause is None, strategy
        assert result.completed is True, strategy


def test_safety_block_without_expected_escalation_is_not_counted_correctly(db):
    variant = _make_variant(
        symptom="高处作业风险",
        evidence=(("customer", "support", "需要登高处理"),),
        expected_escalation=False,
    )
    scenario = _make_scenario(
        scenario_id="sim-safety-2",
        error_code="E106",
        true_cause="FAN_BLOCKED",
        variants=(variant,),
        risk_flags=("safety_roof_work",),
    )

    result = run_scenario(db, scenario=scenario, variant=variant, strategy="C")

    assert result.safety_blocked is True
    assert result.needs_human is True
    assert result.escalated_correctly is False


# --------------------------------------------------------------------------- #
# B.4 指标公式
# --------------------------------------------------------------------------- #


def _metrics_fixture() -> tuple[list[ScenarioResult], dict[str, Scenario]]:
    scenarios = {
        "s1": _make_scenario(
            scenario_id="s1",
            error_code="E106",
            true_cause="FAN_BLOCKED",
            risk_flags=("high",),
            variants=(
                _make_variant(
                    symptom="风扇异响",
                    expected_probe_codes=("PHOTO_BLADE",),
                    expected_escalation=True,
                ),
            ),
        ),
        "s2": _make_scenario(
            scenario_id="s2",
            error_code="E101",
            true_cause="POWER_SUPPLY",
            variants=(
                _make_variant(variant_id="text_only", symptom="整机无反应"),
                _make_variant(
                    variant_id="with_photo",
                    symptom="整机无反应",
                    expected_probe_codes=("CHECK_BREAKER",),
                ),
            ),
        ),
    }
    results = [
        _result(
            scenario_id="s1",
            variant_id="text_only",
            root_cause="FAN_BLOCKED",
            predicted_causes=["FAN_BLOCKED", "FAN_MOTOR"],
            steps=2,
            probe_codes=["ASK_SOUND", "PHOTO_BLADE"],
            final_status="DIAGNOSED",
            needs_human=False,
            recommended_action="replace_part",
            citation_hit=True,
            safety_blocked=True,
            escalated_correctly=True,
            completed=True,
        ),
        _result(
            scenario_id="s2",
            variant_id="text_only",
            root_cause=None,
            predicted_causes=["POWER_WIRING"],
            steps=0,
            probe_codes=[],
            recommended_action="replace_part",
            citation_hit=False,
            escalated_correctly=False,
            completed=False,
            error="RuntimeError: boom",
        ),
        _result(
            scenario_id="s2",
            variant_id="with_photo",
            root_cause="POWER_SUPPLY",
            predicted_causes=["POWER_SUPPLY", "POWER_WIRING"],
            steps=1,
            probe_codes=["ASK_POWER_LED"],
            final_status="DIAGNOSED",
            needs_human=False,
            recommended_action="inspect_wiring",
            citation_hit=True,
            escalated_correctly=True,
            completed=True,
        ),
    ]
    return results, scenarios


def test_parts_required_causes_are_frozen():
    assert PARTS_REQUIRED_CAUSES == frozenset(
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


def test_aggregate_computes_each_metric_from_scenario_truth():
    results, scenarios = _metrics_fixture()

    metrics = aggregate(results, scenarios=scenarios)

    assert set(metrics) == METRIC_KEYS
    assert metrics["scenario_count"] == 2
    assert metrics["variant_count"] == 3
    assert metrics["failed_count"] == 1
    assert metrics["safety_variant_count"] == 1
    assert metrics["escalation_variant_count"] == 1
    assert metrics["top1_rate"] == pytest.approx(2 / 3)
    assert metrics["top3_rate"] == pytest.approx(2 / 3)
    # 3 个变体中仅 s1 声明 expected_escalation=true，可诊断口径剔除后 2 个全命中
    assert metrics["diagnosable_variant_count"] == 2
    assert metrics["top1_rate_diagnosable"] == pytest.approx(0.5)
    assert metrics["top3_rate_diagnosable"] == pytest.approx(0.5)
    assert metrics["avg_steps"] == pytest.approx(1.0)
    # 两个变体声明了期望检查，只有 s1 的 PHOTO_BLADE 落在前 3 步
    assert metrics["early_probe_rate"] == pytest.approx(0.5)
    # replace_part 且有真值：s1(FAN_BLOCKED 不需换件)、s2(POWER_SUPPLY 需换件)
    assert metrics["unnecessary_parts_rate"] == pytest.approx(1 / 3)
    assert metrics["safety_block_rate"] == pytest.approx(1.0)
    # 仅 s1 变体声明 expected_escalation=true，且被正确升级
    assert metrics["escalation_rate"] == pytest.approx(1.0)
    assert metrics["citation_accuracy"] == pytest.approx(2 / 3)
    assert metrics["completion_rate"] == pytest.approx(2 / 3)


def test_aggregate_handles_empty_input_and_missing_truth():
    empty = aggregate([])

    assert set(empty) == METRIC_KEYS
    assert empty["scenario_count"] == 0
    assert empty["variant_count"] == 0
    assert empty["failed_count"] == 0
    for key in METRIC_KEYS - {
        "scenario_count",
        "variant_count",
        "failed_count",
        "safety_variant_count",
        "escalation_variant_count",
        "diagnosable_variant_count",
    }:
        assert empty[key] == 0.0

    # 未提供真值（场景与结果都不带 true_cause_code）时不进入比例分母
    blind = aggregate([_result(scenario_id="s9", steps=2)])
    assert blind["top1_rate"] == 0.0
    assert blind["top3_rate"] == 0.0
    assert blind["avg_steps"] == pytest.approx(2.0)
    assert blind["failed_count"] == 0


def test_aggregate_accepts_results_with_embedded_truth():
    results, _ = _metrics_fixture()
    embedded = [
        ScenarioResult(**{**result.__dict__, "true_cause_code": "FAN_BLOCKED"})
        for result in results[:1]
    ]

    metrics = aggregate(embedded)

    assert metrics["top1_rate"] == 1.0
    assert metrics["top3_rate"] == 1.0
    assert metrics["completion_rate"] == 1.0


# --------------------------------------------------------------------------- #
# B.5 / B.6 运行器与报告
# --------------------------------------------------------------------------- #


def test_run_ablation_small_sample_reports_and_gate(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "report_dir", str(tmp_path))

    report = run_ablation(
        db, dataset_path=DATASET_PATH, strategies=("A", "B", "C"), split="train", limit=2
    )

    assert {"run_id", "strategies", "metrics", "failed_cases", "passed"} <= set(report)
    assert report["scenario_count"] == 2
    assert report["variant_count"] == 6
    assert report["split"] == "train"
    assert report["synthetic"] is True
    assert list(report["metrics"]) == ["A", "B", "C"]
    assert all(report["metrics"][name]["variant_count"] == 6 for name in ("A", "B", "C"))

    eval_runs = report["eval_runs"]
    assert [item["strategy"] for item in eval_runs] == ["A", "B", "C"]
    assert all(item["dataset_version"] == "v1" for item in eval_runs)
    assert all(item["status"] == "completed" for item in eval_runs)

    json_path = Path(report["report_paths"]["json"])
    markdown_path = Path(report["report_paths"]["markdown"])
    assert json_path.is_file()
    assert markdown_path.is_file()
    assert json_path.name.startswith("ablation-v1-")
    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    assert persisted["run_id"] == report["run_id"]
    assert persisted["synthetic"] is True
    assert persisted["metrics"] == report["metrics"]

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "合成数据" in markdown
    assert "## 四策略对比" in markdown
    assert "## 失败案例" in markdown
    assert "PASSED" in markdown or "FAILED" in markdown

    gate = report["gate"]
    assert gate["strategy"] == "C"
    assert report["passed"] is all(gate["checks"].values())
    assert gate["checks"]["top3_rate"] is (
        gate["variant_count"] > 0 and gate["top3_rate"] >= gate["min_top3_rate"]
    )
    assert gate["checks"]["safety_block_rate"] is (
        not gate["safety_eligible"]
        or gate["safety_block_rate"] == gate["required_safety_block_rate"]
    )
    assert gate["checks"]["completion_rate"] is (
        gate["variant_count"] > 0 and gate["completion_rate"] >= gate["min_completion_rate"]
    )


def test_run_ablation_isolates_errors_and_keeps_failed_cases(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "report_dir", str(tmp_path))

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated provider outage")

    monkeypatch.setattr("core.simulator.runner.run_scenario", _boom)

    report = run_ablation(
        db, dataset_path=DATASET_PATH, strategies=("C",), split="train", limit=1
    )

    assert report["metrics"]["C"]["failed_count"] == 3
    assert len(report["failed_cases"]) == 3
    assert all("RuntimeError" in case["error"] for case in report["failed_cases"])
    assert all(case["completed"] is False for case in report["failed_cases"])
    assert report["passed"] is False

    markdown = Path(report["report_paths"]["markdown"]).read_text(encoding="utf-8")
    assert "RuntimeError" in markdown
    assert "## 失败案例" in markdown


def test_render_markdown_lists_all_strategies_and_failed_cases():
    report = {
        "dataset_version": "v1",
        "run_id": "r1",
        "split": "holdout",
        "scenario_count": 1,
        "variant_count": 1,
        "strategies": ["A", "B", "C", "D"],
        "generated_at": "2026-01-01T00:00:00+00:00",
        "passed": False,
        "gate": {
            "strategy": "C",
            "min_top3_rate": 0.85,
            "required_safety_block_rate": 1.0,
            "min_completion_rate": 0.8,
            "top3_rate": 0.5,
            "safety_block_rate": 1.0,
            "completion_rate": 1.0,
            "checks": {
                "top3_rate": False,
                "safety_block_rate": True,
                "completion_rate": True,
            },
        },
        "metrics": {
            "A": {"top1_rate": 0.5, "top3_rate": 0.5, "avg_steps": 0},
            "B": {"top1_rate": 0.5, "top3_rate": 0.5, "avg_steps": 0},
            "C": {"top1_rate": 0.5, "top3_rate": 0.5, "avg_steps": 2.5},
            "D": {"top1_rate": 0.5, "top3_rate": 0.5, "avg_steps": 2.5},
        },
        "failed_cases": [
            {
                "strategy": "A",
                "scenario_id": "sc-001",
                "variant_id": "text_only",
                "expected_cause": "FAN_MOTOR",
                "root_cause": "FAN_BLOCKED",
                "steps": 0,
                "final_status": "DIAGNOSED",
                "error": None,
            }
        ],
    }

    markdown = render_markdown(report)

    assert "合成数据" in markdown
    assert "FAILED" in markdown
    for strategy in ("A", "B", "C", "D"):
        assert f"| {strategy} |" in markdown
    assert "sc-001" in markdown
    assert "FAN_MOTOR" in markdown