"""C-TEST@2: 配件兼容性、维修方案与审批闭环测试（R15/R16/R17）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from core.db.models import Case, DiagnosticStep, Hypothesis, WorkOrder, new_id, utcnow
from core.parts.catalog import PART_CATALOG, find_part, parts_for_model
from core.policy.approval import has_approved
from core.repair.templates import REPAIR_TEMPLATES

API = "/api/v1"
MODEL = "AuroraHome AC-Pro 1200"
CAUSE = "FAN_BLOCKED"


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def _headers(seed_base, auth_headers, key: str) -> dict[str, str]:
    return auth_headers(seed_base["users"][key].email, seed_base["password"])


def _diagnosed_case(
    db,
    *,
    user_id: str,
    device_id: str,
    cause: str = CAUSE,
    status: str = "DIAGNOSED",
) -> Case:
    case = Case(
        id=new_id(),
        user_id=user_id,
        device_id=device_id,
        status=status,
        symptom="风扇异响",
        error_code="E106",
        step_count=0,
        evidence_version=0,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(case)
    db.add(
        Hypothesis(
            id=new_id(),
            case_id=case.id,
            cause_code=cause,
            label="风扇卡阻",
            status="supported",
            confidence_level="high",
            confidence_score=0.9,
            evidence_version=0,
            support_evidence_ids=[],
            refute_evidence_ids=[],
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    db.commit()
    return case


def _build_plan(client, headers, case_id: str):
    return client.post(f"{API}/cases/{case_id}/repair-plan", headers=headers)


def _expected_recommendation(cause: str = CAUSE) -> str:
    return min(
        (option.estimated_cost, option.action)
        for option in REPAIR_TEMPLATES[cause]
    )[1]


def _prepare_planned_case(client, db, seed_base, auth_headers, seed_parts) -> dict:
    technician = seed_base["users"]["technician"]
    device_id = seed_parts["devices"][MODEL].id
    case = _diagnosed_case(db, user_id=technician.id, device_id=device_id)
    headers = auth_headers(technician.email, seed_base["password"])
    plan = _build_plan(client, headers, case.id)
    assert plan.status_code == 200, plan.text
    return {"case": case, "plan": plan.json(), "headers": headers, "device_id": device_id}


def test_part_catalog_covers_demo_models():
    assert len(PART_CATALOG) >= 5
    for device_model, specs in PART_CATALOG.items():
        assert 4 <= len(specs) <= 5, device_model
        main_parts = [spec for spec in specs if not spec.part_no.endswith("-R2")]
        assert len(main_parts) >= 4, device_model
        assert all(spec.device_model == device_model for spec in specs)

    specs = parts_for_model(MODEL)
    assert specs
    assert find_part(MODEL, specs[0].part_no) is not None
    assert parts_for_model("No-Such Model") == []
    assert find_part(MODEL, "NO-SUCH-PART") is None


def test_compatibility_equivalent_replacement_incompatible_unknown(db, seed_parts):
    from core.parts.compatibility import check_part_compatibility

    plain_part = seed_parts["plain"][MODEL]
    substitutable = seed_parts["substitutable"][MODEL]

    equivalent = check_part_compatibility(db, device_model=MODEL, part_no=plain_part)
    assert equivalent.compatible is True
    assert equivalent.compatibility_type == "equivalent"

    replacement = check_part_compatibility(
        db, device_model=MODEL, part_no=substitutable["main"]
    )
    assert replacement.compatible is True
    assert replacement.compatibility_type == "replacement"
    assert substitutable["alternative"] in replacement.alternatives

    incompatible = check_part_compatibility(
        db, device_model=MODEL, part_no=plain_part, hardware_version="HW-99.9"
    )
    assert incompatible.compatible is False
    assert incompatible.compatibility_type == "incompatible"

    unknown_part = check_part_compatibility(db, device_model=MODEL, part_no="NO-SUCH-PART")
    assert unknown_part.compatible is False
    assert unknown_part.compatibility_type == "unknown"

    unknown_model = check_part_compatibility(
        db, device_model="No-Such Model", part_no=plain_part
    )
    assert unknown_model.compatible is False
    assert unknown_model.compatibility_type == "unknown"


def test_explicit_incompatible_relation_degrades_compatibility(db, seed_parts):
    """显式 `incompatible` 兼容关系必须让 check 返回 compatible=False。"""
    from core.db.models import PartCompatibility

    from core.parts.compatibility import check_part_compatibility

    plain_part = seed_parts["plain"][MODEL]
    alternative = seed_parts["substitutable"][MODEL]["alternative"]
    db.add(
        PartCompatibility(
            id=new_id(),
            source_part_no=plain_part,
            target_part_no=alternative,
            compatibility_type="incompatible",
            hardware_range="",
            evidence_source="test-seed",
            created_at=utcnow(),
        )
    )
    db.commit()

    result = check_part_compatibility(db, device_model=MODEL, part_no=plain_part)
    assert result.compatible is False
    assert result.compatibility_type == "incompatible"
    assert alternative not in result.alternatives


def test_parts_http_endpoints(client, seed_base, seed_parts, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    part_nos = seed_parts["parts"][MODEL]
    substitutable = seed_parts["substitutable"][MODEL]

    listed = client.get(f"{API}/parts", params={"device_model": MODEL}, headers=user_headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == len(part_nos)
    assert set(items[0]) == {"part_no", "name", "device_model", "stock_status", "hardware_range"}
    assert {item["part_no"] for item in items} == set(part_nos)
    assert all(item["device_model"] == MODEL for item in items)

    compatible = client.get(
        f"{API}/parts/{substitutable['main']}/compatibility",
        params={"device_model": MODEL},
        headers=user_headers,
    )
    assert compatible.status_code == 200, compatible.text
    body = compatible.json()
    assert set(body) == {
        "part_no",
        "compatible",
        "compatibility_type",
        "evidence_source",
        "stock_status",
        "alternatives",
    }
    assert body["compatible"] is True
    assert substitutable["alternative"] in body["alternatives"]

    unknown = client.get(
        f"{API}/parts/NO-SUCH-PART/compatibility",
        params={"device_model": MODEL},
        headers=user_headers,
    )
    assert unknown.status_code == 200, unknown.text
    assert unknown.json()["compatible"] is False
    assert unknown.json()["compatibility_type"] == "unknown"

    anonymous = client.get(f"{API}/parts", params={"device_model": MODEL})
    assert anonymous.status_code == 401


def test_repair_plan_recommendation_and_idempotency(
    client, db, seed_base, seed_parts, auth_headers
):
    prepared = _prepare_planned_case(client, db, seed_base, auth_headers, seed_parts)
    case = prepared["case"]
    plan = prepared["plan"]

    assert plan["case_id"] == case.id
    assert plan["root_cause_code"] == CAUSE
    assert plan["root_cause_label"]
    assert len(plan["options"]) == len(REPAIR_TEMPLATES[CAUSE])
    assert all(option["parts_compatible"] is True for option in plan["options"])
    assert plan["recommended"] == _expected_recommendation()
    assert isinstance(plan["disclaimers"], list)

    again = _build_plan(client, prepared["headers"], case.id)
    assert again.status_code == 200, again.text
    assert again.json()["recommended"] == plan["recommended"]
    assert again.json()["options"] == plan["options"]

    stored = client.get(f"{API}/cases/{case.id}/repair-plan", headers=prepared["headers"])
    assert stored.status_code == 200, stored.text
    assert stored.json()["recommended"] == plan["recommended"]

    db.expire_all()
    steps = (
        db.execute(
            select(DiagnosticStep).where(
                DiagnosticStep.case_id == case.id,
                DiagnosticStep.step_type == "repair_plan",
            )
        )
        .scalars()
        .all()
    )
    assert len(steps) == 1
    assert db.get(Case, case.id).status == "REPAIR_PLANNING"


def test_repair_plan_degrades_incompatible_parts(
    client, db, seed_base, seed_parts, auth_headers
):
    from core.db.models import Part

    prepared = _prepare_planned_case(client, db, seed_base, auth_headers, seed_parts)
    target = next(
        (
            option
            for option in prepared["plan"]["options"]
            if option["parts"] and option["parts_compatible"]
        ),
        None,
    )
    if target is None:
        pytest.skip("模板中没有含配件的兼容选项")

    for part in target["parts"]:
        part_no = part["part_no"] if isinstance(part, dict) else str(part)
        record = (
            db.execute(
                select(Part).where(
                    Part.device_id == prepared["device_id"],
                    Part.part_no == part_no,
                )
            )
            .scalars()
            .first()
        )
        assert record is not None, part_no
        record.hardware_range = "HW-90.0~HW-99.9"
    db.commit()

    case = _diagnosed_case(
        db,
        user_id=seed_base["users"]["technician"].id,
        device_id=prepared["device_id"],
    )
    headers = prepared["headers"]
    plan = _build_plan(client, headers, case.id)
    assert plan.status_code == 200, plan.text
    body = plan.json()

    degraded = next(
        option for option in body["options"] if option["action"] == target["action"]
    )
    assert degraded["parts_compatible"] is False
    assert body["recommended"] != target["action"]

    still_compatible = [
        option
        for option in body["options"]
        if option["parts_compatible"] and option is not degraded
    ]
    if still_compatible:
        expected = min(
            (option["estimated_cost"], option["action"]) for option in still_compatible
        )[1]
        assert body["recommended"] == expected
    else:
        assert body["recommended"] is None
        assert body["disclaimers"]


def test_repair_plan_requires_diagnosed_state(
    client, db, seed_base, seed_parts, auth_headers
):
    technician = seed_base["users"]["technician"]
    headers = _headers(seed_base, auth_headers, "technician")
    device_id = seed_parts["devices"][MODEL].id

    draft = _diagnosed_case(
        db, user_id=technician.id, device_id=device_id, status="COLLECTING_INFO"
    )
    conflict = _build_plan(client, headers, draft.id)
    assert conflict.status_code == 409
    assert _error_code(conflict) == "ILLEGAL_TRANSITION"

    missing = _build_plan(client, headers, "no-such-case")
    assert missing.status_code == 404

    diagnosed_no_plan = _diagnosed_case(db, user_id=technician.id, device_id=device_id)
    not_found = client.get(
        f"{API}/cases/{diagnosed_no_plan.id}/repair-plan", headers=headers
    )
    assert not_found.status_code == 404
    assert _error_code(not_found) == "REPAIR_PLAN_NOT_FOUND"


def test_assigned_technician_can_access_case_and_plan(
    client, db, seed_base, seed_parts, auth_headers
):
    """被分配工单的 technician 可读取案例并生成维修方案。"""
    user = seed_base["users"]["user"]
    technician = seed_base["users"]["technician"]
    device_id = seed_parts["devices"][MODEL].id
    case = _diagnosed_case(db, user_id=user.id, device_id=device_id)
    db.add(
        WorkOrder(
            id=new_id(),
            case_id=case.id,
            idempotency_key="assigned-technician-case",
            status="created",
            assignee=technician.id,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    db.commit()

    tech_headers = auth_headers(technician.email, seed_base["password"])
    detail = client.get(f"{API}/cases/{case.id}", headers=tech_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["case"]["id"] == case.id

    plan = _build_plan(client, tech_headers, case.id)
    assert plan.status_code == 200, plan.text
    assert plan.json()["case_id"] == case.id
    assert plan.json()["recommended"] is not None


def test_repair_plan_requires_repair_write(
    client, db, seed_base, seed_parts, auth_headers
):
    technician = seed_base["users"]["technician"]
    device_id = seed_parts["devices"][MODEL].id
    case = _diagnosed_case(db, user_id=technician.id, device_id=device_id)
    denied = _build_plan(client, _headers(seed_base, auth_headers, "user"), case.id)
    assert denied.status_code == 403
    assert _error_code(denied) == "FORBIDDEN"


def test_submit_approval_is_idempotent(client, db, seed_base, seed_parts, auth_headers):
    prepared = _prepare_planned_case(client, db, seed_base, auth_headers, seed_parts)
    case_id = prepared["case"].id
    headers = prepared["headers"]

    submitted = client.post(f"{API}/cases/{case_id}/submit-approval", headers=headers)
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["status"] == "APPROVAL_PENDING"
    assert body["case"]["status"] == "APPROVAL_PENDING"

    repeated = client.post(f"{API}/cases/{case_id}/submit-approval", headers=headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["case"]["status"] == "APPROVAL_PENDING"

    approvals = client.get(f"{API}/cases/{case_id}/approvals", headers=headers)
    assert approvals.status_code == 200, approvals.text
    assert approvals.json()["items"] == []

    db.expire_all()
    assert db.get(Case, case_id).status == "APPROVAL_PENDING"


def test_approval_approve_is_idempotent(client, db, seed_base, seed_parts, auth_headers):
    prepared = _prepare_planned_case(client, db, seed_base, auth_headers, seed_parts)
    case_id = prepared["case"].id
    client.post(f"{API}/cases/{case_id}/submit-approval", headers=prepared["headers"])

    agent_headers = _headers(seed_base, auth_headers, "agent")
    decided = client.post(
        f"{API}/cases/{case_id}/approvals",
        json={"decision": "approve", "reason": "方案与配件已确认"},
        headers=agent_headers,
    )
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["case"]["status"] == "APPROVAL_PENDING"
    assert body["approval"]["decision"] == "approve"
    assert body["approval"]["reason"] == "方案与配件已确认"

    repeated = client.post(
        f"{API}/cases/{case_id}/approvals",
        json={"decision": "approve"},
        headers=agent_headers,
    )
    assert repeated.status_code == 200, repeated.text

    listed = client.get(f"{API}/cases/{case_id}/approvals", headers=agent_headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["decision"] == "approve"

    db.expire_all()
    assert has_approved(db, case_id) is True


def test_approval_reject_moves_case_to_need_human(
    client, db, seed_base, seed_parts, auth_headers
):
    prepared = _prepare_planned_case(client, db, seed_base, auth_headers, seed_parts)
    case_id = prepared["case"].id
    client.post(f"{API}/cases/{case_id}/submit-approval", headers=prepared["headers"])

    rejected = client.post(
        f"{API}/cases/{case_id}/approvals",
        json={"decision": "reject", "reason": "现场条件不满足"},
        headers=_headers(seed_base, auth_headers, "agent"),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["case"]["status"] == "NEED_HUMAN"
    assert rejected.json()["approval"]["decision"] == "reject"

    db.expire_all()
    assert db.get(Case, case_id).status == "NEED_HUMAN"
    assert has_approved(db, case_id) is False


def test_approval_permission_and_validation_guards(
    client, db, seed_base, seed_parts, auth_headers
):
    prepared = _prepare_planned_case(client, db, seed_base, auth_headers, seed_parts)
    case_id = prepared["case"].id

    forbidden_submit = client.post(
        f"{API}/cases/{case_id}/submit-approval",
        headers=_headers(seed_base, auth_headers, "user"),
    )
    assert forbidden_submit.status_code == 403
    assert _error_code(forbidden_submit) == "FORBIDDEN"

    early_submit = client.post(
        f"{API}/cases/{case_id}/submit-approval", headers=prepared["headers"]
    )
    assert early_submit.status_code == 200

    forbidden_decide = client.post(
        f"{API}/cases/{case_id}/approvals",
        json={"decision": "approve"},
        headers=prepared["headers"],
    )
    assert forbidden_decide.status_code == 403
    assert _error_code(forbidden_decide) == "FORBIDDEN"

    invalid_decision = client.post(
        f"{API}/cases/{case_id}/approvals",
        json={"decision": "maybe"},
        headers=_headers(seed_base, auth_headers, "agent"),
    )
    assert invalid_decision.status_code == 422

    other = _diagnosed_case(
        db,
        user_id=seed_base["users"]["technician"].id,
        device_id=prepared["device_id"],
    )
    not_planned = client.post(
        f"{API}/cases/{other.id}/submit-approval", headers=prepared["headers"]
    )
    assert not_planned.status_code == 409
    assert _error_code(not_planned) == "ILLEGAL_TRANSITION"