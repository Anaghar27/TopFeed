import os
import sys
import time
from typing import Iterable

import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from tqdm import tqdm


def get_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def get_conn():
    return psycopg2.connect(
        host=get_env("DB_HOST"),
        port=get_env("DB_PORT"),
        dbname=get_env("DB_NAME"),
        user=get_env("DB_USER"),
        password=get_env("DB_PASSWORD"),
    )


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return value.strip()


def format_vector(vec: Iterable[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def count_existing_embeddings(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM items WHERE embedding IS NOT NULL")
        return cur.fetchone()[0]


def fetch_batch(conn, last_news_id: str | None, fetch_size: int, force: bool):
    if force:
        base_sql = "SELECT news_id, title, abstract FROM items"
    else:
        base_sql = "SELECT news_id, title, abstract FROM items WHERE embedding IS NULL"

    if last_news_id is None:
        sql = f"{base_sql} ORDER BY news_id LIMIT %s"
        params = (fetch_size,)
    else:
        if force:
            sql = f"{base_sql} WHERE news_id > %s ORDER BY news_id LIMIT %s"
        else:
            sql = f"{base_sql} AND news_id > %s ORDER BY news_id LIMIT %s"
        params = (last_news_id, fetch_size)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def update_embeddings(conn, rows: list[tuple[str, str]]):
    if not rows:
        return
    sql = """
        UPDATE items AS i
        SET embedding = v.embedding
        FROM (VALUES %s) AS v(news_id, embedding)
        WHERE i.news_id = v.news_id
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows, template="(%s, %s::vector)")
    conn.commit()


def main() -> None:
    load_dotenv()

    model_name = os.getenv("EMB_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
    emb_batch_size = get_int_env("EMB_BATCH_SIZE", 128)
    fetch_batch_size = get_int_env("EMB_FETCH_BATCH", 5000)
    max_rows = os.getenv("EMB_MAX_ROWS")
    force = os.getenv("EMB_FORCE_RECOMPUTE", "0") == "1"

    max_rows_int = int(max_rows) if max_rows else None

    conn = get_conn()

    skipped_existing = 0 if force else count_existing_embeddings(conn)

    model = SentenceTransformer(model_name, device="cpu")

    processed = 0
    embedded = 0
    skipped_empty = 0
    errors = 0

    last_news_id = None
    start = time.time()

    with tqdm(desc="embedding-batches", unit="batch") as progress:
        while True:
            rows = fetch_batch(conn, last_news_id, fetch_batch_size, force)
            if not rows:
                break

            processed += len(rows)
            last_news_id = rows[-1][0]

            news_ids = []
            texts = []

            for news_id, title, abstract in rows:
                text = (normalize_text(title) + " " + normalize_text(abstract)).strip()
                if not text:
                    skipped_empty += 1
                    continue
                news_ids.append(news_id)
                texts.append(text)

            if texts:
                try:
                    vectors = model.encode(
                        texts,
                        batch_size=emb_batch_size,
                        show_progress_bar=False,
                        normalize_embeddings=True,
                    )
                    values = [(nid, format_vector(vec)) for nid, vec in zip(news_ids, vectors)]
                    update_embeddings(conn, values)
                    embedded += len(values)
                except Exception:
                    conn.rollback()
                    errors += len(texts)

            progress.update(1)

            if max_rows_int and processed >= max_rows_int:
                break

    elapsed = time.time() - start

    print("\nEmbedding summary:")
    print(f"processed={processed}")
    print(f"embedded={embedded}")
    print(f"skipped_empty={skipped_empty}")
    print(f"skipped_existing={skipped_existing}")
    print(f"errors={errors}")
    print(f"elapsed_seconds={elapsed:.1f}")

    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
