"""FastAPI 应用外壳：自动装载 `api/routes` 下的路由模块。"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Iterable

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.observability import otel

from .config import settings
from .errors import install_error_handlers
from .hardening import check_jwt_secret
from .ratelimit import install_rate_limit

API_PREFIX = "/api/v1"


def _iter_route_modules() -> Iterable[str]:
    from .api import routes as routes_pkg

    for module_info in pkgutil.iter_modules(routes_pkg.__path__):
        if module_info.name.startswith("_"):
            continue
        yield f"{routes_pkg.__name__}.{module_info.name}"


def _load_routers() -> list[APIRouter]:
    routers: list[APIRouter] = []
    for module_name in _iter_route_modules():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - 启动期必须暴露具体模块
            raise RuntimeError(f"route module failed: {module_name}") from exc
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            routers.append(router)
    return routers


def create_app() -> FastAPI:
    # OTel 为可选旁路：初始化失败不得阻断启动
    try:
        otel.setup_tracing()
    except Exception:  # noqa: BLE001 - 观测故障不影响业务
        pass

    # 安全自检：生产环境 JWT 密钥不足直接拒绝启动
    check_jwt_secret(settings)

    app = FastAPI(title=settings.app_name, version="1.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_rate_limit(app)
    install_error_handlers(app)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env}

    for router in _load_routers():
        app.include_router(router, prefix=API_PREFIX)
    return app


app = create_app()