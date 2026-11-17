# 交付边界说明（智修 V1.2）

> 本文件是项目收尾时的统一口径：能做什么、如何启动、验收结果、已知限制与后续增强入口。

## 1. 启动

```bash
# 本地零依赖（SQLite + 本地对象存储 + 同步任务）
python scripts/init_db.py --reset
python scripts/seed_demo.py
python scripts/seed_parts.py
python scripts/seed_outcomes.py
uvicorn services.api.app.main:app --port 8000
cd apps/web && npm install && npm run dev   # http://localhost:3000

# 真实模型（默认）：启动 Ollama 后即可用 gemma4:12b；离线回归用 AI_PROVIDER=mock
```

账号：`user/agent/tech/admin@demo.local`，密码 `demo1234`。
页面：`/cases`（用户诊断）、`/cases/{id}`（证据/假设/检查/维修/工单/结果）、`/eval`（消融评测）、`/console`（运营工作台）。

## 2. 验收结果（最近一次完整验收）

`python scripts/acceptance.py --with-frontend --json`：

- env / init_db / seed / api_smoke / ablation / ocr / otel / frontend：**全部 PASS**
- 结论：**PASSED（8 PASS / 0 FAIL / 0 SKIP）**
- 报告：`data/reports/acceptance-20261116T081057.json`、`docs/acceptance-report.md`

其他：
- `pytest` 全量：**PASS**（150+ 用例，覆盖率 ≥80%）
- `apps/web` `npm run build`：**成功**（含 `/console` 工作台各页面）

## 3. 能力清单

- 诊断决策闭环：证据账本、候选根因、主动检查规划、检查回写、结论与证据链。
- 维修结果闭环：配件兼容/替代/库存、维修方案、提交审批、审批、幂等工单、真实结果回收、关闭。
- 评测：80 场景 × 3 变体、20% 留出，A/B/C/D 策略消融与门禁，运行记录落库 + `/eval` 页面。
- 可选路径（默认不变 + 回退 + 追踪）：pgvector（真实 PG 实测）、LangGraph 编排、Celery 异步（真实 worker 实测）、真实 OCR（Paddle/Rapid）+ PDF 文本层、OpenTelemetry（console + OTLP 真实导出）。
- 工作台：`/console` 概览/案例/评测/任务；前端异步任务 UI（轮询组件）。
- 硬化：JWT 强度自检、可选速率限制、审计查询接口。
- 真实数据接入：`import_outcomes.py`（校验+幂等）、`build_scenarios_from_real.py`（≥60 条，loader 自校验）。

## 4. 已知限制（必须在评审中声明）

- **全部场景、配件、维修结果与消融均为模拟数据**，不代表真实业务效果。
- 外部工单系统、库存服务为模拟实现；不接真实客户数据与真实支付。
- OCR 默认 `mock`；真实 OCR 需显式 `OCR_PROVIDER=paddle|rapid`（本机已实测，paddle 0.984 / rapid 0.7606）。
- Langfuse 未实接：OTLP 路径已打通（鉴权头透传 + 本地接收器验证），真实上报需 Key/实例。
- 限流为进程内实现；多实例部署需替换为 Redis 共享限流。
- JWT 默认开发密钥仅用于本地；生产必须配置 `JWT_SECRET`（≥32 字节）与 `ENV=prod`。
- Ollama 需本机服务；离线请用 `AI_PROVIDER=mock`。

## 5. 后续增强入口（均需外部输入，非收尾阻塞项）

- 真实维修记录：`import_outcomes.py --file <real.jsonl` → `build_scenarios_from_real.py` → `eval_scenarios.py --dataset data/scenarios/real-v1/scenarios.json`。
- Langfuse：`OTEL_ENDPOINT=<url>` + `OTEL_HEADERS="authorization=Basic <base64>"`，用 `check_otel --exporter otlp` 实测。
- 生产部署：`docker compose -f infra/docker-compose.yml up --build`（PG/pgvector、Redis、MinIO、API、Web、worker）。

## 6. 追踪器说明

- T1–T63 已闭环。
- T64–T67（硬化与真实数据接入）代码、测试、文档已完成并验证（`test_hardening` 7 passed、`test_realdata` 5 passed），因平台 429 无法派发认领，追踪器显示 pending；**以产物为准视为完成**。