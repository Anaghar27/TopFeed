from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import requests
from psycopg2.extras import execute_values
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


@dataclass
class FreshItem:
    news_id: str
    url: str
    url_hash: str
    published_at: datetime | None
    source: str
    title: str
    description: str
    category: str
    subcategory: str


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().split())


def _canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [(k, v) for k, v in query if not k.lower().startswith("utm_") and k.lower() not in {"ref", "fbclid"}]
    new_query = urlencode(filtered)
    cleaned = parsed._replace(fragment="", query=new_query)
    return urlunparse(cleaned)


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _news_id_from_hash(url_hash: str) -> str:
    return f"FRESH_{url_hash[:12]}"


def _map_category(title: str, description: str, tags: list[str]) -> tuple[str, str]:
    text = f"{title} {description} {' '.join(tags)}".lower()
    tag_text = " ".join(tags).lower()

    tag_rules = [
        ("politic", ("news", "newspolitics")),
        ("election", ("news", "newspolitics")),
        ("government", ("news", "newspolitics")),
        ("business", ("finance", "financeeconomy")),
        ("economy", ("finance", "financeeconomy")),
        ("finance", ("finance", "financeeconomy")),
        ("market", ("finance", "financeeconomy")),
        ("stock", ("finance", "financeeconomy")),
        ("sport", ("sports", "sportsnews")),
        ("football", ("sports", "football_nfl")),
        ("soccer", ("sports", "soccer")),
        ("basketball", ("sports", "basketball_nba")),
        ("baseball", ("sports", "baseball_mlb")),
        ("tennis", ("sports", "tennis")),
        ("cricket", ("sports", "cricket")),
        ("tech", ("news", "tech")),
        ("technology", ("news", "tech")),
        ("ai", ("news", "tech")),
        ("science", ("news", "science")),
        ("health", ("health", "health")),
        ("medicine", ("health", "health")),
        ("covid", ("health", "health")),
        ("travel", ("travel", "travel")),
        ("food", ("foodanddrink", "foodanddrink")),
        ("recipe", ("foodanddrink", "foodanddrink")),
        ("entertainment", ("entertainment", "entertainment-celebrity")),
        ("celebrity", ("entertainment", "entertainment-celebrity")),
        ("movie", ("entertainment", "entertainment-celebrity")),
        ("tv", ("tv", "tv-celebrity")),
        ("music", ("music", "musicnews")),
        ("world", ("news", "newsworld")),
        ("us", ("news", "newsus")),
        ("opinion", ("news", "newsopinion")),
    ]
    for keyword, mapped in tag_rules:
        if keyword in tag_text:
            return mapped

    rules = [
        ("politic", ("news", "newspolitics")),
        ("election", ("news", "newspolitics")),
        ("government", ("news", "newspolitics")),
        ("white house", ("news", "newspolitics")),
        ("congress", ("news", "newspolitics")),
        ("parliament", ("news", "newspolitics")),
        ("business", ("finance", "financeeconomy")),
        ("economy", ("finance", "financeeconomy")),
        ("market", ("finance", "financeeconomy")),
        ("finance", ("finance", "financeeconomy")),
        ("stock", ("finance", "financeeconomy")),
        ("inflation", ("finance", "financeeconomy")),
        ("bank", ("finance", "financeeconomy")),
        ("crypto", ("finance", "financeeconomy")),
        ("sport", ("sports", "sportsnews")),
        ("football", ("sports", "football_nfl")),
        ("soccer", ("sports", "soccer")),
        ("basketball", ("sports", "basketball_nba")),
        ("baseball", ("sports", "baseball_mlb")),
        ("tennis", ("sports", "tennis")),
        ("cricket", ("sports", "cricket")),
        ("tech", ("news", "tech")),
        ("technology", ("news", "tech")),
        ("ai", ("news", "tech")),
        ("cyber", ("news", "tech")),
        ("startup", ("news", "tech")),
        ("health", ("health", "health")),
        ("medicine", ("health", "health")),
        ("hospital", ("health", "health")),
        ("vaccine", ("health", "health")),
        ("travel", ("travel", "travel")),
        ("flight", ("travel", "travel")),
        ("food", ("foodanddrink", "foodanddrink")),
        ("recipe", ("foodanddrink", "foodanddrink")),
        ("restaurant", ("foodanddrink", "foodanddrink")),
        ("entertainment", ("entertainment", "entertainment-celebrity")),
        ("celebrity", ("entertainment", "entertainment-celebrity")),
        ("movie", ("entertainment", "entertainment-celebrity")),
        ("film", ("entertainment", "entertainment-celebrity")),
        ("tv", ("tv", "tv-celebrity")),
        ("music", ("music", "musicnews")),
        ("science", ("news", "science")),
        ("climate", ("news", "science")),
        ("space", ("news", "science")),
        ("world", ("news", "newsworld")),
        ("europe", ("news", "newsworld")),
        ("asia", ("news", "newsworld")),
        ("africa", ("news", "newsworld")),
        ("america", ("news", "newsus")),
        ("us ", ("news", "newsus")),
        ("u.s.", ("news", "newsus")),
        ("opinion", ("news", "newsopinion")),
    ]
    for keyword, mapped in rules:
        if keyword in text:
            return mapped
    return "unknown", "unknown"


def _parse_published(entry) -> datetime | None:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published:
        return datetime(*published[:6], tzinfo=timezone.utc)
    return None


def load_rss_sources(config_path: str) -> list[dict]:
    with open(config_path, "r") as handle:
        data = json.load(handle)
    return data.get("sources", [])


def fetch_rss_items(config_path: str, hours: int) -> list[FreshItem]:
    sources = load_rss_sources(config_path)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items: list[FreshItem] = []

    for source in sources:
        url = source.get("url")
        name = source.get("name") or "rss"
        source_tag = source.get("source_tag") or f"rss:{name}"
        if not url:
            continue
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("RSS fetch failed for %s: %s", url, exc)
            continue

        parsed = feedparser.parse(response.content)
        for entry in parsed.entries:
            link = entry.get("link") or entry.get("id")
            if not link:
                continue
            canonical_url = _canonicalize_url(link)
            url_hash = _hash_url(canonical_url)
            news_id = _news_id_from_hash(url_hash)
            title = _normalize_text(entry.get("title"))
            description = _normalize_text(entry.get("summary") or "")
            if not description and entry.get("content"):
                description = _normalize_text(entry.get("content")[0].get("value"))
            tags = [tag.get("term", "") for tag in entry.get("tags", []) if tag.get("term")]
            category, subcategory = _map_category(title, description, tags)
            published_at = _parse_published(entry)
            if published_at and published_at < cutoff:
                continue

            items.append(
                FreshItem(
                    news_id=news_id,
                    url=canonical_url,
                    url_hash=url_hash,
                    published_at=published_at,
                    source=source_tag,
                    title=title,
                    description=description,
                    category=category,
                    subcategory=subcategory,
                )
            )

    return items


def _existing_hashes(conn, url_hashes: list[str]) -> set[str]:
    if not url_hashes:
        return set()
    with conn.cursor() as cur:
        cur.execute("SELECT url_hash FROM items WHERE url_hash = ANY(%s)", (url_hashes,))
        rows = cur.fetchall()
    return {row[0] for row in rows if row[0]}


def upsert_fresh_items(conn, items: list[FreshItem]) -> tuple[int, int]:
    if not items:
        return 0, 0
    deduped = {}
    for item in items:
        if item.url_hash:
            deduped[item.url_hash] = item
    items = list(deduped.values())
    url_hashes = [item.url_hash for item in items]
    existing = _existing_hashes(conn, url_hashes)

    values = [
        (
            item.news_id,
            item.title,
            item.description,
            item.url,
            item.category or "unknown",
            item.subcategory or "unknown",
            "fresh",
            item.source,
            item.published_at,
            item.url_hash,
            True,
        )
        for item in items
    ]

    sql = """
        INSERT INTO items (
            news_id, title, abstract, url, category, subcategory,
            content_type, source, published_at, url_hash, is_fresh
        ) VALUES %s
        ON CONFLICT (url_hash) DO UPDATE SET
            title = EXCLUDED.title,
            abstract = EXCLUDED.abstract,
            url = EXCLUDED.url,
            category = EXCLUDED.category,
            subcategory = EXCLUDED.subcategory,
            content_type = EXCLUDED.content_type,
            source = EXCLUDED.source,
            published_at = EXCLUDED.published_at,
            is_fresh = EXCLUDED.is_fresh
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, values)
    conn.commit()

    inserted = len([u for u in url_hashes if u not in existing])
    updated = len(url_hashes) - inserted
    return inserted, updated


def _compute_quality(items: list[FreshItem], deduped_count: int) -> dict:
    total = len(items)
    duplicates_dropped = max(0, total - deduped_count)
    if total == 0:
        return {
            "total_items": 0,
            "deduped_items": 0,
            "duplicates_dropped": 0,
            "missing_title_pct": 0.0,
            "missing_abstract_pct": 0.0,
            "unknown_category_pct": 0.0,
            "unknown_subcategory_pct": 0.0,
            "avg_title_len": 0.0,
            "avg_abstract_len": 0.0,
            "with_published_at_pct": 0.0,
            "published_last_24h_pct": 0.0,
            "published_last_7d_pct": 0.0,
            "sources": {},
        }

    missing_title = 0
    missing_abstract = 0
    unknown_category = 0
    unknown_subcategory = 0
    title_len = 0
    abstract_len = 0
    with_published = 0
    last_24h = 0
    last_7d = 0
    sources: dict[str, int] = {}
    now = datetime.now(timezone.utc)

    for item in items:
        title = _normalize_text(item.title)
        abstract = _normalize_text(item.description)
        if not title:
            missing_title += 1
        if not abstract:
            missing_abstract += 1
        if item.category in (None, "", "unknown"):
            unknown_category += 1
        if item.subcategory in (None, "", "unknown"):
            unknown_subcategory += 1
        title_len += len(title)
        abstract_len += len(abstract)
        if item.published_at:
            with_published += 1
            age_hours = (now - item.published_at).total_seconds() / 3600.0
            if age_hours <= 24:
                last_24h += 1
            if age_hours <= 24 * 7:
                last_7d += 1
        if item.source:
            sources[item.source] = sources.get(item.source, 0) + 1

    return {
        "total_items": total,
        "deduped_items": deduped_count,
        "duplicates_dropped": duplicates_dropped,
        "missing_title_pct": missing_title / total,
        "missing_abstract_pct": missing_abstract / total,
        "unknown_category_pct": unknown_category / total,
        "unknown_subcategory_pct": unknown_subcategory / total,
        "avg_title_len": title_len / total,
        "avg_abstract_len": abstract_len / total,
        "with_published_at_pct": with_published / total,
        "published_last_24h_pct": last_24h / total,
        "published_last_7d_pct": last_7d / total,
        "sources": sources,
    }


def record_ingest_run(
    conn,
    *,
    source: str,
    window_hours: int,
    items: list[FreshItem],
    inserted: int,
    updated: int,
    embedded: int,
    status: str,
    error: str | None,
) -> dict:
    run_id = uuid.uuid4().hex
    started_at = datetime.now(timezone.utc)
    finished_at = datetime.now(timezone.utc)
    deduped_count = len({item.url_hash for item in items if item.url_hash})
    quality = _compute_quality(items, deduped_count)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fresh_ingest_runs (
                run_id, started_at, finished_at, source, window_hours,
                items_fetched, items_inserted, items_updated, items_embedded,
                quality_json, status, error
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                started_at,
                finished_at,
                source,
                window_hours,
                len(items),
                inserted,
                updated,
                embedded,
                json.dumps(quality),
                status,
                error,
            ),
        )
    conn.commit()
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "source": source,
        "window_hours": window_hours,
        "items_fetched": len(items),
        "items_inserted": inserted,
        "items_updated": updated,
        "items_embedded": embedded,
        "quality": quality,
        "status": status,
        "error": error,
    }


def _format_vector(vec: Iterable[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def embed_fresh_items(
    conn,
    *,
    model_name: str,
    emb_batch_size: int,
    fetch_batch_size: int,
) -> int:
    model = SentenceTransformer(model_name, device="cpu")
    embedded = 0
    last_news_id: str | None = None

    while True:
        if last_news_id is None:
            sql = """
                SELECT news_id, title, abstract
                FROM items
                WHERE content_type = 'fresh' AND embedding IS NULL
                ORDER BY news_id
                LIMIT %s
            """
            params = (fetch_batch_size,)
        else:
            sql = """
                SELECT news_id, title, abstract
                FROM items
                WHERE content_type = 'fresh' AND embedding IS NULL AND news_id > %s
                ORDER BY news_id
                LIMIT %s
            """
            params = (last_news_id, fetch_batch_size)

        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        if not rows:
            break

        last_news_id = rows[-1][0]

        news_ids = []
        texts = []
        for news_id, title, abstract in rows:
            text = (_normalize_text(title) + " " + _normalize_text(abstract)).strip()
            if not text:
                continue
            news_ids.append(news_id)
            texts.append(text)

        if not texts:
            continue

        vectors = model.encode(
            texts,
            batch_size=emb_batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        values = [(nid, _format_vector(vec)) for nid, vec in zip(news_ids, vectors)]
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                UPDATE items AS i
                SET embedding = v.embedding
                FROM (VALUES %s) AS v(news_id, embedding)
                WHERE i.news_id = v.news_id
                """,
                values,
                template="(%s, %s::vector)",
            )
        conn.commit()
        embedded += len(values)

    return embedded


def run_fresh_ingest(conn, *, config_path: str, hours: int) -> dict:
    run_id = uuid.uuid4().hex
    started_at = datetime.now(timezone.utc)
    result = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "items_fetched": 0,
        "items_inserted": 0,
        "items_updated": 0,
        "items_embedded": 0,
        "quality": {},
        "status": "running",
        "error": None,
    }

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fresh_ingest_runs (run_id, started_at, source, window_hours, status, quality_json)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (run_id, started_at, "rss", hours, "running", json.dumps({})),
        )
    conn.commit()

    try:
        items = fetch_rss_items(config_path, hours)
        result["items_fetched"] = len(items)
        deduped_count = len({item.url_hash for item in items if item.url_hash})
        result["quality"] = _compute_quality(items, deduped_count)
        inserted, updated = upsert_fresh_items(conn, items)
        result["items_inserted"] = inserted
        result["items_updated"] = updated

        model_name = os.getenv("EMB_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
        emb_batch_size = int(os.getenv("EMB_BATCH_SIZE", "128"))
        fetch_batch_size = int(os.getenv("EMB_FETCH_BATCH", "2000"))
        embedded = embed_fresh_items(
            conn,
            model_name=model_name,
            emb_batch_size=emb_batch_size,
            fetch_batch_size=fetch_batch_size,
        )
        result["items_embedded"] = embedded
        result["status"] = "success"
    except Exception as exc:
        conn.rollback()
        result["status"] = "error"
        result["error"] = str(exc)
        raise
    finally:
        finished_at = datetime.now(timezone.utc)
        result["finished_at"] = finished_at.isoformat()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE fresh_ingest_runs
                SET finished_at = %s,
                    items_fetched = %s,
                    items_inserted = %s,
                    items_updated = %s,
                    items_embedded = %s,
                    quality_json = %s,
                    status = %s,
                    error = %s
                WHERE run_id = %s
                """,
                (
                    finished_at,
                    result["items_fetched"],
                    result["items_inserted"],
                    result["items_updated"],
                    result["items_embedded"],
                    json.dumps(result.get("quality") or {}),
                    result["status"],
                    result.get("error"),
                    run_id,
                ),
            )
        conn.commit()

    return result


def _ensure_watermark(conn) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT last_run_at FROM top_update_watermark")
        row = cur.fetchone()
    if row is None:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO top_update_watermark (last_run_at) VALUES (NULL)")
        conn.commit()
        return None
    return row[0]


def update_top_incremental(conn, *, window_hours: int) -> dict:
    now = datetime.now(timezone.utc)
    last_run = _ensure_watermark(conn)
    if last_run is None:
        start_ts = now - timedelta(hours=window_hours)
    else:
        start_ts = last_run

    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT user_id FROM events WHERE ts >= %s", (start_ts,))
        users = [row[0] for row in cur.fetchall()]

    users_processed = 0
    nodes_written = 0
    for user_id in users:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT i.category, i.subcategory,
                       COUNT(*) FILTER (WHERE e.event_type = 'impression') AS exposures,
                       COUNT(*) FILTER (WHERE e.event_type = 'click') AS clicks
                FROM events e
                JOIN items i ON i.news_id = e.news_id
                WHERE e.user_id = %s
                  AND e.ts >= %s
                  AND e.event_type IN ('impression','click')
                GROUP BY i.category, i.subcategory
                """,
                (user_id, start_ts),
            )
            rows = cur.fetchall()

        if not rows:
            continue

        total_exposures = sum(int(row[2] or 0) for row in rows)
        total_clicks = sum(int(row[3] or 0) for row in rows)

        categories: dict[str, dict] = {}
        nodes = []
        for category, subcategory, exposures, clicks in rows:
            category = category or "unknown"
            subcategory = subcategory or "unknown"
            exposures = int(exposures or 0)
            clicks = int(clicks or 0)
            underexplored = float(clicks / (exposures + 1e-6)) if exposures > 0 else 0.0

            if category not in categories:
                categories[category] = {
                    "category": category,
                    "exposures": 0,
                    "clicks": 0,
                    "interest_weight": 0.0,
                    "exposure_weight": 0.0,
                    "subcategories": [],
                }
            cat = categories[category]
            cat["exposures"] += exposures
            cat["clicks"] += clicks
            cat["interest_weight"] += clicks
            cat["exposure_weight"] += exposures
            cat["subcategories"].append(
                {
                    "subcategory": subcategory,
                    "exposures": exposures,
                    "clicks": clicks,
                    "interest_weight": clicks,
                    "exposure_weight": exposures,
                    "underexplored_score": underexplored,
                }
            )

            path = f"{category}/{subcategory}" if subcategory else category
            nodes.append(
                {
                    "path": path,
                    "category": category,
                    "subcategory": subcategory,
                    "exposures": exposures,
                    "clicks": clicks,
                    "interest_weight": float(clicks),
                    "exposure_weight": float(exposures),
                    "underexplored_score": underexplored,
                }
            )

        categories_list = []
        for category, cat_node in categories.items():
            exposures = cat_node["exposures"]
            clicks = cat_node["clicks"]
            cat_node["ctr"] = float(clicks / exposures) if exposures else 0.0
            cat_node["underexplored_score"] = float(cat_node["interest_weight"] / (cat_node["exposure_weight"] + 1e-6))
            cat_node["subcategories"] = sorted(
                cat_node["subcategories"], key=lambda x: x["underexplored_score"], reverse=True
            )
            categories_list.append(cat_node)
            nodes.append(
                {
                    "path": category,
                    "category": category,
                    "subcategory": None,
                    "exposures": exposures,
                    "clicks": clicks,
                    "interest_weight": float(clicks),
                    "exposure_weight": float(exposures),
                    "underexplored_score": cat_node["underexplored_score"],
                }
            )

        categories_list.sort(key=lambda x: x["underexplored_score"], reverse=True)

        underexplored_paths = [
            node["path"] for node in sorted(nodes, key=lambda x: x["underexplored_score"], reverse=True)[:20]
        ]

        top_json = {
            "user_id": user_id,
            "split_scope": "live_recent",
            "generated_at": now.isoformat(),
            "window_start": start_ts.isoformat(),
            "window_hours": window_hours,
            "root": {
                "exposures": total_exposures,
                "clicks": total_clicks,
                "ctr": float(total_clicks / total_exposures) if total_exposures else 0.0,
                "interest_weight": float(total_clicks),
                "exposure_weight": float(total_exposures),
                "underexplored_score": float(total_clicks / (total_exposures + 1e-6)) if total_exposures else 0.0,
                "categories": categories_list,
            },
            "underexplored_paths": underexplored_paths,
        }

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_top (user_id, split_scope, generated_at, top_json)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    split_scope = EXCLUDED.split_scope,
                    generated_at = EXCLUDED.generated_at,
                    top_json = EXCLUDED.top_json
                """,
                (user_id, top_json["split_scope"], now, json.dumps(top_json)),
            )

        if nodes:
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
                execute_values(
                    cur,
                    """
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
                    """,
                    values,
                )
            nodes_written += len(values)

        users_processed += 1

    with conn.cursor() as cur:
        cur.execute("UPDATE top_update_watermark SET last_run_at = %s", (now,))
    conn.commit()

    return {
        "window_hours": window_hours,
        "start_ts": start_ts.isoformat(),
        "end_ts": now.isoformat(),
        "users_processed": users_processed,
        "nodes_written": nodes_written,
    }
