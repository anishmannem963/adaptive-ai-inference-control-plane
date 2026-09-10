from fastapi.testclient import TestClient

from control_plane.config import Settings
from control_plane.main import create_app


def client() -> TestClient:
    return TestClient(create_app(Settings()))


def payload(**routing: object) -> dict[str, object]:
    return {
        "model": "auto",
        "messages": [{"role": "user", "content": "route this showcase request"}],
        "max_tokens": 128,
        "routing": routing,
    }


def test_provider_profiles_expose_routing_signals() -> None:
    response = client().get("/v1/providers")

    assert response.status_code == 200
    profiles = response.json()
    assert {profile["name"] for profile in profiles} == {
        "mock-economy",
        "mock-fast",
        "mock-quality",
    }
    assert all(profile["simulated"] for profile in profiles)
    assert all(0 <= profile["utilization_score"] <= 1 for profile in profiles)
    trusted = next(profile for profile in profiles if profile["name"] == "mock-quality")
    assert trusted["trusted_for_sensitive"] is True


def test_allowlist_and_request_scoped_failure_produce_visible_fallback() -> None:
    response = client().post(
        "/v1/chat/completions",
        json=payload(
            policy="lowest_cost",
            allowed_providers=["mock-economy", "mock-fast"],
            simulated_failure_provider="mock-economy",
        ),
    )

    assert response.status_code == 200
    routing = response.json()["routing"]
    assert routing["provider"] == "mock-fast"
    assert routing["eligible_providers"] == ["mock-fast"]
    assert routing["attempted_providers"] == ["mock-economy", "mock-fast"]
    assert routing["fallback_count"] == 1


def test_sensitive_request_only_uses_trusted_provider() -> None:
    response = client().post(
        "/v1/chat/completions",
        json=payload(policy="lowest_cost", require_trusted=True),
    )

    assert response.status_code == 200
    assert response.json()["routing"]["provider"] == "mock-quality"


def test_utilization_weight_can_drive_adaptive_selection() -> None:
    response = client().post(
        "/v1/chat/completions",
        json=payload(
            policy="adaptive",
            weights={"cost": 0, "latency": 0, "utilization": 1, "quality": 0},
        ),
    )

    assert response.status_code == 200
    assert response.json()["routing"]["provider"] == "mock-quality"


def test_cache_bypass_executes_provider_and_reports_preflight_ceiling() -> None:
    test_client = client()
    request = payload(
        policy="single_provider",
        preferred_provider="mock-fast",
        cache_mode="bypass",
    )

    first = test_client.post("/v1/chat/completions", json=request)
    second = test_client.post("/v1/chat/completions", json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["X-Cache"] == "BYPASS"
    assert second.headers["X-Cache"] == "BYPASS"
    routing = second.json()["routing"]
    assert routing["cache_hit"] is False
    assert float(routing["maximum_estimated_cost_usd"]) >= float(routing["estimated_cost_usd"])


def test_excluding_every_allowed_provider_is_rejected() -> None:
    response = client().post(
        "/v1/chat/completions",
        json=payload(
            allowed_providers=["mock-fast"],
            excluded_providers=["mock-fast"],
        ),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "no provider satisfies all routing constraints"


def test_unknown_simulated_failure_target_is_rejected() -> None:
    response = client().post(
        "/v1/chat/completions",
        json=payload(simulated_failure_provider="not-registered"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "simulated failure provider is not registered"
