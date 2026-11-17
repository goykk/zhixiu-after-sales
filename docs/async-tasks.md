# 异步任务（可选路径，R24）

R24 在既有同步接口之上增加一条**可选**的异步执行路径，默认行为完全不变：

- 默认 `TASK_BACKEND=sync`：长任务在请求内执行，返回码与响应体保持既有契约。
- `TASK_BACKEND=celery` 时，手册索引、消融运行与案例推进可异步执行，接口返回 `202` + `task_id`，状态另行查询。

异步路径不新增数据库表：任务状态存 Redis；Redis 不可用时回退进程内字典，并写追踪事件，**不允许静默降级**。
业务失败不改变既有语义，同步接口的错误码与响应体与之前一致。

## 1. 后端选择规则

`core/tasks/dispatch.py::dispatch(task_name, payload, *, owner_id, sync_handler=None)` 的判定：

| `TASK_BACKEND` | `sync_handler` | 执行 | 返回的 `TaskInfo.status` |
| --- | --- | --- | --- |
| `sync`（默认） | 提供 | 请求内执行 | `SUCCESS` / `FAILURE` |
| `sync`（默认） | 未提供 | 抛 `ValueError` | — |
| `celery` | 任意 | 投递 `send_task` | `PENDING` |
| `celery` | 提供，但 broker 连接失败 | 回退请求内执行 + 追踪 | `SUCCESS` / `FAILURE` |

`celery` 下正常投递后立即返回 `PENDING`，由 worker 继续把状态推进到 `STARTED` → `SUCCESS` / `FAILURE`。
`sync` 下 `dispatch` 返回的是**最终**状态（已执行完），同步响应体仍由调用方按既有契约组装。

## 2. 任务模型与存储

```python
@dataclass
class TaskInfo:
    task_id: str
    status: str            # PENDING / STARTED / SUCCESS / FAILURE
    backend: str           # 创单时的 TASK_BACKEND
    owner_id: str | None
    result: dict | None
    error: str | None
    created_at: str
    updated_at: str
```

| 接口 | 说明 |
| --- | --- |
| `TaskStore.put(info)` | 写入（新建或覆盖）一条任务记录 |
| `TaskStore.get(task_id)` | 读取；不存在或已过期返回 `None` |
| `TaskStore.update(task_id, *, status, result=None, error=None)` | 更新状态与结果；记录不存在返回 `None` |
| `new_task_id()` | `task-<uuid4hex12>`，例如 `task-3f9a1c0b7d42`（长度为占位示例） |
| `get_task(task_id)` | `get_task_store().get(task_id)` |
| `get_task_store()` | `lru_cache` 单例，按 `settings.redis_url` 选实现 |

存储口径：

| 项目 | 规则 |
| --- | --- |
| 后端 | Redis（`settings.redis_url`，默认 db 1） |
| 键 | `zhixiu:task:{task_id}` |
| 值 | 整个 `TaskInfo` 的 JSON |
| TTL | `settings.task_ttl_seconds`，默认 `86400`（24 小时） |
| 回退 | Redis 不可用（连接/读写异常）时写模块级 dict，并 `emit("task_store_fallback", reason=...)` |

回退的进程内字典只在当前进程可见，进程重启后记录即消失；多实例部署时必须让所有实例共享同一个 Redis。

## 3. 分发与状态回写

`run_sync(task_info, handler)` 执行 `handler()` 并把状态更新为 `SUCCESS`（写入 `result`）；
`handler` 抛异常时先写 `FAILURE`（`error` 为异常文本）再**重新抛出**，由调用方决定是否转换为 API 错误。
这条规则保证：同步路径的错误码与响应体与异步改造前完全一致。

Celery 任务名固定：

| 任务名 | worker 函数签名 | `result` 字段 |
| --- | --- | --- |
| `zhixiu.index_manual` | `index_manual(task_id, manual_id)` | `{manual_id, chunk_count, status, error}` |
| `zhixiu.run_ablation` | `run_ablation(task_id, dataset_path, split, limit=None, strategies=None)` | `{run_id, passed, metrics, report_paths}` |
| `zhixiu.advance_case` | `advance_case(task_id, case_id)` | `advance(case_id)` 的返回值 |

三个 worker 函数都从 `get_task_store()` 读回 `task_id`：先置 `STARTED`，成功置 `SUCCESS` 并写 `result`，
异常置 `FAILURE` 并写 `error`，最后关闭数据库会话。任务实现复用既有服务，不复制业务规则：

- 索引：`ManualIndexer(db).index_manual(manual_id)`
- 消融：`run_ablation(...)`（口径见 [ablation.md](ablation.md)）
- 案例推进：`get_engine(db).advance(case_id)`，native / langgraph 由 `WORKFLOW_ENGINE` 决定（见
  [vector-and-langgraph.md](vector-and-langgraph.md)）

## 4. Celery 应用

`services/worker/celery_app.py`：

```python
celery_app = Celery("zhixiu", broker=settings.redis_url, backend=settings.redis_url)
```

配置：`task_serializer="json"`、`accept_content=["json"]`、`result_serializer="json"`、
`timezone="UTC"`、`task_track_started=True`、`broker_connection_retry_on_startup=True`。

`services/worker/tasks.py` 用 `@celery_app.task(name=...)` 注册上表三个任务；
worker 与 api 必须使用同一个 `DATABASE_URL` 与 `REDIS_URL`，否则任务记录与业务数据互相不可见。

## 5. 异步 API

### 5.1 任务查询

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/tasks/{task_id}` | 登录；`owner_id == actor_id` 或 staff（agent/admin） | 返回 `TaskOut` |

`TaskOut = {task_id, status, backend, result, error, created_at, updated_at}`。
任务不存在或已过期（TTL 24h）返回 404 `TASK_NOT_FOUND`；非发起者且非 staff 返回 403。

### 5.2 现有端点增量

三个端点只新增 `async` 查询参数，默认 `false`，同步响应保持不变：

| 方法 | 路径 | 权限 | `async=true` 时 |
| --- | --- | --- | --- |
| POST | `/manuals/{manual_id}/index?async=true` | `manual:manage` | 202 `{task_id, status:"PENDING", backend:"celery"}` |
| POST | `/eval/scenarios/run?async=true` | `eval:run` | 202 `{task_id, status:"PENDING"}` |
| POST | `/cases/{case_id}/diagnose?async=true` | 案例可访问 | 202 `{task_id, status:"PENDING"}` |

同步路径的响应保持不变：

- `POST /manuals/{manual_id}/index` → 200 `{manual_id, chunk_count, status, error}`
- `POST /eval/scenarios/run` → 201 `{run_id, passed, gate, metrics, report_paths}`
- `POST /cases/{case_id}/diagnose` → 原有诊断响应（`TurnOut`）

`async=true` 但 `TASK_BACKEND=sync`（或 Celery 不可用回退）时，仍按同步执行并返回**同步响应**，
不返回 202，并追踪 `task_backend_ignored`（回退场景同时追踪 `task_backend_fallback`）。
接口字段与权限的完整说明见 [api.md](api.md)。

## 6. 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `TASK_BACKEND` | `sync` | `sync` / `celery` |
| `REDIS_URL` | `redis://127.0.0.1:6379/1` | Celery broker/backend 与任务状态存储；使用 db 1 |
| `TASK_TTL_SECONDS` | `86400` | 任务记录 TTL（24 小时） |

依赖：`requirements.txt` 增加 `celery` 与 `redis`，两者随默认安装提供，不影响 `sync` 路径。

## 7. 启用步骤

### 7.1 本地（API + worker + Redis）

```bash
pip install -r requirements.txt        # 含 celery / redis

# .env
# TASK_BACKEND=celery
# REDIS_URL=redis://127.0.0.1:6379/1

uvicorn services.api.app.main:app --port 8000
celery -A services.worker.celery_app worker -l info -P solo
```

Windows 上必须使用 `-P solo`（`prefork` 池在 Windows 不可用），这也是 Compose worker 的默认池；
`solo` 池并发度为 1，长任务会串行执行。

### 7.2 Compose

```bash
docker compose -f infra/docker-compose.yml up --build
```

Compose 新增 `worker` 服务：与 `api` 同 build context/dockerfile，命令为
`celery -A services.worker.celery_app worker -l info -P solo`，环境变量与 `api` 一致
（`DATABASE_URL`、`AI_PROVIDER`、`OLLAMA_*`、`VECTOR_BACKEND`、`TASK_BACKEND=celery`、
`REDIS_URL=redis://redis:6379/1`），并等待 `postgres` / `redis` 健康后启动。

### 7.3 触发与查询

```bash
BASE=http://localhost:8000/api/v1
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"agent@demo.local","password":"demo1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST "$BASE/manuals/<manual_id>/index?async=true" -H "Authorization: Bearer $TOKEN"
curl -s -X POST "$BASE/eval/scenarios/run?async=true" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"split":"holdout","limit":16}'

# 用上一步返回的 task_id 查询
curl -s "$BASE/tasks/<task_id>" -H "Authorization: Bearer $TOKEN"
```

`<manual_id>`、`<case_id>`、`<task_id>` 为占位，实际值以接口返回或种子数据为准。

## 8. 回退与追踪

| 事件 | 触发 | 关键字段 |
| --- | --- | --- |
| `task_backend_fallback` | `TASK_BACKEND=celery` 但 `send_task` 连接失败，回退请求内执行 | `reason` |
| `task_store_fallback` | Redis 不可用，任务状态改存进程内 dict | `reason` |
| `task_backend_ignored` | 请求带 `async=true` 但实际按同步执行（`TASK_BACKEND=sync`） | 请求相关字段 |

事件由 `core/observability` 的 `Tracer` 写入 `TRACE_DIR`（默认 `data/traces/`）下的 `*.jsonl`，不阻塞业务主流程。
出现回退事件说明该次请求实际走的是同步/进程内路径，排查异步「不生效」时先按 `event` 过滤追踪。

## 9. 测试

`tests/test_tasks_async.py` 覆盖：

| 场景 | 断言 |
| --- | --- |
| `dispatch`（`sync`）执行 handler | 状态 `SUCCESS`，`result` 落库 |
| `dispatch`（`sync`）handler 抛错 | 状态 `FAILURE` 且异常上抛 |
| `dispatch`（`celery`，monkeypatch `send_task`） | 返回 `PENDING`，任务记录存在 |
| `dispatch`（`celery`）`send_task` 抛连接异常 | 回退执行 handler，产生 `task_backend_fallback` 追踪 |
| `GET /tasks/{id}` | owner 200、staff 200、其他用户 403、不存在 404 |
| `POST /manuals/{id}/index?async=true` | `sync` 下仍 200（非 202）；`celery` 下 202 且返回 `task_id` |
| `TaskStore`（monkeypatch Redis 抛错） | 回退进程内 dict 仍可读写 |

```bash
python -m pytest tests/test_tasks_async.py -q
```

既有同步端点行为不变，全量回归仍以 `pytest -q` 为准；本文件不重复 `test_api_flow.py` 的断言。

## 10. 已知限制

1. 不新增数据库表：任务状态只在 Redis（或回退 dict）里，24 小时后过期，过期后查询返回 404，
   历史任务不可追溯。需要长期留存的运行结果仍看既有业务表（如 `eval_run_records`）与报告文件。
2. Redis 回退为进程内字典：多实例/多进程下互不可见，进程重启即丢失；生产环境应保证 Redis 可用。
3. `async=true` 只是提示：实际是否异步完全由 `TASK_BACKEND` 决定；`sync` 下会追踪 `task_backend_ignored`，
   调用方仍需按同步响应的字段（非 `task_id`）处理。
4. worker 必须与 api 共享 `DATABASE_URL` 与 `REDIS_URL`，否则任务记录与业务数据对不上；
   Compose 已按此配置，自建部署需自行保证。
5. Windows 只能用 `-P solo`（并发 1），索引、消融这类 CPU/IO 密集任务会串行排队；
   `TaskInfo` 只有四个状态，没有队列长度、重试次数与进度百分比。
6. 异步任务失败不会自动重试：`FAILURE` 记录带 `error` 文本，重跑需要重新发起请求。

## 11. 前端异步 UI（R27）

- 案例详情页：“异步推进诊断”按钮 → `POST /cases/{id}/diagnose?async=true`，成功后渲染 `TaskStatus`，完成后自动刷新案例。
- 评测页：“异步运行”按钮 → `POST /eval/scenarios/run?async=true`，成功后渲染 `TaskStatus`，完成后自动刷新运行列表。
- `TaskStatus` 组件（`apps/web/components/task-status.tsx`）：挂载即查询并按 `pollMs`（默认 2s）轮询，最多 `maxPolls`（默认 60）次；终态触发 `onDone`；卸载清理定时器；`FAILURE` 显示 `error`，`SUCCESS` 显示结果摘要。
- 默认同步按钮与响应完全不变；`async` 仅在 `TASK_BACKEND=celery` 时返回 202 + `task_id`，`sync` 下后端按同步返回，前端用 `isTaskAccepted` 判定。
- 失败展示：发起请求或 `GET /tasks/{id}` 返回 401/403/404/422 时，组件展示统一错误体的 `code: message`（如 `TASK_NOT_FOUND: ...`），不白屏。
- 验证：`cd apps/web && npx tsc --noEmit && npm run build`；类型检查无错误，构建成功并输出 App Router 路由表。