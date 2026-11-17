"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Badge, Button, Card, ErrorBanner, inputClass } from "@/components/ui";
import { errorText, login, register, setToken } from "@/lib/api";

type Mode = "login" | "register";

const FLOW = [
  { step: "01", title: "受理", text: "设备、故障码与客户描述进入同一案例。" },
  { step: "02", title: "证据与检查", text: "证据账本保留支持与反对，下一项检查只给一项。" },
  { step: "03", title: "结论到闭环", text: "根因、维修方案、审批、工单与结果全部可追溯。" },
];

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const normalized = email.trim();
      const auth =
        mode === "login"
          ? await login(normalized, password)
          : await register(normalized, password, displayName.trim() || null);
      setToken(auth.access_token || auth.token);
      router.replace("/cases");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto grid max-w-5xl gap-6 py-2 lg:grid-cols-[minmax(0,1.05fr)_minmax(340px,0.85fr)] lg:items-stretch">
      <section className="relative order-2 overflow-hidden rounded-xl border border-teal-200/70 bg-[#eef4f1] p-6 text-slate-950 shadow-[0_1px_2px_rgba(15,27,31,0.04),0_24px_60px_-45px_rgba(15,27,31,0.35)] sm:p-8 lg:order-1">
        <div className="absolute -right-16 -top-16 h-48 w-48 rounded-full bg-teal-300/20 blur-2xl" />
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-700">
          Zhixiu V1.2 / Diagnostic workspace
        </p>
        <h1 className="mt-3 max-w-md text-3xl font-semibold leading-tight tracking-tight text-slate-950">
          把维修判断，变成一条可追溯的链路
        </h1>
        <p className="mt-3 max-w-md text-sm leading-6 text-slate-600">
          不是直接给答案，而是让证据、候选根因、检查、结论与维修结果逐段可核对。
        </p>

        <ol className="mt-8 space-y-4">
          {FLOW.map((item) => (
            <li key={item.step} className="flex gap-3">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-teal-200 bg-white font-mono text-[10px] font-semibold text-teal-700">
                {item.step}
              </span>
              <div>
                <p className="text-sm font-semibold text-slate-950">{item.title}</p>
                <p className="mt-0.5 text-xs leading-5 text-slate-600">{item.text}</p>
              </div>
            </li>
          ))}
        </ol>

        <div className="mt-8 grid grid-cols-3 gap-3 border-t border-teal-200/60 pt-5">
          <div>
            <p className="text-xl font-semibold text-slate-950">19</p>
            <p className="text-[10px] text-slate-500">数据表</p>
          </div>
          <div>
            <p className="text-xl font-semibold text-slate-950">9</p>
            <p className="text-[10px] text-slate-500">演示设备</p>
          </div>
          <div>
            <p className="text-xl font-semibold text-slate-950">36</p>
            <p className="text-[10px] text-slate-500">设备手册</p>
          </div>
        </div>
      </section>

      <Card
        eyebrow="Access"
        title={mode === "login" ? "进入诊断工作台" : "创建工作台账号"}
        description={mode === "login" ? "使用邮箱与密码登录。" : "注册后立即进入案例队列。"}
        className="order-1 lg:order-2"
      >
        <form className="space-y-4" onSubmit={handleSubmit}>
          {mode === "register" && (
            <label className="block text-sm">
              <span className="mb-1 block text-xs font-medium text-slate-600">显示名称</span>
              <input
                className={inputClass}
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="可选"
              />
            </label>
          )}
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-slate-600">邮箱</span>
            <input
              className={inputClass}
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="user@example.com"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-slate-600">密码</span>
            <input
              className={inputClass}
              type="password"
              required
              minLength={mode === "register" ? 8 : 1}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error && <ErrorBanner message={error} />}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "提交中…" : mode === "login" ? "登录工作台" : "注册并登录"}
          </Button>
        </form>

        {mode === "login" && (
          <button
            type="button"
            className="mt-3 w-full rounded-lg border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-500 transition hover:border-teal-300 hover:bg-teal-50/40 hover:text-teal-800"
            onClick={() => {
              setEmail("agent@demo.local");
              setPassword("demo1234");
              setError(null);
            }}
          >
            填入演示账号 agent@demo.local
          </button>
        )}

        <div className="mt-5 flex items-center justify-between border-t border-slate-100 pt-4">
          <button
            type="button"
            className="text-xs text-slate-600 underline decoration-slate-300 underline-offset-2 hover:text-slate-900"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError(null);
            }}
          >
            {mode === "login" ? "没有账号？去注册" : "已有账号？去登录"}
          </button>
          <Badge tone="neutral">local demo</Badge>
        </div>
      </Card>
    </div>
  );
}
