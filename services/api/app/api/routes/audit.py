"""审计日志查询（C-AUDIT@1，仅 staff）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import get_db
from core.db.models import AuditLog, User
from core.policy.rbac import can
from services.api.app.deps import actor_of, get_current_user
from services.api.app.errors import ApiError

router = APIRouter(prefix="/audit-logs", tags=["audit"])


class AuditLogOut(BaseModel):
    id: str
    actor_id: str | None
    action: str
    resource_id: str
    payload_hash: str
    payload: dict
    created_at: str


@router.get("")
def list_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    action: str | None = None,
    actor_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    actor = actor_of(user)
    if not can(actor.role, "audit:read"):
        raise ApiError(403, "FORBIDDEN", "需要审计读取权限")

    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    rows = db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit)).scalars().all()
    items = [
        AuditLogOut(
            id=row.id,
            actor_id=row.actor_id,
            action=row.action,
            resource_id=row.resource_id,
            payload_hash=row.payload_hash,
            payload=row.payload or {},
            created_at=row.created_at.isoformat() if row.created_at else "",
        ).model_dump()
        for row in rows
    ]
    return {"items": items}