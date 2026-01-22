from psycopg2.extras import execute_values


def insert_events(conn, events):
    if not events:
        return 0
    sql = """
        INSERT INTO events (
            ts, user_id, event_type, news_id, impression_id, request_id,
            model_version, method, position, explore_level, diversify,
            dwell_ms, metadata
        ) VALUES %s
    """
    values = [
        (
            event.get("ts"),
            event["user_id"],
            event["event_type"],
            event["news_id"],
            event.get("impression_id"),
            event.get("request_id"),
            event.get("model_version"),
            event.get("method"),
            event.get("position"),
            event.get("explore_level"),
            event.get("diversify"),
            event.get("dwell_ms"),
            event.get("metadata") or {},
        )
        for event in events
    ]
    with conn.cursor() as cur:
        execute_values(cur, sql, values)
    conn.commit()
    return len(events)
