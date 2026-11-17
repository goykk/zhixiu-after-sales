# 生产化硬化（R30）

## 1. JWT 密钥强度（`check_jwt_secret`）

- `JWT_MIN_SECRET_BYTES`（默认 32）为最小字节数。
- `ENV=prod|production` 且密钥不足 → **启动直接抛错**（`RuntimeError`，拒绝启动）。
- 其他环境仅告警（`zhixiu.security` warning），不阻断。
- 接入点：`create_app()` 首步调用；`services/api/app/hardening.py`。

```bash
python - <<'PY'
from services.api.app.config import Settings
from services.api.app.hardening import check_jwt_secret
check_jwt_secret(Settings(env="prod", jwt_secret="x"*40))  # 通过
PY
```

## 2. 速率限制（`RateLimitMiddleware`）

- `RATE_LIMIT_ENABLED=false`（默认）不干预；`/health` 永不限流。
- `RATE_LIMIT_PER_MINUTE`（默认 60）与 `RATE_LIMIT_BURST`（默认 20）构成 60 秒窗口上限（取二者较大值）。
- 身份键：Bearer token 尾段（不存完整 token），否则客户端 IP。
- 超限返回 429 `RATE_LIMITED` + `Retry-After`。
- 实现为进程内令牌桶；多实例部署需换成 Redis 共享限流。

## 3. 审计查询（`GET /api/v1/audit-logs`）

- 权限：`audit:read`（agent/admin）。
- 参数：`limit`（1–200，默认 50）、`action`、`actor_id`。
- 返回 `{items:[{id,actor_id,action,resource_id,payload_hash,payload,created_at}]}`，按时间倒序。

## 4. 验证

```bash
python -m pytest tests/test_hardening.py -q
```

覆盖：生产弱密钥抛错、本地仅告警、强密钥通过、启用限流后超限 429、默认关闭不干预、`/health` 不限流、审计权限与字段。