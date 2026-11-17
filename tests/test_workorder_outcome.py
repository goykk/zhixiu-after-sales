"""C-TEST@2: 幂等工单、真实结果回收与关闭测试（R17/R18）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from core.db.models import Case, Hypothesis, WorkOrder, new_id, utcnow
from core.policy.idempotency import create_work_order_idempotent
from core.repair.templates import REPAIR_TEMPLATES

API = "/api/v1"
MODEL = "AuroraHome AC-Pro 1200"
CAUSE = "FAN_BLOCKED"

_PROBE_ANSWERS = {
    "ASK_SOUND": "有摩擦或刮擦声",
    "CHECK_ROTATION": "拨动叶片有明显卡滞或阻力",
    "PHOTO_BLADE": "叶片有异物或变形",
}


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


def _approved_case(client, db, seed_base, auth_headers, seed_parts) -> dict:
    technician = seed_base["users"]["technician"]
    device_id = seed_parts["devices"][MODEL].id
    tech_headers = auth_headers(technician.email, seed_base["password"])
    agent_headers = _headers(seed_base, auth_headers, "agent")
    case = _diagnosed_case(db, user_id=technician.id, device_id=device_id)

    planned = client.post(f"{API}/cases/{case.id}/repair-plan", headers=tech_headers)
    assert planned.status_code == 200, planned.text
    submitted = client.post(f"{API}/cases/{case.id}/submit-approval", headers=tech_headers)
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        f"{API}/cases/{case.id}/approvals",
        json={"decision": "approve"},
        headers=agent_headers,
    )
    assert approved.status_code == 200, approved.text
    return {
        "case": case,
        "device_id": device_id,
        "technician": technician,
        "tech_headers": tech_headers,
        "agent_headers": agent_headers,
    }


def _create_order(client, prepared, key: str = "wo-key-1", assignee: str | None = None):
    payload = {"idempotency_key": key}
    if assignee is not None:
        payload["assignee"] = assignee
    return client.post(
        f"{API}/cases/{prepared['case'].id}/work-orders",
        json=payload,
        headers=prepared["agent_headers"],
    )


def _work_order_case(
    db,
    *,
    user_id: str,
    device_id: str,
    assignee: str,
    case_status: str = "WORK_ORDER_CREATED",
    cause: str = CAUSE,
) -> tuple[Case, WorkOrder]:
    case = _diagnosed_case(db, user_id=user_id, device_id=device_id, cause=cause, status=case_status)
    work_order = WorkOrder(
        id=new_id(),
        case_id=case.id,
        idempotency_key=f"test-{new_id()}",
        status="created",
        assignee=assignee,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(work_order)
    db.commit()
    return case, work_order


def test_create_work_order_is_idempotent(client, db, seed_base, seed_parts, auth_headers):
    prepared = _approved_case(client, db, seed_base, auth_headers, seed_parts)
    technician = prepared["technician"]

    first = _create_order(client, prepared, key="wo-key-1", assignee=technician.id)
    assert first.status_code in (200, 201), first.text
    body = first.json()
    assert body["created"] is True
    work_order = body["work_order"]
    assert set(work_order) == {
        "id",
        "case_id",
        "status",
        "assignee",
        "external_id",
        "resolution",
        "created_at",
        "updated_at",
    }
    assert work_order["case_id"] == prepared["case"].id
    assert work_order["assignee"] == technician.id

    repeated = _create_order(client, prepared, key="wo-key-1", assignee=technician.id)
    assert repeated.status_code in (200, 201), repeated.text
    assert repeated.json()["created"] is False
    assert repeated.json()["work_order"]["id"] == work_order["id"]

    db.expire_all()
    db_case = db.get(Case, prepared["case"].id)
    assert db_case.status == "WORK_ORDER_CREATED"
    orders = (
        db.execute(select(WorkOrder).where(WorkOrder.case_id == db_case.id))
        .scalars()
        .all()
    )
    assert len(orders) == 1


def test_create_work_order_requires_approval_and_permission(
    client, db, seed_base, seed_parts, auth_headers
):
    technician = seed_base["users"]["technician"]
    device_id = seed_parts["devices"][MODEL].id
    tech_headers = auth_headers(technician.email, seed_base["password"])
    agent_headers = _headers(seed_base, auth_headers, "agent")

    pending = _diagnosed_case(db, user_id=technician.id, device_id=device_id)
    client.post(f"{API}/cases/{pending.id}/repair-plan", headers=tech_headers)
    client.post(f"{API}/cases/{pending.id}/submit-approval", headers=tech_headers)

    not_approved = client.post(
        f"{API}/cases/{pending.id}/work-orders",
        json={"idempotency_key": "wo-unapproved"},
        headers=agent_headers,
    )
    assert not_approved.status_code == 409
    assert _error_code(not_approved) == "APPROVAL_REQUIRED"

    db.expire_all()
    assert (
        db.execute(select(WorkOrder).where(WorkOrder.case_id == pending.id))
        .scalars()
        .all()
        == []
    )

    missing_key = client.post(
        f"{API}/cases/{pending.id}/work-orders", json={}, headers=agent_headers
    )
    assert missing_key.status_code == 422

    prepared = _approved_case(client, db, seed_base, auth_headers, seed_parts)
    denied = client.post(
        f"{API}/cases/{prepared['case'].id}/work-orders",
        json={"idempotency_key": "wo-forbidden"},
        headers=prepared["tech_headers"],
    )
    assert denied.status_code == 403
    assert _error_code(denied) == "FORBIDDEN"


def test_upstream_failure_via_http(client, db, seed_base, seed_parts, auth_headers):
    from core.tools.mock_backend import (
        MockWorkOrderBackend,
        get_mock_backend,
        set_mock_backend,
    )

    prepared = _approved_case(client, db, seed_base, auth_headers, seed_parts)
    original = get_mock_backend()
    set_mock_backend(MockWorkOrderBackend(fail_times=1))
    try:
        failed = _create_order(client, prepared, key="wo-upstream-http")
    finally:
        set_mock_backend(original)

    assert failed.status_code == 503, failed.text
    assert _error_code(failed) == "UPSTREAM_UNAVAILABLE"

    db.expire_all()
    assert (
        db.execute(
            select(WorkOrder).where(WorkOrder.idempotency_key == "wo-upstream-http")
        )
        .scalars()
        .all()
        == []
    )
    assert db.get(Case, prepared["case"].id).status == "APPROVAL_PENDING"


def test_upstream_failure_leaves_no_work_order(db, seed_base, seed_parts):
    technician = seed_base["users"]["technician"]
    device_id = seed_parts["devices"][MODEL].id
    case = _diagnosed_case(db, user_id=technician.id, device_id=device_id, status="APPROVAL_PENDING")

    def _boom():
        raise RuntimeError("UPSTREAM_UNAVAILABLE")

    with pytest.raises(RuntimeError, match="UPSTREAM_UNAVAILABLE"):
        create_work_order_idempotent(
            db,
            case_id=case.id,
            idempotency_key="wo-upstream-failure",
            factory=_boom,
        )

    db.expire_all()
    assert (
        db.execute(
            select(WorkOrder).where(WorkOrder.idempotency_key == "wo-upstream-failure")
        )
        .scalars()
        .all()
        == []
    )


def test_record_outcome_match_and_immutable(
    client, db, seed_base, seed_parts, auth_headers
):
    technician = seed_base["users"]["technician"]
    device_id = seed_parts["devices"][MODEL].id
    case, work_order = _work_order_case(
        db, user_id=technician.id, device_id=device_id, assignee=technician.id
    )
    tech_headers = auth_headers(technician.email, seed_base["password"])
    prepared_part_no = seed_parts["parts"][MODEL][0]

    payload = {
        "actual_cause_code": CAUSE,
        "action": "on_site",
        "parts_replaced": [prepared_part_no],
        "resolved": True,
        "note": "清理卡阻异物并复位叶片",
    }
    recorded = client.post(
        f"{API}/work-orders/{work_order.id}/outcome", json=payload, headers=tech_headers
    )
    assert recorded.status_code in (200, 201), recorded.text
    body = recorded.json()
    assert body["consistency"] == "match"
    outcome = body["outcome"]
    assert set(outcome) == {
        "id",
        "work_order_id",
        "technician_id",
        "actual_cause_code",
        "action",
        "parts_replaced",
        "resolved",
        "note",
        "created_at",
        "updated_at",
    }
    assert outcome["work_order_id"] == work_order.id
    assert outcome["technician_id"] == technician.id
    assert outcome["parts_replaced"] == payload["parts_replaced"]
    assert outcome["resolved"] is True

    duplicated = client.post(
        f"{API}/work-orders/{work_order.id}/outcome", json=payload, headers=tech_headers
    )
    assert duplicated.status_code == 409
    assert _error_code(duplicated) == "OUTCOME_EXISTS"

    listed = client.get(f"{API}/cases/{case.id}/outcomes", headers=tech_headers)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["items"]) == 1

    db.expire_all()
    assert db.get(Case, case.id).status == "OUTCOME_PENDING"
    assert db.get(WorkOrder, work_order.id).status == "resolved"


def test_record_outcome_mismatch(client, db, seed_base, seed_parts, auth_headers):
    technician = seed_base["users"]["technician"]
    device_id = seed_parts["devices"][MODEL].id
    case, work_order = _work_order_case(
        db, user_id=technician.id, device_id=device_id, assignee=technician.id
    )
    tech_headers = auth_headers(technician.email, seed_base["password"])

    recorded = client.post(
        f"{API}/work-orders/{work_order.id}/outcome",
        json={
            "actual_cause_code": "FAN_DRIVER",
            "action": "replace_part",
            "parts_replaced": [],
            "resolved": False,
        },
        headers=tech_headers,
    )
    assert recorded.status_code in (200, 201), recorded.text
    assert recorded.json()["consistency"] == "mismatch"

    db.expire_all()
    assert db.get(Case, case.id).status == "OUTCOME_PENDING"


def test_outcome_permission_and_state_guards(
    client, db, seed_base, seed_parts, auth_headers
):
    technician = seed_base["users"]["technician"]
    device_id = seed_parts["devices"][MODEL].id
    case, work_order = _work_order_case(
        db, user_id=technician.id, device_id=device_id, assignee=technician.id
    )
    tech_headers = auth_headers(technician.email, seed_base["password"])
    payload = {
        "actual_cause_code": CAUSE,
        "action": "on_site",
        "parts_replaced": [],
        "resolved": True,
    }

    for key in ("agent", "user"):
        denied = client.post(
            f"{API}/work-orders/{work_order.id}/outcome",
            json=payload,
            headers=_headers(seed_base, auth_headers, key),
        )
        assert denied.status_code == 403, (key, denied.text)
        assert _error_code(denied) == "FORBIDDEN"

    missing = client.post(
        f"{API}/work-orders/no-such-work-order/outcome",
        json=payload,
        headers=tech_headers,
    )
    assert missing.status_code == 404

    invalid_state_case, invalid_state_order = _work_order_case(
        db,
        user_id=technician.id,
        device_id=device_id,
        assignee=technician.id,
        case_status="APPROVAL_PENDING",
    )
    conflict = client.post(
        f"{API}/work-orders/{invalid_state_order.id}/outcome",
        json=payload,
        headers=tech_headers,
    )
    assert conflict.status_code == 409
    assert _error_code(conflict) == "ILLEGAL_TRANSITION"

    db.expire_all()
    assert db.get(Case, invalid_state_case.id).status == "APPROVAL_PENDING"


def test_close_case_from_outcome_and_work_order_state(
    client, db, seed_base, seed_parts, auth_headers
):
    technician = seed_base["users"]["technician"]
    device_id = seed_parts["devices"][MODEL].id
    tech_headers = auth_headers(technician.email, seed_base["password"])

    case, work_order = _work_order_case(
        db, user_id=technician.id, device_id=device_id, assignee=technician.id
    )
    client.post(
        f"{API}/work-orders/{work_order.id}/outcome",
        json={
            "actual_cause_code": CAUSE,
            "action": "on_site",
            "parts_replaced": [],
            "resolved": True,
        },
        headers=tech_headers,
    )

    closed = client.post(f"{API}/cases/{case.id}/close", headers=tech_headers)
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"
    assert closed.json()["case"]["status"] == "CLOSED"

    repeated = client.post(f"{API}/cases/{case.id}/close", headers=tech_headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["case"]["status"] == "CLOSED"

    direct_case, _ = _work_order_case(
        db, user_id=technician.id, device_id=device_id, assignee=technician.id
    )
    direct = client.post(f"{API}/cases/{direct_case.id}/close", headers=tech_headers)
    assert direct.status_code == 200, direct.text
    assert direct.json()["case"]["status"] == "CLOSED"

    # DRAFT 本身允许 CLOSED，选 DIAGNOSED 才构成非法关闭
    undecided = _diagnosed_case(
        db, user_id=technician.id, device_id=device_id, status="DIAGNOSED"
    )
    illegal = client.post(f"{API}/cases/{undecided.id}/close", headers=tech_headers)
    assert illegal.status_code == 409
    assert _error_code(illegal) == "ILLEGAL_TRANSITION"


def test_full_closure_http_flow(client, db, seed_base, seed_parts, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    agent_headers = _headers(seed_base, auth_headers, "agent")
    technician = seed_base["users"]["technician"]
    tech_headers = auth_headers(technician.email, seed_base["password"])

    created = client.post(
        f"{API}/cases",
        json={"device_model": MODEL, "symptom": "风扇异响", "error_code": "E106"},
        headers=user_headers,
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]

    intake = client.post(
        f"{API}/cases/{case_id}/intake",
        json={"user_text": "故障现象: 风扇转动时有摩擦异响"},
        headers=user_headers,
    )
    assert intake.status_code == 200, intake.text

    for quote in ("风扇叶片有异物卡阻", "风扇区域有摩擦异响"):
        evidence = client.post(
            f"{API}/cases/{case_id}/evidence",
            json={"source_type": "customer", "polarity": "support", "quote": quote},
            headers=user_headers,
        )
        assert evidence.status_code == 201, evidence.text

    generated = client.post(f"{API}/cases/{case_id}/hypotheses/generate", headers=user_headers)
    assert generated.status_code == 200, generated.text

    for _ in range(8):
        planned = client.post(f"{API}/cases/{case_id}/probes/plan", headers=user_headers)
        assert planned.status_code == 200, planned.text
        card = planned.json()["probe"]
        if card is None:
            break
        answered = client.post(
            f"{API}/cases/{case_id}/probes/{card['probe_id']}/result",
            json={"observed_value": _PROBE_ANSWERS[card["code"]]},
            headers=user_headers,
        )
        assert answered.status_code == 200, answered.text

    finalized = client.post(f"{API}/cases/{case_id}/finalize-diagnosis", headers=agent_headers)
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["case_status"] == "DIAGNOSED"
    assert finalized.json()["root_cause"]["cause_code"] == CAUSE

    plan = client.post(f"{API}/cases/{case_id}/repair-plan", headers=agent_headers)
    assert plan.status_code == 200, plan.text
    assert plan.json()["recommended"] is not None

    submitted = client.post(f"{API}/cases/{case_id}/submit-approval", headers=agent_headers)
    assert submitted.status_code == 200, submitted.text

    approved = client.post(
        f"{API}/cases/{case_id}/approvals",
        json={"decision": "approve"},
        headers=agent_headers,
    )
    assert approved.status_code == 200, approved.text

    payload = {"idempotency_key": "full-closure-1", "assignee": technician.id}
    first_order = client.post(
        f"{API}/cases/{case_id}/work-orders", json=payload, headers=agent_headers
    )
    assert first_order.status_code in (200, 201), first_order.text
    work_order = first_order.json()["work_order"]
    assert first_order.json()["created"] is True

    second_order = client.post(
        f"{API}/cases/{case_id}/work-orders", json=payload, headers=agent_headers
    )
    assert second_order.status_code in (200, 201), second_order.text
    assert second_order.json()["created"] is False
    assert second_order.json()["work_order"]["id"] == work_order["id"]

    fetched = client.get(f"{API}/work-orders/{work_order['id']}", headers=agent_headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["case_id"] == case_id

    recorded = client.post(
        f"{API}/work-orders/{work_order['id']}/outcome",
        json={
            "actual_cause_code": CAUSE,
            "action": "on_site",
            "parts_replaced": [],
            "resolved": True,
            "note": "清理异物后恢复",
        },
        headers=tech_headers,
    )
    assert recorded.status_code in (200, 201), recorded.text
    assert recorded.json()["consistency"] == "match"

    closed = client.post(f"{API}/cases/{case_id}/close", headers=agent_headers)
    assert closed.status_code == 200, closed.text
    assert closed.json()["case"]["status"] == "CLOSED"

    detail = client.get(f"{API}/cases/{case_id}", headers=user_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["case"]["status"] == "CLOSED"