# 工作台（R28）

前端 `/console` 工作台整合了运营概览、案例、评测与任务入口，并新增两个只读后端接口。

## 1. 页面

| 页面 | 路径 | 内容 |
|---|---|---|
| 概览 | `/console` | KPI 卡片（案例总数/待人工/已诊断/工单/结果回收/评测/任务）+ 最近 10 条任务 |
| 案例 | `/console/cases` | 可访问案例列表，链接到 `/cases/{id}` |
| 评测 | `/console/eval` | 最近 20 次消融运行（run_id/split/通过） |
| 任务 | `/console/tasks` | 最近 50 条异步任务（仅 staff 可看全部） |

顶部导航新增“工作台”入口；既有 `/cases`、`/eval` 页面保持不变。

## 2. 后端接口

### GET /overview（agent/admin）
返回聚合只读数据：
```
{
  "cases": {"total": int, "by_status": {status: int}},
  "need_human": int,
  "diagnosed": int,
  "work_orders": {"total": int, "by_status": {status: int}},
  "outcomes": int,
  "eval_runs": {"total": int, "latest_passed": bool | null},
  "tasks": {"total": int, "by_status": {status: int}},
  "generated_at": str
}
```
`diagnosed` 统计状态属于 `DIAGNOSED/REPAIR_PLANNING/APPROVAL_PENDING/WORK_ORDER_CREATED/OUTCOME_PENDING/CLOSED` 的案例。

### GET /tasks?limit=20&owner=me|all
- `owner=me`（默认）只返回当前用户任务；`owner=all` 需要 `case:read_all`（agent/admin），否则 403。
- `limit` 范围 1–100，超出返回 422 `LIMIT_EXCEEDED`。
- 返回 `{items: [TaskOut]}`，按创建时间倒序。

任务存储：`core/tasks/store.TaskStore.list` 支持 Redis `scan` 与进程内字典回退。

## 3. 权限

- `/overview`：仅 agent/admin。
- `/tasks?owner=all`：仅 agent/admin；`owner=me` 任意登录用户。
- 非授权访问返回统一错误体 `{error:{code,message}}`，前端显示 `code: message`，不白屏。

## 4. 验证

```bash
python -m pytest tests/test_overview_api.py -q
cd apps/web && npx tsc --noEmit && npm run build
```

说明：概览与任务列表均为只读聚合，不新增数据库表；任务来自 `TaskStore`（Redis 或回退字典）。