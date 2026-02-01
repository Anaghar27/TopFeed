import argparse
import json
import sys
from datetime import datetime

import psycopg2
from dotenv import load_dotenv

sys.path.append("/app")

from app.services.fresh_ingest import (
    FreshItem,
    embed_fresh_items,
    record_ingest_run,
    run_fresh_ingest,
    upsert_fresh_items,
)


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


def load_items_from_file(path: str) -> list[FreshItem]:
    with open(path, "r") as handle:
        payload = json.load(handle)
    items = []
    for raw in payload.get("items", []):
        published_at = raw.get("published_at")
        parsed = None
        if published_at:
            cleaned = published_at.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(cleaned)
        items.append(
            FreshItem(
                news_id=raw["news_id"],
                url=raw["url"],
                url_hash=raw["url_hash"],
                published_at=parsed,
                source=raw.get("source") or "rss",
                title=raw.get("title") or "",
                description=raw.get("description") or "",
                category=raw.get("category") or "unknown",
                subcategory=raw.get("subcategory") or "unknown",
            )
        )
    return items


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--config", type=str, default="/app/ml/config/rss_sources.json")
    parser.add_argument("--input", type=str, default=None)
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.input:
            items = load_items_from_file(args.input)
            inserted, updated = upsert_fresh_items(conn, items)
            model_name = get_env("EMB_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
            emb_batch_size = int(get_env("EMB_BATCH_SIZE", "128"))
            fetch_batch_size = int(get_env("EMB_FETCH_BATCH", "2000"))
            embedded = embed_fresh_items(
                conn,
                model_name=model_name,
                emb_batch_size=emb_batch_size,
                fetch_batch_size=fetch_batch_size,
            )
            record_ingest_run(
                conn,
                source="rss_file",
                window_hours=args.hours,
                items=items,
                inserted=inserted,
                updated=updated,
                embedded=embedded,
                status="success",
                error=None,
            )
            print(f"items_fetched={len(items)}")
            print(f"items_inserted={inserted}")
            print(f"items_updated={updated}")
            print(f"items_embedded={embedded}")
        else:
            result = run_fresh_ingest(conn, config_path=args.config, hours=args.hours)
            print(json.dumps(result))
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
