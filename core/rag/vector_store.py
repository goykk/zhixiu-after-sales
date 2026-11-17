"""向量检索：默认 JSON 列 + 纯 Python 余弦；可选 pgvector 余弦距离。"""

from __future__ import annotations

import importlib.util
import json
import math
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core.db.models import DocumentChunk
from core.observability.tracer import get_tracer
from services.api.app.config import settings

FILTER_KEYS = ("model", "version", "hardware_version", "firmware_version")

EVENT_FALLBACK = "vector_backend_fallback"


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).lower()


def as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def as_vector(value: Any) -> list[float]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, (list, tuple)):
        return []
    vector: list[float] = []
    for item in value:
        try:
            vector.append(float(item))
        except (TypeError, ValueError):
            return []
    return vector


def vector_literal(vector: list[float]) -> str:
    """pgvector 文本输入格式，如 ``[0.1,0.2]``；作为字符串绑定后由 SQL 侧 CAST。"""
    return json.dumps([float(value) for value in vector], separators=(",", ":"))


def pgvector_installed() -> bool:
    return importlib.util.find_spec("pgvector") is not None


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


class JsonVectorStore:
    def __init__(self, db: Session):
        self.db = db

    def search(
        self, vector: list[float], *, filters: dict[str, str] | None = None, top_k: int = 5
    ) -> list[tuple[str, float]]:
        query = _unit(as_vector(vector))
        if not query or top_k <= 0:
            return []
        active = _active_filters(filters)
        scored: list[tuple[str, float]] = []
        chunks = self.db.execute(select(DocumentChunk)).scalars().all()
        for chunk in chunks:
            if not _matches(as_mapping(chunk.meta), active):
                continue
            candidate = as_vector(chunk.embedding)
            if len(candidate) != len(query):
                continue
            scored.append((chunk.id, cosine(query, _unit(candidate))))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]


class PgVectorStore:
    """pgvector 后端：过滤条件下推到 SQL，按余弦距离排序取 top_k。"""

    def __init__(self, db: Session):
        self.db = db

    def search(
        self, vector: list[float], *, filters: dict[str, str] | None = None, top_k: int = 5
    ) -> list[tuple[str, float]]:
        values = as_vector(vector)
        if len(values) != settings.pgvector_dim:
            raise ValueError(
                f"vector dimension {len(values)} != pgvector_dim {settings.pgvector_dim}"
            )
        if top_k <= 0:
            return []
        active = _active_filters(filters)
        statement, params = _pg_sql(active, values, top_k)
        rows = self.db.execute(text(statement), params).all()
        return [(str(row.id), _clamp01(1.0 - float(row.distance))) for row in rows]


# 向后兼容：既有调用方仍按 `VectorStore` 使用 JSON 后端。
VectorStore = JsonVectorStore


def get_vector_store(db: Session) -> JsonVectorStore | PgVectorStore:
    """按配置与运行环境选择后端；请求 pgvector 但条件不满足时回退并记录追踪。"""
    if normalize_text(settings.vector_backend) != "pgvector":
        return JsonVectorStore(db)
    reason: str | None = None
    try:
        bind = db.get_bind()
    except Exception:  # noqa: BLE001 - 未绑定会话一律回退，不阻断检索
        bind = None
    if bind is None:
        reason = "no_bind"
    elif bind.dialect.name != "postgresql":
        reason = f"dialect_{bind.dialect.name}_not_postgresql"
    elif not pgvector_installed():
        reason = "pgvector_not_installed"
    if reason is not None:
        get_tracer().emit(EVENT_FALLBACK, requested="pgvector", reason=reason)
        return JsonVectorStore(db)
    return PgVectorStore(db)


def _active_filters(filters: dict[str, str] | None) -> dict[str, str]:
    return {
        key: normalize_text(value)
        for key, value in (filters or {}).items()
        if key in FILTER_KEYS and normalize_text(value)
    }


def _pg_sql(
    active: dict[str, str], vector: list[float], top_k: int
) -> tuple[str, dict[str, Any]]:
    clauses = [
        "SELECT dc.id AS id,",
        "       (dc.embedding_vec <=> CAST(:vec AS vector)) AS distance",
        "FROM document_chunks dc",
        "JOIN manuals m ON m.id = dc.manual_id",
        "JOIN devices d ON d.id = m.device_id",
        "WHERE dc.embedding_vec IS NOT NULL",
    ]
    params: dict[str, Any] = {"vec": vector_literal(vector), "top_k": top_k}
    if "model" in active:
        clauses.append(
            "  AND (lower(d.model) = :model OR lower(d.brand || ' ' || d.model) = :model)"
        )
        params["model"] = active["model"]
    if "version" in active:
        clauses.append("  AND lower(m.version) = :version")
        params["version"] = active["version"]
    if "hardware_version" in active:
        clauses.append("  AND lower(d.hardware_version) = :hardware_version")
        params["hardware_version"] = active["hardware_version"]
    if "firmware_version" in active:
        clauses.append("  AND lower(d.firmware_version) = :firmware_version")
        params["firmware_version"] = active["firmware_version"]
    clauses.append("ORDER BY dc.embedding_vec <=> CAST(:vec AS vector)")
    clauses.append("LIMIT :top_k")
    return "\n".join(clauses), params


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _matches(meta: dict[str, Any], active: dict[str, str]) -> bool:
    for key, expected in active.items():
        if normalize_text(meta.get(key)) != expected:
            return False
    return True