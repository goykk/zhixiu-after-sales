"""轻量 JSONL 追踪器：事件按 run_id 落盘到 `settings.trace_dir`。"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from core.observability import otel
from core.observability.redact import redact

logger = logging.getLogger("zhixiu.trace")

_otel_fallback_lock = threading.Lock()
_otel_fallback_reported = False


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_trace_dir() -> Path:
    # 延迟导入：core 不静态依赖 services 层
    from services.api.app.config import settings

    return Path(settings.trace_dir)


class Tracer:
    """线程安全的事件追踪器；写盘失败不影响业务主流程。"""

    def __init__(self, run_id: str | None = None, *, trace_dir: str | Path | None = None) -> None:
        self.run_id = run_id or new_run_id()
        self._trace_dir = Path(trace_dir) if trace_dir is not None else None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._dir / f"{self.run_id}.jsonl"

    @property
    def _dir(self) -> Path:
        if self._trace_dir is None:
            self._trace_dir = _default_trace_dir()
        return self._trace_dir

    def emit(self, event: str, /, **fields: Any) -> dict[str, Any]:
        record = {
            "ts": _utcnow(),
            "run_id": self.run_id,
            "event": event,
            "fields": redact(fields),
        }
        self._append(record)
        self._mirror_to_otel(event, fields)
        return record

    @contextmanager
    def step(self, name: str, /, **fields: Any) -> Iterator[dict[str, Any]]:
        """记录 `{name}.start` / `{name}.end`，并带耗时与异常标记。"""
        started = datetime.now(timezone.utc)
        self.emit(f"{name}.start", **fields)
        payload: dict[str, Any] = {}
        # `name`/`kind` 是 span 的保留参数，业务字段中同名项不能传给 otel.span
        span_fields = {key: value for key, value in fields.items() if key not in ("name", "kind")}
        with otel.span(name, **span_fields):
            try:
                yield payload
            except Exception as exc:
                self.emit(
                    f"{name}.error",
                    duration_ms=_elapsed_ms(started),
                    error=type(exc).__name__,
                    **fields,
                )
                raise
            self.emit(
                f"{name}.end",
                duration_ms=_elapsed_ms(started),
                **fields,
                **(payload if isinstance(payload, dict) else {}),
            )

    def _mirror_to_otel(self, event: str, fields: dict[str, Any]) -> None:
        """把 JSONL 事件镜像到 OTel；OTel 故障只记录一次 `otel_fallback`。"""
        global _otel_fallback_reported

        try:
            otel.record_event(event, event, fields)
        except Exception as exc:  # noqa: BLE001 - OTel 故障不得影响业务
            with _otel_fallback_lock:
                first = not _otel_fallback_reported
                _otel_fallback_reported = True
            if first:
                self._append(
                    {
                        "ts": _utcnow(),
                        "run_id": self.run_id,
                        "event": "otel_fallback",
                        "fields": redact(
                            {
                                "original_event": event,
                                "error": type(exc).__name__,
                                "message": str(exc)[:200],
                            }
                        ),
                    }
                )
                logger.warning("otel mirror failed for %s", event, exc_info=True)

    def _append(self, record: dict[str, Any]) -> None:
        try:
            with self._lock:
                self._dir.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            logger.warning("trace write failed for run %s", self.run_id, exc_info=True)


def _elapsed_ms(started: datetime) -> int:
    return int((datetime.now(timezone.utc) - started).total_seconds() * 1000)


_TRACERS: dict[str, Tracer] = {}
_TRACERS_LOCK = threading.Lock()


def get_tracer(run_id: str | None = None) -> Tracer:
    """同一 run_id 复用实例；未指定时返回新的一次性追踪器（不缓存，避免泄漏）。"""
    if run_id is None:
        return Tracer()
    with _TRACERS_LOCK:
        tracer = _TRACERS.get(run_id)
        if tracer is None:
            tracer = Tracer(run_id)
            _TRACERS[run_id] = tracer
        return tracer