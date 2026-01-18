import os

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
