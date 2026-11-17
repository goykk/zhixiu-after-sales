"""配件目录与兼容性接口。"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import get_db
from core.db.models import Part, User
from core.devices import find_device_by_model
from core.parts.catalog import PartSpec, parts_for_model
from core.parts.compatibility import check_part_compatibility
from core.policy.rbac import PART_READ, can
from services.api.app.deps import get_current_user
from services.api.app.errors import ApiError

router = APIRouter(tags=["parts"])


class PartOut(BaseModel):
    part_no: str
    name: str
    device_model: str
    stock_status: str
    hardware_range: str


class PartListOut(BaseModel):
    items: list[PartOut]


class CompatibilityOut(BaseModel):
    part_no: str
    compatible: bool
    compatibility_type: str
    evidence_source: str
    stock_status: str
    alternatives: list[str]


def _require_part_read(user: User) -> None:
    if not can(user.role, PART_READ):
        raise ApiError(403, "FORBIDDEN", "insufficient permission: part:read")


def _resolve_specs(db: Session, device_model: str) -> list[PartSpec]:
    """已入库配件优先（库存与适用区间属运营数据），未入库时回退到内置目录。"""
    catalog_specs = parts_for_model(device_model)
    device = find_device_by_model(db, device_model)
    if device is None:
        return catalog_specs
    rows = db.execute(
        select(Part).where(Part.device_id == device.id).order_by(Part.part_no)
    ).scalars().all()
    if not rows:
        return catalog_specs
    full_name = f"{device.brand} {device.model}".strip()
    return [
        PartSpec(
            part_no=row.part_no,
            name=row.name or row.part_no,
            device_model=full_name,
            stock_status=(row.stock_status or "unknown").strip().lower(),
            hardware_range=row.hardware_range or "",
        )
        for row in rows
    ]


@router.get("/parts", response_model=PartListOut)
def list_parts(
    device_model: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PartListOut:
    _require_part_read(user)
    return PartListOut(items=[PartOut(**asdict(spec)) for spec in _resolve_specs(db, device_model)])


@router.get("/parts/{part_no}/compatibility", response_model=CompatibilityOut)
def get_part_compatibility(
    part_no: str,
    device_model: str = Query(..., min_length=1),
    hardware_version: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CompatibilityOut:
    _require_part_read(user)
    result = check_part_compatibility(
        db, device_model=device_model, part_no=part_no, hardware_version=hardware_version
    )
    return CompatibilityOut(**asdict(result))