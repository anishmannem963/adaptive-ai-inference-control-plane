from fastapi.testclient import TestClient

from control_plane.config import Settings
from control_plane.main import create_app


def test_auto_route_returns_explainable_decision() -> None:
    client = TestClient(create_app(Settings()))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "Choose a provider."}],
            "max_tokens": 100,
            "routing": {"policy": "lowest_latency"},
        },
    )

    assert response.status_code == 200
    routing = response.json()["routing"]
    assert routing["provider"] == "mock-fast"
    assert routing["policy"] == "lowest_latency"
    assert routing["decision_reason"] == "selected minimum nominal latency"
    assert routing["eligible_providers"] == [
        "mock-economy",
        "mock-fast",
        "mock-quality",
    ]


def test_impossible_constraints_return_422() -> None:
    client = TestClient(create_app(Settings()))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "Impossible request"}],
            "routing": {
                "max_latency_ms": 1,
                "min_quality": 1,
                "max_estimated_cost_usd": "0",
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "no provider satisfies all routing constraints"
