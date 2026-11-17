"use client";

import { useState, type FormEvent } from "react";
import { Button, inputClass } from "@/components/ui";
import { errorText } from "@/lib/api";
import type { EvidenceInput } from "@/lib/types";

const SOURCE_TYPES = ["customer", "media", "manual", "probe", "model"] as const;
const SOURCE_LABELS: Record<string, string> = {
  customer: "客户描述",
  media: "照片/媒体",
  manual: "手册",
  probe: "检查结果",
  model: "模型推测",
};
const POLARITIES = ["support", "refute", "neutral"] as const;
const POLARITY_LABELS: Record<string, string> = {
  support: "支持",
  refute: "反对",
  neutral: "中立",
};

export function EvidenceForm({
  onSubmit,
}: {
  onSubmit: (payload: EvidenceInput) => Promise<void>;
}) {
  const [sourceType, setSourceType] = useState<string>("customer");
  const [polarity, setPolarity] = useState<string>("support");
  const [quote, setQuote] = useState("");
  const [page, setPage] = useState("1");
  const [sourceRef, setSourceRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = quote.trim();
    if (!text) {
      setError("引用内容不能为空");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit({
        source_type: sourceType,
        polarity,
        quote: text,
        page: Number(page) || 1,
        source_ref: sourceRef.trim() || null,
      });
      setQuote("");
      setSourceRef("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="space-y-3" onSubmit={handleSubmit}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">来源</span>
          <select
            className={inputClass}
            value={sourceType}
            onChange={(event) => setSourceType(event.target.value)}
          >
            {SOURCE_TYPES.map((value) => (
              <option key={value} value={value}>
                {SOURCE_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">极性</span>
          <select
            className={inputClass}
            value={polarity}
            onChange={(event) => setPolarity(event.target.value)}
          >
            {POLARITIES.map((value) => (
              <option key={value} value={value}>
                {POLARITY_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="block text-sm">
        <span className="mb-1 block text-slate-600">引用内容</span>
        <textarea
          className={inputClass}
          rows={3}
          value={quote}
          placeholder="原始证据文本，例如：外机风扇不转，有嗡嗡声"
          onChange={(event) => setQuote(event.target.value)}
        />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">页码</span>
          <input
            className={inputClass}
            type="number"
            min={1}
            value={page}
            onChange={(event) => setPage(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-slate-600">来源标识（可选）</span>
          <input
            className={inputClass}
            value={sourceRef}
            placeholder="图片文件名 / 检查编号"
            onChange={(event) => setSourceRef(event.target.value)}
          />
        </label>
      </div>
      {sourceType === "model" && (
        <p className="text-xs text-slate-500">模型推测仅用于展示，不计入支持证据。</p>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <Button type="submit" disabled={busy}>
        {busy ? "提交中…" : "登记证据"}
      </Button>
    </form>
  );
}