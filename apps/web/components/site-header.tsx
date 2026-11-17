"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/console", label: "工作台", match: "/console" },
  { href: "/cases", label: "案例队列", match: "/cases" },
  { href: "/eval", label: "评测门禁", match: "/eval" },
];

export function SiteHeader() {
  const pathname = usePathname();
  const loginActive = pathname === "/login";

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-[#fbfcfa]/95 text-slate-900 shadow-[0_8px_24px_-22px_rgba(15,27,31,0.35)] backdrop-blur supports-[backdrop-filter]:bg-[#fbfcfa]/85">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6 lg:px-8">
        <Link href="/cases" className="flex items-center gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-teal-700 text-[13px] font-bold tracking-widest text-white shadow-[0_4px_12px_-6px_rgba(15,118,110,0.7)]">
            ZX
          </span>
          <span className="leading-tight">
            <span className="block text-[15px] font-semibold tracking-tight text-slate-950">智修</span>
            <span className="block text-[10px] uppercase tracking-[0.16em] text-slate-500">
              诊断决策与维修闭环
            </span>
          </span>
        </Link>

        <nav className="order-3 flex w-full items-center gap-1 overflow-x-auto md:order-none md:w-auto">
          {NAV.map((item) => {
            const active = pathname.startsWith(item.match);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`shrink-0 rounded-md px-3 py-1.5 text-xs font-medium transition ${
                  active
                    ? "bg-teal-50 text-teal-800 ring-1 ring-inset ring-teal-200/90"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-2.5">
          <span className="hidden items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-[10px] uppercase tracking-[0.12em] text-emerald-700 sm:inline-flex">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            local demo
          </span>
          <Link
            href="/login"
            className={`rounded-md px-2.5 py-1.5 text-xs font-semibold transition ${
              loginActive
                ? "bg-teal-50 text-teal-800 ring-1 ring-inset ring-teal-200"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"
            }`}
          >
            登录
          </Link>
          <Link
            href="/cases#new-case"
            className="rounded-md bg-teal-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-teal-800"
          >
            新建诊断
          </Link>
        </div>
      </div>
    </header>
  );
}
