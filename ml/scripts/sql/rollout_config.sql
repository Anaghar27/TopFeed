CREATE TABLE IF NOT EXISTS rollout_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO rollout_config (key, value)
VALUES
    ('CANARY_ENABLED', 'false'),
    ('CANARY_PERCENT', '5'),
    ('CONTROL_MODEL_VERSION', 'reranker_baseline:v1'),
    ('CANARY_MODEL_VERSION', 'reranker_baseline:v2'),
    ('CANARY_AUTO_DISABLE', 'false')
ON CONFLICT (key) DO NOTHING;
