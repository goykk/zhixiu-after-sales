"""幂等种子数据：4 个账号、5 台设备、20 份手册（并索引）与 1 个演示案例。

用法：

    python scripts/seed_demo.py
    python scripts/seed_demo.py --skip-index     # 只登记手册，不建切片

脚本可重复执行：已存在的账号/设备/手册会被就地更新，手册索引幂等重建，
演示案例按「用户 + 设备 + 故障码 + 现象」去重。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from core.cases.service import create_case  # noqa: E402
from core.db.base import SessionLocal, create_all  # noqa: E402
from core.db.models import Case, Device, Manual, User, new_id, utcnow  # noqa: E402
from core.rag.indexer import STATUS_INDEXED, ManualIndexer  # noqa: E402
from services.api.app.security import hash_password  # noqa: E402

DEMO_PASSWORD = "demo1234"

USERS: tuple[tuple[str, str, str], ...] = (
    ("user@demo.local", "user", "演示用户"),
    ("agent@demo.local", "agent", "演示调度"),
    ("tech@demo.local", "technician", "演示技师"),
    ("admin@demo.local", "admin", "演示管理员"),
)

DEVICES: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("ac-pro-1200", "AuroraHome", "AC-Pro 1200", "HW-2.1", "3.4.2", "air_conditioner"),
    ("ac-pro-900", "AuroraHome", "AC-Pro 900", "HW-1.4", "2.6.1", "air_conditioner"),
    ("wh-3000", "AuroraHome", "WH-3000", "HW-3.1", "4.0.3", "heat_pump_water_heater"),
    ("ac-lite-500", "AuroraHome", "AC-Lite 500", "HW-1.1", "2.2.0", "air_conditioner"),
    ("dh-200", "Northwind", "DH-200", "HW-1.0", "1.8.4", "dehumidifier"),
)

MANUALS: tuple[tuple[str, str, str], ...] = (
    ("ac-pro-1200", "data/manuals/aurorahome/ac-pro-1200/01-installation-and-safety.md", "v1.2"),
    ("ac-pro-1200", "data/manuals/aurorahome/ac-pro-1200/02-error-codes.md", "v1.2"),
    ("ac-pro-1200", "data/manuals/aurorahome/ac-pro-1200/03-fan-and-airflow-troubleshooting.md", "v1.2"),
    ("ac-pro-1200", "data/manuals/aurorahome/ac-pro-1200/04-maintenance-and-cleaning.md", "v1.1"),
    ("ac-pro-900", "data/manuals/aurorahome/ac-pro-900/01-installation-and-safety.md", "v1.1"),
    ("ac-pro-900", "data/manuals/aurorahome/ac-pro-900/02-error-codes.md", "v1.1"),
    ("ac-pro-900", "data/manuals/aurorahome/ac-pro-900/03-fan-and-airflow-troubleshooting.md", "v1.1"),
    ("ac-pro-900", "data/manuals/aurorahome/ac-pro-900/04-maintenance-and-cleaning.md", "v1.0"),
    ("wh-3000", "data/manuals/aurorahome/wh-3000/01-installation-and-safety.md", "v2.0"),
    ("wh-3000", "data/manuals/aurorahome/wh-3000/02-error-codes.md", "v2.0"),
    ("wh-3000", "data/manuals/aurorahome/wh-3000/03-fan-and-airflow-troubleshooting.md", "v2.0"),
    ("wh-3000", "data/manuals/aurorahome/wh-3000/04-maintenance-and-cleaning.md", "v1.8"),
    ("ac-lite-500", "data/manuals/aurorahome/ac-lite-500/01-installation-and-safety.md", "v1.0"),
    ("ac-lite-500", "data/manuals/aurorahome/ac-lite-500/02-error-codes.md", "v1.0"),
    ("ac-lite-500", "data/manuals/aurorahome/ac-lite-500/03-fan-and-airflow-troubleshooting.md", "v1.0"),
    ("ac-lite-500", "data/manuals/aurorahome/ac-lite-500/04-maintenance-and-cleaning.md", "v1.0"),
    ("dh-200", "data/manuals/northwind/dh-200/01-installation-and-safety.md", "v1.3"),
    ("dh-200", "data/manuals/northwind/dh-200/02-error-codes.md", "v1.3"),
    ("dh-200", "data/manuals/northwind/dh-200/03-fan-and-airflow-troubleshooting.md", "v1.3"),
    ("dh-200", "data/manuals/northwind/dh-200/04-maintenance-and-cleaning.md", "v1.2"),
)

DEMO_CASE_SYMPTOM = "制冷时风扇区域有摩擦异响，出风很小，面板显示 E106。"
_TITLE_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class SeedStats:
    users: int = 0
    devices: int = 0
    manuals: int = 0
    indexed: int = 0
    case_created: bool = False


def _manual_title(path: Path) -> str:
    match = _TITLE_PATTERN.search(path.read_text(encoding="utf-8"))
    if match is None:
        return path.stem
    return match.group(1).strip()


def seed_users(db: Session) -> int:
    for email, role, display_name in USERS:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(id=new_id(), email=email, created_at=utcnow())
            db.add(user)
        user.password_hash = hash_password(DEMO_PASSWORD)
        user.display_name = display_name
        user.role = role
        user.status = "active"
    db.commit()
    return len(USERS)


def seed_devices(db: Session) -> dict[str, Device]:
    devices: dict[str, Device] = {}
    for key, brand, model, hardware, firmware, category in DEVICES:
        device = db.execute(
            select(Device).where(Device.brand == brand, Device.model == model)
        ).scalar_one_or_none()
        if device is None:
            device = Device(id=new_id(), brand=brand, model=model, created_at=utcnow())
            db.add(device)
        device.hardware_version = hardware
        device.firmware_version = firmware
        device.category = category
        db.flush()
        devices[key] = device
    db.commit()
    return devices


def seed_manuals(db: Session, devices: dict[str, Device], *, skip_index: bool) -> tuple[int, int, list[str]]:
    created_or_updated = 0
    indexed = 0
    errors: list[str] = []
    for device_key, relative_path, version in MANUALS:
        path = ROOT / relative_path
        if not path.exists():
            errors.append(f"手册文件缺失：{relative_path}")
            continue
        content = path.read_text(encoding="utf-8")
        title = _manual_title(path)
        device = devices[device_key]
        manual = db.execute(
            select(Manual).where(Manual.device_id == device.id, Manual.title == title)
        ).scalar_one_or_none()
        if manual is None:
            manual = Manual(id=new_id(), device_id=device.id, title=title, created_at=utcnow())
            db.add(manual)
        manual.version = version
        manual.content_text = content
        manual.checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        manual.source_url = f"file:///{relative_path.replace(' ', '%20')}"
        manual.status = "pending"
        manual.indexed_at = None
        db.flush()
        created_or_updated += 1

        if skip_index:
            continue
        result = ManualIndexer(db).index_manual(manual.id)
        if result.status == STATUS_INDEXED:
            indexed += 1
        else:
            errors.append(f"索引失败 {title}: {result.error}")
    db.commit()
    return created_or_updated, indexed, errors


def seed_case(db: Session) -> bool:
    owner = db.execute(select(User).where(User.email == "user@demo.local")).scalar_one()
    device = db.execute(
        select(Device).where(Device.brand == "AuroraHome", Device.model == "AC-Pro 1200")
    ).scalar_one()
    existing = db.execute(
        select(Case).where(
            Case.user_id == owner.id,
            Case.device_id == device.id,
            Case.error_code == "E106",
            Case.symptom == DEMO_CASE_SYMPTOM,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    create_case(
        db,
        user=owner,
        device_model=f"{device.brand} {device.model}",
        symptom=DEMO_CASE_SYMPTOM,
        error_code="E106",
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="写入智修 V1.2 演示种子数据")
    parser.add_argument("--skip-index", action="store_true", help="只登记手册，不建立向量切片")
    args = parser.parse_args(argv)

    create_all()
    db = SessionLocal()
    try:
        users = seed_users(db)
        devices = seed_devices(db)
        manual_count, indexed, errors = seed_manuals(db, devices, skip_index=args.skip_index)
        case_created = seed_case(db)
    finally:
        db.close()

    print(f"账号 {users} 个（密码 {DEMO_PASSWORD}）")
    print(f"设备 {len(DEVICES)} 台")
    print(f"手册 {manual_count} 份，索引成功 {indexed} 份")
    print(f"演示案例：{'已创建' if case_created else '已存在，跳过'}")
    if errors:
        for message in errors:
            print(f"[WARN] {message}")
        print("种子数据存在失败项，请按上方提示排查（不阻断 API 启动）")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())