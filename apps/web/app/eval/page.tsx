"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AblationPanel, SyntheticNotice } from "@/components/ablation-panel";
import { TaskStatus } from "@/components/task-status";
import { Badge, Button, Card, ErrorBanner, Spinner } from "@/components/ui";
import {
  errorText,
  getScenarioRun,
  getToken,
  isTaskAccepted,
  listScenarioRuns,
  runScenarios,
} from "@/lib/api";
import type { EvalRunSummary, ScenarioRunReport } from "@/lib/types";

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

  return (
    <div className="space-y-6">
      <Card
        title="A/B/C/D 消融评测"
        description="按 holdout 场景集运行四策略消融，核对门禁、失败案例与报告路径。仅 agent/admin 可触发运行。"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" onClick={() => void handleRun()} disabled={running}>
              {running ? "运行中…" : "运行 holdout 消融"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => void handleRunAsync()}
              disabled={running}
            >
              异步运行
            </Button>
          </div>
        }
      >
        <SyntheticNotice />
        {asyncTaskId && (
          <div className="mt-4">
            <TaskStatus taskId={asyncTaskId} onDone={() => void loadRuns()} />
          </div>
        )}
      </Card>

      {error && <ErrorBanner message={error} onRetry={() => void loadRuns()} />}

      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <Card
          title="历史运行"
          actions={
            <Button
              type="button"
              variant="secondary"
              onClick={() => void loadRuns()}
              disabled={loadingRuns}
            >
              刷新
            </Button>
          }
        >
          {loadingRuns ? (
            <Spinner label="加载运行记录…" />
          ) : runs.length === 0 ? (
            <p className="text-sm text-slate-500">暂无运行记录，可点击右上角运行一次 holdout 消融。</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {runs.map((item) => {
                const active = item.run_id === selectedRunId;
                return (
                  <li key={item.run_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedRunId(item.run_id)}
                      className={`flex w-full items-center justify-between gap-2 px-1 py-3 text-left hover:bg-slate-50 ${
                        active ? "bg-slate-50" : ""
                      }`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-mono text-xs text-slate-900">
                          {item.run_id}
                        </span>
                        <span className="mt-1 block text-xs text-slate-500">
                          {item.split} · {item.dataset_version}
                          {item.created_at ? ` · ${item.created_at}` : ""}
                        </span>
                      </span>
                      <Badge tone={item.passed ? "green" : "red"}>
                        {item.passed ? "通过" : "未通过"}
                      </Badge>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <div>
          {loadingReport ? (
            <Spinner label="加载运行详情…" />
          ) : report ? (
            <AblationPanel report={report} />
          ) : (
            <Card title="运行详情">
              <p className="text-sm text-slate-500">请选择一次运行查看四策略指标与门禁结论。</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}