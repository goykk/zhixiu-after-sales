"""C-REPAIR@1: 维修方案生成与持久化。

方案只做“候选 + 推荐 + 免责声明”，不自动下单、不执行维修动作；
配件不兼容只降级方案，不抛错。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from core.cases.service import load_case_for_actor
from core.db.models import AuditLog, DiagnosticStep, Hypothesis, new_id, utcnow
from core.devices import DeviceProfile, get_device_profile
from core.parts.catalog import find_part
from core.parts.compatibility import check_part_compatibility
from core.policy.rbac import Actor, can
from core.repair.templates import REPAIR_TEMPLATES, OptionTemplate
from core.workflow.states import (
    CaseStatus,
    IllegalTransition,
    assert_transition,
    coerce_status,
)
from services.api.app.errors import ApiError

BASE_DISCLAIMERS: tuple[str, ...] = (
    "方案由系统按已确认根因与在库配件生成，不构成维修承诺或报价。",
    "系统不会自动下单或执行维修动作，需经人工审批后由授权维修人员操作。",
)
INCOMPATIBLE_DISCLAIMER = "部分方案包含不兼容或未知配件，已从推荐中排除。"
NO_RECOMMENDATION_DISCLAIMER = (
    "在库配件均未通过兼容性校验，暂无可推荐方案，请联系人工确认配件来源。"
)


@dataclass(frozen=True)
class RepairOption:
    action: str
    label: str
    parts: list[dict[str, Any]] = field(default_factory=list)
    rationale: str = ""
    risk_level: str = "low"
    estimated_cost: float = 0.0
    parts_compatible: bool = True


@dataclass(frozen=True)
class RepairPlan:
    case_id: str
    root_cause_code: str
    root_cause_label: str
    options: list[RepairOption] = field(default_factory=list)
    recommended: str | None = None
    disclaimers: list[str] = field(default_factory=list)


def _as_actor(value: Any) -> Actor:
    if isinstance(value, Actor):
        return value
    actor_id = getattr(value, "actor_id", None) or getattr(value, "id", None)
    return Actor(actor_id, getattr(value, "role", None))


def _write_audit(db: Any, actor: Actor, action: str, resource_id: str, payload: dict) -> None:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8"))
    db.add(
        AuditLog(
            id=new_id(),
            actor_id=actor.actor_id,
            action=action,
            resource_id=resource_id,
            payload_hash=digest.hexdigest(),
            payload=payload,
        )
    )


def _model_name(profile: DeviceProfile | None) -> str:
    if profile is None:
        return ""
    brand = (profile.brand or "").strip()
    model = (profile.model or "").strip()
    if not brand or not model or model.lower().startswith(brand.lower()):
        return model
    return f"{brand} {model}".strip()


def _root_cause(db: Any, case_id: str) -> Hypothesis | None:
    stmt = (
        select(Hypothesis)
        .where(Hypothesis.case_id == case_id, Hypothesis.status == "supported")
        .order_by(Hypothesis.confidence_score.desc(), Hypothesis.cause_code.asc())
    )
    return db.execute(stmt).scalars().first()


def _build_option(
    db: Any,
    template: OptionTemplate,
    *,
    device_model: str,
    hardware_version: str,
) -> RepairOption:
    parts: list[dict[str, Any]] = []
    compatible = True
    for part_no in template.parts:
        result = check_part_compatibility(
            db,
            device_model=device_model,
            part_no=part_no,
            hardware_version=hardware_version,
        )
        spec = find_part(device_model, part_no) if device_model else None
        parts.append(
            {
                "part_no": result.part_no,
                "name": getattr(spec, "name", None),
                "compatible": result.compatible,
                "compatibility_type": result.compatibility_type,
                "stock_status": result.stock_status,
                "alternatives": list(result.alternatives),
            }
        )
        if not result.compatible:
            compatible = False
    return RepairOption(
        action=template.action,
        label=template.label,
        parts=parts,
        rationale=template.rationale,
        risk_level=template.risk_level,
        estimated_cost=template.estimated_cost,
        parts_compatible=compatible,
    )


def _recommend(options: list[RepairOption]) -> str | None:
    candidates = [option for option in options if option.parts_compatible]
    if not candidates:
        return None
    return min(candidates, key=lambda option: (option.estimated_cost, option.action)).action


def repair_plan_out(plan: RepairPlan) -> dict[str, Any]:
    return {
        "case_id": plan.case_id,
        "root_cause_code": plan.root_cause_code,
        "root_cause_label": plan.root_cause_label,
        "options": [
            {
                "action": option.action,
                "label": option.label,
                "parts": [dict(part) for part in option.parts],
                "rationale": option.rationale,
                "risk_level": option.risk_level,
                "estimated_cost": option.estimated_cost,
                "parts_compatible": option.parts_compatible,
            }
            for option in plan.options
        ],
        "recommended": plan.recommended,
        "disclaimers": list(plan.disclaimers),
    }


def _plan_from_output(case_id: str, output: Any) -> RepairPlan | None:
    if not isinstance(output, dict):
        return None
    options = [
        RepairOption(
            action=str(item.get("action") or ""),
            label=str(item.get("label") or ""),
            parts=[dict(part) for part in item.get("parts") or []],
            rationale=str(item.get("rationale") or ""),
            risk_level=str(item.get("risk_level") or "low"),
            estimated_cost=float(item.get("estimated_cost") or 0.0),
            parts_compatible=bool(item.get("parts_compatible", True)),
        )
        for item in output.get("options") or []
        if isinstance(item, dict)
    ]
    root_cause_code = str(output.get("root_cause_code") or "")
    if not root_cause_code:
        return None
    return RepairPlan(
        case_id=case_id,
        root_cause_code=root_cause_code,
        root_cause_label=str(output.get("root_cause_label") or root_cause_code),
        options=options,
        recommended=output.get("recommended"),
        disclaimers=[str(item) for item in output.get("disclaimers") or []],
    )


def latest_repair_plan(db: Any, case_id: str) -> RepairPlan | None:
    stmt = (
        select(DiagnosticStep)
        .where(
            DiagnosticStep.case_id == case_id,
            DiagnosticStep.step_type == "repair_plan",
        )
        .order_by(DiagnosticStep.created_at.desc(), DiagnosticStep.id.desc())
    )
    step = db.execute(stmt).scalars().first()
    if step is None:
        return None
    return _plan_from_output(case_id, step.output)


def _status_of(case: Any) -> CaseStatus:
    try:
        return coerce_status(case.status)
    except ValueError as exc:
        raise ApiError(
            409, "ILLEGAL_TRANSITION", f"unknown case status: {case.status}"
        ) from exc


def build_repair_plan(db: Any, *, case_id: str, actor: Any) -> RepairPlan:
    actor_obj = _as_actor(actor)
    if not can(actor_obj.role, "repair:write"):
        raise ApiError(403, "FORBIDDEN", "repair:write not permitted")

    case = load_case_for_actor(db, case_id, actor_obj)
    status = _status_of(case)

    if status == CaseStatus.REPAIR_PLANNING:
        stored = latest_repair_plan(db, case_id)
        if stored is not None:
            return stored
    elif status != CaseStatus.DIAGNOSED:
        raise ApiError(
            409,
            "ILLEGAL_TRANSITION",
            f"repair plan requires DIAGNOSED, got {case.status}",
        )

    root = _root_cause(db, case_id)
    if root is None:
        raise ApiError(409, "INSUFFICIENT_EVIDENCE", "no supported root cause to plan for")

    templates = REPAIR_TEMPLATES.get(root.cause_code) or REPAIR_TEMPLATES["GENERAL_CONTROL"]
    profile = get_device_profile(db, case.device_id) if case.device_id else None
    device_model = _model_name(profile)
    hardware_version = (getattr(profile, "hardware_version", None) or "").strip()

    options = [
        _build_option(
            db,
            template,
            device_model=device_model,
            hardware_version=hardware_version,
        )
        for template in templates
    ]

    recommended = _recommend(options)
    disclaimers = list(BASE_DISCLAIMERS)
    if any(not option.parts_compatible for option in options):
        disclaimers.append(INCOMPATIBLE_DISCLAIMER)
    if recommended is None:
        disclaimers.append(NO_RECOMMENDATION_DISCLAIMER)

    plan = RepairPlan(
        case_id=case.id,
        root_cause_code=root.cause_code,
        root_cause_label=root.label or root.cause_code,
        options=options,
        recommended=recommended,
        disclaimers=disclaimers,
    )
    plan_dict = repair_plan_out(plan)

    db.add(
        DiagnosticStep(
            id=new_id(),
            case_id=case.id,
            step_type="repair_plan",
            input={
                "root_cause_code": root.cause_code,
                "device_model": device_model,
                "hardware_version": hardware_version,
            },
            output=plan_dict,
        )
    )

    if status == CaseStatus.DIAGNOSED:
        try:
            assert_transition(CaseStatus.DIAGNOSED, CaseStatus.REPAIR_PLANNING)
        except IllegalTransition as exc:
            raise ApiError(409, "ILLEGAL_TRANSITION", str(exc)) from exc
        case.status = CaseStatus.REPAIR_PLANNING.value
    case.updated_at = utcnow()

    _write_audit(
        db,
        actor_obj,
        "case.repair_plan",
        case.id,
        {
            "root_cause_code": root.cause_code,
            "recommended": recommended,
            "option_count": len(options),
            "compatible_options": sum(1 for option in options if option.parts_compatible),
        },
    )
    db.commit()
    return plan