"""幂等写入 20 条模拟维修结果（案例 + 工单 + 结果）。

用法：

    python scripts/seed_outcomes.py
    python scripts/seed_outcomes.py --samples data/outcomes/v1/sample_outcomes.json

每条样本按幂等键 `sim-<n>` 建一个处于 `WORK_ORDER_CREATED` 的案例、一张已完成工单与
一条维修结果，并在案例 `extracted` 与结果 `note` 中标注 `source=simulated`。
重复执行时按幂等键跳过，不新增、不覆盖。
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

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from core.db.base import SessionLocal, create_all  # noqa: E402
from core.db.models import (  # noqa: E402
    Case,
    Device,
    RepairOutcome,
    User,
    WorkOrder,
    new_id,
    utcnow,
)
from core.devices import find_device_by_model  # noqa: E402
from core.workflow.states import CaseStatus  # noqa: E402
from services.api.app.security import hash_password  # noqa: E402

DEFAULT_SAMPLES = ROOT / "data" / "outcomes" / "v1" / "sample_outcomes.json"
DEMO_PASSWORD = "demo1234"
USER_EMAIL = "user@demo.local"
TECH_EMAIL = "tech@demo.local"
SOURCE_MARKER = "simulated"


@dataclass(frozen=True)
class SeedStats:
    created: int = 0
    skipped: int = 0
    devices_created: int = 0


def _load_samples(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    samples = payload.get("outcomes")
    if not isinstance(samples, list) or not samples:
        raise ValueError("sample_outcomes.json 缺少非空的 outcomes 列表")
    return samples


def _ensure_user(db: Session, *, email: str, display_name: str, role: str) -> User:
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        id=new_id(),
        email=email,
        password_hash=hash_password(DEMO_PASSWORD),
        display_name=display_name,
        role=role,
        status="active",
        created_at=utcnow(),
    )
    db.add(user)
    db.flush()
    return user


def _ensure_device(db: Session, device_model: str) -> tuple[Device, bool]:
    profile = find_device_by_model(db, device_model)
    if profile is not None:
        device = db.get(Device, profile.id)
        if device is not None:
            return device, False
    brand, _, model = device_model.partition(" ")
    if not model:
        brand, model = "Generic", brand or device_model
    device = Device(
        id=new_id(),
        brand=brand,
        model=model,
        hardware_version="HW-1.0",
        category=None,
        created_at=utcnow(),
    )
    db.add(device)
    db.flush()
    return device, True


def seed_outcomes(db: Session, samples: list[dict]) -> SeedStats:
    owner = _ensure_user(db, email=USER_EMAIL, display_name="演示用户", role="user")
    technician = _ensure_user(
        db, email=TECH_EMAIL, display_name="演示技师", role="technician"
    )
    created = 0
    skipped = 0
    devices_created = 0

    for index, sample in enumerate(samples, start=1):
        idempotency_key = f"sim-{index}"
        existing = db.execute(
            select(WorkOrder).where(WorkOrder.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            skipped += 1
            continue

        device, device_created = _ensure_device(db, str(sample["device_model"]))
        devices_created += int(device_created)
        now = utcnow()
        case = Case(
            id=new_id(),
            user_id=owner.id,
            device_id=device.id,
            status=CaseStatus.WORK_ORDER_CREATED.value,
            symptom=str(sample["case_symptom"]),
            error_code=str(sample["error_code"]),
            extracted={"source": SOURCE_MARKER, "sample_index": index},
            step_count=0,
            evidence_version=0,
            missing_fields=[],
        )
        db.add(case)
        db.flush()

        work_order = WorkOrder(
            id=new_id(),
            case_id=case.id,
            idempotency_key=idempotency_key,
            status="resolved",
            assignee=TECH_EMAIL,
            external_id=f"SIM-{index:04d}",
            resolution=SOURCE_MARKER,
            created_at=now,
            updated_at=now,
        )
        db.add(work_order)
        db.flush()

        db.add(
            RepairOutcome(
                id=new_id(),
                work_order_id=work_order.id,
                technician_id=technician.id,
                actual_cause_code=str(sample["actual_cause_code"]),
                action=str(sample["action"]),
                parts_replaced=list(sample.get("parts_replaced") or []),
                resolved=bool(sample.get("resolved", False)),
                note=f"source={SOURCE_MARKER}; {sample.get('note') or ''}".strip(),
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        created += 1

    db.commit()
    return SeedStats(created=created, skipped=skipped, devices_created=devices_created)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="写入智修 V1.2 模拟维修结果样本")
    parser.add_argument(
        "--samples", default=str(DEFAULT_SAMPLES), help="维修结果样本 JSON 路径"
    )
    args = parser.parse_args(argv)

    try:
        samples = _load_samples(Path(args.samples))
    except (OSError, ValueError) as exc:
        print(f"[ERROR] 读取维修结果样本失败：{exc}")
        return 1

    create_all()
    db = SessionLocal()
    try:
        stats = seed_outcomes(db, samples)
    finally:
        db.close()

    print(
        f"模拟维修结果：新增 {stats.created} 条，跳过 {stats.skipped} 条，"
        f"自动建档设备 {stats.devices_created} 台（source={SOURCE_MARKER}）"
    )
    print(f"OUTCOMES {len(samples)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())