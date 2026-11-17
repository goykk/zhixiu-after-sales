"""认证接口：注册、登录、当前用户与管理员建号。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.base import get_db
from core.db.models import User, new_id, utcnow
from core.policy.rbac import Role, as_role
from services.api.app.deps import get_current_user, require_roles
from services.api.app.errors import ApiError
from services.api.app.security import (
    create_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, _, domain = normalized.partition("@")
        if not local or "." not in domain or domain.startswith("."):
            raise ValueError("invalid email address")
        return normalized


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        return value.strip().lower()


class CreateUserIn(RegisterIn):
    role: str = Field(default=Role.USER.value)

    @field_validator("role")
    @classmethod
    def _check_role(cls, value: str) -> str:
        normalized = as_role(value)
        if normalized is None:
            raise ValueError("unknown role")
        return normalized.value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str | None = None
    role: str
    status: str
    created_at: datetime | None = None


class AuthOut(BaseModel):
    access_token: str
    token: str
    token_type: str = "bearer"
    user: UserOut


def _auth_out(user: User) -> AuthOut:
    token = create_access_token(user.id, user.role)
    return AuthOut(access_token=token, token=token, user=UserOut.model_validate(user))


def _find_user_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email)).scalar_one_or_none()


def _create_user(
    db: Session, *, email: str, password: str, display_name: str | None, role: Role
) -> User:
    if _find_user_by_email(db, email) is not None:
        raise ApiError(409, "EMAIL_EXISTS", "email already registered")
    user = User(
        id=new_id(),
        email=email,
        password_hash=hash_password(password),
        display_name=display_name or email.split("@", 1)[0],
        role=role.value,
        status="active",
        created_at=utcnow(),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "EMAIL_EXISTS", "email already registered") from exc
    db.refresh(user)
    return user


@router.post("/register", response_model=AuthOut, status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> AuthOut:
    user = _create_user(
        db,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        role=Role.USER,
    )
    return _auth_out(user)


@router.post("/login", response_model=AuthOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> AuthOut:
    user = _find_user_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "invalid email or password")
    if (user.status or "active") != "active":
        raise ApiError(403, "FORBIDDEN", "user is not active")
    return _auth_out(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: CreateUserIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> UserOut:
    user = _create_user(
        db,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        role=Role(payload.role),
    )
    return UserOut.model_validate(user)