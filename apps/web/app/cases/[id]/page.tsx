"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { DiagnosisPanel } from "@/components/diagnosis-panel";
import { RepairPanel } from "@/components/repair-panel";
import { TaskStatus } from "@/components/task-status";
import { UploadPanel } from "@/components/upload-panel";
import { Badge, Button, Card, ErrorBanner, Spinner } from "@/components/ui";
import {
  addEvidence,
  advanceCase,
  errorText,
  finalizeDiagnosis,
  generateHypotheses,
  getCase,
  getDiagnosis,
  getToken,
  intake,
  isTaskAccepted,
  planProbe,
  submitProbeResult,
  uploadFile,
} from "@/lib/api";
import type {
  CaseDetail,
  DiagnosisResult,
  DiagnosisSummary,
  EvidenceInput,
  ProbeCard,
} from "@/lib/types";

const REPAIR_STATUSES = new Set([
  "DIAGNOSED",
  "REPAIR_PLANNING",
  "APPROVAL_PENDING",
  "WORK_ORDER_CREATED",
  "OUTCOME_PENDING",
  "CLOSED",
]);

export default function CaseDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const caseId = params?.id ?? "";

  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [summary, setSummary] = useState<DiagnosisSummary | null>(null);
  const [result, setResult] = useState<DiagnosisResult | null>(null);
  const [probeCard, setProbeCard] = useState<ProbeCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [advanceTaskId, setAdvanceTaskId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await getCase(caseId);
      setDetail(data);
      const summaryData = await getDiagnosis(caseId).catch(() => null);
      setSummary(summaryData);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    if (caseId) void load();
  }, [caseId, load, router]);

  async function run(key: string, task: () => Promise<void>) {
    setAction(key);
    setError(null);
    setNotice(null);
    try {
      await task();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setAction(null);
    }
  }

  const handleIntake = () =>
    run("intake", async () => {
      await intake(caseId);
      await load();
    });

  const handleGenerateHypotheses = () =>
    run("hypotheses", async () => {
      await generateHypotheses(caseId);
      await load();
    });

  const handlePlanProbe = () =>
    run("probe-plan", async () => {
      const planned = await planProbe(caseId);
      setProbeCard(planned.probe);
      if (!planned.probe) setNotice("已无可执行的检查项，可生成诊断结论。");
      await load();
    });

  const handleSubmitEvidence = async (payload: EvidenceInput) => {
    await addEvidence(caseId, payload);
    await load();
  };

  const handleUpload = async (file: File) => {
    await uploadFile(caseId, file);
    await load();
  };

  const handleSubmitProbeResult = (probeId: string, observedValue: string, sourceRef: string) =>
    void run("probe-result", async () => {
      const outcome = await submitProbeResult(caseId, probeId, observedValue, sourceRef);
      setProbeCard(null);
      if (outcome.needs_human) setNotice("已达检查步数上限，建议转人工处理。");
      await load();
    });

  const handleFinalize = () =>
    run("finalize", async () => {
      const diagnosed = await finalizeDiagnosis(caseId);
      setResult(diagnosed);
      await load();
    });

  const handleAdvanceAsync = () =>
    run("advance-async", async () => {
      const advanced = await advanceCase(caseId, { async: true });
      if (isTaskAccepted(advanced)) {
        setAdvanceTaskId(advanced.task_id);
      } else {
        await load();
      }
    });

  if (!caseId) {
    return <ErrorBanner message="缺少案例编号" />;
  }

  if (loading && !detail) {
    return <Spinner label="加载案例详情…" />;
  }

  const current = detail?.case;
  const showRepair =
    !!current &&
    (REPAIR_STATUSES.has(current.status) || !!result || !!summary?.root_cause);

  return (
    <div className="space-y-6">
      <div>
        <Link href="/cases" className="text-sm text-slate-500 hover:text-slate-900">
          ← 返回案例列表
        </Link>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {notice && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {notice}
        </div>
      )}

      {current && (
        <Card
          title={current.device_model ?? "未绑定设备"}
          description={current.symptom}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="blue">{current.status}</Badge>
              <Button
                type="button"
                variant="secondary"
                onClick={() => void handleAdvanceAsync()}
                disabled={action === "advance-async"}
              >
                {action === "advance-async" ? "提交中…" : "异步推进诊断"}
              </Button>
            </div>
          }
        >
          <dl className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs text-slate-500">故障码</dt>
              <dd className="text-slate-900">{current.error_code ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">置信 / 风险</dt>
              <dd className="text-slate-900">
                {current.confidence ?? "—"} / {current.risk_level ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">证据版本</dt>
              <dd className="text-slate-900">v{current.evidence_version}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">检查步数</dt>
              <dd className="text-slate-900">{current.step_count}</dd>
            </div>
          </dl>
          {current.missing_fields && current.missing_fields.length > 0 && (
            <p className="mt-3 text-sm text-amber-700">
              待补充信息：{current.missing_fields.join("、")}
            </p>
          )}
          {current.last_question && (
            <p className="mt-2 text-sm text-slate-600">待确认：{current.last_question}</p>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button type="button" variant="secondary" onClick={handleIntake} disabled={action === "intake"}>
              {action === "intake" ? "受理中…" : "受理并提取信息"}
            </Button>
            <Button type="button" variant="secondary" onClick={() => void load()} disabled={loading}>
              刷新
            </Button>
          </div>
          {advanceTaskId && (
            <div className="mt-3">
              <TaskStatus taskId={advanceTaskId} onDone={() => void load()} />
            </div>
          )}
        </Card>
      )}

      {detail && (
        <Card title="证据文件" description="支持 jpg/png/webp/pdf/md/txt，单文件不超过 10 MB。">
          <UploadPanel uploads={detail.uploads} onUpload={handleUpload} />
        </Card>
      )}

      {detail && (
        <DiagnosisPanel
          detail={detail}
          summary={summary}
          result={result}
          probeCard={probeCard}
          action={action}
          onAddEvidence={handleSubmitEvidence}
          onGenerateHypotheses={handleGenerateHypotheses}
          onPlanProbe={handlePlanProbe}
          onSubmitProbeResult={handleSubmitProbeResult}
          onFinalize={handleFinalize}
        />
      )}

      {current && showRepair && (
        <RepairPanel
          caseId={caseId}
          caseStatus={current.status}
          deviceModel={current.device_model}
          onCaseChanged={load}
        />
      )}
    </div>
  );
}