# 真实维修记录接入（R31）

当前仓库中的 80 场景与 20 条维修结果均为**合成数据**。真实数据接入路径如下；在提供真实记录前，路径已可运行（含模板与校验），但不会产生真实业务结论。

## 1. 数据格式（JSONL，每行一个对象）

必填：
- `error_code`（须存在于检查目录 `PROBE_CATALOG`）
- `device_model`（须已在目标库建档；`seed_demo.py` 默认建 9 个演示型号）
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
- 检查观察值按真实根因回填：优先选 `supports` 命中该根因的观察；否则选不反驳该根因、且尽量反驳混淆根因的观察；
  覆盖该故障码全部低/中风险检查，避免 planner 继续规划时缺少答案而留下 pending probe。
- 写出后用 `core.simulator.loader.load_scenarios` 自校验（型号/根因/变体 id/枚举/留出比例）。
- 随后可直接运行 `scripts/eval_scenarios.py --dataset data/scenarios/real-v1/scenarios.json --strategies A,B,C,D --split holdout`。

## 4. 链路演练（不是真实数据）

`data/outcomes/drill/v1/pipeline_drill.jsonl` 的 60 条记录由合成场景派生，只用于在独立数据库
（`data/drill.db`）验证 `导入 → 幂等 → 生成场景 → 评测`：

```bash
export DATABASE_URL="sqlite:///./data/drill.db"
python scripts/seed_demo.py --skip-index
python scripts/import_outcomes.py --file data/outcomes/drill/v1/pipeline_drill.jsonl --dry-run
python scripts/import_outcomes.py --file data/outcomes/drill/v1/pipeline_drill.jsonl
python scripts/import_outcomes.py --file data/outcomes/drill/v1/pipeline_drill.jsonl   # skipped=60
python scripts/build_scenarios_from_real.py --file data/outcomes/drill/v1/pipeline_drill.jsonl --out data/scenarios/drill-v1/scenarios.json
python scripts/eval_scenarios.py --dataset data/scenarios/drill-v1/scenarios.json --strategies A,B,C,D --split holdout
```

演练结果：C/D 可诊断 Top-1 100%、Top-3 100%；A/B Top-1 0%，因为单轮策略没有检查回写证据，
只有症状文本。该结果只证明链路与契约可运行，观察值是按真因回填的，**不能当作真实诊断准确率**。

## 5. 验证

```bash
python -m pytest tests/test_realdata.py -q
```

覆盖：dry-run 不写库、非法记录报告、导入幂等、数据不足报错、60 条记录生成可加载数据集（holdout=12）。

## 6. 说明

- 接入真实记录不会自动改口径：`actual_cause_code` 必须来自冻结清单，否则整条跳过。
- 场景生成只做格式转换、划分与按检查目录回填观察值，不引入任何模型推断；真实业务效果需以真实 holdout 重新评测。
- 演练集必须与真实数据分开存放；不要把 `data/outcomes/drill/` 的指标写进交付结论。