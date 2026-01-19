CREATE TABLE IF NOT EXISTS user_top (
    user_id TEXT PRIMARY KEY,
    split_scope TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    top_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS user_top_nodes (
    user_id TEXT,
    path TEXT,
    category TEXT,
    subcategory TEXT,
    exposures BIGINT,
    clicks BIGINT,
    interest_weight DOUBLE PRECISION,
    exposure_weight DOUBLE PRECISION,
    underexplored_score DOUBLE PRECISION,
    updated_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, path)
);
