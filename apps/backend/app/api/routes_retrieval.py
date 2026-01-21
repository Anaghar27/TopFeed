import os
import subprocess
import sys

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from app.db import get_psycopg_conn
from app.schemas.feed import ExplainRequest, ExplainResponse, FeedRequest, FeedResponse, PreferredResponse
from app.services.explain import (
    build_explanations,
    load_recent_clicks,
    load_top_node_stats,
    load_user_preferred_ids,
)
from app.services.reranker import rerank as rerank_candidates, score_candidates
from app.services.diversify_top import diversify_greedy
from app.services.retrieval_pgvector import (
    build_user_vector,
    get_recent_seen_news_ids,
    get_user_click_history,
    retrieve_by_vector,
    retrieve_underexplored,
    retrieve_popular,
)

router = APIRouter()


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


def _handle_feed(request: FeedRequest, include_explanations: bool = True):
    top_n = request.top_n or get_int_env("RETRIEVE_TOP_N", 200)
    candidate_pool_n = max(top_n, get_int_env("CANDIDATE_POOL_N", 200))
    explore_ratio = get_float_env("EXPLORE_POOL_RATIO", 0.2)
    explore_ratio = max(0.0, min(0.5, explore_ratio))
    history_k = request.history_k or get_int_env("USER_HISTORY_K", 50)
    half_life_days = get_float_env("USER_HALF_LIFE_DAYS", 7.0)
    exclude_recent_m = get_int_env("EXCLUDE_RECENT_M", 200)

    conn = get_psycopg_conn()
    try:
        clicks = get_user_click_history(conn, request.user_id, history_k)
        if clicks:
            user_vec, _ = build_user_vector(conn, clicks, half_life_days)
        else:
            user_vec = None

        if user_vec is None:
            items = retrieve_popular(conn, top_n)
            method = "popular_fallback"
            if include_explanations:
                top_stats = load_top_node_stats(conn, request.user_id)
                recent_clicks = load_recent_clicks(conn, clicks)
                preferred_ids = load_user_preferred_ids(conn, request.user_id)
                items = build_explanations(
                    request.user_id,
                    items,
                    {
                        "method": method,
                        "top_node_stats": top_stats,
                        "recent_clicks": recent_clicks,
                        "preferred_ids": preferred_ids,
                    },
                )
            return FeedResponse(user_id=request.user_id, items=items, method=method)

        exclude_ids = get_recent_seen_news_ids(conn, request.user_id, exclude_recent_m)

        explore_pool_n = int(candidate_pool_n * explore_ratio)
        vector_pool_n = max(candidate_pool_n - explore_pool_n, 1)

        items = retrieve_by_vector(conn, user_vec, vector_pool_n, exclude_ids)

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
        else:
            method = "rerank_only"

        if include_explanations:
            top_stats = load_top_node_stats(conn, request.user_id)
            recent_clicks = load_recent_clicks(conn, clicks)
            preferred_ids = load_user_preferred_ids(conn, request.user_id)
            items = build_explanations(
                request.user_id,
                items,
                {
                    "method": method,
                    "top_node_stats": top_stats,
                    "recent_clicks": recent_clicks,
                    "preferred_ids": preferred_ids,
                },
            )

        return FeedResponse(
            user_id=request.user_id,
            items=items[:top_n],
            method=method,
            diversification=metrics,
        )
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
        clicks = get_user_click_history(conn, request.user_id, history_k)
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
        clicks = get_user_click_history(conn, user_id, history_k)
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
