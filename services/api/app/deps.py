"""FastAPI 认证依赖：Bearer 解析、当前用户与角色校验。"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from core.db.base import get_db
from core.db.models import User
from core.policy.rbac import Actor, Role, as_role
from services.api.app.errors import ApiError
from services.api.app.security import decode_token

bearer = HTTPBearer(auto_error=False, description="JWT Bearer 令牌")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise ApiError(401, "UNAUTHORIZED", "missing bearer token")
    payload = decode_token(credentials.credentials)
    user = db.get(User, payload.user_id)
    if user is None:
        raise ApiError(401, "UNAUTHORIZED", "unknown user")
    if (user.status or "active") != "active":
        raise ApiError(403, "FORBIDDEN", "user is not active")
    return user


def require_roles(*roles: Role | str) -> Callable[..., User]:
    allowed = {normalized.value for normalized in map(as_role, roles) if normalized}
    if not allowed:
        raise ValueError("require_roles needs at least one known role")

    def dependency(user: User = Depends(get_current_user)) -> User:
        current = as_role(user.role)
        if current is None or current.value not in allowed:
            raise ApiError(403, "FORBIDDEN", "insufficient role")
        return user

    return dependency


def actor_of(user: User) -> Actor:
    return Actor(actor_id=user.id, role=user.role)