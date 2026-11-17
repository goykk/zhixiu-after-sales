"""设备档案读取与型号匹配。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import Device


@dataclass(frozen=True)
class DeviceProfile:
    id: str
    brand: str
    model: str
    hardware_version: str | None = None
    firmware_version: str | None = None
    category: str | None = None


def _norm(value: str | None) -> str:
    return " ".join((value or "").split()).lower()


def to_profile(device: Device) -> DeviceProfile:
    return DeviceProfile(
        id=device.id,
        brand=device.brand or "",
        model=device.model or "",
        hardware_version=device.hardware_version,
        firmware_version=device.firmware_version,
        category=device.category,
    )


def get_device_profile(db: Session, device_id: str) -> DeviceProfile | None:
    device = db.get(Device, device_id)
    return to_profile(device) if device is not None else None


def find_device_by_model(db: Session, model: str) -> DeviceProfile | None:
    """按型号匹配设备档案：先匹配 model，再匹配 `brand model` 全名，大小写与空白不敏感。"""
    target = _norm(model)
    if not target:
        return None
    devices = db.execute(select(Device).order_by(Device.created_at)).scalars().all()
    for device in devices:
        if _norm(device.model) == target:
            return to_profile(device)
    for device in devices:
        if _norm(f"{device.brand or ''} {device.model or ''}") == target:
            return to_profile(device)
    return None