"""任务派发：`sync` 在请求内执行，`celery` 提交后台任务，连接失败时回退同步并追踪。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from core.observability.tracer import get_tracer
from core.tasks.store import (
    STATUS_FAILURE,
    STATUS_PENDING,
    STATUS_SUCCESS,
    TaskInfo,
    TaskStore,
    get_task_store,
    new_task_id,
)
from services.api.app.config import settings


def dispatch(
    task_name: str,
    payload: dict,
    *,
    owner_id: str | None,
    sync_handler: Callable[[], dict] | None = None,
) -> TaskInfo:
    store = get_task_store()
    task_id = new_task_id()
    info = TaskInfo(
        task_id=task_id,
        status=STATUS_PENDING,
        backend=settings.task_backend,
        owner_id=owner_id,
    )
    store.put(info)

    if (settings.task_backend or "sync").strip().lower() == "celery":
        try:
            _celery_app().send_task(task_name, kwargs={**payload, "task_id": task_id})
        except Exception as exc:  # noqa: BLE001 - broker 不可用时必须回退，不得 500
            get_tracer().emit("task_backend_fallback", reason=f"{type(exc).__name__}: {exc}")
            return run_sync(info, _require_handler(sync_handler))
        return store.get(task_id) or info

    return run_sync(info, _require_handler(sync_handler))


def run_sync(task_info: TaskInfo, handler: Callable[[], dict]) -> TaskInfo:
    store = get_task_store()
    try:
        result = handler()
    except Exception as exc:
        _finish(store, task_info, STATUS_FAILURE, error=f"{type(exc).__name__}: {exc}")
        raise
    return _finish(store, task_info, STATUS_SUCCESS, result=result)


def get_task(task_id: str) -> TaskInfo | None:
    return get_task_store().get(task_id)


def _require_handler(handler: Callable[[], dict] | None) -> Callable[[], dict]:
    if handler is None:
        raise ValueError("sync 模式下必须提供 sync_handler")
    return handler


def _finish(
    store: TaskStore,
    task_info: TaskInfo,
    status: str,
    *,
    result: dict | None = None,
    error: str | None = None,
) -> TaskInfo:
    updated = store.update(task_info.task_id, status=status, result=result, error=error)
    if updated is not None:
        return updated
    # 记录可能因 TTL 过期消失；仍要返回本次执行的终态。
    return replace(task_info, status=status, result=result, error=error)


def _celery_app():
    # 延迟导入：Celery 是可选依赖，且 worker 模块反过来依赖 core.tasks。
    from services.worker.celery_app import celery_app

    return celery_app