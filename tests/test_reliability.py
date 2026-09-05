import asyncio

import pytest

from control_plane.contracts import ChatCompletionRequest, ChatMessage, ProviderResult
from control_plane.providers.base import ProviderDescriptor
from control_plane.reliability import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    ProviderRateLimitedError,
    ProviderRuntime,
    ProviderTimeoutError,
    TokenBucket,
)


class SlowProvider:
    descriptor = ProviderDescriptor(
        name="slow",
        models=("slow",),
        simulated=True,
        nominal_latency_ms=1000,
        input_cost_per_million_tokens_usd="1",
        output_cost_per_million_tokens_usd="1",
        quality_score=0.8,
    )

    async def complete(self, request: ChatCompletionRequest) -> ProviderResult:
        await asyncio.sleep(0.1)
        return ProviderResult(
            text="late",
            prompt_tokens=1,
            completion_tokens=1,
            estimated_cost_usd="0",
        )


def inference_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="slow",
        messages=[ChatMessage(role="user", content="hello")],
    )


def test_circuit_opens_and_allows_one_recovery_probe() -> None:
    now = [0.0]
    breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=10,
        clock=lambda: now[0],
    )

    asyncio.run(breaker.allow_request())
    asyncio.run(breaker.record_failure())
    asyncio.run(breaker.allow_request())
    asyncio.run(breaker.record_failure())

    state, failures = asyncio.run(breaker.snapshot())
    assert state == CircuitState.OPEN
    assert failures == 2
    with pytest.raises(CircuitOpenError):
        asyncio.run(breaker.allow_request())

    now[0] = 11
    asyncio.run(breaker.allow_request())
    with pytest.raises(CircuitOpenError, match="probe"):
        asyncio.run(breaker.allow_request())

    asyncio.run(breaker.record_success())
    assert asyncio.run(breaker.snapshot()) == (CircuitState.CLOSED, 0)


def test_token_bucket_rejects_excess_admission() -> None:
    now = [0.0]
    limiter = TokenBucket(rate_per_second=1, capacity=1, clock=lambda: now[0])

    asyncio.run(limiter.acquire())
    with pytest.raises(ProviderRateLimitedError):
        asyncio.run(limiter.acquire())

    now[0] = 1
    asyncio.run(limiter.acquire())


def test_provider_deadline_is_bounded_and_recorded() -> None:
    runtime = ProviderRuntime(
        SlowProvider(),
        timeout_seconds=0.001,
        failure_threshold=1,
    )

    with pytest.raises(ProviderTimeoutError):
        asyncio.run(runtime.invoke(inference_request()))

    snapshot = asyncio.run(runtime.snapshot())
    assert snapshot.total_requests == 1
    assert snapshot.total_failures == 1
    assert snapshot.total_successes == 0
    assert snapshot.circuit == "open"
    assert snapshot.available is False
