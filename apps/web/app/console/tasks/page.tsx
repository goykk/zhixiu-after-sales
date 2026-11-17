"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge, Card, EmptyState, ErrorBanner, PageHeader, Spinner } from "@/components/ui";
import { errorText, getToken, listTasks } from "@/lib/api";
import type { TaskInfo, TaskStatus } from "@/lib/types";

const TASK_META: Record<TaskStatus, { label: string; tone: "blue" | "green" | "orange" | "red" }> = {
  PENDING: { label: "排队", tone: "blue" },
  STARTED: { label: "运行中", tone: "orange" },
  SUCCESS: { label: "成功", tone: "green" },
  FAILURE: { label: "失败", tone: "red" },
};

export default function ConsoleTasksPage() {
  const router = useRouter();
  const [items, setItems] = useState<TaskInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listTasks({ limit: 50, owner: "all" });
      setItems(data.items);
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

  const running = items.filter((t) => t.status === "PENDING" || t.status === "STARTED").length;
  const failed = items.filter((t) => t.status === "FAILURE").length;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Task center / 任务中心"
        title="异步任务与失败追踪"
        description="诊断推进、评测与报告生成的后台任务；优先处理运行中阻塞和失败任务。"
        meta={
          <>
            <Badge tone="neutral">{items.length} 条</Badge>
            {running > 0 && <Badge tone="orange">{running} 条运行中</Badge>}
            {failed > 0 && <Badge tone="red">{failed} 条失败</Badge>}
          </>
        }
        actions={
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-teal-600 hover:text-teal-800"
          >
            刷新任务
          </button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <Card eyebrow="Queue" title="任务列表" description="最近 50 条异步任务（全部用户）。">
        {loading ? (
          <Spinner label="加载任务…" />
        ) : items.length === 0 ? (
          <EmptyState title="暂无任务" description="提交异步诊断或评测后，任务会出现在这里。" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-[10px] uppercase tracking-[0.12em] text-slate-500">
                  <th className="py-2 pr-3 font-semibold">任务</th>
                  <th className="px-3 py-2 font-semibold">状态</th>
                  <th className="px-3 py-2 font-semibold">后端</th>
                  <th className="px-3 py-2 font-semibold">创建时间</th>
                  <th className="pl-3 py-2 font-semibold">错误</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((t) => {
                  const meta = TASK_META[t.status];
                  return (
                    <tr key={t.task_id} className="hover:bg-slate-50/70">
                      <td className="py-2.5 pr-3 font-mono text-[11px] text-slate-700">{t.task_id.slice(0, 12)}</td>
                      <td className="px-3 py-2.5">
                        <Badge tone={meta.tone}>{meta.label}</Badge>
                      </td>
                      <td className="px-3 py-2.5 text-xs text-slate-500">{t.backend}</td>
                      <td className="px-3 py-2.5 text-xs text-slate-500">{t.created_at}</td>
                      <td className="max-w-[18rem] truncate pl-3 py-2.5 text-xs text-rose-700">{t.error ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
