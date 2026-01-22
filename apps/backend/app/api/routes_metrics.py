from fastapi import APIRouter, Query

from app.db import get_psycopg_conn

router = APIRouter()


@router.get("/metrics/summary")
def metrics_summary(
    days: int = Query(default=14, ge=1, le=365),
    method: str | None = None,
    model_version: str | None = None,
    user_id: str | None = None,
):
    conn = get_psycopg_conn()
    try:
        if user_id:
            filters = ["user_id = %s", "ts::date >= CURRENT_DATE - (%s || ' days')::interval"]
            params = [user_id, days]
            if method:
                filters.append("method = %s")
                params.append(method)
            if model_version:
                filters.append("model_version = %s")
                params.append(model_version)
            where_sql = " AND ".join(filters)

            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        ts::date AS day,
                        COALESCE(model_version, 'unknown') AS model_version,
                        COALESCE(method, 'unknown') AS method,
                        COUNT(*) FILTER (WHERE event_type = 'impression') AS impressions,
                        COUNT(*) FILTER (WHERE event_type = 'click') AS clicks,
                        COUNT(*) FILTER (WHERE event_type = 'hide') AS hides,
                        COUNT(*) FILTER (WHERE event_type = 'save') AS saves,
                        AVG(dwell_ms) FILTER (WHERE event_type = 'dwell') AS avg_dwell_ms
                    FROM events
                    WHERE {where_sql}
                    GROUP BY 1, 2, 3
                    ORDER BY day ASC
                    """,
                    params,
                )
                rows = cur.fetchall()

            series = [
                {
                    "day": row[0].isoformat(),
                    "model_version": row[1],
                    "method": row[2],
                    "impressions": int(row[3]),
                    "clicks": int(row[4]),
                    "hides": int(row[5]),
                    "saves": int(row[6]),
                    "avg_dwell_ms": float(row[7]) if row[7] is not None else None,
                    "ctr": float(row[4]) / float(row[3]) if row[3] else 0.0,
                }
                for row in rows
            ]

            totals = {
                "impressions": sum(item["impressions"] for item in series),
                "clicks": sum(item["clicks"] for item in series),
                "hides": sum(item["hides"] for item in series),
                "saves": sum(item["saves"] for item in series),
            }
            totals["ctr"] = (
                totals["clicks"] / totals["impressions"] if totals["impressions"] > 0 else 0.0
            )

            return {
                "days": days,
                "filters": {"method": method, "model_version": model_version, "user_id": user_id},
                "totals": totals,
                "series": series,
            }

        filters = ["day >= CURRENT_DATE - (%s || ' days')::interval"]
        params = [days]
        if method:
            filters.append("method = %s")
            params.append(method)
        if model_version:
            filters.append("model_version = %s")
            params.append(model_version)
        where_sql = " AND ".join(filters)

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT day, model_version, method, impressions, clicks, hides, saves,
                       avg_dwell_ms, ctr, save_rate, hide_rate,
                       unique_users, unique_items,
                       coverage_categories, coverage_subcategories,
                       repetition_rate, novelty_proxy
                FROM daily_feed_metrics
                WHERE {where_sql}
                ORDER BY day ASC
                """,
                params,
            )
            rows = cur.fetchall()

        series = [
            {
                "day": row[0].isoformat(),
                "model_version": row[1],
                "method": row[2],
                "impressions": int(row[3]),
                "clicks": int(row[4]),
                "hides": int(row[5]),
                "saves": int(row[6]),
                "avg_dwell_ms": float(row[7]) if row[7] is not None else None,
                "ctr": float(row[8]),
                "save_rate": float(row[9]) if row[9] is not None else None,
                "hide_rate": float(row[10]) if row[10] is not None else None,
                "unique_users": int(row[11]),
                "unique_items": int(row[12]),
                "coverage_categories": int(row[13]) if row[13] is not None else None,
                "coverage_subcategories": int(row[14]) if row[14] is not None else None,
                "repetition_rate": float(row[15]) if row[15] is not None else None,
                "novelty_proxy": float(row[16]) if row[16] is not None else None,
            }
            for row in rows
        ]

        totals = {
            "impressions": sum(item["impressions"] for item in series),
            "clicks": sum(item["clicks"] for item in series),
            "hides": sum(item["hides"] for item in series),
            "saves": sum(item["saves"] for item in series),
            "unique_users": max((item["unique_users"] for item in series), default=0),
            "unique_items": max((item["unique_items"] for item in series), default=0),
        }
        totals["ctr"] = (
            totals["clicks"] / totals["impressions"] if totals["impressions"] > 0 else 0.0
        )

        return {
            "days": days,
            "filters": {"method": method, "model_version": model_version, "user_id": user_id},
            "totals": totals,
            "series": series,
        }
    finally:
        conn.close()


@router.get("/metrics/user")
def metrics_user(
    user_id: str,
    days: int = Query(default=14, ge=1, le=365),
):
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ts::date AS day,
                    COALESCE(model_version, 'unknown') AS model_version,
                    COALESCE(method, 'unknown') AS method,
                    COUNT(*) FILTER (WHERE event_type = 'impression') AS impressions,
                    COUNT(*) FILTER (WHERE event_type = 'click') AS clicks,
                    COUNT(*) FILTER (WHERE event_type = 'hide') AS hides,
                    COUNT(*) FILTER (WHERE event_type = 'save') AS saves,
                    AVG(dwell_ms) FILTER (WHERE event_type = 'dwell') AS avg_dwell_ms
                FROM events
                WHERE user_id = %s
                  AND ts::date >= CURRENT_DATE - (%s || ' days')::interval
                GROUP BY 1, 2, 3
                ORDER BY day ASC
                """,
                (user_id, days),
            )
            rows = cur.fetchall()

        series = [
            {
                "day": row[0].isoformat(),
                "model_version": row[1],
                "method": row[2],
                "impressions": int(row[3]),
                "clicks": int(row[4]),
                "hides": int(row[5]),
                "saves": int(row[6]),
                "avg_dwell_ms": float(row[7]) if row[7] is not None else None,
                "ctr": float(row[4]) / float(row[3]) if row[3] else 0.0,
            }
            for row in rows
        ]

        totals = {
            "impressions": sum(item["impressions"] for item in series),
            "clicks": sum(item["clicks"] for item in series),
            "hides": sum(item["hides"] for item in series),
            "saves": sum(item["saves"] for item in series),
        }
        totals["ctr"] = (
            totals["clicks"] / totals["impressions"] if totals["impressions"] > 0 else 0.0
        )

        return {"user_id": user_id, "days": days, "totals": totals, "series": series}
    finally:
        conn.close()
