from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field, validator

from app.db import get_psycopg_conn, insert_events

router = APIRouter()

ALLOWED_EVENT_TYPES = {"impression", "click", "hide", "save", "dwell"}


class EventIn(BaseModel):
    user_id: str
    event_type: str
    news_id: str
    impression_id: str | None = None
    request_id: str | None = None
    model_version: str | None = None
    method: str | None = None
    position: int | None = None
    explore_level: float | None = None
    diversify: bool | None = None
    dwell_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @validator("event_type")
    def validate_event_type(cls, value):
        if value not in ALLOWED_EVENT_TYPES:
            raise ValueError("invalid event_type")
        return value


@router.post("/events")
def ingest_events(payload: Any = Body(...)):
    if isinstance(payload, list):
        raw_events = payload
    elif isinstance(payload, dict):
        raw_events = [payload]
    else:
        raise HTTPException(status_code=400, detail="invalid payload")

    valid_events = []
    dropped = 0
    for raw in raw_events:
        try:
            event = EventIn(**raw).dict()
            valid_events.append(event)
        except Exception:
            dropped += 1

    if not valid_events:
        return {"inserted_count": 0, "dropped_count": dropped}

    conn = get_psycopg_conn()
    try:
        inserted = insert_events(conn, valid_events)
    finally:
        conn.close()

    return {"inserted_count": inserted, "dropped_count": dropped}
