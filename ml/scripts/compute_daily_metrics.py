import argparse
import os
from collections import defaultdict
from datetime import date, timedelta

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values


def get_env(name: str, default: str | None = None) -> str:
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


def compute_date_range(days: int):
    end = date.today()
    start = end - timedelta(days=days - 1)
    return start, end


def fetch_base_metrics(conn, start_date: date, end_date: date):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ts::date AS day,
                COALESCE(model_version, 'unknown') AS model_version,
                COALESCE(method, 'unknown') AS method,
                COUNT(*) FILTER (WHERE event_type = 'impression') AS impressions,
                COUNT(*) FILTER (WHERE event_type = 'click') AS clicks,
                COUNT(*) FILTER (WHERE event_type = 'hide') AS hides,
                COUNT(*) FILTER (WHERE event_type = 'save') AS saves,
                AVG(dwell_ms) FILTER (WHERE event_type = 'dwell') AS avg_dwell_ms,
                COUNT(DISTINCT user_id) AS unique_users,
                COUNT(DISTINCT news_id) FILTER (WHERE event_type = 'impression') AS unique_items
            FROM events
            WHERE ts::date BETWEEN %s AND %s
            GROUP BY 1, 2, 3
            """,
            (start_date, end_date),
        )
        return cur.fetchall()


def fetch_coverage_metrics(conn, start_date: date, end_date: date):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                e.ts::date AS day,
                COALESCE(e.model_version, 'unknown') AS model_version,
                COALESCE(e.method, 'unknown') AS method,
                COUNT(DISTINCT i.category) AS coverage_categories,
                COUNT(DISTINCT i.subcategory) AS coverage_subcategories,
                COUNT(*) AS impressions,
                COUNT(DISTINCT i.subcategory) AS unique_subcategories
            FROM events e
            JOIN items i ON i.news_id = e.news_id
            WHERE e.event_type = 'impression'
              AND e.ts::date BETWEEN %s AND %s
            GROUP BY 1, 2, 3
            """,
            (start_date, end_date),
        )
        return cur.fetchall()


def fetch_popularity(conn, start_date: date, end_date: date):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT news_id, COUNT(*) AS impressions
            FROM events
            WHERE event_type = 'impression'
              AND ts::date BETWEEN %s AND %s
            GROUP BY news_id
            """,
            (start_date, end_date),
        )
        return cur.fetchall()


def fetch_impressions_by_group(conn, start_date: date, end_date: date):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ts::date AS day,
                COALESCE(model_version, 'unknown') AS model_version,
                COALESCE(method, 'unknown') AS method,
                news_id,
                COUNT(*) AS impressions
            FROM events
            WHERE event_type = 'impression'
              AND ts::date BETWEEN %s AND %s
            GROUP BY 1, 2, 3, 4
            """,
            (start_date, end_date),
        )
        return cur.fetchall()


def build_novelty_map(popularity_rows):
    counts = [row[1] for row in popularity_rows]
    if not counts:
        return {}
    sorted_counts = sorted(counts)
    n = len(sorted_counts)
    count_to_percentile = {}
    for rank, count in enumerate(sorted_counts):
        if count in count_to_percentile:
            continue
        percentile = rank / max(n - 1, 1)
        count_to_percentile[count] = percentile
    return {row[0]: 1.0 - count_to_percentile[row[1]] for row in popularity_rows}


def compute_novelty(impression_rows, novelty_map):
    novelty = defaultdict(lambda: {"weighted": 0.0, "total": 0})
    for day, model_version, method, news_id, impressions in impression_rows:
        score = novelty_map.get(news_id, 0.0)
        key = (day, model_version, method)
        novelty[key]["weighted"] += score * impressions
        novelty[key]["total"] += impressions
    results = {}
    for key, data in novelty.items():
        if data["total"] > 0:
            results[key] = data["weighted"] / data["total"]
    return results


def upsert_daily_metrics(conn, rows):
    sql = """
        INSERT INTO daily_feed_metrics (
            day, model_version, method,
            impressions, clicks, hides, saves,
            avg_dwell_ms, ctr, save_rate, hide_rate,
            unique_users, unique_items,
            coverage_categories, coverage_subcategories,
            repetition_rate, novelty_proxy
        )
        VALUES %s
        ON CONFLICT (day, model_version, method) DO UPDATE SET
            impressions = EXCLUDED.impressions,
            clicks = EXCLUDED.clicks,
            hides = EXCLUDED.hides,
            saves = EXCLUDED.saves,
            avg_dwell_ms = EXCLUDED.avg_dwell_ms,
            ctr = EXCLUDED.ctr,
            save_rate = EXCLUDED.save_rate,
            hide_rate = EXCLUDED.hide_rate,
            unique_users = EXCLUDED.unique_users,
            unique_items = EXCLUDED.unique_items,
            coverage_categories = EXCLUDED.coverage_categories,
            coverage_subcategories = EXCLUDED.coverage_subcategories,
            repetition_rate = EXCLUDED.repetition_rate,
            novelty_proxy = EXCLUDED.novelty_proxy
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    load_dotenv()
    start_date, end_date = compute_date_range(args.days)

    conn = get_conn()
    try:
        base_rows = fetch_base_metrics(conn, start_date, end_date)
        coverage_rows = fetch_coverage_metrics(conn, start_date, end_date)
        popularity_rows = fetch_popularity(conn, start_date, end_date)
        impression_rows = fetch_impressions_by_group(conn, start_date, end_date)
    finally:
        conn.close()

    coverage_map = {}
    for row in coverage_rows:
        day, model_version, method, cat_count, subcat_count, impressions, unique_subcats = row
        repetition_rate = None
        if impressions:
            repetition_rate = 1.0 - (unique_subcats / impressions)
        coverage_map[(day, model_version, method)] = {
            "coverage_categories": cat_count,
            "coverage_subcategories": subcat_count,
            "repetition_rate": repetition_rate,
        }

    novelty_map = build_novelty_map(popularity_rows)
    novelty_by_group = compute_novelty(impression_rows, novelty_map)

    upsert_rows = []
    for row in base_rows:
        (
            day,
            model_version,
            method,
            impressions,
            clicks,
            hides,
            saves,
            avg_dwell_ms,
            unique_users,
            unique_items,
        ) = row
        ctr = clicks / impressions if impressions else 0.0
        save_rate = saves / impressions if impressions else None
        hide_rate = hides / impressions if impressions else None

        coverage = coverage_map.get((day, model_version, method), {})
        novelty = novelty_by_group.get((day, model_version, method))

        upsert_rows.append(
            (
                day,
                model_version,
                method,
                impressions,
                clicks,
                hides,
                saves,
                avg_dwell_ms,
                ctr,
                save_rate,
                hide_rate,
                unique_users,
                unique_items,
                coverage.get("coverage_categories"),
                coverage.get("coverage_subcategories"),
                coverage.get("repetition_rate"),
                novelty,
            )
        )

    if not upsert_rows:
        print("No metrics to write.")
        return

    conn = get_conn()
    try:
        upsert_daily_metrics(conn, upsert_rows)
        print(f"Wrote metrics for {len(upsert_rows)} rows.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
