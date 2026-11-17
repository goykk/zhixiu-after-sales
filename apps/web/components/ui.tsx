"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

export type BadgeTone = "neutral" | "blue" | "green" | "orange" | "red" | "purple";

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  blue: "bg-blue-50 text-blue-700 ring-blue-200",
  green: "bg-green-50 text-green-700 ring-green-200",
  orange: "bg-orange-50 text-orange-700 ring-orange-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  purple: "bg-purple-50 text-purple-700 ring-purple-200",
};

const BUTTON_VARIANTS = {
  primary: "bg-slate-900 text-white hover:bg-slate-700 disabled:bg-slate-400",
  secondary: "bg-white text-slate-800 ring-1 ring-inset ring-slate-300 hover:bg-slate-50",
  danger: "bg-red-600 text-white hover:bg-red-500 disabled:bg-red-300",
} as const;

export type ButtonVariant = keyof typeof BUTTON_VARIANTS;

export const inputClass =
  "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-500 focus:outline-none disabled:bg-slate-100";

export function Button({
  variant = "primary",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed ${BUTTON_VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Card({
  title,
  description,
  actions,
  children,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      {(title || actions) && (
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
            {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${BADGE_TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <span className="break-all">{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 font-medium text-red-700 underline hover:text-red-900"
        >
          重试
        </button>
      )}
    </div>
  );
}

export function Spinner({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 px-1 py-6 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" />
      <span>{label}</span>
    </div>
  );
}