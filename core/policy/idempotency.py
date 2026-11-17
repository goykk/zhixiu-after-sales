"""工单幂等创建基础（C-APPROVAL@1 提供，C-WORKORDER@1 消费）。

同一 `idempotency_key` 至多产生一条 `WorkOrder`：先按键回查，未命中再执行
factory 落库；并发写入导致唯一键冲突时回滚并回查，保证调用方看到的始终是原单。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.db.models import AuditLog, WorkOrder, new_id, utcnow

WORK_ORDER_CREATED = "work_order.created"


def _payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_work_order_by_key(db: Any, key: str) -> WorkOrder | None:
    normalized = str(key or "").strip()
    if not normalized:
        return None
    return db.execute(
        select(WorkOrder).where(WorkOrder.idempotency_key == normalized).limit(1)
    ).scalar_one_or_none()


def create_work_order_idempotent(
    db: Any,
    *,
    case_id: str,
    idempotency_key: str,
    factory: Callable[[], WorkOrder],
) -> tuple[WorkOrder, bool]:
    """返回 `(work_order, created)`；重复请求返回原单且 `created=False`。"""
    normalized = str(idempotency_key or "").strip()
    if not normalized:
        raise ValueError("idempotency_key is required")

    existing = get_work_order_by_key(db, normalized)
    if existing is not None:
        return existing, False

    try:
        work_order = factory()
        db.add(work_order)
        db.flush()
        payload = {
            "case_id": case_id,
            "work_order_id": work_order.id,
            "idempotency_key": normalized,
        }
        db.add(
            AuditLog(
                id=new_id(),
                actor_id=None,
                action=WORK_ORDER_CREATED,
                resource_id=case_id,
                payload_hash=_payload_hash(payload),
                payload=payload,
                created_at=utcnow(),
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_work_order_by_key(db, normalized)
        if existing is None:
            raise
        return existing, False
    except Exception:
        db.rollback()
        raise

    db.refresh(work_order)
    return work_order, True