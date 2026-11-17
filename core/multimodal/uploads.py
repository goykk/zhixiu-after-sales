"""上传来源登记表。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base
from core.db.models import new_id, utcnow


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="stored")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


def upload_out(upload: Upload) -> dict:
    created = upload.created_at
    return {
        "id": upload.id,
        "case_id": upload.case_id,
        "filename": upload.filename,
        "content_type": upload.content_type,
        "size": upload.size,
        "sha256": upload.sha256,
        "object_key": upload.object_key,
        "status": upload.status,
        "created_at": created.isoformat() if created else None,
    }