import csv
import json
import math
import os
import sys
from datetime import datetime

import numpy as np
import psycopg2
from dotenv import load_dotenv
from tqdm import tqdm

TIME_FORMAT = "%m/%d/%Y %I:%M:%S %p"


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


def get_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    return float(value)


def get_splits_env(name: str, default: str) -> list[str]:
    value = os.getenv(name, default)
    splits = [item.strip() for item in value.split(",") if item.strip()]
    return splits or [default]


def get_conn():
    return psycopg2.connect(
        host=get_env("DB_HOST"),
        port=get_env("DB_PORT"),
        dbname=get_env("DB_NAME"),
        user=get_env("DB_USER"),
        password=get_env("DB_PASSWORD"),
    )


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, TIME_FORMAT)
    except ValueError:
        return None


def parse_vector(value) -> np.ndarray | None:
    if value is None:
        return None
    text = str(value).strip().lstrip("[").rstrip("]")
    if not text:
        return None
    return np.fromstring(text, sep=",", dtype=np.float32)


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if denom == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


def get_category_ctr(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(AVG(CASE WHEN clicked THEN 1 ELSE 0 END), 0)
            FROM impressions
            WHERE split = 'train' AND clicked IS NOT NULL
            """
        )
        global_ctr = float(cur.fetchone()[0] or 0.0)

        cur.execute(
            """
            SELECT i.category, AVG(CASE WHEN im.clicked THEN 1 ELSE 0 END)::float AS ctr
            FROM impressions im
            JOIN items i ON i.news_id = im.news_id
            WHERE im.split = 'train' AND im.clicked IS NOT NULL
            GROUP BY i.category
            """
        )
        category_ctr = {row[0]: float(row[1]) for row in cur.fetchall()}

        cur.execute(
            """
            SELECT i.subcategory, AVG(CASE WHEN im.clicked THEN 1 ELSE 0 END)::float AS ctr
            FROM impressions im
            JOIN items i ON i.news_id = im.news_id
            WHERE im.split = 'train' AND im.clicked IS NOT NULL
            GROUP BY i.subcategory
            """
        )
        subcategory_ctr = {row[0]: float(row[1]) for row in cur.fetchall()}

    return global_ctr, category_ctr, subcategory_ctr


def build_user_context(conn, user_id: str, history_k: int, half_life_days: float):
    sql = """
        SELECT im.news_id, s.time, s.impression_id
        FROM impressions im
        JOIN sessions s
          ON s.impression_id = im.impression_id
         AND s.split = im.split
        WHERE s.user_id = %s
          AND im.clicked = TRUE
          AND s.split IN ('train','dev')
        ORDER BY s.impression_id DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (user_id, history_k))
        rows = cur.fetchall()

    if not rows:
        return None, set(), None

    news_ids = [row[0] for row in rows]

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT news_id, embedding, category
            FROM items
            WHERE news_id = ANY(%s)
            """,
            (news_ids,),
        )
        emb_rows = cur.fetchall()

    vectors = {row[0]: parse_vector(row[1]) for row in emb_rows}
    categories = {row[0]: row[2] for row in emb_rows}

    parsed_times = [parse_time(row[1]) for row in rows]
    use_fallback = any(ts is None for ts in parsed_times)

    if use_fallback:
        def sort_key(item):
            try:
                return int(item[2])
            except (TypeError, ValueError):
                return 0
        ordered = sorted(rows, key=sort_key, reverse=True)
        age_map = {item[0]: idx for idx, item in enumerate(ordered)}
        last_time = None
    else:
        now = datetime.utcnow()
        age_map = {}
        last_time = max(ts for ts in parsed_times if ts is not None)
        for (news_id, _time, _imp), ts in zip(rows, parsed_times):
            age_days = (now - ts).total_seconds() / 86400.0
            age_map[news_id] = max(age_days, 0.0)

    weights = []
    embeddings = []
    user_categories = set()

    for news_id, _time, _imp in rows:
        vec = vectors.get(news_id)
        if vec is None:
            continue
        age_days = age_map.get(news_id, 0.0)
        weight = math.exp(-math.log(2) * age_days / half_life_days) if half_life_days > 0 else 1.0
        embeddings.append(vec)
        weights.append(weight)
        category = categories.get(news_id)
        if category:
            user_categories.add(category)

    if not embeddings:
        return None, user_categories, last_time

    weights_np = np.array(weights, dtype=np.float64)
    if weights_np.sum() == 0:
        return None, user_categories, last_time

    user_vec = np.average(np.vstack(embeddings), axis=0, weights=weights_np)
    return user_vec, user_categories, last_time


def build_dataset(
    conn,
    conn_ctx,
    split: str,
    output_path: str,
    neg_per_pos: int,
    history_k: int,
    half_life_days: float,
    max_rows: int | None,
    global_ctr: float,
    category_ctr_map: dict,
    subcategory_ctr_map: dict,
    neg_hash_pct: int,
):
    limit_clause = "LIMIT %s" if max_rows else ""
    sql = f"""
        WITH base AS (
            SELECT im.split, im.impression_id, im.news_id, im.position, im.clicked,
                   s.user_id, s.time, i.category, i.subcategory, i.title, i.abstract, i.embedding
            FROM impressions im
            JOIN sessions s
              ON s.impression_id = im.impression_id
             AND s.split = im.split
            JOIN items i
              ON i.news_id = im.news_id
            WHERE im.split = %s
              AND im.clicked IS NOT NULL
              AND i.embedding IS NOT NULL
        ),
        pos_counts AS (
            SELECT split, impression_id, COUNT(*) AS pos_count
            FROM base
            WHERE clicked = TRUE
            GROUP BY split, impression_id
        ),
        neg_sample AS (
            SELECT
                b.*,
                (
                    ('x' || substr(md5(b.impression_id || b.news_id), 1, 8))::bit(32)::int
                ) AS hash_key,
                ROW_NUMBER() OVER (
                    PARTITION BY b.split, b.impression_id
                    ORDER BY ('x' || substr(md5(b.impression_id || b.news_id), 1, 8))::bit(32)::int
                ) AS rn
            FROM base b
            WHERE b.clicked = FALSE
              AND (abs(('x' || substr(md5(b.impression_id || b.news_id), 1, 8))::bit(32)::int) %% 100) < %s
        ),
        neg_limited AS (
            SELECT n.split, n.impression_id, n.news_id, n.position, n.clicked,
                   n.user_id, n.time, n.category, n.subcategory, n.title, n.abstract, n.embedding
            FROM neg_sample n
            JOIN pos_counts p
              ON p.split = n.split
             AND p.impression_id = n.impression_id
            WHERE n.rn <= p.pos_count * %s
        ),
        combined AS (
            SELECT * FROM base WHERE clicked = TRUE
            UNION ALL
            SELECT * FROM neg_limited
        )
        SELECT * FROM combined
        ORDER BY impression_id
        {limit_clause}
    """

    print(f"Starting dataset build for split={split}")
    cursor = conn.cursor(name=f"cursor_{split}")
    cursor.itersize = 5000
    params = [split, neg_hash_pct, neg_per_pos]
    if max_rows:
        params.append(max_rows)
    cursor.execute(sql, params)
    print(f"Query started for split={split}, streaming rows...")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    header = [
        "split",
        "impression_id",
        "user_id",
        "news_id",
        "label",
        "position",
        "title_len",
        "abstract_len",
        "category_ctr",
        "subcategory_ctr",
        "category_match",
        "user_recency_days",
        "cosine_sim",
    ]

    user_cache: dict[str, tuple[np.ndarray | None, set, datetime | None]] = {}

    with open(output_path, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header)

        count = 0
        for row in tqdm(cursor, desc=f"build-{split}", unit="rows"):
            (
                _split,
                impression_id,
                news_id,
                position,
                clicked,
                user_id,
                time_text,
                category,
                subcategory,
                title,
                abstract,
                embedding,
            ) = row

            if user_id not in user_cache:
                user_cache[user_id] = build_user_context(conn_ctx, user_id, history_k, half_life_days)

            user_vec, user_categories, last_time = user_cache[user_id]
            item_vec = parse_vector(embedding)

            title_len = len(title or "")
            abstract_len = len(abstract or "")

            user_recency_days = 0.0
            current_time = parse_time(time_text)
            if last_time and current_time:
                user_recency_days = max((last_time - current_time).total_seconds() / 86400.0, 0.0)

            cosine_sim = 0.0
            if user_vec is not None and item_vec is not None:
                cosine_sim = cosine_similarity(user_vec, item_vec)

            category_match = 1.0 if category and category in user_categories else 0.0

            writer.writerow(
                [
                    _split,
                    impression_id,
                    user_id,
                    news_id,
                    1 if clicked else 0,
                    position or 0,
                    title_len,
                    abstract_len,
                    category_ctr_map.get(category, global_ctr),
                    subcategory_ctr_map.get(subcategory, global_ctr),
                    category_match,
                    round(user_recency_days, 6),
                    round(cosine_sim, 6),
                ]
            )

            count += 1
            if count % 100000 == 0:
                print(f"{split}: processed {count} rows")
            if max_rows and count >= max_rows:
                break

    cursor.close()
    print(f"Completed split={split}, rows_written={count}")
    return count


if __name__ == "__main__":
    load_dotenv()

    neg_per_pos = get_int_env("RERANK_NEG_PER_POS", 5)
    neg_hash_pct = get_int_env("RERANK_NEG_HASH_PCT", 5)
    splits = get_splits_env("RERANK_SPLITS", "train,dev")
    history_k = get_int_env("USER_HISTORY_K", 50)
    half_life_days = get_float_env("USER_HALF_LIFE_DAYS", 7.0)
    max_rows = os.getenv("RERANK_MAX_ROWS")
    max_rows_int = int(max_rows) if max_rows else None
    max_rows_train = os.getenv("RERANK_MAX_ROWS_TRAIN")
    max_rows_dev = os.getenv("RERANK_MAX_ROWS_DEV")
    max_rows_train_int = int(max_rows_train) if max_rows_train else None
    max_rows_dev_int = int(max_rows_dev) if max_rows_dev else None

    conn = get_conn()

    global_ctr, category_ctr_map, subcategory_ctr_map = get_category_ctr(conn)

    out_dir = os.path.join("ml", "data", "processed", "reranker")
    os.makedirs(out_dir, exist_ok=True)
    metadata_path = os.path.join(out_dir, "metadata.json")

    with open(metadata_path, "w") as file:
        json.dump(
            {
                "global_ctr": global_ctr,
                "category_ctr": category_ctr_map,
                "subcategory_ctr": subcategory_ctr_map,
                "history_k": history_k,
                "half_life_days": half_life_days,
                "neg_per_pos": neg_per_pos,
            },
            file,
            indent=2,
        )

    train_path = os.path.join(out_dir, "train.csv")
    val_path = os.path.join(out_dir, "val.csv")

    conn_ctx = get_conn()

    train_rows = 0
    val_rows = 0
    if "train" in splits:
        train_rows = build_dataset(
            conn,
            conn_ctx,
            "train",
            train_path,
            neg_per_pos,
            history_k,
            half_life_days,
            max_rows_train_int or max_rows_int,
            global_ctr,
            category_ctr_map,
            subcategory_ctr_map,
            neg_hash_pct,
        )
        print(f"Train rows: {train_rows}")
    if "dev" in splits:
        val_rows = build_dataset(
            conn,
            conn_ctx,
            "dev",
            val_path,
            neg_per_pos,
            history_k,
            half_life_days,
            max_rows_dev_int or max_rows_int,
            global_ctr,
            category_ctr_map,
            subcategory_ctr_map,
            neg_hash_pct,
        )
        print(f"Val rows: {val_rows}")

    conn_ctx.close()
    conn.close()
