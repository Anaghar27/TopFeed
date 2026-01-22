CREATE TABLE IF NOT EXISTS events (
    event_id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('impression','click','hide','save','dwell')),
    news_id TEXT NOT NULL,
    impression_id TEXT NULL,
    request_id TEXT NULL,
    model_version TEXT NULL,
    method TEXT NULL,
    position INT NULL,
    explore_level DOUBLE PRECISION NULL,
    diversify BOOLEAN NULL,
    dwell_ms INT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts);
CREATE INDEX IF NOT EXISTS idx_events_user_ts ON events (user_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_request_id ON events (request_id);
CREATE INDEX IF NOT EXISTS idx_events_news_ts ON events (news_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events (event_type, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_impressions_ts
    ON events (ts DESC)
    WHERE event_type = 'impression';

CREATE TABLE IF NOT EXISTS daily_feed_metrics (
    day DATE NOT NULL,
    model_version TEXT NOT NULL,
    method TEXT NOT NULL,
    impressions BIGINT NOT NULL,
    clicks BIGINT NOT NULL,
    hides BIGINT NOT NULL,
    saves BIGINT NOT NULL,
    avg_dwell_ms DOUBLE PRECISION NULL,
    ctr DOUBLE PRECISION NOT NULL,
    save_rate DOUBLE PRECISION NULL,
    hide_rate DOUBLE PRECISION NULL,
    unique_users BIGINT NOT NULL,
    unique_items BIGINT NOT NULL,
    coverage_categories BIGINT NULL,
    coverage_subcategories BIGINT NULL,
    repetition_rate DOUBLE PRECISION NULL,
    novelty_proxy DOUBLE PRECISION NULL,
    PRIMARY KEY (day, model_version, method)
);
