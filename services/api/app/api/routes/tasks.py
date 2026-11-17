"""异步任务查询与异步开关（C-TASK-API@1 + C-OVERVIEW@1 任务列表）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.db.models import User
from core.observability.tracer import get_tracer
from core.policy.rbac import can
from core.tasks.dispatch import get_task
from core.tasks.store import get_task_store
from services.api.app.config import settings
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(prefix="/tasks", tags=["tasks"])

TASK_INDEX_MANUAL = "zhixiu.index_manual"
TASK_RUN_ABLATION = "zhixiu.run_ablation"
TASK_ADVANCE_CASE = "zhixiu.advance_case"


class TaskOut(BaseModel):
    task_id: str
    status: str
    backend: str
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class TaskListOut(BaseModel):
    items: list[TaskOut]


class TaskAcceptedOut(BaseModel):
    task_id: str
    status: str
    backend: str


def async_enabled(requested: bool, *, endpoint: str) -> bool:
    """async=true 仅在 TASK_BACKEND=celery 时生效；sync 后端继续同步执行并追踪。"""
    if not requested:
        return False
    if getattr(settings, "task_backend", "sync") != "celery":
        get_tracer().emit("task_backend_ignored", endpoint=endpoint, backend="sync")
        return False
    return True


def _task_out(info: Any) -> TaskOut:
    return TaskOut(
        task_id=info.task_id,
        status=info.status,
        backend=info.backend,
        result=info.result,
        error=info.error,
        created_at=info.created_at,
        updated_at=info.updated_at,
    )


@router.get("", response_model=TaskListOut)
def list_tasks(
    limit: int = 20,
    owner: str = "me",
    user: User = Depends(get_current_user),
) -> TaskListOut:
    actor = actor_of(user)
    if owner not in ("me", "all"):
        raise ApiError(422, "VALIDATION_ERROR", "owner 只能是 me 或 all")
    if owner == "all" and not can(actor.role, "case:read_all"):
        raise ApiError(403, "FORBIDDEN", "无权查看全部任务")
    if limit < 1 or limit > 100:
        raise ApiError(422, "LIMIT_EXCEEDED", "limit 必须在 1-100 之间")
    owner_id = None if owner == "all" else actor.actor_id
    infos = get_task_store().list(limit=limit, owner_id=owner_id)
    return TaskListOut(items=[_task_out(info) for info in infos])


@router.get("/{task_id}", response_model=TaskOut)
def get_task_endpoint(task_id: str, user: User = Depends(get_current_user)) -> TaskOut:
    info = get_task(task_id)
    if info is None:
        raise ApiError(404, "TASK_NOT_FOUND", f"任务不存在：{task_id}")
    actor = actor_of(user)
    if info.owner_id != actor.actor_id and not actor.is_staff:
        raise ApiError(403, "FORBIDDEN", "无权查询该任务")
    return _task_out(info)