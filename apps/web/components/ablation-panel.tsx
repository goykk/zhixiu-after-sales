"use client";

import { Badge, Card, EmptyState, ProgressBar } from "@/components/ui";
import type { EvalGate, ScenarioRunReport, StrategyMetrics } from "@/lib/types";

const STRATEGY_LABELS: Record<string, string> = {
  A: "规则树",
  B: "证据 + 假设",
  C: "证据 + 假设 + 检查",
  D: "C + 历史结果加权",
};

const STRATEGY_META: Record<
  string,
  { block: string; border: string; bar: "slate" | "blue" | "teal" | "amber"; badge: "neutral" | "blue" | "teal" | "orange" }
> = {
  A: { block: "bg-slate-800", border: "border-slate-200", bar: "slate", badge: "neutral" },
  B: { block: "bg-sky-600", border: "border-sky-200", bar: "blue", badge: "blue" },
  C: { block: "bg-teal-700", border: "border-teal-200", bar: "teal", badge: "teal" },
  D: { block: "bg-amber-500", border: "border-amber-200", bar: "amber", badge: "orange" },
};

type MetricKind = "count" | "rate" | "steps";

const METRIC_ROWS: { key: keyof StrategyMetrics; label: string; kind: MetricKind }[] = [
  { key: "variant_count", label: "变体数", kind: "count" },
  { key: "diagnosable_variant_count", label: "可诊断变体数", kind: "count" },
  { key: "failed_count", label: "失败数", kind: "count" },
  { key: "top1_rate", label: "Top-1 命中率", kind: "rate" },
  { key: "top3_rate", label: "Top-3 命中率", kind: "rate" },
  { key: "top1_rate_diagnosable", label: "可诊断 Top-1", kind: "rate" },
  { key: "top3_rate_diagnosable", label: "可诊断 Top-3", kind: "rate" },
  { key: "avg_steps", label: "平均检查步数", kind: "steps" },
  { key: "early_probe_rate", label: "前序检查命中率", kind: "rate" },
  { key: "unnecessary_parts_rate", label: "无效配件率", kind: "rate" },
  { key: "safety_block_rate", label: "安全阻断率", kind: "rate" },
  { key: "escalation_rate", label: "转人工率", kind: "rate" },
  { key: "citation_accuracy", label: "引用准确率", kind: "rate" },
  { key: "completion_rate", label: "完成率", kind: "rate" },
];

function formatMetric(value: number | undefined, kind: MetricKind): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  if (kind === "rate") return `${(value * 100).toFixed(1)}%`;
  if (kind === "steps") return value.toFixed(2);
  return String(value);
}

function pct(value: number | undefined): string {
  return value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

function PassedBadge({ passed }: { passed: boolean }) {
  return <Badge tone={passed ? "green" : "red"}>{passed ? "门禁通过" : "门禁未通过"}</Badge>;
}

export function SyntheticNotice() {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-900">
      <span className="mt-0.5 shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-800">
        Notice
      </span>
      <p className="leading-6">
        本页场景与指标来自合成数据集，仅用于 A/B/C/D 策略消融对比与回归门禁，不代表真实线上效果。
      </p>
    </div>
  );
}

function StrategyCard({
  strategy,
  metrics,
  isBest,
}: {
  strategy: string;
  metrics: StrategyMetrics | undefined;
  isBest: boolean;
}) {
  const meta = STRATEGY_META[strategy] ?? STRATEGY_META.A;
  const top1 = metrics?.top1_rate;
  const top3 = metrics?.top3_rate;
  const diagnosable = metrics?.top1_rate_diagnosable;

  return (
    <div
      className={`relative overflow-hidden rounded-xl border bg-white p-4 ${
        isBest ? `${meta.border} ring-2 ring-teal-600/15` : "border-slate-200"
      }`}
    >
      {isBest && <span className="absolute inset-x-0 top-0 h-[3px] bg-teal-600" />}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={`grid h-7 w-7 place-items-center rounded-md text-xs font-bold text-white ${meta.block}`}>
            {strategy}
          </span>
          <div>
            <p className="text-xs font-semibold text-slate-950">{STRATEGY_LABELS[strategy] ?? "未知策略"}</p>
            <p className="text-[10px] text-slate-500">
              {metrics?.variant_count ?? 0} 变体 / {metrics?.failed_count ?? 0} 失败
            </p>
          </div>
        </div>
        {isBest && <Badge tone="teal">领先</Badge>}
      </div>

      <div className="mt-4">
        <div className="flex items-end justify-between gap-2">
          <div>
            <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-slate-500">Top-1 命中</p>
            <p className="mt-0.5 text-3xl font-semibold leading-none tracking-tight text-slate-950">
              {pct(top1)}
            </p>
          </div>
          <p className="pb-0.5 text-right text-[10px] leading-4 text-slate-500">
            Top-3
            <span className="ml-1 font-semibold text-slate-800">{pct(top3)}</span>
          </p>
        </div>
        <div className="mt-3">
          <ProgressBar value={top1 ?? 0} tone={meta.bar} />
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-slate-100 pt-3 text-[11px]">
        <div>
          <dt className="text-slate-500">可诊断 Top-1</dt>
          <dd className="mt-0.5 font-semibold text-slate-900">{pct(diagnosable)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">平均检查</dt>
          <dd className="mt-0.5 font-semibold text-slate-900">
            {metrics ? metrics.avg_steps.toFixed(2) : "—"} 步
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">引用准确</dt>
          <dd className="mt-0.5 font-semibold text-slate-900">{pct(metrics?.citation_accuracy)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">完成率</dt>
          <dd className="mt-0.5 font-semibold text-slate-900">{pct(metrics?.completion_rate)}</dd>
        </div>
      </dl>
    </div>
  );
}

function GateCard({
  label,
  requirement,
  actual,
  ok,
}: {
  label: string;
  requirement: string;
  actual: string;
  ok: boolean | undefined;
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        ok === false ? "border-rose-200 bg-rose-50/50" : "border-slate-200 bg-white"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-slate-900">{label}</p>
        {ok === undefined ? (
          <Badge tone="neutral">未评估</Badge>
        ) : (
          <Badge tone={ok ? "green" : "red"}>{ok ? "通过" : "未通过"}</Badge>
        )}
      </div>
      <div className="mt-2 flex items-baseline justify-between gap-2">
        <span className="text-lg font-semibold text-slate-950">{actual}</span>
        <span className="text-[10px] text-slate-500">阈值 {requirement}</span>
      </div>
    </div>
  );
}

export function AblationPanel({ report }: { report: ScenarioRunReport }) {
  const strategies = (report.strategies.length ? report.strategies : Object.keys(report.metrics)).sort();
  const reportPaths = Object.entries(report.report_paths ?? {});
  const bestTop1 = Math.max(...strategies.map((strategy) => report.metrics[strategy]?.top1_rate ?? 0));
  const bestLabels = strategies.filter(
    (strategy) => (report.metrics[strategy]?.top1_rate ?? 0) >= bestTop1 - 0.0001,
  );
  const baseline = report.metrics.A?.top1_rate;
  const delta = baseline === undefined ? null : (bestTop1 - baseline) * 100;
  const diagnosableBest = Math.max(
    ...strategies.map((strategy) => report.metrics[strategy]?.top1_rate_diagnosable ?? 0),
  );

  return (
    <div className="space-y-4">
      <Card
        eyebrow="Strategy comparison"
        title="四策略指标对比"
        description={`${report.dataset_version} · ${report.split} · ${report.created_at ?? "时间未知"}`}
        actions={<PassedBadge passed={report.passed} />}
      >
        <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50/80 px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            Readout
          </p>
          <p className="mt-1 text-sm leading-6 text-slate-800">
            <span className="font-semibold text-teal-800">{bestLabels.join(" / ")}</span> Top-1 达到{" "}
            <span className="font-semibold text-slate-950">{pct(bestTop1)}</span>
            {delta !== null && delta > 0 && (
              <>
                ，较 A 提升 <span className="font-semibold text-slate-950">{delta.toFixed(1)}pp</span>
              </>
            )}
            ；可诊断口径 Top-1 最高 <span className="font-semibold text-slate-950">{pct(diagnosableBest)}</span>。
          </p>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {strategies.map((strategy) => (
            <StrategyCard
              key={strategy}
              strategy={strategy}
              metrics={report.metrics[strategy]}
              isBest={bestLabels.includes(strategy)}
            />
          ))}
        </div>
      </Card>

      <Card
        eyebrow="Release gate"
        title="门禁结论"
        description={`门禁策略 ${report.gate.strategy} · ${report.gate.variant_count} 变体（安全变体 ${report.gate.safety_variant_count}）`}
        actions={<PassedBadge passed={report.passed} />}
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <GateCard
            label="Top-3 命中率"
            requirement={`≥ ${(report.gate.min_top3_rate * 100).toFixed(0)}%`}
            actual={pct(report.gate.top3_rate)}
            ok={report.gate.checks?.top3_rate}
          />
          <GateCard
            label="安全阻断率"
            requirement={`= ${(report.gate.required_safety_block_rate * 100).toFixed(0)}%`}
            actual={pct(report.gate.safety_block_rate)}
            ok={report.gate.checks?.safety_block_rate}
          />
          <GateCard
            label="完成率"
            requirement={`≥ ${(report.gate.min_completion_rate * 100).toFixed(0)}%`}
            actual={pct(report.gate.completion_rate)}
            ok={report.gate.checks?.completion_rate}
          />
        </div>
      </Card>

      <Card
        eyebrow="Diagnostics"
        title="失败案例"
        description={`共 ${report.failed_cases.length} 条未达预期的变体运行；优先看失败集中在哪个策略与场景。`}
        actions={<Badge tone={report.failed_cases.length > 0 ? "red" : "green"}>{report.failed_cases.length} 条</Badge>}
      >
        {report.failed_cases.length === 0 ? (
          <EmptyState
            title="本次运行没有失败案例"
            description="四策略在 holdout 上均达到门禁要求，可继续关注可诊断口径与平均步数。"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-[10px] uppercase tracking-[0.12em] text-slate-500">
                  <th className="py-2 pr-3 font-semibold">策略</th>
                  <th className="px-3 py-2 font-semibold">场景 / 变体</th>
                  <th className="px-3 py-2 font-semibold">期望根因</th>
                  <th className="px-3 py-2 font-semibold">实际根因</th>
                  <th className="px-3 py-2 font-semibold">终态</th>
                  <th className="pl-3 py-2 font-semibold">错误</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {report.failed_cases.map((item, index) => (
                  <tr key={`${item.strategy}-${item.scenario_id}-${item.variant_id}-${index}`}>
                    <td className="py-2.5 pr-3">
                      <span className={`inline-grid h-6 w-6 place-items-center rounded text-[10px] font-bold text-white ${STRATEGY_META[item.strategy]?.block ?? "bg-slate-700"}`}>
                        {item.strategy}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-[11px] text-slate-700">
                      {item.scenario_id}
                      <span className="ml-1 text-slate-400">/{item.variant_id}</span>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-[11px] text-slate-700">{item.expected_cause}</td>
                    <td className="px-3 py-2.5 font-mono text-[11px] text-slate-700">{item.root_cause ?? "—"}</td>
                    <td className="px-3 py-2.5 text-xs text-slate-600">{item.final_status}</td>
                    <td className="pl-3 py-2.5 text-xs text-rose-700">{item.error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <details className="surface overflow-hidden">
        <summary className="cursor-pointer px-5 py-4 text-sm font-semibold text-slate-900 marker:text-teal-700">
          查看完整指标明细与报告路径
        </summary>
        <div className="border-t border-slate-200 px-5 py-4">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-[10px] uppercase tracking-[0.12em] text-slate-500">
                  <th className="py-2 pr-4 font-semibold">指标</th>
                  {strategies.map((strategy) => (
                    <th key={strategy} className="px-3 py-2 font-semibold">
                      {strategy} · {STRATEGY_LABELS[strategy] ?? "未知"}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {METRIC_ROWS.map((row) => (
                  <tr key={row.key}>
                    <td className="py-2 pr-4 text-xs text-slate-700">{row.label}</td>
                    {strategies.map((strategy) => (
                      <td key={strategy} className="px-3 py-2 text-xs text-slate-900">
                        {formatMetric(report.metrics[strategy]?.[row.key], row.kind)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {reportPaths.length > 0 && (
            <div className="mt-4 border-t border-slate-200 pt-4">
              <p className="data-label mb-2">报告路径</p>
              <ul className="space-y-1.5">
                {reportPaths.map(([key, path]) => (
                  <li key={key} className="flex flex-wrap items-baseline gap-2 text-xs">
                    <span className="w-16 shrink-0 text-slate-500">{key}</span>
                    <code className="break-all font-mono text-slate-700">{path}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </details>
    </div>
  );
}
