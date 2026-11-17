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
| 422 | `VALIDATION_ERROR` | 请求体校验失败 |
| 422 | `UPLOAD_REJECTED` | 上传类型/大小/内容不合法（不落盘） |
| 422 | `INVALID_EVIDENCE` | 证据枚举非法或 quote 为空 |
| 422 | `INVALID_OBSERVATION` | 观察值不匹配该检查的预期结果 |
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

## 6. 权限矩阵

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
| `audit:read` |  |  | ✓ | ✓ |

案例归属隔离由 `can_access_case` 统一判定：非 `case:read_all` 角色只能访问自己的案例，
越权返回 403 且不泄露资源内容。

## 7. 调用示例

```bash
BASE=http://localhost:8000/api/v1
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"agent@demo.local","password":"demo1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST $BASE/cases -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"device_model":"AuroraHome AC-Pro 1200","symptom":"风扇有摩擦异响","error_code":"E106"}'
```