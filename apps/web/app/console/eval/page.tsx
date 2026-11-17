"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge, Card, EmptyState, ErrorBanner, PageHeader, Spinner } from "@/components/ui";
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
    <div className="space-y-6">
      <PageHeader
        eyebrow="Evaluation registry / 评测台账"
        title="最近 20 次消融运行"
        description="只展示运行级结论；四策略指标、门禁明细与失败案例在评测页展开。"
        meta={
          <>
            <Badge tone="neutral">{items.length} 次运行</Badge>
            {items[0] && (
              <Badge tone={items[0].passed ? "green" : "red"}>
                最近一次 {items[0].passed ? "PASSED" : "FAILED"}
              </Badge>
            )}
          </>
        }
        actions={
          <Link
            href="/eval"
            className="rounded-lg bg-teal-700 px-3.5 py-2 text-sm font-semibold text-white transition hover:bg-teal-800"
          >
            打开评测页
          </Link>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <Card eyebrow="Runs" title="运行记录" description="固定 holdout 消融，用于发布门禁与回归对比。">
        {loading ? (
          <Spinner label="加载评测…" />
        ) : items.length === 0 ? (
          <EmptyState title="暂无评测运行" description="在评测页运行一次 holdout 消融后，这里会出现记录。" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-[10px] uppercase tracking-[0.12em] text-slate-500">
                  <th className="py-2 pr-3 font-semibold">run_id</th>
                  <th className="px-3 py-2 font-semibold">数据集</th>
                  <th className="px-3 py-2 font-semibold">split</th>
                  <th className="px-3 py-2 font-semibold">结果</th>
                  <th className="pl-3 py-2 font-semibold">时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((run) => (
                  <tr key={run.run_id} className="hover:bg-slate-50/70">
                    <td className="py-2.5 pr-3 font-mono text-[11px] text-slate-700">{run.run_id.slice(0, 20)}</td>
                    <td className="px-3 py-2.5 text-xs text-slate-600">{run.dataset_version}</td>
                    <td className="px-3 py-2.5 text-xs text-slate-600">{run.split}</td>
                    <td className="px-3 py-2.5">
                      <Badge tone={run.passed ? "green" : "red"}>{run.passed ? "PASSED" : "FAILED"}</Badge>
                    </td>
                    <td className="pl-3 py-2.5 text-xs text-slate-500">{run.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
