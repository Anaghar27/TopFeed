from fastapi import APIRouter, HTTPException, Query

from app.db import get_psycopg_conn

router = APIRouter()


@router.get("/users/{user_id}/top")
def get_user_top(user_id: str):
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT top_json FROM user_top WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="ToP not found")
        return row[0]
    finally:
        conn.close()


@router.get("/users/{user_id}/top/nodes")
def get_user_top_nodes(user_id: str, limit: int = Query(default=100, ge=1, le=1000)):
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT path, category, subcategory, exposures, clicks,
                       interest_weight, exposure_weight, underexplored_score, updated_at
                FROM user_top_nodes
                WHERE user_id = %s
                ORDER BY underexplored_score DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            rows = cur.fetchall()
        return [
            {
                "path": row[0],
                "category": row[1],
                "subcategory": row[2],
                "exposures": row[3],
                "clicks": row[4],
                "interest_weight": row[5],
                "exposure_weight": row[6],
                "underexplored_score": row[7],
                "updated_at": row[8].isoformat() if row[8] else None,
            }
            for row in rows
        ]
    finally:
        conn.close()
