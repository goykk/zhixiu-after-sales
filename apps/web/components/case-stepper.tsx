import { caseStatusMeta } from "@/components/status";

const STEPS = [
  { key: "intake", label: "受理", hint: "设备 / 故障码" },
  { key: "evidence", label: "证据", hint: "描述 / 媒体 / 手册" },
  { key: "hypothesis", label: "假设", hint: "候选根因排序" },
  { key: "probe", label: "检查", hint: "最小成本验证" },
  { key: "conclusion", label: "结论", hint: "根因与置信" },
  { key: "repair", label: "维修", hint: "方案 / 配件" },
  { key: "approval", label: "审批", hint: "风险与人工确认" },
  { key: "workorder", label: "工单", hint: "执行与配件" },
  { key: "outcome", label: "结果", hint: "回收与复盘" },
  { key: "closed", label: "关闭", hint: "闭环完成" },
];

const STATUS_INDEX: Record<string, number> = {
  DRAFT: 0,
  COLLECTING_INFO: 0,
  EVIDENCE_READY: 1,
  HYPOTHESIZING: 2,
  PROBE_PENDING: 3,
  PROBE_EVALUATING: 3,
  DIAGNOSED: 4,
  REPAIR_PLANNING: 5,
  APPROVAL_PENDING: 6,
  WORK_ORDER_CREATED: 7,
  OUTCOME_PENDING: 8,
  NEED_HUMAN: 4,
  CLOSED: 9,
};

export function CaseStepper({ status }: { status: string }) {
  const meta = caseStatusMeta(status);
  const current = STATUS_INDEX[status] ?? 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-slate-700">
          当前阶段
          <span className="ml-2 font-normal text-slate-500">{meta.label}</span>
        </p>
        <p className="text-[11px] text-slate-500">{meta.hint}</p>
      </div>
      <div className="-mx-1 overflow-x-auto pb-1">
        <ol className="flex min-w-[720px] items-start gap-0 px-1">
          {STEPS.map((step, index) => {
            const done = index < current;
            const active = index === current;
            return (
              <li key={step.key} className="relative flex-1">
                {index < STEPS.length - 1 && (
                  <span
                    className={`absolute left-[calc(50%+14px)] right-[calc(-50%+14px)] top-3 h-px ${
                      done ? "bg-teal-500" : "bg-slate-200"
                    }`}
                  />
                )}
                <div className="relative flex flex-col items-center text-center">
                  <span
                    className={`grid h-6 w-6 place-items-center rounded-full border text-[10px] font-bold ${
                      done
                        ? "border-teal-600 bg-teal-600 text-white"
                        : active
                          ? "border-teal-600 bg-white text-teal-700 ring-4 ring-teal-600/10"
                          : "border-slate-300 bg-white text-slate-400"
                    } ${active && status === "NEED_HUMAN" ? "border-rose-500 text-rose-600 ring-rose-500/10" : ""}`}
                  >
                    {done ? "✓" : index + 1}
                  </span>
                  <span
                    className={`mt-1.5 text-[11px] font-semibold ${
                      active ? "text-slate-950" : done ? "text-teal-800" : "text-slate-400"
                    }`}
                  >
                    {step.label}
                  </span>
                  <span className="mt-0.5 text-[9px] leading-3 text-slate-400">{step.hint}</span>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
