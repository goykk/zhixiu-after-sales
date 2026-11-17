"""消融报告的 Markdown 渲染：四策略对比表、门禁结论与失败案例。"""

from __future__ import annotations

from typing import Any

SYNTHETIC_DISCLAIMER = (
    "本报告基于合成场景数据与模拟运行结果生成（非真实设备、非真实维修记录），"
    "仅用于比较 A/B/C/D 策略在同一场景集上的相对表现。"
)

METRIC_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("top1_rate", "Top-1", "rate"),
    ("top3_rate", "Top-3", "rate"),
    ("avg_steps", "平均检查步数", "number"),
    ("early_probe_rate", "前3步覆盖", "rate"),
    ("unnecessary_parts_rate", "不必要换件率", "rate"),
    ("safety_block_rate", "安全拦截率", "rate"),
    ("escalation_rate", "应升级转人工率", "rate"),
    ("citation_accuracy", "引用准确率", "rate"),
    ("completion_rate", "完成率", "rate"),
)

MAX_FAILED_ROWS = 40
GATE_LABELS = (
    ("top3_rate", "Top-3 ≥ 85%", "min_top3_rate"),
    ("safety_block_rate", "安全拦截率 = 100%", "required_safety_block_rate"),
    ("completion_rate", "完成率 ≥ 80%", "min_completion_rate"),
)


def render_markdown(report: dict[str, Any]) -> str:
    """把 ``run_ablation`` 的返回结果渲染为简体中文 Markdown。"""
    lines: list[str] = []
    dataset_version = report.get("dataset_version", "v1")
    passed = bool(report.get("passed"))

    lines.append(f"# 诊断场景消融报告（{dataset_version}）")
    lines.append("")
    lines.append(f"> **合成数据声明**：{SYNTHETIC_DISCLAIMER}")
    lines.append("")
    lines.append(f"- 运行 ID：`{report.get('run_id', '-')}`")
    lines.append(f"- 拆分：`{report.get('split', '-')}`")
    lines.append(f"- 场景数：{report.get('scenario_count', '-')}")
    lines.append(f"- 变体数：{report.get('variant_count', '-')}")
    lines.append(f"- 策略：{', '.join(report.get('strategies') or []) or '-'}")
    lines.append(f"- 生成时间（UTC）：{report.get('generated_at', '-')}")
    lines.append("")

    metrics_by_strategy = report.get("metrics") or {}
    lines.extend(_render_metrics_table(metrics_by_strategy))
    lines.append("")
    lines.extend(_render_diagnosable(metrics_by_strategy))
    lines.append("")
    lines.extend(_render_gate(report.get("gate") or {}, passed))
    lines.append("")
    lines.extend(_render_failed_cases(report.get("failed_cases") or []))

    paths = report.get("report_paths") or {}
    if paths:
        lines.append("")
        lines.append(f"报告文件：`{paths.get('json', '-')}`、`{paths.get('markdown', '-')}`")
    lines.append("")
    return "\n".join(lines)


def _render_metrics_table(metrics_by_strategy: dict[str, Any]) -> list[str]:
    header = "| 策略 | " + " | ".join(label for _, label, _ in METRIC_COLUMNS) + " |"
    divider = "| --- | " + " | ".join("---:" for _ in METRIC_COLUMNS) + " |"
    lines = ["## 四策略对比", "", header, divider]
    strategies = list(metrics_by_strategy)
    if not strategies:
        lines.append("| - | " + " | ".join("-" for _ in METRIC_COLUMNS) + " |")
        return lines
    for strategy in strategies:
        metrics = metrics_by_strategy[strategy] or {}
        cells = [_format_metric(metrics.get(key), kind) for key, _, kind in METRIC_COLUMNS]
        lines.append(f"| {strategy} | " + " | ".join(cells) + " |")
    return lines


def _render_diagnosable(metrics_by_strategy: dict[str, Any]) -> list[str]:
    lines = [
        "## 诊断口径",
        "",
        "| 策略 | 计分变体 | 可诊断变体 | 应转人工变体 | 可诊断 Top-1 | 可诊断 Top-3 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for strategy, metrics in metrics_by_strategy.items():
        metrics = metrics or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    str(strategy),
                    _cell(metrics.get("variant_count")),
                    _cell(metrics.get("diagnosable_variant_count")),
                    _cell(metrics.get("escalation_variant_count")),
                    _format_metric(metrics.get("top1_rate_diagnosable"), "rate"),
                    _format_metric(metrics.get("top3_rate_diagnosable"), "rate"),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append(
        "应转人工变体按契约不产出根因，仍计入上表 Top-1/Top-3 分母（保守口径）；"
        "本表剔除后单列，仅用于口径说明，不参与门禁。"
    )
    return lines


def _render_gate(gate: dict[str, Any], passed: bool) -> list[str]:
    strategy = gate.get("strategy", "C")
    lines = [
        "## 门禁结论",
        "",
        f"- 结果：**{'PASSED' if passed else 'FAILED'}**（门槛策略：{strategy}）",
    ]
    checks = gate.get("checks") or {}
    safety_eligible = gate.get("safety_eligible", True)
    for key, label, threshold_key in GATE_LABELS:
        if key == "safety_block_rate" and not safety_eligible:
            lines.append(f"- {label}：N/A（本子集无高风险样本）")
            continue
        actual = _format_metric(gate.get(key), "rate")
        mark = "✅" if checks.get(key) else "❌"
        threshold = _format_metric(gate.get(threshold_key), "rate")
        lines.append(f"- {mark} {label}：{actual}（门槛 {threshold}）")
    return lines


def _render_failed_cases(failed_cases: list[dict[str, Any]]) -> list[str]:
    lines = ["## 失败案例", ""]
    if not failed_cases:
        lines.append("无失败案例。")
        return lines
    lines.append(
        f"共 {len(failed_cases)} 条（含运行错误、未完成、根因不符或应升级未升级）；"
        f"下表最多列出前 {MAX_FAILED_ROWS} 条，完整清单见同次运行的 JSON 报告。"
    )
    lines.append("")
    lines.append(
        "| 策略 | 场景 | 变体 | 期望根因 | 实际根因 | 步数 | 状态 | 错误 |"
    )
    lines.append("| --- | --- | --- | --- | --- | ---: | --- | --- |")
    for case in failed_cases[:MAX_FAILED_ROWS]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(case.get("strategy")),
                    _cell(case.get("scenario_id")),
                    _cell(case.get("variant_id")),
                    _cell(case.get("expected_cause")),
                    _cell(case.get("root_cause")),
                    _cell(case.get("steps")),
                    _cell(case.get("final_status")),
                    _cell(case.get("error")),
                ]
            )
            + " |"
        )
    return lines


def _format_metric(value: Any, kind: str) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    if kind == "rate":
        return f"{float(value) * 100:.1f}%"
    return f"{float(value):.2f}"


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ").strip()