# 可观测性：OpenTelemetry 接入（可选路径，R26）

R26 在既有 JSONL 追踪之上增加一条**可选**的 OpenTelemetry 桥接，默认行为完全不变：

- 默认 `OTEL_ENABLED=false`：不初始化 `TracerProvider`，既有 `TRACE_DIR`（默认 `data/traces/`）下的 `*.jsonl` 事件与全部测试保持不变。
- `OTEL_ENABLED=true` 时，`Tracer.emit` / `Tracer.step` 产生的模型、检索、工具与任务事件同时镜像为 OTel span event 或短 span。
- 导出目标为 `console`（标准输出）或 `otlp`（HTTP OTLP，可指向 Langfuse / Jaeger / Collector）。
- SDK 缺失、初始化失败或导出异常一律回退 JSONL 并写 `otel_fallback`，**不允许影响业务请求**。

> **JSONL 仍是权威本地记录**：OTel 只是旁路镜像。采样丢弃、后端不可达或导出异常都不会让事件在本地追踪中缺失；
> 排查仍以 `data/traces/*.jsonl` 为准。

## 1. 配置

`services/api/app/config.py` 新增六个字段（不改既有字段），环境变量名与字段同名大写：

| Settings 字段 | 环境变量 | 默认 | 可选值 | 作用 |
| --- | --- | --- | --- | --- |
| `otel_enabled` | `OTEL_ENABLED` | `false` | `true` / `false` | 是否初始化 `TracerProvider` |
| `otel_exporter` | `OTEL_EXPORTER` | `none` | `none` / `console` / `otlp` | 导出方式；`none` 不导出 |
| `otel_endpoint` | `OTEL_ENDPOINT` | `http://localhost:4318` | URL | OTLP/HTTP 接收端（base 地址，SDK 自行拼 `/v1/traces`） |
| `otel_service_name` | `OTEL_SERVICE_NAME` | `zhixiu-v12` | 字符串 | 资源属性 `service.name`，也是 Jaeger/Langfuse 中的服务名 |
| `otel_headers` | `OTEL_HEADERS` | 空 | `k=v,k2=v2` | OTLP 请求头（如 Langfuse 的 Basic / Bearer 鉴权） |
| `otel_sample_ratio` | `OTEL_SAMPLE_RATIO` | `1.0` | 0–1 浮点 | `ParentBased(TraceIdRatioBased(...))` 的采样比例 |

`OTEL_ENABLED` 为假时其余字段不生效；`OTEL_EXPORTER=none` 时即使已开启也不导出。

## 2. 启用与切换

依赖以注释形式列在 `requirements.txt`（`opentelemetry-sdk`、`opentelemetry-exporter-otlp`），默认安装不引入：

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp
```

`services/api/app/main.py` 的 `create_app()` 在启动时调用 `setup_tracing()`，读取上述 settings；
初始化失败只返回 `False` 并记日志，不阻断启动：

```bash
# .env: OTEL_ENABLED=true、OTEL_EXPORTER=console
uvicorn services.api.app.main:app --port 8000
```

| `OTEL_EXPORTER` | 处理器 | 典型用途 |
| --- | --- | --- |
| `console` | `ConsoleSpanExporter` + `SimpleSpanProcessor`（同步逐条打印） | 本地确认桥接是否生效 |
| `otlp` | `OTLPSpanExporter(endpoint=..., headers=...)` + `BatchSpanProcessor`（批量上报） | 接 Langfuse / Jaeger / Collector |
| `none`（默认） | — | 未启用导出；`setup_tracing()` 返回 `False` |

`setup_tracing(*, service_name=None, exporter=None, endpoint=None)` 幂等：重复调用不会重建 provider，
已在初始化后返回当前启用状态。显式传入的参数优先于 settings，便于脚本与测试指定导出方式。

## 3. OTLP 后端配置示例

### 3.1 Jaeger

```bash
docker run -d --name jaeger -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one:latest

# .env
# OTEL_ENABLED=true
# OTEL_EXPORTER=otlp
# OTEL_ENDPOINT=http://localhost:4318
# OTEL_SERVICE_NAME=zhixiu-v12
```

`4318` 是 Jaeger 的 OTLP/HTTP 接收端口（`4317` 是 gRPC，本项目不走 gRPC）；查询界面在 `http://localhost:16686`，
服务名下拉中选 `zhixiu-v12`（或 `OTEL_SERVICE_NAME` 的取值）。`OTEL_ENDPOINT` 填 base 地址，路径由 SDK 拼接。

### 3.2 Langfuse

Langfuse 的 OTLP 接入点随部署区域不同（自托管另有地址），以下为占位，实际值以 Langfuse 控制台
「OpenTelemetry / OTLP」接入信息为准：

```bash
# .env
# OTEL_ENABLED=true
# OTEL_EXPORTER=otlp
# OTEL_ENDPOINT=<langfuse_otlp_endpoint>       # 例：https://<region>.langfuse.com/api/public/otel
# OTEL_SERVICE_NAME=zhixiu-v12
# OTEL_HEADERS=Authorization=Basic <public_key:secret_key 的 Base64>
```

`OTEL_HEADERS` 只传给导出器，不作为 span 属性，因此不会出现在 JSONL 或 span 属性里；但它本身是凭据，
**不要提交进仓库或写进日志**，本地用 `.env`（不纳入版本控制）承载。

### 3.3 通用 Collector

```bash
# .env
# OTEL_ENABLED=true
# OTEL_EXPORTER=otlp
# OTEL_ENDPOINT=http://<collector-host>:4318
```

Collector 侧按标准 OTLP/HTTP receiver 配置即可，本项目只负责按 HTTP 导出，不做协议转换与批量策略定制。

## 4. `OTEL_HEADERS` 解析

`core/observability/otel.py::parse_headers(raw)`：逗号分隔 `k=v`，忽略空项与不含 `=` 的项，首尾空白被去掉：

| 输入 | 输出 |
| --- | --- |
| `a=1, b=2, bad, =x` | `{"a": "1", "b": "2"}` |
| `Authorization=Basic <base64>,x-scope=team-a` | `{"Authorization": "Basic <base64>", "x-scope": "team-a"}` |
| `""` / `bad` | `{}` |

逗号是分隔符，因此单个 header 的值里不能含逗号；`=` 只按第一个切分，值内部可以出现 `=`（Base64 填充、`Basic` 凭据均不受影响）。

## 5. 镜像语义

| 既有调用 | 未启用 | 启用且当前无活动 span | 启用且当前有活动 span |
| --- | --- | --- | --- |
| `Tracer.emit(event, **fields)` | 只写 JSONL | 建短 span `otel.<kind>`，写事件后立即结束 | 当前 span 上 `add_event(name, {kind, **redacted})` |
| `Tracer.step(name, **fields)` | 只写 `{name}.start` / `{name}.end` JSONL | 同上，另在 span 上下文中执行 | 在外层 span 内执行，JSONL 记录不变 |

`core/observability/otel.py` 的公开接口：

| 函数 | 语义 |
| --- | --- |
| `available()` | `opentelemetry.sdk` 是否可导入；不导入任何导出器 |
| `setup_tracing(...)` | 初始化 provider；未开启、SDK 缺失、导出器初始化失败均返回 `False` 且不抛 |
| `parse_headers(raw)` | 见上一节 |
| `span(name, kind="internal", **attrs)` | 上下文的 `start_as_current_span`；属性经 `redact`；异常记录错误后 re-raise；未启用时 yield `None` |
| `record_event(kind, name, attrs=None)` | 有活动 span 时 `add_event`，否则建短 span `otel.<kind>` 并立即结束；未启用时 no-op |
| `shutdown()` | flush 并关闭 provider，幂等 |
| `reset_for_tests()` | 清空初始化标志，仅供测试 |

span 属性与 span event 属性统一经 `core/observability/redact.py` 的 `redact` 处理：键名敏感的值替换为 `***`，
包括 `password` / `token` / `authorization` / `api_key` 以及**键名含 `email`** 的字段（`email`、`email_address`、
`e_mail` 等）；字符串值中的 `Bearer <token>` 与邮箱地址同样按正则替换为 `***`。与 JSONL 相同，脱敏只保留结构，
不改变字段名，便于对照排查。

`Tracer.step` 内部用 `otel.span(name, **fields)` 包裹，因此 step 内部的 `emit`
会落到当前 span 上成为 span event；step 结束时 span 一并结束。

## 6. 回退语义

| 场景 | `setup_tracing()` | 业务影响 | 追踪 |
| --- | --- | --- | --- |
| `OTEL_ENABLED=false`（默认） | `False` | 无 | 无；JSONL 与改造前一致 |
| `OTEL_EXPORTER=none` | `False` | 无 | 无 |
| `opentelemetry.sdk` 未安装 | `False` | 无 | 无（只记日志） |
| 导出器构造失败（端点格式错、包缺失） | `False` | 启动不阻断 | 无（只记日志） |
| `emit` 期间 OTel 调用抛异常 | — | 捕获，请求不失败 | JSONL 追加一条 `otel_fallback`，进程内只写一次 |
| OTLP 后端不可达 / 拒绝 | — | 请求不受影响 | 该批 span 由 SDK 丢弃；JSONL 记录完整 |

`otel_fallback` 每进程只写一次，避免导出器持续异常时把追踪文件刷爆、也避免"写失败 → 再写失败"的递归。
过滤方式：`event=otel_fallback`。

`shutdown()` 负责 flush `BatchSpanProcessor` 的缓冲区；进程正常退出前调用可减少最后一批 span 丢失，
异常终止（kill -9、容器硬重启）时最后一批 span 可能丢失，JSONL 不受影响。

## 7. 检查脚本

```bash
# 本地确认桥接链路：console 导出
python scripts/check_otel.py --exporter console

# 指向真实后端
python scripts/check_otel.py --exporter otlp --endpoint http://localhost:4318

# 带鉴权头（Langfuse / Bearer 等）
python scripts/check_otel.py --exporter otlp --endpoint http://localhost:4318 --headers "authorization=Basic <base64>"

# 放大一次检查的事件量
python scripts/check_otel.py --exporter console --events 3
```

`scripts/check_otel.py` 参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--exporter` | `console` | `console` 或 `otlp` |
| `--endpoint` | `settings.otel_endpoint` | 仅 `otlp` 生效 |
| `--events` | 脚本内置值 | 本次写入的事件数量，用于观察导出器负载 |
| `--headers` | `settings.otel_headers` | OTLP 请求头 `k=v,k2=v2`（Langfuse Basic/Bearer 等） |

脚本临时置 `OTEL_ENABLED=true` 与给定 exporter 后调用 `setup_tracing()`，创建 `model.call`、`retrieval`、
`tool.call` 三个 span 并各写事件，最后 `shutdown()`。

| 输出形态 | 内容 |
| --- | --- |
| 摘要行 | `provider=<exporter> available=<bool> events=<n>`（`events` 为实际写入的事件数），`otlp` 带 `--headers` 时另起一行 `headers=<n>`（头数量，不打印值） |
| 成功 | 追加 `OTEL OK`，退出码 `0` |
| 失败 | 打印不可用原因（SDK 缺失、导出器构造失败）或导出失败原因，退出码 `1` |

`<bool>` / `<n>` 的实际取值随环境浮动（是否安装 SDK、写入多少事件），本节不给出固定基准；
console 导出的 span 明细由 SDK 版本决定字段顺序，只用于确认链路已通。

## 8. 测试

`tests/test_otel.py` 覆盖：

| 场景 | 断言 |
| --- | --- |
| 默认 `otel_enabled=False` | `setup_tracing()` 返回 `False`；`record_event` / `span` 为 no-op；`emit` 仍写 JSONL |
| 用 `InMemorySpanExporter` 注入 | `record_event` 产生 span event；`span` 产生命名 span 且属性经脱敏（`token` / `email` 等敏感键 → `***`） |
| `parse_headers("a=1, b=2, bad, =x")` | `{"a":"1","b":"2"}` |
| `available` monkeypatch 为 `False` | `setup_tracing()` 返回 `False`、不抛 |
| `Tracer.emit` 在启用且 OTel 抛错 | 业务不失败，JSONL 记录 `otel_fallback`，且只记一次 |
| `check_otel.py --exporter console --events 1` | 退出码 `0` |

```bash
python -m pytest tests/test_otel.py -q
```

`InMemorySpanExporter` 来自 `opentelemetry-sdk`，SDK 未安装时相关用例 skip；全量回归仍以 `pytest -q` 为准。

## 9. 已知限制

1. **导出器缺失即不启用**：只装 `opentelemetry-api` 而没有 `opentelemetry-sdk`，或 `otlp` 路径缺
   `opentelemetry-exporter-otlp`，`available()`/`setup_tracing()` 都返回 `False`，得到的是"什么都没导出"而不是错误；
   排查手段是看启动日志与 `check_otel.py` 的退出码。
2. **采样只作用于 OTel 侧**：`OTEL_SAMPLE_RATIO < 1.0` 时部分 span 与事件不会导出，本地 JSONL 仍是全量；
   因此不能用采样后的后端数据统计事件次数。
3. **脱敏覆盖有限**：只按 `redact.py` 的敏感键清单（含键名带 `email` 的字段）与 `Bearer` / 邮箱正则遮蔽；自由文本
   （用户描述、OCR 原文、模型输出）中的其他敏感信息（手机号、地址、单号）不会被内容级识别。
   不要把原始材料、凭据写进 span 属性。
4. **JSONL 权威**：OTel 不替代 `data/traces/*.jsonl`，也不改变既有事件名与字段；导出失败丢的是 span 副本。
5. **console 是同步导出**：`SimpleSpanProcessor` 逐条打印，高并发下会拖慢请求并刷屏，只用于本地确认；
   生产一律 `otlp`。
6. **无 GenAI 语义约定**：span 名沿用既有事件名，不打 `gen_ai.*` 属性，因此 Langfuse 侧看到的是一般 span 结构，
   而不是被识别为 LLM 调用的专用视图；需要更细语义时应在真实模型调用层另行埋点，而不是改追踪口径。
7. **不改变 HTTP 契约与表结构**：不新增数据库表、不新增响应字段、不加额外 API；开启与关闭对调用方透明。
8. **导出器与进程生命周期绑定**：`BatchSpanProcessor` 的缓冲区在进程内，正常退出前需要 `shutdown()` flush；
   容器被强杀时最后一批 span 可能丢失。