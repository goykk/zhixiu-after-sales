# 向量后端与 LangGraph 编排（可选路径）

R22/R23 在既有诊断闭环之上增加两条**可选**技术栈路径，默认行为完全不变：

- 检索默认走 `JsonVectorStore`：向量以 JSON 存 `document_chunks.embedding`，进程内余弦检索。
- 编排默认走 `NativeDiagnosisFlow`：`core/workflow` 的 13 状态确定性状态机。

可选路径只在条件全部满足时启用；条件不满足即回退默认，并写追踪事件，**不允许静默降级**。
两条路径都不改变 REST 契约、不新增必需依赖，SQLite 下的表结构与默认路径完全相同。

## 1. 后端选择规则

`core/rag/vector_store.py::get_vector_store(db)` 的函数级判定：

| `VECTOR_BACKEND` | `db.bind.dialect.name` | `pgvector` 可导入 | 返回 |
| --- | --- | --- | --- |
| `json`（默认） | 任意 | 任意 | `JsonVectorStore` |
| `pgvector` | `postgresql` | 是 | `PgVectorStore` |
| `pgvector` | 非 `postgresql` | 任意 | `JsonVectorStore` + 回退追踪 |
| `pgvector` | `postgresql` | 否 | `JsonVectorStore` + 回退追踪 |

`core/workflow/engine_factory.py::get_engine(db, *, retriever=None, llm=None)` 的判定：

| `WORKFLOW_ENGINE` | `langgraph_adapter.available()` | 返回 |
| --- | --- | --- |
| `native`（默认） | 任意 | `NativeDiagnosisFlow` |
| `langgraph` | 是 | `LangGraphDiagnosisFlow` |
| `langgraph` | 否 | `NativeDiagnosisFlow` + 回退追踪 |

两个实现接口一致：`advance(case_id) -> dict`，调用方通过 `get_engine` 获取，不感知具体实现。

## 2. 两种向量后端

### 2.1 `JsonVectorStore`（默认）

- 读取 `document_chunks.embedding`（JSON 数组），进程内计算余弦相似度，返回 `(chunk_id, score)` 降序列表。
- 保留向后兼容别名：`VectorStore = JsonVectorStore`，既有调用点与导入不变。
- 过滤键与检索语义见 [architecture.md](architecture.md) 与 `core/rag` 现有实现；版本过滤在进程内完成。

### 2.2 `PgVectorStore`（可选）

```python
class PgVectorStore:
    def __init__(self, db: Session): ...
    def search(
        self, vector: list[float], *, filters: dict[str, str], top_k: int
    ) -> list[tuple[str, float]]: ...
```

检索口径：

| 项目 | 规则 |
| --- | --- |
| 取数 | `document_chunks` JOIN `manuals` JOIN `devices`；`WHERE embedding_vec IS NOT NULL` |
| 过滤键 | `model` / `version` / `hardware_version` / `firmware_version`；空值不过滤 |
| 型号 | `model` 大小写不敏感，并支持 `brand + " " + model` 全名 |
| 排序 | `ORDER BY embedding_vec <=> CAST(:vec AS vector)`，`LIMIT :top_k` |
| 分数 | `score = clamp(1 - distance, 0, 1)`，按分数降序返回 |
| 参数绑定 | `vector` 绑定为 `"[v1,v2,...]"` 字符串 |
| 维度 | 必须等于 `settings.pgvector_dim`（默认 `768`），否则抛 `ValueError` |

维度不一致属于调用方错误（Embedding Provider 维度与 `PGVECTOR_DIM` 不匹配），不静默截断或补零。

## 3. 索引写入

`core/rag/indexer.py` 在原有切片写入之后增量补一步：

1. 每个 chunk 写入并 `flush()` 后，若 `settings.vector_backend == "pgvector"` 且方言为 `postgresql`，
   执行 `UPDATE document_chunks SET embedding_vec = CAST(:vec AS vector) WHERE id = :id`。
2. SQLite 路径完全不变（没有该列，也不执行该语句）。
3. 任一步失败沿用既有语义：手册索引状态置 `status="failed"` 并回滚事务，不留下半写 chunk。

因此切换后端后需要**重建索引**（例如重新执行 `python scripts/seed_demo.py`），既有切片不会自动补齐
`embedding_vec`，这也是 `WHERE embedding_vec IS NOT NULL` 存在的意义：未回填的切片不参与 pgvector 检索。

## 4. 迁移 `0004_pgvector`

`migrations/versions/0004_pgvector.py`：`revision="0004"`，`down_revision="0003"`。

| 方言 | upgrade | downgrade |
| --- | --- | --- |
| `postgresql` | `CREATE EXTENSION IF NOT EXISTS vector`；`ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_vec vector(768)`；`CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_vec ON document_chunks USING ivfflat (embedding_vec vector_cosine_ops)` | drop index、drop column（**不删扩展**） |
| 其他（含 SQLite） | no-op | no-op |

执行顺序：

```bash
python scripts/init_db.py     # create_all 建出现有 ORM 表
alembic upgrade head          # PostgreSQL 下补 embedding_vec 列与索引；SQLite 下 0004 为 no-op
```

`init_db.py` 使用 `create_all`，不会建 `embedding_vec`（SQLite 不建该列，PostgreSQL 需要迁移补列），
所以 PostgreSQL 场景必须先执行 `alembic upgrade head` 再写索引。`migrations/env.py` 从
`services.api.app.config.settings.database_url` 取连接串，`alembic.ini` 中不写真实 URL。

## 5. LangGraph 编排

### 5.1 入口

```python
def available() -> bool: ...  # importlib.util.find_spec("langgraph") 是否为真

def get_engine(db, *, retriever=None, llm=None) -> NativeDiagnosisFlow | LangGraphDiagnosisFlow: ...

class LangGraphDiagnosisFlow:
    def __init__(self, db: Session, retriever=None, llm=None): ...
    def advance(self, case_id: str) -> dict: ...
```

`NativeDiagnosisFlow` 由 `core/workflow/engine_factory.py` 提供，`LangGraphDiagnosisFlow` 由
`core/workflow/langgraph_adapter.py` 提供，`get_engine` 按配置二选一返回；两者接口同为
`advance(case_id) -> dict`：`native` 封装既有的 13 状态确定性推进，`langgraph` 用 StateGraph
按同样顺序驱动同一批服务函数。

### 5.2 图结构

| 节点 | 行为 |
| --- | --- |
| `load_case` | 读取案例当前状态与上下文 |
| `ensure_hypotheses` | 状态为 `EVIDENCE_READY` 时调用 `generate_hypotheses` |
| `plan_probe` | 调用 `plan_next_probe` 规划下一步检查 |
| `apply_pending` | 存在 pending probe 且已有已存结果时调用 `record_probe_result`；否则停在等待外部输入 |
| `finalize` | 无 pending 且无未关闭的高信息增益检查时调用 `finalize_diagnosis` |

条件边：`ensure_hypotheses → plan_probe → apply_pending → plan_probe`（循环最多 `settings.max_probe_steps` 次）；
`apply_pending` 没有新结果 → 结束；`plan_probe` 没有候选 → `finalize`。

### 5.3 返回值

`advance` 返回 `{case_status, root_cause, steps, needs_human, node}`，其中 `root_cause` 在未出结论时为 `None`，
`needs_human` 表示需要人工介入，`node` 为本次推进停下的节点名。

### 5.4 与 native 的等价性

适配层只做流程编排与状态读取：业务判断全部委托 `core/diagnosis`、`core/probes`、`core/workflow` 的既有服务，
不复制规则、不直接写 `Case.status`。在无外部输入的确定条件下，同一案例在 `native` 与 `langgraph` 下推进应得到
一致的最终状态与根因（允许两者都停在 `PROBE_PENDING` / `NEED_HUMAN` 这类等待外部输入的确定性结果）。
`NativeDiagnosisFlow` 的推进规则不因适配层引入而变化，既有 native 测试保持通过。

## 6. 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `VECTOR_BACKEND` | `json` | `json` / `pgvector` |
| `PGVECTOR_DIM` | `768` | pgvector 向量维度，须与 Embedding 维度一致 |
| `WORKFLOW_ENGINE` | `native` | `native` / `langgraph` |
| `DATABASE_URL` | `sqlite:///./data/app.db` | pgvector 需要 `postgresql+psycopg://...` |
| `EMBEDDING_DIM` | `768` | Embedding 维度；与 `PGVECTOR_DIM` 不一致时 pgvector 检索拒绝执行 |

Compose 的 `api` 服务默认 `VECTOR_BACKEND=${VECTOR_BACKEND:-pgvector}`（容器内使用 PostgreSQL），
`WORKFLOW_ENGINE=${WORKFLOW_ENGINE:-native}`。本地默认仍为 `json` / `native`。

## 7. 启用步骤

### 7.1 pgvector（本地 PostgreSQL）

```bash
pip install "pgvector>=0.2" "psycopg[binary]>=3.1"   # 仅 pgvector 路径需要的可选依赖

# .env
# DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<db>
# VECTOR_BACKEND=pgvector

python scripts/init_db.py
alembic upgrade head
python scripts/seed_demo.py          # 重建索引并回填 embedding_vec
```

### 7.2 pgvector（Compose）

```bash
docker compose -f infra/docker-compose.yml up --build
# api 默认 VECTOR_BACKEND=pgvector；回退到 JSON：VECTOR_BACKEND=json docker compose ... up
```

### 7.3 LangGraph

```bash
pip install langgraph
# .env: WORKFLOW_ENGINE=langgraph
```

## 8. 回退与追踪

| 事件 | 触发 | 关键字段 |
| --- | --- | --- |
| `vector_backend_fallback` | 请求 pgvector 但方言非 PostgreSQL，或 `pgvector` 包不可导入 | `requested="pgvector"`、`reason` |
| `workflow_engine_fallback` | 请求 langgraph 但未安装或适配失败 | `reason` |

事件由 `core/observability` 的 `Tracer` 写入 `TRACE_DIR`（默认 `data/traces/`）下的 `*.jsonl`，
不阻塞业务主流程。排查时可按 `event` 过滤：出现回退事件说明该次请求实际走了默认实现。

## 9. 测试

`tests/test_stack_adapters.py` 覆盖：

| 场景 | 断言 |
| --- | --- |
| 默认配置 | `get_vector_store` 返回 `JsonVectorStore` |
| 非 PostgreSQL + `VECTOR_BACKEND=pgvector` | 回退 `JsonVectorStore`，并产生 `vector_backend_fallback` 追踪 |
| `PgVectorStore.search` 维度不符 | 抛 `ValueError`（无需真实 PostgreSQL） |
| `0004` 在 SQLite 上 upgrade/downgrade | no-op 且不报错 |
| `available()` 为真 | `LangGraphDiagnosisFlow.advance` 的最终 `case_status` 与 native `NativeDiagnosisFlow.advance` 一致 |
| `available()` 为假 | `get_engine` 回退 `NativeDiagnosisFlow` |

真实 PostgreSQL 集成测试以 `pytest.mark.skipif(not os.getenv("TEST_PG_URL"))` 保护，默认测试不依赖该环境。

```bash
pytest -q tests/test_stack_adapters.py
TEST_PG_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<db> pytest -q tests/test_stack_adapters.py
```

## 10. 已知限制

1. 迁移把向量列固定为 `vector(768)`，与 `PGVECTOR_DIM` 默认值一致；改动维度需同步修改迁移并重建索引。
2. `PgVectorStore` 只按余弦距离检索，不支持其他距离算子；ivfflat 索引使用 PostgreSQL 默认参数，
   未按数据量调优，切片规模增大后需评估重建索引与参数。
3. 切换后端后必须重建索引；未回填 `embedding_vec` 的历史切片不参与 pgvector 检索。
4. `pgvector` 与 `langgraph` 都是可选依赖，不在默认安装范围内；缺失时对应路径整体回退，不影响默认功能。
5. LangGraph 只替换编排层：规则、评分、状态迁移仍由既有服务裁决，`finalize` / 转人工的条件与 native 相同。