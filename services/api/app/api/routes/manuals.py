"""手册上传、列表与索引接口。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import get_db
from core.db.models import Device, Manual, new_id
from core.rag.indexer import ManualIndexer
from core.tasks.dispatch import dispatch
from core.tasks.handlers import index_manual_handler

from services.api.app.api.routes.tasks import (
    TASK_INDEX_MANUAL,
    TaskAcceptedOut,
    async_enabled,
)
from services.api.app.config import settings
from services.api.app.deps import get_current_user, require_roles
from services.api.app.errors import ApiError

router = APIRouter(tags=["manuals"])

TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
PDF_SUFFIX = ".pdf"


class ManualOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str
    title: str
    version: str | None = None
    source_url: str | None = None
    checksum: str | None = None
    status: str
    indexed_at: datetime | None = None
    created_at: datetime | None = None


class ManualIndexOut(BaseModel):
    manual_id: str
    chunk_count: int
    status: str
    error: str | None = None


@router.post("/manuals", response_model=ManualOut, status_code=201)
async def upload_manual(
    device_id: str = Form(...),
    file: UploadFile = File(...),
    title: str | None = Form(None),
    version: str = Form(""),
    source_url: str | None = Form(None),
    db: Session = Depends(get_db),
    user=Depends(require_roles("agent", "admin")),
) -> ManualOut:
    if db.get(Device, device_id) is None:
        raise ApiError(404, "DEVICE_NOT_FOUND", f"设备档案不存在：{device_id}")
    data = await file.read()
    if not data:
        raise ApiError(422, "MANUAL_REJECTED", "手册内容为空")
    if len(data) > settings.max_upload_bytes:
        raise ApiError(422, "MANUAL_REJECTED", "手册文件超过大小限制")
    content_text = _extract_text(file.filename, data)
    manual = Manual(
        id=new_id(),
        device_id=device_id,
        title=(title or "").strip() or Path(file.filename or "manual").stem,
        version=(version or "").strip(),
        source_url=_clean(source_url),
        checksum=hashlib.sha256(data).hexdigest(),
        status="pending",
        object_key=None,
        content_text=content_text,
    )
    db.add(manual)
    db.commit()
    db.refresh(manual)
    return ManualOut.model_validate(manual)


@router.get("/manuals", response_model=list[ManualOut])
def list_manuals(
    device_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> list[ManualOut]:
    stmt = select(Manual).order_by(Manual.created_at.desc()).limit(limit)
    if device_id:
        stmt = stmt.where(Manual.device_id == device_id)
    manuals = db.execute(stmt).scalars().all()
    return [ManualOut.model_validate(manual) for manual in manuals]


@router.post(
    "/manuals/{manual_id}/index",
    response_model=ManualIndexOut | TaskAcceptedOut,
)
def index_manual(
    manual_id: str,
    response: Response,
    async_: bool = Query(False, alias="async"),
    db: Session = Depends(get_db),
    user=Depends(require_roles("agent", "admin")),
) -> ManualIndexOut | TaskAcceptedOut:
    if async_enabled(async_, endpoint="manuals.index"):
        info = dispatch(
            TASK_INDEX_MANUAL,
            {"manual_id": manual_id},
            owner_id=user.id,
            sync_handler=lambda: index_manual_handler(db, manual_id),
        )
        if info.status == "PENDING":
            response.status_code = 202
            return TaskAcceptedOut(
                task_id=info.task_id, status=info.status, backend=info.backend
            )
        return _index_out(manual_id, info.result or {})
    return _index_out(manual_id, ManualIndexer(db).index_manual(manual_id))


def _index_out(manual_id: str, result: Any) -> ManualIndexOut:
    if isinstance(result, dict):
        payload = result
    else:
        payload = {
            "manual_id": result.manual_id,
            "chunk_count": result.chunk_count,
            "status": result.status,
            "error": result.error,
        }
    if payload.get("status") == "failed" and payload.get("error") == "MANUAL_NOT_FOUND":
        raise ApiError(404, "MANUAL_NOT_FOUND", f"手册不存在：{manual_id}")
    return ManualIndexOut(
        manual_id=str(payload.get("manual_id") or manual_id),
        chunk_count=int(payload.get("chunk_count") or 0),
        status=str(payload.get("status") or "failed"),
        error=payload.get("error"),
    )


def _extract_text(filename: str | None, data: bytes) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return data.decode("utf-8", errors="replace")
    if suffix == PDF_SUFFIX:
        return _extract_pdf(data)
    raise ApiError(422, "MANUAL_TYPE_UNSUPPORTED", f"不支持的手册格式：{suffix or '未知'}")


def _extract_pdf(data: bytes) -> str:
    try:
        import fitz
    except ImportError:
        raise ApiError(422, "MANUAL_TYPE_UNSUPPORTED", "PDF 解析需要安装可选依赖 pymupdf")
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            pages: list[str] = []
            for number, page in enumerate(document, start=1):
                text = page.get_text()
                if text.strip():
                    pages.append(f"<!-- page: {number} -->\n{text.strip()}")
    except Exception as exc:  # noqa: BLE001 - 第三方解析器异常统一转为可读错误
        raise ApiError(422, "MANUAL_REJECTED", f"PDF 解析失败：{exc}")
    if not pages:
        raise ApiError(422, "MANUAL_REJECTED", "PDF 无可提取文本")
    return "\n".join(pages)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None