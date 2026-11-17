"""统一错误体：`{"error": {"code", "message", "details"}}`。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.observability.redact import redact

logger = logging.getLogger("zhixiu.api")

_STATUS_CODE_NAMES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


class ApiError(Exception):
    """业务异常，由处理器转换为固定错误体。"""

    def __init__(
        self,
        status_code: int = 400,
        code: str = "BAD_REQUEST",
        message: str = "",
        details: Any = None,
    ) -> None:
        super().__init__(message or code)
        self.status_code = status_code
        self.code = code
        self.message = message or code
        self.details = details


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def _status_code_name(status_code: int, fallback: str = "ERROR") -> str:
    return _STATUS_CODE_NAMES.get(status_code, fallback)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(
                "VALIDATION_ERROR",
                "request validation failed",
                jsonable_encoder(exc.errors()),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(_status_code_name(exc.status_code), message),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        # 不把异常细节返回给调用方，日志侧也只保留脱敏后的摘要
        logger.debug("unhandled error summary: %s", redact(str(exc)))
        return JSONResponse(
            status_code=500,
            content=error_body("INTERNAL_ERROR", "internal server error"),
        )