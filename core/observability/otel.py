"""OpenTelemetry 桥接：默认关闭，失败即回退 JSONL，不影响业务请求。

SDK 为可选依赖，因此 opentelemetry 相关导入全部延迟到函数内部。
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from core.observability.redact import redact

logger = logging.getLogger("zhixiu.otel")

_SCOPE_NAME = "zhixiu.observability"

_KINDS = {
    "internal": "INTERNAL",
    "server": "SERVER",
    "client": "CLIENT",
    "producer": "PRODUCER",
    "consumer": "CONSUMER",
}

_initialized = False
_enabled = False
_provider: Any = None
_lock = threading.Lock()


def _settings() -> Any:
    # 延迟导入：core 不静态依赖 services 层
    try:
        from services.api.app.config import settings

        return settings
    except Exception:  # noqa: BLE001 - 配置不可用时不阻断业务
        return None


def available() -> bool:
    """`opentelemetry.sdk` 是否可导入。"""
    try:
        import opentelemetry.sdk  # noqa: F401
        from opentelemetry.sdk.trace import TracerProvider  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 - 任何导入失败都视为不可用
        return False


def parse_headers(raw: str) -> dict[str, str]:
    """解析 `OTEL_HEADERS`：逗号分隔的 `k=v`，忽略空项与无 `=` 项。"""
    headers: dict[str, str] = {}
    for item in str(raw or "").split(","):
        key, sep, value = item.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        headers[key] = value.strip()
    return headers


def _build_exporter(exporter: str, endpoint: str, headers: str) -> Any:
    if exporter == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=endpoint, headers=parse_headers(headers))


def setup_tracing(
    *,
    service_name: str | None = None,
    exporter: str | None = None,
    endpoint: str | None = None,
) -> bool:
    """按配置初始化 TracerProvider；幂等，任何失败都返回 False 且不抛异常。"""
    global _initialized, _enabled, _provider

    if _initialized:
        return _enabled

    settings = _settings()
    if settings is None or not getattr(settings, "otel_enabled", False):
        return False
    if not available():
        logger.info("opentelemetry sdk not installed; JSONL tracing only")
        return False

    chosen = str(exporter or getattr(settings, "otel_exporter", "none") or "none").strip().lower()
    if chosen in ("", "none"):
        return False
    if chosen not in ("console", "otlp"):
        logger.warning("unknown otel exporter %r; JSONL tracing only", chosen)
        return False

    service = service_name or str(getattr(settings, "otel_service_name", "zhixiu-v12"))
    export_endpoint = endpoint or str(getattr(settings, "otel_endpoint", "http://localhost:4318"))
    headers = str(getattr(settings, "otel_headers", ""))
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        sampler = ParentBased(TraceIdRatioBased(float(getattr(settings, "otel_sample_ratio", 1.0))))
        provider = TracerProvider(
            resource=Resource.create({"service.name": service}),
            sampler=sampler,
        )
        span_exporter = _build_exporter(chosen, export_endpoint, headers)
        if chosen == "console":
            provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        else:
            provider.add_span_processor(BatchSpanProcessor(span_exporter))
    except Exception:  # noqa: BLE001 - 导出器不可用时回退 JSONL
        logger.warning("otel exporter init failed; JSONL tracing only", exc_info=True)
        return False

    try:
        from opentelemetry import trace

        trace.set_tracer_provider(provider)
    except Exception:  # noqa: BLE001 - 全局注册失败时仍可用注入的 provider
        logger.debug("otel global provider registration failed", exc_info=True)

    with _lock:
        if _initialized:
            return _enabled
        _provider = provider
        _enabled = True
        _initialized = True
    logger.info("otel tracing enabled exporter=%s service=%s", chosen, service)
    return True


def _get_tracer() -> Any:
    provider = _provider
    if provider is not None:
        try:
            return provider.get_tracer(_SCOPE_NAME)
        except Exception:  # noqa: BLE001 - 注入的 provider 不可用时退回全局
            logger.debug("otel provider get_tracer failed", exc_info=True)
    from opentelemetry import trace

    return trace.get_tracer(_SCOPE_NAME)


def _span_kind(kind: str) -> Any:
    from opentelemetry.trace import SpanKind

    return getattr(SpanKind, _KINDS.get(str(kind or "").lower(), "INTERNAL"))


def _attribute_value(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)) and all(
        isinstance(item, (bool, int, float, str)) for item in value
    ):
        return list(value)
    return str(value)


def _otel_attrs(attrs: dict[str, Any] | None) -> dict[str, Any]:
    """脱敏后转成 OTel 可接受的属性值；None 值被丢弃。"""
    cleaned: dict[str, Any] = {}
    for key, value in (redact(attrs) or {}).items():
        if value is None:
            continue
        cleaned[str(key)] = _attribute_value(value)
    return cleaned


@contextmanager
def span(name: str, kind: str = "internal", **attrs: Any) -> Iterator[Any]:
    """命名 span 上下文；未启用时为空上下文。异常记录后向上抛出。"""
    if not _enabled:
        yield None
        return
    try:
        context_manager = _get_tracer().start_as_current_span(
            name,
            kind=_span_kind(kind),
            attributes=_otel_attrs(attrs),
        )
    except Exception:  # noqa: BLE001 - OTel 内部故障不得影响业务
        logger.warning("otel span creation failed for %s", name, exc_info=True)
        yield None
        return
    with context_manager:
        yield context_manager


def record_event(kind: str, name: str, attrs: dict[str, Any] | None = None) -> None:
    """把事件镜像为活动 span 的 event；无活动 span 时用短 span 承载。"""
    if not _enabled:
        return
    payload = {**_otel_attrs(attrs or {}), "kind": kind}
    from opentelemetry import trace

    active = trace.get_current_span()
    if active is not None and active.get_span_context().is_valid:
        active.add_event(name, payload)
        return

    short = _get_tracer().start_span(f"otel.{kind}")
    try:
        for key, value in payload.items():
            short.set_attribute(key, value)
        short.add_event(name, payload)
    finally:
        short.end()


def _clear_global_provider() -> None:
    """best-effort 清空全局 provider（OTel 无公开重置接口，仅测试/关闭时使用）。"""
    try:
        from opentelemetry import trace

        if getattr(trace, "_TRACER_PROVIDER", None) is not None:
            trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
            trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - 私有属性变化时忽略
        pass


def shutdown() -> None:
    """flush 并关闭 provider；幂等。"""
    global _initialized, _enabled, _provider

    provider = _provider
    _provider = None
    _enabled = False
    _initialized = False
    _clear_global_provider()
    if provider is None:
        return
    try:
        provider.shutdown()
    except Exception:  # noqa: BLE001 - 关闭失败不应影响进程退出
        logger.warning("otel provider shutdown failed", exc_info=True)


def reset_for_tests() -> None:
    """清空模块状态，仅供测试使用。"""
    global _initialized, _enabled, _provider

    _initialized = False
    _enabled = False
    _provider = None
    _clear_global_provider()