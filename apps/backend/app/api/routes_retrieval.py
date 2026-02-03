import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from app.db import get_psycopg_conn
from app.observability.metrics import observe_feed_response
from app.schemas.feed import ExplainRequest, ExplainResponse, FeedRequest, FeedResponse, PreferredResponse
from app.services.explain import (
    build_explanations,
    load_recent_clicks,
    load_top_node_stats,
    load_user_preferred_ids,
)
from app.services.reranker import rerank as rerank_candidates, score_candidates
from app.services.diversify_top import diversify_greedy
from app.services.diversify_top import load_user_top_nodes
from app.services.retrieval_pgvector import (
    build_user_vector,
    get_recent_seen_news_ids,
    get_user_click_history,
    get_user_click_history_events,
    merge_click_histories,
    retrieve_by_vector,
    retrieve_underexplored,
    retrieve_popular,
)
from app.services.rollout import assign_variant, load_rollout_config, model_version_for_variant

router = APIRouter()


def _normalize_scores(values):
    if not values:
        return []
    min_val = min(values)
    max_val = max(values)
    if max_val - min_val == 0:
        return [0.0 for _ in values]
    return [(v - min_val) / (max_val - min_val) for v in values]


def _top_percent_threshold(values, percent):
    if not values:
        return 1.0
    values_sorted = sorted(values, reverse=True)
    idx = max(0, int(np.ceil(len(values_sorted) * percent)) - 1)
    return values_sorted[idx]


def load_preferred_category_counts(conn, user_id: str):
    sql = """
        SELECT i.category, i.subcategory, COUNT(DISTINCT im.news_id)
        FROM impressions im
        JOIN sessions s
          ON s.impression_id = im.impression_id
         AND s.split = im.split
        JOIN items i ON i.news_id = im.news_id
        WHERE s.user_id = %s
          AND s.split = 'live'
          AND im.clicked = TRUE
        GROUP BY i.category, i.subcategory
    """
    with conn.cursor() as cur:
        cur.execute(sql, (user_id,))
        rows = cur.fetchall()
    counts = {}
    for category, subcategory, count in rows:
        if not category:
            continue
        path = f"{category}/{subcategory}" if subcategory else category
        counts[path] = int(count or 0)
    return counts


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


def get_str_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _fetch_fresh_candidates(conn, fresh_hours: int, pool_n: int, require_embedding: bool = True):
    emb_clause = "AND embedding IS NOT NULL" if require_embedding else ""
    sql = f"""
        SELECT news_id, title, abstract, category, subcategory, url,
               published_at, source, content_type, url_hash
        FROM items
        WHERE content_type = 'fresh'
          AND is_fresh = TRUE
          AND published_at >= NOW() - (%s || ' hours')::interval
          {emb_clause}
        ORDER BY published_at DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (fresh_hours, pool_n))
        rows = cur.fetchall()
    candidates = []
    for row in rows:
        published_at = row[6]
        candidates.append(
            {
                "news_id": row[0],
                "title": row[1],
                "abstract": row[2],
                "category": row[3],
                "subcategory": row[4],
                "url": row[5],
                "published_at": published_at.isoformat() if published_at else None,
                "source": row[7],
                "content_type": row[8],
                "url_hash": row[9],
                "score": 0.0,
            }
        )
    return candidates


def _get_recent_event_news_ids(conn, user_id: str, hours: int, limit: int):
    if hours <= 0 or limit <= 0:
        return []
    sql = """
        SELECT news_id
        FROM events
        WHERE user_id = %s
          AND event_type = 'impression'
          AND ts >= NOW() - (%s || ' hours')::interval
        GROUP BY news_id
        ORDER BY MAX(ts) DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (user_id, hours, limit))
        rows = cur.fetchall()
    return [row[0] for row in rows]


def _freshness_bonus(published_at: str | None, fresh_hours: int) -> float:
    if not published_at:
        return 0.0
    try:
        published_dt = datetime.fromisoformat(published_at)
    except ValueError:
        return 0.0
    now = datetime.now(timezone.utc)
    age_hours = (now - published_dt).total_seconds() / 3600.0
    if age_hours < 0:
        age_hours = 0.0
    return max(0.0, 1.0 - (age_hours / float(fresh_hours)))


def _dedupe_items(items):
    seen = set()
    deduped = []
    for item in items:
        key = item.get("url_hash") or item.get("news_id")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _blend_candidates(fresh, fallback, fresh_ratio: float, top_n: int):
    fresh = _dedupe_items(fresh)
    fallback = _dedupe_items(fallback)
    target_fresh = int(round(top_n * fresh_ratio))
    blended = []
    blended.extend(fresh[:target_fresh])
    remaining = top_n - len(blended)
    if remaining > 0:
        existing = {item.get("url_hash") or item.get("news_id") for item in blended}
        blended.extend([item for item in fallback if (item.get("url_hash") or item.get("news_id")) not in existing][:remaining])
    return blended[:top_n]


def _handle_feed(request: FeedRequest, include_explanations: bool = True):
    start = time.perf_counter()
    request_id = uuid.uuid4().hex
    top_n = request.top_n or get_int_env("RETRIEVE_TOP_N", 200)
    candidate_pool_n = max(top_n, get_int_env("CANDIDATE_POOL_N", 200))
    explore_ratio = get_float_env("EXPLORE_POOL_RATIO", 0.2)
    explore_ratio = max(0.0, min(0.5, explore_ratio)) * max(0.0, min(1.0, request.explore_level))
    history_k = request.history_k or get_int_env("USER_HISTORY_K", 50)
    half_life_days = get_float_env("USER_HALF_LIFE_DAYS", 7.0)
    exclude_recent_m = get_int_env("EXCLUDE_RECENT_M", 200)
    live_exclude_hours = get_int_env("LIVE_EXCLUDE_HOURS", 6)
    live_exclude_limit = get_int_env("LIVE_EXCLUDE_LIMIT", 500)

    conn = get_psycopg_conn()
    try:
        rollout_config = load_rollout_config(conn)
        variant = assign_variant(
            user_id=request.user_id, request_id=request_id, config=rollout_config
        )
        preferred_ids = load_user_preferred_ids(conn, request.user_id)
        preferred_counts = load_preferred_category_counts(conn, request.user_id)
        top_stats = None
        mind_clicks = get_user_click_history(conn, request.user_id, history_k)
        event_clicks = get_user_click_history_events(conn, request.user_id, history_k)
        clicks = merge_click_histories(mind_clicks, event_clicks, history_k)
        user_vec, _ = build_user_vector(conn, clicks, half_life_days) if clicks else (None, [])

        recent_event_ids = set(
            _get_recent_event_news_ids(conn, request.user_id, live_exclude_hours, live_exclude_limit)
        )

        if request.feed_mode == "fresh_first":
            fresh_hours = (
                request.fresh_hours if request.fresh_hours is not None else get_int_env("FRESH_HOURS", 168)
            )
            fresh_hours = max(1, min(168, fresh_hours))
            fresh_ratio = (
                request.fresh_ratio if request.fresh_ratio is not None else get_float_env("FRESH_RATIO", 1.0)
            )
            fresh_pool_n = (
                request.fresh_pool_n if request.fresh_pool_n is not None else get_int_env("FRESH_POOL_N", 200)
            )
            fresh_min_items = (
                request.fresh_min_items if request.fresh_min_items is not None else get_int_env("FRESH_MIN_ITEMS", 20)
            )
            fresh_rel_weight = get_float_env("FRESH_REL_WEIGHT", 0.7)
            fresh_freshness_weight = get_float_env("FRESH_FRESHNESS_WEIGHT", 0.3)
            fresh_top_weight = get_float_env("FRESH_TOP_WEIGHT", 0.2)

            fresh_candidates = [
                item
                for item in _fetch_fresh_candidates(conn, fresh_hours, fresh_pool_n, True)
                if item.get("news_id") not in recent_event_ids
            ]
            if not fresh_candidates and recent_event_ids:
                fresh_candidates = _fetch_fresh_candidates(conn, fresh_hours, fresh_pool_n, True)
            if not fresh_candidates:
                fresh_candidates = _fetch_fresh_candidates(conn, fresh_hours, fresh_pool_n, False)
            top_nodes = load_user_top_nodes(conn, request.user_id)
            if len(fresh_candidates) < top_n:
                fallback = [
                    item
                    for item in retrieve_popular(conn, top_n * 2)
                    if item.get("news_id") not in recent_event_ids
                ]
                candidates = _blend_candidates(fresh_candidates, fallback, fresh_ratio, top_n)
            else:
                candidates = fresh_candidates[:top_n]

            if not candidates:
                response = FeedResponse(
                    user_id=request.user_id,
                    items=[],
                    method="popular_fallback",
                    request_id=request_id,
                    model_version=get_str_env("POPULAR_MODEL_VERSION", "popular:v1"),
                    variant=variant,
                )
                observe_feed_response(
                    variant=variant,
                    method="popular_fallback",
                    latency_seconds=time.perf_counter() - start,
                    items=[],
                    diversify_enabled=bool(request.diversify),
                    explore_level=float(request.explore_level or 0.0),
                )
                return response

            base_scores = score_candidates(conn, request.user_id, candidates, history_k, half_life_days)
            freshness_scores = [
                _freshness_bonus(item.get("published_at"), fresh_hours) for item in candidates
            ]
            adjusted_scores = [
                (fresh_rel_weight * rel) + (fresh_freshness_weight * fresh)
                for rel, fresh in zip(base_scores, freshness_scores)
            ]

            if request.diversify:
                items, metrics = diversify_greedy(
                    request.user_id,
                    candidates,
                    adjusted_scores,
                    request.explore_level,
                    top_n,
                )
                if len(items) < top_n:
                    remaining = [
                        item for item in candidates if not item.get("_selected")
                    ]
                    remaining.sort(key=lambda x: x.get("score", 0.0), reverse=True)
                    items.extend(remaining[: max(0, top_n - len(items))])
                for item in candidates:
                    if "_selected" in item:
                        item.pop("_selected", None)
            else:
                for idx, item in enumerate(candidates):
                    category = item.get("category") or ""
                    subcategory = item.get("subcategory") or ""
                    top_bonus = top_nodes.get((category, subcategory), 0.0)
                    item["top_bonus"] = float(top_bonus)
                    item["total_score"] = adjusted_scores[idx] + (fresh_top_weight * float(top_bonus))
                    item["score"] = item["total_score"]
                items = sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)[:top_n]
                metrics = None

            if user_vec is None:
                method = "popular_fallback"
                model_version = get_str_env("POPULAR_MODEL_VERSION", "popular:v1")
            else:
                method = "personalized_top_diversified" if request.diversify else "rerank_only"
                model_version = model_version_for_variant(variant, rollout_config)

            if include_explanations:
                top_stats = load_top_node_stats(conn, request.user_id)
                recent_clicks = load_recent_clicks(conn, clicks)
                items = build_explanations(
                    request.user_id,
                    items,
                    {
                        "method": method,
                        "top_node_stats": top_stats,
                        "recent_clicks": recent_clicks,
                        "preferred_ids": preferred_ids,
                        "preferred_category_counts": preferred_counts,
                        "fresh_hours": fresh_hours,
                        "now": datetime.now(timezone.utc),
                    },
                )
            else:
                for item in items:
                    if item.get("news_id") in preferred_ids:
                        item["is_preferred"] = True
                        category = item.get("category")
                        subcategory = item.get("subcategory")
                        path = f"{category}/{subcategory}" if subcategory else category
                        if preferred_counts.get(path, 0) < 5:
                            item["is_new_interest"] = True

            response = FeedResponse(
                user_id=request.user_id,
                items=items,
                method=method,
                diversification=metrics,
                request_id=request_id,
                model_version=model_version,
                variant=variant,
            )
            observe_feed_response(
                variant=variant,
                method=method,
                latency_seconds=time.perf_counter() - start,
                items=[item if isinstance(item, dict) else item.model_dump() for item in items],
                diversify_enabled=bool(request.diversify),
                explore_level=float(request.explore_level or 0.0),
            )
            return response

        if user_vec is None:
            items = [
                item for item in retrieve_popular(conn, top_n * 2)
                if item.get("news_id") not in recent_event_ids
            ][:top_n]
            method = "popular_fallback"
            model_version = get_str_env("POPULAR_MODEL_VERSION", "popular:v1")
            if include_explanations:
                top_stats = load_top_node_stats(conn, request.user_id)
                recent_clicks = load_recent_clicks(conn, clicks)
                items = build_explanations(
                    request.user_id,
                    items,
                    {
                        "method": method,
                        "top_node_stats": top_stats,
                        "recent_clicks": recent_clicks,
                        "preferred_ids": preferred_ids,
                        "preferred_category_counts": preferred_counts,
                    },
                )
            else:
                for item in items:
                    if item.get("news_id") in preferred_ids:
                        item["is_preferred"] = True
                        category = item.get("category")
                        subcategory = item.get("subcategory")
                        path = f"{category}/{subcategory}" if subcategory else category
                        if preferred_counts.get(path, 0) < 5:
                            item["is_new_interest"] = True
            response = FeedResponse(
                user_id=request.user_id,
                items=items,
                method=method,
                request_id=request_id,
                model_version=model_version,
                variant=variant,
            )
            observe_feed_response(
                variant=variant,
                method=method,
                latency_seconds=time.perf_counter() - start,
                items=[item if isinstance(item, dict) else item.model_dump() for item in items],
                diversify_enabled=bool(request.diversify),
                explore_level=float(request.explore_level or 0.0),
            )
            return response

        exclude_ids = set(get_recent_seen_news_ids(conn, request.user_id, exclude_recent_m))
        exclude_ids |= recent_event_ids

        explore_pool_n = int(candidate_pool_n * explore_ratio)
        vector_pool_n = max(candidate_pool_n - explore_pool_n, 1)

        items = retrieve_by_vector(conn, user_vec, vector_pool_n, list(exclude_ids))

        if explore_pool_n > 0:
            seen_ids = set(exclude_ids) | {item["news_id"] for item in items}
            explore_items = retrieve_underexplored(
                conn,
                request.user_id,
                explore_pool_n,
                list(seen_ids),
            )
            if not explore_items:
                explore_items = retrieve_popular(conn, explore_pool_n)
            for item in explore_items:
                if item["news_id"] not in seen_ids:
                    items.append(item)
                    seen_ids.add(item["news_id"])

            if len(items) < top_n:
                backfill = retrieve_by_vector(conn, user_vec, top_n - len(items), list(seen_ids))
                for item in backfill:
                    if item["news_id"] not in seen_ids:
                        items.append(item)
                        seen_ids.add(item["news_id"])

        if len(items) > candidate_pool_n:
            items = items[:candidate_pool_n]
        if request.rerank:
            items = rerank_candidates(conn, request.user_id, items, history_k, half_life_days)

        metrics = None
        if request.diversify:
            reranker_scores = score_candidates(conn, request.user_id, items, history_k, half_life_days)
            items, metrics = diversify_greedy(
                request.user_id,
                items,
                reranker_scores,
                request.explore_level,
                top_n,
            )
            method = "personalized_top_diversified"
            model_version = model_version_for_variant(variant, rollout_config)
        else:
            method = "rerank_only"
            model_version = model_version_for_variant(variant, rollout_config)

        if include_explanations:
            top_stats = load_top_node_stats(conn, request.user_id)
            recent_clicks = load_recent_clicks(conn, clicks)
            items = build_explanations(
                request.user_id,
                items,
                {
                    "method": method,
                    "top_node_stats": top_stats,
                    "recent_clicks": recent_clicks,
                    "preferred_ids": preferred_ids,
                    "preferred_category_counts": preferred_counts,
                },
            )
        else:
            top_stats = load_top_node_stats(conn, request.user_id)
            top_bonus = []
            for item in items:
                if item.get("news_id") in preferred_ids:
                    item["is_preferred"] = True
                    category = item.get("category")
                    subcategory = item.get("subcategory")
                    path = f"{category}/{subcategory}" if subcategory else category
                    if preferred_counts.get(path, 0) < 5:
                        item["is_new_interest"] = True
                category = item.get("category")
                subcategory = item.get("subcategory")
                path = f"{category}/{subcategory}" if subcategory else category
                top_bonus.append(float(top_stats.get(path, {}).get("underexplored_score", 0.0)))

            top_norm = _normalize_scores(top_bonus)
            top_threshold = _top_percent_threshold(top_norm, 0.3)
            for idx, item in enumerate(items):
                item["is_new_interest"] = (
                    bool(item.get("is_preferred"))
                    and top_norm[idx] >= top_threshold
                    and top_norm[idx] > 0
                )

        response = FeedResponse(
            user_id=request.user_id,
            items=items[:top_n],
            method=method,
            diversification=metrics,
            request_id=request_id,
            model_version=model_version,
            variant=variant,
        )
        observe_feed_response(
            variant=variant,
            method=method,
            latency_seconds=time.perf_counter() - start,
            items=[item if isinstance(item, dict) else item.model_dump() for item in items[:top_n]],
            diversify_enabled=bool(request.diversify),
            explore_level=float(request.explore_level or 0.0),
        )
        return response
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        conn.close()


@router.post("/retrieve", response_model=FeedResponse)
def retrieve_candidates(request: FeedRequest):
    return _handle_feed(request, include_explanations=request.include_explanations)


@router.post("/feed", response_model=FeedResponse)
def feed(request: FeedRequest):
    return _handle_feed(request, include_explanations=request.include_explanations)


@router.post("/feedback")
def feedback(payload: dict):
    user_id = payload.get("user_id")
    news_id = payload.get("news_id")
    action = payload.get("action", "prefer")
    split = payload.get("split", "live")

    if not user_id or not news_id:
        raise HTTPException(status_code=400, detail="user_id and news_id are required")

    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (split, impression_id, user_id, time)
                VALUES (%s, %s, %s, NOW()::text)
                ON CONFLICT (split, impression_id) DO NOTHING
                """,
                (split, f"{user_id}-{news_id}", user_id),
            )
            cur.execute(
                """
                INSERT INTO impressions (split, impression_id, news_id, position, clicked)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (split, impression_id, news_id, position)
                DO UPDATE SET clicked = EXCLUDED.clicked
                """,
                (split, f"{user_id}-{news_id}", news_id, 1, True if action == "prefer" else False),
            )
        conn.commit()
        if action in ("prefer", "unprefer"):
            subprocess.Popen(
                [
                    sys.executable,
                    "/app/ml/scripts/build_top.py",
                    "--user_id",
                    user_id,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    finally:
        conn.close()

    return {"status": "ok"}


@router.post("/explain", response_model=ExplainResponse)
def explain_item(request: ExplainRequest):
    history_k = get_int_env("USER_HISTORY_K", 50)
    conn = get_psycopg_conn()
    try:
        mind_clicks = get_user_click_history(conn, request.user_id, history_k)
        event_clicks = get_user_click_history_events(conn, request.user_id, history_k)
        clicks = merge_click_histories(mind_clicks, event_clicks, history_k)
        top_stats = load_top_node_stats(conn, request.user_id)
        recent_clicks = load_recent_clicks(conn, clicks)
        preferred_ids = load_user_preferred_ids(conn, request.user_id)
        explained = build_explanations(
            request.user_id,
            [request.item.model_dump()],
            {
                "method": request.method,
                "top_node_stats": top_stats,
                "recent_clicks": recent_clicks,
                "preferred_ids": preferred_ids,
                "preferred_category_counts": load_preferred_category_counts(conn, request.user_id),
                "score_context": request.score_context or {},
            },
        )
        return ExplainResponse(item=explained[0])
    finally:
        conn.close()


@router.get("/users/{user_id}/preferred", response_model=PreferredResponse)
def get_preferred(user_id: str, limit: int = Query(default=100, ge=1, le=500)):
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH preferred AS (
                    SELECT im.news_id, MAX(s.time::timestamptz) AS last_time
                    FROM impressions im
                    JOIN sessions s
                      ON s.impression_id = im.impression_id
                     AND s.split = im.split
                    WHERE s.user_id = %s
                      AND s.split = 'live'
                      AND im.clicked = TRUE
                    GROUP BY im.news_id
                )
                SELECT p.news_id, i.title, i.abstract, i.category, i.subcategory, i.url,
                       p.last_time::text
                FROM preferred p
                JOIN items i ON i.news_id = p.news_id
                ORDER BY p.last_time DESC NULLS LAST
                LIMIT %s
                """,
                (user_id, limit),
            )
            rows = cur.fetchall()
        items = [
            {
                "news_id": row[0],
                "title": row[1],
                "abstract": row[2],
                "category": row[3],
                "subcategory": row[4],
                "url": row[5],
                "last_time": row[6],
                "is_preferred": True,
            }
            for row in rows
        ]
        return PreferredResponse(user_id=user_id, items=items)
    finally:
        conn.close()


@router.get("/retrieve/debug/{user_id}")
def retrieve_debug(user_id: str):
    history_k = get_int_env("USER_HISTORY_K", 50)
    half_life_days = get_float_env("USER_HALF_LIFE_DAYS", 7.0)

    conn = get_psycopg_conn()
    try:
        mind_clicks = get_user_click_history(conn, user_id, history_k)
        event_clicks = get_user_click_history_events(conn, user_id, history_k)
        clicks = merge_click_histories(mind_clicks, event_clicks, history_k)
        user_vec, debug = build_user_vector(conn, clicks, half_life_days)
        if user_vec is None:
            return {
                "user_id": user_id,
                "method": "popular_fallback",
                "vector_norm": 0.0,
                "used_clicks": debug,
            }
        return {
            "user_id": user_id,
            "method": "personalized",
            "vector_norm": float(np.linalg.norm(user_vec)),
            "used_clicks": debug,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        conn.close()
