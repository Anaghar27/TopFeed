CREATE TABLE IF NOT EXISTS top_update_watermark (
    last_run_at TIMESTAMPTZ
);

INSERT INTO top_update_watermark (last_run_at)
SELECT NULL
WHERE NOT EXISTS (SELECT 1 FROM top_update_watermark);
