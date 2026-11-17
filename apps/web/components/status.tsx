import type { BadgeTone } from "@/components/ui";

export interface CaseStatusMeta {
  label: string;
  tone: BadgeTone;
  rail: string;
  hint: string;
}

export const CASE_STATUS_META: Record<string, CaseStatusMeta> = {
  DRAFT: { label: "草稿", tone: "neutral", rail: "bg-slate-400", hint: "等待受理" },
  COLLECTING_INFO: { label: "补充信息", tone: "blue", rail: "bg-sky-500", hint: "缺少关键字段" },
  EVIDENCE_READY: { label: "证据就绪", tone: "teal", rail: "bg-teal-500", hint: "可生成候选根因" },
  HYPOTHESIZING: { label: "假设生成中", tone: "teal", rail: "bg-teal-600", hint: "候选等待排序" },
  PROBE_PENDING: { label: "待检查", tone: "orange", rail: "bg-amber-500", hint: "有检查未回填" },
  PROBE_EVALUATING: { label: "检查评估中", tone: "blue", rail: "bg-sky-500", hint: "正在更新证据" },
  DIAGNOSED: { label: "已诊断", tone: "green", rail: "bg-emerald-500", hint: "可制定维修方案" },
  REPAIR_PLANNING: { label: "维修规划", tone: "teal", rail: "bg-teal-500", hint: "方案待提交" },
  APPROVAL_PENDING: { label: "待审批", tone: "orange", rail: "bg-amber-500", hint: "等待人工审批" },
  WORK_ORDER_CREATED: { label: "已建工单", tone: "blue", rail: "bg-sky-500", hint: "等待执行结果" },
  OUTCOME_PENDING: { label: "待回收", tone: "orange", rail: "bg-amber-500", hint: "结果尚未回收" },
  NEED_HUMAN: { label: "转人工", tone: "red", rail: "bg-rose-500", hint: "需要人工接管" },
  CLOSED: { label: "已关闭", tone: "neutral", rail: "bg-slate-500", hint: "闭环完成" },
};

export function caseStatusMeta(status: string | null | undefined): CaseStatusMeta {
  if (!status) return { label: "未知", tone: "neutral", rail: "bg-slate-300", hint: "状态缺失" };
  return CASE_STATUS_META[status] ?? {
    label: status,
    tone: "neutral",
    rail: "bg-slate-300",
    hint: "状态待确认",
  };
}

export const NEXT_ACTION: Record<string, string> = {
  DRAFT: "受理并提取设备与故障信息",
  COLLECTING_INFO: "补充缺失字段，完成信息受理",
  EVIDENCE_READY: "生成候选根因，建立证据与假设的对应",
  HYPOTHESIZING: "规划下一项检查，或直接生成诊断结论",
  PROBE_PENDING: "录入当前检查结果，更新证据版本",
  PROBE_EVALUATING: "等待检查评估完成，确认候选排序",
  DIAGNOSED: "生成维修方案并提交审批",
  REPAIR_PLANNING: "核对配件与步骤，提交维修审批",
  APPROVAL_PENDING: "跟进审批，批准后创建工单",
  WORK_ORDER_CREATED: "执行维修工单并回收结果",
  OUTCOME_PENDING: "录入维修结果，完成闭环",
  NEED_HUMAN: "转人工接管，补齐证据或执行特殊处置",
  CLOSED: "案例已闭环，可复盘诊断与维修记录",
};

export function nextAction(status: string | null | undefined): string {
  if (!status) return "确认案例状态";
  return NEXT_ACTION[status] ?? "确认当前状态后再推进";
}
