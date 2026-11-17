"""一键验收脚本测试（C-TEST-ACCEPTANCE@1）：仅测渲染与汇总，不真实起服务。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("acceptance", _ROOT / "scripts" / "acceptance.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summarize_counts_and_passed():
    mod = _load()
    steps = [
        {"name": "a", "status": "PASS", "elapsed_s": 0.1, "detail": ""},
        {"name": "b", "status": "SKIP", "elapsed_s": 0.0, "detail": ""},
    ]
    result = mod.summarize(steps)
    assert result["counts"] == {"pass": 1, "fail": 0, "skip": 1}
    assert result["passed"] is True

    with_fail = steps + [{"name": "c", "status": "FAIL", "elapsed_s": 0.0, "detail": ""}]
    assert mod.summarize(with_fail)["passed"] is False


def test_render_markdown_contains_required_sections():
    mod = _load()
    report = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "provider": "mock",
        "steps": [{"name": "env", "status": "PASS", "elapsed_s": 0.0, "detail": "ok"}],
        "counts": {"pass": 1, "fail": 0, "skip": 0},
        "passed": True,
    }
    text = mod.render_markdown(report)
    assert "合成数据声明" in text
    assert "| 步骤 | 状态 | 耗时(s) | 详情 |" in text
    assert "PASSED" in text
    assert "已知限制" in text


def test_run_with_stubbed_steps(monkeypatch):
    mod = _load()
    stub = lambda *a, **k: {"name": "stub", "status": "PASS", "elapsed_s": 0.0, "detail": ""}
    for name in (
        "check_env",
        "check_init_db",
        "check_seed",
        "check_api_smoke",
        "check_ablation",
        "check_ocr",
        "check_otel_step",
        "check_frontend",
    ):
        monkeypatch.setattr(mod, name, stub)

    class Args:
        provider = "mock"
        skip_heavy = True
        with_frontend = False
        no_reset = True

    report = mod.run(Args())
    assert report["passed"] is True
    assert report["counts"]["pass"] == 8