"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge, Card, EmptyState, ErrorBanner, PageHeader, Spinner } from "@/components/ui";
import { caseStatusMeta, nextAction } from "@/components/status";
import { errorText, getToken, listCases } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";

export default function ConsoleCasesPage() {
  const router = useRouter();
  const [items, setItems] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listCases({});
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
        eyebrow="Registry / 案例台账"
        title="全量诊断记录"
        description="用于核查案例状态、证据版本与下一步动作，不替代工作队列的优先级视图。"
        meta={<Badge tone="teal">{items.length} 条案例</Badge>}
        actions={
          <Link
            href="/cases"
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-teal-600 hover:text-teal-800"
          >
            打开案例队列
          </Link>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <Card eyebrow="All cases" title="案例列表" description="当前账号可访问的全部案例。">
        {loading ? (
          <Spinner label="加载案例…" />
        ) : items.length === 0 ? (
          <EmptyState title="暂无案例" description="创建第一条案例后，台账会显示在这里。" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-[10px] uppercase tracking-[0.12em] text-slate-500">
                  <th className="py-2 pr-3 font-semibold">案例</th>
                  <th className="px-3 py-2 font-semibold">状态</th>
                  <th className="px-3 py-2 font-semibold">故障码</th>
                  <th className="px-3 py-2 font-semibold">证据 / 检查</th>
                  <th className="pl-3 py-2 font-semibold">下一步</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((c) => {
                  const meta = caseStatusMeta(c.status);
                  return (
                    <tr key={c.id} className="hover:bg-slate-50/70">
                      <td className="py-2.5 pr-3">
                        <Link className="group block" href={`/cases/${c.id}`}>
                          <span className="block text-sm font-semibold text-slate-900 group-hover:text-teal-800">
                            {c.device_model ?? "未绑定设备"}
                          </span>
                          <span className="mt-0.5 block max-w-[22rem] truncate text-xs text-slate-500">
                            {c.symptom}
                          </span>
                        </Link>
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge tone={meta.tone}>{meta.label}</Badge>
                      </td>
                      <td className="px-3 py-2.5 font-mono text-[11px] text-slate-700">{c.error_code || "—"}</td>
                      <td className="px-3 py-2.5 text-xs text-slate-500">
                        v{c.evidence_version} / {c.step_count} 步
                      </td>
                      <td className="pl-3 py-2.5 text-xs text-slate-600">{nextAction(c.status)}</td>
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
