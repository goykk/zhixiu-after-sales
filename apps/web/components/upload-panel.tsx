"use client";

import { useState } from "react";
import { Badge, Button } from "@/components/ui";
import { errorText } from "@/lib/api";
import type { UploadItem } from "@/lib/types";

function formatSize(size: number): string {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}

export function UploadPanel({
  uploads,
  onUpload,
}: {
  uploads: UploadItem[];
  onUpload: (file: File) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleUpload() {
    if (!file) {
      setError("请先选择文件");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onUpload(file);
      setFile(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="file"
          accept=".jpg,.jpeg,.png,.webp,.pdf,.md,.txt"
          className="text-sm text-slate-700 file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-700"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <Button type="button" onClick={handleUpload} disabled={busy || !file}>
          {busy ? "上传中…" : "上传证据文件"}
        </Button>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {uploads.length === 0 ? (
        <p className="text-sm text-slate-500">暂无上传文件。</p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
          {uploads.map((item) => (
            <li
              key={item.id}
              className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
            >
              <span className="font-medium text-slate-800">{item.filename}</span>
              <span className="flex items-center gap-2 text-xs text-slate-500">
                <span>{formatSize(item.size)}</span>
                <Badge tone={item.status === "stored" ? "green" : "neutral"}>
                  {item.status}
                </Badge>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}