"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AblationPanel, SyntheticNotice } from "@/components/ablation-panel";
import { TaskStatus } from "@/components/task-status";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  PageHeader,
  Spinner,
  StatCard,
} from "@/components/ui";
import {
  errorText,
  getScenarioRun,
  getToken,
  isTaskAccepted,
  listScenarioRuns,
  runScenarios,
} from "@/lib/api";
import type { EvalRunSummary, ScenarioRunReport } from "@/lib/types";

function formatPct(value: number | undefined): string {
  return value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

export default function EvalPage() {
  const router = useRouter();
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [report, setReport] = useState<ScenarioRunReport | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingReport, setLoadingReport] = useState(false);
  const [running, setRunning] = useState(false);
  const [asyncTaskId, setAsyncTaskId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const loadRuns = useCallback(async (preferRunId?: string) => {
    setLoadingRuns(true);
    setError(null);
    try {
      const data = await listScenarioRuns(20);
      setRuns(data.items);
      setSelectedRunId((current) => {
        const target = preferRunId ?? current;
        if (target && data.items.some((item) => item.run_id === target)) return target;
        return data.items[0]?.run_id ?? null;
      });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoadingRuns(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    void loadRuns();
  }, [loadRuns, router]);

  useEffect(() => {
    if (!selectedRunId) {
      setReport(null);
      return;
    }
    let cancelled = false;
    setLoadingReport(true);
    getScenarioRun(selectedRunId)
      .then((detail) => {
        if (!cancelled) setReport(detail);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setReport(null);
          setError(errorText(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingReport(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRunId, refreshKey]);

  async function handleRun() {
    setRunning(true);
    setError(null);
    setAsyncTaskId(null);
    try {
      const result = await runScenarios({ split: "holdout", limit: 16 });
      if (isTaskAccepted(result)) {
        setAsyncTaskId(result.task_id);
      } else {
        await loadRuns(result.run_id);
        setSelectedRunId(result.run_id);
        setRefreshKey((key) => key + 1);
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setRunning(false);
    }
  }

  async function handleRunAsync() {
    setRunning(true);
    setError(null);
    setAsyncTaskId(null);
    try {
      const result = await runScenarios({ split: "holdout", limit: 16 }, { async: true });
      if (isTaskAccepted(result)) {
        setAsyncTaskId(result.task_id);
      } else {
        await loadRuns(result.run_id);
        setSelectedRunId(result.run_id);
        setRefreshKey((key) => key + 1);
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setRunning(false);
    }
  }

  const strategies = report ? Object.keys(report.metrics) : [];
  const bestStrategy = strategies.reduce<string | null>((best, strategy) => {
    if (!report) return best;
    if (!best) return strategy;
    return (report.metrics[strategy]?.top1_rate ?? 0) > (report.metrics[best]?.top1_rate ?? 0) ? strategy : best;
  }, null);
  const bestMetrics = report && bestStrategy ? report.metrics[bestStrategy] : undefined;
  const diagnosableBest = report
    ? Math.max(...strategies.map((strategy) => report.metrics[strategy]?.top1_rate_diagnosable ?? 0))
    : undefined;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Evaluation / 评测门禁"
        title="先看门禁，再看策略差异"
        description="每次 holdout 消融都回答三个问题：能否发布、哪个策略领先、失败集中在哪里。"
        meta={
          <>
            {report ? (
              <Badge tone={report.passed ? "green" : "red"}>
                {report.passed ? "PASSED · 可发布" : "FAILED · 需修正"}
              </Badge>
            ) : (
              <Badge tone="neutral">等待运行</Badge>
            )}
            <span className="text-xs text-slate-500">{runs.length} 次历史运行</span>
          </>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" onClick={() => void handleRun()} disabled={running}>
              {running ? "运行中…" : "运行 holdout 消融"}
            </Button>
            <Button type="button" variant="secondary" onClick={() => void handleRunAsync()} disabled={running}>
              异步运行
            </Button>
          </div>
        }
      />

      <SyntheticNotice />

      {asyncTaskId && (
        <Card eyebrow="Async task" title="评测任务运行中" description="完成后会自动刷新历史运行列表。">
          <TaskStatus taskId={asyncTaskId} onDone={() => void loadRuns()} />
        </Card>
      )}

      {error && <ErrorBanner message={error} onRetry={() => void loadRuns()} />}

      {report && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="门禁结论"
            value={report.passed ? "PASSED" : "FAILED"}
            hint={report.passed ? "当前 holdout 满足发布门禁" : "存在未达标项，需查看门禁明细"}
            tone={report.passed ? "green" : "red"}
            footer={`门禁策略 ${report.gate.strategy}`}
          />
          <StatCard
            label={`领先策略 ${bestStrategy ?? ""} · Top-1`}
            value={formatPct(bestMetrics?.top1_rate)}
            hint="全量变体口径；同分策略并列"
            tone="teal"
            progress={bestMetrics?.top1_rate}
            footer={`Top-3 ${formatPct(bestMetrics?.top3_rate)}`}
          />
          <StatCard
            label="可诊断 Top-1"
            value={formatPct(diagnosableBest)}
            hint="排除无检查回写证据的变体后计算"
            tone="blue"
            progress={diagnosableBest}
            footer="反映策略真实定位能力"
          />
          <StatCard
            label="失败案例"
            value={report.failed_cases.length}
            hint={report.failed_cases.length === 0 ? "本次运行全部达到预期" : "优先查看失败场景与策略"}
            tone={report.failed_cases.length > 0 ? "amber" : "green"}
            footer={`${strategies.length} 个策略参与对比`}
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[17rem_minmax(0,1fr)]">
        <Card
          eyebrow="Run history"
          title="历史运行"
          description="选择一次运行，右侧联动指标与门禁。"
          actions={
            <Button type="button" variant="ghost" onClick={() => void loadRuns()} disabled={loadingRuns}>
              刷新
            </Button>
          }
        >
          {loadingRuns ? (
            <Spinner label="加载运行记录…" />
          ) : runs.length === 0 ? (
            <EmptyState title="暂无运行记录" description="点击右上角运行一次 holdout 消融。" />
          ) : (
            <ul className="max-h-[21rem] space-y-2 overflow-y-auto pr-1 lg:max-h-[calc(100vh-16rem)]">
              {runs.map((item) => {
                const active = item.run_id === selectedRunId;
                return (
                  <li key={item.run_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedRunId(item.run_id)}
                      className={`w-full rounded-lg border px-3 py-2.5 text-left transition ${
                        active
                          ? "border-teal-300 bg-teal-50/50 ring-1 ring-inset ring-teal-300/30"
                          : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className={`h-2 w-2 rounded-full ${item.passed ? "bg-emerald-500" : "bg-rose-500"}`} />
                        <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-slate-600">
                          {item.run_id}
                        </span>
                        <Badge tone={item.passed ? "green" : "red"}>{item.passed ? "通过" : "失败"}</Badge>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-slate-500">
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-700">
                          {item.split}
                        </span>
                        <span>{item.dataset_version}</span>
                      </div>
                      {item.created_at && (
                        <p className="mt-1 text-[10px] text-slate-400">{item.created_at.replace("T", " ").slice(0, 16)}</p>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <div className="min-w-0">
          {loadingReport ? (
            <Spinner label="加载运行详情…" />
          ) : report ? (
            <AblationPanel report={report} />
          ) : (
            <Card eyebrow="Run detail" title="运行详情">
              <EmptyState
                title="请选择一次运行"
                description="左侧历史运行会展示四策略指标、门禁结论与失败案例。"
              />
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
