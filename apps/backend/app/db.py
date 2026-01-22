import os

from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import Json, execute_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def _get_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def get_database_url() -> str:
    host = _get_env("DB_HOST")
    port = _get_env("DB_PORT")
    user = _get_env("DB_USER")
    password = _get_env("DB_PASSWORD")
    db_name = _get_env("DB_NAME")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"


def get_engine() -> Engine:
    return create_engine(get_database_url(), pool_pre_ping=True)


def check_db_connection() -> None:
    engine = get_engine()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def get_psycopg_conn():
    return psycopg2.connect(
        host=_get_env("DB_HOST"),
        port=_get_env("DB_PORT"),
        dbname=_get_env("DB_NAME"),
        user=_get_env("DB_USER"),
        password=_get_env("DB_PASSWORD"),
    )


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
            event.get("ts") or datetime.now(timezone.utc),
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
            Json(event.get("metadata") or {}),
        )
        for event in events
    ]
    with conn.cursor() as cur:
        execute_values(cur, sql, values)
    conn.commit()
    return len(events)
