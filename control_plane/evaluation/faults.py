"""Repeatable provider-fault matrix for fallback and circuit-breaker evidence."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from typing import Literal

import httpx

from control_plane.config import Settings
from control_plane.contracts import ChatCompletionRequest, ProviderResult
from control_plane.main import create_app
from control_plane.providers.base import ProviderDescriptor
from control_plane.providers.registry import ProviderRegistry
from control_plane.reliability import ReliabilityManager

ProviderMode = Literal["healthy", "error", "timeout"]


class ControlledProvider:
    """In-memory provider whose failure mode is controlled by the test harness."""

    def __init__(
        self,
        name: str,
        *,
        cost_per_million: str,
        nominal_latency_ms: int,
        mode: ProviderMode = "healthy",
    ) -> None:
        self.descriptor = ProviderDescriptor(
            name=name,
            models=(name,),
            simulated=True,
            nominal_latency_ms=nominal_latency_ms,
            input_cost_per_million_tokens_usd=cost_per_million,
            output_cost_per_million_tokens_usd=cost_per_million,
            quality_score=0.8,
        )
        self.mode = mode
        self.calls = 0

    async def complete(self, request: ChatCompletionRequest) -> ProviderResult:
        self.calls += 1
        if self.mode == "error":
            raise RuntimeError("controlled provider error")
        if self.mode == "timeout":
            await asyncio.sleep(0.05)
        return ProviderResult(
            text=f"[{self.descriptor.name}] recovered response",
            prompt_tokens=4,
            completion_tokens=4,
            estimated_cost_usd="0.000008",
        )


@dataclass(frozen=True, slots=True)
class FaultScenarioResult:
    scenario: str
    repetition: int
    passed: bool
    latency_ms: float
    status_code: int
    observed_provider: str | None
    fallback_count: int | None
    detail: str


def _payload(
    content: str,
    *,
    model: str = "auto",
    policy: str = "lowest_cost",
) -> dict[str, object]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "routing": {"policy": policy},
    }


async def _post(
    client: httpx.AsyncClient,
    payload: dict[str, object],
) -> tuple[httpx.Response, float]:
    started = time.perf_counter()
    response = await client.post("/v1/chat/completions", json=payload)
    return response, (time.perf_counter() - started) * 1000


def _result(
    *,
    scenario: str,
    repetition: int,
    response: httpx.Response,
    latency_ms: float,
    passed: bool,
    detail: str,
) -> FaultScenarioResult:
    body = response.json()
    routing = body.get("routing", {})
    return FaultScenarioResult(
        scenario=scenario,
        repetition=repetition,
        passed=passed,
        latency_ms=round(latency_ms, 3),
        status_code=response.status_code,
        observed_provider=routing.get("provider"),
        fallback_count=routing.get("fallback_count"),
        detail=detail,
    )


def _client(
    providers: tuple[ControlledProvider, ...],
    *,
    failure_threshold: int = 1,
    recovery_timeout_seconds: float = 0.005,
) -> httpx.AsyncClient:
    registry = ProviderRegistry(providers)
    reliability = ReliabilityManager(
        providers,
        timeout_seconds=0.005,
        failure_threshold=failure_threshold,
        recovery_timeout_seconds=recovery_timeout_seconds,
    )
    app = create_app(
        Settings(cache_enabled=False),
        registry=registry,
        reliability=reliability,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://fault-matrix",
    )


async def provider_error_failover(repetition: int) -> FaultScenarioResult:
    primary = ControlledProvider(
        "primary", cost_per_million="0.1", nominal_latency_ms=10, mode="error"
    )
    secondary = ControlledProvider("secondary", cost_per_million="1", nominal_latency_ms=20)
    async with _client((primary, secondary)) as client:
        response, latency = await _post(client, _payload(f"error failover {repetition}"))
    routing = response.json().get("routing", {})
    passed = (
        response.status_code == 200
        and routing.get("provider") == "secondary"
        and routing.get("fallback_count") == 1
    )
    return _result(
        scenario="provider_error_failover",
        repetition=repetition,
        response=response,
        latency_ms=latency,
        passed=passed,
        detail="primary exception is isolated and the request completes on secondary",
    )


async def provider_timeout_failover(repetition: int) -> FaultScenarioResult:
    primary = ControlledProvider(
        "primary", cost_per_million="0.1", nominal_latency_ms=10, mode="timeout"
    )
    secondary = ControlledProvider("secondary", cost_per_million="1", nominal_latency_ms=20)
    async with _client((primary, secondary)) as client:
        response, latency = await _post(client, _payload(f"timeout failover {repetition}"))
    routing = response.json().get("routing", {})
    passed = (
        response.status_code == 200
        and routing.get("provider") == "secondary"
        and routing.get("fallback_count") == 1
    )
    return _result(
        scenario="provider_timeout_failover",
        repetition=repetition,
        response=response,
        latency_ms=latency,
        passed=passed,
        detail="bounded provider deadline triggers fallback",
    )


async def open_circuit_isolation(repetition: int) -> FaultScenarioResult:
    primary = ControlledProvider(
        "primary", cost_per_million="0.1", nominal_latency_ms=10, mode="error"
    )
    secondary = ControlledProvider("secondary", cost_per_million="1", nominal_latency_ms=20)
    async with _client((primary, secondary), recovery_timeout_seconds=10) as client:
        first, _ = await _post(client, _payload(f"open circuit first {repetition}"))
        response, latency = await _post(client, _payload(f"open circuit second {repetition}"))
        health = (await client.get("/v1/providers/health")).json()
    primary_health = next(item for item in health if item["provider"] == "primary")
    routing = response.json().get("routing", {})
    passed = (
        first.status_code == 200
        and response.status_code == 200
        and primary.calls == 1
        and primary_health["circuit"] == "open"
        and routing.get("provider") == "secondary"
    )
    return _result(
        scenario="open_circuit_isolation",
        repetition=repetition,
        response=response,
        latency_ms=latency,
        passed=passed,
        detail="open circuit rejects a second call without invoking the failed provider",
    )


async def half_open_recovery(repetition: int) -> FaultScenarioResult:
    primary = ControlledProvider(
        "primary", cost_per_million="0.1", nominal_latency_ms=10, mode="error"
    )
    secondary = ControlledProvider("secondary", cost_per_million="1", nominal_latency_ms=20)
    async with _client((primary, secondary)) as client:
        first, _ = await _post(client, _payload(f"recovery failure {repetition}"))
        primary.mode = "healthy"
        await asyncio.sleep(0.007)
        response, latency = await _post(
            client,
            _payload(f"recovery probe {repetition}", model="primary", policy="adaptive"),
        )
        health = (await client.get("/v1/providers/health")).json()
    primary_health = next(item for item in health if item["provider"] == "primary")
    routing = response.json().get("routing", {})
    passed = (
        first.status_code == 200
        and response.status_code == 200
        and routing.get("provider") == "primary"
        and primary_health["circuit"] == "closed"
        and primary_health["total_successes"] == 1
    )
    return _result(
        scenario="half_open_recovery",
        repetition=repetition,
        response=response,
        latency_ms=latency,
        passed=passed,
        detail="a successful half-open probe restores the provider",
    )


async def explicit_model_no_substitution(repetition: int) -> FaultScenarioResult:
    primary = ControlledProvider(
        "primary", cost_per_million="0.1", nominal_latency_ms=10, mode="error"
    )
    secondary = ControlledProvider("secondary", cost_per_million="1", nominal_latency_ms=20)
    async with _client((primary, secondary)) as client:
        response, latency = await _post(
            client,
            _payload(f"explicit failure {repetition}", model="primary", policy="adaptive"),
        )
    detail = response.json().get("detail", {})
    passed = (
        response.status_code == 503
        and detail.get("attempted_providers") == ["primary"]
        and secondary.calls == 0
    )
    return _result(
        scenario="explicit_model_no_substitution",
        repetition=repetition,
        response=response,
        latency_ms=latency,
        passed=passed,
        detail="an explicit model failure returns 503 without changing models",
    )


async def total_provider_outage(repetition: int) -> FaultScenarioResult:
    first = ControlledProvider("first", cost_per_million="0.1", nominal_latency_ms=10, mode="error")
    second = ControlledProvider(
        "second", cost_per_million="0.2", nominal_latency_ms=20, mode="error"
    )
    third = ControlledProvider("third", cost_per_million="0.3", nominal_latency_ms=30, mode="error")
    async with _client((first, second, third)) as client:
        response, latency = await _post(client, _payload(f"total outage {repetition}"))
    detail = response.json().get("detail", {})
    passed = (
        response.status_code == 503
        and detail.get("attempted_providers") == ["first", "second", "third"]
        and first.calls == second.calls == third.calls == 1
    )
    return _result(
        scenario="total_provider_outage",
        repetition=repetition,
        response=response,
        latency_ms=latency,
        passed=passed,
        detail="exhausting every eligible provider returns an auditable 503",
    )


SCENARIOS = (
    provider_error_failover,
    provider_timeout_failover,
    open_circuit_isolation,
    half_open_recovery,
    explicit_model_no_substitution,
    total_provider_outage,
)


async def run_fault_matrix(repetitions: int = 10) -> dict[str, object]:
    """Run all controlled fault categories repeatedly."""
    started_at = int(time.time())
    results: list[FaultScenarioResult] = []
    for repetition in range(1, repetitions + 1):
        for scenario in SCENARIOS:
            results.append(await scenario(repetition))
    passed = sum(result.passed for result in results)
    latencies = [result.latency_ms for result in results]
    return {
        "schema_version": 1,
        "kind": "provider-fault-matrix",
        "generated_at_unix": started_at,
        "configuration": {
            "repetitions": repetitions,
            "scenario_categories": [scenario.__name__ for scenario in SCENARIOS],
            "fault_scope": "controlled in-process provider errors, deadlines, and recovery",
        },
        "summary": {
            "scenarios": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "pass_rate": round(passed / len(results), 6),
            "mean_scenario_latency_ms": round(sum(latencies) / len(latencies), 3),
            "max_scenario_latency_ms": round(max(latencies), 3),
        },
        "results": [asdict(result) for result in results],
    }
