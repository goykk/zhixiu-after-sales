# 验收报告（智修 V1.2）

生成时间：2026-11-16T08:10:57.385417+00:00 ｜ AI provider：mock

> **合成数据声明**：本报告的场景、配件、维修结果与评测均为模拟数据，仅用于内部验收，不代表真实业务效果。

结论：**PASSED**（PASS 8 / FAIL 0 / SKIP 0）

## 验收步骤

| 步骤 | 状态 | 耗时(s) | 详情 |
| --- | --- | --- | --- |
| env | PASS | 2.62 | core import ok; redis SKIP (ConnectionError); otel available=True; db=sqlite:///./data/app.db; ocr_provider=mock; provider=mock |
| init_db | PASS | 0.88 | rc=0; 已删除 data\app.db 数据库已就绪：sqlite:///./data/app.db 共 19 张表：approvals, audit_logs, cases, devices, diagnostic_steps, document_chunks, eval_run_records, eval_scenarios, evidence, hypotheses, manuals, part_compatibilities, parts, probe_results, probes, repair_outcomes, uploads, users, work_orders |
| seed | PASS | 3.92 | seed_demo.py rc=0 \| seed_parts.py rc=0 \| seed_outcomes.py rc=0 |
| api_smoke | PASS | 7.45 | demo_diagnosis.py text_only rc=0 \| demo_diagnosis.py with_photo rc=0 \| demo_diagnosis.py with_probe_result rc=0 \| demo_full_closure.py rc=0 \| e2e_smoke.py rc=0 |
| ablation | PASS | 8.98 | rc=0; ith_photo \| POWER_SUPPLY \| POWER_WIRING \| 3 \| DIAGNOSED \| - \| \| D \| sc-069-ventocool-fz-30-e101-power-supply \| with_probe_result \| POWER_SUPPLY \| POWER_WIRING \| 3 \| DIAGNOSED \| - \| 报告文件：`data\reports\ablation-v1-20261116T080955-1da89e.json`、`data\reports\ablation-v1-20261116T080955-1da89e.md` PASSED |
| ocr | PASS | 27.36 | el: ('PP-OCRv6_medium_rec', None, None) Model files already exist. Using cached files. To redownload, please delete the directory manually: `C:\Users\goy\.paddlex\official_models\PP-OCRv6_medium_rec`. |
| otel | PASS | 0.45 | OTEL OK |
| frontend | PASS | 26.7 | rc=0;  |

## 已知限制

- 全部数据为模拟数据；真实维修记录未接入。
- 可选路径（pgvector / Celery / OCR / OTel / LangGraph）在缺少依赖或服务时记 SKIP。
- 消融基于 80 场景 × 3 变体的合成场景集。
