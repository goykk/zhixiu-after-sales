"""进程内令牌桶限流（可选，默认关闭）。

- `RATE_LIMIT_ENABLED=false`（默认）时不干预任何请求。
- 启用后按身份（Bearer token 尾段，或客户端 IP）限制 60 秒窗口内的请求数。
- `/health` 永不限流；超限返回 429 `RATE_LIMITED` 与 `Retry-After`。
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings


class RateLimiter:
    def __init__(self, per_minute: int = 60, burst: int = 20) -> None:
        self.per_minute = max(1, int(per_minute))
        self.burst = max(1, int(burst))
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return max(self.per_minute, self.burst)

    def allow(self, key: str, now: float | None = None) -> tuple[bool, float]:
        now = time.monotonic() if now is None else now
        window = 60.0
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= window:
                events.popleft()
            if len(events) >= self.limit:
                retry = window - (now - events[0]) if events else window
                return False, max(0.0, retry)
            events.append(now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


_limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_burst)


def _sync(limiter: RateLimiter) -> RateLimiter:
    limiter.per_minute = max(1, int(settings.rate_limit_per_minute))
    limiter.burst = max(1, int(settings.rate_limit_burst))
    return limiter


def get_limiter() -> RateLimiter:
    return _sync(_limiter)


def _identity(request: Request) -> str:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return "tok:" + auth[7:][-16:]
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter) -> None:
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled or request.url.path.endswith("/health"):
            return await call_next(request)
        allowed, retry = self.limiter.allow(_identity(request))
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "请求过于频繁，请稍后重试",
                        "details": {"retry_after_s": round(retry, 1)},
                    }
                },
                headers={"Retry-After": str(int(retry) + 1)},
            )
        return await call_next(request)


def install_rate_limit(app: FastAPI) -> None:
    _sync(_limiter)
    app.add_middleware(RateLimitMiddleware, limiter=_limiter)