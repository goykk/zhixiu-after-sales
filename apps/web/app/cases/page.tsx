"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge, Button, Card, ErrorBanner, Spinner, inputClass } from "@/components/ui";
import { createCase, errorText, getToken, listCases } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";

const STATUS_FILTERS = [
  "",
  "DRAFT",
  "COLLECTING_INFO",
  "EVIDENCE_READY",
  "HYPOTHESIZING",
  "PROBE_PENDING",
  "DIAGNOSED",
  "NEED_HUMAN",
  "CLOSED",
];

export default function CasesPage() {
  const router = useRouter();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deviceModel, setDeviceModel] = useState("");
  const [symptom, setSymptom] = useState("");
  const [errorCode, setErrorCode] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listCases({ status: statusFilter || undefined });
      setCases(data.items);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    void load();
  }, [load, router]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!deviceModel.trim() || !symptom.trim()) {
      setError("设备型号与现象描述不能为空");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createCase({
        device_model: deviceModel.trim(),
        symptom: symptom.trim(),
        error_code: errorCode.trim() || null,
      });
      setDeviceModel("");
      setSymptom("");
      setErrorCode("");
      router.push(`/cases/${created.id}`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card
        title="我的案例"
        description="仅展示当前账号有权访问的诊断案例。"
        actions={
          <div className="flex items-center gap-2">
            <select
              className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              {STATUS_FILTERS.map((value) => (
                <option key={value || "all"} value={value}>
                  {value || "全部状态"}
                </option>
              ))}
            </select>
            <Button type="button" variant="secondary" onClick={() => void load()} disabled={loading}>
              刷新
            </Button>
          </div>
        }
      >
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {loading ? (
          <Spinner label="加载案例…" />
        ) : cases.length === 0 ? (
          <p className="text-sm text-slate-500">暂无案例，可在下方创建。</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {cases.map((item) => (
              <li key={item.id}>
                <Link
                  href={`/cases/${item.id}`}
                  className="flex flex-wrap items-center justify-between gap-3 py-3 hover:bg-slate-50"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-900">
                      {item.device_model ?? "未绑定设备"} · {item.symptom}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {item.error_code ? `故障码 ${item.error_code} · ` : ""}
                      证据版本 v{item.evidence_version} · 检查 {item.step_count} 步
                    </p>
                  </div>
                  <Badge tone="blue">{item.status}</Badge>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="新建案例" description="填写设备型号与现象，受理后补充证据。">
        <form className="space-y-3" onSubmit={handleCreate}>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block text-sm">
              <span className="mb-1 block text-slate-600">设备型号</span>
              <input
                className={inputClass}
                value={deviceModel}
                placeholder="AuroraHome AC-Pro 1200"
                onChange={(event) => setDeviceModel(event.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-slate-600">故障码</span>
              <input
                className={inputClass}
                value={errorCode}
                placeholder="E106"
                onChange={(event) => setErrorCode(event.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-slate-600">现象描述</span>
              <input
                className={inputClass}
                value={symptom}
                placeholder="空调不制冷，外机有异响"
                onChange={(event) => setSymptom(event.target.value)}
              />
            </label>
          </div>
          <Button type="submit" disabled={busy}>
            {busy ? "创建中…" : "创建案例"}
          </Button>
        </form>
      </Card>
    </div>
  );
}