"""证据账本与候选根因测试（C-EVIDENCE@1 / C-HYPOTHESIS@1）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from core.cases.service import create_case
from core.db.models import AuditLog, Case, DiagnosticStep, Hypothesis, User, new_id
from core.diagnosis.evidence import add_evidence, list_evidence
from core.diagnosis.hypotheses import (
    GENERAL_RULES,
    apply_evidence,
    confidence_of,
    generate_hypotheses,
    list_hypotheses,
    rules_for,
)
from core.policy.rbac import Actor
from services.api.app.errors import ApiError

FROZEN_E106 = {"FAN_BLOCKED", "FAN_MOTOR", "FAN_DRIVER"}


def _actor(seed_base, key: str = "user") -> Actor:
    user = seed_base["users"][key]
    return Actor(user.id, user.role)


def _new_case(db, seed_base, *, error_code: str = "E106"):
    return create_case(
        db,
        user=seed_base["users"]["user"],
        device_model="AC-Pro 1200",
        symptom="风扇异响",
        error_code=error_code,
    )


def _evidence(
    db,
    seed_base,
    case_id: str,
    *,
    polarity: str = "support",
    quote: str,
    source_type: str = "customer",
):
    return add_evidence(
        db,
        case_id=case_id,
        actor=_actor(seed_base),
        source_type=source_type,
        polarity=polarity,
        quote=quote,
    )


def _expect_api_error(excinfo: pytest.ExceptionInfo[ApiError], status: int, code: str) -> None:
    assert excinfo.value.status_code == status
    assert excinfo.value.code == code


def test_conflicting_evidence_is_preserved_without_overwrite(db, seed_base):
    case = _new_case(db, seed_base)

    support = _evidence(db, seed_base, case.id, polarity="support", quote="风扇叶片有异物卡阻")
    refute = _evidence(db, seed_base, case.id, polarity="refute", quote="风扇叶片有异物卡阻")

    assert support.id != refute.id
    rows = list_evidence(db, case.id)
    assert len(rows) == 2
    assert {row.polarity for row in rows} == {"support", "refute"}

    db.expire_all()
    assert db.get(Case, case.id).status == "EVIDENCE_READY"

    steps = db.execute(
        select(DiagnosticStep).where(DiagnosticStep.case_id == case.id)
    ).scalars().all()
    assert [step.step_type for step in steps] == ["evidence", "evidence"]

    audits = db.execute(
        select(AuditLog).where(AuditLog.action == "evidence.added")
    ).scalars().all()
    assert len(audits) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source_type": "unknown", "polarity": "support", "quote": "有效引用"},
        {"source_type": "customer", "polarity": "unknown", "quote": "有效引用"},
        {"source_type": "customer", "polarity": "support", "quote": "   "},
    ],
)
def test_invalid_evidence_payload_is_rejected(db, seed_base, kwargs):
    case = _new_case(db, seed_base)
    with pytest.raises(ApiError) as excinfo:
        add_evidence(db, case_id=case.id, actor=_actor(seed_base), **kwargs)
    _expect_api_error(excinfo, 422, "INVALID_EVIDENCE")


def test_evidence_requires_case_access(db, seed_base):
    case = _new_case(db, seed_base)
    with pytest.raises(ApiError) as excinfo:
        add_evidence(
            db,
            case_id=case.id,
            actor=_actor(seed_base, "technician"),
            source_type="customer",
            polarity="support",
            quote="风扇叶片有异物",
        )
    _expect_api_error(excinfo, 403, "FORBIDDEN")


def test_state_is_kept_at_evidence_ready_on_repeated_evidence(db, seed_base):
    case = _new_case(db, seed_base)
    _evidence(db, seed_base, case.id, quote="风扇叶片有异物")
    _evidence(db, seed_base, case.id, quote="风扇区域有摩擦异响")

    db.expire_all()
    assert db.get(Case, case.id).status == "EVIDENCE_READY"


@pytest.mark.parametrize(
    ("support", "refute", "expected"),
    [
        (2, 0, ("supported", "high", 0.7)),
        (3, 0, ("supported", "high", 0.95)),
        (1, 0, ("open", "medium", 0.45)),
        (0, 0, ("open", "low", 0.2)),
        (0, 1, ("rejected", "low", 0.0)),
        (1, 2, ("rejected", "low", 0.0)),
        (2, 2, ("open", "low", 0.0)),
    ],
)
def test_confidence_rules(support, refute, expected):
    status, level, score = confidence_of(support, refute)
    assert (status, level) == expected[:2]
    assert score == pytest.approx(expected[2])


def test_rules_for_falls_back_to_general_causes():
    assert {rule.cause_code for rule in rules_for("E106")} == FROZEN_E106
    assert {rule.cause_code for rule in rules_for("e106")} == FROZEN_E106
    fallback = {rule.cause_code for rule in rules_for("E999")}
    assert fallback == {"GENERAL_POWER", "GENERAL_CONTROL"}
    assert fallback == {rule.cause_code for rule in GENERAL_RULES}
    assert {rule.cause_code for rule in rules_for(None)} == fallback


def test_generate_hypotheses_builds_frozen_rule_tree_and_advances_state(db, seed_base):
    case = _new_case(db, seed_base)
    _evidence(db, seed_base, case.id, quote="风扇叶片有异物卡阻")
    _evidence(db, seed_base, case.id, quote="风扇区域有摩擦异响")

    items = generate_hypotheses(db, case_id=case.id, actor=_actor(seed_base))

    assert {item.cause_code for item in items} == FROZEN_E106
    by_code = {item.cause_code: item for item in items}
    assert by_code["FAN_BLOCKED"].status == "supported"
    assert by_code["FAN_BLOCKED"].confidence_level == "high"
    assert by_code["FAN_BLOCKED"].confidence_score == pytest.approx(0.7)
    assert len(by_code["FAN_BLOCKED"].support_evidence_ids) == 2
    assert by_code["FAN_MOTOR"].status == "open"
    assert by_code["FAN_MOTOR"].confidence_level == "low"

    db.expire_all()
    assert db.get(Case, case.id).status == "HYPOTHESIZING"
    steps = db.execute(
        select(DiagnosticStep).where(DiagnosticStep.case_id == case.id)
    ).scalars().all()
    assert "hypotheses_generated" in {step.step_type for step in steps}
    assert (
        db.execute(select(AuditLog).where(AuditLog.action == "hypotheses.generated"))
        .scalars()
        .all()
    )


def test_generate_hypotheses_is_idempotent_per_cause_code(db, seed_base):
    case = _new_case(db, seed_base)
    _evidence(db, seed_base, case.id, quote="风扇叶片有异物卡阻")
    _evidence(db, seed_base, case.id, quote="风扇区域有摩擦异响")

    generate_hypotheses(db, case_id=case.id, actor=_actor(seed_base))
    again = generate_hypotheses(db, case_id=case.id, actor=_actor(seed_base))

    assert len(again) == 3
    stored = db.execute(
        select(Hypothesis).where(Hypothesis.case_id == case.id)
    ).scalars().all()
    assert len(stored) == 3
    assert {row.cause_code for row in stored} == FROZEN_E106
    db.expire_all()
    assert db.get(Case, case.id).status == "HYPOTHESIZING"


def test_generate_hypotheses_requires_evidence_ready_state(db, seed_base):
    case = _new_case(db, seed_base)
    with pytest.raises(ApiError) as excinfo:
        generate_hypotheses(db, case_id=case.id, actor=_actor(seed_base))
    _expect_api_error(excinfo, 409, "ILLEGAL_TRANSITION")


def test_model_source_evidence_is_not_counted(db, seed_base):
    case = _new_case(db, seed_base)
    support = _evidence(db, seed_base, case.id, quote="风扇叶片有异物")
    _evidence(db, seed_base, case.id, quote="风扇叶片有异物，模型推测", source_type="model")

    items = generate_hypotheses(db, case_id=case.id, actor=_actor(seed_base))
    by_code = {item.cause_code: item for item in items}
    assert by_code["FAN_BLOCKED"].support_evidence_ids == [support.id]


def test_apply_evidence_updates_target_hypothesis_and_evidence_version(db, seed_base):
    case = _new_case(db, seed_base)
    _evidence(db, seed_base, case.id, quote="风扇叶片有异物")
    generate_hypotheses(db, case_id=case.id, actor=_actor(seed_base))

    motor = next(
        item for item in list_hypotheses(db, case.id) if item.cause_code == "FAN_MOTOR"
    )
    version_before = motor.evidence_version

    extra = _evidence(db, seed_base, case.id, quote="叶片有异物卡阻")
    affected = apply_evidence(db, case_id=case.id, evidence=extra, cause_codes=["FAN_MOTOR"])

    assert [item.cause_code for item in affected] == ["FAN_MOTOR"]
    assert extra.id in affected[0].support_evidence_ids
    assert affected[0].evidence_version == version_before + 1
    assert affected[0].status == "open"
    assert affected[0].confidence_level == "medium"

    versions = affected[0].evidence_version
    apply_evidence(db, case_id=case.id, evidence=extra, cause_codes=["FAN_MOTOR"])
    assert affected[0].evidence_version == versions
    assert affected[0].support_evidence_ids.count(extra.id) == 1


def test_apply_evidence_matches_open_hypotheses_by_keyword(db, seed_base):
    case = _new_case(db, seed_base)
    _evidence(db, seed_base, case.id, quote="风扇叶片有异物")
    generate_hypotheses(db, case_id=case.id, actor=_actor(seed_base))

    refute = _evidence(db, seed_base, case.id, polarity="refute", quote="电机轴承磨损")
    affected = apply_evidence(db, case_id=case.id, evidence=refute)

    assert [item.cause_code for item in affected] == ["FAN_MOTOR"]
    assert refute.id in affected[0].refute_evidence_ids
    assert affected[0].status == "rejected"
    assert affected[0].confidence_level == "low"


def test_apply_evidence_ignores_neutral_and_model_sources(db, seed_base):
    case = _new_case(db, seed_base)
    _evidence(db, seed_base, case.id, quote="风扇叶片有异物")
    generate_hypotheses(db, case_id=case.id, actor=_actor(seed_base))

    neutral = _evidence(
        db, seed_base, case.id, polarity="neutral", quote="风扇轴承异常"
    )
    model = _evidence(db, seed_base, case.id, quote="风扇轴承异常", source_type="model")

    assert apply_evidence(db, case_id=case.id, evidence=neutral) == []
    assert apply_evidence(db, case_id=case.id, evidence=model) == []


def test_list_hypotheses_sorted_by_confidence_score_desc(db, seed_base):
    case = _new_case(db, seed_base)
    _evidence(db, seed_base, case.id, quote="风扇叶片有异物卡阻")
    _evidence(db, seed_base, case.id, quote="风扇区域有摩擦异响")
    generate_hypotheses(db, case_id=case.id, actor=_actor(seed_base))

    scores = [item.confidence_score for item in list_hypotheses(db, case.id)]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == pytest.approx(0.7)