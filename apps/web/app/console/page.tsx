"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge, Card, ErrorBanner, Spinner } from "@/components/ui";
import { errorText, getOverview, getToken, listTasks } from "@/lib/api";
import type { Overview, TaskInfo } from "@/lib/types";

function Kpi({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

export default function ConsoleOverviewPage() {
  const router = useRouter();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ov, taskList] = await Promise.all([getOverview(), listTasks({ limit: 10 })]);
      setOverview(ov);
      setTasks(taskList.items);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    void load();
  }, [load, router]);

  if (loading) return <Spinner label="加载概览…" />;
  if (error) return <ErrorBanner message={error} onRetry={() => void load()} />;
  if (!overview) return null;

  const o = overview;
  const latest = o.eval_runs.latest_passed;
  return (
    <div className="space-y-6">
      <Card
        title="运营概览"
        description={`生成于 ${o.generated_at}`}
        actions={
          <Badge tone={latest === null ? "neutral" : latest ? "green" : "red"}>
            {latest === null ? "暂无评测" : latest ? "最近评测通过" : "最近评测未通过"}
          </Badge>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Kpi label="案例总数" value={o.cases.total} hint={`待人工 ${o.need_human} · 已诊断 ${o.diagnosed}`} />
          <Kpi label="工单" value={o.work_orders.total} />
          <Kpi label="结果回收" value={o.outcomes} />
          <Kpi label="评测运行" value={o.eval_runs.total} />
          <Kpi
            label="任务"
            value={o.tasks.total}
            hint={Object.entries(o.tasks.by_status).map(([k, v]) => `${k}:${v}`).join(" · ") || "无任务"}
          />
        </div>
      </Card>

      <Card title="最近任务" description="最近 10 条任务记录">
        {tasks.length === 0 ? (
          <p className="text-sm text-slate-500">暂无任务。</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-slate-500">
              <tr>
                <th className="py-1">任务</th>
                <th>状态</th>
                <th>后端</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tasks.map((t) => (
                <tr key={t.task_id}>
                  <td className="py-2 font-mono text-xs">{t.task_id}</td>
                  <td>
                    <Badge tone={t.status === "SUCCESS" ? "green" : t.status === "FAILURE" ? "red" : "blue"}>
                      {t.status}
                    </Badge>
                  </td>
                  <td className="text-xs text-slate-500">{t.backend}</td>
                  <td className="text-xs text-slate-500">{t.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}