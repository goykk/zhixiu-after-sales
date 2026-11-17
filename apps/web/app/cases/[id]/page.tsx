"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { CaseStepper } from "@/components/case-stepper";
import { DiagnosisPanel } from "@/components/diagnosis-panel";
import { RepairPanel } from "@/components/repair-panel";
import { caseStatusMeta, nextAction } from "@/components/status";
import { TaskStatus } from "@/components/task-status";
import { UploadPanel } from "@/components/upload-panel";
import { Badge, Button, Card, ErrorBanner, PageHeader, Spinner } from "@/components/ui";
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

  const statusMeta = current ? caseStatusMeta(current.status) : null;
  const intakeFirst = current?.status === "DRAFT" || current?.status === "COLLECTING_INFO";

  return (
    <div className="space-y-6">
      <div>
        <Link href="/cases" className="text-xs font-medium text-slate-500 transition hover:text-teal-800">
          ← 返回案例队列
        </Link>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {notice && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {notice}
        </div>
      )}

      {current && statusMeta && (
        <>
          <PageHeader
            eyebrow={`Case detail / ${caseId.slice(0, 8)}`}
            title={current.device_model ?? "未绑定设备"}
            description={current.symptom}
            meta={
              <>
                <Badge tone={statusMeta.tone}>{statusMeta.label}</Badge>
                {current.error_code && (
                  <span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-[10px] font-semibold text-slate-700">
                    {current.error_code}
                  </span>
                )}
                {current.risk_level && (
                  <Badge tone={current.risk_level === "high" ? "red" : current.risk_level === "medium" ? "orange" : "neutral"}>
                    风险 {current.risk_level}
                  </Badge>
                )}
                <span className="text-xs text-slate-500">证据版本 v{current.evidence_version}</span>
                <span className="text-xs text-slate-500">检查 {current.step_count} 步</span>
                {current.confidence !== null && (
                  <span className="text-xs text-slate-500">置信 {current.confidence}</span>
                )}
              </>
            }
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant={intakeFirst ? "primary" : "secondary"}
                  onClick={handleIntake}
                  disabled={action === "intake"}
                >
                  {action === "intake" ? "受理中…" : "受理并提取信息"}
                </Button>
                <Button
                  type="button"
                  variant={intakeFirst ? "secondary" : "primary"}
                  onClick={() => void handleAdvanceAsync()}
                  disabled={action === "advance-async"}
                >
                  {action === "advance-async" ? "提交中…" : "异步推进诊断"}
                </Button>
                <Button type="button" variant="ghost" onClick={() => void load()} disabled={loading}>
                  刷新
                </Button>
                {showRepair && current.status !== "CLOSED" && (
                  <a
                    href="#repair-panel"
                    className="inline-flex items-center justify-center rounded-lg border border-teal-300 bg-teal-50 px-3.5 py-2 text-sm font-semibold text-teal-800 transition hover:bg-teal-100"
                  >
                    前往维修方案
                  </a>
                )}
              </div>
            }
          />

          <Card
            eyebrow="Workflow"
            title="诊断流程与下一步"
            description="阶段表示案例在闭环链路中的位置，不表示自动执行顺序。"
            actions={<Badge tone={statusMeta.tone}>{statusMeta.label}</Badge>}
          >
            <div className="rounded-lg border border-teal-200 bg-teal-50/60 px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded bg-teal-700 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
                  Next
                </span>
                <p className="text-sm font-semibold text-teal-950">{nextAction(current.status)}</p>
              </div>
              {current.missing_fields && current.missing_fields.length > 0 && (
                <p className="mt-2 text-xs text-amber-800">
                  待补充信息：{current.missing_fields.join("、")}
                </p>
              )}
              {current.last_question && (
                <p className="mt-1 text-xs text-slate-600">待确认：{current.last_question}</p>
              )}
            </div>
            <div className="mt-5">
              <CaseStepper status={current.status} />
            </div>
            {advanceTaskId && (
              <div className="mt-4 border-t border-slate-200 pt-4">
                <TaskStatus taskId={advanceTaskId} onDone={() => void load()} />
              </div>
            )}
          </Card>
        </>
      )}

      {detail && (
        <Card
          eyebrow="Evidence files"
          title="证据文件"
          description="支持 jpg/png/webp/pdf/md/txt，单文件不超过 10 MB；上传后进入证据账本。"
        >
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
        <div id="repair-panel" className="scroll-mt-24">
          <RepairPanel
            caseId={caseId}
            caseStatus={current.status}
            deviceModel={current.device_model}
            onCaseChanged={load}
          />
        </div>
      )}
    </div>
  );
}