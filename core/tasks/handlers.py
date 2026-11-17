"""长任务的领域执行体：Celery 任务与同步回退共用同一份逻辑。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.rag.indexer import ManualIndexer
from core.simulator.runner import run_ablation
from core.workflow.engine_factory import get_engine


def index_manual_handler(db: Session, manual_id: str) -> dict:
    result = ManualIndexer(db).index_manual(manual_id)
    return {
        "manual_id": result.manual_id,
        "chunk_count": result.chunk_count,
        "status": result.status,
        "error": result.error,
    }


def run_ablation_handler(
    db: Session,
    *,
    dataset_path: str,
    split: str,
    limit: int | None,
    strategies: list[str],
) -> dict:
    report: dict[str, Any] = run_ablation(
        db,
        dataset_path=dataset_path,
        split=split,
        limit=limit,
        strategies=strategies,
    )
    return {
        "run_id": report.get("run_id"),
        "passed": report.get("passed"),
        "metrics": report.get("metrics"),
        "report_paths": report.get("report_paths"),
    }


def advance_case_handler(db: Session, case_id: str) -> dict:
    return get_engine(db).advance(case_id)