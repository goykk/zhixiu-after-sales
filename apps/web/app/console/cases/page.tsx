"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge, Card, ErrorBanner, Spinner } from "@/components/ui";
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
    <Card title="案例" description="当前账号可访问的全部案例">
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {loading ? (
        <Spinner label="加载案例…" />
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-500">暂无案例。</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-slate-500">
            <tr>
              <th className="py-1">案例</th>
              <th>状态</th>
              <th>故障码</th>
              <th>检查步数</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((c) => (
              <tr key={c.id}>
                <td className="py-2">
                  <Link className="text-blue-700 hover:underline" href={`/cases/${c.id}`}>
                    {c.device_model ?? "未绑定设备"} · {c.symptom}
                  </Link>
                </td>
                <td>
                  <Badge tone="blue">{c.status}</Badge>
                </td>
                <td className="text-xs">{c.error_code || "-"}</td>
                <td className="text-xs">{c.step_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}