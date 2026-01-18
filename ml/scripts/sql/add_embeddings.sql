ALTER TABLE items ADD COLUMN IF NOT EXISTS embedding vector(384);

CREATE INDEX IF NOT EXISTS idx_items_embedding_hnsw
ON items USING hnsw (embedding vector_cosine_ops);
