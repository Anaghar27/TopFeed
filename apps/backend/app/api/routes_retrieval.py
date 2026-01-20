import os
from typing import List, Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import get_psycopg_conn
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


class RetrievalRequest(BaseModel):
    user_id: str
    top_n: int = Field(default=200, ge=1, le=1000)
    history_k: int = Field(default=50, ge=1, le=500)
    rerank: bool = True
    explore_level: float = Field(default=0.3, ge=0.0, le=1.0)
    diversify: bool = True


class RetrievalItem(BaseModel):
    news_id: str
    title: str | None
    abstract: str | None
    category: str | None
    subcategory: str | None
    url: str | None
    score: float
    rel_score: float | None = None
    top_bonus: float | None = None
    redundancy_penalty: float | None = None
    coverage_gain: float | None = None
    total_score: float | None = None
    top_path: str | None = None


class RetrievalResponse(BaseModel):
    user_id: str
    items: List[RetrievalItem]
    method: Literal["personalized", "popular_fallback"]
    diversification: dict | None = None


@router.post("/retrieve", response_model=RetrievalResponse)
def retrieve_candidates(request: RetrievalRequest):
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
            return RetrievalResponse(user_id=request.user_id, items=items, method="popular_fallback")

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
        if request.diversify:
            reranker_scores = score_candidates(conn, request.user_id, items, history_k, half_life_days)
            diversified, metrics = diversify_greedy(
                request.user_id,
                items,
                reranker_scores,
                request.explore_level,
                top_n,
            )
            return RetrievalResponse(
                user_id=request.user_id,
                items=diversified,
                method="personalized",
                diversification=metrics,
            )
        return RetrievalResponse(user_id=request.user_id, items=items[:top_n], method="personalized")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        conn.close()


@router.post("/feed", response_model=RetrievalResponse)
def feed(request: RetrievalRequest):
    return retrieve_candidates(request)


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
