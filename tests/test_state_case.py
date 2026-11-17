"""状态机、案例创建与受理测试（C-STATE@1 / C-CASE@1）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from core.cases.service import case_out, create_case, get_case, intake, load_case_for_actor
from core.db.models import AuditLog, Case, DiagnosticStep
from core.policy.rbac import Actor
from core.workflow.states import (
    ALLOWED_TRANSITIONS,
    CaseStatus,
    IllegalTransition,
    assert_transition,
)
from services.api.app.errors import ApiError

EXPECTED_EDGES: dict[str, set[str]] = {
    "DRAFT": {"COLLECTING_INFO", "NEED_HUMAN", "CLOSED"},
    "COLLECTING_INFO": {"EVIDENCE_READY", "NEED_HUMAN"},
    "EVIDENCE_READY": {"HYPOTHESIZING", "NEED_HUMAN"},
    "HYPOTHESIZING": {"PROBE_PENDING", "DIAGNOSED", "NEED_HUMAN"},
    "PROBE_PENDING": {"PROBE_EVALUATING", "HYPOTHESIZING", "NEED_HUMAN"},
    "PROBE_EVALUATING": {"HYPOTHESIZING", "PROBE_PENDING", "NEED_HUMAN"},
    "DIAGNOSED": {"REPAIR_PLANNING", "HYPOTHESIZING", "NEED_HUMAN"},
    "REPAIR_PLANNING": {"APPROVAL_PENDING", "NEED_HUMAN"},
    "APPROVAL_PENDING": {"WORK_ORDER_CREATED", "NEED_HUMAN", "CLOSED"},
    "WORK_ORDER_CREATED": {"OUTCOME_PENDING", "CLOSED"},
    "OUTCOME_PENDING": {"CLOSED", "NEED_HUMAN"},
    "NEED_HUMAN": {"HYPOTHESIZING", "APPROVAL_PENDING", "CLOSED"},
    "CLOSED": set(),
}


def _actor(seed_base, key: str = "user") -> Actor:
    user = seed_base["users"][key]
    return Actor(user.id, user.role)


def _new_case(db, seed_base, *, device_model: str = "AC-Pro 1200", error_code: str = "E106"):
    return create_case(
        db,
        user=seed_base["users"]["user"],
        device_model=device_model,
        symptom="风扇异响",
        error_code=error_code,
    )


def _expect_api_error(excinfo: pytest.ExceptionInfo[ApiError], status: int, code: str) -> None:
    assert excinfo.value.status_code == status
    assert excinfo.value.code == code


def test_there_are_exactly_thirteen_states():
    assert {status.value for status in CaseStatus} == set(EXPECTED_EDGES)
    assert len(CaseStatus) == 13


def test_allowed_transitions_match_frozen_matrix():
    for source, expected in EXPECTED_EDGES.items():
        actual = {status.value for status in ALLOWED_TRANSITIONS[CaseStatus(source)]}
        assert actual == expected, source


@pytest.mark.parametrize("source", list(EXPECTED_EDGES))
def test_every_transition_edge_is_enforced(source):
    for target in CaseStatus:
        if target.value in EXPECTED_EDGES[source]:
            assert assert_transition(source, target) is target
        else:
            with pytest.raises(IllegalTransition) as excinfo:
                assert_transition(source, target)
            assert excinfo.value.from_status is CaseStatus(source)
            assert excinfo.value.to_status is target


def test_unknown_status_is_rejected():
    with pytest.raises(IllegalTransition):
        assert_transition("NOT_A_STATUS", CaseStatus.DRAFT)


def test_create_case_binds_device_normalises_error_code_and_audits(db, seed_base):
    case = _new_case(db, seed_base, device_model="ac-pro 1200", error_code="e106")

    assert case.status == CaseStatus.DRAFT.value
    assert case.device_id == seed_base["device"].id
    assert case.error_code == "E106"

    audits = db.execute(select(AuditLog).where(AuditLog.action == "case.created")).scalars().all()
    assert len(audits) == 1
    assert audits[0].resource_id == case.id

    body = case_out(db, case)
    assert body["device_model"] == "AuroraHome AC-Pro 1200"
    assert body["status"] == "DRAFT"
    assert body["missing_fields"] == []
    assert set(body) == {
        "id",
        "user_id",
        "device_id",
        "device_model",
        "status",
        "symptom",
        "error_code",
        "confidence",
        "risk_level",
        "step_count",
        "evidence_version",
        "missing_fields",
        "last_question",
        "created_at",
        "updated_at",
    }


def test_create_case_requires_case_write_permission(db, seed_base):
    with pytest.raises(ApiError) as excinfo:
        create_case(
            db,
            user=seed_base["users"]["technician"],
            device_model="AC-Pro 1200",
            symptom="风扇异响",
        )
    _expect_api_error(excinfo, 403, "FORBIDDEN")


def test_case_lookup_and_access_control(db, seed_base):
    case = _new_case(db, seed_base)

    assert get_case(db, case.id).id == case.id
    with pytest.raises(ApiError) as missing:
        get_case(db, "does-not-exist")
    _expect_api_error(missing, 404, "CASE_NOT_FOUND")

    with pytest.raises(ApiError) as forbidden:
        load_case_for_actor(db, case.id, _actor(seed_base, "technician"))
    _expect_api_error(forbidden, 403, "FORBIDDEN")

    staff_case = load_case_for_actor(db, case.id, _actor(seed_base, "agent"))
    assert staff_case.id == case.id


def test_intake_extracts_fields_and_advances_to_collecting_info(db, seed_base):
    case = _new_case(db, seed_base)

    result = intake(
        db,
        case_id=case.id,
        actor=_actor(seed_base),
        user_text="故障现象: 风扇转动时有摩擦声",
    )

    assert result["needs_human"] is False
    assert result["case"]["status"] == "COLLECTING_INFO"
    assert result["extracted"]["device_model"] == "AC-Pro 1200"
    assert result["extracted"]["symptom"] == "风扇转动时有摩擦声"

    db.expire_all()
    fresh = db.get(Case, case.id)
    assert fresh.status == "COLLECTING_INFO"
    assert fresh.device_id == seed_base["device"].id
    assert fresh.error_code == "E106"

    steps = db.execute(
        select(DiagnosticStep).where(DiagnosticStep.case_id == case.id)
    ).scalars().all()
    assert [step.step_type for step in steps] == ["intake"]
    assert steps[0].output["needs_human"] is False

    audits = db.execute(select(AuditLog).where(AuditLog.action == "case.intake")).scalars().all()
    assert len(audits) == 1


def test_intake_marks_human_when_device_model_unknown(db, seed_base):
    case = _new_case(db, seed_base, device_model="Ghost-9999", error_code="E106")

    result = intake(db, case_id=case.id, actor=_actor(seed_base), user_text="")

    assert result["needs_human"] is True
    assert result["case"]["status"] == "NEED_HUMAN"
    assert "device_model" in result["case"]["missing_fields"]
    assert result["case"]["last_question"]

    db.expire_all()
    fresh = db.get(Case, case.id)
    assert fresh.status == "NEED_HUMAN"
    assert fresh.extracted["needs_human"] is True