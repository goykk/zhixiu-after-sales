"""启动期安全自检：JWT 密钥强度（生产环境强制）。"""

from __future__ import annotations

import logging

from .config import Settings

logger = logging.getLogger("zhixiu.security")

_PROD_ENVS = {"prod", "production"}


def check_jwt_secret(settings: Settings) -> bool:
    """校验 JWT 密钥强度。生产环境不足则抛错；其他环境仅告警。返回是否达标。"""
    secret = str(getattr(settings, "jwt_secret", "") or "")
    min_bytes = int(getattr(settings, "jwt_min_secret_bytes", 32) or 32)
    length = len(secret.encode("utf-8"))
    weak = length < min_bytes
    env = str(getattr(settings, "env", "local") or "local").lower()
    if weak and env in _PROD_ENVS:
        raise RuntimeError(
            f"JWT_SECRET 强度不足：至少需要 {min_bytes} 字节（当前 {length} 字节）。"
            "请在 .env 中设置足够长的随机密钥。"
        )
    if weak:
        logger.warning("JWT_SECRET 偏短（%s < %s 字节），仅建议用于非生产环境", length, min_bytes)
    return not weak