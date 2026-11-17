"""OpenTelemetry 接入测试（C-TEST-OTEL@1）。

覆盖默认关闭、InMemory 导出与脱敏、headers 解析、SDK 缺失回退、
Tracer 事件镜像与 otel_fallback、检查脚本退出码。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from core.observability import otel
from core.observability.tracer import Tracer
from services.api.app.config import settings

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _otel_reset() -> Any:
    otel.reset_for_tests()
    yield
    otel.shutdown()
    otel.reset_for_tests()


def _patch_record_event(monkeypatch: pytest.MonkeyPatch, fake: Any) -> None:
    """同时覆盖模块属性与可能的直接导入引用，确保 Tracer 侧的调用被拦截。"""
    import core.observability.tracer as tracer_module

    monkeypatch.setattr(otel, "record_event", fake)
    if getattr(tracer_module, "record_event", None) is not None:
        monkeypatch.setattr(tracer_module, "record_event", fake)


def _enable_inmemory(monkeypatch: pytest.MonkeyPatch) -> Any:
    """启用 OTel 并给全局 provider 挂 InMemory 导出器；SDK 未安装时跳过。"""
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry import trace as trace_api
    from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    monkeypatch.setattr(settings, "otel_enabled", True)
    monkeypatch.setattr(settings, "otel_exporter", "console")
    monkeypatch.setattr(settings, "otel_sample_ratio", 1.0)
    otel.reset_for_tests()
    assert otel.setup_tracing() is True

    provider = trace_api.get_tracer_provider()
    assert isinstance(provider, SdkTracerProvider)
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    return memory


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "otel_enabled", False)

    assert otel.setup_tracing() is False

    with otel.span("unit.disabled", token="s3cr3t") as span:
        assert span is None
    otel.record_event("model", "model.call", {"token": "s3cr3t"})

    tracer = Tracer(trace_dir=tmp_path)
    record = tracer.emit("model.call", model="gemma")
    lines = (tmp_path / f"{tracer.run_id}.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "model.call"
    assert payload["fields"]["model"] == "gemma"
    assert record["event"] == "model.call"


def test_parse_headers_ignores_invalid_entries() -> None:
    assert otel.parse_headers("a=1, b=2, bad, =x") == {"a": "1", "b": "2"}
    assert otel.parse_headers("") == {}


def test_setup_tracing_without_sdk_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "otel_enabled", True)
    monkeypatch.setattr(otel, "available", lambda: False)

    assert otel.setup_tracing() is False


def test_span_and_event_exported_with_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = _enable_inmemory(monkeypatch)

    with otel.span("unit.span", token="s3cr3t", email="user@example.com", user_id="u-1") as span:
        assert span is not None
        otel.record_event(
            "model", "model.call", {"token": "s3cr3t", "email": "user@example.com", "model": "gemma"}
        )

    spans = [s for s in memory.get_finished_spans() if s.name == "unit.span"]
    assert len(spans) == 1
    exported = spans[0]
    assert exported.attributes["token"] == "***"
    assert exported.attributes["email"] == "***"
    assert exported.attributes["user_id"] == "u-1"

    event = next(e for e in exported.events if e.name == "model.call")
    assert event.attributes["kind"] == "model"
    assert event.attributes["token"] == "***"
    assert event.attributes["email"] == "***"
    assert event.attributes["model"] == "gemma"


def test_record_event_without_active_span_creates_short_span(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = _enable_inmemory(monkeypatch)

    otel.record_event("retrieval", "retrieval.search", {"token": "s3cr3t"})

    spans = [s for s in memory.get_finished_spans() if s.name == "otel.retrieval"]
    assert len(spans) == 1
    assert spans[0].attributes["token"] == "***"


def test_tracer_emit_mirrors_event_to_otel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "otel_enabled", True)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    _patch_record_event(monkeypatch, lambda *args, **kwargs: calls.append((args, kwargs)))

    tracer = Tracer(trace_dir=tmp_path)
    tracer.emit("model.call", token="s3cr3t", model="gemma")

    assert len(calls) == 1
    args, _ = calls[0]
    assert args[0] == "model.call"


def test_tracer_emit_survives_otel_failure_and_logs_fallback_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import core.observability.tracer as tracer_module

    monkeypatch.setattr(settings, "otel_enabled", True)
    for name, value in vars(tracer_module).items():
        if name.isupper() or (name.startswith("_") and "otel" in name.lower()):
            if isinstance(value, bool):
                monkeypatch.setattr(tracer_module, name, False)

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("otel exporter down")

    _patch_record_event(monkeypatch, _boom)

    tracer = Tracer(trace_dir=tmp_path)
    assert tracer.emit("model.call", token="s3cr3t")["event"] == "model.call"
    assert tracer.emit("retrieval.search", query="fan")["event"] == "retrieval.search"

    events = [
        json.loads(line)["event"]
        for line in (tmp_path / f"{tracer.run_id}.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events.count("otel_fallback") == 1
    assert events.count("model.call") == 1
    assert events.count("retrieval.search") == 1


def test_check_script_console_exit_code_zero() -> None:
    pytest.importorskip("opentelemetry.sdk.trace")
    script = _ROOT / "scripts" / "check_otel.py"
    assert script.exists(), "scripts/check_otel.py 缺失"

    env = dict(os.environ)
    env.pop("OTEL_ENABLED", None)
    env.pop("OTEL_EXPORTER", None)
    result = subprocess.run(
        [sys.executable, str(script), "--exporter", "console", "--events", "1"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "OTEL OK" in result.stdout

def test_otlp_exporter_receives_parsed_headers(monkeypatch) -> None:
    pytest.importorskip("opentelemetry.sdk.trace")
    http_mod = pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    captured: dict[str, Any] = {}

    class FakeExporter:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def export(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
            return None

        def shutdown(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
            return None

    monkeypatch.setattr(http_mod, "OTLPSpanExporter", FakeExporter)
    monkeypatch.setattr(settings, "otel_enabled", True, raising=False)
    monkeypatch.setattr(
        settings, "otel_headers", "authorization=Basic abc123, x-tenant=demo", raising=False
    )
    try:
        assert otel.setup_tracing(exporter="otlp", endpoint="http://127.0.0.1:4318") is True
        assert captured.get("headers") == {"authorization": "Basic abc123", "x-tenant": "demo"}
        assert captured.get("endpoint") == "http://127.0.0.1:4318"
    finally:
        otel.shutdown()
        otel.reset_for_tests()


def test_check_script_reports_headers_count() -> None:
    pytest.importorskip("opentelemetry.sdk.trace")
    script = _ROOT / "scripts" / "check_otel.py"
    env = dict(os.environ)
    env.pop("OTEL_ENABLED", None)
    result = subprocess.run(
        [sys.executable, str(script), "--exporter", "console", "--events", "1", "--headers", "a=1,b=2"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "headers=2" in result.stdout
    assert "OTEL OK" in result.stdout