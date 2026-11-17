"""pgvector 向量列与 ivfflat 索引

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-14

仅 PostgreSQL 生效：建扩展、加 ``document_chunks.embedding_vec`` 列与 ivfflat 索引；
SQLite 下为 no-op（不建该列，检索继续走 JSON 余弦）。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VECTOR_DIM = 768


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_vec vector({VECTOR_DIM})"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_vec "
        "ON document_chunks USING ivfflat (embedding_vec vector_cosine_ops)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # 扩展可能被其他表共用，降级只回退本迁移新增的对象。
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_vec")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding_vec")