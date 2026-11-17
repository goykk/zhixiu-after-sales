"""任务抽象：状态记录、派发与查询。"""

from __future__ import annotations

from core.tasks.store import (
    STATUS_FAILURE,
    STATUS_PENDING,
    STATUS_STARTED,
    STATUS_SUCCESS,
    TaskInfo,
    TaskStore,
    get_task_store,
    new_task_id,
)
from core.tasks.dispatch import dispatch, get_task, run_sync

__all__ = [
    "STATUS_FAILURE",
    "STATUS_PENDING",
    "STATUS_STARTED",
    "STATUS_SUCCESS",
    "TaskInfo",
    "TaskStore",
    "dispatch",
    "get_task",
    "get_task_store",
    "new_task_id",
    "run_sync",
]