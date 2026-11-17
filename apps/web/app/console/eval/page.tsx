"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge, Card, ErrorBanner, Spinner } from "@/components/ui";
import { errorText, getToken, listScenarioRuns } from "@/lib/api";
import type { EvalRunSummary } from "@/lib/types";

export default function ConsoleEvalPage() {
  const router = useRouter();
  const [items, setItems] = useState<EvalRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listScenarioRuns(20);
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
    <Card title="评测运行" description="最近 20 次 A/B/C/D 消融运行">
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {loading ? (
        <Spinner label="加载评测…" />
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-500">暂无评测运行。</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-slate-500">
            <tr>
              <th className="py-1">run_id</th>
              <th>数据集</th>
              <th>split</th>
              <th>结果</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((run) => (
              <tr key={run.run_id}>
                <td className="py-2 font-mono text-xs">{run.run_id.slice(0, 18)}…</td>
                <td className="text-xs">{run.dataset_version}</td>
                <td className="text-xs">{run.split}</td>
                <td>
                  <Badge tone={run.passed ? "green" : "red"}>{run.passed ? "PASSED" : "FAILED"}</Badge>
                </td>
                <td className="text-xs text-slate-500">{run.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}