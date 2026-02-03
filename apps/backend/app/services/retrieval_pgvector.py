import math
from datetime import datetime, timezone
from typing import Iterable

import numpy as np


TIME_FORMAT = "%m/%d/%Y %I:%M:%S %p"


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(tz=timezone.utc).replace(tzinfo=None)


def parse_time(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return _to_naive_utc(value)
    try:
        return datetime.strptime(str(value), TIME_FORMAT)
    except ValueError:
        pass
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return _to_naive_utc(parsed)
    except ValueError:
        return None


def format_vector(vec: Iterable[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def parse_vector(value) -> np.ndarray | None:
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        return value.astype(np.float32)
    if isinstance(value, (list, tuple)):
        return np.array(value, dtype=np.float32)
    text = str(value).strip().lstrip("[").rstrip("]")
    if not text:
        return None
    return np.fromstring(text, sep=",", dtype=np.float32)


def get_user_click_history(conn, user_id: str, k: int, splits: tuple[str, ...] = ("train", "dev")):
    sql = """
        SELECT im.news_id, s.time, s.split, s.impression_id
        FROM impressions im
        JOIN sessions s
          ON s.impression_id = im.impression_id
         AND s.split = im.split
        WHERE s.user_id = %s
          AND im.clicked = TRUE
          AND s.split = ANY(%s)
        ORDER BY s.impression_id DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (user_id, list(splits), k))
        rows = cur.fetchall()
    return [
        {"news_id": row[0], "time": row[1], "split": row[2], "impression_id": row[3]}
        for row in rows
    ]


def get_user_click_history_events(conn, user_id: str, k: int):
    sql = """
        SELECT news_id, ts
        FROM events
        WHERE user_id = %s
          AND event_type = 'click'
        ORDER BY ts DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (user_id, k))
        rows = cur.fetchall()
    return [
        {"news_id": row[0], "time": row[1], "split": "live", "impression_id": None}
        for row in rows
    ]


def merge_click_histories(primary, secondary, limit: int):
    combined = []
    for click in primary:
        combined.append(("primary", click))
    for click in secondary:
        combined.append(("secondary", click))

    def sort_key(entry):
        _, click = entry
        ts = parse_time(click.get("time"))
        return ts or datetime.min

    combined.sort(key=sort_key, reverse=True)
    deduped = []
    seen = set()
    for _, click in combined:
        news_id = click.get("news_id")
        if not news_id or news_id in seen:
            continue
        seen.add(news_id)
        deduped.append(click)
        if len(deduped) >= limit:
            break
    return deduped


def build_user_vector(conn, clicks, half_life_days: float):
    if not clicks:
        return None, []

    news_ids = [click["news_id"] for click in clicks]
    sql = """
        SELECT news_id, embedding
        FROM items
        WHERE news_id = ANY(%s) AND embedding IS NOT NULL
    """
    with conn.cursor() as cur:
        cur.execute(sql, (news_ids,))
        rows = cur.fetchall()

    vectors = {row[0]: parse_vector(row[1]) for row in rows}

    parsed_times = [parse_time(click["time"]) for click in clicks]
    use_fallback = any(ts is None for ts in parsed_times)

    if use_fallback:
        def sort_key(item):
            try:
                return int(item["impression_id"])
            except (TypeError, ValueError):
                return 0
        ordered_clicks = sorted(clicks, key=sort_key, reverse=True)
        age_map = {c["news_id"]: idx for idx, c in enumerate(ordered_clicks)}
    else:
        now = datetime.utcnow()
        age_map = {}
        for click, ts in zip(clicks, parsed_times):
            age_days = (now - ts).total_seconds() / 86400.0
            age_map[click["news_id"]] = max(age_days, 0.0)

    weights = []
    embeddings = []
    debug = []

    for click in clicks:
        news_id = click["news_id"]
        vec = vectors.get(news_id)
        age_days = age_map.get(news_id, 0.0)
        weight = math.exp(-math.log(2) * age_days / half_life_days) if half_life_days > 0 else 1.0
        used = vec is not None
        debug.append(
            {
                "news_id": news_id,
                "split": click["split"],
                "time": click["time"],
                "weight": weight if used else 0.0,
                "used": used,
            }
        )
        if vec is not None:
            embeddings.append(vec)
            weights.append(weight)

    if not embeddings:
        return None, debug

    weights_np = np.array(weights, dtype=np.float64)
    if weights_np.sum() == 0:
        return None, debug
    vectors_np = np.vstack(embeddings)
    user_vec = np.average(vectors_np, axis=0, weights=weights_np)
    return user_vec, debug


def retrieve_by_vector(conn, user_vec: np.ndarray, top_n: int, exclude_news_ids=None):
    if exclude_news_ids is None:
        exclude_news_ids = []

    vector_str = format_vector(user_vec)

    if exclude_news_ids:
        sql = """
            SELECT news_id, title, abstract, category, subcategory, url, content_type, source,
                   embedding <=> %s::vector AS score
            FROM items
            WHERE embedding IS NOT NULL
              AND news_id <> ALL(%s)
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        params = (vector_str, exclude_news_ids, vector_str, top_n)
    else:
        sql = """
            SELECT news_id, title, abstract, category, subcategory, url, content_type, source,
                   embedding <=> %s::vector AS score
            FROM items
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        params = (vector_str, vector_str, top_n)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {
            "news_id": row[0],
            "title": row[1],
            "abstract": row[2],
            "category": row[3],
            "subcategory": row[4],
            "url": row[5],
            "content_type": row[6],
            "source": row[7],
            "score": float(row[8]),
        }
        for row in rows
    ]


def retrieve_popular(conn, top_n: int, splits: tuple[str, ...] = ("train", "dev")):
    sql = """
        SELECT i.news_id, i.title, i.abstract, i.category, i.subcategory, i.url,
               i.content_type, i.source, COUNT(*) AS clicks
        FROM impressions im
        JOIN items i ON i.news_id = im.news_id
        WHERE im.split = ANY(%s)
          AND im.clicked = TRUE
        GROUP BY i.news_id, i.title, i.abstract, i.category, i.subcategory, i.url,
                 i.content_type, i.source
        ORDER BY clicks DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (list(splits), top_n))
        rows = cur.fetchall()

    return [
        {
            "news_id": row[0],
            "title": row[1],
            "abstract": row[2],
            "category": row[3],
            "subcategory": row[4],
            "url": row[5],
            "content_type": row[6],
            "source": row[7],
            "score": float(row[8]),
        }
        for row in rows
    ]


def retrieve_underexplored(conn, user_id: str, top_n: int, exclude_news_ids=None, max_nodes: int = 12):
    if top_n <= 0:
        return []
    if exclude_news_ids is None:
        exclude_news_ids = []

    per_category = max(1, int(math.ceil(top_n / max_nodes)))

    if exclude_news_ids:
        exclude_clause = "AND i.news_id <> ALL(%s)"
        params = [user_id, max_nodes, exclude_news_ids, per_category, top_n]
    else:
        exclude_clause = ""
        params = [user_id, max_nodes, per_category, top_n]

    sql = f"""
        WITH top_categories AS (
            SELECT category, MAX(underexplored_score) AS score
            FROM user_top_nodes
            WHERE user_id = %s
            GROUP BY category
            ORDER BY score DESC
            LIMIT %s
        ),
        candidates AS (
            SELECT i.news_id, i.title, i.abstract, i.category, i.subcategory, i.url,
                   i.content_type, i.source,
                   COUNT(im.*) FILTER (WHERE im.clicked) AS clicks,
                   ROW_NUMBER() OVER (
                       PARTITION BY i.category
                       ORDER BY COUNT(im.*) FILTER (WHERE im.clicked) DESC NULLS LAST, i.news_id
                   ) AS rn
            FROM items i
            JOIN top_categories n
              ON i.category = n.category
            LEFT JOIN impressions im
              ON im.news_id = i.news_id
             AND im.split IN ('train', 'dev')
             AND im.clicked = TRUE
            WHERE i.embedding IS NOT NULL
            {exclude_clause}
            GROUP BY i.news_id, i.title, i.abstract, i.category, i.subcategory, i.url,
                     i.content_type, i.source
        )
        SELECT news_id, title, abstract, category, subcategory, url,
               content_type, source,
               COALESCE(clicks, 0) AS score
        FROM candidates
        WHERE rn <= %s
        ORDER BY score DESC, news_id
        LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    return [
        {
            "news_id": row[0],
            "title": row[1],
            "abstract": row[2],
            "category": row[3],
            "subcategory": row[4],
            "url": row[5],
            "content_type": row[6],
            "source": row[7],
            "score": float(row[8]),
        }
        for row in rows
    ]


def get_recent_seen_news_ids(conn, user_id: str, m: int, splits: tuple[str, ...] = ("train", "dev")):
    if m <= 0:
        return []
    sql = """
        SELECT im.news_id
        FROM impressions im
        JOIN sessions s
          ON s.impression_id = im.impression_id
         AND s.split = im.split
        WHERE s.user_id = %s
          AND s.split = ANY(%s)
        ORDER BY s.impression_id DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (user_id, list(splits), m))
        rows = cur.fetchall()
    return [row[0] for row in rows]
