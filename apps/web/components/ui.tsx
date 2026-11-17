"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

export type BadgeTone = "neutral" | "blue" | "teal" | "green" | "orange" | "red";

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  blue: "bg-sky-50 text-sky-700 ring-sky-200",
  teal: "bg-teal-50 text-teal-800 ring-teal-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  orange: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-rose-50 text-rose-700 ring-rose-200",
};

const BUTTON_VARIANTS = {
  primary: "bg-teal-700 text-white hover:bg-teal-800 disabled:bg-teal-700/50",
  secondary:
    "bg-white text-slate-800 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900",
  danger: "bg-rose-600 text-white hover:bg-rose-500 disabled:bg-rose-300",
} as const;

export type ButtonVariant = keyof typeof BUTTON_VARIANTS;

export const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-teal-600 focus:ring-2 focus:ring-teal-600/15 disabled:bg-slate-100 disabled:text-slate-500";

export function Button({
  variant = "primary",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold transition disabled:cursor-not-allowed ${BUTTON_VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Card({
  id,
  title,
  description,
  eyebrow,
  actions,
  tone = "default",
  className = "",
  children,
}: {
  id?: string;
  title?: ReactNode;
  description?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  tone?: "default" | "accent" | "warning";
  className?: string;
  children: ReactNode;
}) {
  const accent =
    tone === "accent"
      ? "border-teal-200/80 bg-teal-50/30"
      : tone === "warning"
        ? "border-amber-200/80 bg-amber-50/30"
        : "border-slate-200/80 bg-white";

  return (
    <section id={id} className={`surface relative overflow-hidden p-5 ${accent} ${className}`}>
      {(title || description || actions || eyebrow) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
            {title && (
              <h2 className="text-base font-semibold tracking-tight text-slate-950">{title}</h2>
            )}
            {description && (
              <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">{description}</p>
            )}
          </div>
          {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  meta,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-slate-200/80 pb-5">
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-1.5">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold tracking-tight text-slate-950 sm:text-[28px]">{title}</h1>
        {description && (
          <p className="mt-1.5 max-w-2xl text-sm leading-6 text-slate-600">{description}</p>
        )}
        {meta && <div className="mt-3 flex flex-wrap items-center gap-2">{meta}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${BADGE_TONES[tone]}`}
    >
      {children}
    </span>
  );
}

const STAT_ACCENTS = {
  default: "bg-slate-400",
  teal: "bg-teal-600",
  green: "bg-emerald-500",
  amber: "bg-amber-500",
  red: "bg-rose-500",
  blue: "bg-sky-500",
} as const;

export function StatCard({
  label,
  value,
  hint,
  tone = "default",
  progress,
  footer,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: keyof typeof STAT_ACCENTS;
  progress?: number;
  footer?: ReactNode;
}) {
  return (
    <div className="surface relative overflow-hidden p-4">
      <span className={`absolute inset-x-0 top-0 h-[3px] ${STAT_ACCENTS[tone]}`} />
      <p className="data-label">{label}</p>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span className="text-[27px] font-semibold leading-none tracking-tight text-slate-950">
          {value}
        </span>
      </div>
      {hint && <p className="mt-1.5 text-xs leading-5 text-slate-500">{hint}</p>}
      {progress !== undefined && (
        <div className="mt-3">
          <ProgressBar value={progress} tone={tone === "default" ? "slate" : tone} />
        </div>
      )}
      {footer && <div className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-500">{footer}</div>}
    </div>
  );
}

const PROGRESS_TONES = {
  slate: "bg-slate-500",
  teal: "bg-teal-600",
  green: "bg-emerald-500",
  amber: "bg-amber-500",
  red: "bg-rose-500",
  blue: "bg-sky-500",
} as const;

export function ProgressBar({
  value,
  tone = "teal",
}: {
  value: number;
  tone?: keyof typeof PROGRESS_TONES;
}) {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
      <div className={`h-full rounded-full ${PROGRESS_TONES[tone]}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      <span className="break-all">{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 font-semibold text-rose-700 underline decoration-rose-300 underline-offset-2 hover:text-rose-900"
        >
          重试
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/70 px-5 py-8 text-center">
      <p className="text-sm font-semibold text-slate-800">{title}</p>
      {description && <p className="mx-auto mt-1 max-w-md text-xs leading-5 text-slate-500">{description}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function Spinner({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 px-1 py-6 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-teal-700" />
      <span>{label}</span>
    </div>
  );
}
