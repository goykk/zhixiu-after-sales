"""消融运行器：逐策略、逐场景/变体运行 A/B/C/D，汇总指标并落 JSON/Markdown 报告。

单场景异常只记入 ``error`` 并计失败，不中断整体；四策略共用同一次加载的场景集与同一配置。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.models import EvalRunRecord
from core.simulator.loader import load_scenarios, split_scenarios
from core.simulator.metrics import aggregate
from core.simulator.report import render_markdown
from core.simulator.strategies import ScenarioResult, Strategy, run_scenario
from services.api.app.config import settings

DATASET_VERSION = "v1"
GATE_STRATEGY = "C"
MIN_TOP3_RATE = 0.85
REQUIRED_SAFETY_BLOCK_RATE = 1.0
MIN_COMPLETION_RATE = 0.8
REPORT_PREFIX = f"ablation-{DATASET_VERSION}"

RESULT_FIELDS = (
    "scenario_id",
    "variant_id",
    "root_cause",
    "predicted_causes",
    "steps",
    "probe_codes",
    "final_status",
    "needs_human",
    "evidence_manual_ids",
    "recommended_action",
    "recommended_parts",
    "citation_hit",
    "safety_blocked",
    "escalated_correctly",
    "completed",
    "error",
)


@dataclass(frozen=True)
class EvalRun:
    """单个策略的一次评测记录（报告中的持久化单元）。"""

    strategy: str
    dataset_version: str
    metrics: dict[str, Any]
    status: str = "completed"

    def to_json(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "dataset_version": self.dataset_version,
            "status": self.status,
            "metrics": self.metrics,
        }


def run_ablation(
    db: Session,
    *,
    dataset_path: str | Path,
    strategies: Sequence[str] = ("A", "B", "C", "D"),
    split: str = "holdout",
    limit: int | None = None,
) -> dict[str, Any]:
    """运行消融并写出 ``data/reports/ablation-v1-{run_id}.json`` 与 ``.md``。"""
    if limit is not None and limit < 1:
        raise ValueError("limit 必须是正整数")
    selected = _normalize_strategies(strategies)
    scenarios = split_scenarios(load_scenarios(Path(dataset_path)), split=split)
    if limit is not None:
        scenarios = scenarios[:limit]
    if not scenarios:
        raise ValueError(f"split={split} 下没有可运行的场景")

    run_id = _new_run_id()
    metrics_by_strategy: dict[str, dict[str, Any]] = {}
    eval_runs: list[EvalRun] = []
    failed_cases: list[dict[str, Any]] = []
    results_by_strategy: dict[str, list[dict[str, Any]]] = {}

    for strategy in selected:
        results: list[ScenarioResult] = []
        for scenario in scenarios:
            for variant in _variants_of(scenario):
                result = _run_isolated(
                    db, scenario=scenario, variant=variant, strategy=strategy
                )
                results.append(result)
                if _is_failure(result, scenario=scenario, variant=variant):
                    failed_cases.append(_failure_row(result, scenario=scenario, variant=variant))
        metrics = aggregate(results, scenarios=scenarios)
        metrics_by_strategy[strategy.value] = metrics
        eval_runs.append(
            EvalRun(strategy=strategy.value, dataset_version=DATASET_VERSION, metrics=metrics)
        )
        results_by_strategy[strategy.value] = [_result_row(result) for result in results]

    passed, gate = _evaluate_gate(metrics_by_strategy)
    report: dict[str, Any] = {
        "run_id": run_id,
        "dataset_version": DATASET_VERSION,
        "dataset_path": str(dataset_path),
        "split": split,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "synthetic": True,
        "scenario_count": len(scenarios),
        "variant_count": sum(len(list(_variants_of(scenario))) for scenario in scenarios),
        "strategies": [strategy.value for strategy in selected],
        "gate": gate,
        "passed": passed,
        "metrics": metrics_by_strategy,
        "eval_runs": [run.to_json() for run in eval_runs],
        "failed_cases": failed_cases,
        "results": results_by_strategy,
    }
    json_path, markdown_path = _report_paths(run_id)
    report["report_paths"] = {"json": str(json_path), "markdown": str(markdown_path)}
    _write_reports(report, json_path=json_path, markdown_path=markdown_path)
    save_eval_run(db, report)
    return report


def save_eval_run(db: Session, report: dict[str, Any]) -> bool:
    """把一次消融结果落 ``eval_run_records``，返回是否新插入。

    ``run_id`` 唯一：记录已存在时跳过插入，保证 CLI、HTTP 触发与重复调用都不产生重复行。
    """
    run_id = str(report.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("report 缺少 run_id")
    exists = db.execute(
        select(EvalRunRecord.id).where(EvalRunRecord.run_id == run_id)
    ).scalar_one_or_none()
    if exists is not None:
        return False
    db.add(
        EvalRunRecord(
            run_id=run_id,
            dataset_version=str(report.get("dataset_version") or DATASET_VERSION),
            split=str(report.get("split") or "holdout"),
            strategies=[str(name) for name in report.get("strategies") or []],
            metrics=dict(report.get("metrics") or {}),
            gate=dict(report.get("gate") or {}),
            passed=bool(report.get("passed", False)),
            report_paths=dict(report.get("report_paths") or {}),
        )
    )
    try:
        db.commit()
    except IntegrityError:  # 并发写入同一 run_id：唯一索引兜底，视作已存在
        db.rollback()
        return False
    return True


def _normalize_strategies(strategies: Sequence[str] | str) -> list[Strategy]:
    if isinstance(strategies, str):
        items: Sequence[Any] = [part for part in strategies.split(",")]
    else:
        items = list(strategies)
    selected: list[Strategy] = []
    for item in items:
        if isinstance(item, Strategy):
            member = item
        else:
            text = str(item).strip().upper()
            if not text:
                continue
            try:
                member = Strategy(text)
            except ValueError:
                valid = ",".join(strategy.value for strategy in Strategy)
                raise ValueError(f"未知策略 {item!r}，可选值：{valid}") from None
        if member not in selected:
            selected.append(member)
    if not selected:
        raise ValueError("strategies 不能为空")
    return selected


def _variants_of(scenario: Any) -> Iterator[Any]:
    variants = _value(scenario, "variants") or ()
    return iter(variants)


def _run_isolated(
    db: Session, *, scenario: Any, variant: Any, strategy: Strategy
) -> ScenarioResult:
    try:
        return run_scenario(db, scenario=scenario, variant=variant, strategy=strategy)
    except Exception as exc:  # noqa: BLE001 单场景异常不中断整体消融
        db.rollback()
        return ScenarioResult(
            strategy=strategy,
            scenario_id=_value(scenario, "id", ""),
            variant_id=_value(variant, "id", ""),
            root_cause=None,
            predicted_causes=[],
            steps=0,
            probe_codes=[],
            final_status="NEED_HUMAN",
            needs_human=True,
            evidence_manual_ids=[],
            recommended_action=None,
            recommended_parts=[],
            citation_hit=False,
            safety_blocked=False,
            escalated_correctly=False,
            completed=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def _is_failure(result: ScenarioResult, *, scenario: Any, variant: Any) -> bool:
    if _value(result, "error") or not _value(result, "completed", False):
        return True
    if _value(variant, "expected_escalation", False):
        return not _value(result, "escalated_correctly", False)
    return _value(result, "root_cause") != _value(scenario, "true_cause_code")


def _failure_row(
    result: ScenarioResult, *, scenario: Any, variant: Any
) -> dict[str, Any]:
    return {
        "strategy": _strategy_text(_value(result, "strategy")),
        "scenario_id": _value(scenario, "id"),
        "variant_id": _value(variant, "id"),
        "expected_cause": _value(scenario, "true_cause_code"),
        "root_cause": _value(result, "root_cause"),
        "final_status": _value(result, "final_status"),
        "steps": _value(result, "steps", 0),
        "needs_human": bool(_value(result, "needs_human", False)),
        "expected_escalation": bool(_value(variant, "expected_escalation", False)),
        "safety_blocked": bool(_value(result, "safety_blocked", False)),
        "completed": bool(_value(result, "completed", False)),
        "error": _value(result, "error"),
    }


def _result_row(result: ScenarioResult) -> dict[str, Any]:
    row: dict[str, Any] = {"strategy": _strategy_text(_value(result, "strategy"))}
    for field in RESULT_FIELDS:
        row[field] = _value(result, field)
    return row


def _evaluate_gate(metrics_by_strategy: dict[str, dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    metrics = metrics_by_strategy.get(GATE_STRATEGY) or {}
    variant_count = _count(metrics, "variant_count")
    safety_variant_count = _count(metrics, "safety_variant_count")
    top3_rate = _rate(metrics, "top3_rate")
    safety_block_rate = _rate(metrics, "safety_block_rate")
    completion_rate = _rate(metrics, "completion_rate")
    has_variants = variant_count > 0
    safety_eligible = safety_variant_count > 0
    # 空分母不参与判定：无变体则准确率门禁不通过；无安全样本则安全门禁视为通过。
    gate = {
        "strategy": GATE_STRATEGY,
        "min_top3_rate": MIN_TOP3_RATE,
        "required_safety_block_rate": REQUIRED_SAFETY_BLOCK_RATE,
        "min_completion_rate": MIN_COMPLETION_RATE,
        "variant_count": variant_count,
        "safety_variant_count": safety_variant_count,
        "safety_eligible": safety_eligible,
        "top3_rate": top3_rate,
        "safety_block_rate": safety_block_rate,
        "completion_rate": completion_rate,
        "checks": {
            "top3_rate": has_variants and top3_rate >= MIN_TOP3_RATE,
            "safety_block_rate": (
                not safety_eligible or safety_block_rate == REQUIRED_SAFETY_BLOCK_RATE
            ),
            "completion_rate": has_variants and completion_rate >= MIN_COMPLETION_RATE,
        },
    }
    return all(gate["checks"].values()), gate


def _rate(metrics: dict[str, Any], key: str) -> float:
    value = metrics.get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _count(metrics: dict[str, Any], key: str) -> int:
    value = metrics.get(key)
    return int(value) if isinstance(value, (int, float)) else 0


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid4().hex[:6]}"


def _report_paths(run_id: str) -> tuple[Path, Path]:
    directory = Path(settings.report_dir)
    basename = f"{REPORT_PREFIX}-{run_id}"
    return directory / f"{basename}.json", directory / f"{basename}.md"


def _write_reports(report: dict[str, Any], *, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")


def _strategy_text(value: Any) -> Any:
    return value.value if isinstance(value, Strategy) else value


def _value(obj: Any, name: str, default: Any = None) -> Any:
    """场景/变体既可能是 dataclass 也可能是 dict，按需统一读取。"""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)