# 状态机

V1.2 的案例状态由确定性状态机唯一裁决（`core/workflow/states.py`）。任何模块都不得直接写
`Case.status`，必须调用服务函数，由 `assert_transition` 逐跳校验并落库 `DiagnosticStep` + `AuditLog`。

## 1. 13 个状态

| 状态 | 含义 |
| --- | --- |
| `DRAFT` | 案例已创建，未受理 |
| `COLLECTING_INFO` | 字段已提取、等待补充证据 |
| `EVIDENCE_READY` | 存在可用于推断的证据 |
| `HYPOTHESIZING` | 已生成候选根因，等待检查或结论 |
| `PROBE_PENDING` | 已规划检查，等待执行 |
| `PROBE_EVALUATING` | 检查结果回写处理中（事务内瞬时状态） |
| `DIAGNOSED` | 已生成可追溯的诊断结论 |
| `REPAIR_PLANNING` | 维修方案制定（本轮不展开） |
| `APPROVAL_PENDING` | 审批中（本轮不展开） |
| `WORK_ORDER_CREATED` | 工单已创建（本轮不展开） |
| `OUTCOME_PENDING` | 维修结果回收中（本轮不展开） |
| `NEED_HUMAN` | 证据不足或超步数，转人工 |
| `CLOSED` | 关闭，终态 |

## 2. 合法迁移

| From | To |
| --- | --- |
| DRAFT | COLLECTING_INFO, NEED_HUMAN, CLOSED |
| COLLECTING_INFO | EVIDENCE_READY, NEED_HUMAN |
| EVIDENCE_READY | HYPOTHESIZING, NEED_HUMAN |
| HYPOTHESIZING | PROBE_PENDING, DIAGNOSED, NEED_HUMAN |
| PROBE_PENDING | PROBE_EVALUATING, HYPOTHESIZING, NEED_HUMAN |
| PROBE_EVALUATING | HYPOTHESIZING, PROBE_PENDING, NEED_HUMAN |
| DIAGNOSED | REPAIR_PLANNING, HYPOTHESIZING, NEED_HUMAN |
| REPAIR_PLANNING | APPROVAL_PENDING, NEED_HUMAN |
| APPROVAL_PENDING | WORK_ORDER_CREATED, NEED_HUMAN, CLOSED |
| WORK_ORDER_CREATED | OUTCOME_PENDING, CLOSED |
| OUTCOME_PENDING | CLOSED, NEED_HUMAN |
| NEED_HUMAN | HYPOTHESIZING, APPROVAL_PENDING, CLOSED |
| CLOSED | （终态，无出边） |

除上表之外一律非法，抛 `IllegalTransition`，接口层返回 **409 `ILLEGAL_TRANSITION`**。

## 3. 触发点

| 触发 | 迁移 | 附加副作用 |
| --- | --- | --- |
| `POST /cases/{id}/intake` | `DRAFT→COLLECTING_INFO`；`needs_human` 时 `DRAFT→NEED_HUMAN` | 更新 `extracted/missing_fields/last_question`，写 `DiagnosticStep(intake)` |
| `add_evidence` | `DRAFT→COLLECTING_INFO→EVIDENCE_READY`（逐跳）；已在 `EVIDENCE_READY/HYPOTHESIZING/PROBE_PENDING` 保持不变 | 写证据行、`DiagnosticStep(evidence)`、审计 `evidence.added` |
| `generate_hypotheses` | `EVIDENCE_READY→HYPOTHESIZING` | upsert 假设（`(case_id, cause_code)` 唯一）、写 `DiagnosticStep` |
| `plan_next_probe` | `HYPOTHESIZING→PROBE_PENDING`（插入 pending Probe） | 同一 `(case_id, code)` 不重复；已存在 pending 直接返回 |
| `record_probe_result` | `PROBE_PENDING→PROBE_EVALUATING→HYPOTHESIZING` | 写 `ProbeResult`、证据、更新假设、`step_count+1`、`evidence_version+1`；达到 `MAX_PROBE_STEPS` 转 `NEED_HUMAN` |
| `finalize_diagnosis` | `HYPOTHESIZING→DIAGNOSED` | 写 `DiagnosticStep(diagnosis_finalized)` 与审计 `case.diagnosed` |

## 4. 不变量

1. `PROBE_EVALUATING` 只在单个事务内出现，事务结束前必须离开。
2. `DIAGNOSED` 必须有至少一条 `supported` 且置信级别为 `high`/`medium` 的假设，且结论携带证据链。
3. `step_count` 只由检查结果回写递增，达到 `MAX_PROBE_STEPS`（默认 5）必须转 `NEED_HUMAN`。
4. `evidence_version` 只在证据或假设关联变化时递增，历史判断不覆盖。
5. 重复调用幂等接口（生成假设、规划检查）不得新增行或重复迁移。

## 5. 复查要点

- 非法迁移返回 409 且不写任何业务数据（单事务回滚）。
- 状态推进与业务写入在同一事务内，失败全部回滚。
- 状态历史通过 `DiagnosticStep` 与 `AuditLog` 还原，不依赖日志文本。