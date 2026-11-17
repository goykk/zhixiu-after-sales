"""评测运行接口：列出历史运行、查询单次运行、同步触发一次 holdout 消融（C-EVAL-API@1）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import get_db
from core.db.models import EvalRunRecord, User
from core.policy.rbac import EVAL_READ, EVAL_RUN, can
from core.simulator.runner import run_ablation, save_eval_run
from core.tasks.dispatch import dispatch
from core.tasks.handlers import run_ablation_handler
from services.api.app.api.routes.tasks import (
    TASK_RUN_ABLATION,
    TaskAcceptedOut,
    async_enabled,
)
from services.api.app.deps import get_current_user
from services.api.app.errors import ApiError

router = APIRouter(tags=["eval"])

DATASET_PATH = "data/scenarios/v1/scenarios.json"
DEFAULT_SPLIT = "holdout"
DEFAULT_LIMIT = 20
MAX_LIMIT = 20
STRATEGY_CHOICES = ("A", "B", "C", "D")


class EvalRunSummary(BaseModel):
    run_id: str
    dataset_version: str
    split: str
    strategies: list[str]
    passed: bool
    gate: dict[str, Any]
    created_at: datetime


class EvalRunDetail(EvalRunSummary):
    metrics: dict[str, Any]
    failed_cases: list[dict[str, Any]]
    report_paths: dict[str, Any]


class EvalRunListOut(BaseModel):
    items: list[EvalRunSummary]


class EvalRunTriggeredOut(BaseModel):
    run_id: str
    passed: bool
    gate: dict[str, Any]
    metrics: dict[str, Any]
    report_paths: dict[str, Any]


class RunCreate(BaseModel):
    split: Literal["holdout", "train", "all"] = DEFAULT_SPLIT
    limit: int = DEFAULT_LIMIT
    strategies: list[str] = Field(default_factory=lambda: list(STRATEGY_CHOICES))


def _require(user: User, action: str) -> None:
    if not can(user.role, action):
        raise ApiError(403, "FORBIDDEN", f"insufficient permission: {action}")


def _summary(record: EvalRunRecord) -> EvalRunSummary:
    return EvalRunSummary(
        run_id=record.run_id,
        dataset_version=record.dataset_version,
        split=record.split,
        strategies=[str(name) for name in record.strategies or []],
        passed=bool(record.passed),
        gate=dict(record.gate or {}),
        created_at=record.created_at,
    )


def _find_run(db: Session, run_id: str) -> EvalRunRecord:
    record = db.execute(
        select(EvalRunRecord).where(EvalRunRecord.run_id == run_id)
    ).scalar_one_or_none()
    if record is None:
        raise ApiError(404, "RUN_NOT_FOUND", f"run not found: {run_id}")
    return record


def _failed_cases(report_paths: dict[str, Any]) -> list[dict[str, Any]]:
    """失败案例只存于报告文件；文件缺失或损坏时返回空列表，不影响详情查询。"""
    path = report_paths.get("json")
    if not path:
        return []
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cases = payload.get("failed_cases")
    return [case for case in cases if isinstance(case, dict)] if isinstance(cases, list) else []


def _normalize_strategies(strategies: list[str]) -> list[str]:
    selected: list[str] = []
    for item in strategies:
        name = str(item).strip().upper()
        if name not in STRATEGY_CHOICES:
            raise ApiError(
                422, "VALIDATION_ERROR", f"未知策略 {item!r}，可选值：{','.join(STRATEGY_CHOICES)}"
            )
        if name not in selected:
            selected.append(name)
    if not selected:
        raise ApiError(
            422, "VALIDATION_ERROR", f"strategies 不能为空，可选值：{','.join(STRATEGY_CHOICES)}"
        )
    return selected


@router.get("/eval/scenarios/runs", response_model=EvalRunListOut)
def list_eval_runs(
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EvalRunListOut:
    _require(user, EVAL_READ)
    rows = db.execute(
        select(EvalRunRecord)
        .order_by(EvalRunRecord.created_at.desc(), EvalRunRecord.run_id.desc())
        .limit(limit)
    ).scalars().all()
    return EvalRunListOut(items=[_summary(row) for row in rows])


@router.get("/eval/scenarios/runs/{run_id}", response_model=EvalRunDetail)
def get_eval_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EvalRunDetail:
    _require(user, EVAL_READ)
    record = _find_run(db, run_id)
    report_paths = dict(record.report_paths or {})
    return EvalRunDetail(
        **_summary(record).model_dump(),
        metrics=dict(record.metrics or {}),
        failed_cases=_failed_cases(report_paths),
        report_paths=report_paths,
    )


@router.post(
    "/eval/scenarios/run",
    status_code=201,
    response_model=EvalRunTriggeredOut | TaskAcceptedOut,
)
def trigger_eval_run(
    payload: RunCreate,
    response: Response,
    async_: bool = Query(False, alias="async"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EvalRunTriggeredOut | TaskAcceptedOut:
    _require(user, EVAL_RUN)
    if payload.limit < 1 or payload.limit > MAX_LIMIT:
        raise ApiError(422, "LIMIT_EXCEEDED", f"limit 必须在 1–{MAX_LIMIT} 之间")
    strategies = _normalize_strategies(payload.strategies)
    if async_enabled(async_, endpoint="eval.scenarios.run"):
        info = dispatch(
            TASK_RUN_ABLATION,
            {
                "dataset_path": DATASET_PATH,
                "split": payload.split,
                "limit": payload.limit,
                "strategies": strategies,
            },
            owner_id=user.id,
            sync_handler=lambda: run_ablation_handler(
                db,
                dataset_path=DATASET_PATH,
                split=payload.split,
                limit=payload.limit,
                strategies=strategies,
            ),
        )
        if info.status == "PENDING":
            response.status_code = 202
            return TaskAcceptedOut(
                task_id=info.task_id, status=info.status, backend=info.backend
            )
        return _triggered_out(info.result or {})
    try:
        report = run_ablation(
            db,
            dataset_path=DATASET_PATH,
            strategies=strategies,
            split=payload.split,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_ERROR", str(exc)) from exc
    # runner 已按 run_id 落库；这里幂等兜底，避免运行器实现差异导致记录缺失
    save_eval_run(db, report)
    return _triggered_out(report)


def _triggered_out(report: dict[str, Any]) -> EvalRunTriggeredOut:
    return EvalRunTriggeredOut(
        run_id=str(report.get("run_id") or ""),
        passed=bool(report.get("passed", False)),
        gate=dict(report.get("gate") or {}),
        metrics=dict(report.get("metrics") or {}),
        report_paths=dict(report.get("report_paths") or {}),
    )