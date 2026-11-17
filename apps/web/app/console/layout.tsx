import { ConsoleNav } from "@/components/console-nav";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
      <aside className="lg:sticky lg:top-24 lg:self-start">
        <div className="rounded-xl border border-slate-200/80 bg-white p-1.5 shadow-[0_1px_2px_rgba(15,27,31,0.04),0_14px_30px_-26px_rgba(15,27,31,0.28)] lg:p-3">
          <div className="hidden px-3 pb-3 pt-2 lg:block">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-700">
              Operations
            </p>
            <p className="mt-1 text-sm font-semibold text-slate-950">运营控制台</p>
            <p className="mt-1 text-[10px] leading-4 text-slate-500">按队列处理，而不是按页面浏览</p>
          </div>
          <div className="lg:border-t lg:border-slate-100 lg:pt-3">
            <ConsoleNav />
          </div>
          <div className="mt-3 hidden border-t border-slate-100 px-3 pt-3 text-[10px] leading-4 text-slate-500 lg:block">
            <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 align-middle" />
            本地演示数据 · 9 设备 / 36 手册
          </div>
        </div>
      </aside>
      <section className="min-w-0">{children}</section>
    </div>
  );
}
