"""异步任务：执行长任务并把状态回写到 TaskStore。"""

from __future__ import annotations

from collections.abc import Callable


from sqlalchemy.orm import Session

from core.db.base import SessionLocal
from core.tasks.handlers import (
    advance_case_handler,
    index_manual_handler,
    run_ablation_handler,
)
from core.tasks.store import get_task_store
from services.worker.celery_app import celery_app


def _execute(task_id: str, handler: Callable[[Session], dict]) -> dict:
    store = get_task_store()
    store.update(task_id, status="STARTED")
    db = SessionLocal()
    try:
        result = handler(db)
    except Exception as exc:
        store.update(task_id, status="FAILURE", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        db.close()
    store.update(task_id, status="SUCCESS", result=result)
    return result


@celery_app.task(name="zhixiu.index_manual")
def index_manual(task_id: str, manual_id: str) -> dict:
    return _execute(task_id, lambda db: index_manual_handler(db, manual_id))


@celery_app.task(name="zhixiu.run_ablation")
def run_ablation(
    task_id: str,
    dataset_path: str,
    split: str,
    limit: int | None = None,
    strategies: list[str] | None = None,
) -> dict:
    def handler(db: Session) -> dict:
        return run_ablation_handler(
            db,
            dataset_path=dataset_path,
            split=split,
            limit=limit,
            strategies=list(strategies or []),
        )

    return _execute(task_id, handler)


@celery_app.task(name="zhixiu.advance_case")
def advance_case(task_id: str, case_id: str) -> dict:
    return _execute(task_id, lambda db: advance_case_handler(db, case_id))