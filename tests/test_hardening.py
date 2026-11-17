"""生产化硬化测试：JWT 强度、限流、审计查询（C-TEST-HARDENING@1）。"""

from __future__ import annotations

from services.api.app.config import Settings
from services.api.app.hardening import check_jwt_secret
from services.api.app.ratelimit import get_limiter


def test_jwt_secret_weak_in_prod_raises():
    weak_prod = Settings(env="prod", jwt_secret="short")
    try:
        check_jwt_secret(weak_prod)
    except RuntimeError as exc:
        assert "JWT_SECRET" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("生产环境弱密钥应抛错")


def test_jwt_secret_weak_in_local_only_warns():
    weak_local = Settings(env="local", jwt_secret="short")
    assert check_jwt_secret(weak_local) is False


def test_jwt_secret_strong_passes():
    strong = Settings(env="prod", jwt_secret="x" * 40)
    assert check_jwt_secret(strong) is True


def test_rate_limit_blocks_after_threshold(client, seed_base, auth_headers, monkeypatch):
    from services.api.app.config import settings

    monkeypatch.setattr(settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2, raising=False)
    monkeypatch.setattr(settings, "rate_limit_burst", 2, raising=False)
    limiter = get_limiter()
    limiter.reset()
    try:
        headers = auth_headers("user@demo.local")
        codes = [client.get("/api/v1/auth/me", headers=headers).status_code for _ in range(4)]
        assert codes[:2] == [200, 200]
        assert 429 in codes[2:]
    finally:
        limiter.reset()
        monkeypatch.setattr(settings, "rate_limit_enabled", False, raising=False)


def test_rate_limit_disabled_by_default(client, seed_base, auth_headers):
    headers = auth_headers("user@demo.local")
    codes = [client.get("/api/v1/auth/me", headers=headers).status_code for _ in range(5)]
    assert codes == [200] * 5


def test_health_never_rate_limited(client, seed_base, monkeypatch):
    from services.api.app.config import settings

    monkeypatch.setattr(settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1, raising=False)
    monkeypatch.setattr(settings, "rate_limit_burst", 1, raising=False)
    get_limiter().reset()
    try:
        codes = [client.get("/health").status_code for _ in range(4)]
        assert codes == [200] * 4
    finally:
        get_limiter().reset()
        monkeypatch.setattr(settings, "rate_limit_enabled", False, raising=False)


def test_audit_logs_permissions_and_shape(client, db, seed_base, auth_headers):
    from core.db.models import AuditLog, new_id, utcnow

    db.add(
        AuditLog(
            id=new_id(),
            actor_id=seed_base["users"]["agent"].id,
            action="case.diagnosed",
            resource_id="case-1",
            payload_hash="deadbeef",
            payload={"case_status": "DIAGNOSED"},
            created_at=utcnow(),
        )
    )
    db.commit()

    agent = client.get("/api/v1/audit-logs?limit=10", headers=auth_headers("agent@demo.local"))
    assert agent.status_code == 200, agent.text
    body = agent.json()
    assert body["items"] and set(body["items"][0]) == {
        "id",
        "actor_id",
        "action",
        "resource_id",
        "payload_hash",
        "payload",
        "created_at",
    }
    user = client.get("/api/v1/audit-logs", headers=auth_headers("user@demo.local"))
    assert user.status_code == 403
    bad = client.get("/api/v1/audit-logs?limit=999", headers=auth_headers("agent@demo.local"))
    assert bad.status_code == 422