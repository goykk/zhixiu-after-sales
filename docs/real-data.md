# 真实维修记录接入（R31）

当前仓库中的 80 场景与 20 条维修结果均为**合成数据**。真实数据接入路径如下；在提供真实记录前，路径已可运行（含模板与校验），但不会产生真实业务结论。

## 1. 数据格式（JSONL，每行一个对象）

必填：
- `error_code`（须存在于检查目录 `PROBE_CATALOG`）
- `device_model`（须已建档的演示型号）
- `case_symptom`（非空）
- `actual_cause_code`（须为冻结 cause_code）
- `action`

可选：`parts_replaced`（数组）、`resolved`（布尔）、`note`。
模板：`data/outcomes/real/v1/sample_template.jsonl`（3 行，标注为模板）。

## 2. 导入维修结果

```bash
python scripts/import_outcomes.py --file <real.jsonl> --dry-run   # 仅校验与统计，不写库
python scripts/import_outcomes.py --file <real.jsonl>            # 幂等导入
python scripts/import_outcomes.py --file <real.jsonl> --json
```

- 校验：缺字段 / 未知根因 / 型号未建档 / `parts_replaced` 非数组 → 记 `invalid` 并跳过，退出码 1。
- 幂等：`idempotency_key = real-<记录 sha1>`，重复导入跳过（`skipped`）。
- 产物：`Case(status=WORK_ORDER_CREATED)` + `WorkOrder(status=resolved)` + `RepairOutcome`，案例 `extracted.source="real"`。

## 3. 由真实记录生成场景集

```bash
python scripts/build_scenarios_from_real.py --file <real.jsonl> --out data/scenarios/real-v1/scenarios.json
python scripts/build_scenarios_from_real.py --file <real.jsonl> --dry-run
```

- 有效记录须 ≥ **60**（场景集契约 60–80）；不足时退出码 1 并打印原因。
- 自动派生 3 个变体（text_only/with_photo/with_probe_result）、holdout 按 id 哈希取 20%。
- 写出后用 `core.simulator.loader.load_scenarios` 自校验（型号/根因/变体 id/枚举/留出比例）。
- 随后可直接运行 `scripts/eval_scenarios.py --dataset data/scenarios/real-v1/scenarios.json --strategies A,B,C,D --split holdout`。

## 4. 验证

```bash
python -m pytest tests/test_realdata.py -q
```

覆盖：dry-run 不写库、非法记录报告、导入幂等、数据不足报错、60 条记录生成可加载数据集（holdout=12）。

## 5. 说明

- 接入真实记录不会自动改口径：`actual_cause_code` 必须来自冻结清单，否则整条跳过。
- 场景生成只是格式转换与采样，不引入任何模型推断；真实业务效果需以真实 holdout 重新评测。