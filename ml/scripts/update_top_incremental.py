import argparse
import json
import sys

import psycopg2
from dotenv import load_dotenv

sys.path.append("/app")

from app.services.fresh_ingest import update_top_incremental


def get_env(name: str, default: str | None = None) -> str:
    import os

    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def get_conn():
    return psycopg2.connect(
        host=get_env("DB_HOST"),
        port=get_env("DB_PORT"),
        dbname=get_env("DB_NAME"),
        user=get_env("DB_USER"),
        password=get_env("DB_PASSWORD"),
    )


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=1)
    args = parser.parse_args()

    conn = get_conn()
    try:
        result = update_top_incremental(conn, window_hours=args.hours)
        print(json.dumps(result))
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
