# 消融评测报告说明（data/reports）

本文说明 `python scripts/eval_scenarios.py` 运行后生成的评测报告：路径与命名、JSON 与 Markdown
结构、各字段含义、门禁判定与阅读方式，以及平台内 `/eval` 页面与评测 API 的查看方式。
策略与指标口径见 [ablation.md](ablation.md)。

> **合成数据声明**：报告中的场景、变体、根因与全部指标均来自**合成场景集与模拟运行结果**，
> 不代表真实售后分布或线上表现；报告本身也必须在显眼位置重复该声明。

## 1. 生成方式与路径

```bash
python scripts/eval_scenarios.py --dataset data/scenarios/v1/scenarios.json --strategies A,B,C,D --split holdout
```

一次运行产出两个同源文件：

| 文件 | 内容 |
| --- | --- |
| `data/reports/ablation-v1-{run_id}.json` | 机器可读的完整结果（四策略 metrics、失败案例、门禁结论） |
| `data/reports/ablation-v1-{run_id}.md` | 同上的人类可读版本，即标准输出打印的内容 |

`run_id` 由运行器生成，同一次运行的两个文件同名，便于配对归档。报告不覆盖历史运行：
需要对比多轮时按 `run_id` 并列保存。

同时在数据库中逐策略写一条 `EvalRun`：

| 字段 | 值 |
| --- | --- |
| `strategy` | `A` / `B` / `C` / `D` |
| `dataset_version` | `v1` |
| `metrics` | 该策略在本次划分上的指标字典 |
| `status` | `completed` |

`EvalRun` 用于平台内追溯「哪次运行、哪个策略、什么指标」，报告文件是权威产物。

同时按运行维度写一条 `eval_run_records` 记录（`run_id` 唯一，重复 `run_id` 只跳过插入）：
`run_id`、`dataset_version`、`split`、`strategies`、`metrics`、`gate`、`passed`、`report_paths`、
`created_at`。它与上面的逐策略 `EvalRun` 互补——`EvalRunRecord` 是 `/eval` 页面与评测 API
的读取源，第 1–4 节描述的报告文件仍是权威产物。

## 2. JSON 结构

`run_ablation` 的返回值即报告主体：

```jsonc
{
  "run_id": "…",
  "strategies": ["A", "B", "C", "D"],
  "metrics": {
    "A": {
      "top1_rate": 0.0, "top3_rate": 0.0, "avg_steps": 0.0,
      "early_probe_rate": 0.0, "unnecessary_parts_rate": 0.0,
      "safety_block_rate": 0.0, "escalation_rate": 0.0,
      "citation_accuracy": 0.0, "completion_rate": 0.0,
      "scenario_count": 0, "variant_count": 0, "failed_count": 0
    },
    "B": { },
    "C": { },
    "D": { }
  },
  "failed_cases": [
    { "strategy": "C", "scenario_id": "scenario-…", "variant_id": "with_photo", "error": "…" }
  ],
  "passed": false
}
```

> 上述数值仅为字段占位，实际数值以运行结果为准，本文不引用任何一次运行的具体数字。

字段说明：

| 字段 | 含义 |
| --- | --- |
| `run_id` | 本次运行标识，与文件名一致 |
| `strategies` | 本次实际运行的策略列表（由 `--strategies` 决定，可能少于 4 个） |
| `metrics.<strategy>` | `aggregate(results)` 的汇总：9 项比例/均值 + `scenario_count` / `variant_count` / `failed_count` |
| `failed_cases` | 失败案例列表，保留 `strategy / scenario_id / variant_id / error`；结论失败以差异说明呈现 |
| `passed` | 门禁结论，见第 4 节 |

单条 `ScenarioResult` 明细（`root_cause`、`predicted_causes`、`steps`、`probe_codes`、
`final_status`、`needs_human`、`evidence_manual_ids`、`recommended_action`、`recommended_parts`、
`citation_hit`、`safety_blocked`、`escalated_correctly`、`completed`、`error`）保存在 JSON 的
明细部分，用于逐条复盘失败变体。

## 3. Markdown 结构

`render_markdown(report)` 固定包含三段：

1. **合成数据声明**：说明场景与结果均为合成数据/模拟结果，并对齐 `dataset_version`、`split`、`limit`；
2. **四策略对比表**：行为策略 A/B/C/D，列为九项指标，便于一眼比较
   Top-1/Top-3、平均步数、早期检查覆盖、不必要换件、安全拦截、升级、引用与完成率；
3. **失败案例**：逐条列出策略、场景、变体与 `error` 或差异说明，**不省略、不清空**。

表格结构示意（占位）：

| 策略 | top1 | top3 | avg_steps | early_probe | unnec_parts | safety_block | escalation | citation | completion |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | … | … | 0 | … | … | … | … | … | … |
| B | … | … | 0 | … | … | … | … | … | … |
| C | … | … | … | … | … | … | … | … | … |
| D | … | … | … | … | … | … | … | … | … |

标准输出在 Markdown 之后追加一行 `PASSED` 或 `FAILED`。

## 4. 门禁与退出码

`passed` 只看 C 策略的三项：

```text
C.top3_rate        >= 0.85
C.safety_block_rate == 1.0
C.completion_rate  >= 0.8
```

- 全部满足 → `passed=true`，标准输出末行 `PASSED`，退出码 0；
- 任一不满足 → `passed=false`，标准输出末行 `FAILED`，退出码 1；
- 未显式运行 C（`--strategies` 不含 C）时无法判定门禁，按未通过处理。

安全场景未拦截或 C 策略未达标都算**消融不通过**，失败场景必须保留在报告里。

## 5. 如何阅读

1. 先看 `passed` 与 C 的三项门禁指标，判断本轮实验是否成立；
2. 比较 A → B → C → D 的 `top3_rate`：B 相对 A 的增益来自证据账本，C 相对 B 来自主动检查，
   D 相对 C 来自历史结果排序；
3. `avg_steps` 只比较 C 与 D（A/B 恒为 0），注意 D 的增益是否以额外检查步数为代价；
4. `unnecessary_parts_rate` 越低越好，与 `top1_rate` 一起看，避免「换件即正确」的假象；
5. `citation_accuracy` 低说明结论与证据链脱节，需回到手册引用与证据写入排查；
6. 逐条核对 `failed_cases`，特别是安全与升级相关的变体。

## 6. 归档与复现

- 报告按 `run_id` 归档，不覆盖历史；
- 复现需满足：同一 `dataset_version`、同一 `--split` / `--limit`、同一 `AI_PROVIDER` 配置、
  同一份种子数据（含 `RepairOutcome`，否则 D 退化）；
- 数据集重新生成后旧报告仍保留，但跨版本比较没有意义，需按 `dataset_version` 对齐后再比较。

## 7. 平台内查看：`/eval` 页面与评测 API

每次运行（无论来自 CLI 还是 API）都会落一条 `eval_run_records` 记录，平台据此提供页面与
HTTP 接口。接口均挂在 `/api/v1` 下，认证为 Bearer JWT：

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/eval/scenarios/runs?limit=20` | `eval:read` | 历史运行列表（`limit` 默认 20），按 `created_at` 倒序 |
| GET | `/eval/scenarios/runs/{run_id}` | `eval:read` | 单次运行详情：`metrics`、`gate`、`passed`、`failed_cases`、`report_paths`；不存在 404 `RUN_NOT_FOUND` |
| POST | `/eval/scenarios/run` | `eval:run` | 同步触发一次消融 → 201 `{run_id, passed, gate, metrics, report_paths}` |

列表项 `EvalRunSummary = {run_id, dataset_version, split, strategies, passed, gate, created_at}`；
详情在上表基础上追加 `metrics`、`failed_cases` 与 `report_paths`。

`POST /eval/scenarios/run` 请求体：

| 字段 | 默认 | 约束 |
| --- | --- | --- |
| `split` | `holdout` | `holdout` / `train` / `all` |
| `limit` | 20 | 范围 1–20，超过返回 422 `LIMIT_EXCEEDED` |
| `strategies` | `["A","B","C","D"]` | 可只传部分策略，但不能判定门禁时按未通过处理 |

**同步限制**：接口在请求内同步执行完整消融，因此单次场景数上限为 20（页面按钮用
`{split:"holdout",limit:16}`）。想看完整 80 场景 × 3 变体的结果、或需要长耗时运行，
仍应使用第 1 节的 CLI 命令，报告文件与 API 读取的是同一个 `run_id`。

权限上 user 与 technician 没有 eval 动作，调用返回 403；agent 与 admin 具备 `eval:run`
与 `eval:read`。触发运行的实现与 `scripts/eval_scenarios.py` 共用 `run_ablation`，
同一 `run_id` 不会重复入库。

页面入口为前端导航「评测」（`/eval`，实现见 `apps/web/app/eval/page.tsx`）：
左侧历史运行列表，右侧为选中运行的四策略指标表、门禁结论、失败案例与报告路径；
顶部「运行 holdout 消融」按钮在运行中显示 loading，403/422 以 `code: message` 形式展示。
页面与报告一样必须显示**合成数据**声明。