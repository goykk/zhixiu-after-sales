"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, ErrorBanner, inputClass } from "@/components/ui";
import { errorText, login, register, setToken } from "@/lib/api";

type Mode = "login" | "register";

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
    <div className="mx-auto max-w-md">
      <Card
        title={mode === "login" ? "登录" : "注册"}
        description="使用邮箱与密码进入诊断工作台。"
      >
        <form className="space-y-3" onSubmit={handleSubmit}>
          {mode === "register" && (
            <label className="block text-sm">
              <span className="mb-1 block text-slate-600">显示名称</span>
              <input
                className={inputClass}
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="可选"
              />
            </label>
          )}
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">邮箱</span>
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
            <span className="mb-1 block text-slate-600">密码</span>
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
            {busy ? "提交中…" : mode === "login" ? "登录" : "注册并登录"}
          </Button>
        </form>
        <button
          type="button"
          className="mt-4 text-sm text-slate-600 underline hover:text-slate-900"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "没有账号？去注册" : "已有账号？去登录"}
        </button>
      </Card>
    </div>
  );
}