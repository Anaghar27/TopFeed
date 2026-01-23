import uuid

from app.db import get_psycopg_conn


def test_events_ingest(client):
    request_id = uuid.uuid4().hex
    payload = [
        {
            "user_id": "test-user-1",
            "event_type": "impression",
            "news_id": "news-123",
            "request_id": request_id,
            "model_version": "reranker_baseline:v1",
            "method": "popular_fallback",
            "position": 1,
            "explore_level": 0.2,
            "diversify": False,
            "metadata": {"novelty_proxy": 0.1},
        }
    ]

    response = client.post("/events", json=payload)
    assert response.status_code == 200
    assert response.json()["inserted_count"] == 1

    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM events WHERE request_id = %s", (request_id,))
            count = cur.fetchone()[0]
            assert count >= 1
            cur.execute("DELETE FROM events WHERE request_id = %s", (request_id,))
        conn.commit()
    finally:
        conn.close()
