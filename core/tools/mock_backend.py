"""模拟外部工单服务：失败注入与同幂等键返回同一 external_id。"""

from __future__ import annotations

import uuid
from typing import Any

from core.tools.gateway import ToolError


class MockWorkOrderBackend:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = max(0, int(fail_times))
        self._attempts = 0
        self._by_key: dict[str, dict[str, Any]] = {}
        self._by_external: dict[str, dict[str, Any]] = {}

    def create(
        self,
        *,
        idempotency_key: str,
        case_id: str,
        assignee: str | None = None,
    ) -> dict[str, Any]:
        self._attempts += 1
        if self._attempts <= self.fail_times:
            raise ToolError(
                "UPSTREAM_UNAVAILABLE", "mock work order backend is unavailable"
            )
        key = str(idempotency_key or "").strip()
        if not key:
            raise ToolError("IDEMPOTENCY_KEY_REQUIRED", "idempotency_key is required")
        existing = self._by_key.get(key)
        if existing is not None:
            return dict(existing)
        record: dict[str, Any] = {
            "external_id": f"EXT-{uuid.uuid4().hex[:12].upper()}",
            "case_id": case_id,
            "assignee": assignee,
            "status": "created",
            "resolution": None,
        }
        self._by_key[key] = record
        self._by_external[record["external_id"]] = record
        return dict(record)

    def update(
        self,
        external_id: str,
        *,
        status: str | None = None,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        record = self._record(external_id)
        if status is not None:
            record["status"] = status
        if resolution is not None:
            record["resolution"] = resolution
        return dict(record)

    def get(self, external_id: str) -> dict[str, Any]:
        return dict(self._record(external_id))

    def _record(self, external_id: str) -> dict[str, Any]:
        record = self._by_external.get(str(external_id or "").strip())
        if record is None:
            raise ToolError("WORK_ORDER_NOT_FOUND", "mock work order not found")
        return record


_BACKEND = MockWorkOrderBackend()


def get_mock_backend() -> MockWorkOrderBackend:
    return _BACKEND


def set_mock_backend(backend: MockWorkOrderBackend) -> None:
    """替换进程级 mock 后端（测试注入失败场景）。"""
    global _BACKEND
    _BACKEND = backend