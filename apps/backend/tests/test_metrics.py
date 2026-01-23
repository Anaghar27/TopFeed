def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "request_count_total" in body
    assert "feed_requests_total" in body
