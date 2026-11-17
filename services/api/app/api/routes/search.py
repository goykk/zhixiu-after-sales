"""版本感知检索接口。"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.db.base import get_db
from core.devices import get_device_profile
from core.rag.retriever import VersionAwareRetriever
from services.api.app.deps import get_current_user
from services.api.app.errors import ApiError

router = APIRouter(tags=["search"])


class SearchItemOut(BaseModel):
    chunk_id: str
    manual_id: str
    quote: str
    page: int | None = None
    section: str | None = None
    relevance_score: float
    source_url: str | None = None
    model: str | None = None
    version: str | None = None


class SearchOut(BaseModel):
    query: str
    device_id: str | None = None
    items: list[SearchItemOut]


@router.get("/search", response_model=SearchOut)
def search(
    q: str = Query(..., min_length=1),
    device_id: str | None = None,
    top_k: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> SearchOut:
    model = hardware_version = firmware_version = None
    if device_id:
        profile = get_device_profile(db, device_id)
        if profile is None:
            raise ApiError(404, "DEVICE_NOT_FOUND", f"设备档案不存在：{device_id}")
        model, hardware_version, firmware_version = (
            profile.model,
            profile.hardware_version,
            profile.firmware_version,
        )
    items = VersionAwareRetriever(db).retrieve(
        q,
        model=model,
        hardware_version=hardware_version,
        firmware_version=firmware_version,
        top_k=top_k,
    )
    return SearchOut(
        query=q,
        device_id=device_id,
        items=[SearchItemOut(**asdict(item)) for item in items],
    )