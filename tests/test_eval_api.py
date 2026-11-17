"""评测 HTTP API 测试（C-TEST@4 / C-EVAL-API@1 / C-RBAC@3）。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from core.db.models import EvalRunRecord, utcnow
from core.policy.rbac import EVAL_READ, EVAL_RUN, can
from services.api.app.config import settings

API = "/api/v1/eval/scenarios"
RUNS = f"{API}/runs"
RUN = f"{API}/run"

_LIST_FIELDS = {
    "run_id",
    "dataset_version",
    "split",
    "strategies",
    "passed",
    "gate",
    "created_at",
}
_DETAIL_FIELDS = {
    "run_id",
    "dataset_version",
    "split",
    "strategies",
    "metrics",
    "gate",
    "passed",
    "failed_cases",
    "report_paths",
    "created_at",
}
_RUN_FIELDS = {"run_id", "passed", "gate", "metrics", "report_paths"}
_SMALL_RUN = {"split": "holdout", "limit": 1, "strategies": ["A"]}


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def _headers(seed_base, auth_headers, key: str) -> dict[str, str]:
    return auth_headers(seed_base["users"][key].email, seed_base["password"])


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "report_dir", str(tmp_path))
    return tmp_path


def _add_record(db, *, run_id: str, created_at, passed: bool = True) -> EvalRunRecord:
    record = EvalRunRecord(
        run_id=run_id,
        dataset_version="v1",
        split="holdout",
        strategies=["A", "B", "C", "D"],
        metrics={"A": {"top3_rate": 1.0}, "C": {"top3_rate": 0.9}},
        gate={"strategy": "C", "checks": {"top3_rate": True}},
        passed=passed,
        report_paths={
            "json": f"data/reports/ablation-v1-{run_id}.json",
            "markdown": f"data/reports/ablation-v1-{run_id}.md",
        },
        created_at=created_at,
    )
    db.add(record)
    db.commit()
    return record


# --------------------------------------------------------------------------- #
# 权限
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ["user", "technician"])
def test_eval_endpoints_deny_roles_without_eval_actions(
    client, seed_base, auth_headers, role
):
    headers = _headers(seed_base, auth_headers, role)

    requests = (
        client.get(RUNS, headers=headers),
        client.get(f"{RUNS}/some-run", headers=headers),
        client.post(RUN, json=_SMALL_RUN, headers=headers),
    )
    for response in requests:
        assert response.status_code == 403, response.text
        assert _error_code(response) == "FORBIDDEN"


def test_eval_endpoints_require_authentication(client):
    for response in (
        client.get(RUNS),
        client.get(f"{RUNS}/some-run"),
        client.post(RUN, json=_SMALL_RUN),
    ):
        assert response.status_code == 401
        assert _error_code(response) == "UNAUTHORIZED"


def test_rbac_grants_eval_actions_to_staff_only():
    assert EVAL_RUN == "eval:run"
    assert EVAL_READ == "eval:read"
    assert can("agent", EVAL_RUN) is True
    assert can("agent", EVAL_READ) is True
    assert can("admin", EVAL_RUN) is True
    assert can("admin", EVAL_READ) is True
    for role in ("user", "technician"):
        assert can(role, EVAL_RUN) is False, role
        assert can(role, EVAL_READ) is False, role
    assert can("agent", "eval:unknown") is False
    assert can(None, EVAL_READ) is False


# --------------------------------------------------------------------------- #
# 历史运行列表
# --------------------------------------------------------------------------- #


def test_list_runs_returns_summaries_newest_first(client, seed_base, auth_headers, db):
    base = utcnow()
    _add_record(db, run_id="run-older", created_at=base)
    _add_record(db, run_id="run-middle", created_at=base + timedelta(minutes=1))
    _add_record(db, run_id="run-newest", created_at=base + timedelta(minutes=2), passed=False)

    for key in ("agent", "admin"):
        headers = _headers(seed_base, auth_headers, key)
        response = client.get(RUNS, headers=headers)
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert [item["run_id"] for item in items] == [
            "run-newest",
            "run-middle",
            "run-older",
        ]
        for item in items:
            assert set(item) == _LIST_FIELDS
        assert items[0]["passed"] is False

    limited = client.get(
        RUNS, params={"limit": 2}, headers=_headers(seed_base, auth_headers, "agent")
    )
    assert limited.status_code == 200
    assert [item["run_id"] for item in limited.json()["items"]] == [
        "run-newest",
        "run-middle",
    ]


# --------------------------------------------------------------------------- #
# 运行详情
# --------------------------------------------------------------------------- #


def test_run_detail_returns_full_record_and_404(client, seed_base, auth_headers, report_dir):
    headers = _headers(seed_base, auth_headers, "agent")
    created = client.post(RUN, json=_SMALL_RUN, headers=headers)
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    detail = client.get(f"{RUNS}/{run_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert set(body) == _DETAIL_FIELDS
    assert body["run_id"] == run_id
    assert body["dataset_version"] == "v1"
    assert body["split"] == "holdout"
    assert body["strategies"] == ["A"]
    assert isinstance(body["metrics"]["A"], dict)
    assert isinstance(body["failed_cases"], list)
    assert isinstance(body["gate"], dict)
    assert body["passed"] is created.json()["passed"]

    missing = client.get(f"{RUNS}/does-not-exist", headers=headers)
    assert missing.status_code == 404
    assert _error_code(missing) == "RUN_NOT_FOUND"


# --------------------------------------------------------------------------- #
# 触发一次消融
# --------------------------------------------------------------------------- #


def test_trigger_run_persists_record_and_report_files(
    client, seed_base, auth_headers, db, report_dir
):
    headers = _headers(seed_base, auth_headers, "agent")
    response = client.post(RUN, json=_SMALL_RUN, headers=headers)
    assert response.status_code == 201, response.text

    body = response.json()
    assert set(body) == _RUN_FIELDS
    run_id = body["run_id"]
    assert body["gate"]["strategy"] == "C"
    assert body["passed"] is all(body["gate"]["checks"].values())
    assert set(body["metrics"]) == {"A"}

    json_path = Path(body["report_paths"]["json"])
    markdown_path = Path(body["report_paths"]["markdown"])
    assert json_path.is_file()
    assert markdown_path.is_file()
    assert json_path.parent == report_dir
    assert markdown_path.parent == report_dir

    db.expire_all()
    rows = db.scalars(select(EvalRunRecord).where(EvalRunRecord.run_id == run_id)).all()
    assert len(rows) == 1
    record = rows[0]
    assert record.dataset_version == "v1"
    assert record.split == "holdout"
    assert record.strategies == ["A"]
    assert record.passed == body["passed"]
    assert record.gate == body["gate"]
    assert record.metrics == body["metrics"]
    assert record.report_paths == body["report_paths"]
    assert record.created_at is not None


def test_trigger_run_rejects_limit_above_range(client, seed_base, auth_headers):
    headers = _headers(seed_base, auth_headers, "agent")

    exceeded = client.post(
        RUN, json={"split": "holdout", "limit": 21, "strategies": ["A"]}, headers=headers
    )
    assert exceeded.status_code == 422
    assert _error_code(exceeded) == "LIMIT_EXCEEDED"

    below_range = client.post(
        RUN, json={"split": "holdout", "limit": 0, "strategies": ["A"]}, headers=headers
    )
    assert below_range.status_code == 422
    assert set(below_range.json()) == {"error"}


def test_trigger_run_is_idempotent_for_same_run_id(
    client, seed_base, auth_headers, db, report_dir, monkeypatch
):
    headers = _headers(seed_base, auth_headers, "agent")
    monkeypatch.setattr("core.simulator.runner._new_run_id", lambda: "fixed-run-0001")

    first = client.post(RUN, json=_SMALL_RUN, headers=headers)
    assert first.status_code == 201, first.text
    second = client.post(RUN, json=_SMALL_RUN, headers=headers)
    assert second.status_code == 201, second.text
    assert second.json()["run_id"] == first.json()["run_id"] == "fixed-run-0001"

    db.expire_all()
    rows = db.scalars(
        select(EvalRunRecord).where(EvalRunRecord.run_id == "fixed-run-0001")
    ).all()
    assert len(rows) == 1