"""异步任务测试（C-TEST-ASYNC@1）。"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
import redis
from kombu.exceptions import OperationalError

from core.observability.tracer import Tracer
from core.tasks.dispatch import dispatch, get_task, run_sync
from core.tasks.store import TaskInfo, TaskStore
from services.api.app.config import settings

API = "/api/v1"
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:6399/1"

_TASK_FIELDS = {
    "task_id",
    "status",
    "backend",
    "result",
    "error",
    "created_at",
    "updated_at",
}
_INDEX_FIELDS = {"manual_id", "chunk_count", "status", "error"}


def _events(events: list[dict], name: str) -> list[dict]:
    return [event for event in events if event["event"] == name]


def _new_task_id() -> str:
    return f"task-{uuid4().hex[:12]}"


@pytest.fixture
def traced_events(monkeypatch):
    """拦截追踪事件：既便于断言，也避免测试写盘到 data/traces。"""
    events: list[dict] = []

    def _emit(self, event, /, **fields):
        record = {"event": event, "fields": fields}
        events.append(record)
        return record

    monkeypatch.setattr(Tracer, "emit", _emit)
    return events


@pytest.fixture
def offline_store(monkeypatch, traced_events) -> TaskStore:
    """Redis 不可达的 TaskStore，并让 dispatch/查询端点复用它，测试不依赖外部服务。"""

    def _unavailable(*args, **kwargs):
        raise redis.exceptions.ConnectionError("redis unavailable")

    monkeypatch.setattr(redis.Redis, "from_url", _unavailable)
    store = TaskStore(url=UNREACHABLE_REDIS_URL)
    monkeypatch.setattr(
        importlib.import_module("core.tasks.dispatch"), "get_task_store", lambda: store
    )
    return store


def _put_task(
    store: TaskStore,
    *,
    owner_id: str,
    status: str = "SUCCESS",
    result: dict | None = None,
    error: str | None = None,
) -> TaskInfo:
    info = TaskInfo(
        task_id=_new_task_id(),
        status=status,
        backend="sync",
        owner_id=owner_id,
        result=result,
        error=error,
    )
    store.put(info)
    return info


class _FakeCelerySend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name, kwargs=None, **options):
        self.calls.append((name, dict(kwargs or {})))
        return SimpleNamespace(id="celery-result-1")


@pytest.fixture
def celery_send(monkeypatch) -> _FakeCelerySend:
    from services.worker.celery_app import celery_app

    fake = _FakeCelerySend()
    monkeypatch.setattr(celery_app, "send_task", fake)
    return fake


# ---------------------------------------------------------------- dispatch


def test_dispatch_sync_runs_handler(traced_events, offline_store, monkeypatch):
    monkeypatch.setattr(settings, "task_backend", "sync")

    info = dispatch(
        "zhixiu.index_manual",
        {"manual_id": "m-1"},
        owner_id="u-1",
        sync_handler=lambda: {
            "manual_id": "m-1",
            "chunk_count": 3,
            "status": "indexed",
            "error": None,
        },
    )

    assert info.status == "SUCCESS"
    assert info.backend == "sync"
    assert info.owner_id == "u-1"
    assert info.result == {
        "manual_id": "m-1",
        "chunk_count": 3,
        "status": "indexed",
        "error": None,
    }
    stored = get_task(info.task_id)
    assert stored is not None
    assert stored.status == "SUCCESS"
    assert _events(traced_events, "task_backend_fallback") == []


def test_dispatch_sync_failure_records_failure_and_reraises(
    traced_events, offline_store, monkeypatch
):
    monkeypatch.setattr(settings, "task_backend", "sync")
    task_id = _new_task_id()
    monkeypatch.setattr(
        importlib.import_module("core.tasks.dispatch"), "new_task_id", lambda: task_id
    )

    def _boom() -> dict:
        raise RuntimeError("index failed")

    with pytest.raises(RuntimeError, match="index failed"):
        dispatch(
            "zhixiu.index_manual",
            {"manual_id": "m-1"},
            owner_id="u-1",
            sync_handler=_boom,
        )

    stored = get_task(task_id)
    assert stored is not None
    assert stored.status == "FAILURE"
    assert "index failed" in (stored.error or "")


def test_dispatch_sync_requires_handler(traced_events, offline_store, monkeypatch):
    monkeypatch.setattr(settings, "task_backend", "sync")

    with pytest.raises(ValueError):
        dispatch("zhixiu.index_manual", {"manual_id": "m-1"}, owner_id="u-1")


def test_dispatch_celery_returns_pending(
    traced_events, offline_store, celery_send, monkeypatch
):
    monkeypatch.setattr(settings, "task_backend", "celery")

    info = dispatch(
        "zhixiu.index_manual",
        {"manual_id": "m-1"},
        owner_id="u-1",
        sync_handler=lambda: {"chunk_count": 99},
    )

    assert info.status == "PENDING"
    assert info.backend == "celery"
    stored = get_task(info.task_id)
    assert stored is not None
    assert stored.status == "PENDING"
    assert stored.owner_id == "u-1"
    assert celery_send.calls == [
        ("zhixiu.index_manual", {"manual_id": "m-1", "task_id": info.task_id})
    ]
    assert _events(traced_events, "task_backend_fallback") == []


def test_dispatch_celery_falls_back_when_broker_unavailable(
    traced_events, offline_store, monkeypatch
):
    from services.worker.celery_app import celery_app

    monkeypatch.setattr(settings, "task_backend", "celery")

    def _send_task(*args, **kwargs):
        raise OperationalError("broker unreachable")

    monkeypatch.setattr(celery_app, "send_task", _send_task)

    info = dispatch(
        "zhixiu.index_manual",
        {"manual_id": "m-1"},
        owner_id="u-1",
        sync_handler=lambda: {"manual_id": "m-1", "chunk_count": 2},
    )

    assert info.status == "SUCCESS"
    assert info.result == {"manual_id": "m-1", "chunk_count": 2}
    fallback = _events(traced_events, "task_backend_fallback")
    assert len(fallback) == 1
    assert "broker unreachable" in str(fallback[0]["fields"].get("reason"))


def test_run_sync_marks_failure_before_reraising(offline_store):
    info = TaskInfo(task_id=_new_task_id(), status="PENDING", backend="sync", owner_id="u-1")
    offline_store.put(info)

    def _boom() -> dict:
        raise ValueError("handler exploded")

    with pytest.raises(ValueError, match="handler exploded"):
        run_sync(info, _boom)

    stored = get_task(info.task_id)
    assert stored is not None
    assert stored.status == "FAILURE"
    assert "handler exploded" in (stored.error or "")


# ------------------------------------------------------------ 任务查询权限


def test_get_task_owner_can_read(client, auth_headers, seed_base, offline_store):
    info = _put_task(
        offline_store,
        owner_id=seed_base["users"]["technician"].id,
        result={"chunk_count": 4},
    )

    response = client.get(
        f"{API}/tasks/{info.task_id}", headers=auth_headers("technician@demo.local")
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == _TASK_FIELDS
    assert body["task_id"] == info.task_id
    assert body["status"] == "SUCCESS"
    assert body["backend"] == "sync"
    assert body["result"] == {"chunk_count": 4}


def test_get_task_staff_can_read_others_task(client, auth_headers, seed_base, offline_store):
    info = _put_task(offline_store, owner_id=seed_base["users"]["user"].id)

    response = client.get(
        f"{API}/tasks/{info.task_id}", headers=auth_headers("agent@demo.local")
    )

    assert response.status_code == 200, response.text
    assert response.json()["task_id"] == info.task_id


def test_get_task_other_user_is_forbidden(client, auth_headers, seed_base, offline_store):
    info = _put_task(offline_store, owner_id=seed_base["users"]["technician"].id)

    response = client.get(
        f"{API}/tasks/{info.task_id}", headers=auth_headers("user@demo.local")
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_get_task_missing_returns_404(client, auth_headers, seed_base, offline_store):
    response = client.get(
        f"{API}/tasks/task-doesnotexist", headers=auth_headers("agent@demo.local")
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


# --------------------------------------------------------- 端点 async 行为


def test_index_async_true_stays_sync_on_sync_backend(
    client, auth_headers, seed_base, traced_events, offline_store, monkeypatch
):
    monkeypatch.setattr(settings, "task_backend", "sync")

    response = client.post(
        f"{API}/manuals/{seed_base['manual'].id}/index?async=true",
        headers=auth_headers("agent@demo.local"),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == _INDEX_FIELDS
    assert body["manual_id"] == seed_base["manual"].id
    assert body["status"] == "indexed"
    ignored = _events(traced_events, "task_backend_ignored")
    assert len(ignored) == 1
    assert ignored[0]["fields"].get("endpoint") == "manuals.index"


def test_index_async_true_returns_202_on_celery_backend(
    client, auth_headers, seed_base, traced_events, offline_store, celery_send, monkeypatch
):
    monkeypatch.setattr(settings, "task_backend", "celery")

    response = client.post(
        f"{API}/manuals/{seed_base['manual'].id}/index?async=true",
        headers=auth_headers("agent@demo.local"),
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["backend"] == "celery"
    assert body["task_id"].startswith("task-")
    stored = offline_store.get(body["task_id"])
    assert stored is not None
    assert stored.status == "PENDING"
    assert stored.owner_id == seed_base["users"]["agent"].id
    assert celery_send.calls == [
        ("zhixiu.index_manual", {"manual_id": seed_base["manual"].id, "task_id": body["task_id"]})
    ]


def test_index_without_async_flag_keeps_sync_response(
    client, auth_headers, seed_base, traced_events, offline_store, monkeypatch
):
    monkeypatch.setattr(settings, "task_backend", "celery")

    response = client.post(
        f"{API}/manuals/{seed_base['manual'].id}/index",
        headers=auth_headers("agent@demo.local"),
    )

    assert response.status_code == 200, response.text
    assert set(response.json()) == _INDEX_FIELDS
    assert response.json()["status"] == "indexed"
    assert _events(traced_events, "task_backend_ignored") == []


# ------------------------------------------------------------ TaskStore 回退


def test_task_store_falls_back_to_dict_when_redis_unavailable(traced_events, monkeypatch):
    def _unavailable(*args, **kwargs):
        raise redis.exceptions.ConnectionError("redis down")

    monkeypatch.setattr(redis.Redis, "from_url", _unavailable)
    store = TaskStore(url=UNREACHABLE_REDIS_URL)
    task_id = _new_task_id()

    store.put(TaskInfo(task_id=task_id, status="PENDING", backend="sync", owner_id="u-1"))
    loaded = store.get(task_id)
    assert loaded is not None
    assert loaded.status == "PENDING"
    assert loaded.owner_id == "u-1"

    updated = store.update(task_id, status="SUCCESS", result={"ok": True})
    assert updated is not None
    assert updated.status == "SUCCESS"
    assert updated.result == {"ok": True}
    assert store.get(task_id).status == "SUCCESS"
    assert store.get("task-missing") is None

    fallback = _events(traced_events, "task_store_fallback")
    assert len(fallback) == 1
    assert "redis down" in str(fallback[0]["fields"].get("reason"))


def test_task_store_stores_redis_json_with_ttl(traced_events, monkeypatch):
    """Redis 可用时按 `zhixiu:task:{id}` 写入 JSON 并带 TTL。"""
    writes: dict[str, dict] = {}

    class _FakeRedis:
        def ping(self) -> bool:
            return True

        def set(self, key, value, ex=None):
            writes[key] = {"value": value, "ex": ex}

        def get(self, key):
            entry = writes.get(key)
            return entry["value"] if entry else None

    monkeypatch.setattr(
        redis.Redis, "from_url", staticmethod(lambda *args, **kwargs: _FakeRedis())
    )
    monkeypatch.setattr(settings, "task_ttl_seconds", 3600)
    store = TaskStore(url="redis://fake:6379/1")
    task_id = _new_task_id()

    store.put(TaskInfo(task_id=task_id, status="PENDING", backend="sync", owner_id="u-1"))

    entry = writes[f"zhixiu:task:{task_id}"]
    assert entry["ex"] == 3600
    assert f'"task_id": "{task_id}"' in entry["value"]
    assert store.get(task_id).status == "PENDING"
    assert _events(traced_events, "task_store_fallback") == []