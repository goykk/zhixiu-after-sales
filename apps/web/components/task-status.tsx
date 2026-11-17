"use client";

import { useEffect, useRef, useState } from "react";
import { Badge, type BadgeTone } from "@/components/ui";
import { errorText, getTask } from "@/lib/api";
import type { TaskInfo, TaskStatus as TaskStatusValue } from "@/lib/types";

const TONES: Record<TaskStatusValue, BadgeTone> = {
  PENDING: "neutral",
  STARTED: "blue",
  SUCCESS: "green",
  FAILURE: "red",
};

function summarize(result: Record<string, unknown> | null): string | null {
  if (!result) return null;
  const keys = ["run_id", "case_status", "chunk_count", "status", "passed", "manual_id"];
  const picked: Record<string, unknown> = {};
  for (const key of keys) {
    if (key in result) picked[key] = result[key];
  }
  const payload = Object.keys(picked).length > 0 ? picked : result;
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

export function TaskStatus({
  taskId,
  onDone,
  pollMs = 2000,
  maxPolls = 60,
}: {
  taskId: string;
  onDone?: (task: TaskInfo) => void;
  pollMs?: number;
  maxPolls?: number;
}) {
  const [task, setTask] = useState<TaskInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [count, setCount] = useState(0);
  const onDoneRef = useRef(onDone);

  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let polls = 0;
    setTask(null);
    setError(null);
    setCount(0);

    const tick = async () => {
      if (cancelled) return;
      try {
        const info = await getTask(taskId);
        if (cancelled) return;
        setTask(info);
        polls += 1;
        setCount(polls);
        if (info.status === "SUCCESS" || info.status === "FAILURE") {
          onDoneRef.current?.(info);
          return;
        }
      } catch (err) {
        if (!cancelled) setError(errorText(err));
        return;
      }
      if (polls >= maxPolls) return;
      timer = setTimeout(() => void tick(), pollMs);
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [taskId, pollMs, maxPolls]);

  const summary = task ? summarize(task.result) : null;

  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-slate-700">{taskId.slice(0, 20)}…</span>
        <Badge tone={task ? TONES[task.status] : "neutral"}>
          {task ? task.status : "查询中…"}
        </Badge>
        <span className="text-xs text-slate-500">
          轮询 {count}/{maxPolls}
        </span>
        {task?.backend && <span className="text-xs text-slate-400">backend={task.backend}</span>}
      </div>
      {error && <p className="mt-2 break-all text-xs text-red-700">{error}</p>}
      {task?.error && <p className="mt-2 break-all text-xs text-red-700">{task.error}</p>}
      {task?.status === "SUCCESS" && summary && (
        <pre className="mt-2 max-h-40 overflow-auto rounded bg-white p-2 text-xs text-slate-700">
          {summary}
        </pre>
      )}
      {task && task.status !== "SUCCESS" && task.status !== "FAILURE" && count >= maxPolls && (
        <p className="mt-2 text-xs text-amber-700">
          已达轮询上限，任务可能仍在执行，可稍后刷新查看。
        </p>
      )}
    </div>
  );
}