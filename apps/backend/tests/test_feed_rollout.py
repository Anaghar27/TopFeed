from app.services.rollout import RolloutConfig, assign_variant


def test_feed_response_includes_rollout_fields(client):
    response = client.post(
        "/feed",
        json={
            "user_id": "test-user-1",
            "top_n": 5,
            "history_k": 5,
            "diversify": True,
            "explore_level": 0.5,
            "include_explanations": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "variant" in payload
    assert "model_version" in payload


def test_canary_bucketing_is_deterministic():
    config = RolloutConfig(
        canary_enabled=True,
        canary_percent=50,
        control_model_version="reranker_baseline:v1",
        canary_model_version="reranker_baseline:v2",
        canary_auto_disable=False,
    )
    first = assign_variant(user_id="stable-user", request_id="req-1", config=config)
    second = assign_variant(user_id="stable-user", request_id="req-2", config=config)
    assert first == second
