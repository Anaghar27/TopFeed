import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_events import router as events_router
from app.api.routes_metrics import router as metrics_router
from app.api.routes_rollout import router as rollout_router
from app.api.routes_retrieval import router as retrieval_router
from app.api.routes_top import router as top_router
from app.db import check_db_connection
from app.middleware.prometheus_middleware import PrometheusMiddleware

app = FastAPI(title="ToPFeed Backend")

logging.basicConfig(level=logging.INFO)

allowed_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[allowed_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(PrometheusMiddleware)

app.include_router(retrieval_router)
app.include_router(top_router)
app.include_router(events_router)
app.include_router(metrics_router)
app.include_router(rollout_router)


@app.get("/health")
def health_check():
    try:
        check_db_connection()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok"}
