"""设备档案接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.base import get_db
from core.db.models import Device, new_id
from core.devices import get_device_profile, to_profile
from services.api.app.deps import get_current_user, require_roles
from services.api.app.errors import ApiError

router = APIRouter(tags=["devices"])


class DeviceCreate(BaseModel):
    brand: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=120)
    hardware_version: str | None = None
    firmware_version: str | None = None
    category: str | None = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    brand: str
    model: str
    hardware_version: str | None = None
    firmware_version: str | None = None
    category: str | None = None


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(
    brand: str | None = None,
    model: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> list[DeviceOut]:
    stmt = select(Device).order_by(Device.created_at)
    if brand and brand.strip():
        stmt = stmt.where(func.lower(Device.brand) == brand.strip().lower())
    if model and model.strip():
        stmt = stmt.where(func.lower(Device.model) == model.strip().lower())
    devices = db.execute(stmt).scalars().all()
    return [DeviceOut.model_validate(to_profile(device)) for device in devices]


@router.post("/devices", response_model=DeviceOut, status_code=201)
def create_device(
    payload: DeviceCreate,
    db: Session = Depends(get_db),
    user=Depends(require_roles("agent", "admin")),
) -> DeviceOut:
    brand, model = payload.brand.strip(), payload.model.strip()
    duplicate = db.execute(
        select(Device).where(func.lower(Device.brand) == brand.lower(), func.lower(Device.model) == model.lower())
    ).scalars().first()
    if duplicate is not None:
        raise ApiError(409, "DEVICE_EXISTS", f"设备档案已存在：{brand} {model}")
    device = Device(
        id=new_id(),
        brand=brand,
        model=model,
        hardware_version=_clean(payload.hardware_version),
        firmware_version=_clean(payload.firmware_version),
        category=_clean(payload.category),
    )
    db.add(device)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "DEVICE_EXISTS", f"设备档案已存在：{brand} {model}")
    db.refresh(device)
    return DeviceOut.model_validate(to_profile(device))


@router.get("/devices/{device_id}", response_model=DeviceOut)
def get_device(device_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)) -> DeviceOut:
    profile = get_device_profile(db, device_id)
    if profile is None:
        raise ApiError(404, "DEVICE_NOT_FOUND", f"设备档案不存在：{device_id}")
    return DeviceOut.model_validate(profile)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None