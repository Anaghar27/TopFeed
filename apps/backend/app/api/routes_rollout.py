from __future__ import annotations

import os

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from app.db import get_psycopg_conn
from app.services.rollout import check_rollout_guard, update_rollout_config

router = APIRouter()


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


class RolloutCheckRequest(BaseModel):
    window_minutes: int = Field(default=60, ge=1, le=24 * 60)


class RolloutConfigUpdate(BaseModel):
    updates: dict[str, str]


@router.post("/rollout/check")
def rollout_check(payload: RolloutCheckRequest = Body(...)):
    conn = get_psycopg_conn()
    try:
        result = check_rollout_guard(
            conn,
            window_minutes=payload.window_minutes,
            ctr_drop_threshold=_float_env("CTR_DROP_THRESHOLD", 0.1),
            novelty_spike_threshold=_float_env("NOVELTY_SPIKE_THRESHOLD", 0.1),
        )
        return result
    finally:
        conn.close()


@router.post("/rollout/config")
def rollout_config(update: RolloutConfigUpdate = Body(...)):
    conn = get_psycopg_conn()
    try:
        updated = update_rollout_config(conn, update.updates)
        return {"updated": updated}
    finally:
        conn.close()
