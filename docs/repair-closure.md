# 维修闭环（R15–R19）

本文说明 V1.2 在「诊断结论」之后继续推进的维修闭环：配件兼容性与库存 → 维修方案 →
提交审批 / 审批决定 → 幂等工单 → 真实维修结果回收 → 关闭案例。全链路通过 REST 接口驱动，
状态迁移仍由 `core/workflow/states.py` 唯一裁决。

## 1. 模拟数据声明

以下内容**全部为演示用模拟数据**，不是真实供应链、库存或外部工单系统结果：

- `data/parts/v1/catalog.json`：5 个演示型号的配件目录、库存状态、硬件适用区间与兼容关系；
- `PartCompatibility` 中的替代关系与证据来源（`servicenote:*`、`manual:*`、`模拟数据：*`）；
- 外部工单号（`SIM-0001` 等）与工单状态；
- `data/outcomes/v1/sample_outcomes.json` 的 20 条维修结果（`source="simulated"`）。

> 演示库现有 9 台设备、36 份手册；配件目录只覆盖其中 5 个有维修闭环演练数据的型号
> （AC-Pro 1200、AC-Mini 600、PX-220、PX-450、FZ-30）。其余型号可诊断、可检索，但维修方案
> 不会给出兼容配件，需先补配件目录。

本轮不接真实外部工单系统，闭环止于 `WORK_ORDER_CREATED → OUTCOME_PENDING → CLOSED`。

## 2. 配件目录与兼容性

### 2.1 演示型号与主件号

| 型号 | 主件（每型号另有 1 个 `-R2` 替代件） |
| --- | --- |
| AuroraHome AC-Pro 1200 | FAN-BLADE-KIT、FAN-MOTOR-ASSY、FAN-DRIVER-BOARD、POWER-SUPPLY-UNIT |
| AuroraHome AC-Mini 600 | FAN-BLADE-KIT、FAN-MOTOR-ASSY、POWER-WIRING-HARNESS、SENSOR-KIT |
| NovaDesk PX-220 | POWER-SUPPLY-UNIT、CONTROL-BOARD、SENSOR-KIT、WIFI-MODULE |
| NovaDesk PX-450 | POWER-SUPPLY-UNIT、CONTROL-BOARD、WIFI-MODULE、SENSOR-HARNESS |
| VentoCool FZ-30 | COMPRESSOR-UNIT、CONDENSER-FILTER、POWER-WIRING-HARNESS、SENSOR-HARNESS |

替代件使用 `<主件号>-R2`（如 `FAN-MOTOR-ASSY-R2`）。`catalog.json` 每个型号显式包含
4 个主件 + 1 个 `-R2` 替代件（AC-Pro 1200/AC-Mini 600 → `FAN-MOTOR-ASSY-R2`，
PX-220 → `CONTROL-BOARD-R2`，PX-450 → `WIFI-MODULE-R2`，FZ-30 → `COMPRESSOR-UNIT-R2`），
`seed_parts.py` 一并写入 `Part` 与 `PartCompatibility`（模拟库存 `in_stock`），使
`check_part_compatibility` 能命中原件、替代件与兼容关系。

### 2.2 兼容性类型

`compatibility_type ∈ {equivalent, replacement, requires_adapter, incompatible, unknown}`：

- `replacement` / `equivalent`：可直接或等效替换，`alternatives` 返回库存为 `in_stock` 的替代件；
- `requires_adapter`：需转接件，方案中提示但不作为首选；
- `incompatible`：不可互替，含该配件的维修方案 `parts_compatible=False`，不得被推荐；
- `unknown`：型号或配件不存在时返回，`compatible=False`，不抛 500。

硬件适用区间在模拟数据中统一为 `HW-1.0~HW-3.9`。

### 2.3 种子命令与幂等

```bash
python scripts/seed_parts.py
python scripts/seed_parts.py --catalog data/parts/v1/catalog.json
```

脚本按唯一键 `(device_id, part_no)` 与 `(source_part_no, target_part_no)` 查重，重复执行只跳过、
不新增；演示型号设备档案缺失时按「品牌 + 型号」自动建档。输出配件与兼容关系总数（含本次新增/跳过）。

## 3. 维修结果模拟数据

### 3.1 样本结构与组成

`data/outcomes/v1/sample_outcomes.json` 共 20 条，字段为
`case_symptom / device_model / error_code / actual_cause_code / action / parts_replaced / resolved / note`。

| 诊断一致案例（1–10） | 诊断差异案例（11–20） |
| --- | --- |
| `actual_cause_code` 等于故障码对应的主根因 | `actual_cause_code` 为同故障码下的其他根因 |

故障码 → 主根因映射（与手册 `02-error-codes.md` 一致）：

| 故障码 | 主根因 |
| --- | --- |
| E101 | POWER_SUPPLY |
| E103 | NETWORK_CONFIG |
| E105 | COMPRESSOR_FAULT |
| E106 | FAN_BLOCKED |
| E108 | SENSOR_FAULT |

差异案例使用冻结根因中的 FAN_MOTOR / FAN_DRIVER / POWER_WIRING / GENERAL_POWER /
CONDENSER_BLOCKED / NETWORK_MODULE / SENSOR_WIRING / REFRIGERANT_LEAK / GENERAL_CONTROL。

### 3.2 种子命令与幂等

```bash
python scripts/seed_outcomes.py
python scripts/seed_outcomes.py --samples data/outcomes/v1/sample_outcomes.json
```

每条样本按幂等键 `sim-<n>`（n = 1..20）创建：

- `Case(status="WORK_ORDER_CREATED")`，`extracted={"source": "simulated", "sample_index": n}`；
- 一张工单（`status="resolved"`、`external_id=SIM-<n>`、`resolution="simulated"`）；
- 一条 `RepairOutcome`，`note` 以 `source=simulated;` 开头。

重复执行按幂等键跳过，不新增、不覆盖。成功时输出 `OUTCOMES 20`。

## 4. 接口与权限

| 方法 | 路径 | 权限 | 作用 |
| --- | --- | --- | --- |
| GET | `/parts?device_model=` | `part:read` | 型号配件与库存 |
| GET | `/parts/{part_no}/compatibility?device_model=&hardware_version=` | `part:read` | 兼容性、类型、证据来源、替代件 |
| POST | `/cases/{id}/repair-plan` | `repair:write` | 生成维修方案（仅 `DIAGNOSED`） |
| GET | `/cases/{id}/repair-plan` | 案例可访问 | 读取最近方案 |
| POST | `/cases/{id}/submit-approval` | `repair:write` | `REPAIR_PLANNING→APPROVAL_PENDING` |
| POST | `/cases/{id}/approvals` | `approval:decide` | approve / reject（reject → `NEED_HUMAN`） |
| GET | `/cases/{id}/approvals` | 案例可访问 | 审批记录 |
| POST | `/cases/{id}/work-orders` | `workorder:create` | 幂等建单（必须已批审批） |
| GET | `/work-orders?case_id=` / `/work-orders/{id}` | staff / assignee | 工单查询 |
| POST | `/work-orders/{id}/outcome` | `outcome:write` | 结果回收（唯一、不可覆盖） |
| GET | `/cases/{id}/outcomes` | 案例可访问 | 结果列表 |
| POST | `/cases/{id}/close` | `approval:decide` 或 `workorder:update` | 关闭案例 |

角色矩阵：`agent` 无 `outcome:write`（AI/调度不能覆盖维修结果），结果录入仅 technician/admin；
审批仅 agent/admin。全链路演示先以 technician 登录取 `GET /auth/me` 的 user id，建单时把
工单 `assignee` 设为该 id，再由 technician 完成结果录入。

## 5. 维修方案推荐规则

- 取 `supported` 最高分根因，按根因模板生成 ≥2 个方案（self_service / repair_center / on_site / replace_part）；
- 每个含配件方案调用 `check_part_compatibility`，任一配件不兼容则 `parts_compatible=False`；
- 推荐规则：在 `parts_compatible=True` 的方案中选 `estimated_cost` 最低者，并列按 `action` 字典序；
- 全部不兼容时 `recommended=None` 并追加免责声明；
- 方案只做建议，不自动下单、不自动执行维修。

## 6. 全链路演示

```bash
python scripts/demo_full_closure.py
python scripts/demo_full_closure.py --variant with_photo --base-url http://localhost:8000/api/v1
```

前置：后端已启动，且已执行 `seed_demo.py`、`seed_parts.py`、`seed_outcomes.py`。

脚本按顺序执行并逐步打印 JSON：

1. agent 登录、建案、受理、证据、生成假设、检查规划/结果、诊断结论（`DIAGNOSED`）；
2. 生成维修方案，读取配件列表并做一次兼容性校验；
3. 提交审批 → agent approve；
4. 创建工单两次（同一 `idempotency_key`），断言首次 `created=True`、重复 `created=False` 且工单号相同；
5. technician 登录（工单 assignee 已设为其 user id）并录入维修结果，断言 `consistency="match"`；
6. 关闭案例，断言状态 `CLOSED`。

全部通过输出 `CLOSURE OK` 并退出码 0；任一步失败打印失败步骤的 `step` 与错误码并以退出码 1 结束。

## 7. 失败语义

| 场景 | HTTP / 错误码 |
| --- | --- |
| 未诊断即生成方案 | 409 `ILLEGAL_TRANSITION` |
| 方案/审批状态不合法 | 409 `ILLEGAL_TRANSITION` |
| 未审批即建单 | 409 `APPROVAL_REQUIRED` |
| 同一工单重复录入结果 | 409 `OUTCOME_EXISTS` |
| 工单不存在 | 404 `NOT_FOUND` |
| technician/agent 越权 | 403 `FORBIDDEN` |
| 非法审批决定 | 422 `VALIDATION_ERROR` |
| 上游工单系统不可用 | 工具错误 `UPSTREAM_UNAVAILABLE`，不落工单 |

结果不可覆盖：需要修订时创建新工单，保留历史结果。

## 8. 验收口径

```bash
python scripts/init_db.py --reset
python scripts/seed_demo.py
python scripts/seed_parts.py          # 输出配件/兼容关系数量
python scripts/seed_outcomes.py       # 输出 OUTCOMES 20
python scripts/seed_parts.py          # 再次执行不新增
python scripts/seed_outcomes.py       # 再次执行不新增
uvicorn services.api.app.main:app --port 8000 &
python scripts/demo_full_closure.py   # 输出 CLOSURE OK
pytest -q
```

- `catalog.json`：5 型号 × (4 主件 + 1 个 `-R2`)，含 `incompatible` 与 `replacement`；
- `sample_outcomes.json`：20 条，10 条与故障码主根因一致、10 条差异；
- seed 脚本可重复执行不新增；
- 全链路演示一次性通过并输出 `CLOSURE OK`。