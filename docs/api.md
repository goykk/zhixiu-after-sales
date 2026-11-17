# REST 接口

所有业务接口挂在 `/api/v1`，认证为 Bearer JWT。健康检查在根路径 `GET /health`。

## 1. 统一错误体

```json
{ "error": { "code": "INSUFFICIENT_EVIDENCE", "message": "证据不足，无法生成结论", "details": null } }
```

| HTTP | 固定 code | 场景 |
| --- | --- | --- |
| 401 | `UNAUTHORIZED` / `INVALID_CREDENTIALS` | 令牌缺失/失效、登录失败 |
| 403 | `FORBIDDEN` | 角色或案例归属不足 |
| 404 | `NOT_FOUND` / `DEVICE_NOT_FOUND` / `MANUAL_NOT_FOUND` | 资源不存在 |
| 409 | `EMAIL_EXISTS` | 邮箱重复注册 |
| 409 | `ILLEGAL_TRANSITION` | 状态机拒绝的状态迁移 |
| 409 | `PENDING_PROBE` | 仍有待执行检查时生成结论 |
| 409 | `INSUFFICIENT_EVIDENCE` | 无 high/medium 级 supported 假设 |
| 409 | `PROBE_AVAILABLE` | 仍有更高增益的安全检查未执行 |
| 409 | `PROBE_NOT_PENDING` | 重复回写检查结果或状态不允许 |
| 409 | `WORK_ORDER_EXISTS` / `IDEMPOTENCY_KEY_CONFLICT` | 案例已有工单、幂等键被其他案例占用 |
| 409 | `OUTCOME_EXISTS` | 同一工单重复提交维修结果 |
| 404 | `TASK_NOT_FOUND` | 异步任务不存在或已过期 |
| 422 | `VALIDATION_ERROR` | 请求体校验失败 |
| 422 | `UPLOAD_REJECTED` | 上传类型/大小/内容不合法（不落盘） |
| 422 | `INVALID_EVIDENCE` | 证据枚举非法或 quote 为空 |
| 422 | `INVALID_OBSERVATION` | 观察值不匹配该检查的预期结果 |
| 422 | `LIMIT_EXCEEDED` | 评测 limit 超出 1–20 |
| 404 | `RUN_NOT_FOUND` | 评测运行记录不存在 |
| 500 | `STORAGE_ERROR` / `INTERNAL_ERROR` | 对象存储失败、未捕获异常 |

## 2. 认证与用户

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/auth/register` | 公开 | 固定注册为 `user`；返回 `access_token`/`token`/`user` |
| POST | `/auth/login` | 公开 | 失败统一 401，不区分用户不存在与密码错误 |
| GET | `/auth/me` | 已登录 | 当前用户档案 |
| POST | `/auth/users` | admin | 指定角色创建账号 |

## 3. 设备、手册与检索

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/devices?brand=&model=` | 已登录 | 设备档案列表 |
| POST | `/devices` | agent/admin | `{brand, model, hardware_version?, firmware_version?, category?}`，`(brand, model)` 唯一 |
| GET | `/devices/{device_id}` | 已登录 | 单台设备档案 |
| POST | `/manuals` | agent/admin | multipart：`device_id`、`file`（md/txt/pdf）、`title?`、`version?`、`source_url?` |
| GET | `/manuals?device_id=&limit=` | 已登录 | 手册列表（含索引状态） |
| POST | `/manuals/{manual_id}/index` | agent/admin | 幂等重建切片，失败回滚并置 `failed` |
| GET | `/search?q=&device_id=&top_k=5` | 已登录 | 版本过滤 + 向量召回 + 重排，返回带版本/页码/章节的引用 |

检索无有效证据时返回 `items: []`（低于 `RELEVANCE_THRESHOLD` 的条目被过滤），诊断不得据此生成确定性根因。

## 4. 案例与受理

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/cases` | user/agent/admin | `{device_model, symptom, error_code?}` → 201，状态 `DRAFT` |
| GET | `/cases?status=&limit=&offset=` | 已登录 | user 只见自己的案例；agent/admin 见全部 |
| GET | `/cases/{case_id}` | owner 或 staff | `CaseDetail = {case, evidence, hypotheses, probes, steps, uploads}` |
| POST | `/cases/{case_id}/intake` | owner 或 staff | `{user_text?}`；OCR/LLM 提取字段并绑定设备，`DRAFT→COLLECTING_INFO`（或 `NEED_HUMAN`） |
| POST | `/cases/{case_id}/uploads` | owner 或 staff | multipart `file`；内容寻址存储并登记来源 |
| GET | `/cases/{case_id}/uploads` | owner 或 staff | 上传记录列表 |

`CaseOut` 字段：`id, user_id, device_id, device_model, status, symptom, error_code, confidence,
risk_level, step_count, evidence_version, missing_fields, last_question, created_at, updated_at`。

## 5. 证据、假设、检查与结论

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/cases/{id}/evidence` | owner/staff（`evidence:write`） | `{source_type, polarity, quote, chunk_id?, page?, relevance_score?, source_ref?}` → 201 |
| GET | `/cases/{id}/evidence` | owner/staff | `{items: [EvidenceOut]}`，按时间升序 |
| POST | `/cases/{id}/hypotheses/generate` | owner 或 agent/admin（`hypothesis:write`） | 规则树 upsert → `{case_status, items}` |
| GET | `/cases/{id}/hypotheses` | owner/staff | `{items}`，按 `confidence_score` 降序 |
| POST | `/cases/{id}/probes/plan` | owner/staff（`probe:write`） | → `{case_status, probe: ProbeCard \| null}` |
| POST | `/cases/{id}/probes/{probe_id}/result` | owner/staff（`probe:write`） | `{observed_value, source_ref?}`；结果→证据→假设→状态 |
| GET | `/cases/{id}/probes` | owner/staff | `{items: [ProbeOut]}` |
| POST | `/cases/{id}/finalize-diagnosis` | agent/admin（`diagnosis:finalize`） | → `DiagnosisOut`，成功时 `HYPOTHESIZING→DIAGNOSED` |
| GET | `/cases/{id}/diagnosis` | owner/staff | `{case, evidence, hypotheses, probes, root_cause, evidence_chain}` |

`EvidenceOut`：`id, case_id, chunk_id, source_type, polarity, quote, page, relevance_score, source_ref, observed_at, created_at`。

`HypothesisOut`：`id, cause_code, label, status, confidence_level, confidence_score, evidence_version,
support_evidence_ids, refute_evidence_ids, rationale, updated_at`。

`ProbeCard`：`probe_id, code, probe_type, question, target_labels, expected_outcomes, cost_level,
risk_level, score, rationale`。

`DiagnosisOut`：`{case_id, case_status, root_cause: HypothesisOut | null, evidence_chain: [EvidenceOut],
unresolved: [str], rationale}`。

## 6. 维修闭环与运营

### 6.1 维修方案与配件

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/cases/{id}/repair-plan` | `repair:write` | 基于诊断结论生成自处理/寄修/上门/换件候选与推荐；`DIAGNOSED→REPAIR_PLANNING`，已在 `REPAIR_PLANNING` 幂等返回 |
| GET | `/cases/{id}/repair-plan` | owner/staff | 最近一次维修方案（未生成返回 404） |
| GET | `/parts?device_model=` | `part:read` | 按型号返回配件目录：配件号、库存、硬件区间与兼容性 |
| GET | `/parts/{part_no}/compatibility?device_model=&hardware_version=` | `part:read` | 单件兼容性：`equivalent` / `replacement` / `requires_adapter` / `incompatible` |

维修方案只做候选与推荐，不自动下单；换件候选必须通过配件兼容性校验，不兼容件不进入推荐。

### 6.2 审批与工单

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/cases/{id}/submit-approval` | `repair:write` | `REPAIR_PLANNING→APPROVAL_PENDING`；重复提交幂等 |
| POST | `/cases/{id}/approvals` | `approval:decide` | `{decision: approve\|reject, reason?}`；批准保持 `APPROVAL_PENDING`，驳回转 `NEED_HUMAN` |
| GET | `/cases/{id}/approvals` | owner/staff | 审批记录列表 |
| POST | `/cases/{id}/work-orders` | `workorder:create` | `{idempotency_key, assignee?}`；批准后建单，`APPROVAL_PENDING→WORK_ORDER_CREATED`；同键同案例返回原单，跨案例 409 |
| GET | `/work-orders?case_id=&limit=&offset=` | `workorder:read` | 工单列表；technician 仅见指派给自己的工单 |
| GET | `/work-orders/{work_order_id}` | `workorder:read` | 工单详情（案例、审批、结果） |

工单幂等键唯一；`created=false` 表示命中已有工单。未批准或状态不符返回 409 `ILLEGAL_TRANSITION`。

### 6.3 维修结果与关闭

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/work-orders/{id}/outcome` | `outcome:write` | `{actual_cause_code, action, parts_replaced, resolved, note?}`；`WORK_ORDER_CREATED→OUTCOME_PENDING`，每单唯一，重复 409 `OUTCOME_EXISTS` |
| GET | `/cases/{id}/outcomes` | `outcome:read` | 结果列表，含诊断一致/差异比对（`match` / `mismatch` / `unknown`） |
| POST | `/cases/{id}/close` | `approval:decide` 或 `workorder:update` | 允许 `CLOSED` 的状态迁入终态；已关闭幂等返回 |

### 6.4 评测、任务、概览与审计

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/eval/scenarios/runs?limit=` | `eval:read` | 消融运行列表：指标、门禁、失败案例、报告路径 |
| GET | `/eval/scenarios/runs/{run_id}` | `eval:read` | 单次运行详情（含失败案例与报告链接） |
| POST | `/eval/scenarios/run?async=true` | `eval:run` | `{split?, strategies?, limit?}`；数据集取服务端配置；同步 201，异步 202 + `task_id` |
| GET | `/tasks?limit=&owner=` | 已登录 | 当前用户任务列表（24h TTL） |
| GET | `/tasks/{task_id}` | 已登录 | 任务状态与结果；不存在 404 `TASK_NOT_FOUND` |
| GET | `/overview` | 已登录 | 工作台概览：案例状态分布、待办、最近评测 |
| GET | `/audit-logs?action=&actor_id=&limit=` | `audit:read` | 审计日志（载荷已脱敏） |

## 7. 权限矩阵

| 动作 | user | technician | agent | admin |
| --- | --- | --- | --- | --- |
| `case:read_own` | ✓ | ✓ | ✓ | ✓ |
| `case:read_all` |  |  | ✓ | ✓ |
| `case:write` | ✓ |  | ✓ | ✓ |
| `evidence:write` | ✓ | ✓ | ✓ | ✓ |
| `device:manage` / `manual:manage` |  |  | ✓ | ✓ |
| `hypothesis:write` |  |  | ✓ | ✓ |
| `probe:write` |  | ✓ | ✓ | ✓ |
| `diagnosis:finalize` |  |  | ✓ | ✓ |
| `part:read` | ✓ | ✓ | ✓ | ✓ |
| `repair:write` |  | ✓ | ✓ | ✓ |
| `approval:decide` |  |  | ✓ | ✓ |
| `workorder:create` |  |  | ✓ | ✓ |
| `workorder:read` |  | ✓ | ✓ | ✓ |
| `workorder:update` |  | ✓ | ✓ | ✓ |
| `outcome:write` |  | ✓ |  | ✓ |
| `outcome:read` | ✓ | ✓ | ✓ | ✓ |
| `eval:run` / `eval:read` |  |  | ✓ | ✓ |
| `audit:read` |  |  | ✓ | ✓ |

案例归属隔离由 `can_access_case` 统一判定：非 `case:read_all` 角色只能访问自己的案例，
越权返回 403 且不泄露资源内容。

## 8. 调用示例

```bash
BASE=http://localhost:8000/api/v1
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"agent@demo.local","password":"demo1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST $BASE/cases -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"device_model":"AuroraHome AC-Pro 1200","symptom":"风扇有摩擦异响","error_code":"E106"}'
```