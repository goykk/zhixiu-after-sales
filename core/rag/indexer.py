"""手册索引：幂等重建切片与向量，失败回滚并标记 failed。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from core.ai.factory import get_embedder
from core.db.models import Device, DocumentChunk, Manual, new_id, utcnow
from core.rag.chunking import chunk_markdown
from core.rag.vector_store import vector_literal
from services.api.app.config import settings

STATUS_INDEXED = "indexed"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class IndexResult:
    manual_id: str
    chunk_count: int
    status: str
    error: str | None = None


class ManualIndexer:
    def __init__(self, db: Session, embedder=None):
        self.db = db
        self.embedder = embedder or get_embedder()

    def index_manual(self, manual_id: str) -> IndexResult:
        manual = self.db.get(Manual, manual_id)
        if manual is None:
            return IndexResult(manual_id=manual_id, chunk_count=0, status=STATUS_FAILED, error="MANUAL_NOT_FOUND")
        try:
            drafts = chunk_markdown(manual.content_text or "")
            vectors = self.embedder.embed([draft.content for draft in drafts]) if drafts else []
            if len(vectors) != len(drafts):
                raise RuntimeError("embedding count mismatch")
            device = self.db.get(Device, manual.device_id) if manual.device_id else None
            write_pgvector = _pgvector_mode(self.db)
            self.db.execute(delete(DocumentChunk).where(DocumentChunk.manual_id == manual_id))
            for draft, vector in zip(drafts, vectors):
                embedding = [float(value) for value in vector]
                chunk = DocumentChunk(
                    id=new_id(),
                    manual_id=manual_id,
                    page=draft.page,
                    section=draft.section,
                    content=draft.content,
                    embedding=embedding,
                    meta=_meta_of(manual, device, draft.page, draft.section),
                )
                self.db.add(chunk)
                if write_pgvector:
                    # 先 flush 保证行已存在，再在同一事务内补齐向量列，失败即整批回滚。
                    self.db.flush()
                    _write_embedding_vec(self.db, chunk.id, embedding)
            manual.status = STATUS_INDEXED
            manual.indexed_at = utcnow()
            self.db.commit()
        except Exception as exc:  # noqa: BLE001 - 任何失败都必须回滚整批 chunk
            self.db.rollback()
            self._mark_failed(manual_id)
            return IndexResult(
                manual_id=manual_id,
                chunk_count=0,
                status=STATUS_FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
        return IndexResult(manual_id=manual_id, chunk_count=len(vectors), status=STATUS_INDEXED)

    def _mark_failed(self, manual_id: str) -> None:
        try:
            manual = self.db.get(Manual, manual_id)
            if manual is not None:
                manual.status = STATUS_FAILED
                self.db.commit()
        except Exception:  # noqa: BLE001 - 标记失败本身不再向上抛出
            self.db.rollback()


def _pgvector_mode(db: Session) -> bool:
    """仅 pgvector 模式 + PostgreSQL 方言才写 ``embedding_vec``；SQLite 路径不变。"""
    if (settings.vector_backend or "").strip().lower() != "pgvector":
        return False
    try:
        bind = db.get_bind()
    except Exception:  # noqa: BLE001 - 未绑定会话按 SQLite 处理
        return False
    return bind is not None and bind.dialect.name == "postgresql"


def _write_embedding_vec(db: Session, chunk_id: str, vector: list[float]) -> None:
    db.execute(
        text("UPDATE document_chunks SET embedding_vec = CAST(:vec AS vector) WHERE id = :id"),
        {"vec": vector_literal(vector), "id": chunk_id},
    )


def _meta_of(manual: Manual, device: Device | None, page: int, section: str) -> dict:
    return {
        "brand": (device.brand or "") if device is not None else "",
        "model": (device.model or "") if device is not None else "",
        "hardware_version": (device.hardware_version or "") if device is not None else "",
        "firmware_version": (device.firmware_version or "") if device is not None else "",
        "version": manual.version or "",
        "page": page,
        "section": section,
    }