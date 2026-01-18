import os
from typing import List, Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import get_psycopg_conn
from app.services.retrieval_pgvector import (
    build_user_vector,
    get_recent_seen_news_ids,
    get_user_click_history,
    retrieve_by_vector,
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


class RetrievalItem(BaseModel):
    news_id: str
    title: str | None
    abstract: str | None
    category: str | None
    subcategory: str | None
    url: str | None
    score: float


class RetrievalResponse(BaseModel):
    user_id: str
    items: List[RetrievalItem]
    method: Literal["personalized", "popular_fallback"]


@router.post("/retrieve", response_model=RetrievalResponse)
def retrieve_candidates(request: RetrievalRequest):
    top_n = request.top_n or get_int_env("RETRIEVE_TOP_N", 200)
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
        items = retrieve_by_vector(conn, user_vec, top_n, exclude_ids)
        return RetrievalResponse(user_id=request.user_id, items=items, method="personalized")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
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
