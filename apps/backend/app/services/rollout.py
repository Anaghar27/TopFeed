from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass

from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)

def _bool_from_value(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_from_value(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RolloutConfig:
    canary_enabled: bool
    canary_percent: int
    control_model_version: str
    canary_model_version: str
    canary_auto_disable: bool


def _get_env_default(key: str, default: str) -> str:
    value = os.getenv(key)
    if value is None or value == "":
        return default
    return value


def _get_rollout_value(conn: PgConnection, key: str, default: str) -> str:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM rollout_config WHERE key = %s", (key,))
            row = cur.fetchone()
        if row and row[0] is not None:
            return str(row[0])
    except Exception:
        conn.rollback()
        return default
    return default


def _set_rollout_value(conn: PgConnection, key: str, value: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rollout_config (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key)
            DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            (key, value),
        )
    conn.commit()


def load_rollout_config(conn: PgConnection) -> RolloutConfig:
    canary_enabled = _bool_from_value(
        _get_rollout_value(conn, "CANARY_ENABLED", _get_env_default("CANARY_ENABLED", "false"))
    )
    canary_percent_raw = _get_rollout_value(
        conn, "CANARY_PERCENT", _get_env_default("CANARY_PERCENT", "5")
    )
    canary_percent = max(0, min(100, _int_from_value(canary_percent_raw, 0)))

    control_model_version = _get_rollout_value(
        conn,
        "CONTROL_MODEL_VERSION",
        _get_env_default("CONTROL_MODEL_VERSION", "reranker_baseline:v1"),
    )
    canary_model_version = _get_rollout_value(
        conn,
        "CANARY_MODEL_VERSION",
        _get_env_default("CANARY_MODEL_VERSION", "reranker_baseline:v2"),
    )
    canary_auto_disable = _bool_from_value(
        _get_rollout_value(
            conn,
            "CANARY_AUTO_DISABLE",
            _get_env_default("CANARY_AUTO_DISABLE", "false"),
        )
    )

    return RolloutConfig(
        canary_enabled=canary_enabled,
        canary_percent=canary_percent,
        control_model_version=control_model_version,
        canary_model_version=canary_model_version,
        canary_auto_disable=canary_auto_disable,
    )


def assign_variant(*, user_id: str | None, request_id: str | None, config: RolloutConfig) -> str:
    if not config.canary_enabled or config.canary_percent <= 0:
        return "control"
    key = user_id or request_id or "anonymous"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    if bucket < config.canary_percent:
        return "canary"
    return "control"


def model_version_for_variant(variant: str, config: RolloutConfig) -> str:
    if variant == "canary":
        return config.canary_model_version
    return config.control_model_version


def _rollout_stats_for_window(
    conn: PgConnection,
    window_minutes: int,
    control_model_version: str,
    canary_model_version: str,
) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                model_version,
                COUNT(*) FILTER (WHERE event_type = 'impression') AS impressions,
                COUNT(*) FILTER (WHERE event_type = 'click') AS clicks,
                AVG(
                    CASE
                        WHEN event_type = 'impression'
                         AND metadata ? 'novelty_proxy'
                        THEN (metadata->>'novelty_proxy')::float
                        ELSE NULL
                    END
                ) AS novelty_proxy
            FROM events
            WHERE ts >= NOW() - (%s || ' minutes')::interval
              AND model_version IN (%s, %s)
            GROUP BY model_version
            """,
            (window_minutes, control_model_version, canary_model_version),
        )
        rows = cur.fetchall()

    stats = {
        "control": {
            "model_version": control_model_version,
            "impressions": 0,
            "clicks": 0,
            "ctr": 0.0,
            "novelty_proxy": None,
        },
        "canary": {
            "model_version": canary_model_version,
            "impressions": 0,
            "clicks": 0,
            "ctr": 0.0,
            "novelty_proxy": None,
        },
    }

    for model_version, impressions, clicks, novelty_proxy in rows:
        key = "canary" if model_version == canary_model_version else "control"
        impressions = int(impressions or 0)
        clicks = int(clicks or 0)
        ctr = float(clicks) / float(impressions) if impressions > 0 else 0.0
        stats[key] = {
            "model_version": model_version,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": ctr,
            "novelty_proxy": float(novelty_proxy) if novelty_proxy is not None else None,
        }

    return stats


def check_rollout_guard(
    conn: PgConnection,
    *,
    window_minutes: int,
    ctr_drop_threshold: float,
    novelty_spike_threshold: float,
) -> dict:
    config = load_rollout_config(conn)
    stats = _rollout_stats_for_window(
        conn, window_minutes, config.control_model_version, config.canary_model_version
    )

    control_ctr = stats["control"]["ctr"]
    canary_ctr = stats["canary"]["ctr"]
    control_novelty = stats["control"]["novelty_proxy"]
    canary_novelty = stats["canary"]["novelty_proxy"]

    ctr_drop = 0.0
    if control_ctr > 0:
        ctr_drop = 1.0 - (canary_ctr / control_ctr)

    novelty_delta = None
    if control_novelty is not None and canary_novelty is not None:
        novelty_delta = canary_novelty - control_novelty

    should_rollback = (
        ctr_drop >= ctr_drop_threshold
        and novelty_delta is not None
        and novelty_delta >= novelty_spike_threshold
    )

    auto_disabled = False
    if should_rollback and config.canary_auto_disable and config.canary_enabled:
        _set_rollout_value(conn, "CANARY_ENABLED", "false")
        auto_disabled = True

    if should_rollback:
        logger.warning(
            "Rollout guard triggered: ctr_drop=%.4f novelty_delta=%s auto_disabled=%s",
            ctr_drop,
            f"{novelty_delta:.4f}" if novelty_delta is not None else "none",
            auto_disabled,
        )

    return {
        "window_minutes": window_minutes,
        "thresholds": {
            "ctr_drop_threshold": ctr_drop_threshold,
            "novelty_spike_threshold": novelty_spike_threshold,
        },
        "stats": stats,
        "ctr_drop": ctr_drop,
        "novelty_delta": novelty_delta,
        "rollback_recommended": should_rollback,
        "auto_disabled": auto_disabled,
    }


def update_rollout_config(conn: PgConnection, updates: dict[str, str]) -> dict[str, str]:
    for key, value in updates.items():
        _set_rollout_value(conn, key, value)
    return updates
