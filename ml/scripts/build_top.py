import argparse
import json
import math
import os
import time
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from tqdm import tqdm

TIME_FORMAT = "%m/%d/%Y %I:%M:%S %p"
EPSILON = 1e-6


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


def decay_weight(age_days: float, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 1.0
    return math.exp(-math.log(2) * age_days / half_life_days)


def get_user_ids(conn, limit_users: int | None):
    sql = """
        SELECT DISTINCT user_id
        FROM sessions
        WHERE split IN ('train','dev')
        ORDER BY user_id
    """
    if limit_users:
        sql += " LIMIT %s"
        params = (limit_users,)
    else:
        params = None
    with conn.cursor(name="users_cursor") as cur:
        cur.itersize = 1000
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        for row in cur:
            yield row[0]


def fetch_user_impressions(conn, user_id: str):
    sql = """
        SELECT im.impression_id, s.time, im.news_id, im.clicked,
               i.category, i.subcategory
        FROM impressions im
        JOIN sessions s
          ON s.impression_id = im.impression_id
         AND s.split = im.split
        JOIN items i
          ON i.news_id = im.news_id
        WHERE s.user_id = %s
          AND s.split IN ('train','dev')
        ORDER BY s.impression_id DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (user_id,))
        return cur.fetchall()


def compute_top(user_id: str, rows, half_life_days: float):
    if not rows:
        return {
            "user_id": user_id,
            "split_scope": "train_dev",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "half_life_days": half_life_days,
            "epsilon": EPSILON,
            "root": {
                "exposures": 0,
                "clicks": 0,
                "ctr": 0.0,
                "interest_weight": 0.0,
                "exposure_weight": 0.0,
                "underexplored_score": 0.0,
                "categories": [],
            },
            "underexplored_paths": [],
        }, []

    parsed_times = [parse_time(row[1]) for row in rows]
    use_fallback = any(ts is None for ts in parsed_times)

    if use_fallback:
        age_map = {row[0]: idx for idx, row in enumerate(rows)}
        now = None
    else:
        now = max(ts for ts in parsed_times if ts is not None)
        age_map = {row[0]: max((now - ts).total_seconds() / 86400.0, 0.0) for row, ts in zip(rows, parsed_times)}

    root = {
        "exposures": 0,
        "clicks": 0,
        "ctr": 0.0,
        "interest_weight": 0.0,
        "exposure_weight": 0.0,
        "underexplored_score": 0.0,
        "categories": {},
    }

    for impression_id, _time, _news_id, clicked, category, subcategory in rows:
        age_days = age_map.get(impression_id, 0.0)
        weight = decay_weight(age_days, half_life_days)

        root["exposures"] += 1
        root["exposure_weight"] += weight
        if clicked:
            root["clicks"] += 1
            root["interest_weight"] += weight

        if category not in root["categories"]:
            root["categories"][category] = {
                "category": category,
                "exposures": 0,
                "clicks": 0,
                "interest_weight": 0.0,
                "exposure_weight": 0.0,
                "subcategories": {},
            }
        cat_node = root["categories"][category]
        cat_node["exposures"] += 1
        cat_node["exposure_weight"] += weight
        if clicked:
            cat_node["clicks"] += 1
            cat_node["interest_weight"] += weight

        sub_key = subcategory or ""
        if sub_key not in cat_node["subcategories"]:
            cat_node["subcategories"][sub_key] = {
                "subcategory": subcategory,
                "exposures": 0,
                "clicks": 0,
                "interest_weight": 0.0,
                "exposure_weight": 0.0,
            }
        sub_node = cat_node["subcategories"][sub_key]
        sub_node["exposures"] += 1
        sub_node["exposure_weight"] += weight
        if clicked:
            sub_node["clicks"] += 1
            sub_node["interest_weight"] += weight

    def finalize_node(node):
        exposures = node["exposures"]
        clicks = node["clicks"]
        node["ctr"] = float(clicks / exposures) if exposures else 0.0
        node["underexplored_score"] = float(node["interest_weight"] / (node["exposure_weight"] + EPSILON))
        return node

    root = finalize_node(root)

    flattened_nodes = []
    categories_list = []

    for category, cat_node in root["categories"].items():
        finalize_node(cat_node)
        subcategories_list = []

        for sub_key, sub_node in cat_node["subcategories"].items():
            finalize_node(sub_node)
            subcategories_list.append(sub_node)
            if sub_key:
                path = f"{category}/{sub_key}"
                flattened_nodes.append(
                    {
                        "path": path,
                        "category": category,
                        "subcategory": sub_node.get("subcategory"),
                        "exposures": sub_node["exposures"],
                        "clicks": sub_node["clicks"],
                        "interest_weight": sub_node["interest_weight"],
                        "exposure_weight": sub_node["exposure_weight"],
                        "underexplored_score": sub_node["underexplored_score"],
                    }
                )

        cat_node["subcategories"] = sorted(
            subcategories_list, key=lambda x: x["underexplored_score"], reverse=True
        )
        categories_list.append(cat_node)
        flattened_nodes.append(
            {
                "path": category,
                "category": category,
                "subcategory": None,
                "exposures": cat_node["exposures"],
                "clicks": cat_node["clicks"],
                "interest_weight": cat_node["interest_weight"],
                "exposure_weight": cat_node["exposure_weight"],
                "underexplored_score": cat_node["underexplored_score"],
            }
        )

    categories_list = sorted(categories_list, key=lambda x: x["underexplored_score"], reverse=True)

    root["categories"] = categories_list

    underexplored_paths = [
        node["path"] for node in sorted(flattened_nodes, key=lambda x: x["underexplored_score"], reverse=True)[:20]
    ]

    top_json = {
        "user_id": user_id,
        "split_scope": "train_dev",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "half_life_days": half_life_days,
        "epsilon": EPSILON,
        "root": root,
        "underexplored_paths": underexplored_paths,
    }

    return top_json, flattened_nodes


def upsert_user_top(conn, user_id: str, top_json: dict):
    sql = """
        INSERT INTO user_top (user_id, split_scope, generated_at, top_json)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            split_scope = EXCLUDED.split_scope,
            generated_at = EXCLUDED.generated_at,
            top_json = EXCLUDED.top_json
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                user_id,
                top_json["split_scope"],
                datetime.utcnow(),
                json.dumps(top_json),
            ),
        )
    conn.commit()


def upsert_user_nodes(conn, user_id: str, nodes):
    if not nodes:
        return 0
    sql = """
        INSERT INTO user_top_nodes (
            user_id, path, category, subcategory, exposures, clicks,
            interest_weight, exposure_weight, underexplored_score, updated_at
        ) VALUES %s
        ON CONFLICT (user_id, path) DO UPDATE SET
            category = EXCLUDED.category,
            subcategory = EXCLUDED.subcategory,
            exposures = EXCLUDED.exposures,
            clicks = EXCLUDED.clicks,
            interest_weight = EXCLUDED.interest_weight,
            exposure_weight = EXCLUDED.exposure_weight,
            underexplored_score = EXCLUDED.underexplored_score,
            updated_at = EXCLUDED.updated_at
    """
    now = datetime.utcnow()
    values = [
        (
            user_id,
            node["path"],
            node["category"],
            node["subcategory"],
            node["exposures"],
            node["clicks"],
            node["interest_weight"],
            node["exposure_weight"],
            node["underexplored_score"],
            now,
        )
        for node in nodes
    ]
    with conn.cursor() as cur:
        execute_values(cur, sql, values)
    conn.commit()
    return len(nodes)


def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--user_id", type=str, default=None)
    parser.add_argument("--limit_users", type=int, default=None)
    args = parser.parse_args()

    half_life_days = get_float_env("TOP_HALF_LIFE_DAYS", 7.0)

    conn = get_conn()

    users_processed = 0
    nodes_written = 0
    start = time.time()

    if args.user_id:
        user_ids = [args.user_id]
        total = 1
    else:
        user_ids = list(get_user_ids(conn, args.limit_users))
        total = len(user_ids)

    for user_id in tqdm(user_ids, desc="users", unit="user", total=total):
        rows = fetch_user_impressions(conn, user_id)
        top_json, nodes = compute_top(user_id, rows, half_life_days)
        upsert_user_top(conn, user_id, top_json)
        nodes_written += upsert_user_nodes(conn, user_id, nodes)
        users_processed += 1

    elapsed = time.time() - start
    print(f"users_processed={users_processed}")
    print(f"nodes_written={nodes_written}")
    print(f"elapsed_seconds={elapsed:.1f}")

    conn.close()


if __name__ == "__main__":
    main()
