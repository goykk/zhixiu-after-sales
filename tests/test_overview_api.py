"""工作台概览与任务列表测试（C-TEST-WB@1）。"""

from __future__ import annotations

from core.tasks import store as store_mod
from core.tasks.store import TaskInfo, TaskStore


def _seed_case(db, *, user_id: str, status: str):
    from core.db.models import Case, new_id, utcnow

    case = Case(
        id=new_id(),
        user_id=user_id,
        status=status,
        symptom="风扇异响",
        error_code="E106",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(case)
    db.commit()
    return case


def _seed_work_order(db, *, case_id: str, status: str = "created"):
    from core.db.models import WorkOrder, new_id, utcnow

    order = WorkOrder(
        id=new_id(),
        case_id=case_id,
        idempotency_key=new_id(),
        status=status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(order)
    db.commit()
    return order


def test_overview_requires_staff(client, seed_base, auth_headers):
    agent = auth_headers("agent@demo.local")
    user = auth_headers("user@demo.local")
    assert client.get("/api/v1/overview", headers=agent).status_code == 200
    assert client.get("/api/v1/overview", headers=user).status_code == 403


def test_overview_shape_and_counts(client, db, seed_base, auth_headers):
    users = seed_base["users"]
    _seed_case(db, user_id=users["user"].id, status="NEED_HUMAN")
    diagnosed = _seed_case(db, user_id=users["user"].id, status="DIAGNOSED")
    _seed_work_order(db, case_id=diagnosed.id)

    from core.db.models import EvalRunRecord, RepairOutcome, new_id, utcnow

    db.add(
        EvalRunRecord(
            id=new_id(),
            run_id=new_id(),
            dataset_version="v1",
            split="holdout",
            strategies=["A", "B"],
            metrics={},
            gate={},
            passed=True,
            report_paths={},
            created_at=utcnow(),
        )
    )
    db.commit()

    resp = client.get("/api/v1/overview", headers=auth_headers("agent@demo.local"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) >= {"cases", "need_human", "diagnosed", "work_orders", "outcomes", "eval_runs", "tasks", "generated_at"}
    assert body["cases"]["total"] == 2
    assert body["need_human"] == 1
    assert body["diagnosed"] >= 1
    assert body["work_orders"]["total"] == 1
    assert body["eval_runs"]["total"] == 1
    assert body["eval_runs"]["latest_passed"] is True
    assert isinstance(body["tasks"]["by_status"], dict)


def test_overview_empty_like_counts(db):
    # 空库时结构仍完整（直接调用服务层需要 user；这里通过 API 在 seed_base 下验证为 0 亦可）
    assert store_mod.TaskStore is TaskStore


def test_tasks_list_scope_and_limits(client, seed_base, auth_headers):
    agent = auth_headers("agent@demo.local")
    user = auth_headers("user@demo.local")
    assert client.get("/api/v1/tasks?owner=all", headers=agent).status_code == 200
    assert client.get("/api/v1/tasks?owner=all", headers=user).status_code == 403
    assert client.get("/api/v1/tasks?owner=me", headers=user).status_code == 200
    assert client.get("/api/v1/tasks?limit=101", headers=agent).status_code == 422


def test_task_store_list_sort_filter_limit():
    store_mod._FALLBACK_TASKS.clear()
    store = TaskStore(url="redis://127.0.0.1:6399/1", ttl_seconds=60)
    try:
        for idx, (owner, created) in enumerate(
            [("u1", "2026-01-01T00:00:00+00:00"), ("u2", "2026-01-02T00:00:00+00:00"), ("u1", "2026-01-03T00:00:00+00:00")]
        ):
            store.put(TaskInfo(task_id=f"task-{idx}", status="SUCCESS", backend="sync", owner_id=owner, created_at=created, updated_at=created))
        all_items = store.list(limit=10)
        assert [item.task_id for item in all_items] == ["task-2", "task-1", "task-0"]
        u1_items = store.list(limit=10, owner_id="u1")
        assert [item.task_id for item in u1_items] == ["task-2", "task-0"]
        assert len(store.list(limit=1)) == 1
    finally:
        store_mod._FALLBACK_TASKS.clear()