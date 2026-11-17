import Link from "next/link";

const LINKS = [
  { href: "/console", label: "概览" },
  { href: "/console/cases", label: "案例" },
  { href: "/console/eval", label: "评测" },
  { href: "/console/tasks", label: "任务" },
];

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-6 md:flex-row">
      <aside className="md:w-40 md:shrink-0">
        <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">工作台</p>
        <nav className="flex gap-3 text-sm md:flex-col md:gap-1">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded px-2 py-1 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </aside>
      <section className="min-w-0 flex-1">{children}</section>
    </div>
  );
}