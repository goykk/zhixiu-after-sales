import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "智修 V1.2 诊断工作台",
  description: "多模态售后工单诊断工作台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
            <Link href="/cases" className="text-lg font-semibold text-slate-900">
              智修诊断工作台
            </Link>
            <nav className="flex items-center gap-5 text-sm text-slate-600">
              <Link href="/console" className="hover:text-slate-900">
                工作台
              </Link>
              <Link href="/cases" className="hover:text-slate-900">
                案例
              </Link>
              <Link href="/eval" className="hover:text-slate-900">
                评测
              </Link>
              <Link href="/login" className="hover:text-slate-900">
                登录
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}