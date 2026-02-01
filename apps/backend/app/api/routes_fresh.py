from __future__ import annotations

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from app.db import get_psycopg_conn
from app.services.fresh_ingest import run_fresh_ingest, update_top_incremental

router = APIRouter()


class FreshIngestRequest(BaseModel):
    hours: int = Field(default=24, ge=1, le=168)
    config_path: str = "/app/ml/config/rss_sources.json"


class TopUpdateRequest(BaseModel):
    window_hours: int = Field(default=1, ge=1, le=168)


@router.post("/fresh/ingest")
def fresh_ingest(payload: FreshIngestRequest = Body(...)):
    conn = get_psycopg_conn()
    try:
        return run_fresh_ingest(conn, config_path=payload.config_path, hours=payload.hours)
    finally:
        conn.close()


@router.post("/top/update")
def top_update(payload: TopUpdateRequest = Body(...)):
    conn = get_psycopg_conn()
    try:
        return update_top_incremental(conn, window_hours=payload.window_hours)
    finally:
        conn.close()


@router.get("/fresh/quality")
def fresh_quality():
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, started_at, finished_at, source, window_hours,
                       items_fetched, items_inserted, items_updated, items_embedded,
                       quality_json, status, error
                FROM fresh_ingest_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
        if not row:
            return {"status": "no_runs"}
        return {
            "run_id": row[0],
            "started_at": row[1].isoformat() if row[1] else None,
            "finished_at": row[2].isoformat() if row[2] else None,
            "source": row[3],
            "window_hours": row[4],
            "items_fetched": row[5],
            "items_inserted": row[6],
            "items_updated": row[7],
            "items_embedded": row[8],
            "quality": row[9] or {},
            "status": row[10],
            "error": row[11],
        }
    finally:
        conn.close()
