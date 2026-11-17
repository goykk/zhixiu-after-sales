"""T13 测试基座：隔离 SQLite、Mock AI 与通用 fixtures。

环境变量必须在导入 `core` / `services` 之前设置：`settings` 与数据库 engine
都在模块导入时完成初始化，之后再改环境变量不会生效。
"""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TEST_DB = _ROOT / "data" / "test_zhixiu.db"

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ["AI_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


from core.db.base import Base, SessionLocal, engine, get_db  # noqa: E402
from core.db.models import Device, Manual, User, new_id, utcnow  # noqa: E402
from core.rag.indexer import ManualIndexer  # noqa: E402
from services.api.app.main import create_app  # noqa: E402
from services.api.app.security import hash_password  # noqa: E402

SEED_PASSWORD = "test1234"

_SEED_ROLES = {
    "user": "user",
    "agent": "agent",
    "technician": "technician",
    "admin": "admin",
}

_MANUAL_TEXT = """<!-- page: 1 -->
# 风扇故障 E106
风扇区域出现异响或完全不转时，先检查叶片是否被异物卡阻、是否积尘过多。
<!-- page: 2 -->
# 风扇电机与驱动检查
断电后手动拨动叶片：若卡滞，多为轴承磨损；若顺畅，则检查驱动板供电与绕组。
"""


@pytest.fixture(scope="session", autouse=True)
def _database_schema():
    # 先加载扩展表（uploads）再重建 schema，避免跨次运行残留旧表结构。
    import core.multimodal.uploads  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_database(_database_schema):
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield


@pytest.fixture
def db(_clean_database):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(_clean_database):
    app = create_app()

    def _override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client):
    def _factory(email: str, password: str = SEED_PASSWORD) -> dict[str, str]:
        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _factory


@pytest.fixture
def seed_base(db):
    users: dict[str, User] = {}
    for key, role in _SEED_ROLES.items():
        user = User(
            id=new_id(),
            email=f"{key}@demo.local",
            password_hash=hash_password(SEED_PASSWORD),
            display_name=key,
            role=role,
            status="active",
            created_at=utcnow(),
        )
        db.add(user)
        users[key] = user

    device = Device(
        id=new_id(),
        brand="AuroraHome",
        model="AC-Pro 1200",
        hardware_version="HW-1",
        firmware_version="FW-2.3",
        category="air_conditioner",
        created_at=utcnow(),
    )
    db.add(device)
    db.flush()

    manual = Manual(
        id=new_id(),
        device_id=device.id,
        title="AC-Pro 1200 维修手册",
        version="v1.2",
        source_url="https://example.test/manuals/ac-pro-1200",
        checksum="seed-checksum",
        status="pending",
        content_text=_MANUAL_TEXT,
        created_at=utcnow(),
    )
    db.add(manual)
    db.commit()

    index_result = ManualIndexer(db).index_manual(manual.id)
    assert index_result.status == "indexed", index_result
    assert index_result.chunk_count > 0


    for user in users.values():
        db.refresh(user)
    db.refresh(device)
    db.refresh(manual)
    return {
        "password": SEED_PASSWORD,
        "users": users,
        "device": device,
        "manual": manual,
        "index_result": index_result,
    }


_PART_ALTERNATIVE_SUFFIX = "-R2"


def _range_upper(hardware_range: str) -> str:
    for separator in ("~", "..", "至"):
        if separator in hardware_range:
            return hardware_range.split(separator)[-1].strip()
    return hardware_range.strip()


@pytest.fixture
def seed_parts(db):
    """以 PART_CATALOG 为源写入 5 个演示型号的配件与替代关系。

    设备硬件版本对齐到目录适用区间内，避免维修方案因区间不匹配整体降级。
    返回 `parts`（型号→全部件号）、`plain`（无替代关系的兼容件）、`substitutable`（main/alternative）。
    """
    from sqlalchemy import select

    from core.db.models import Device, Part, PartCompatibility, new_id, utcnow
    from core.parts.catalog import PART_CATALOG

    devices: dict[str, Device] = {}
    part_numbers: dict[str, list[str]] = {}
    plain: dict[str, str] = {}
    substitutable: dict[str, dict[str, str]] = {}
    for full_name, specs in PART_CATALOG.items():
        brand, _, model = full_name.partition(" ")
        device = (
            db.execute(
                select(Device).where(Device.brand == brand, Device.model == model)
            )
            .scalars()
            .first()
        )
        if device is None:
            device = Device(
                id=new_id(),
                brand=brand,
                model=model,
                hardware_version=_range_upper(specs[0].hardware_range),
                firmware_version="FW-1",
                category="air_conditioner",
                created_at=utcnow(),
            )
            db.add(device)
            db.flush()
        else:
            device.hardware_version = _range_upper(specs[0].hardware_range)
        devices[full_name] = device

        for spec in specs:
            row = (
                db.execute(
                    select(Part).where(
                        Part.device_id == device.id, Part.part_no == spec.part_no
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                db.add(
                    Part(
                        id=new_id(),
                        device_id=device.id,
                        part_no=spec.part_no,
                        name=spec.name,
                        stock_status=spec.stock_status,
                        hardware_range=spec.hardware_range,
                        created_at=utcnow(),
                    )
                )
            else:
                row.name = spec.name
                row.stock_status = spec.stock_status
                row.hardware_range = spec.hardware_range

            self_record = (
                db.execute(
                    select(PartCompatibility).where(
                        PartCompatibility.source_part_no == spec.part_no,
                        PartCompatibility.target_part_no == spec.part_no,
                    )
                )
                .scalars()
                .first()
            )
            if self_record is None:
                db.add(
                    PartCompatibility(
                        id=new_id(),
                        source_part_no=spec.part_no,
                        target_part_no=spec.part_no,
                        compatibility_type="equivalent",
                        hardware_range=spec.hardware_range,
                        evidence_source="test-seed",
                        created_at=utcnow(),
                    )
                )

        alternatives = [
            spec for spec in specs if spec.part_no.endswith(_PART_ALTERNATIVE_SUFFIX)
        ]
        main_part_nos = {
            spec.part_no[: -len(_PART_ALTERNATIVE_SUFFIX)]
            for spec in alternatives
        }
        for alternative_spec in alternatives:
            main_part_no = alternative_spec.part_no[: -len(_PART_ALTERNATIVE_SUFFIX)]
            relation = (
                db.execute(
                    select(PartCompatibility).where(
                        PartCompatibility.source_part_no == main_part_no,
                        PartCompatibility.target_part_no == alternative_spec.part_no,
                    )
                )
                .scalars()
                .first()
            )
            if relation is None:
                db.add(
                    PartCompatibility(
                        id=new_id(),
                        source_part_no=main_part_no,
                        target_part_no=alternative_spec.part_no,
                        compatibility_type="replacement",
                        hardware_range=alternative_spec.hardware_range,
                        evidence_source="test-seed",
                        created_at=utcnow(),
                    )
                )
            substitutable[full_name] = {
                "main": main_part_no,
                "alternative": alternative_spec.part_no,
            }

        plain[full_name] = next(
            spec.part_no
            for spec in specs
            if not spec.part_no.endswith(_PART_ALTERNATIVE_SUFFIX)
            and spec.part_no not in main_part_nos
        )
        part_numbers[full_name] = [spec.part_no for spec in specs]

    db.commit()
    return {
        "models": list(devices),
        "devices": devices,
        "parts": part_numbers,
        "plain": plain,
        "substitutable": substitutable,
    }
