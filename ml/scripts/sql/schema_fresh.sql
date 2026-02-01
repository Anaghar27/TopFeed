ALTER TABLE items
    ADD COLUMN IF NOT EXISTS content_type TEXT NOT NULL DEFAULT 'mind',
    ADD COLUMN IF NOT EXISTS source TEXT,
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS url_hash TEXT,
    ADD COLUMN IF NOT EXISTS is_fresh BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS idx_items_url_hash_unique_all
    ON items (url_hash);

CREATE INDEX IF NOT EXISTS idx_items_is_fresh_published_at
    ON items (is_fresh, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_items_content_type_published_at
    ON items (content_type, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_items_url_hash
    ON items (url_hash);

CREATE TABLE IF NOT EXISTS fresh_ingest_runs (
    run_id TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    source TEXT,
    window_hours INT,
    items_fetched INT,
    items_inserted INT,
    items_updated INT,
    items_embedded INT,
    quality_json JSONB,
    status TEXT,
    error TEXT
);
