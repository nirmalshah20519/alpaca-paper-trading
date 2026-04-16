"""Health endpoint tests."""


def test_health_endpoint_returns_status(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert set(payload["services"]) == {"api", "database", "redis", "broker"}
