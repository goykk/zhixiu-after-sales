"""版本感知检索：型号/硬件/固件过滤 → 向量召回 → 阈值过滤 → 重排。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.ai.base import EmbeddingProvider
from core.ai.factory import get_embedder
from core.ai.mock import MockEmbedder
from core.db.models import DocumentChunk, Manual
from core.devices import find_device_by_model
from core.rag.rerank import rerank
from core.rag.vector_store import as_mapping, get_vector_store
from services.api.app.config import settings


@dataclass(frozen=True)
class EvidenceItem:
    chunk_id: str
    manual_id: str
    quote: str
    page: int | None
    section: str | None
    relevance_score: float
    source_url: str | None
    model: str | None
    version: str | None


class VersionAwareRetriever:
    def __init__(self, db: Session, embedder: EmbeddingProvider | None = None, store=None):
        self.db = db
        self.embedder = embedder or get_embedder()
        self.store = store or get_vector_store(db)
        # Mock 嵌入是确定性哈希，不是语义向量：余弦普遍低于真实模型阈值，
        # 离线演示时取消阈值过滤，交给关键词重排决定顺序。
        self.threshold = 0.0 if isinstance(self.embedder, MockEmbedder) else settings.relevance_threshold

    def retrieve(
        self,
        query: str,
        *,
        model: str | None = None,
        hardware_version: str | None = None,
        firmware_version: str | None = None,
        top_k: int = 8,
    ) -> list[EvidenceItem]:
        query = (query or "").strip()
        if not query or top_k <= 0:
            return []
        filters = {
            "model": self._canonical_model(model),
            "hardware_version": hardware_version,
            "firmware_version": firmware_version,
        }
        vector = self.embedder.embed([query])[0]
        candidates = self.store.search(vector, filters=filters, top_k=max(top_k * 4, top_k))
        if not candidates:
            return []
        chunks = self._load_chunks([chunk_id for chunk_id, _ in candidates])
        manuals = self._load_manuals({chunk.manual_id for chunk in chunks.values()})
        threshold = self.threshold
        items: list[EvidenceItem] = []
        for chunk_id, score in candidates:
            chunk = chunks.get(chunk_id)
            if chunk is None or score < threshold:
                continue
            manual = manuals.get(chunk.manual_id)
            if manual is None:
                continue
            meta = as_mapping(chunk.meta)
            items.append(
                EvidenceItem(
                    chunk_id=chunk.id,
                    manual_id=chunk.manual_id,
                    quote=chunk.content,
                    page=chunk.page,
                    section=chunk.section,
                    relevance_score=score,
                    source_url=manual.source_url,
                    model=_text_or_none(meta.get("model")),
                    version=_text_or_none(meta.get("version")),
                )
            )
        if not items:
            return []
        return rerank(query, items, top_k=top_k)

    def _canonical_model(self, model: str | None) -> str | None:
        if not model or not model.strip():
            return None
        profile = find_device_by_model(self.db, model)
        return profile.model if profile is not None else model.strip()

    def _load_chunks(self, chunk_ids: list[str]) -> dict[str, DocumentChunk]:
        if not chunk_ids:
            return {}
        rows = self.db.execute(select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))).scalars().all()
        return {row.id: row for row in rows}

    def _load_manuals(self, manual_ids: set[str]) -> dict[str, Manual]:
        if not manual_ids:
            return {}
        rows = self.db.execute(select(Manual).where(Manual.id.in_(manual_ids))).scalars().all()
        return {row.id: row for row in rows}


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None