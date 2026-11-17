# 诊断场景集与 A/B/C/D 策略消融（R20）

本文说明 V1.2 的场景集、四种诊断策略的差异、消融指标口径、运行方法与失败案例处理。
契约依据：`design-sim.md` §A R20 与 §B C-SIM@1（B.1–B.7）。

> **合成数据声明**：`data/scenarios/v1/scenarios.json` 的 80 个场景（240 个变体）与
> `data/reports/` 下的消融结果**均为合成数据与模拟结果**，用于在同一配置下横向比较策略，
> 不代表真实售后工单分布，也不能当作线上诊断准确率的估计。

## 1. 场景集

### 1.1 文件与结构

`data/scenarios/v1/scenarios.json`：

```jsonc
{
  "dataset_version": "v1",
  "scenarios": [
    {
      "id": "scenario-...",
      "device_model": "AuroraHome AC-Pro 1200",
      "error_code": "E106",
      "true_cause_code": "FAN_BLOCKED",
      "confusable_causes": ["FAN_MOTOR", "FAN_DRIVER"],
      "risk_flags": [],                 // 含 "high" 表示安全场景
      "holdout": true,
      "variants": [
        {
          "id": "text_only",            // text_only | with_photo | with_probe_result
          "symptom": "...",
          "evidence": [{ "source_type": "customer", "polarity": "support", "quote": "..." }],
          "probe_answers": { "ASK_SOUND": "...", "PHOTO_BLADE": "..." },
          "expected_probe_codes": ["PHOTO_BLADE", "CHECK_ROTATION"],
          "expected_escalation": false,
          "expected_evidence_manual_ids": ["..."]
        }
      ]
    }
  ]
}
```

约束（加载时校验，违反抛 `ValueError`）：

- 场景数在 60–80 之间，每场景恰好 3 个变体，变体 `id` 为 `text_only` / `with_photo` / `with_probe_result`；
- `true_cause_code` 属于冻结的 `cause_code` 清单（见 [diagnosis-flow.md](diagnosis-flow.md) §3）；
- `device_model` 属于 5 个演示型号：`AuroraHome AC-Pro 1200`、`AuroraHome AC-Mini 600`、
  `NovaDesk PX-220`、`NovaDesk PX-450`、`VentoCool FZ-30`；
- `holdout=true` 占 20%±1（80 场景即 16 个）；
- `probe_answers` 覆盖该故障码 `PROBE_CATALOG` 中至少 2 个检查，且至少一个期望检查在规划的前 3 位。

### 1.2 生成方式

```bash
python scripts/build_scenarios.py
# 输出 data/scenarios/v1/scenarios.json，同时打印场景数 / 变体数 / holdout 数
```

生成器是确定性的（同版本重复执行产出同一份文件），按其构成 80 个场景：

| 组成 | 数量 | 说明 |
| --- | --- | --- |
| 基础 | 60 | 5 个演示型号 × 12 个演示故障码 |
| 困难 | 10 | 与 `confusable_causes` 高度混淆，需要区分度高的检查才能收敛 |
| 安全 | 5 | `risk_flags` 含 `high`，期望被拦截并转人工 |
| 边界 | 5 | 证据稀疏/冲突，期望在步数上限内转人工 |

holdout 按场景序号每 5 个取 1 标记，因此起点即 20% 留出。

### 1.3 划分

`split_scenarios(scenarios, split)` 支持三种取值：

| split | 返回 | 用途 |
| --- | --- | --- |
| `holdout` | `holdout=true` 的场景 | 消融默认口径，避免调参泄漏 |
| `train` | `holdout=false` 的场景 | 可作为 D 策略历史权重的来源场景 |
| `all` | 全部场景 | 全量回归 |

## 2. 四种策略

同一场景、同一变体、同一配置下横向运行，唯一差异是策略路径：

| 策略 | 名称 | 路径 | 典型特征 |
| --- | --- | --- | --- |
| A | RAG-only 基线 | 按规则树生成候选根因，不规划、不写 probe | `steps` 恒为 0；最高候选为 `high` 时 `DIAGNOSED`，否则 `NEED_HUMAN` |
| B | 证据账本 + 状态机 | 证据 → 假设 → `finalize_diagnosis`（不规划） | `steps` 恒为 0；靠证据支持/反对计数收敛 |
| C | + 主动检查规划 | 证据 → 假设 → 循环 `plan_next_probe` / `record_probe_result`（用场景 `probe_answers`）→ `finalize_diagnosis` | `steps` 为实际执行的检查数 |
| D | + 结果感知排序 | 同 C，但用 `RepairOutcome.actual_cause_code` 对同 `error_code` 的历史根因加权排序 | 无历史时退化为 C；不得改变安全规则与转人工判定 |

要点：

- 每个变体在**独立隔离案例**中运行，结束后清理，策略间不共享案例状态；
- A/B 不产生检查步数，因此 `avg_steps` 的对比只在 B → C/D 之间有意义；
- D 的权重唯一来源是历史维修结果表 `RepairOutcome`，**不得**读取场景的 `true_cause_code`，否则消融失效；
- 任何 `ProviderError` / `IllegalTransition` 记入 `ScenarioResult.error` 并计为失败，不中断整体运行。

## 3. 指标口径

单条结果 `ScenarioResult` 记录：`strategy`、`scenario_id`、`variant_id`、`root_cause`、
`predicted_causes`、`steps`、`probe_codes`、`final_status`、`needs_human`、`evidence_manual_ids`、
`recommended_action`、`recommended_parts`、`citation_hit`、`safety_blocked`、`escalated_correctly`、
`completed`、`error`。

| 指标 | 口径 |
| --- | --- |
| `top1_rate` | 首选根因（`root_cause` / `predicted_causes[0]`）等于 `true_cause_code` 的变体占比 |
| `top3_rate` | `true_cause_code` 出现在 `predicted_causes` 前 3 的变体占比 |
| `avg_steps` | 变体平均实际检查步数（`steps`）；A/B 恒为 0 |
| `early_probe_rate` | `expected_probe_codes` 中任一出现在 `probe_codes[:3]` 的变体占比（高区分度检查的前 3 步覆盖率） |
| `unnecessary_parts_rate` | `recommended_action == "replace_part"` 且 `true_cause_code` 不属于 `PARTS_REQUIRED_CAUSES` 的变体占比（不必要配件更换率） |
| `safety_block_rate` | `risk_flags` 含 `high` 的安全变体中被拦截（`safety_blocked`）的占比 |
| `escalation_rate` | `expected_escalation=true` 的变体中 `escalated_correctly`（既 `needs_human` 又应升级）的占比 |
| `citation_accuracy` | `citation_hit=true` 的变体占比（结论引用命中该变体期望的手册证据 `expected_evidence_manual_ids`） |
| `completion_rate` | `completed=true` 的变体占比（无 `ProviderError` / `IllegalTransition` 且流程走完） |

`PARTS_REQUIRED_CAUSES`：

```python
{FAN_MOTOR, FAN_DRIVER, POWER_SUPPLY, POWER_WIRING, NETWORK_MODULE,
 COMPRESSOR_FAULT, SENSOR_FAULT, SENSOR_WIRING, CONTROL_BOARD}
```

不在该集合中的根因（如 `FAN_BLOCKED`、`CONDENSER_BLOCKED`、`NETWORK_CONFIG`）应通过清洁/配置修复，
据此推荐换件即计为不必要更换。

`aggregate(results)` 汇总上述比例，并额外给出 `scenario_count`、`variant_count`、`failed_count`；
空结果集返回零值，不抛异常。

## 4. 运行消融

前置：已完成 `python scripts/init_db.py` 与 `python scripts/seed_demo.py`；
D 策略的历史权重需要 `python scripts/seed_outcomes.py` 写入 `RepairOutcome`（否则 D 退化为 C）。
默认本机 Ollama 可用时直接运行；无模型时在 `.env` 设 `AI_PROVIDER=mock` 得到确定性输出。

```bash
# 默认：holdout 划分，四策略全跑
python scripts/eval_scenarios.py --dataset data/scenarios/v1/scenarios.json --strategies A,B,C,D --split holdout

# 小样本快速自检
python scripts/eval_scenarios.py --dataset data/scenarios/v1/scenarios.json --strategies A,B,C,D --split holdout --limit 8
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--dataset` | — | 场景集路径，示例取 `data/scenarios/v1/scenarios.json` |
| `--strategies` | `A,B,C,D` | 逗号分隔的策略子集 |
| `--split` | `holdout` | `holdout` / `train` / `all` |
| `--limit` | 不限 | 只取前 N 个场景（调试用） |

行为：

1. 逐策略写一条 `EvalRun(strategy=..., dataset_version="v1", metrics=..., status="completed")`；
2. 生成 `data/reports/ablation-v1-{run_id}.json` 与同名 `.md`；
3. 标准输出打印 Markdown 报告，最后一行 `PASSED` 或 `FAILED`；
4. 未达门禁退出码为 1，可直接用于 CI 或验收脚本。

门禁（`passed`）同时要求 C 策略：

```text
C.top3_rate        >= 0.85
C.safety_block_rate == 1.0
C.completion_rate  >= 0.8
```

任一不满足即 `passed=false`。安全场景未拦截（`safety_block_rate < 1.0`）或 C 策略未达标均判为
**消融不通过**，且报告中必须保留失败场景，便于逐条复盘。

## 5. 失败案例

失败分为两类，都保留在报告里：

| 类型 | 判定 | 读取字段 |
| --- | --- | --- |
| 流程失败 | 变体运行抛 `ProviderError` / `IllegalTransition` | `ScenarioResult.error`，`completed=false` |
| 结论失败 | 流程走完但指标不如预期（如 `top1/top3` 未命中、安全未拦截、期望升级未升级） | `predicted_causes`、`final_status`、`needs_human`、`safety_blocked` |

`run_ablation` 返回 `failed_cases` 列表，Markdown 报告含「失败案例」章节逐条列出
`strategy / scenario_id / variant_id / error 或差异说明`。

排查顺序建议：

1. 先看 `failed_count` 与 `completion_rate`：若大面积流程失败，先确认 Provider 与数据库种子数据；
2. 单条 `error` 指出具体异常，从 `DiagnosticStep` 时间线复现该变体；
3. `top1_rate` 低但 `top3_rate` 高，通常是候选排序问题（D 的权重方向、证据关键词命中）；
4. `early_probe_rate` 低说明 `PROBE_CATALOG` 的评分没把区分度高的检查排进前 3；
5. `safety_block_rate < 1.0` 属于门禁级问题：检查安全场景的 `risk_flags` 是否被规则读取、是否被
   `plan_next_probe` / 转人工判定短路；
6. `escalation_rate` 低通常是步数上限或 `final_status` 与 `needs_human` 不一致。

失败案例不得删除或改写场景数据来「通过」；确属场景标注错误的，修正数据集并重跑全量。

## 6. 复现性与边界

- 四个策略使用同一份场景文件、同一 `AI_PROVIDER` 配置与同一份种子数据；
- 每变体独立案例、运行后清理，策略间不可见彼此状态；
- D 的加权只能来自 `RepairOutcome`，任何形式的场景答案泄漏都会使消融结论失效；
- 场景集生成是确定性的，`build_scenarios.py` 重跑不改变同版本数据集；
- 结果与场景均为**合成数据/模拟结果**，结论只用于内部策略选型，不用于对外宣称诊断准确率。

报告字段与阅读方法见 [eval-report.md](eval-report.md)。