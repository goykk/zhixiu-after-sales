"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  PageHeader,
  Spinner,
  inputClass,
} from "@/components/ui";
import { caseStatusMeta, nextAction } from "@/components/status";
import { createCase, errorText, getToken, listCases } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";

const STATUS_FILTERS = [
  "DRAFT",
  "COLLECTING_INFO",
  "EVIDENCE_READY",
  "HYPOTHESIZING",
  "PROBE_PENDING",
  "DIAGNOSED",
  "NEED_HUMAN",
  "APPROVAL_PENDING",
  "WORK_ORDER_CREATED",
  "OUTCOME_PENDING",
  "CLOSED",
];

const DEVICE_MODELS = [
  "AuroraHome AC-Pro 1200",
  "AuroraHome AC-Mini 600",
  "NovaDesk PX-220",
  "NovaDesk PX-450",
  "VentoCool FZ-30",
];

function formatTime(value: string | null): string {
  if (!value) return "时间未知";
  return value.replace("T", " ").slice(0, 16);
}

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

  const activeFilter = statusFilter ? caseStatusMeta(statusFilter) : null;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Case queue / 案例队列"
        title="从受理到关闭的诊断队列"
        description="先看每张卡停在哪个阶段、下一步做什么，再决定打开哪一条。"
        meta={
          <>
            <Badge tone="teal">{cases.length} 条</Badge>
            {activeFilter && <Badge tone={activeFilter.tone}>{activeFilter.label}</Badge>}
            <span className="text-xs text-slate-500">当前账号可见案例</span>
          </>
        }
        actions={
          <Button type="button" variant="secondary" onClick={() => void load()} disabled={loading}>
            刷新队列
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.9fr)]">
        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => setStatusFilter("")}
                className={`rounded-md px-2.5 py-1.5 text-[11px] font-semibold transition ${
                  statusFilter === ""
                    ? "bg-teal-700 text-white"
                    : "border border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                }`}
              >
                全部
              </button>
              {STATUS_FILTERS.map((status) => {
                const meta = caseStatusMeta(status);
                const active = statusFilter === status;
                return (
                  <button
                    key={status}
                    type="button"
                    onClick={() => setStatusFilter(status)}
                    className={`rounded-md px-2.5 py-1.5 text-[11px] font-semibold transition ${
                      active
                        ? "bg-teal-700 text-white"
                        : "border border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                    }`}
                  >
                    <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${meta.rail}`} />
                    {meta.label}
                  </button>
                );
              })}
            </div>
          <Card eyebrow="Queue" title="待处理案例" description="按最近更新时间排列；左侧色条表示当前阶段。">
            {loading ? (
              <Spinner label="加载案例…" />
            ) : cases.length === 0 ? (
              <EmptyState
                title="这个筛选下没有案例"
                description="切换状态，或从右侧新建一条案例，受理后即可看到阶段与下一步。"
                action={
                  <Button type="button" variant="secondary" onClick={() => setStatusFilter("")}>
                    查看全部案例
                  </Button>
                }
              />
            ) : (
              <ul className="divide-y divide-slate-100">
                {cases.map((item) => {
                  const meta = caseStatusMeta(item.status);
                  const updated = formatTime(item.updated_at);
                  return (
                    <li key={item.id}>
                      <Link
                        href={`/cases/${item.id}`}
                        className="group flex gap-3 py-4 transition first:pt-0 last:pb-0 hover:bg-slate-50/70"
                      >
                        <span className={`mt-0.5 h-14 w-1 shrink-0 rounded-full ${meta.rail}`} />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone={meta.tone}>{meta.label}</Badge>
                            {item.error_code && (
                              <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-600">
                                {item.error_code}
                              </span>
                            )}
                            {item.risk_level && (
                              <span className="text-[10px] text-slate-400">风险 {item.risk_level}</span>
                            )}
                          </div>
                          <p className="mt-1.5 truncate text-sm font-semibold text-slate-950">
                            {item.device_model ?? "未绑定设备"}
                          </p>
                          <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-slate-600">{item.symptom}</p>
                          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-500">
                            <span>证据 v{item.evidence_version}</span>
                            <span>检查 {item.step_count} 步</span>
                            {item.confidence !== null && <span>置信 {item.confidence.toFixed(2)}</span>}
                            <span>{updated}</span>
                          </div>
                          <p className="mt-2 text-[11px] font-medium text-teal-800">
                            下一步：{nextAction(item.status)}
                          </p>
                        </div>
                        <span className="self-center text-lg text-slate-300 transition group-hover:text-teal-700">
                          →
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>

        <Card
          id="new-case"
          eyebrow="New case"
          title="新建诊断案例"
          description="先建立最小信息，再进入受理与证据补充。"
          className="lg:sticky lg:top-24 lg:self-start"
        >
          <form className="space-y-5" onSubmit={handleCreate}>
            <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                Step 1 · 设备
              </p>
              <label className="mt-2 block text-sm">
                <span className="mb-1 block text-xs font-medium text-slate-600">设备型号</span>
                <input
                  className={inputClass}
                  value={deviceModel}
                  placeholder="例如 AuroraHome AC-Mini 600"
                  list="device-models"
                  onChange={(event) => setDeviceModel(event.target.value)}
                />
                <datalist id="device-models">
                  {DEVICE_MODELS.map((model) => (
                    <option key={model} value={model} />
                  ))}
                </datalist>
              </label>
              <label className="mt-3 block text-sm">
                <span className="mb-1 block text-xs font-medium text-slate-600">故障码（可选）</span>
                <input
                  className={inputClass}
                  value={errorCode}
                  placeholder="例如 E106"
                  onChange={(event) => setErrorCode(event.target.value)}
                />
              </label>
            </div>

            <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                Step 2 · 现象
              </p>
              <label className="mt-2 block text-sm">
                <span className="mb-1 block text-xs font-medium text-slate-600">客户描述</span>
                <textarea
                  className={`${inputClass} min-h-[96px] resize-y`}
                  value={symptom}
                  placeholder="例如：空调不制冷，外机有异响，已持续两天。"
                  onChange={(event) => setSymptom(event.target.value)}
                />
              </label>
            </div>

            <div className="flex items-start gap-2 rounded-lg border border-teal-200 bg-teal-50/50 px-3 py-2.5">
              <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-teal-700 text-[10px] font-bold text-white">
                3
              </span>
              <p className="text-[11px] leading-5 text-teal-900">
                创建后进入案例详情，先做「受理并提取信息」，再补充照片、手册或检查结果。
              </p>
            </div>

            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? "创建中…" : "创建并进入诊断"}
            </Button>
            <p className="text-center text-[10px] text-slate-400">
              设备型号与现象为必填；创建后可继续补充证据。
            </p>
          </form>
        </Card>
      </div>
    </div>
  );
}
