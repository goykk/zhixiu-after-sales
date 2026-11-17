"""校验 OpenTelemetry 接入：临时启用 OTel，生成 3 个 span 与事件并检查导出结果。"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 覆盖模型、检索、工具三条主链路，便于肉眼确认 span 名称与属性
PROBES: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("model.call", "client", {"model": "check-otel", "operation": "generate"}),
    ("retrieval", "internal", {"query": "check-otel", "top_k": 1}),
    ("tool.call", "client", {"tool": "check_otel", "status": "ok"}),
)


class _ExportErrorLog(logging.Handler):
    """收集 OTel 导出器的错误日志，用于判定导出是否失败。"""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"需要正整数：{raw}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"需要正整数：{raw}")
    return value


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验 OTel 导出链路是否可用")
    parser.add_argument(
        "--exporter",
        choices=("console", "otlp"),
        default="console",
        help="导出器类型（默认 console）",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="OTLP 导出地址，默认取 settings.otel_endpoint",
    )
    parser.add_argument(
        "--events",
        type=_positive_int,
        default=1,
        help="每个 span 写入的事件数（默认 1）",
    )
    parser.add_argument(
        "--headers",
        default=None,
        help='OTLP 请求头，如 "authorization=Basic <base64(public:secret)>"（Langfuse 用）',
    )
    return parser.parse_args(argv)


def _force_enabled(settings: Any, exporter: str, endpoint: str, headers: str = "") -> None:
    """临时启用 OTel：先写环境变量，再覆盖已构造的 settings 实例。"""
    os.environ["OTEL_ENABLED"] = "true"
    os.environ["OTEL_EXPORTER"] = exporter
    os.environ["OTEL_ENDPOINT"] = endpoint
    os.environ["OTEL_HEADERS"] = headers
    settings.otel_enabled = True
    settings.otel_exporter = exporter
    settings.otel_endpoint = endpoint
    settings.otel_headers = headers
    if settings.otel_enabled is not True:
        raise RuntimeError("settings 为只读，无法临时启用 OTel")


def _emit_probes(otel: Any, per_span: int) -> int:
    written = 0
    for name, kind, attrs in PROBES:
        with otel.span(name, kind=kind, **attrs):
            for seq in range(per_span):
                otel.record_event("check", f"{name}.event", {"seq": seq})
                written += 1
    return written


def _print_status(exporter: str, available: bool, events: int) -> None:
    print(f"provider={exporter} available={available} events={events}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        from core.observability import otel
        from services.api.app.config import settings
    except Exception as exc:  # 模块缺失或依赖未装都不能导致 traceback
        _print_status(args.exporter, False, 0)
        print(f"OTel 模块不可用：{exc}", file=sys.stderr)
        return 1

    endpoint = args.endpoint or settings.otel_endpoint
    headers = args.headers if args.headers is not None else str(getattr(settings, "otel_headers", ""))
    try:
        _force_enabled(settings, args.exporter, endpoint, headers)
    except Exception as exc:
        _print_status(args.exporter, False, 0)
        print(f"无法启用 OTel 配置：{exc}", file=sys.stderr)
        return 1

    catcher = _ExportErrorLog()
    otel_logger = logging.getLogger("opentelemetry")
    otel_logger.addHandler(catcher)

    available = bool(otel.available())
    events_written = 0
    failure: str | None = None
    try:
        try:
            initialized = bool(otel.setup_tracing(exporter=args.exporter, endpoint=endpoint))
        except Exception as exc:
            initialized = False
            failure = f"初始化失败：{exc}"
        if failure is None and not initialized:
            failure = (
                "初始化未生效：请确认已安装 opentelemetry-sdk"
                "（otlp 导出还需 opentelemetry-exporter-otlp）"
            )
        if failure is None:
            try:
                events_written = _emit_probes(otel, args.events)
            except Exception as exc:
                failure = f"生成 span 失败：{exc}"
    finally:
        try:
            otel.shutdown()
        except Exception as exc:
            failure = failure or f"导出失败：{exc}"
        otel_logger.removeHandler(catcher)

    export_errors = [msg for msg in catcher.messages if "export" in msg.lower()]
    if failure is None and export_errors:
        failure = f"导出失败：{export_errors[0]}"

    _print_status(args.exporter, available, events_written)
    if failure is not None:
        print(failure, file=sys.stderr)
        return 1
    print(f"headers={len(otel.parse_headers(headers))}")
    print("OTEL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())