"use client";

import { Badge, Card } from "@/components/ui";
import type { EvalGate, ScenarioRunReport, StrategyMetrics } from "@/lib/types";

const STRATEGY_LABELS: Record<string, string> = {
  A: "A · 规则树",
  B: "B · 证据+假设",
  C: "C · 证据+假设+检查",
  D: "D · C+历史结果加权",
};

type MetricKind = "count" | "rate" | "steps";

const METRIC_ROWS: { key: keyof StrategyMetrics; label: string; kind: MetricKind }[] = [
  { key: "variant_count", label: "变体数", kind: "count" },
  { key: "failed_count", label: "失败数", kind: "count" },
  { key: "top1_rate", label: "top1_rate", kind: "rate" },
  { key: "top3_rate", label: "top3_rate", kind: "rate" },
  { key: "avg_steps", label: "avg_steps", kind: "steps" },
  { key: "early_probe_rate", label: "early_probe_rate", kind: "rate" },
  { key: "unnecessary_parts_rate", label: "unnecessary_parts_rate", kind: "rate" },
  { key: "safety_block_rate", label: "safety_block_rate", kind: "rate" },
  { key: "escalation_rate", label: "escalation_rate", kind: "rate" },
  { key: "citation_accuracy", label: "citation_accuracy", kind: "rate" },
  { key: "completion_rate", label: "completion_rate", kind: "rate" },
];

function formatMetric(value: number | undefined, kind: MetricKind): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  if (kind === "rate") return `${(value * 100).toFixed(1)}%`;
  if (kind === "steps") return value.toFixed(2);
  return String(value);
}

function PassedBadge({ passed }: { passed: boolean }) {
  return <Badge tone={passed ? "green" : "red"}>{passed ? "门禁通过" : "门禁未通过"}</Badge>;
}

export function SyntheticNotice() {
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
      <span className="font-medium">合成数据声明：</span>
      本页所有场景与指标均来自合成数据集（synthetic scenarios），仅用于 A/B/C/D 策略消融对比与回归门禁，
      不代表真实线上效果。
    </div>
  );
}

function GateTable({ gate }: { gate: EvalGate }) {
  const rows = [
    {
      label: "top3_rate",
      required: `≥ ${gate.min_top3_rate}`,
      actual: formatMetric(gate.top3_rate, "rate"),
      ok: gate.checks?.top3_rate,
    },
    {
      label: "safety_block_rate",
      required: `= ${gate.required_safety_block_rate}`,
      actual: formatMetric(gate.safety_block_rate, "rate"),
      ok: gate.checks?.safety_block_rate,
    },
    {
      label: "completion_rate",
      required: `≥ ${gate.min_completion_rate}`,
      actual: formatMetric(gate.completion_rate, "rate"),
      ok: gate.checks?.completion_rate,
    },
  ];
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th className="py-2 pr-4">指标</th>
          <th className="py-2 pr-4">阈值</th>
          <th className="py-2 pr-4">实测</th>
          <th className="py-2">结论</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {rows.map((row) => (
          <tr key={row.label}>
            <td className="py-2 pr-4 font-mono text-xs text-slate-700">{row.label}</td>
            <td className="py-2 pr-4 text-slate-600">{row.required}</td>
            <td className="py-2 pr-4 text-slate-900">{row.actual}</td>
            <td className="py-2">
              {row.ok === undefined ? (
                <Badge tone="neutral">未评估</Badge>
              ) : (
                <Badge tone={row.ok ? "green" : "red"}>{row.ok ? "通过" : "未通过"}</Badge>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function AblationPanel({ report }: { report: ScenarioRunReport }) {
  const strategies = report.strategies.length ? report.strategies : Object.keys(report.metrics);
  const reportPaths = Object.entries(report.report_paths ?? {});

  return (
    <div className="space-y-4">
      <Card
        title="四策略指标对比"
        description={`run_id ${report.run_id} · 数据集 ${report.dataset_version} · split ${report.split}${
          report.created_at ? ` · ${report.created_at}` : ""
        }`}
        actions={<PassedBadge passed={report.passed} />}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-2 pr-4">指标</th>
                {strategies.map((strategy) => (
                  <th key={strategy} className="py-2 pr-4">
                    {STRATEGY_LABELS[strategy] ?? strategy}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {METRIC_ROWS.map((row) => (
                <tr key={row.key}>
                  <td className="py-2 pr-4 font-mono text-xs text-slate-700">{row.label}</td>
                  {strategies.map((strategy) => (
                    <td key={strategy} className="py-2 pr-4 text-slate-900">
                      {formatMetric(report.metrics[strategy]?.[row.key], row.kind)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="门禁结论"
        description={`门禁策略 ${report.gate.strategy} · 变体 ${report.gate.variant_count}（安全变体 ${report.gate.safety_variant_count}）`}
        actions={<PassedBadge passed={report.passed} />}
      >
        <GateTable gate={report.gate} />
      </Card>

      <Card
        title="失败案例"
        description={`共 ${report.failed_cases.length} 条未达预期的变体运行。`}
      >
        {report.failed_cases.length === 0 ? (
          <p className="text-sm text-slate-500">本次运行无失败案例。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-2 pr-4">策略</th>
                  <th className="py-2 pr-4">场景</th>
                  <th className="py-2 pr-4">变体</th>
                  <th className="py-2 pr-4">期望根因</th>
                  <th className="py-2 pr-4">实际根因</th>
                  <th className="py-2 pr-4">终态</th>
                  <th className="py-2">错误</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {report.failed_cases.map((item, index) => (
                  <tr key={`${item.strategy}-${item.scenario_id}-${item.variant_id}-${index}`}>
                    <td className="py-2 pr-4 text-slate-900">{item.strategy}</td>
                    <td className="py-2 pr-4 font-mono text-xs text-slate-700">
                      {item.scenario_id}
                    </td>
                    <td className="py-2 pr-4 text-slate-600">{item.variant_id}</td>
                    <td className="py-2 pr-4 font-mono text-xs text-slate-700">
                      {item.expected_cause}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs text-slate-700">
                      {item.root_cause ?? "—"}
                    </td>
                    <td className="py-2 pr-4 text-slate-600">{item.final_status}</td>
                    <td className="py-2 text-xs text-red-600">{item.error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="报告路径">
        {reportPaths.length === 0 ? (
          <p className="text-sm text-slate-500">本次运行未记录报告路径。</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {reportPaths.map(([key, path]) => (
              <li key={key} className="flex flex-wrap items-baseline gap-2">
                <span className="w-20 shrink-0 text-slate-500">{key}</span>
                <code className="break-all font-mono text-xs text-slate-800">{path}</code>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}