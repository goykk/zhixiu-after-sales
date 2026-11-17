# 架构

## 1. 形态

模块化单体：一个 FastAPI 进程承载 REST 接口，Next.js 工作台单独部署；数据与向量同库，
默认 SQLite 即可完整运行，切换到 PostgreSQL + pgvector 只需改 `DATABASE_URL` 与 `VECTOR_BACKEND`，不改变任何契约。

```
浏览器 (apps/web)
   │  fetch /api/v1/*（Bearer JWT）
   ▼
services/api  ── routes/*（认证、案例、上传、证据、假设、检查、诊断、设备、手册、检索、维修、配件、审批、工单、结果、评测、任务、概览、审计）
   │
   ├─ core/cases        案例用例：创建、受理、可见性、序列化
   ├─ core/diagnosis    证据账本、假设与置信、诊断编排（结论）
   ├─ core/probes       检查目录、规划评分、结果回写
├─ core/workflow     13 状态确定性状态机；可选 LangGraph 编排适配（默认 `NativeDiagnosisFlow`）
    ├─ core/rag          切片、向量索引（JSON 余弦 / 可选 pgvector）、检索、重排、引用
   ├─ core/multimodal   上传校验、对象存储、OCR + 结构化提取
   ├─ core/policy       RBAC 权限矩阵
   ├─ core/observability 追踪与脱敏
   ├─ core/ai           LLM / Embedding / OCR（Ollama 或 Mock）
   └─ core/db           engine / Session / 19 张表
```

## 2. 模块边界（谁写状态，谁只读）

| 模块 | 职责 | 禁止事项 |
| --- | --- | --- |
| `core/cases` | 案例创建、受理、可见性判定、输出序列化 | 不得绕过状态机改状态 |
| `core/diagnosis/evidence` | 证据写入、冲突保留、状态推进 | 不得去重或覆盖相反极性 |
| `core/diagnosis/hypotheses` | 规则树、支持/反对计数、置信级别 | 不得把无支持证据的根因标记为 supported |
| `core/probes/planner` | 过滤、评分、幂等规划、结果回写 | 高风险检查不得进入候选；同一检查不得重复推荐 |
| `core/diagnosis/orchestrator` | 结论生成与诊断汇总 | 不得只返回模型文本，结论必须绑定证据链 |
| `core/repair` | 维修方案模板、候选生成与推荐 | 不得自动下单或跳过兼容性校验 |
| `core/parts` | 配件目录、兼容/替代/库存校验 | 不得把不兼容配件推荐为可更换件 |
| `core/policy` | RBAC、审批、幂等工单与受控工具 | 不得绕过状态机或重复建单 |
| `core/outcome` | 真实结果回收、诊断一致性比对与关闭 | 结果唯一且不可覆盖，不得改写诊断结论 |
| `core/workflow/states` | 合法迁移唯一裁决点 | 任何模块不得直接写 `Case.status` |
| `core/ai/*` | Provider 实现 | 业务代码只通过 `factory` 获取，失败必须抛错不伪造成功 |

状态变更只允许经 C-CASE、C-EVIDENCE、C-HYPOTHESIS、C-PROBE、C-DIAG-ORCH 的服务函数，
每次变更写 `DiagnosticStep` 与 `AuditLog`。

## 3. 数据模型（19 张表）

| 表 | 关键约束 |
| --- | --- |
| `users` | email 唯一索引，role ∈ user/agent/technician/admin |
| `devices` | 唯一 `(brand, model)` |
| `manuals` | 版本、校验和、索引状态与正文 |
| `document_chunks` | 切片正文 + `embedding` JSON + 元数据（brand/model/hw/fw/version/page/section）；PostgreSQL 下另有 `embedding_vec` vector 列（迁移 `0004`，SQLite 不建） |
| `cases` | 状态、证据版本、步数上限计数、`missing_fields` |
| `diagnostic_steps` | 每步输入输出，构成可回溯时间线 |
| `evidence` | 来源、极性、引用、`chunk_id`（手册事实必填） |
| `hypotheses` | 唯一 `(case_id, cause_code)`，支持/反对证据 id 列表 |
| `probes` | 唯一 `(case_id, code)`，保存预期结果与选择理由 |
| `probe_results` | `probe_id` 唯一，重复提交返回 409 |
| `eval_scenarios` | 场景集（本轮用于登记 E106 场景） |
| `audit_logs` | 操作者、动作、资源与脱敏后的载荷 |
| `uploads` | 多模态扩展表：案例上传的来源登记与内容寻址键 |
| `parts` | 配件号、适用型号/硬件区间、库存与替代关系 |
| `part_compatibilities` | 配件兼容矩阵（equivalent/replacement/requires_adapter/incompatible） |
| `approvals` | 审批记录：提交人、审批人、decision 与理由 |
| `work_orders` | 幂等键唯一的工单，关联案例与派单人 |
| `repair_outcomes` | 每张工单唯一的结果：真实根因、动作、更换件、是否解决 |
| `eval_run_records` | 消融运行记录：指标、门禁、失败案例与报告路径 |

## 4. 运行形态

1. **本地零依赖**：SQLite + 本地文件对象存储 + 同步调用；Embedding 默认 Mock，OCR 默认 Mock。
2. **AI 增强**：`AI_PROVIDER=ollama` 时 LLM 与（可选）Embedding 走本机 Ollama；超时或不可用时
   Provider 抛 `ProviderError`，受理标记人工、假设生成回退规则树、诊断失败转人工，不伪造成功。
3. **Compose**：postgres/pgvector、redis、minio、api、web 五个服务；api 在 postgres/redis 健康后启动，
   容器内执行 `init_db → seed_demo → uvicorn`。本轮 Redis 与 MinIO 为服务位，业务仍走同步实现。
4. **可选技术栈路径（R22/R23）**：`VECTOR_BACKEND=pgvector` 且数据库为 PostgreSQL 且 `pgvector` 包可导入时，
   检索走 `PgVectorStore`；`WORKFLOW_ENGINE=langgraph` 且已安装 `langgraph` 时，案例推进走
   `LangGraphDiagnosisFlow`。条件不满足即回退默认并写追踪事件；Compose 中 api 默认 `VECTOR_BACKEND=pgvector`。

## 5. 可替换边界

- `core/workflow/engine_factory.py` 是流程编排水位线：`native`（`NativeDiagnosisFlow`）与 `langgraph`
  共用 `advance(case_id) -> dict`，替换编排实现不改变 HTTP 契约。
- `core/ai/base.py` 的 Provider 协议隔离模型差异；更换模型不影响业务规则。
- 向量后端由 `get_vector_store` 选择：`JsonVectorStore` 与 `PgVectorStore` 提供同一 `search`
  语义；pgvector 需迁移 `0004` 增加 `embedding_vec` 列与 ivfflat 索引，检索接口与表结构（SQLite）不变。

## 6. 可选技术栈路径（R22/R23）

两条路径都不改变 REST 契约、不新增必需依赖；默认实现不受影响，任何回退都写追踪事件而非静默降级。

| 路径 | 默认 | 启用条件 | 启用后实现 | 回退事件 |
| --- | --- | --- | --- | --- |
| 向量检索 | `VECTOR_BACKEND=json` | `VECTOR_BACKEND=pgvector` + PostgreSQL + `pgvector` 可导入 | `PgVectorStore`（余弦距离） | `vector_backend_fallback` |
| 案例编排 | `WORKFLOW_ENGINE=native` | `WORKFLOW_ENGINE=langgraph` + 已安装 `langgraph` | `LangGraphDiagnosisFlow`（StateGraph） | `workflow_engine_fallback` |

- 向量：JSON 余弦在进程内计算；pgvector 检索走 `embedding_vec <=> CAST(:vec AS vector)`，索引写入同步回填该列。
- 编排：LangGraph 适配层只做流程编排与状态读取，规则、评分与状态迁移仍由既有服务裁决。
- 迁移、环境变量、测试与已知限制见 [vector-and-langgraph.md](vector-and-langgraph.md)。

## 7. 前端

`apps/web` 为 App Router 工程，`lib/api.ts` 统一封装 `apiFetch`（Bearer 令牌、错误体解析），
`lib/types.ts` 与后端 JSON 字段同名（snake_case）。页面：`/`、`/login`、`/cases`、`/cases/[id]`；
案例详情页由 `components/diagnosis-panel.tsx` 组织证据账本、候选根因、检查卡片与结论区。