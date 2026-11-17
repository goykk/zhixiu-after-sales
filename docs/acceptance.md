# 一键验收（R29）

`scripts/acceptance.py` 按固定顺序跑一遍关键验收并生成报告，用于评审与回归。

## 1. 用法

```bash
python scripts/acceptance.py --skip-heavy --json      # 快速：跳过消融/OCR/前端
python scripts/acceptance.py                          # 完整（不含前端）
python scripts/acceptance.py --with-frontend          # 追加前端 tsc 检查
python scripts/acceptance.py --provider ollama        # 用真实本地模型跑 API 冒烟
python scripts/acceptance.py --no-reset               # 不重建数据库
```

- `--provider mock|ollama`：API 冒烟使用的 AI provider（默认 mock）。
- `--skip-heavy`：跳过消融、OCR、前端；便于快速回归。
- `--with-frontend`：执行 `npx tsc --noEmit`（cwd `apps/web`）。
- `--no-reset`：`init_db` 不带 `--reset`。
- `--json`：stdout 只输出汇总 JSON。

任一 `FAIL` → 整体 `passed=false`，退出码 1；只要没有 FAIL（允许 SKIP）→ 退出码 0。

## 2. 步骤

| 步骤 | 内容 | 失败/跳过规则 |
| --- | --- | --- |
| env | Python/`core` 导入、DB URL、Redis ping、OTel 可用性、provider/OCR | `core` 导入失败→FAIL；Redis/OTel 不可用→SKIP |
| init_db | `scripts/init_db.py`（可选 `--reset`） | 非零→FAIL |
| seed | `seed_demo` + `seed_parts` + `seed_outcomes`（mock） | 非零→FAIL |
| api_smoke | 起 uvicorn(8123) → 三变体 demo_diagnosis + demo_full_closure + e2e_smoke | 任一非零→FAIL |
| ablation | `eval_scenarios.py`（holdout，A/B/C/D） | 非 PASSED→FAIL；`--skip-heavy`→SKIP |
| ocr | `check_ocr.py --json` | 不可用→SKIP；`--skip-heavy`→SKIP |
| otel | `check_otel.py --exporter console` | 失败→SKIP（可选能力） |
| frontend | `npx tsc --noEmit` | 仅 `--with-frontend` 时执行，否则 SKIP |

## 3. 报告

- JSON：`data/reports/acceptance-{YYYYmmddTHHMMSS}.json`
- Markdown：默认 `docs/acceptance-report.md`（可用 `--report` 指定）
- Markdown 首段包含 **合成数据声明**，随后是结论、步骤表与已知限制。

## 4. 说明

- 脚本不引入新依赖；全部通过子进程调用既有脚本与 `npx`。
- API 冒烟在子进程中临时启动 `uvicorn`，结束即终止，不影响已运行的 8000 端口服务。
- 报告中的场景、配件、维修结果与评测均为模拟数据。