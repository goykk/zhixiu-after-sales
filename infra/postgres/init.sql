-- 智修 V1.2：PostgreSQL 初始化（pgvector 扩展；表结构由 scripts/init_db.py 创建）
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 当前版本向量存 document_chunks.embedding(JSON)，检索在进程内完成；
-- 下一轮切换 pgvector 时可直接在此建列与索引：
--   ALTER TABLE document_chunks ADD COLUMN embedding_vec vector(768);
--   CREATE INDEX document_chunks_embedding_idx
--       ON document_chunks USING ivfflat (embedding_vec vector_cosine_ops) WITH (lists = 100);