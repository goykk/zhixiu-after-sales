"""受控工具网关：白名单工具、参数校验、越权与幂等/审批前置校验。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from core.db.models import WorkOrder
from core.devices import get_device_profile
from core.policy.rbac import (
    PART_READ,
    WORKORDER_CREATE,
    WORKORDER_READ,
    Actor,
    can,
)

_STATUS_BY_CODE = {
    "UNKNOWN_TOOL": 404,
    "INVALID_ARGS": 422,
    "FORBIDDEN": 403,
    "IDEMPOTENCY_KEY_REQUIRED": 422,
    "APPROVAL_REQUIRED": 409,
    "DEVICE_NOT_FOUND": 404,
    "WORK_ORDER_NOT_FOUND": 404,
    "UPSTREAM_UNAVAILABLE": 503,
}


class ToolError(Exception):
    """工具层错误；路由层按 code 转成统一错误体。"""

    def __init__(self, code: str, message: str = "", details: Any = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.details = details
        self.status_code = _STATUS_BY_CODE.get(code, 400)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    required: dict[str, type]
    permission: str


TOOL_SPECS: dict[str, ToolSpec] = {
    "get_device_profile": ToolSpec(
        name="get_device_profile",
        required={"device_id": str},
        permission=PART_READ,
    ),
    "check_part_compatibility": ToolSpec(
        name="check_part_compatibility",
        required={"device_model": str, "part_no": str},
        permission=PART_READ,
    ),
    "create_work_order": ToolSpec(
        name="create_work_order",
        required={"case_id": str},
        permission=WORKORDER_CREATE,
    ),
    "get_work_order_status": ToolSpec(
        name="get_work_order_status",
        required={"work_order_id": str},
        permission=WORKORDER_READ,
    ),
}


class ToolGateway:
    def __init__(self, db: Any, tracer: Any = None) -> None:
        self.db = db
        self.tracer = tracer

    def call(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        actor: Actor,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        spec = TOOL_SPECS.get(name)
        if spec is None:
            self._trace("tool.error", tool=name, code="UNKNOWN_TOOL", actor_id=actor.actor_id)
            raise ToolError("UNKNOWN_TOOL", f"unknown tool: {name}")
        payload = dict(args or {})
        try:
            self._check_args(spec, payload)
            if not can(actor.role, spec.permission):
                raise ToolError(
                    "FORBIDDEN", f"role {actor.role.value} cannot call tool {name}"
                )
            if name == "create_work_order" and not str(idempotency_key or "").strip():
                raise ToolError(
                    "IDEMPOTENCY_KEY_REQUIRED", "create_work_order requires idempotency_key"
                )
            result = self._dispatch(name, payload, actor, idempotency_key)
        except ToolError as exc:
            self._trace("tool.error", tool=name, code=exc.code, actor_id=actor.actor_id)
            raise
        self._trace("tool.result", tool=name, actor_id=actor.actor_id)
        return result

    def _check_args(self, spec: ToolSpec, args: dict[str, Any]) -> None:
        for key, expected in spec.required.items():
            if key not in args or args[key] is None:
                raise ToolError(
                    "INVALID_ARGS", f"missing argument: {key}", {"missing": [key]}
                )
            value = args[key]
            if expected is str:
                if not isinstance(value, str) or not value.strip():
                    raise ToolError(
                        "INVALID_ARGS", f"argument {key} must be a non-empty string"
                    )
            elif expected is int:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ToolError("INVALID_ARGS", f"argument {key} must be an integer")
            elif not isinstance(value, expected):
                raise ToolError(
                    "INVALID_ARGS", f"argument {key} must be {expected.__name__}"
                )

    def _dispatch(
        self,
        name: str,
        args: dict[str, Any],
        actor: Actor,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        # 延迟导入：工具执行时才加载配件/工单模块，避免网关与业务模块互相静态依赖
        if name == "get_device_profile":
            profile = get_device_profile(self.db, args["device_id"].strip())
            if profile is None:
                raise ToolError("DEVICE_NOT_FOUND", "device profile not found")
            return asdict(profile)

        if name == "check_part_compatibility":
            from core.parts.compatibility import check_part_compatibility

            result = check_part_compatibility(
                self.db,
                device_model=args["device_model"].strip(),
                part_no=args["part_no"].strip(),
                hardware_version=str(args.get("hardware_version") or ""),
            )
            return asdict(result)

        from core.tools.workorder_tool import create_work_order, work_order_out

        if name == "create_work_order":
            work_order, created = create_work_order(
                self.db,
                case_id=args["case_id"].strip(),
                actor=actor,
                idempotency_key=str(idempotency_key or ""),
                assignee=args.get("assignee"),
            )
            return {"work_order": work_order_out(work_order), "created": created}

        work_order = self.db.get(WorkOrder, args["work_order_id"].strip())
        if work_order is None:
            raise ToolError("WORK_ORDER_NOT_FOUND", "work order not found")
        return work_order_out(work_order)

    def _trace(self, event: str, **fields: Any) -> None:
        if self.tracer is None:
            return
        try:
            self.tracer.emit(event, **fields)
        except Exception:  # 追踪失败不得影响工具调用本身
            return