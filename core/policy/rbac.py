"""V1.2 角色权限矩阵与案例可见性判定。

矩阵来源：design.md §2.2 C-AUTH@1、C-RBAC@2 与 design-eval-ui.md §C C-RBAC@3。
所有权限判定必须经过本模块，业务代码不得自行比较角色字符串。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

CASE_READ_OWN = "case:read_own"
CASE_READ_ALL = "case:read_all"
CASE_WRITE = "case:write"
DEVICE_MANAGE = "device:manage"
MANUAL_MANAGE = "manual:manage"
EVIDENCE_WRITE = "evidence:write"
HYPOTHESIS_WRITE = "hypothesis:write"
PROBE_WRITE = "probe:write"
DIAGNOSIS_FINALIZE = "diagnosis:finalize"
AUDIT_READ = "audit:read"

PART_READ = "part:read"
REPAIR_WRITE = "repair:write"
APPROVAL_DECIDE = "approval:decide"
WORKORDER_CREATE = "workorder:create"
WORKORDER_READ = "workorder:read"
WORKORDER_UPDATE = "workorder:update"
OUTCOME_WRITE = "outcome:write"
OUTCOME_READ = "outcome:read"

EVAL_RUN = "eval:run"
EVAL_READ = "eval:read"


class Role(str, Enum):
    USER = "user"
    AGENT = "agent"
    TECHNICIAN = "technician"
    ADMIN = "admin"


ALL_PERMISSIONS = frozenset(
    {
        CASE_READ_OWN,
        CASE_READ_ALL,
        CASE_WRITE,
        DEVICE_MANAGE,
        MANUAL_MANAGE,
        EVIDENCE_WRITE,
        HYPOTHESIS_WRITE,
        PROBE_WRITE,
        DIAGNOSIS_FINALIZE,
        AUDIT_READ,
        PART_READ,
        REPAIR_WRITE,
        APPROVAL_DECIDE,
        WORKORDER_CREATE,
        WORKORDER_READ,
        WORKORDER_UPDATE,
        OUTCOME_WRITE,
        OUTCOME_READ,
        EVAL_RUN,
        EVAL_READ,
    }
)

PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.USER: frozenset(
        {CASE_READ_OWN, CASE_WRITE, EVIDENCE_WRITE, PROBE_WRITE, PART_READ, OUTCOME_READ}
    ),
    Role.TECHNICIAN: frozenset(
        {
            CASE_READ_OWN,
            EVIDENCE_WRITE,
            PROBE_WRITE,
            PART_READ,
            REPAIR_WRITE,
            WORKORDER_READ,
            WORKORDER_UPDATE,
            OUTCOME_WRITE,
            OUTCOME_READ,
        }
    ),
    Role.AGENT: frozenset(
        {
            CASE_READ_ALL,
            CASE_WRITE,
            DEVICE_MANAGE,
            MANUAL_MANAGE,
            EVIDENCE_WRITE,
            HYPOTHESIS_WRITE,
            PROBE_WRITE,
            DIAGNOSIS_FINALIZE,
            AUDIT_READ,
            PART_READ,
            REPAIR_WRITE,
            APPROVAL_DECIDE,
            WORKORDER_CREATE,
            WORKORDER_READ,
            WORKORDER_UPDATE,
            OUTCOME_READ,
            EVAL_RUN,
            EVAL_READ,
        }
    ),
    Role.ADMIN: ALL_PERMISSIONS,
}


def as_role(role: Role | str | None) -> Role | None:
    """把数据库/令牌中的角色值归一化，未知角色返回 None（视为无权限）。"""
    if isinstance(role, Role):
        return role
    if role is None:
        return None
    try:
        return Role(str(role).strip().lower())
    except ValueError:
        return None


def can(role: Role | str | None, action: str) -> bool:
    normalized = as_role(role)
    if normalized is None:
        return False
    return action in PERMISSIONS[normalized]


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: Role = Role.USER

    def __post_init__(self) -> None:
        normalized = as_role(self.role)
        if normalized is None:
            raise ValueError(f"unknown role: {self.role!r}")
        object.__setattr__(self, "role", normalized)

    @property
    def is_staff(self) -> bool:
        return can(self.role, CASE_READ_ALL)


def can_access_case(
    actor: Actor,
    *,
    case_user_id: str | None,
    assigned_to: str | None = None,
    workorder_assignee: str | None = None,
) -> bool:
    """拥有 `case:read_all` 的角色可读全部案例，其余角色只能读自己或被指派的案例。"""
    if can(actor.role, CASE_READ_ALL):
        return True
    actor_id = actor.actor_id
    if not actor_id:
        return False
    return actor_id in {case_user_id, assigned_to, workorder_assignee}