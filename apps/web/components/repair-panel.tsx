"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  approveCase,
  buildRepairPlan,
  checkPartCompatibility,
  closeCase,
  createWorkOrder,
  errorText,
  getRepairPlan,
  listApprovals,
  listOutcomes,
  listParts,
  listWorkOrders,
  recordOutcome,
  submitApproval,
} from "@/lib/api";
import { Badge, Button, Card, Spinner, inputClass, type BadgeTone } from "@/components/ui";
import type {
  Approval,
  CompatibilityResult,
  Part,
  RepairOption,
  RepairOutcome,
  RepairPlan,
  RepairPartRef,
  WorkOrder,
} from "@/lib/types";

const ACTION_LABELS: Record<string, string> = {
  self_service: "自助处理",
  repair_center: "送修",
  on_site: "上门维修",
  replace_part: "更换配件",
};

const RISK_LABELS: Record<string, string> = { low: "低", medium: "中", high: "高" };

const STOCK_META: Record<string, { label: string; tone: BadgeTone }> = {
  in_stock: { label: "有货", tone: "green" },
  low_stock: { label: "库存紧张", tone: "orange" },
  out_of_stock: { label: "缺货", tone: "red" },
  discontinued: { label: "停产", tone: "neutral" },
};

const COMPAT_META: Record<string, { label: string; tone: BadgeTone }> = {
  equivalent: { label: "等效件", tone: "green" },
  replacement: { label: "替代件", tone: "blue" },
  requires_adapter: { label: "需转接", tone: "orange" },
  incompatible: { label: "不兼容", tone: "red" },
  unknown: { label: "未知", tone: "neutral" },
};

const DECISION_META: Record<string, { label: string; tone: BadgeTone }> = {
  approve: { label: "批准", tone: "green" },
  reject: { label: "驳回", tone: "red" },
};

const WORK_ORDER_META: Record<string, { label: string; tone: BadgeTone }> = {
  created: { label: "已创建", tone: "blue" },
  assigned: { label: "已派单", tone: "blue" },
  in_progress: { label: "处理中", tone: "orange" },
  resolved: { label: "已解决", tone: "green" },
  cancelled: { label: "已取消", tone: "neutral" },
};

const OUTCOME_ACTIONS = ["self_service", "repair_center", "on_site", "replace_part"];

const EMPTY_APPROVALS: Approval[] = [];
const EMPTY_WORK_ORDERS: WorkOrder[] = [];
const EMPTY_OUTCOMES: RepairOutcome[] = [];
const EMPTY_PARTS: Part[] = [];

function meta(
  table: Record<string, { label: string; tone: BadgeTone }>,
  key: string,
): { label: string; tone: BadgeTone } {
  return table[key] ?? { label: key, tone: "neutral" };
}

function formatTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function newIdempotencyKey(caseId: string): string {
  return `web-${caseId}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function stockMeta(status: string | null | undefined) {
  return meta(STOCK_META, status ?? "");
}

function compatMeta(status: string | null | undefined) {
  return meta(COMPAT_META, status ?? "unknown");
}

function PartRow({ part }: { part: RepairPartRef }) {
  const stock = part.stock_status ? stockMeta(part.stock_status) : null;
  const compat = part.compatible === undefined || part.compatible === null
    ? (part.compatibility_type ? compatMeta(part.compatibility_type) : null)
    : part.compatible
      ? { label: "兼容", tone: "green" as BadgeTone }
      : { label: "不兼容", tone: "red" as BadgeTone };
  return (
    <li className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
      <span className="font-mono text-slate-800">{part.part_no}</span>
      {part.name && <span>{part.name}</span>}
      {stock && <Badge tone={stock.tone}>{stock.label}</Badge>}
      {compat && <Badge tone={compat.tone}>{compat.label}</Badge>}
    </li>
  );
}

function OptionItem({ option, recommended }: { option: RepairOption; recommended: boolean }) {
  const riskLabel = RISK_LABELS[option.risk_level] ?? option.risk_level;
  return (
    <li className="rounded-md border border-slate-200 px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-slate-900">{option.label}</span>
        <Badge tone="blue">{ACTION_LABELS[option.action] ?? option.action}</Badge>
        {recommended && <Badge tone="green">推荐</Badge>}
        <Badge tone={option.parts_compatible ? "green" : "red"}>
          {option.parts_compatible ? "配件兼容" : "配件不兼容"}
        </Badge>
        <span className="text-xs text-slate-500">预估费用 {option.estimated_cost.toFixed(2)}</span>
        <span className="text-xs text-slate-500">风险 {riskLabel}</span>
      </div>
      {option.rationale && <p className="mt-1 text-sm text-slate-700">{option.rationale}</p>}
      {option.parts.length > 0 && (
        <ul className="mt-2 space-y-1 border-t border-slate-100 pt-2">
          {option.parts.map((part) => (
            <PartRow key={`${option.action}-${part.part_no}`} part={part} />
          ))}
        </ul>
      )}
    </li>
  );
}

function CompatibilityBox({ result }: { result: CompatibilityResult }) {
  const compat = compatMeta(result.compatibility_type);
  const stock = stockMeta(result.stock_status);
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-slate-900">{result.part_no}</span>
        <Badge tone={result.compatible ? "green" : "red"}>
          {result.compatible ? "可替换" : "不可替换"}
        </Badge>
        <Badge tone={compat.tone}>{compat.label}</Badge>
        <Badge tone={stock.tone}>{stock.label}</Badge>
      </div>
      <p className="mt-1 text-xs text-slate-500">依据：{result.evidence_source || "—"}</p>
      {result.alternatives.length > 0 && (
        <p className="mt-1 text-xs text-slate-600">替代件：{result.alternatives.join("、")}</p>
      )}
    </div>
  );
}

export interface RepairPanelProps {
  caseId: string;
  caseStatus: string;
  deviceModel: string | null;
  hardwareVersion?: string | null;
  onCaseChanged: () => void | Promise<void>;
}

export function RepairPanel({
  caseId,
  caseStatus,
  deviceModel,
  hardwareVersion = "",
  onCaseChanged,
}: RepairPanelProps) {
  const [plan, setPlan] = useState<RepairPlan | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>(EMPTY_APPROVALS);
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>(EMPTY_WORK_ORDERS);
  const [outcomes, setOutcomes] = useState<RepairOutcome[]>(EMPTY_OUTCOMES);
  const [parts, setParts] = useState<Part[]>(EMPTY_PARTS);
  const [compat, setCompat] = useState<CompatibilityResult | null>(null);
  const [partsError, setPartsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [decisionReason, setDecisionReason] = useState("");
  const [assignee, setAssignee] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState(() => newIdempotencyKey(caseId));
  const keyCaseRef = useRef(caseId);

  const [selectedWorkOrderId, setSelectedWorkOrderId] = useState("");
  const [actualCauseCode, setActualCauseCode] = useState("");
  const [outcomeAction, setOutcomeAction] = useState(OUTCOME_ACTIONS[0]);
  const [partsReplaced, setPartsReplaced] = useState("");
  const [resolved, setResolved] = useState(true);
  const [outcomeNote, setOutcomeNote] = useState("");
  const [consistency, setConsistency] = useState<string | null>(null);

  useEffect(() => {
    if (keyCaseRef.current === caseId) return;
    keyCaseRef.current = caseId;
    setIdempotencyKey(newIdempotencyKey(caseId));
  }, [caseId]);

  const load = useCallback(async () => {
    setLoading(true);
    const problems: string[] = [];

    const planData = await getRepairPlan(caseId).catch((err: unknown) => {
      const missing =
        err instanceof ApiError && (err.status === 404 || err.code === "REPAIR_PLAN_NOT_FOUND");
      if (!missing) problems.push(errorText(err));
      return null;
    });
    const approvalData = await listApprovals(caseId).catch((err: unknown) => {
      problems.push(errorText(err));
      return { items: EMPTY_APPROVALS };
    });
    const workOrderData = await listWorkOrders(caseId).catch((err: unknown) => {
      problems.push(errorText(err));
      return { items: EMPTY_WORK_ORDERS };
    });
    const outcomeData = await listOutcomes(caseId).catch((err: unknown) => {
      problems.push(errorText(err));
      return { items: EMPTY_OUTCOMES };
    });

    setPlan(planData);
    setApprovals(approvalData.items);
    setWorkOrders(workOrderData.items);
    setOutcomes(outcomeData.items);
    setError(problems.length > 0 ? problems[0] : null);
    setLoading(false);
  }, [caseId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!deviceModel) {
      setParts(EMPTY_PARTS);
      return;
    }
    let alive = true;
    setPartsError(null);
    listParts(deviceModel)
      .then((res) => {
        if (alive) setParts(res.items);
      })
      .catch((err: unknown) => {
        if (alive) setPartsError(errorText(err));
      });
    return () => {
      alive = false;
    };
  }, [deviceModel]);

  useEffect(() => {
    if (workOrders.length === 0) {
      setSelectedWorkOrderId("");
      return;
    }
    const preferred = workOrders.find((item) => item.status !== "resolved") ?? workOrders[0];
    setSelectedWorkOrderId((current) =>
      current && workOrders.some((item) => item.id === current) ? current : preferred.id,
    );
  }, [workOrders]);

  async function run(key: string, task: () => Promise<string | null>) {
    setAction(key);
    setError(null);
    setNotice(null);
    try {
      const message = await task();
      if (message) setNotice(message);
      await load();
      await onCaseChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setAction(null);
    }
  }

  const handleBuildPlan = () =>
    run("plan", async () => {
      const built = await buildRepairPlan(caseId);
      setPlan(built);
      return built.recommended ? `已生成维修方案，推荐：${built.recommended}` : "已生成维修方案，但无配件兼容的推荐方案。";
    });

  const handleCheckCompat = async (partNo: string) => {
    if (!deviceModel) {
      setError("案例未绑定设备型号，无法校验配件兼容性");
      return;
    }
    setAction(`compat-${partNo}`);
    setError(null);
    try {
      setCompat(await checkPartCompatibility(partNo, deviceModel, hardwareVersion || undefined));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setAction(null);
    }
  };

  const handleSubmitApproval = () =>
    run("submit-approval", async () => {
      await submitApproval(caseId);
      return "已提交审批，等待审批决定。";
    });

  const handleDecide = (decision: "approve" | "reject") =>
    run(`decide-${decision}`, async () => {
      await approveCase(caseId, decision, decisionReason.trim());
      setDecisionReason("");
      return decision === "approve" ? "已批准该维修方案。" : "已驳回该维修方案，案例转人工处理。";
    });

  const handleCreateWorkOrder = () =>
    run("work-order", async () => {
      const result = await createWorkOrder(caseId, idempotencyKey, assignee.trim() || null);
      return result.created ? "工单已创建。" : "该幂等键已有工单，已返回原工单。";
    });

  const handleRecordOutcome = () =>
    run("outcome", async () => {
      if (!selectedWorkOrderId) throw new Error("请先创建并选择工单");
      if (!actualCauseCode.trim()) throw new Error("请填写实际根因代码");
      const result = await recordOutcome(selectedWorkOrderId, {
        actual_cause_code: actualCauseCode.trim(),
        action: outcomeAction,
        parts_replaced: partsReplaced
          .split(/[,，\s]+/)
          .map((item) => item.trim())
          .filter(Boolean),
        resolved,
        note: outcomeNote.trim(),
      });
      setConsistency(result.consistency);
      setOutcomeNote("");
      return `维修结果已记录，与诊断根因一致性：${result.consistency}`;
    });

  const handleClose = () =>
    run("close", async () => {
      await closeCase(caseId);
      return "案例已关闭。";
    });

  const recommended = plan?.recommended ?? null;
  const canSubmitApproval = caseStatus === "REPAIR_PLANNING";
  const canDecide = caseStatus === "APPROVAL_PENDING";
  const canCreateWorkOrder = caseStatus === "APPROVAL_PENDING" || caseStatus === "WORK_ORDER_CREATED";
  const canRecordOutcome = caseStatus === "WORK_ORDER_CREATED";
  const canClose = caseStatus === "OUTCOME_PENDING" || caseStatus === "WORK_ORDER_CREATED";
  const hasApproval = approvals.some((item) => item.decision === "approve");

  if (loading && !plan && approvals.length === 0 && workOrders.length === 0) {
    return <Spinner label="加载维修闭环数据…" />;
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <span className="break-all">{error}</span>
        </div>
      )}
      {notice && (
        <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          {notice}
        </div>
      )}

      <Card
        eyebrow="Repair plan"
        title="维修方案"
        description="仅在诊断结论完成后可生成；推荐方案要求配件兼容且费用最低。"
        actions={<Badge tone="blue">{caseStatus}</Badge>}
      >
        <div className="mb-4 flex flex-wrap gap-2">
          <Button type="button" onClick={handleBuildPlan} disabled={action === "plan"}>
            {action === "plan" ? "生成中…" : plan ? "重新生成方案" : "生成维修方案"}
          </Button>
          <Button type="button" variant="secondary" onClick={() => void load()} disabled={loading}>
            刷新
          </Button>
        </div>

        {!plan ? (
          <p className="text-sm text-slate-500">尚未生成维修方案。</p>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-slate-700">
              根因：<span className="font-medium text-slate-900">{plan.root_cause_label}</span>
              <span className="ml-2 font-mono text-xs text-slate-500">{plan.root_cause_code}</span>
            </p>
            <p className="text-sm text-slate-600">
              推荐方案：{recommended ? (ACTION_LABELS[recommended] ?? recommended) : "无（配件均不兼容）"}
            </p>
            <ul className="space-y-2">
              {plan.options.map((option, index) => (
                <OptionItem
                  key={`${option.action}-${index}`}
                  option={option}
                  recommended={recommended === option.action}
                />
              ))}
            </ul>
            {plan.disclaimers.length > 0 && (
              <ul className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {plan.disclaimers.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Card>

      <Card
        eyebrow="Parts catalog"
        title="配件兼容与库存"
        description={deviceModel ? `设备型号：${deviceModel}` : "案例未绑定设备型号"}
      >
        {partsError && <p className="mb-2 text-xs text-red-600">{partsError}</p>}
        {parts.length === 0 ? (
          <p className="text-sm text-slate-500">未获取到配件目录。</p>
        ) : (
          <ul className="mb-4 space-y-1">
            {parts.map((part) => {
              const stock = stockMeta(part.stock_status);
              return (
                <li
                  key={part.part_no}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 px-3 py-2"
                >
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-mono text-slate-900">{part.part_no}</span>
                    <span className="text-slate-700">{part.name}</span>
                    <Badge tone={stock.tone}>{stock.label}</Badge>
                    <span className="text-xs text-slate-500">适配 {part.hardware_range || "全版本"}</span>
                  </div>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => void handleCheckCompat(part.part_no)}
                    disabled={!deviceModel || action === `compat-${part.part_no}`}
                  >
                    {action === `compat-${part.part_no}` ? "校验中…" : "校验兼容性"}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
        {compat && <CompatibilityBox result={compat} />}
      </Card>

      <Card
        eyebrow="Approval"
        title="提交审批与审批决定"
        description="提交后案例进入 APPROVAL_PENDING；批准保持待办，驳回转人工处理。"
      >
        <div className="mb-4 flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={handleSubmitApproval}
            disabled={!canSubmitApproval || action === "submit-approval"}
          >
            {action === "submit-approval" ? "提交中…" : "提交审批"}
          </Button>
        </div>

        {approvals.length === 0 ? (
          <p className="text-sm text-slate-500">暂无审批记录。</p>
        ) : (
          <ul className="mb-4 space-y-2">
            {approvals.map((item) => {
              const decision = meta(DECISION_META, item.decision);
              return (
                <li key={item.id} className="rounded-md border border-slate-200 px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={decision.tone}>{decision.label}</Badge>
                    <span className="text-xs text-slate-500">审批人 {item.approver_id}</span>
                    <span className="text-xs text-slate-400">{formatTime(item.created_at)}</span>
                  </div>
                  {item.reason && <p className="mt-1 text-slate-700">理由：{item.reason}</p>}
                </li>
              );
            })}
          </ul>
        )}

        <div className="space-y-2 border-t border-slate-200 pt-4">
          <label className="block text-xs text-slate-500" htmlFor="approval-reason">
            审批理由（驳回时建议填写）
          </label>
          <input
            id="approval-reason"
            className={inputClass}
            value={decisionReason}
            onChange={(event) => setDecisionReason(event.target.value)}
            placeholder="例如：客户已同意上门维修报价"
          />
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              onClick={() => void handleDecide("approve")}
              disabled={!canDecide || action === "decide-approve"}
            >
              {action === "decide-approve" ? "提交中…" : "批准"}
            </Button>
            <Button
              type="button"
              variant="danger"
              onClick={() => void handleDecide("reject")}
              disabled={!canDecide || action === "decide-reject"}
            >
              {action === "decide-reject" ? "提交中…" : "驳回"}
            </Button>
          </div>
          {!canDecide && (
            <p className="text-xs text-slate-500">
              当前状态 {caseStatus} 不可审批，需先提交审批进入 APPROVAL_PENDING。
            </p>
          )}
        </div>
      </Card>

      <Card
        eyebrow="Work order"
        title="工单"
        description="创建工单需先获得批准；同一幂等键重复提交返回原工单。"
      >
        <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label className="block text-xs text-slate-500" htmlFor="work-order-assignee">
              指派给（可选）
            </label>
            <input
              id="work-order-assignee"
              className={inputClass}
              value={assignee}
              onChange={(event) => setAssignee(event.target.value)}
              placeholder="例如：tech@demo.local"
            />
          </div>
          <Button
            type="button"
            onClick={handleCreateWorkOrder}
            disabled={!canCreateWorkOrder || action === "work-order"}
          >
            {action === "work-order" ? "创建中…" : "创建工单"}
          </Button>
        </div>
        <p className="mb-3 break-all text-xs text-slate-500">
          本次页面会话幂等键：<span className="font-mono">{idempotencyKey}</span>
          {!hasApproval && canCreateWorkOrder && "（当前无批准记录，后端将拒绝创建）"}
        </p>

        {workOrders.length === 0 ? (
          <p className="text-sm text-slate-500">暂无工单。</p>
        ) : (
          <ul className="space-y-2">
            {workOrders.map((item) => {
              const status = meta(WORK_ORDER_META, item.status);
              return (
                <li key={item.id} className="rounded-md border border-slate-200 px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-slate-500">{item.id}</span>
                    <Badge tone={status.tone}>{status.label}</Badge>
                    <span className="text-xs text-slate-500">指派 {item.assignee ?? "—"}</span>
                    <span className="text-xs text-slate-500">外部单号 {item.external_id ?? "—"}</span>
                    <span className="text-xs text-slate-400">{formatTime(item.created_at)}</span>
                  </div>
                  {item.resolution && <p className="mt-1 text-slate-700">结果：{item.resolution}</p>}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Card
        eyebrow="Outcome"
        title="维修结果录入"
        description="结果只能记录一次，不可覆盖；修订需新建工单。"
      >
        {canRecordOutcome ? (
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-slate-500" htmlFor="outcome-work-order">
                工单
              </label>
              <select
                id="outcome-work-order"
                className={inputClass}
                value={selectedWorkOrderId}
                onChange={(event) => setSelectedWorkOrderId(event.target.value)}
              >
                {workOrders.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id} · {item.status}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="block text-xs text-slate-500" htmlFor="outcome-cause">
                  实际根因代码
                </label>
                <input
                  id="outcome-cause"
                  className={inputClass}
                  value={actualCauseCode}
                  onChange={(event) => setActualCauseCode(event.target.value)}
                  placeholder="例如：FAN_BLOCKED"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-500" htmlFor="outcome-action">
                  处理动作
                </label>
                <select
                  id="outcome-action"
                  className={inputClass}
                  value={outcomeAction}
                  onChange={(event) => setOutcomeAction(event.target.value)}
                >
                  {OUTCOME_ACTIONS.map((item) => (
                    <option key={item} value={item}>
                      {ACTION_LABELS[item] ?? item}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="block text-xs text-slate-500" htmlFor="outcome-parts">
                更换配件（逗号分隔）
              </label>
              <input
                id="outcome-parts"
                className={inputClass}
                value={partsReplaced}
                onChange={(event) => setPartsReplaced(event.target.value)}
                placeholder="例如：FAN-MOTOR-1200"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500" htmlFor="outcome-note">
                备注
              </label>
              <input
                id="outcome-note"
                className={inputClass}
                value={outcomeNote}
                onChange={(event) => setOutcomeNote(event.target.value)}
                placeholder="例如：清理风道后风机恢复运转"
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={resolved}
                onChange={(event) => setResolved(event.target.checked)}
              />
              已解决
            </label>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                onClick={handleRecordOutcome}
                disabled={!selectedWorkOrderId || action === "outcome"}
              >
                {action === "outcome" ? "提交中…" : "提交维修结果"}
              </Button>
              {consistency && <Badge tone={consistency === "match" ? "green" : "orange"}>一致性 {consistency}</Badge>}
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-500">
            当前状态 {caseStatus} 不可录入结果，需案例进入 WORK_ORDER_CREATED。
          </p>
        )}

        {outcomes.length > 0 && (
          <ul className="mt-4 space-y-2 border-t border-slate-200 pt-4">
            {outcomes.map((item) => (
              <li key={item.id} className="rounded-md border border-slate-200 px-3 py-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-slate-500">{item.actual_cause_code}</span>
                  <Badge tone="blue">{ACTION_LABELS[item.action] ?? item.action}</Badge>
                  <Badge tone={item.resolved ? "green" : "red"}>
                    {item.resolved ? "已解决" : "未解决"}
                  </Badge>
                  <span className="text-xs text-slate-400">{formatTime(item.created_at)}</span>
                </div>
                {item.parts_replaced.length > 0 && (
                  <p className="mt-1 text-xs text-slate-600">更换配件：{item.parts_replaced.join("、")}</p>
                )}
                {item.note && <p className="mt-1 text-slate-700">{item.note}</p>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card eyebrow="Closure" title="关闭案例" description="关闭后案例闭环结束，只允许查看。">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={handleClose}
            disabled={!canClose || action === "close"}
          >
            {action === "close" ? "关闭中…" : "关闭案例"}
          </Button>
          {!canClose && (
            <span className="text-xs text-slate-500">
              当前状态 {caseStatus} 不可关闭，需为 WORK_ORDER_CREATED 或 OUTCOME_PENDING。
            </span>
          )}
        </div>
      </Card>
    </div>
  );
}