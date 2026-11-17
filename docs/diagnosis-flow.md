# 诊断流程

流程是确定性的代码路径，模型只参与字段提取与候选提示，不参与状态迁移与最终判定。

```
受理(intake) → 证据(evidence) → 假设(hypotheses) → 规划(plan) → 结果(result) → 结论(finalize)
```

## 1. 受理（intake）

1. 读取案例的上传，图片/PDF 走 OCR，文本直接解码；合并 `型号 <device.model>` + 症状 + 请求中的 `user_text`。
2. LLM 输出结构化字段：`device_model, serial_number, error_code, symptom, environment, attempted_steps`。
3. 型号必须命中设备档案（全名或去品牌短名）；未命中或 Provider 失败 → `needs_human=true` → `NEED_HUMAN`。
4. 更新 `extracted/missing_fields/last_question`，写 `DiagnosticStep(intake)` 与审计；**不自动生成证据或假设**。
5. 非人工路径 `DRAFT→COLLECTING_INFO`。

字段置信度保留在 `extracted.field_confidence`；低于 `MIN_CONFIDENCE` 的字段进入 `missing_fields` 并在前端提示补采。

## 2. 证据账本

`source_type ∈ {customer, media, manual, probe, model}`，`polarity ∈ {support, refute, neutral}`。

- 只做枚举与空引用校验，不替换标点、不去重；同一事实的相反极性各存一行（冲突保留）。
- `source_type="model"` 的推测不参与支持/反对计数，只用于界面展示。
- 手册事实证据可带 `chunk_id/page/relevance_score`，引用必须能回溯到版本化切片。
- 证据写入把案例推进到 `EVIDENCE_READY`。

## 3. 候选根因与置信

规则树按 `error_code` 展开，`(case_id, cause_code)` 唯一 upsert，重复调用不新增：

| 故障码 | cause_code |
| --- | --- |
| E101 | `POWER_SUPPLY`, `POWER_WIRING` |
| E103 | `NETWORK_CONFIG`, `NETWORK_MODULE` |
| E105 | `COMPRESSOR_FAULT`, `CONDENSER_BLOCKED`, `REFRIGERANT_LEAK` |
| E106 | `FAN_BLOCKED`, `FAN_MOTOR`, `FAN_DRIVER` |
| E108 | `SENSOR_FAULT`, `SENSOR_WIRING` |
| 其他 | `GENERAL_POWER`, `GENERAL_CONTROL` |

支持/反对由证据 `quote` 命中根因关键词与极性决定；`confidence_score = clamp(0.2 + 0.25*support - 0.35*refute, 0, 1)`。

| 条件 | status | confidence_level |
| --- | --- | --- |
| support ≥ 2 且 refute = 0 | supported | high |
| support ≥ 1 且 refute = 0 | open | medium |
| refute > support | rejected | low |
| 其他 | open | low |

界面只展示等级，不展示内部得分。

## 4. 检查规划

候选来自 `PROBE_CATALOG[error_code]`，先做硬过滤：

1. `risk_level == "high"` 永不进入候选；
2. 已执行（同 `case_id` 已存在同 `code` 的 Probe）；
3. `required_tools` 非空（当前无工具台账，一律排除）；
4. 与所有非 rejected 假设的目标交集为空。

其余按 `信息增益 × 执行成功率 − 时间成本 − 风险惩罚 − 工具成本` 确定性排序，同分按 `code` 字典序。
命中项插入 pending `Probe`（唯一 `(case_id, code)`），把案例推进到 `PROBE_PENDING`，返回检查卡片：
问题、目标根因、预期结果、成本、风险、评分与选择理由（含被排除项及原因）。

没有可执行且有区分度的检查时返回 `probe: null`，并写 `DiagnosticStep(probe_exhausted)`。

## 5. 结果回写

1. 观察值必须严格匹配该检查的某个预期结果（归一化空白后比较），否则 422 `INVALID_OBSERVATION`。
2. 由预期结果得出支持/反对的目标根因，生成 `source_type="probe"` 证据并更新假设。
3. `step_count` 与 `evidence_version` 递增；达到 `MAX_PROBE_STEPS` 自动转 `NEED_HUMAN`。
4. `ProbeResult.probe_id` 唯一，重复提交同一检查返回 409 `PROBE_NOT_PENDING`。

## 6. 结论

`finalize_diagnosis` 的判定顺序（任一不满足即 409）：

1. 权限 `diagnosis:finalize`（agent/admin）；
2. 状态 ∈ `{HYPOTHESIZING, PROBE_PENDING}`；`PROBE_PENDING` 且存在 pending 检查 → `PENDING_PROBE`；
3. 取 `status=="supported"` 且 `confidence_level ∈ {high, medium}` 的最高分假设；没有 → `INSUFFICIENT_EVIDENCE`；
4. 若仍有 open 假设、`step_count < MAX_PROBE_STEPS` 且规划存在候选 → `PROBE_AVAILABLE`（先做更有区分度的检查）；
5. 通过后 `HYPOTHESIZING→DIAGNOSED`，写 `DiagnosticStep(diagnosis_finalized)` 与审计 `case.diagnosed`。

结论对象必须携带绑定到该假设的 `support_evidence_ids` 证据链与仍未决的 `unresolved` 列表；
不允许只返回模型文本。`GET /cases/{id}/diagnosis` 为纯读汇总，可随时查看当前证据与候选。

## 7. 人工接管

以下情况转 `NEED_HUMAN`：型号未命中或 Provider 失败造成字段不可信、检查步数达上限、
规划无候选且无达到置信门槛的假设、证据冲突无法用安全检查区分。转人工后仍可从
`NEED_HUMAN→HYPOTHESIZING` 回到诊断流程。