"use client";

import { useState } from "react";
import { EvidenceForm } from "@/components/evidence-form";
import { Badge, Button, Card, inputClass, type BadgeTone } from "@/components/ui";
import type {
  CaseDetail,
  DiagnosisResult,
  DiagnosisSummary,
  EvidenceInput,
  EvidenceItem,
  Hypothesis,
  Probe,
  ProbeCard,
} from "@/lib/types";

const SOURCE_LABELS: Record<string, string> = {
  customer: "客户描述",
  media: "照片/媒体",
  manual: "手册",
  probe: "检查结果",
  model: "模型推测",
};

const POLARITY_META: Record<string, { label: string; tone: BadgeTone }> = {
  support: { label: "支持", tone: "green" },
  refute: { label: "反对", tone: "red" },
  neutral: { label: "中立", tone: "neutral" },
};

const HYPOTHESIS_STATUS: Record<string, { label: string; tone: BadgeTone }> = {
  supported: { label: "已支持", tone: "green" },
  open: { label: "待验证", tone: "blue" },
  rejected: { label: "已排除", tone: "red" },
};

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "置信高",
  medium: "置信中",
  low: "置信低",
};

const PROBE_TYPE_LABELS: Record<string, string> = {
  question: "问询",
  photo: "拍照",
  self_check: "自检",
};

const LEVEL_LABELS: Record<string, string> = {
  low: "低",
  medium: "中",
  high: "高",
};

function formatList(value: unknown): string {
  if (Array.isArray(value)) return value.length > 0 ? value.map(String).join("、") : "—";
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function evidenceIndex(evidence: EvidenceItem[]): Map<string, EvidenceItem> {
  return new Map(evidence.map((item) => [item.id, item]));
}

function EvidenceLedger({ evidence }: { evidence: EvidenceItem[] }) {
  if (evidence.length === 0) {
    return <p className="text-sm text-slate-500">证据账本为空，请先登记或上传证据。</p>;
  }
  return (
    <ul className="space-y-2">
      {evidence.map((item) => {
        const polarity = POLARITY_META[item.polarity] ?? { label: item.polarity, tone: "neutral" as BadgeTone };
        return (
          <li key={item.id} className="rounded-md border border-slate-200 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="blue">{SOURCE_LABELS[item.source_type] ?? item.source_type}</Badge>
              <Badge tone={polarity.tone}>{polarity.label}</Badge>
              <span className="text-xs text-slate-500">
                第 {item.page} 页 · 相关度 {item.relevance_score.toFixed(2)}
              </span>
              {item.chunk_id && (
                <span className="text-xs text-slate-400">片段 {item.chunk_id.slice(0, 8)}</span>
              )}
            </div>
            <p className="mt-1 whitespace-pre-wrap text-sm text-slate-800">{item.quote}</p>
            {item.source_ref && (
              <p className="mt-1 text-xs text-slate-400">来源：{item.source_ref}</p>
            )}

          </li>
        );
      })}
    </ul>
  );
}

function HypothesisList({
  hypotheses,
  evidenceById,
}: {
  hypotheses: Hypothesis[];
  evidenceById: Map<string, EvidenceItem>;
}) {
  if (hypotheses.length === 0) {
    return <p className="text-sm text-slate-500">尚未生成候选根因。</p>;
  }
  return (
    <ul className="space-y-3">
      {hypotheses.map((item) => {
        const status = HYPOTHESIS_STATUS[item.status] ?? {
          label: item.status,
          tone: "neutral" as BadgeTone,
        };
        return (
          <li key={item.id} className="rounded-md border border-slate-200 px-3 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-slate-900">{item.label}</span>
              <Badge tone="purple">{item.cause_code}</Badge>
              <Badge tone={status.tone}>{status.label}</Badge>
              <Badge tone="orange">
                {CONFIDENCE_LABELS[item.confidence_level] ?? item.confidence_level}
              </Badge>
              <span className="text-xs text-slate-500">证据版本 v{item.evidence_version}</span>
            </div>
            <div className="mt-2 grid gap-1 text-xs text-slate-600">
              <span>
                支持证据：{item.support_evidence_ids.length} 条
                {item.support_evidence_ids.length > 0 &&
                  `（${item.support_evidence_ids
                    .map((id) => evidenceById.get(id)?.quote ?? id)
                    .join("；")}）`}
              </span>
              <span>
                反对证据：{item.refute_evidence_ids.length} 条
                {item.refute_evidence_ids.length > 0 &&
                  `（${item.refute_evidence_ids
                    .map((id) => evidenceById.get(id)?.quote ?? id)
                    .join("；")}）`}
              </span>
            </div>
            {item.rationale && <p className="mt-2 text-sm text-slate-700">{item.rationale}</p>}
          </li>
        );
      })}
    </ul>
  );
}

function ProbeCardView({
  card,
  busy,
  onSubmitResult,
}: {
  card: ProbeCard;
  busy: boolean;
  onSubmitResult: (probeId: string, observedValue: string, sourceRef: string) => void;
}) {
  const outcomes = Object.keys(card.expected_outcomes ?? {});
  const [observedValue, setObservedValue] = useState(outcomes[0] ?? "");
  const [sourceRef, setSourceRef] = useState("");
  const rationale = card.rationale;

  return (
    <div className="space-y-3 rounded-md border border-slate-200 px-4 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="blue">{PROBE_TYPE_LABELS[card.probe_type] ?? card.probe_type}</Badge>
        <Badge tone="purple">{card.code}</Badge>
        <span className="text-xs text-slate-500">
          成本 {LEVEL_LABELS[card.cost_level] ?? card.cost_level} · 风险{" "}
          {LEVEL_LABELS[card.risk_level] ?? card.risk_level} · 评分 {card.score.toFixed(2)}
        </span>
      </div>
      <p className="text-sm font-medium text-slate-900">{card.question}</p>
      <p className="text-sm text-slate-700">目标根因：{formatList(card.target_labels)}</p>
      <div className="text-sm text-slate-700">
        预期结果：
        <ul className="mt-1 space-y-1">
          {outcomes.map((key) => {
            const outcome = card.expected_outcomes[key];
            return (
              <li key={key} className="text-xs text-slate-600">
                <span className="font-medium text-slate-800">{key}</span> → 支持{" "}
                {formatList(outcome?.supports)}；反对 {formatList(outcome?.refutes)}
              </li>
            );
          })}
        </ul>
      </div>
      {rationale?.why && <p className="text-sm text-slate-700">选择理由：{rationale.why}</p>}
      {rationale?.alternatives !== undefined && (
        <p className="text-sm text-slate-500">
          未选中的检查：{formatList(rationale.alternatives)}
        </p>
      )}
      <form
        className="flex flex-wrap items-end gap-3 border-t border-slate-200 pt-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!observedValue) return;
          onSubmitResult(card.probe_id, observedValue, sourceRef.trim());
        }}
      >
        <label className="min-w-[220px] flex-1 text-sm">
          <span className="mb-1 block text-slate-600">观察结果</span>
          <select
            className={inputClass}
            value={observedValue}
            onChange={(event) => setObservedValue(event.target.value)}
          >
            {outcomes.map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-[180px] flex-1 text-sm">
          <span className="mb-1 block text-slate-600">来源标识（可选）</span>
          <input
            className={inputClass}
            value={sourceRef}
            onChange={(event) => setSourceRef(event.target.value)}
            placeholder="照片/视频/自检截图"
          />
        </label>
        <Button type="submit" disabled={busy || !observedValue}>
          {busy ? "提交中…" : "录入检查结果"}
        </Button>
      </form>
    </div>
  );
}

function ProbeSection({
  probes,
  card,
  action,
  onPlanProbe,
  onSubmitResult,
}: {
  probes: Probe[];
  card: ProbeCard | null;
  action: string | null;
  onPlanProbe: () => void;
  onSubmitResult: (probeId: string, observedValue: string, sourceRef: string) => void;
}) {
  const pending = probes.find((probe) => probe.status === "pending") ?? null;
  return (
    <div className="space-y-3">
      {card && (
        <ProbeCardView
          key={card.probe_id}
          card={card}
          busy={action === "probe-result"}
          onSubmitResult={onSubmitResult}
        />
      )}
      {!card && pending && (
        <p className="text-sm text-slate-600">
          当前待执行检查：<span className="font-medium text-slate-900">{pending.code}</span> ·{" "}
          {pending.question}
        </p>
      )}
      {!card && !pending && (
        <p className="text-sm text-slate-500">尚未规划检查，点击下方按钮获取下一项。</p>
      )}
      <Button type="button" variant="secondary" onClick={onPlanProbe} disabled={action === "probe-plan"}>
        {action === "probe-plan" ? "规划中…" : "规划下一项检查"}
      </Button>
      {probes.length > 0 && (
        <ul className="space-y-1 text-xs text-slate-500">
          {probes.map((probe) => (
            <li key={probe.id}>
              {probe.code} · {probe.status} · {probe.question}
              {probe.executed_at ? ` · 完成于 ${probe.executed_at}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ConclusionSection({
  result,
  summary,
  action,
  onFinalize,
}: {
  result: DiagnosisResult | null;
  summary: DiagnosisSummary | null;
  action: string | null;
  onFinalize: () => void;
}) {
  if (result) {
    const rootCause = result.root_cause;
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-slate-600">根因</span>
          <span className="font-medium text-slate-900">{rootCause?.label ?? "未确定"}</span>
          {rootCause && <Badge tone="purple">{rootCause.cause_code}</Badge>}
          {rootCause && (
            <Badge tone="orange">
              {CONFIDENCE_LABELS[rootCause.confidence_level] ?? rootCause.confidence_level}
            </Badge>
          )}
          <Badge tone="green">{result.case_status}</Badge>
        </div>
        {result.rationale && <p className="text-sm text-slate-700">{result.rationale}</p>}
        <div className="text-sm text-slate-700">
          证据链：
          {result.evidence_chain.length === 0 ? (
            <span className="text-slate-500">无</span>
          ) : (
            <ul className="mt-1 space-y-1 text-xs text-slate-600">
              {result.evidence_chain.map((item) => (
                <li key={item.id}>
                  [{SOURCE_LABELS[item.source_type] ?? item.source_type}] {item.quote}
                </li>
              ))}
            </ul>
          )}
        </div>
        {result.unresolved.length > 0 && (
          <p className="text-sm text-slate-500">未排除根因：{formatList(result.unresolved)}</p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {summary?.root_cause ? (
        <p className="text-sm text-slate-700">
          当前最强候选：
          <span className="font-medium text-slate-900">{summary.root_cause.label}</span>
          <Badge tone="purple">{summary.root_cause.cause_code}</Badge>
          <Badge tone="orange">
            {CONFIDENCE_LABELS[summary.root_cause.confidence_level] ??
              summary.root_cause.confidence_level}
          </Badge>
        </p>
      ) : (
        <p className="text-sm text-slate-500">尚未形成可支持的结论。</p>
      )}
      <Button type="button" onClick={onFinalize} disabled={action === "finalize"}>
        {action === "finalize" ? "生成结论中…" : "完成诊断并生成结论"}
      </Button>
    </div>
  );
}

export interface DiagnosisPanelProps {
  detail: CaseDetail;
  summary: DiagnosisSummary | null;
  result: DiagnosisResult | null;
  probeCard: ProbeCard | null;
  action: string | null;
  onAddEvidence: (payload: EvidenceInput) => Promise<void>;
  onGenerateHypotheses: () => void;
  onPlanProbe: () => void;
  onSubmitProbeResult: (probeId: string, observedValue: string, sourceRef: string) => void;
  onFinalize: () => void;
}

export function DiagnosisPanel({
  detail,
  summary,
  result,
  probeCard,
  action,
  onAddEvidence,
  onGenerateHypotheses,
  onPlanProbe,
  onSubmitProbeResult,
  onFinalize,
}: DiagnosisPanelProps) {
  const evidence = result?.evidence_chain.length ? result.evidence_chain : detail.evidence;
  const hypotheses = detail.hypotheses.length > 0 ? detail.hypotheses : summary?.hypotheses ?? [];
  const evidenceById = evidenceIndex(evidence);

  return (
    <div className="space-y-6">
      <Card
        title="证据账本"
        description="客户描述、媒体、手册与检查结果分别记入，极性保留冲突。"
        actions={<span className="text-xs text-slate-500">{detail.evidence.length} 条</span>}
      >
        <EvidenceLedger evidence={detail.evidence} />
        <div className="mt-5 border-t border-slate-200 pt-4">
          <h3 className="mb-3 text-sm font-medium text-slate-700">补充证据</h3>
          <EvidenceForm onSubmit={onAddEvidence} />
        </div>
      </Card>

      <Card
        title="候选根因"
        description="置信级别用于排序，不等同于概率。"
        actions={
          <Button
            type="button"
            onClick={onGenerateHypotheses}
            disabled={action === "hypotheses"}
          >
            {action === "hypotheses" ? "生成中…" : "生成/更新候选根因"}
          </Button>
        }
      >
        <HypothesisList hypotheses={hypotheses} evidenceById={evidenceById} />
      </Card>

      <Card title="下一项检查" description="按信息增益、成本与风险排序，一次只给一项。">
        <ProbeSection
          probes={detail.probes}
          card={probeCard}
          action={action}
          onPlanProbe={onPlanProbe}
          onSubmitResult={onSubmitProbeResult}
        />
      </Card>

      <Card title="诊断结论">
        <ConclusionSection
          result={result}
          summary={summary}
          action={action}
          onFinalize={onFinalize}
        />
      </Card>
    </div>
  );
}