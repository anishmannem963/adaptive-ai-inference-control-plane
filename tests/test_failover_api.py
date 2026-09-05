from fastapi.testclient import TestClient

from control_plane.config import Settings
from control_plane.contracts import ChatCompletionRequest, ProviderResult
from control_plane.main import create_app
from control_plane.providers.base import ProviderDescriptor
from control_plane.providers.registry import ProviderRegistry


class FailingProvider:
    descriptor = ProviderDescriptor(
        name="failing",
        models=("failing",),
        simulated=True,
        nominal_latency_ms=10,
        input_cost_per_million_tokens_usd="0.01",
        output_cost_per_million_tokens_usd="0.01",
        quality_score=0.8,
    )

    async def complete(self, request: ChatCompletionRequest) -> ProviderResult:
        raise RuntimeError("injected provider failure")


class HealthyProvider:
    descriptor = ProviderDescriptor(
        name="healthy",
        models=("healthy",),
        simulated=True,
        nominal_latency_ms=20,
        input_cost_per_million_tokens_usd="1",
        output_cost_per_million_tokens_usd="1",
        quality_score=0.8,
    )

    async def complete(self, request: ChatCompletionRequest) -> ProviderResult:
        return ProviderResult(
            text="fallback succeeded",
            prompt_tokens=2,
            completion_tokens=2,
            estimated_cost_usd="0.000004",
        )


def test_auto_request_falls_back_to_next_eligible_provider() -> None:
    registry = ProviderRegistry((FailingProvider(), HealthyProvider()))
    client = TestClient(create_app(Settings(), registry))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "survive failure"}],
            "routing": {"policy": "lowest_cost"},
        },
    )

    assert response.status_code == 200
    routing = response.json()["routing"]
    assert routing["provider"] == "healthy"
    assert routing["attempted_providers"] == ["failing", "healthy"]
    assert routing["fallback_count"] == 1


def test_direct_request_does_not_change_requested_model_on_failure() -> None:
    registry = ProviderRegistry((FailingProvider(), HealthyProvider()))
    client = TestClient(create_app(Settings(), registry))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "failing",
            "messages": [{"role": "user", "content": "do not substitute"}],
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["attempted_providers"] == ["failing"]


def test_health_endpoint_exposes_runtime_failure_counts() -> None:
    registry = ProviderRegistry((FailingProvider(), HealthyProvider()))
    client = TestClient(create_app(Settings(), registry))

    client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "record health"}],
            "routing": {"policy": "lowest_cost"},
        },
    )
    health = client.get("/v1/providers/health").json()

    failing = next(item for item in health if item["provider"] == "failing")
    healthy = next(item for item in health if item["provider"] == "healthy")
    assert failing["total_failures"] == 1
    assert healthy["total_successes"] == 1
