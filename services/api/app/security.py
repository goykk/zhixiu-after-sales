"""密码哈希与 JWT 访问令牌。

密码使用标准库 PBKDF2-HMAC-SHA256（requirements.txt 未引入 bcrypt/passlib），
格式 `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>`，便于将来平滑迁移。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from core.policy.rbac import Role, as_role
from services.api.app.config import settings
from services.api.app.errors import ApiError

_PBKDF2_ALGO = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 260_000
_SALT_BYTES = 16


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    role: str
    exp: datetime


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return "$".join(
        (_PBKDF2_ALGO, str(_PBKDF2_ITERATIONS), _b64encode(salt), _b64encode(digest))
    )


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        algo, iterations, salt_b64, digest_b64 = password_hash.split("$")
        if algo != _PBKDF2_ALGO:
            return False
        expected = _b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _b64decode(salt_b64), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


def create_access_token(
    user_id: str, role: Role | str, *, minutes: int | None = None
) -> str:
    normalized = as_role(role)
    if normalized is None:
        raise ValueError(f"unknown role: {role!r}")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(
        minutes=settings.access_token_minutes if minutes is None else minutes
    )
    claims = {
        "sub": str(user_id),
        "role": normalized.value,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> TokenPayload:
    try:
        claims = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        user_id = str(claims["sub"])
        role = str(claims["role"])
        exp = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, OSError) as exc:
        # 401 不区分过期、签名错误与载荷损坏，避免泄露校验细节
        raise ApiError(401, "UNAUTHORIZED", "invalid or expired token") from exc
    if not user_id or as_role(role) is None:
        raise ApiError(401, "UNAUTHORIZED", "invalid or expired token")
    return TokenPayload(user_id=user_id, role=role, exp=exp)