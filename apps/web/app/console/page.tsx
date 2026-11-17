"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  PageHeader,
  ProgressBar,
  Spinner,
  StatCard,
} from "@/components/ui";
import { caseStatusMeta } from "@/components/status";
import { errorText, getOverview, getToken, listTasks } from "@/lib/api";
import type { Overview, TaskInfo, TaskStatus } from "@/lib/types";

const TASK_META: Record<TaskStatus, { label: string; tone: "blue" | "green" | "orange" | "red" }> = {
  PENDING: { label: "排队", tone: "blue" },
  STARTED: { label: "运行中", tone: "orange" },
  SUCCESS: { label: "成功", tone: "green" },
  FAILURE: { label: "失败", tone: "red" },
};

const QUEUE_ROWS = [
  {
    status: "NEED_HUMAN",
    label: "待人工接管",
    hint: "异常、低置信或高风险案例，需要人工判断后再推进",
    href: "/cases",
    action: "去接管",
  },
  {
    status: "PROBE_PENDING",
    label: "待回填检查",
    hint: "已有下一项检查，但观察结果尚未录入",
    href: "/cases",
    action: "补检查",
  },
  {
    status: "DIAGNOSED",
    label: "已诊断待维修",
    hint: "根因已形成，可进入维修方案与配件核对",
    href: "/cases",
    action: "定方案",
  },
  {
    status: "APPROVAL_PENDING",
    label: "待审批",
    hint: "维修方案等待人工确认风险与配件",
    href: "/cases",
    action: "跟审批",
  },
  {
    status: "OUTCOME_PENDING",
    label: "待回收结果",
    hint: "工单已执行，维修结果尚未回填闭环",
    href: "/cases",
    action: "收结果",
  },
];

export default function ConsoleOverviewPage() {
  const router = useRouter();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ov, taskList] = await Promise.all([getOverview(), listTasks({ limit: 10 })]);
      setOverview(ov);
      setTasks(taskList.items);
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

  if (loading) return <Spinner label="加载运营概览…" />;
  if (error) return <ErrorBanner message={error} onRetry={() => void load()} />;
  if (!overview) return null;

  const o = overview;
  const latest = o.eval_runs.latest_passed;
  const byStatus = o.cases.by_status ?? {};
  const statusEntries = Object.entries(byStatus)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  const pendingTasks = (o.tasks.by_status?.PENDING ?? 0) + (o.tasks.by_status?.STARTED ?? 0);
  const diagnosisRate = o.cases.total > 0 ? o.diagnosed / o.cases.total : 0;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Command overview / 运营总览"
        title="今天先处理什么"
        description="把待人工、待检查、待维修、待回收分成行动队列；先清阻塞，再看指标。"
        meta={
          <>
            <Badge tone={latest === null ? "neutral" : latest ? "green" : "red"}>
              {latest === null ? "暂无评测" : latest ? "评测门禁通过" : "评测门禁未通过"}
            </Badge>
            <span className="text-xs text-slate-500">数据生成于 {o.generated_at}</span>
          </>
        }
        actions={
          <Link
            href="/cases"
            className="inline-flex items-center justify-center rounded-lg bg-teal-700 px-3.5 py-2 text-sm font-semibold text-white transition hover:bg-teal-800"
          >
            打开案例队列
          </Link>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Link href="/cases" className="block">
          <StatCard
            label="案例总量"
            value={o.cases.total}
            hint={`已诊断 ${o.diagnosed} · 待人工 ${o.need_human}`}
            tone="teal"
            progress={diagnosisRate}
            footer={`诊断覆盖 ${Math.round(diagnosisRate * 100)}%`}
          />
        </Link>
        <Link href="/cases" className="block">
          <StatCard
            label="优先接管"
            value={o.need_human}
            hint={o.need_human > 0 ? "需要人工判断，不能继续自动推进" : "当前没有人工阻塞，继续巡检其余队列"}
            tone="red"
            footer={o.need_human > 0 ? "建议先清空此队列" : "人工队列已清空"}
          />
        </Link>
        <Link href="/cases" className="block">
          <StatCard
            label="维修工单"
            value={o.work_orders.total}
            hint={`已回收结果 ${o.outcomes} 条`}
            tone="amber"
            footer={o.work_orders.total > 0 ? `回收率 ${Math.round((o.outcomes / o.work_orders.total) * 100)}%` : "暂无工单"}
          />
        </Link>
        <Link href="/console/eval" className="block">
          <StatCard
            label="评测运行"
            value={o.eval_runs.total}
            hint={latest === null ? "尚未跑过正式评测" : latest ? "最近一次门禁通过" : "最近一次门禁失败"}
            tone={latest === null ? "default" : latest ? "green" : "red"}
            footer="A / B / C / D 四策略对比"
          />
        </Link>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(280px,1fr)]">
        <Card
          eyebrow="Action queue"
          title="行动队列"
          description="按业务阻塞排序，不是按创建时间排序。"
          actions={<Badge tone="orange">{QUEUE_ROWS.reduce((sum, row) => sum + (byStatus[row.status] ?? 0), 0)} 项待处理</Badge>}
        >
          <div className="divide-y divide-slate-100">
            {QUEUE_ROWS.map((row) => {
              const meta = caseStatusMeta(row.status);
              const count = byStatus[row.status] ?? 0;
              return (
                <div key={row.status} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
                  <span className={`h-8 w-1 shrink-0 rounded-full ${meta.rail}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-slate-950">{row.label}</p>
                      <Badge tone={meta.tone}>{count}</Badge>
                    </div>
                    <p className="mt-0.5 text-xs leading-5 text-slate-500">{row.hint}</p>
                  </div>
                  <Link
                    href={row.href}
                    className="shrink-0 rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-slate-700 transition hover:border-teal-600 hover:text-teal-800"
                  >
                    {count > 0 ? row.action : "暂无"}
                  </Link>
                </div>
              );
            })}
          </div>
        </Card>

        <div className="space-y-4">
          <div className="rounded-xl border border-teal-200/70 bg-[#eef4f1] p-5 text-slate-950 shadow-[0_1px_2px_rgba(15,27,31,0.04),0_18px_40px_-36px_rgba(15,27,31,0.3)]">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-700">
              System pulse
            </p>
            <h2 className="mt-1 text-base font-semibold text-slate-950">运行健康</h2>
            <dl className="mt-4 space-y-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate-600">评测门禁</dt>
                <dd>
                  <Badge tone={latest === null ? "neutral" : latest ? "green" : "red"}>
                    {latest === null ? "未运行" : latest ? "PASSED" : "FAILED"}
                  </Badge>
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate-600">异步任务</dt>
                <dd className="font-mono text-xs text-slate-800">
                  {pendingTasks} 运行 / {o.tasks.total} 总数
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate-600">结果闭环</dt>
                <dd className="font-mono text-xs text-slate-800">
                  {o.outcomes} / {o.work_orders.total}
                </dd>
              </div>
            </dl>
            <div className="mt-4">
              <div className="mb-1.5 flex items-center justify-between text-[10px] text-slate-500">
                <span>诊断覆盖率</span>
                <span>{Math.round(diagnosisRate * 100)}%</span>
              </div>
              <ProgressBar value={diagnosisRate} tone="green" />
            </div>
            <p className="mt-4 border-t border-teal-200/60 pt-3 text-[10px] leading-4 text-slate-500">
              本地演示环境 · 后端 8000 · 前端 3001
            </p>
          </div>

          <Card eyebrow="Next step" title="快捷动作">
            <div className="space-y-2">
              {[
                { href: "/cases", label: "新建一条诊断案例", hint: "从设备型号与故障码开始" },
                { href: "/eval", label: "查看最近评测结果", hint: "确认门禁与策略差异" },
                { href: "/console/tasks", label: "追踪异步任务", hint: "诊断推进与报告生成" },
              ].map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2.5 transition hover:border-teal-300 hover:bg-teal-50/40"
                >
                  <span>
                    <span className="block text-sm font-medium text-slate-900">{item.label}</span>
                    <span className="mt-0.5 block text-[11px] text-slate-500">{item.hint}</span>
                  </span>
                  <span className="text-teal-700">→</span>
                </Link>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <Card
        eyebrow="Pipeline"
        title="案例阶段分布"
        description="用阶段分布判断阻塞点：数量堆积在哪里，下一步就该清哪里。"
      >
        {statusEntries.length === 0 ? (
          <EmptyState title="还没有案例" description="创建第一条案例后，这里会按状态显示诊断流程的分布。" />
        ) : (
          <>
            <div className="flex h-3 overflow-hidden rounded-full bg-slate-100">
              {statusEntries.map(([status, count]) => {
                const meta = caseStatusMeta(status);
                const width = o.cases.total > 0 ? (count / o.cases.total) * 100 : 0;
                return (
                  <span
                    key={status}
                    className={`${meta.rail} h-full`}
                    style={{ width: `${width}%` }}
                    title={`${meta.label} ${count}`}
                  />
                );
              })}
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {statusEntries.map(([status, count]) => {
                const meta = caseStatusMeta(status);
                return (
                  <div key={status} className="flex items-center gap-2 rounded-md bg-slate-50 px-2.5 py-2">
                    <span className={`h-2 w-2 rounded-full ${meta.rail}`} />
                    <span className="min-w-0 flex-1 truncate text-xs text-slate-700">{meta.label}</span>
                    <span className="font-mono text-xs font-semibold text-slate-950">{count}</span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </Card>

      <Card
        eyebrow="Recent activity"
        title="最近任务"
        description="异步推进与报告任务的执行记录，优先关注运行中与失败。"
        actions={<Badge tone="neutral">{tasks.length} 条</Badge>}
      >
        {tasks.length === 0 ? (
          <EmptyState title="暂无任务" description="提交异步诊断或评测后，任务会出现在这里。" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-[10px] uppercase tracking-[0.12em] text-slate-500">
                  <th className="py-2 pr-3 font-semibold">任务</th>
                  <th className="px-3 py-2 font-semibold">状态</th>
                  <th className="px-3 py-2 font-semibold">后端</th>
                  <th className="pl-3 py-2 font-semibold">创建时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {tasks.map((t) => {
                  const meta = TASK_META[t.status];
                  return (
                    <tr key={t.task_id} className="hover:bg-slate-50/70">
                      <td className="py-2.5 pr-3 font-mono text-[11px] text-slate-700">{t.task_id.slice(0, 8)}</td>
                      <td className="px-3 py-2.5">
                        <Badge tone={meta.tone}>{meta.label}</Badge>
                      </td>
                      <td className="px-3 py-2.5 text-xs text-slate-500">{t.backend}</td>
                      <td className="pl-3 py-2.5 text-xs text-slate-500">{t.created_at}</td>
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
