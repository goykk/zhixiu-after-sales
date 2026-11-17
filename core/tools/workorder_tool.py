"""create_work_order 工具：审批前置、上游建单与幂等落库。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.db.models import Case, WorkOrder, new_id
from core.policy.approval import has_approved
from core.policy.idempotency import create_work_order_idempotent
from core.policy.rbac import Actor, can_access_case
from core.tools.gateway import ToolError
from core.tools.mock_backend import get_mock_backend
from services.api.app.errors import ApiError


def work_order_out(work_order: WorkOrder) -> dict[str, Any]:
    return {
        "id": work_order.id,
        "case_id": work_order.case_id,
        "status": work_order.status,
        "assignee": work_order.assignee,
        "external_id": work_order.external_id,
        "resolution": work_order.resolution,
        "created_at": work_order.created_at,
        "updated_at": work_order.updated_at,
    }


def _lock_case(db: Any, case_id: str) -> Case:
    stmt = select(Case).where(Case.id == case_id)
    if db.get_bind().dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    case = db.execute(stmt).scalar_one_or_none()
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", "case not found")
    return case


def create_work_order(
    db: Any,
    *,
    case_id: str,
    actor: Actor,
    idempotency_key: str,
    assignee: str | None = None,
) -> tuple[WorkOrder, bool]:
    key = str(idempotency_key or "").strip()
    if not key:
        raise ToolError("IDEMPOTENCY_KEY_REQUIRED", "idempotency_key is required")

    case = _lock_case(db, case_id)
    if not can_access_case(actor, case_user_id=case.user_id):
        raise ApiError(403, "FORBIDDEN", "forbidden")
    if not has_approved(db, case.id):
        raise ToolError("APPROVAL_REQUIRED", "case has no approved repair plan")

    backend = get_mock_backend()

    def factory() -> WorkOrder:
        record = backend.create(
            idempotency_key=key, case_id=case.id, assignee=assignee
        )
        return WorkOrder(
            id=new_id(),
            case_id=case.id,
            idempotency_key=key,
            status=str(record.get("status") or "created"),
            assignee=assignee,
            external_id=record.get("external_id"),
            resolution=record.get("resolution"),
        )

    return create_work_order_idempotent(
        db, case_id=case.id, idempotency_key=key, factory=factory
    )