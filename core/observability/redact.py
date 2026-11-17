"""日志与追踪载荷脱敏。"""

from __future__ import annotations

import re
from typing import Any

MASK = "***"

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "passwd",
        "pwd",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "authorization",
        "jwt_secret",
        "secret",
        "secret_key",
        "api_key",
        "apikey",
        "access_key",
        "private_key",
        "session_id",
        "cookie",
        "email",
        "email_address",
        "e_mail",
    }
)

_SENSITIVE_SUFFIXES = ("_password", "_token", "_secret")

_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")

_MAX_DEPTH = 8


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.strip().lower().replace("-", "_")
    return (
        normalized in SENSITIVE_KEYS
        or normalized.endswith(_SENSITIVE_SUFFIXES)
        or "email" in normalized
    )


def _redact_str(value: str) -> str:
    return _BEARER_PATTERN.sub(f"Bearer {MASK}", value)


def redact(value: Any, *, mask: str = MASK, _depth: int = 0) -> Any:
    """递归替换敏感字段值与 Bearer 令牌，保留结构以便排查。"""
    if _depth > _MAX_DEPTH:
        return mask
    if isinstance(value, dict):
        return {
            key: (mask if _is_sensitive_key(key) else redact(item, mask=mask, _depth=_depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact(item, mask=mask, _depth=_depth + 1) for item in value]
    if isinstance(value, str):
        return _redact_str(value)
    return value