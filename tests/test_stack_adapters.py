"""向量后端与 LangGraph 可选编排适配测试（C-VECTOR@1 / C-LANGGRAPH@1 / C-TEST-STACK@1）。

默认路径（JSON 余弦 + native 编排）必须保持可用；可选路径不可用时回退并留下追踪。
可选依赖相关的符号在用例内延迟导入，避免单个契约未就绪时整文件收集失败。
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.cases.service import create_case
from core.db.models import Case
from core.diagnosis.evidence import add_evidence
from core.diagnosis.hypotheses import generate_hypotheses
from core.diagnosis.orchestrator import finalize_diagnosis
from core.policy.rbac import Actor
from core.probes.planner import plan_next_probe
from services.api.app.config import settings
from services.api.app.errors import ApiError

_ROOT = Path(__file__).resolve().parents[1]
_EVIDENCE_QUOTE = "风扇叶片有异物卡阻"
_LANGGRAPH_STATUSES = {"PROBE_PENDING", "NEED_HUMAN", "DIAGNOSED", "HYPOTHESIZING"}
_TEST_PG_URL = os.getenv("TEST_PG_URL")


def _actor(seed_base, key: str = "user") -> Actor:
    user = seed_base["users"][key]
    return Actor(user.id, user.role)


def _status_of(db, case_id: str) -> str:
    db.expire_all()
    return db.get(Case, case_id).status


def _evidence_ready_case(db, seed_base) -> Case:
    case = create_case(
        db,
        user=seed_base["users"]["user"],
        device_model="AC-Pro 1200",
        symptom="风扇异响",
        error_code="E106",
    )
    add_evidence(
        db,
        case_id=case.id,
        actor=_actor(seed_base),
        source_type="customer",
        polarity="support",
        quote=_EVIDENCE_QUOTE,
    )
    assert _status_of(db, case.id) == "EVIDENCE_READY"
    return case


def _native_status(db, case_id: str, actor: Actor) -> str:
    """native 基线：优先用 `NativeDiagnosisFlow.advance`，否则直接委托 core 服务。"""
    try:
        from core.workflow import engine_factory

        native_flow_cls = getattr(engine_factory, "NativeDiagnosisFlow", None)
    except ModuleNotFoundError:
        native_flow_cls = None
    if native_flow_cls is not None:
        return native_flow_cls(db).advance(case_id)["case_status"]
    return _native_baseline_status(db, case_id, actor)


def _native_baseline_status(db, case_id: str, actor: Actor) -> str:
    """按 native 语义直接委托 core 服务推进，作为 LangGraph 等价性基线。

    无外部输入时 native 流程同样停在等待检查结果处，因此这里只做
    hypotheses → plan_probe，无候选时尝试定案，不伪造检查结果。
    """
    if _status_of(db, case_id) == "EVIDENCE_READY":
        generate_hypotheses(db, case_id=case_id, actor=actor)
    if plan_next_probe(db, case_id=case_id, actor=actor) is not None:
        return _status_of(db, case_id)
    try:
        finalize_diagnosis(db, case_id=case_id, actor=actor)
    except ApiError:
        # 证据不足等停止条件：native 也停原状态，不作为等价性失败。
        pass
    return _status_of(db, case_id)


def _trace_events(trace_dir: Path, event: str) -> list[dict]:
    events: list[dict] = []
    for path in sorted(trace_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("event") == event:
                events.append(record)
    return events


def test_default_vector_backend_is_json_store(db):
    from core.rag.vector_store import JsonVectorStore, get_vector_store

    assert settings.vector_backend == "json"
    assert settings.pgvector_dim > 0
    assert isinstance(get_vector_store(db), JsonVectorStore)


def test_vector_store_alias_is_backward_compatible():
    from core.rag.vector_store import JsonVectorStore, VectorStore

    assert VectorStore is JsonVectorStore


def test_pgvector_backend_falls_back_on_sqlite_and_traces(db, monkeypatch, tmp_path):
    from core.rag.vector_store import JsonVectorStore, PgVectorStore, get_vector_store

    monkeypatch.setattr(settings, "vector_backend", "pgvector")
    monkeypatch.setattr(settings, "trace_dir", str(tmp_path))

    store = get_vector_store(db)

    assert isinstance(store, JsonVectorStore)
    assert not isinstance(store, PgVectorStore)
    events = _trace_events(tmp_path, "vector_backend_fallback")
    assert events, "回退必须产生 vector_backend_fallback 追踪，不得静默降级"
    assert events[-1]["fields"]["requested"] == "pgvector"


def test_pgvector_search_rejects_dimension_mismatch(db):
    from core.rag.vector_store import PgVectorStore

    wrong_dim = [0.1] * (settings.pgvector_dim + 1)

    with pytest.raises(ValueError):
        PgVectorStore(db).search(wrong_dim, filters={}, top_k=3)


class _SentinelStore:
    def __init__(self, results: list[tuple[str, float]]) -> None:
        self._results = results
        self.calls: list[dict] = []

    def search(self, vector, *, filters, top_k):
        self.calls.append({"vector": vector, "filters": filters, "top_k": top_k})
        return list(self._results[:top_k])


def test_version_aware_retriever_uses_configured_vector_store(db, seed_base, monkeypatch):
    from sqlalchemy import select

    from core.db.models import DocumentChunk
    from core.rag import retriever as retriever_module

    chunk = db.scalars(select(DocumentChunk)).first()
    assert chunk is not None, "seed_base 应已索引出切片"
    sentinel = _SentinelStore([(chunk.id, 0.9)])
    monkeypatch.setattr(retriever_module, "get_vector_store", lambda session: sentinel)

    retriever = retriever_module.VersionAwareRetriever(db)

    assert retriever.store is sentinel, "检索器必须持有 get_vector_store 选择的后端"
    items = retriever.retrieve("风扇异响", model="AC-Pro 1200", top_k=3)
    assert sentinel.calls, "检索必须走注入的向量后端，而不是硬编码 JSON 实现"
    assert [item.chunk_id for item in items] == [chunk.id]


class _RecordingBind:
    def __init__(self, dialect_name: str, log: list[str]) -> None:
        self.dialect = SimpleNamespace(name=dialect_name)
        self._log = log

    def execute(self, statement, *args, **kwargs):
        self._log.append(str(statement))
        return None


class _RecordingOp:
    """替代 alembic.op：记录迁移调用，并按给定 dialect 返回假 bind。"""

    def __init__(self, dialect_name: str) -> None:
        self.log: list[str] = []
        self.bind = _RecordingBind(dialect_name, self.log)

    def get_bind(self):
        return self.bind

    def execute(self, statement, *args, **kwargs):
        self.log.append(str(statement))
        return None

    def __getattr__(self, name: str):
        def _record(*args, **kwargs):
            self.log.append(name)
            return self.bind

        return _record


def _load_migration_0004(monkeypatch, dialect_name: str):
    import alembic

    recording = _RecordingOp(dialect_name)
    monkeypatch.setattr(alembic, "op", recording)
    path = _ROOT / "migrations" / "versions" / "0004_pgvector.py"
    spec = importlib.util.spec_from_file_location("migration_0004_pgvector", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, recording


def test_migration_0004_is_noop_on_sqlite(monkeypatch):
    module, recording = _load_migration_0004(monkeypatch, "sqlite")

    assert module.revision == "0004"
    assert module.down_revision == "0003"

    module.upgrade()
    assert recording.log == [], f"SQLite 下 upgrade 必须 no-op，实际调用={recording.log}"

    module.downgrade()
    assert recording.log == [], f"SQLite 下 downgrade 必须 no-op，实际调用={recording.log}"


def test_migration_0004_creates_extension_column_and_index_on_postgresql(monkeypatch):
    module, recording = _load_migration_0004(monkeypatch, "postgresql")

    module.upgrade()
    text = " ".join(recording.log).lower()
    assert "vector" in text
    assert "create extension" in text
    assert "add_column" in text or "add column" in text
    assert "create_index" in text or "create index" in text

    recording.log.clear()
    module.downgrade()
    text = " ".join(recording.log).lower()
    assert "drop" in text
    assert "extension" not in text, "downgrade 不得删除 vector 扩展"


def test_langgraph_available_matches_module_presence():
    from core.workflow import langgraph_adapter

    assert langgraph_adapter.available() == bool(importlib.util.find_spec("langgraph"))


def test_langgraph_advance_matches_native_status(db, seed_base):
    from core.workflow import langgraph_adapter

    if not langgraph_adapter.available():
        pytest.skip("未安装 langgraph，跳过等价性测试")

    system_actor = _actor(seed_base, "agent")
    native_case = _evidence_ready_case(db, seed_base)
    langgraph_case = _evidence_ready_case(db, seed_base)
    native_status = _native_status(db, native_case.id, system_actor)

    result = langgraph_adapter.LangGraphDiagnosisFlow(db).advance(langgraph_case.id)

    assert set(result) >= {"case_status", "root_cause", "steps", "needs_human", "node"}
    assert result["root_cause"] is None or isinstance(result["root_cause"], str)
    assert isinstance(result["steps"], int) and isinstance(result["needs_human"], bool)
    assert native_status in _LANGGRAPH_STATUSES
    assert result["case_status"] == native_status
    assert _status_of(db, langgraph_case.id) == result["case_status"]


def _force_langgraph_available(monkeypatch, value: bool) -> None:
    from core.workflow import engine_factory, langgraph_adapter

    def _unavailable() -> bool:
        return value

    # 适配层可能被 engine_factory 以「模块调用」或「函数导入」两种方式引用，两处都要覆盖。
    monkeypatch.setattr(langgraph_adapter, "available", _unavailable, raising=False)
    monkeypatch.setattr(engine_factory, "available", _unavailable, raising=False)


def test_get_engine_falls_back_to_native_when_langgraph_unavailable(
    db, seed_base, monkeypatch, tmp_path
):
    from core.workflow import engine_factory, langgraph_adapter

    monkeypatch.setattr(settings, "workflow_engine", "langgraph")
    monkeypatch.setattr(settings, "trace_dir", str(tmp_path))
    _force_langgraph_available(monkeypatch, False)

    engine = engine_factory.get_engine(db)

    assert not isinstance(engine, langgraph_adapter.LangGraphDiagnosisFlow)
    native_flow_cls = getattr(engine_factory, "NativeDiagnosisFlow", None)
    if native_flow_cls is not None:
        assert isinstance(engine, native_flow_cls)
    assert callable(getattr(engine, "advance", None))
    events = _trace_events(tmp_path, "workflow_engine_fallback")
    assert events, "回退 native 必须产生 workflow_engine_fallback 追踪"


def test_get_engine_returns_langgraph_flow_when_enabled(db, seed_base, monkeypatch):
    from core.workflow import engine_factory, langgraph_adapter

    if not langgraph_adapter.available():
        pytest.skip("未安装 langgraph")
    monkeypatch.setattr(settings, "workflow_engine", "langgraph")

    engine = engine_factory.get_engine(db)

    assert isinstance(engine, langgraph_adapter.LangGraphDiagnosisFlow)


@pytest.mark.skipif(not _TEST_PG_URL, reason="需要 TEST_PG_URL 指向真实 PostgreSQL 才运行")
def test_pgvector_backend_against_real_postgres(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.rag.vector_store import PgVectorStore, get_vector_store

    engine = create_engine(_TEST_PG_URL, future=True)
    session = sessionmaker(bind=engine, future=True)()
    try:
        monkeypatch.setattr(settings, "vector_backend", "pgvector")
        store = get_vector_store(session)
        assert isinstance(store, PgVectorStore)
        with pytest.raises(ValueError):
            store.search([0.0] * (settings.pgvector_dim + 1), filters={}, top_k=3)
    finally:
        session.close()
        engine.dispose()