# 真实数据链路演练集（pipeline drill）

> **不是真实维修数据。** 本目录的 60 条记录由 `data/scenarios/v1/scenarios.json` 的前 60 个合成场景派生，
> 仅用于在**独立数据库**中演练 `导入 → 生成场景 → 评测` 全链路，验证脚本、幂等与契约，不产生任何真实业务结论。

## 文件

- `pipeline_drill.jsonl`：60 条 JSONL，字段与 `scripts/import_outcomes.py` 一致。
- 每条记录的 `note` 均标注 `pipeline drill`，案例 `extracted.source` 为 `real`，但内容来自合成场景。

## 生成方式

取合成场景的 `error_code`、`device_model`、`text_only` 现象与 `true_cause_code`，按根因映射处理动作与更换件。
可按以下思路重放（在仓库根目录执行）：

```bash
python - <<'PY'
import json
from pathlib import Path
src = json.loads(Path("data/scenarios/v1/scenarios.json").read_text(encoding="utf-8"))
print(len(src["scenarios"][:60]))
PY
```

## 演练命令（使用独立数据库，不污染 `data/app.db`）

```bash
export DATABASE_URL="sqlite:///./data/drill.db"
python scripts/seed_demo.py --skip-index          # 建 9 台设备与账号
python scripts/import_outcomes.py --file data/outcomes/drill/v1/pipeline_drill.jsonl --dry-run
python scripts/import_outcomes.py --file data/outcomes/drill/v1/pipeline_drill.jsonl
python scripts/import_outcomes.py --file data/outcomes/drill/v1/pipeline_drill.jsonl   # 第二次应全部 skipped
python scripts/build_scenarios_from_real.py --file data/outcomes/drill/v1/pipeline_drill.jsonl --out data/scenarios/drill-v1/scenarios.json
python scripts/eval_scenarios.py --dataset data/scenarios/drill-v1/scenarios.json --strategies A,B,C,D --split holdout
```

> 真实接入时请使用真实维修记录，并把 `actual_cause_code` 限定在冻结根因清单内；
> 本演练集只证明链路可运行，不代表真实场景准确率。

## 最近一次演练结果（2026-11-17）

- 独立库 `data/drill.db`：账号 4 / 设备 9 / 手册 36（`--skip-index`）；导入 60 条，第二次导入 `skipped=60`。
- 生成 `data/scenarios/drill-v1/scenarios.json`：60 场景，holdout 12。
- 评测：C/D 可诊断 Top-1 **100%**、Top-3 100%；A/B Top-1 0%。
- 解释：场景的症状文本只用于受理，检查观察值按真实根因回填；A/B 不执行检查，因此没有可用于收敛的证据。
  该结果验证的是导入、幂等、场景生成与评测契约，**不是**真实数据上的模型/规则效果。
