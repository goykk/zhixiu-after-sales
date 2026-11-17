"""任务状态存储：默认 Redis，连接不可用时回退进程内字典并追踪。"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from functools import lru_cache

import redis

from core.observability.tracer import get_tracer
from services.api.app.config import settings

TASK_KEY_PREFIX = "zhixiu:task:"

STATUS_PENDING = "PENDING"
STATUS_STARTED = "STARTED"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILURE = "FAILURE"

_FALLBACK_TASKS: dict[str, "TaskInfo"] = {}
_FALLBACK_LOCK = threading.Lock()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskInfo:
    task_id: str
    status: str = STATUS_PENDING
    backend: str = field(default_factory=lambda: settings.task_backend)
    owner_id: str | None = None
    result: dict | None = None
    error: str | None = None
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)


def new_task_id() -> str:
    return f"task-{uuid.uuid4().hex[:12]}"


class TaskStore:
    """Redis JSON 记录（TTL 由 `settings.task_ttl_seconds` 决定）；失败即降级为模块级字典。"""

    def __init__(self, *, url: str | None = None, ttl_seconds: int | None = None) -> None:
        self._url = url or settings.redis_url
        self._ttl_seconds = int(ttl_seconds if ttl_seconds is not None else settings.task_ttl_seconds)
        self._fallback_announced = False
        self._client: redis.Redis | None = self._connect()

    def put(self, info: TaskInfo) -> None:
        client = self._client
        if client is not None:
            try:
                client.set(self._key(info.task_id), _encode(info), ex=self._ttl_seconds)
                return
            except Exception as exc:  # noqa: BLE001 - 任何 Redis 故障都不得中断任务流程
                self._degrade(exc)
        with _FALLBACK_LOCK:
            _FALLBACK_TASKS[info.task_id] = info

    def get(self, task_id: str) -> TaskInfo | None:
        client = self._client
        if client is not None:
            try:
                raw = client.get(self._key(task_id))
            except Exception as exc:  # noqa: BLE001 - 同上
                self._degrade(exc)
            else:
                return _decode(raw) if raw else None
        with _FALLBACK_LOCK:
            return _FALLBACK_TASKS.get(task_id)

    def update(
        self,
        task_id: str,
        *,
        status: str,
        result: dict | None = None,
        error: str | None = None,
    ) -> TaskInfo | None:
        info = self.get(task_id)
        if info is None:
            return None
        updated = replace(info, status=status, result=result, error=error, updated_at=_utcnow())
        self.put(updated)
        return updated

    def list(self, *, limit: int = 20, owner_id: str | None = None) -> list[TaskInfo]:
        """按创建时间倒序列出任务；owner_id 为空表示不过滤。"""
        items: list[TaskInfo] = []
        client = self._client
        if client is not None:
            try:
                keys = list(client.scan_iter(match=f"{TASK_KEY_PREFIX}*"))
            except Exception as exc:  # noqa: BLE001
                self._degrade(exc)
                keys = []
            for key in keys:
                try:
                    raw = client.get(key)
                except Exception as exc:  # noqa: BLE001
                    self._degrade(exc)
                    break
                info = _decode(raw) if raw else None
                if info is not None:
                    items.append(info)
        if not items:
            with _FALLBACK_LOCK:
                items = list(_FALLBACK_TASKS.values())
        if owner_id is not None:
            items = [item for item in items if item.owner_id == owner_id]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[: max(0, int(limit))]

    def _connect(self) -> "redis.Redis | None":
        try:
            client = redis.Redis.from_url(self._url, decode_responses=True)
            client.ping()
        except Exception as exc:  # noqa: BLE001 - 连接失败是预期内的部署差异
            self._announce(exc)
            return None
        return client

    def _degrade(self, exc: Exception) -> None:
        self._client = None
        self._announce(exc)

    def _announce(self, exc: Exception) -> None:
        if self._fallback_announced:
            return
        self._fallback_announced = True
        get_tracer().emit("task_store_fallback", reason=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _key(task_id: str) -> str:
        return f"{TASK_KEY_PREFIX}{task_id}"


@lru_cache(maxsize=1)
def get_task_store() -> TaskStore:
    return TaskStore()


def _encode(info: TaskInfo) -> str:
    return json.dumps(asdict(info), ensure_ascii=False)


def _decode(raw: str | bytes) -> TaskInfo | None:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return TaskInfo(**payload)
    except TypeError:
        return None