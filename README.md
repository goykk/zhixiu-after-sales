# 智修 V1.2 — 多模态售后诊断决策闭环

智修 V1.2 是面向家电售后场景的诊断决策系统：用户提交报错与多模态材料，系统按
**受理 → 证据账本 → 候选根因 → 主动检查规划 → 检查结果 → 诊断结论** 的确定性流程推进案例，
最终给出带证据链的根因结论，而不是一段不可追溯的模型文本。

本轮范围在诊断闭环之上扩展到维修闭环：配件兼容性与库存（R15）、维修方案（R16）、
审批与幂等工单（R17）、真实结果回收与关闭（R18）、工作台维修入口（R19），
以及 60–80 个合成诊断场景与 A/B/C/D 四策略消融（R20），
含骨架、前端、测试与 Compose。

> **模拟数据声明**：配件目录、库存状态、兼容关系、外部工单、20 条维修结果，以及全部诊断场景与
> 消融评测结果均为演示用模拟数据（`source="simulated"`），不接真实供应链或工单系统。
> 详见 [docs/repair-closure.md](docs/repair-closure.md) 与 [docs/ablation.md](docs/ablation.md)。

## 能力一览

| 编号 | 能力 |
| --- | --- |
| R1 | 四种角色（user / agent / technician / admin）与案例归属隔离、JWT 认证 |
| R2 | 设备档案（brand+model 唯一）与版本感知知识库 |
| R3 | 多模态受理：上传校验、不可变对象存储、OCR + 结构化字段提取 |
| R4 | 手册切片索引、按型号/硬件/固件/版本过滤的向量检索与引用 |
| R5 | 证据账本：来源、极性、原文引用，冲突保留不覆盖 |
| R6 | 规则诊断树生成候选根因，支持/反对计数与置信级别 |
| R7 | 检查规划：硬过滤（高风险/缺工具/已执行）与信息增益评分 |
| R8 | 检查结果回写 → 证据 → 假设更新，步数上限自动转人工 |
| R9 | 13 状态确定性状态机与诊断结论 |
| R10 | 统一错误体的 REST 接口 |
| R11 | Next.js 诊断工作台 |
| R12 | 1 场景 3 变体与逐步演示脚本 |
| R13 | 零依赖本地启动 + Docker Compose（PostgreSQL/pgvector、Redis、MinIO、API、Web） |
| R14 | 自动化测试（CI 覆盖率门禁 ≥80%）与端到端冒烟 |
| R15 | 配件目录：型号/配件号/库存/硬件区间与 equivalent/replacement/requires_adapter/incompatible 兼容性 |
| R16 | 维修方案：自处理/寄修/上门/换件的候选与推荐，校验配件兼容性但不自动下单 |
| R17 | 提交审批、approve/reject、幂等工单（同一幂等键只建一张单） |
| R18 | 真实维修结果回收（唯一、不可覆盖）、诊断一致/差异比对与案例关闭 |
| R19 | 诊断工作台的维修闭环入口：方案、配件、审批、工单、结果与关闭 |
| R20 | 60–80 个合成诊断场景（每场景 3 变体、20% 留出）与 A/B/C/D 四策略消融：九项指标、门禁与双格式报告 |
| R21 | 评测可视化闭环：运行记录落库、评测 HTTP API 与 `/eval` 工作台页面（四策略对比、门禁、失败案例、报告路径） |
| R22 | 可选 pgvector 向量后端：PostgreSQL 下按余弦距离检索，条件不满足时回退 JSON 余弦并记录追踪 |
| R23 | 可选 LangGraph 编排：StateGraph 驱动案例推进，复用既有诊断服务，不可用时回退 native |
| R24 | 可选异步任务：`TASK_BACKEND=celery` 时索引、消融运行与案例推进可异步执行（202 + `task_id`），状态可查询（24h TTL），不可用即回退同步 |
| R25 | 可选真实 OCR：`OCR_PROVIDER` 取 `paddle` / `rapid` / `tesseract` 时启用 PaddleOCR / PP-OCR ONNX / Tesseract，不可用回退 Mock 并追踪；PDF 优先文本层，扫描件才走 OCR |
| R26 | 可选 OpenTelemetry 可观测：`OTEL_ENABLED=true` 时把模型/检索/工具/任务事件镜像为 span 与 span event，导出 console 或 OTLP（Langfuse/Jaeger/Collector），不可用或导出失败回退 JSONL |

## 技术栈

- 后端：Python 3.12+（CI 3.12，本机验证 3.13）、FastAPI、SQLAlchemy 2、Pydantic 2、Alembic、PyJWT
- 前端：Next.js 14（App Router，`output: "standalone"`）、React 18、TypeScript strict、Tailwind CSS
- 数据：默认 SQLite（向量以 JSON 存 `document_chunks.embedding`，进程内余弦检索）；Compose 下为 PostgreSQL + pgvector
- 检索：默认 `VECTOR_BACKEND=json`（JSON 余弦）；PostgreSQL 下可切换 `VECTOR_BACKEND=pgvector`，不可用即回退
- 编排：默认 `WORKFLOW_ENGINE=native`（`NativeDiagnosisFlow`）；可选 `langgraph` StateGraph，不可用即回退
- 异步：默认 `TASK_BACKEND=sync`（请求内执行）；可选 `celery` + Redis（db 1），不可用即回退同步
- OCR：默认 `OCR_PROVIDER=mock`（确定性）；可选 `paddle` / `rapid` / `tesseract`，PDF 优先文本层，不可用即回退
- AI：默认本机 Ollama `gemma4:12b`，`AI_PROVIDER=mock` 为离线确定性回退
- 可观测：默认仅 JSONL 追踪（`data/traces/*.jsonl`）；可选 OpenTelemetry（`console` / OTLP → Langfuse、Jaeger、Collector），不可用即回退 JSONL

## 目录结构

```
core/ai            LLM / Embedding / OCR Provider（Ollama 默认，Mock 回退）
core/db            Base、engine、Session、19 张 ORM 表
core/rag           切片、向量索引（JSON 余弦 / 可选 pgvector）、版本过滤检索、重排、引用
core/multimodal    上传校验、对象存储、OCR 与结构化提取
core/workflow      V1.2 确定性诊断状态机；可选 LangGraph 编排适配层（默认 native）
core/diagnosis     证据账本、根因假设、置信更新、诊断编排
core/probes        检查库、信息增益/成本/风险评分、下一步规划
core/cases         案例用例层（受理、可见性、序列化）
core/policy        RBAC、审批、幂等与受控工具
core/parts         模拟配件目录与兼容性校验
core/repair        维修方案模板与推荐规则
core/outcome       维修结果回收与案例关闭
core/simulator     场景加载与划分、A/B/C/D 策略、消融指标、运行器与 Markdown 报告
core/observability 追踪与脱敏；可选 OpenTelemetry 桥接（默认关闭）
core/tasks         任务模型与状态存储（Redis + 进程内回退）、分发与同步/异步 handler
services/api       FastAPI（自动发现 routes，前缀 /api/v1）
services/worker    Celery 应用与异步任务（手册索引、消融运行、案例推进）
apps/web           Next.js 14 诊断工作台
data/manuals       36 份演示手册（9 设备 × 4 份）
data/scenarios     E106 演示场景 3 变体；`v1/scenarios.json` 为 80 场景 × 3 变体的合成场景集
data/parts         模拟配件目录与兼容关系（5 型号 × 4 主件 + R2 替代件）
data/outcomes      20 条模拟维修结果（10 一致 / 10 差异）
data/reports       消融评测报告（`ablation-v1-{run_id}.json` / `.md`）
data/ocr_samples    OCR 样例图（`sample.png`，由 `scripts/make_ocr_sample.py` 生成）
scripts            init_db / seed_demo / seed_parts / seed_outcomes / build_scenarios / eval_scenarios / demo_diagnosis / demo_full_closure / e2e_smoke / check_llm / make_ocr_sample / check_ocr / check_otel
infra              docker-compose.yml 与 postgres 初始化
docs               架构、接口、状态机、诊断流程、维修闭环、场景消融、评测报告、向量与编排、OCR 与 PDF 文本层、可观测性、演示脚本
```

## 本地快速开始（零外部依赖）

前置：Python 3.12+（本机验证 3.13）、Node 20（只跑后端时不需要 Node）。

```bash
# 1. 依赖
python -m venv .venv
.venv/Scripts/activate            # Windows
pip install -r requirements.txt

# 2. 建表（SQLite：data/app.db）
python scripts/init_db.py
python scripts/init_db.py --reset # 需要清空时

# 3. 种子数据：4 账号 / 9 设备 / 36 手册+索引 / 1 演示案例
python scripts/seed_demo.py

# 4. 维修闭环模拟数据：5 型号配件与兼容关系 + 20 条模拟维修结果
python scripts/seed_parts.py
python scripts/seed_outcomes.py

# 5. 启动后端
uvicorn services.api.app.main:app --reload --port 8000
# 健康检查：http://localhost:8000/health
# 接口文档：http://localhost:8000/docs

# 6. 启动前端（另开一个终端）
cd apps/web
npm install
npm run dev                       # http://localhost:3000
```

演示账号（密码均为 `demo1234`）：

| 账号 | 角色 | 用途 |
| --- | --- | --- |
| user@demo.local | user | 提交案例、补证据、执行检查 |
| agent@demo.local | agent | 生成假设、规划检查、生成结论 |
| tech@demo.local | technician | 上门检查与结果回写 |
| admin@demo.local | admin | 全部权限 |

## AI Provider

默认配置走本机 Ollama：

```bash
ollama pull gemma4:12b
python scripts/check_llm.py        # 校验模型存在并试跑一次
```

离线或没有模型时，在 `.env` 中设置 `AI_PROVIDER=mock` 即可得到确定性输出
（型号识别、故障码候选、Embedding、OCR 全部由 Mock 提供），演示与测试均不依赖网络。
注意：Mock 只识别 `KNOWN_MODELS` 中的 9 个演示型号（含 `AuroraHome AC-Mini 600`、`NovaDesk PX-220/PX-450`、
`VentoCool FZ-30`），其他设备仍可建档与索引，但受理时会标记人工确认型号。
真实 OCR（`paddle` / `rapid` / `tesseract`）是独立开关，见下文「真实 OCR 与 PDF 文本层」。

环境变量完整清单见 `.env.example`。

## 向量后端与编排引擎（可选路径，R22/R23）

默认路径不变：`VECTOR_BACKEND=json`（`document_chunks.embedding` JSON 余弦）+ `WORKFLOW_ENGINE=native`（`NativeDiagnosisFlow`）。
两条可选路径都不改变 HTTP 契约与表结构（SQLite 不建 pgvector 列）；条件不满足时回退默认，并写追踪事件
`vector_backend_fallback` / `workflow_engine_fallback`，不静默降级。

| 变量 | 默认 | 可选值 | 作用 |
| --- | --- | --- | --- |
| `VECTOR_BACKEND` | `json` | `json` / `pgvector` | 检索实现：进程内 JSON 余弦或 pgvector 余弦距离 |
| `PGVECTOR_DIM` | `768` | 整数 | pgvector 向量维度，须与 Embedding 维度一致 |
| `WORKFLOW_ENGINE` | `native` | `native` / `langgraph` | 案例推进的编排实现 |

### 启用 pgvector

```bash
# 1. 可选依赖（仅 pgvector 路径需要）
pip install "pgvector>=0.2" "psycopg[binary]>=3.1"

# 2. .env 指向 PostgreSQL 并选择后端
#    DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<db>
#    VECTOR_BACKEND=pgvector

# 3. 建表后执行迁移：PostgreSQL 下创建 vector 扩展、embedding_vec 列与 ivfflat 索引
python scripts/init_db.py
alembic upgrade head

# 4. 重建索引，使切片写入 embedding_vec
python scripts/seed_demo.py
```

`VECTOR_BACKEND=pgvector` 时检索走 `PgVectorStore`；索引写入在 `document_chunks.embedding_vec` 上同步落向量。
SQLite 下 `alembic upgrade head` 对 `0004` 为 no-op，表结构与默认路径完全相同。

### 启用 LangGraph

```bash
pip install langgraph
# .env: WORKFLOW_ENGINE=langgraph
```

适配层（`core/workflow/langgraph_adapter.py` + `engine_factory.py`）复用既有 `core/diagnosis`、
`core/probes`、`core/workflow` 服务，只做流程编排与状态读取；native 与 langgraph 两个实现共用
`advance(case_id) -> dict` 接口，调用方不感知差异。

### 回退说明

| 请求 | 回退条件 | 结果 | 追踪事件 |
| --- | --- | --- | --- |
| `VECTOR_BACKEND=pgvector` | 非 PostgreSQL、`pgvector` 包不可导入 | `JsonVectorStore` | `vector_backend_fallback`（`requested="pgvector"`，带 `reason`） |
| `WORKFLOW_ENGINE=langgraph` | 未安装 `langgraph`、适配失败 | `NativeDiagnosisFlow`（native） | `workflow_engine_fallback`（带 `reason`） |

追踪事件落在 `TRACE_DIR` 下的 `*.jsonl`。Compose 中 api 默认 `VECTOR_BACKEND=pgvector`（容器内为 PostgreSQL），
可用 `VECTOR_BACKEND=json` 覆盖；编排默认 `native`。

细节、迁移语义、测试与已知限制见 [docs/vector-and-langgraph.md](docs/vector-and-langgraph.md)。

## 异步任务（可选路径，R24）

默认路径不变：`TASK_BACKEND=sync`，索引、消融运行与案例推进在请求内执行，返回码与响应体保持既有契约。
切换 `TASK_BACKEND=celery` 后这三个长任务可异步执行：接口返回 `202` + `task_id`，状态
（`PENDING` / `STARTED` / `SUCCESS` / `FAILURE`）通过 `GET /tasks/{task_id}` 查询，记录 TTL 24 小时。

| 变量 | 默认 | 可选值 | 作用 |
| --- | --- | --- | --- |
| `TASK_BACKEND` | `sync` | `sync` / `celery` | 长任务在请求内执行还是投递给 Celery worker |
| `REDIS_URL` | `redis://127.0.0.1:6379/1` | Redis URL | Celery broker/backend 与任务状态存储（db 1） |
| `TASK_TTL_SECONDS` | `86400` | 秒 | 任务记录 TTL（24 小时），过期后查询 404 |

```bash
# .env: TASK_BACKEND=celery、REDIS_URL=redis://127.0.0.1:6379/1
uvicorn services.api.app.main:app --port 8000
celery -A services.worker.celery_app worker -l info -P solo   # Windows 必须 -P solo
```

Compose 已内置 `worker` 服务（`-P solo`、`TASK_BACKEND=celery`、`REDIS_URL=redis://redis:6379/1`），
`docker compose -f infra/docker-compose.yml up --build` 即可同时启动 api 与 worker。

```bash
BASE=http://localhost:8000/api/v1
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"agent@demo.local","password":"demo1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST "$BASE/eval/scenarios/run?async=true" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"split":"holdout","limit":16}'   # 202 {task_id, status:"PENDING"}
curl -s "$BASE/tasks/<task_id>" -H "Authorization: Bearer $TOKEN"           # 仅发起者或 agent/admin
```

前端：案例详情页有「异步推进诊断」按钮、评测页有「异步运行」按钮，均用通用 `TaskStatus` 组件轮询
`GET /tasks/{id}`（默认 2 秒、最多 60 次），任务完成后自动刷新页面数据；同步按钮保持不变。

`async=true` 但 `TASK_BACKEND=sync` 时仍同步执行并返回同步响应（追踪 `task_backend_ignored`）；
Celery/Redis 不可用时回退同步执行并追踪 `task_backend_fallback`，不返回 500。
不新增数据库表，任务状态存 Redis，不可用时回退进程内字典（追踪 `task_store_fallback`）。
完整说明见 [docs/async-tasks.md](docs/async-tasks.md)。

## 真实 OCR 与 PDF 文本层（可选路径，R25）

默认 `OCR_PROVIDER=mock` 不变（确定性输出，演示与测试不依赖额外依赖）。切换到真实引擎后图片走真实 OCR，
上传 PDF 时优先提取文本层；条件不满足时回退 Mock 并写追踪事件 `ocr_provider_fallback`，不静默降级。

| 变量 | 默认 | 可选值 | 作用 |
| --- | --- | --- | --- |
| `OCR_PROVIDER` | `mock` | `mock` / `paddle` / `rapid` / `tesseract` | 图片 OCR 实现 |
| `OCR_LANG` | `ch` | PaddleOCR / PP-OCR 语言代码 | 识别语言；Tesseract 使用系统已装语言包 |
| `OCR_MIN_CONFIDENCE` | `0.5` | 0–1 浮点 | 低于阈值的识别块丢弃 |
| `OCR_PDF_TEXT_LAYER` | `true` | `true` / `false` | PDF 优先文本层，扫描件才走 OCR |

| `OCR_PROVIDER` | 实现 | 依赖 |
| --- | --- | --- |
| `mock` | 既有 `MockOCR`（确定性） | 无 |
| `paddle` | PaddleOCR 官方运行时 | `paddleocr` + `paddlepaddle` + `numpy` |
| `rapid` | PaddleOCR PP-OCR 的 ONNX 实现，**Python 3.13 推荐** | `rapidocr_onnxruntime` + `numpy` |
| `tesseract` | Tesseract | `pytesseract` + 系统 `tesseract` 二进制 |

```bash
# 可选依赖（仅对应 provider 需要；requirements.txt 中以注释形式列出，默认安装不引入）
pip install paddlepaddle paddleocr          # paddle
pip install rapidocr_onnxruntime            # rapid
pip install pytesseract                     # tesseract，另需安装系统二进制

# .env: OCR_PROVIDER=rapid

python scripts/make_ocr_sample.py                     # 生成 data/ocr_samples/sample.png
python scripts/check_ocr.py --provider rapid          # 打印 provider/available/elapsed_ms/confidence 与文本
python scripts/check_ocr.py --json                    # 不指定 provider：paddle → rapid → tesseract → mock
```

PDF 先 `extract_pdf_text` 取文本层（`has_text_layer` 要求去空白后 ≥ 20 字符），有文本层则不调用 OCR，
并按页插入 `<!-- page: N -->` 标记供切片定位；无文本层或 `OCR_PDF_TEXT_LAYER=false` 才走 OCR。
真实识别失败（依赖缺失、模型加载失败、图片损坏）抛 `ProviderError`，案例只标记 `needs_human=true`，不伪造文本。
`check_ocr.py` 在 provider 不可用或识别失败时打印 `OCR_UNAVAILABLE` 原因并以退出码 1 结束；`--json` 输出
`{provider, available, elapsed_ms, confidence, text}`。

provider 选择、回退判定、依赖安装与已知限制（Python 3.13 下 Paddle 无 wheel、Tesseract 需系统二进制、
扫描件质量）见 [docs/ocr.md](docs/ocr.md)。

## 可观测性（可选路径，R26）

默认 `OTEL_ENABLED=false` 不变：事件仍只写 `TRACE_DIR`（默认 `data/traces/`）下的 `*.jsonl`。
开启后 `Tracer.emit` / `Tracer.step` 的模型、检索、工具与任务事件通过 OpenTelemetry 镜像为 span event 或短 span，
可导出到 console 或 HTTP OTLP（Langfuse / Jaeger / Collector）；SDK 缺失、初始化失败或导出异常一律回退 JSONL，
不影响业务请求与响应。

| 变量 | 默认 | 可选值 | 作用 |
| --- | --- | --- | --- |
| `OTEL_ENABLED` | `false` | `true` / `false` | 是否初始化 `TracerProvider` |
| `OTEL_EXPORTER` | `none` | `none` / `console` / `otlp` | 导出方式；`none` 不导出 |
| `OTEL_ENDPOINT` | `http://localhost:4318` | URL | OTLP/HTTP 接收端（base 地址，SDK 自行拼 `/v1/traces`） |
| `OTEL_SERVICE_NAME` | `zhixiu-v12` | 字符串 | 资源属性 `service.name` |
| `OTEL_HEADERS` | 空 | `k=v,k2=v2` | OTLP 请求头，逗号分隔（Langfuse Basic/Bearer 鉴权） |
| `OTEL_SAMPLE_RATIO` | `1.0` | 0–1 浮点 | 采样比例（`ParentBased(TraceIdRatioBased(...))`） |

```bash
# 可选依赖（requirements.txt 中以注释形式列出，默认安装不引入）
pip install opentelemetry-sdk opentelemetry-exporter-otlp

# .env: OTEL_ENABLED=true、OTEL_EXPORTER=console
python scripts/check_otel.py --exporter console          # 成功输出 OTEL OK，失败退出码 1
python scripts/check_otel.py --exporter otlp --endpoint http://localhost:4318
python scripts/check_otel.py --exporter otlp --endpoint https://cloud.langfuse.com/api/public/otel --headers "authorization=Basic <base64(public:secret)>"
```

`console` 用 `SimpleSpanProcessor` 同步逐条打印，只用于本地确认链路；`otlp` 用 `BatchSpanProcessor` 批量上报，
接 Jaeger 时 `OTEL_ENDPOINT` 指向其 `4318` 端口。OTLP 鉴权头通过 `--headers`/`OTEL_HEADERS` 透传到导出器
（Langfuse 用 `authorization=Basic <base64(public:secret)>`；本机无实例时可用本地 OTLP 接收器验证头透传）。
采样只作用于 OTel 侧，JSONL 仍是权威本地记录。
Jaeger / Langfuse 配置示例、`OTEL_HEADERS` 解析规则、镜像语义、回退与已知限制见
[docs/observability.md](docs/observability.md)。

## 演示与冒烟

```bash
# 逐步演示（默认 text_only；可选 with_photo / with_probe_result）
python scripts/demo_diagnosis.py --variant text_only
python scripts/demo_diagnosis.py --variant with_photo

# 端到端冒烟：认证→案例→上传→受理→证据→假设→规划→结果→结论
python scripts/e2e_smoke.py

# 维修闭环全链路：诊断→维修方案→配件校验→审批→幂等工单→结果回收→关闭
python scripts/demo_full_closure.py
```

三个脚本都需要后端已启动并已写入种子数据；成功时分别输出 `DEMO OK` / `E2E OK` / `CLOSURE OK`，
失败时打印失败步骤并以退出码 1 结束。诊断演示细节见 [docs/demo-script.md](docs/demo-script.md)，
维修闭环细节与模拟数据声明见 [docs/repair-closure.md](docs/repair-closure.md)。

## 场景集与消融实验（R20）

`data/scenarios/v1/scenarios.json` 是 80 个合成诊断场景 × 3 变体（受控生成，20% 留出），
用于在同一份数据与同一配置下横向比较四种诊断策略：

| 策略 | 含义 |
| --- | --- |
| A | RAG-only 基线：只按规则树生成候选，不规划检查（`steps=0`） |
| B | 证据账本 + 状态机：证据→假设→结论，不规划检查（`steps=0`） |
| C | + 主动检查规划：循环 `plan_next_probe` / `record_probe_result` 后再出结论 |
| D | + 结果感知排序：用历史 `RepairOutcome.actual_cause_code` 加权，无历史时退化为 C |

指标：Top-1/Top-3 根因命中率、平均检查步数、高区分度检查前 3 步覆盖率、不必要配件更换率、
安全拦截率、应升级转人工率、引用正确率、场景完成率。门禁要求 C 策略
`top3_rate ≥ 0.85`、`safety_block_rate == 1.0`、`completion_rate ≥ 0.8`，
未达标退出码为 1 且失败场景必须保留在报告中。

```bash
# 1. 生成场景集（确定性；重复执行产出同一份文件）
python scripts/build_scenarios.py

# 2. 运行消融（默认 holdout 划分；--limit 用于小样本自检）
python scripts/eval_scenarios.py --dataset data/scenarios/v1/scenarios.json \
  --strategies A,B,C,D --split holdout
```

运行前需已执行 `init_db` / `seed_demo` / `seed_outcomes`；命令打印 Markdown 报告与
`PASSED` / `FAILED`，同时写入 `data/reports/ablation-v1-{run_id}.json` 与 `.md`。

> 场景与结果均为**合成数据与模拟结果**。四策略说明、指标口径与失败案例排查见
> [docs/ablation.md](docs/ablation.md)，报告字段与阅读方式见
> [docs/eval-report.md](docs/eval-report.md)。

### 评测 API 与 `/eval` 页面（R21）

每次消融运行落一条 `eval_run_records` 记录（`run_id` 唯一），平台通过下列接口读取和触发
（均挂在 `/api/v1` 下，Bearer JWT）：

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/eval/scenarios/runs?limit=20` | `eval:read` | 历史运行列表，按 `created_at` 倒序 |
| GET | `/eval/scenarios/runs/{run_id}` | `eval:read` | 单次运行详情：指标、门禁、失败案例与报告路径；不存在 404 `RUN_NOT_FOUND` |
| POST | `/eval/scenarios/run` | `eval:run` | 同步触发一次消融，201 返回 `run_id` / `passed` / `gate` / `metrics` / `report_paths` |

`POST /eval/scenarios/run` 请求体 `{split?, limit?, strategies?}`：`split` 默认 `holdout`
（可选 `holdout` / `train` / `all`），`strategies` 默认 `["A","B","C","D"]`，`limit` 默认 20
且范围 1–20，超过返回 422 `LIMIT_EXCEEDED`。同步执行，单次请求的场景数受此上限约束，
避免超时；完整数据集消融仍用上面的 CLI 命令。权限上 user 与 technician 没有评测动作
（返回 403），agent 与 admin 可运行和读取。

前端导航新增「评测」入口进入 `/eval`：左侧历史运行列表，右侧为选中运行的四策略指标表、
门禁结论、失败案例与报告路径；顶部「运行 holdout 消融」按钮以 `{split:"holdout",limit:16}`
触发运行，运行中显示 loading，403/422 以 `code: message` 形式展示，页面保留合成数据声明。

```bash
BASE=http://localhost:8000/api/v1
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"agent@demo.local","password":"demo1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s "$BASE/eval/scenarios/runs?limit=20" -H "Authorization: Bearer $TOKEN"
curl -s -X POST $BASE/eval/scenarios/run -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"split":"holdout","limit":16}'
```

接口字段、页面使用与同步限制的完整说明见
[docs/eval-report.md](docs/eval-report.md)。

## Docker Compose

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| api | 8000 | 启动时执行 `init_db → seed_demo → uvicorn`；种子失败只告警，需按日志人工排查 |
| worker | — | Celery worker（`-P solo`、`TASK_BACKEND=celery`、`REDIS_URL=redis://redis:6379/1`），等待 postgres/redis 健康后启动 |
| web | 3000 | Next.js standalone，构建期注入 `NEXT_PUBLIC_API_BASE` |
| postgres | 5432 | `pgvector/pgvector:pg16`，账号 `zhixiu/zhixiu` |
| redis | 6379 | `redis:7-alpine`；任务状态使用 db 1 |
| minio | 9000/9001 | 对象存储服务位（本轮 API 仍写本地存储卷） |

`api` 等待 `postgres`/`redis` 健康后启动；Ollama 使用 `host.docker.internal:11434` 访问宿主机。
容器启动只执行 `init_db → seed_demo`；维修闭环的配件与结果模拟数据需在容器内手动执行
`python scripts/seed_parts.py && python scripts/seed_outcomes.py`。

## 测试

```bash
pip install -r requirements-dev.txt
pytest -q
pytest --cov=core --cov=services/api/app --cov-report=term-missing
```

测试使用隔离的 SQLite 文件与 `AI_PROVIDER=mock`，不接触生产数据。
向量后端与 LangGraph 适配的测试在同一套默认测试内（`tests/test_stack_adapters.py`）；真实 PostgreSQL
集成测试以 `TEST_PG_URL` 开启，未设置时自动跳过。

## 文档

- [docs/architecture.md](docs/architecture.md) — 模块边界、数据流与运行形态
- [docs/api.md](docs/api.md) — REST 接口、错误体与权限
- [docs/state-machine.md](docs/state-machine.md) — 13 状态与合法迁移
- [docs/diagnosis-flow.md](docs/diagnosis-flow.md) — 证据、假设、规划与结论的确定性规则
- [docs/demo-script.md](docs/demo-script.md) — 演示脚本与三变体说明
- [docs/repair-closure.md](docs/repair-closure.md) — 维修闭环、模拟配件/结果数据与全链路演示
- [docs/ablation.md](docs/ablation.md) — 场景集、A/B/C/D 策略、指标口径、运行命令与失败案例
- [docs/eval-report.md](docs/eval-report.md) — `data/reports/` 消融报告的结构、门禁与阅读方式，以及 `/eval` 页面与评测 API 的用法
- [docs/vector-and-langgraph.md](docs/vector-and-langgraph.md) — pgvector 向量后端、LangGraph 编排、迁移与环境变量、回退与已知限制
- [docs/async-tasks.md](docs/async-tasks.md) — 可选异步任务：同步/异步切换、Celery worker 启动、任务查询、回退与限制
- [docs/ocr.md](docs/ocr.md) — 四种 OCR provider、依赖安装、PDF 文本层优先、回退与追踪、检查脚本与限制
- [docs/observability.md](docs/observability.md) — 可选 OpenTelemetry：console/OTLP 导出、Langfuse/Jaeger 配置、`OTEL_HEADERS`、回退与限制
- [data/manuals/README.md](data/manuals/README.md) — 手册库结构与新增方式

## 验收命令

```bash
python scripts/init_db.py --reset
python scripts/seed_demo.py
python scripts/seed_parts.py
python scripts/seed_outcomes.py       # 输出 OUTCOMES 20；重复执行不新增
uvicorn services.api.app.main:app --port 8000 &
python scripts/demo_diagnosis.py --variant text_only
python scripts/demo_diagnosis.py --variant with_photo
python scripts/demo_diagnosis.py --variant with_probe_result
python scripts/e2e_smoke.py
python scripts/demo_full_closure.py   # 输出 CLOSURE OK
python scripts/check_ocr.py            # OCR 检查：打印 provider/耗时/置信度，失败退出码 1
python scripts/check_otel.py --exporter console --events 1   # 可观测检查：打印 provider/available/events，成功输出 OTEL OK
python scripts/build_scenarios.py     # 生成 data/scenarios/v1/scenarios.json
python scripts/eval_scenarios.py --dataset data/scenarios/v1/scenarios.json --strategies A,B,C,D --split holdout
pytest -q
```
## 工作台（R28）

前端提供统一工作台 `/console`（概览 / 案例 / 评测 / 任务），顶部导航新增“工作台”入口；既有 `/cases`、`/eval` 保持不变。

- `GET /overview`（agent/admin）：案例/工单/结果回收/评测/任务的聚合只读数据。
- `GET /tasks?limit=20&owner=me|all`：任务列表；`owner=all` 仅 staff 可看。
- 详见 `docs/workbench.md`。

```bash
python -m pytest tests/test_overview_api.py -q
cd apps/web && npx tsc --noEmit && npm run build
```
## 一键验收（R29）

`scripts/acceptance.py` 串起关键验收并产出报告（JSON + Markdown）。

```bash
python scripts/acceptance.py --skip-heavy --json   # 快速：跳过消融/OCR/前端
python scripts/acceptance.py                        # 完整（不含前端）
python scripts/acceptance.py --with-frontend         # 追加 npx tsc --noEmit
python scripts/acceptance.py --provider ollama       # 用本地模型跑 API 冒烟
```

- 步骤：env → init_db → seed → api_smoke（三变体 demo + 全链路 + e2e）→ ablation → ocr → otel →（可选）frontend。
- 报告：`data/reports/acceptance-{ts}.json` 与 `docs/acceptance-report.md`（含合成数据声明）。
- 详见 `docs/acceptance.md`。
## 生产化硬化（R30）

- JWT 密钥强度：`ENV=prod` 且不足 `JWT_MIN_SECRET_BYTES`（默认 32）时启动抛错；其他环境仅告警。
- 速率限制：`RATE_LIMIT_ENABLED=false`（默认关闭），启用后按令牌尾段/IP 限流，超限返回 429 `RATE_LIMITED`；`/health` 永不限流。
- 审计查询：`GET /api/v1/audit-logs`（`audit:read`，支持 `limit`/`action`/`actor_id`）。
- 详见 `docs/hardening.md`；测试 `tests/test_hardening.py`。

## 真实维修记录接入（R31）

```bash
python scripts/import_outcomes.py --file <real.jsonl> --dry-run   # 仅校验，不写库
python scripts/import_outcomes.py --file <real.jsonl>            # 幂等导入真实结果
python scripts/build_scenarios_from_real.py --file <real.jsonl>  # 生成场景集（≥60 条）
```

- 模板：`data/outcomes/real/v1/sample_template.jsonl`；导入幂等键 `real-<sha1>`。
- 场景生成要求有效记录 ≥60，写出后用 `core.simulator.loader` 自校验，可直接跑 `eval_scenarios.py`。
- 详见 `docs/real-data.md`；测试 `tests/test_realdata.py`。