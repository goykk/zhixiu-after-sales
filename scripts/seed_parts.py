"""幂等写入模拟配件目录与兼容关系。

用法：

    python scripts/seed_parts.py
    python scripts/seed_parts.py --catalog data/parts/v1/catalog.json

读取 `data/parts/v1/catalog.json`，按 `(device_id, part_no)` 与
`(source_part_no, target_part_no)` 唯一键查重，已存在的行直接跳过。替代关系中的
`<主件号>-R2` 会随主件写入同一设备的配件行（模拟库存默认 `in_stock`），
保证 `check_part_compatibility` 能命中替代件。

演示型号的设备档案缺失时按「品牌 + 型号」自动建档（模拟数据，幂等）。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from core.db.base import SessionLocal, create_all  # noqa: E402
from core.db.models import Device, Part, PartCompatibility, new_id, utcnow  # noqa: E402
from core.devices import find_device_by_model  # noqa: E402

DEFAULT_CATALOG = ROOT / "data" / "parts" / "v1" / "catalog.json"
DEMO_HARDWARE_VERSION = "HW-1.0"
REPLACEMENT_SUFFIX = "-R2"


@dataclass(frozen=True)
class SeedStats:
    devices_created: int = 0
    parts_created: int = 0
    parts_skipped: int = 0
    compat_created: int = 0
    compat_skipped: int = 0


def _load_catalog(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    models = payload.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("catalog.json 缺少非空的 models 列表")
    return payload


def _split_device_model(device_model: str) -> tuple[str, str]:
    brand, _, model = device_model.partition(" ")
    if not model:
        return "Generic", brand or device_model
    return brand, model


def _ensure_device(db: Session, device_model: str) -> tuple[Device, bool]:
    profile = find_device_by_model(db, device_model)
    if profile is not None:
        device = db.get(Device, profile.id)
        if device is not None:
            return device, False
    brand, model = _split_device_model(device_model)
    device = Device(
        id=new_id(),
        brand=brand,
        model=model,
        hardware_version=DEMO_HARDWARE_VERSION,
        category=None,
        created_at=utcnow(),
    )
    db.add(device)
    db.flush()
    return device, True


def _ensure_part(
    db: Session,
    *,
    device: Device,
    part_no: str,
    name: str,
    stock_status: str,
    hardware_range: str,
) -> bool:
    existing = db.execute(
        select(Part).where(Part.device_id == device.id, Part.part_no == part_no)
    ).scalar_one_or_none()
    if existing is not None:
        return False
    db.add(
        Part(
            id=new_id(),
            device_id=device.id,
            part_no=part_no,
            name=name,
            stock_status=stock_status,
            hardware_range=hardware_range,
            created_at=utcnow(),
        )
    )
    db.flush()
    return True


def _ensure_compatibility(
    db: Session,
    *,
    source_part_no: str,
    target_part_no: str,
    compatibility_type: str,
    hardware_range: str,
    evidence_source: str,
) -> bool:
    existing = db.execute(
        select(PartCompatibility).where(
            PartCompatibility.source_part_no == source_part_no,
            PartCompatibility.target_part_no == target_part_no,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    db.add(
        PartCompatibility(
            id=new_id(),
            source_part_no=source_part_no,
            target_part_no=target_part_no,
            compatibility_type=compatibility_type,
            hardware_range=hardware_range,
            evidence_source=evidence_source,
            created_at=utcnow(),
        )
    )
    db.flush()
    return True


def seed_parts(db: Session, catalog: dict) -> SeedStats:
    devices_created = 0
    parts_created = 0
    parts_skipped = 0
    compat_created = 0
    compat_skipped = 0
    replacement_relations: list[tuple[str, str, str]] = []
    device_parts: list[tuple[Device, dict[str, str]]] = []

    for model_block in catalog["models"]:
        device_model = str(model_block["device_model"])
        device, created = _ensure_device(db, device_model)
        devices_created += int(created)

        part_names = {
            item["part_no"]: item["name"] for item in model_block.get("parts", [])
        }
        device_parts.append((device, part_names))
        for item in model_block.get("parts", []):
            if _ensure_part(
                db,
                device=device,
                part_no=str(item["part_no"]),
                name=str(item["name"]),
                stock_status=str(item["stock_status"]),
                hardware_range=str(item["hardware_range"]),
            ):
                parts_created += 1
            else:
                parts_skipped += 1

        for compatibility in model_block.get("compatibilities", []):
            source_part_no = str(compatibility["source_part_no"])
            target_part_no = str(compatibility["target_part_no"])
            hardware_range = str(compatibility["hardware_range"])
            if _ensure_compatibility(
                db,
                source_part_no=source_part_no,
                target_part_no=target_part_no,
                compatibility_type=str(compatibility["compatibility_type"]),
                hardware_range=hardware_range,
                evidence_source=str(compatibility["evidence_source"]),
            ):
                compat_created += 1
            else:
                compat_skipped += 1
            if (
                str(compatibility["compatibility_type"]) == "replacement"
                and target_part_no.endswith(REPLACEMENT_SUFFIX)
            ):
                relation = (source_part_no, target_part_no, hardware_range)
                if relation not in replacement_relations:
                    replacement_relations.append(relation)

    # 替代件按全局件号关系注册到所有拥有该主件的设备，保证库存查询能命中
    for device, part_names in device_parts:
        for source_part_no, target_part_no, hardware_range in replacement_relations:
            source_name = part_names.get(source_part_no)
            if source_name is None:
                continue
            if _ensure_part(
                db,
                device=device,
                part_no=target_part_no,
                name=f"{source_name}（R2 替代件）",
                stock_status="in_stock",
                hardware_range=hardware_range,
            ):
                parts_created += 1
            else:
                parts_skipped += 1

    db.commit()
    return SeedStats(
        devices_created=devices_created,
        parts_created=parts_created,
        parts_skipped=parts_skipped,
        compat_created=compat_created,
        compat_skipped=compat_skipped,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="写入智修 V1.2 模拟配件目录")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="配件目录 JSON 路径")
    args = parser.parse_args(argv)

    try:
        catalog = _load_catalog(Path(args.catalog))
    except (OSError, ValueError) as exc:
        print(f"[ERROR] 读取配件目录失败：{exc}")
        return 1

    create_all()
    db = SessionLocal()
    try:
        stats = seed_parts(db, catalog)
        parts_total = db.execute(select(func.count()).select_from(Part)).scalar_one()
        compat_total = db.execute(
            select(func.count()).select_from(PartCompatibility)
        ).scalar_one()
    finally:
        db.close()

    print(
        f"配件 {parts_total} 个（新增 {stats.parts_created}，跳过 {stats.parts_skipped}）"
    )
    print(
        f"兼容关系 {compat_total} 条（新增 {stats.compat_created}，跳过 {stats.compat_skipped}）"
    )
    print(f"自动建档设备 {stats.devices_created} 台")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())