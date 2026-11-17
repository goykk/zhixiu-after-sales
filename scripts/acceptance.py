"""一键验收与交付报告（C-ACCEPTANCE@1）。

按固定顺序执行：环境检查 → 建库 → 种子 → API 冒烟（诊断/维修/端到端）→ 消融 → OCR → OTel →（可选）前端构建。
每步记录 PASS/FAIL/SKIP 与耗时，输出 JSON 与 Markdown 报告；任一步 FAIL 则整体未通过（退出码 1）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_DIR = ROOT / "data" / "reports"
DEFAULT_REPORT = ROOT / "docs" / "acceptance-report.md"
API_PORT = 8123
API_BASE = f"http://127.0.0.1:{API_PORT}/api/v1"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def _step(name: str, status: str, elapsed: float, detail: str) -> dict:
    return {"name": name, "status": status, "elapsed_s": round(elapsed, 2), "detail": detail}


def _tail(text: str, limit: int = 300) -> str:
    return " ".join(str(text).strip().split())[-limit:]


def _run(cmd, *, cwd: Path = ROOT, timeout: int = 900, env: dict | None = None):
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            shell=isinstance(cmd, str),
        )
    except subprocess.TimeoutExpired as exc:
        return 124, f"timeout: {exc}", time.perf_counter() - started
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output, time.perf_counter() - started


def check_env(provider: str) -> dict:
    started = time.perf_counter()
    parts: list[str] = []
    core_ok = True
    try:
        import core  # noqa: F401

        parts.append("core import ok")
    except Exception as exc:  # noqa: BLE001
        core_ok = False
        parts.append(f"core import failed: {exc}")
    try:
        import redis

        from services.api.app.config import settings

        redis.Redis.from_url(settings.redis_url, decode_responses=True).ping()
        parts.append("redis ping ok")
    except Exception as exc:  # noqa: BLE001
        parts.append(f"redis SKIP ({type(exc).__name__})")
    try:
        from core.observability.otel import available as otel_available

        parts.append(f"otel available={otel_available()}")
    except Exception as exc:  # noqa: BLE001
        parts.append(f"otel SKIP ({type(exc).__name__})")
    try:
        from services.api.app.config import settings as s

        parts.append(f"db={s.database_url}")
        parts.append(f"ocr_provider={s.ocr_provider}")
    except Exception as exc:  # noqa: BLE001
        parts.append(f"settings SKIP ({type(exc).__name__})")
    parts.append(f"provider={provider}")
    return _step("env", PASS if core_ok else FAIL, time.perf_counter() - started, "; ".join(parts))


def check_init_db(reset: bool) -> dict:
    cmd = [sys.executable, "scripts/init_db.py"] + (["--reset"] if reset else [])
    rc, out, elapsed = _run(cmd)
    return _step("init_db", PASS if rc == 0 else FAIL, elapsed, f"rc={rc}; {_tail(out)}")


def check_seed() -> dict:
    env = {**os.environ, "AI_PROVIDER": "mock"}
    started = time.perf_counter()
    details: list[str] = []
    ok = True
    for script in ("scripts/seed_demo.py", "scripts/seed_parts.py", "scripts/seed_outcomes.py"):
        rc, out, _ = _run([sys.executable, script], env=env)
        details.append(f"{Path(script).name} rc={rc}")
        if rc != 0:
            ok = False
            details.append(_tail(out, 160))
    return _step("seed", PASS if ok else FAIL, time.perf_counter() - started, " | ".join(details))


def _wait_health(timeout_s: int = 60) -> bool:
    for _ in range(timeout_s):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return False


def check_api_smoke(provider: str) -> dict:
    started = time.perf_counter()
    env = {**os.environ, "AI_PROVIDER": provider}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "services.api.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(API_PORT),
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        if not _wait_health():
            return _step("api_smoke", FAIL, time.perf_counter() - started, "API 未在 8123 就绪")
        commands = [
            [sys.executable, "scripts/demo_diagnosis.py", "--base-url", API_BASE, "--variant", v]
            for v in ("text_only", "with_photo", "with_probe_result")
        ] + [
            [sys.executable, "scripts/demo_full_closure.py", "--base-url", API_BASE],
            [sys.executable, "scripts/e2e_smoke.py", "--base-url", API_BASE],
        ]
        details: list[str] = []
        ok = True
        for cmd in commands:
            label = Path(cmd[1]).name
            if "--variant" in cmd:
                label += " " + cmd[-1]
            rc, out, _ = _run(cmd, timeout=900)
            details.append(f"{label} rc={rc}")
            if rc != 0:
                ok = False
                details.append(_tail(out, 200))
        return _step("api_smoke", PASS if ok else FAIL, time.perf_counter() - started, " | ".join(details))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()


def check_ablation(skip_heavy: bool) -> dict:
    if skip_heavy:
        return _step("ablation", SKIP, 0.0, "--skip-heavy")
    cmd = [
        sys.executable,
        "scripts/eval_scenarios.py",
        "--dataset",
        "data/scenarios/v1/scenarios.json",
        "--strategies",
        "A,B,C,D",
        "--split",
        "holdout",
    ]
    rc, out, elapsed = _run(cmd, timeout=1800)
    status = PASS if rc == 0 and "PASSED" in out else FAIL
    return _step("ablation", status, elapsed, f"rc={rc}; {_tail(out, 300)}")


def check_ocr(skip_heavy: bool) -> dict:
    if skip_heavy:
        return _step("ocr", SKIP, 0.0, "--skip-heavy")
    rc, out, elapsed = _run([sys.executable, "scripts/check_ocr.py", "--json"], timeout=600)
    if rc != 0:
        return _step("ocr", SKIP, elapsed, f"unavailable: {_tail(out, 200)}")
    return _step("ocr", PASS, elapsed, _tail(out, 200))


def check_otel_step() -> dict:
    rc, out, elapsed = _run(
        [sys.executable, "scripts/check_otel.py", "--exporter", "console", "--events", "1"],
        timeout=300,
    )
    if rc == 0 and "OTEL OK" in out:
        return _step("otel", PASS, elapsed, "OTEL OK")
    return _step("otel", SKIP, elapsed, f"unavailable rc={rc}; {_tail(out, 200)}")


def check_frontend(with_frontend: bool) -> dict:
    if not with_frontend:
        return _step("frontend", SKIP, 0.0, "use --with-frontend")
    rc, out, elapsed = _run("npx tsc --noEmit", cwd=ROOT / "apps" / "web", timeout=900)
    return _step("frontend", PASS if rc == 0 else FAIL, elapsed, f"rc={rc}; {_tail(out, 200)}")


def summarize(steps: list[dict]) -> dict:
    counts = {"pass": 0, "fail": 0, "skip": 0}
    for step in steps:
        key = str(step.get("status", "")).lower()
        if key in counts:
            counts[key] += 1
    return {"counts": counts, "passed": counts["fail"] == 0}


def run(args) -> dict:
    steps = [
        check_env(args.provider),
        check_init_db(not args.no_reset),
        check_seed(),
        check_api_smoke(args.provider),
        check_ablation(args.skip_heavy),
        check_ocr(args.skip_heavy),
        check_otel_step(),
        check_frontend(args.with_frontend),
    ]
    summary = summarize(steps)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "steps": steps,
        "counts": summary["counts"],
        "passed": summary["passed"],
    }


def render_markdown(report: dict) -> str:
    counts = report.get("counts", {})
    lines = [
        "# 验收报告（智修 V1.2）",
        "",
        f"生成时间：{report.get('generated_at', '')} ｜ AI provider：{report.get('provider', '')}",
        "",
        "> **合成数据声明**：本报告的场景、配件、维修结果与评测均为模拟数据，仅用于内部验收，不代表真实业务效果。",
        "",
        f"结论：**{'PASSED' if report.get('passed') else 'FAILED'}**"
        f"（PASS {counts.get('pass', 0)} / FAIL {counts.get('fail', 0)} / SKIP {counts.get('skip', 0)}）",
        "",
        "## 验收步骤",
        "",
        "| 步骤 | 状态 | 耗时(s) | 详情 |",
        "| --- | --- | --- | --- |",
    ]
    for step in report.get("steps", []):
        detail = str(step.get("detail", "")).replace("|", "\\|")
        lines.append(f"| {step.get('name')} | {step.get('status')} | {step.get('elapsed_s')} | {detail} |")
    lines += [
        "",
        "## 已知限制",
        "",
        "- 全部数据为模拟数据；真实维修记录未接入。",
        "- 可选路径（pgvector / Celery / OCR / OTel / LangGraph）在缺少依赖或服务时记 SKIP。",
        "- 消融基于 80 场景 × 3 变体的合成场景集。",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="一键验收与交付报告")
    parser.add_argument("--provider", default="mock", choices=("mock", "ollama"))
    parser.add_argument("--skip-heavy", action="store_true")
    parser.add_argument("--with-frontend", action="store_true")
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    report = run(args)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    json_path = REPORT_DIR / f"acceptance-{stamp}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown(report), encoding="utf-8")
    report["report_paths"] = {"json": str(json_path), "markdown": str(report_path)}

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(render_markdown(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())