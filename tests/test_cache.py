import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from control_plane.cache import MemoryKeyValue, RedisKeyValue
from control_plane.config import ConfigurationError, Settings
from control_plane.contracts import ChatCompletionRequest, ProviderResult
from control_plane.main import create_app
from control_plane.providers.base import ProviderDescriptor
from control_plane.providers.registry import ProviderRegistry


class CountingProvider:
    descriptor = ProviderDescriptor(
        name="counting",
        models=("counting",),
        simulated=True,
        nominal_latency_ms=10,
        input_cost_per_million_tokens_usd="0.01",
        output_cost_per_million_tokens_usd="0.01",
        quality_score=0.8,
    )

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: ChatCompletionRequest) -> ProviderResult:
        self.calls += 1
        return ProviderResult(
            text=f"call-{self.calls}",
            prompt_tokens=2,
            completion_tokens=1,
            estimated_cost_usd="0.000001",
        )


class FailingKeyValue:
    async def get(self, key: str) -> str | None:
        raise ConnectionError("injected cache outage")

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        raise ConnectionError("injected cache outage")


def payload(content: str = "cache this") -> dict[str, object]:
    return {
        "model": "counting",
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 32,
    }


def test_repeated_request_uses_provider_aware_cache() -> None:
    provider = CountingProvider()
    registry = ProviderRegistry((provider,))
    client = TestClient(create_app(Settings(), registry, cache_backend=MemoryKeyValue()))

    first = client.post("/v1/chat/completions", json=payload())
    second = client.post("/v1/chat/completions", json=payload())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json()["routing"]["cache_hit"] is False
    assert second.json()["routing"]["cache_hit"] is True
    assert provider.calls == 1

    status = client.get("/v1/cache/status").json()
    assert status["backend"] == "injected"
    assert status["hits"] == 1
    assert status["misses"] == 1
    assert status["writes"] == 1


def test_idempotency_replays_response_and_rejects_conflicts() -> None:
    provider = CountingProvider()
    registry = ProviderRegistry((provider,))
    client = TestClient(create_app(Settings(), registry, cache_backend=MemoryKeyValue()))
    headers = {
        "X-Client-ID": "test-client",
        "X-Idempotency-Key": "operation-42",
    }

    first = client.post("/v1/chat/completions", headers=headers, json=payload())
    replay = client.post("/v1/chat/completions", headers=headers, json=payload())
    conflict = client.post(
        "/v1/chat/completions",
        headers=headers,
        json=payload("different payload"),
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert replay.headers["X-Cache"] == "REPLAY"
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert provider.calls == 1

    status = client.get("/v1/cache/status").json()
    assert status["idempotent_replays"] == 1
    assert status["idempotency_conflicts"] == 1


def test_idempotency_headers_must_be_supplied_together() -> None:
    client = TestClient(create_app(Settings()))

    response = client.post(
        "/v1/chat/completions",
        headers={"X-Client-ID": "test-client"},
        json={
            "model": "mock-fast",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 400


def test_cache_failure_does_not_stop_inference() -> None:
    provider = CountingProvider()
    registry = ProviderRegistry((provider,))
    client = TestClient(create_app(Settings(), registry, cache_backend=FailingKeyValue()))

    response = client.post("/v1/chat/completions", json=payload())

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert provider.calls == 1
    assert client.get("/v1/cache/status").json()["backend_errors"] == 2


def test_cache_can_be_disabled_without_disabling_inference() -> None:
    provider = CountingProvider()
    registry = ProviderRegistry((provider,))
    settings = Settings(cache_enabled=False)
    client = TestClient(create_app(settings, registry, cache_backend=MemoryKeyValue()))

    first = client.post("/v1/chat/completions", json=payload())
    second = client.post("/v1/chat/completions", json=payload())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["X-Cache"] == "BYPASS"
    assert second.headers["X-Cache"] == "BYPASS"
    assert provider.calls == 2
    assert client.get("/v1/cache/status").json()["enabled"] is False


def test_cache_ttls_must_be_positive() -> None:
    with pytest.raises(ConfigurationError, match="CACHE_TTL_SECONDS"):
        Settings.from_env({"CACHE_TTL_SECONDS": "0"})
    with pytest.raises(ConfigurationError, match="IDEMPOTENCY_TTL_SECONDS"):
        Settings.from_env({"IDEMPOTENCY_TTL_SECONDS": "not-an-integer"})


def test_redis_backend_round_trip() -> None:
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("TEST_REDIS_URL is not configured")

    async def round_trip() -> None:
        backend = RedisKeyValue(redis_url)
        key = f"ci-cache-test:{uuid.uuid4()}"
        await backend.set(key, "available", 30)
        assert await backend.get(key) == "available"

    asyncio.run(round_trip())
