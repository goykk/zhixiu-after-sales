"""运营概览聚合接口（C-OVERVIEW@1，只读）。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.db.base import get_db
from core.db.models import Case, EvalRunRecord, RepairOutcome, User, WorkOrder
from core.policy.rbac import can
from core.tasks.store import get_task_store
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(tags=["overview"])

DIAGNOSED_STATUSES = {
    "DIAGNOSED",
    "REPAIR_PLANNING",
    "APPROVAL_PENDING",
    "WORK_ORDER_CREATED",
    "OUTCOME_PENDING",
    "CLOSED",
}


@router.get("/overview")
def overview(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    actor = actor_of(user)
    if not can(actor.role, "case:read_all"):
        raise ApiError(403, "FORBIDDEN", "需要调度或管理员权限")

    case_rows = db.execute(select(Case.status, func.count()).group_by(Case.status)).all()
    cases_by_status = {str(status): int(count) for status, count in case_rows}
    cases_total = sum(cases_by_status.values())

    wo_rows = db.execute(
        select(WorkOrder.status, func.count()).group_by(WorkOrder.status)
    ).all()
    work_orders_by_status = {str(status): int(count) for status, count in wo_rows}

    outcomes = int(
        db.execute(select(func.count()).select_from(RepairOutcome)).scalar() or 0
    )
    eval_total = int(
        db.execute(select(func.count()).select_from(EvalRunRecord)).scalar() or 0
    )
    latest = (
        db.execute(
            select(EvalRunRecord).order_by(EvalRunRecord.created_at.desc()).limit(1)
        )
        .scalars()
        .first()
    )
    latest_passed = bool(latest.passed) if latest is not None else None

    tasks = get_task_store().list(limit=500)
    tasks_by_status = dict(Counter(task.status for task in tasks))

    return {
        "cases": {"total": cases_total, "by_status": cases_by_status},
        "need_human": cases_by_status.get("NEED_HUMAN", 0),
        "diagnosed": sum(cases_by_status.get(s, 0) for s in DIAGNOSED_STATUSES),
        "work_orders": {
            "total": sum(work_orders_by_status.values()),
            "by_status": work_orders_by_status,
        },
        "outcomes": outcomes,
        "eval_runs": {"total": eval_total, "latest_passed": latest_passed},
        "tasks": {"total": len(tasks), "by_status": tasks_by_status},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }