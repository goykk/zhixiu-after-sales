# 演示脚本

## 1. 场景

`data/scenarios/v1/e106.json`：`AuroraHome AC-Pro 1200` 报 `E106`，真根因 `FAN_BLOCKED`（风扇卡阻）。
场景包含 3 个变体，逐步补充材料，但都必须收敛到同一个根因：

| 变体 | 输入 | 证据 | 用途 |
| --- | --- | --- | --- |
| `text_only` | 纯文字描述 | 2 条客户陈述（支持） | 最简路径：无附件也能走到结论 |
| `with_photo` | 文字 + 出风口照片 | 客户陈述 + 手册事实 | 演示 OCR 型号识别与手册引用 |
| `with_probe_result` | 文字 + 现场拨叶结论 | 1 条客户陈述 | 演示靠检查结果补足证据 |

每个变体的 `probe_answers` 提供 `ASK_SOUND`、`PHOTO_BLADE`、`CHECK_ROTATION` 的观察值，
演示脚本按规划顺序取用。

## 2. 前置

```bash
python scripts/init_db.py
python scripts/seed_demo.py
uvicorn services.api.app.main:app --port 8000
```

`seed_demo.py` 写入演示账号（`agent@demo.local` / `demo1234` 等）与手册索引；后端未启动或
种子未执行时脚本会以 HTTP 错误结束。

## 3. 运行

```bash
python scripts/demo_diagnosis.py --variant text_only
python scripts/demo_diagnosis.py --variant with_photo
python scripts/demo_diagnosis.py --variant with_probe_result

# 指向其他环境
python scripts/demo_diagnosis.py --base-url http://localhost:8000/api/v1 --variant text_only
```

成功输出 `DEMO OK` 并退出码 0；根因不符、变体缺失或任一步失败时退出码 1，并打印失败步骤。

## 4. 输出结构

脚本逐步打印 JSON，每步含 `step` 字段：

| step | 内容 |
| --- | --- |
| `login` | 登录账号 |
| `create_case` | 案例 id 与 `CaseOut` |
| `upload` | 上传记录（仅 `with_photo`） |
| `intake` | 受理后的状态、绑定型号、`needs_human` |
| `evidence_N` | 每条证据的来源与极性 |
| `generate_hypotheses` | 候选根因、状态、置信级别 |
| `plan_probe_N` | 检查卡片（问题、目标根因、预期结果、成本/风险、评分、理由） |
| `probe_result_N` | 观察值、回写结果与状态变化 |
| `final` | 结论：`root_cause`、`evidence_chain`、`unresolved`、`rationale` |

期望终局：`case_status == "DIAGNOSED"`、`root_cause.cause_code == "FAN_BLOCKED"`、
`confidence_level == "high"`、证据链包含客户陈述与检查结果。

## 5. 端到端冒烟

```bash
python scripts/e2e_smoke.py                 # 默认 with_photo，走上传分支
python scripts/e2e_smoke.py --variant text_only
```

步骤：认证 → 创建案例 → 上传 → 受理 → 证据 → 假设 → 规划 → 结果 → 结论，逐步打印 `[n/9]`，
全部通过输出 `E2E OK`。与演示脚本的区别：冒烟只断言链路与终局，不打印卡片细节。
默认使用 `agent@demo.local`（需要 `probe:write` 与 `diagnosis:finalize`，`user` 角色只能提交证据）。

## 6. 失败排查

| 现象 | 排查 |
| --- | --- |
| 连接错误 | 后端是否在 8000 端口启动；`--base-url` 是否带 `/api/v1` |
| `INVALID_CREDENTIALS` | 是否执行过 `scripts/seed_demo.py` |
| 受理后 `NEED_HUMAN` | 型号未命中档案；检查 `AI_PROVIDER=mock` 或 Ollama 可用性 |
| `PROBE_AVAILABLE` 持续出现 | 场景 `probe_answers` 缺少规划中的检查观察值 |
| `INSUFFICIENT_EVIDENCE` | 证据未命中 E106 关键词，或变体被改动导致支持不足 2 条 |
| 根因与真根因不符 | 观察值选错（例如 `CHECK_ROTATION` 选了“旋转顺畅”会给 `FAN_DRIVER` 加分） |

排查时可先看 `GET /api/v1/cases/{id}/diagnosis` 的 `evidence/hypotheses`，
再对照 [diagnosis-flow.md](diagnosis-flow.md) 的置信规则。

## 7. 演示讲稿顺序

1. 展示场景文件与真根因，说明三变体只改变输入形态。
2. 跑 `text_only`：强调没有附件也能依靠证据与检查得到结论。
3. 跑 `with_photo`：指出 OCR 识别型号、手册切片引用的版本与页码。
4. 打开前端 `/cases/[id]`：证据账本、候选根因支持/反对、检查卡片与结论区。
5. 说明结论不可绕过：无支持证据返回 `INSUFFICIENT_EVIDENCE`，仍有安全高增益检查返回 `PROBE_AVAILABLE`。