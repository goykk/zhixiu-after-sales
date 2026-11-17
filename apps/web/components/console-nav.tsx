"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/console", label: "运营概览", index: "01", hint: "队列与健康度" },
  { href: "/console/cases", label: "案例台账", index: "02", hint: "全量诊断记录" },
  { href: "/console/eval", label: "评测门禁", index: "03", hint: "A/B/C/D 回归" },
  { href: "/console/tasks", label: "任务中心", index: "04", hint: "异步任务追踪" },
];

export function ConsoleNav() {
  const pathname = usePathname();

  return (
    <nav className="flex gap-1 overflow-x-auto lg:block lg:space-y-1 lg:overflow-visible">
      {LINKS.map((link) => {
        const active = pathname === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            className={`group flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 transition lg:w-full lg:gap-3 lg:py-2.5 ${
              active
                ? "bg-teal-50 text-teal-900 ring-1 ring-inset ring-teal-200"
                : "text-slate-600 hover:bg-slate-50 hover:text-slate-950"
            }`}
          >
            <span
              className={`font-mono text-[10px] tracking-widest ${
                active ? "text-teal-700" : "text-slate-400 group-hover:text-slate-600"
              }`}
            >
              {link.index}
            </span>
            <span className="min-w-0">
              <span className="block whitespace-nowrap text-sm font-medium">{link.label}</span>
              <span
                className={`hidden text-[10px] lg:block ${
                  active ? "text-teal-700/70" : "text-slate-500"
                }`}
              >
                {link.hint}
              </span>
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
