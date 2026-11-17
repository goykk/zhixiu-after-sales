"""检查过滤、评分、去重与结果回写测试（C-PROBE@1）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from core.cases.service import create_case
from core.db.models import AuditLog, Case, DiagnosticStep, Evidence, Probe, ProbeResult
from core.diagnosis.evidence import add_evidence
from core.diagnosis.hypotheses import generate_hypotheses, list_hypotheses
from core.policy.rbac import Actor
from core.probes.catalog import PROBE_CATALOG
from core.probes.planner import list_probes, plan_next_probe, probe_card, record_probe_result
from services.api.app.config import settings
from services.api.app.errors import ApiError

_SUPPORT_QUOTES = {
    "E106": ("风扇叶片有异物卡阻", "风扇区域有摩擦异响"),
    "E101": ("电源无输出，电压异常", "空气开关跳闸"),
}

_ANSWERS = {
    "ASK_SOUND": "有摩擦或刮擦声",
    "CHECK_ROTATION": "拨动叶片有明显卡滞或阻力",
    "PHOTO_BLADE": "叶片有异物或变形",
}


def _actor(seed_base, key: str = "user") -> Actor:
    user = seed_base["users"][key]
    return Actor(user.id, user.role)


def _hypothesizing_case(db, seed_base, *, error_code: str = "E106"):
    case = create_case(
        db,
        user=seed_base["users"]["user"],
        device_model="AC-Pro 1200",
        symptom="风扇异响",
        error_code=error_code,
    )
    actor = _actor(seed_base)
    for quote in _SUPPORT_QUOTES[error_code]:
        add_evidence(
            db,
            case_id=case.id,
            actor=actor,
            source_type="customer",
            polarity="support",
            quote=quote,
        )
    generate_hypotheses(db, case_id=case.id, actor=actor)
    return case


def _expect_api_error(excinfo: pytest.ExceptionInfo[ApiError], status: int, code: str) -> None:
    assert excinfo.value.status_code == status
    assert excinfo.value.code == code


def _status_of(db, case_id: str) -> str:
    db.expire_all()
    return db.get(Case, case_id).status


def test_plan_selects_highest_scoring_probe_and_advances_state(db, seed_base):
    case = _hypothesizing_case(db, seed_base)
    probe = plan_next_probe(db, case_id=case.id, actor=_actor(seed_base))

    assert probe is not None
    assert probe.code == "ASK_SOUND"
    assert probe.status == "pending"
    assert probe.score == pytest.approx(3 * 0.85 * 0.8 - 0.1)
    assert set(probe.rationale) == {"why", "alternatives", "targets"}
    assert {"code": "DISASSEMBLE_FAN_CAGE", "reason": "HIGH_RISK"} in probe.rationale[
        "alternatives"
    ]
    assert _status_of(db, case.id) == "PROBE_PENDING"

    steps = db.execute(
        select(DiagnosticStep).where(DiagnosticStep.case_id == case.id)
    ).scalars().all()
    assert "probe_planned" in {step.step_type for step in steps}
    assert (
        db.execute(select(AuditLog).where(AuditLog.action == "probe.planned")).scalars().all()
    )


def test_plan_is_idempotent_while_probe_pending(db, seed_base):
    case = _hypothesizing_case(db, seed_base)
    first = plan_next_probe(db, case_id=case.id, actor=_actor(seed_base))
    again = plan_next_probe(db, case_id=case.id, actor=_actor(seed_base))

    assert again.id == first.id
    assert len(list_probes(db, case.id)) == 1


def test_plan_requires_hypothesizing_or_probe_pending(db, seed_base):
    draft = create_case(
        db,
        user=seed_base["users"]["user"],
        device_model="AC-Pro 1200",
        symptom="风扇异响",
        error_code="E106",
    )
    with pytest.raises(ApiError) as excinfo:
        plan_next_probe(db, case_id=draft.id, actor=_actor(seed_base))
    _expect_api_error(excinfo, 409, "ILLEGAL_TRANSITION")

    evidence_ready = create_case(
        db,
        user=seed_base["users"]["user"],
        device_model="AC-Pro 1200",
        symptom="风扇异响",
        error_code="E106",
    )
    add_evidence(
        db,
        case_id=evidence_ready.id,
        actor=_actor(seed_base),
        source_type="customer",
        polarity="support",
        quote="风扇叶片有异物",
    )
    with pytest.raises(ApiError) as excinfo:
        plan_next_probe(db, case_id=evidence_ready.id, actor=_actor(seed_base))
    _expect_api_error(excinfo, 409, "ILLEGAL_TRANSITION")


def test_record_probe_result_writes_evidence_and_updates_hypotheses(db, seed_base):
    case = _hypothesizing_case(db, seed_base)
    probe = plan_next_probe(db, case_id=case.id, actor=_actor(seed_base))

    result = record_probe_result(
        db,
        case_id=case.id,
        probe_id=probe.id,
        observed_value="有摩擦或刮擦声",
        source_ref="tech-1",
        actor=_actor(seed_base, "agent"),
    )

    assert result["case_status"] == "HYPOTHESIZING"
    assert result["needs_human"] is False
    assert result["probe"]["status"] == "done"
    hypotheses = {item["cause_code"]: item for item in result["hypotheses"]}
    assert hypotheses["FAN_BLOCKED"]["confidence_level"] == "high"
    assert len(hypotheses["FAN_BLOCKED"]["support_evidence_ids"]) == 3

    db.expire_all()
    evidence = db.execute(
        select(Evidence).where(Evidence.case_id == case.id, Evidence.source_type == "probe")
    ).scalar_one()
    assert evidence.polarity == "support"
    assert evidence.source_ref == probe.id
    assert "→" in evidence.quote
    assert db.execute(
        select(ProbeResult).where(ProbeResult.probe_id == probe.id)
    ).scalar_one().observed_value == "有摩擦或刮擦声"

    fresh = db.get(Case, case.id)
    assert fresh.step_count == 1
    assert fresh.evidence_version == 1


def test_record_probe_result_rejects_invalid_observation_and_duplicate(db, seed_base):
    case = _hypothesizing_case(db, seed_base)
    probe = plan_next_probe(db, case_id=case.id, actor=_actor(seed_base))

    for bad in ("", "不存在的观察值"):
        with pytest.raises(ApiError) as excinfo:
            record_probe_result(
                db,
                case_id=case.id,
                probe_id=probe.id,
                observed_value=bad,
                source_ref=None,
                actor=_actor(seed_base),
            )
        _expect_api_error(excinfo, 422, "INVALID_OBSERVATION")

    record_probe_result(
        db,
        case_id=case.id,
        probe_id=probe.id,
        observed_value="有摩擦或刮擦声",
        source_ref=None,
        actor=_actor(seed_base),
    )
    with pytest.raises(ApiError) as excinfo:
        record_probe_result(
            db,
            case_id=case.id,
            probe_id=probe.id,
            observed_value="有摩擦或刮擦声",
            source_ref=None,
            actor=_actor(seed_base),
        )
    _expect_api_error(excinfo, 409, "PROBE_NOT_PENDING")

    with pytest.raises(ApiError) as excinfo:
        record_probe_result(
            db,
            case_id=case.id,
            probe_id="missing-probe",
            observed_value="有摩擦或刮擦声",
            source_ref=None,
            actor=_actor(seed_base),
        )
    _expect_api_error(excinfo, 404, "NOT_FOUND")


def test_observations_match_ignoring_case_and_whitespace(db, seed_base):
    case = _hypothesizing_case(db, seed_base, error_code="E101")
    probe = plan_next_probe(db, case_id=case.id, actor=_actor(seed_base))
    assert probe.code == "ASK_POWER_LED"

    result = record_probe_result(
        db,
        case_id=case.id,
        probe_id=probe.id,
        observed_value="  指示灯不亮 ",
        source_ref=None,
        actor=_actor(seed_base),
    )
    assert result["probe"]["status"] == "done"


def test_probes_never_repeat_and_exhaust_without_high_risk(db, seed_base):
    case = _hypothesizing_case(db, seed_base)
    codes: list[str] = []

    for _ in range(10):
        probe = plan_next_probe(db, case_id=case.id, actor=_actor(seed_base))
        if probe is None:
            break
        codes.append(probe.code)
        assert probe.risk_level != "high"
        record_probe_result(
            db,
            case_id=case.id,
            probe_id=probe.id,
            observed_value=_ANSWERS[probe.code],
            source_ref=None,
            actor=_actor(seed_base),
        )

    assert codes == ["ASK_SOUND", "CHECK_ROTATION", "PHOTO_BLADE"]
    assert len(set(codes)) == len(codes)
    assert _status_of(db, case.id) == "HYPOTHESIZING"

    steps = db.execute(
        select(DiagnosticStep).where(DiagnosticStep.case_id == case.id)
    ).scalars().all()
    assert "probe_exhausted" in {step.step_type for step in steps}
    assert len(list_probes(db, case.id)) == 3


def test_high_risk_and_tool_dependent_probes_are_filtered(db, seed_base):
    case = _hypothesizing_case(db, seed_base, error_code="E101")
    probe = plan_next_probe(db, case_id=case.id, actor=_actor(seed_base))

    assert probe.code == "ASK_POWER_LED"
    reasons = {item["code"]: item["reason"] for item in probe.rationale["alternatives"]}
    assert reasons["MEASURE_LINE_VOLTAGE"] == "HIGH_RISK"
    high_risk_codes = {
        spec.code
        for spec in PROBE_CATALOG["E101"]
        if spec.risk_level == "high"
    }
    assert high_risk_codes == {"MEASURE_LINE_VOLTAGE"}
    assert probe.code not in high_risk_codes


def test_probe_card_exposes_labels_outcomes_and_rationale(db, seed_base):
    case = _hypothesizing_case(db, seed_base)
    probe = plan_next_probe(db, case_id=case.id, actor=_actor(seed_base))

    card = probe_card(probe, list_hypotheses(db, case.id))

    assert set(card) == {
        "probe_id",
        "code",
        "probe_type",
        "question",
        "target_labels",
        "expected_outcomes",
        "cost_level",
        "risk_level",
        "score",
        "rationale",
    }
    assert card["probe_id"] == probe.id
    assert card["target_labels"] == ["风扇卡阻（异物/积尘）", "风扇电机/轴承磨损", "风扇驱动板/供电异常"]
    assert "有摩擦或刮擦声" in card["expected_outcomes"]
    assert card["rationale"]["targets"] == ["FAN_BLOCKED", "FAN_MOTOR", "FAN_DRIVER"]


def test_step_limit_forces_human_handover(db, seed_base, monkeypatch):
    monkeypatch.setattr(settings, "max_probe_steps", 1)
    case = _hypothesizing_case(db, seed_base)
    probe = plan_next_probe(db, case_id=case.id, actor=_actor(seed_base))

    result = record_probe_result(
        db,
        case_id=case.id,
        probe_id=probe.id,
        observed_value="有摩擦或刮擦声",
        source_ref=None,
        actor=_actor(seed_base),
    )

    assert result["needs_human"] is True
    assert result["case_status"] == "NEED_HUMAN"
    db.expire_all()
    assert db.get(Case, case.id).status == "NEED_HUMAN"