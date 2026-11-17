"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge, Card, ErrorBanner, Spinner } from "@/components/ui";
import { errorText, getToken, listTasks } from "@/lib/api";
import type { TaskInfo } from "@/lib/types";

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

  return (
    <Card title="任务" description="最近 50 条异步任务（全部用户）">
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {loading ? (
        <Spinner label="加载任务…" />
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-500">暂无任务。</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-slate-500">
            <tr>
              <th className="py-1">任务</th>
              <th>状态</th>
              <th>后端</th>
              <th>创建时间</th>
              <th>错误</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((t) => (
              <tr key={t.task_id}>
                <td className="py-2 font-mono text-xs">{t.task_id}</td>
                <td>
                  <Badge tone={t.status === "SUCCESS" ? "green" : t.status === "FAILURE" ? "red" : "blue"}>
                    {t.status}
                  </Badge>
                </td>
                <td className="text-xs text-slate-500">{t.backend}</td>
                <td className="text-xs text-slate-500">{t.created_at}</td>
                <td className="max-w-[16rem] truncate text-xs text-red-700">{t.error ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}