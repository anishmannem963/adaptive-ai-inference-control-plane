"""HTTP load generation with machine-readable latency, cost, and routing evidence."""

from __future__ import annotations

import asyncio
import math
import time
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class LoadProfile:
    name: str
    policy: str
    preferred_provider: str | None = None


@dataclass(frozen=True, slots=True)
class RequestSample:
    status_code: int
    latency_ms: float
    provider: str | None
    estimated_cost_usd: str
    fallback_count: int


@dataclass(frozen=True, slots=True)
class LoadRun:
    profile: str
    repetition: int
    requests: int
    concurrency: int
    successful_requests: int
    failed_requests: int
    success_rate: float
    duration_seconds: float
    throughput_rps: float
    latency_ms: dict[str, float]
    estimated_cost_usd: str
    provider_distribution: dict[str, int]
    fallback_count: int


DEFAULT_PROFILES = (
    LoadProfile("adaptive", "adaptive"),
    LoadProfile("round_robin", "round_robin"),
    LoadProfile("single_provider", "single_provider", "mock-quality"),
    LoadProfile("lowest_cost", "lowest_cost"),
)


def percentile(values: list[float], quantile: float) -> float:
    """Return a deterministic nearest-rank percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def summarize_samples(
    *,
    profile: LoadProfile,
    repetition: int,
    concurrency: int,
    duration_seconds: float,
    samples: list[RequestSample],
) -> LoadRun:
    successes = [sample for sample in samples if sample.status_code == 200]
    latencies = [sample.latency_ms for sample in successes]
    provider_distribution = Counter(
        sample.provider for sample in successes if sample.provider is not None
    )
    total_cost = sum(
        (Decimal(sample.estimated_cost_usd) for sample in successes),
        start=Decimal(0),
    )
    request_count = len(samples)
    successful_count = len(successes)
    return LoadRun(
        profile=profile.name,
        repetition=repetition,
        requests=request_count,
        concurrency=concurrency,
        successful_requests=successful_count,
        failed_requests=request_count - successful_count,
        success_rate=round(successful_count / request_count, 6) if request_count else 0.0,
        duration_seconds=round(duration_seconds, 6),
        throughput_rps=round(request_count / duration_seconds, 3) if duration_seconds else 0.0,
        latency_ms={
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        estimated_cost_usd=format(total_cost, "f"),
        provider_distribution=dict(sorted(provider_distribution.items())),
        fallback_count=sum(sample.fallback_count for sample in successes),
    )


def aggregate_runs(runs: list[LoadRun]) -> dict[str, dict[str, object]]:
    """Aggregate repeated runs without discarding their individual measurements."""
    grouped: dict[str, list[LoadRun]] = {}
    for run in runs:
        grouped.setdefault(run.profile, []).append(run)

    aggregates: dict[str, dict[str, object]] = {}
    for profile, profile_runs in sorted(grouped.items()):
        requests = sum(run.requests for run in profile_runs)
        successes = sum(run.successful_requests for run in profile_runs)
        total_cost = sum(
            (Decimal(run.estimated_cost_usd) for run in profile_runs),
            start=Decimal(0),
        )
        providers: Counter[str] = Counter()
        for run in profile_runs:
            providers.update(run.provider_distribution)
        aggregates[profile] = {
            "runs": len(profile_runs),
            "requests": requests,
            "successful_requests": successes,
            "failed_requests": requests - successes,
            "success_rate": round(successes / requests, 6),
            "mean_throughput_rps": round(
                sum(run.throughput_rps for run in profile_runs) / len(profile_runs),
                3,
            ),
            "mean_p95_latency_ms": round(
                sum(run.latency_ms["p95"] for run in profile_runs) / len(profile_runs),
                3,
            ),
            "total_estimated_cost_usd": format(total_cost, "f"),
            "estimated_cost_per_successful_request_usd": (
                format(total_cost / successes, "f") if successes else "0"
            ),
            "provider_distribution": dict(sorted(providers.items())),
            "fallback_count": sum(run.fallback_count for run in profile_runs),
        }
    return aggregates


def compare_adaptive(
    aggregates: dict[str, dict[str, object]],
) -> dict[str, dict[str, float]]:
    """Calculate adaptive cost and latency changes against explicit baselines."""
    adaptive = aggregates.get("adaptive")
    if adaptive is None:
        return {}
    adaptive_cost = Decimal(str(adaptive["estimated_cost_per_successful_request_usd"]))
    adaptive_p95 = float(str(adaptive["mean_p95_latency_ms"]))
    comparisons: dict[str, dict[str, float]] = {}
    for baseline_name in ("round_robin", "single_provider", "lowest_cost"):
        baseline = aggregates.get(baseline_name)
        if baseline is None:
            continue
        baseline_cost = Decimal(str(baseline["estimated_cost_per_successful_request_usd"]))
        baseline_p95 = float(str(baseline["mean_p95_latency_ms"]))
        cost_reduction = (
            float((baseline_cost - adaptive_cost) / baseline_cost * 100) if baseline_cost else 0.0
        )
        latency_change = (adaptive_p95 - baseline_p95) / baseline_p95 * 100 if baseline_p95 else 0.0
        comparisons[baseline_name] = {
            "estimated_cost_reduction_percent": round(cost_reduction, 3),
            "mean_p95_latency_change_percent": round(latency_change, 3),
        }
    return comparisons


async def run_load(
    *,
    client: httpx.AsyncClient,
    profile: LoadProfile,
    repetition: int,
    requests: int,
    concurrency: int,
) -> LoadRun:
    """Execute one bounded load run against an OpenAI-compatible gateway."""
    queue: asyncio.Queue[int] = asyncio.Queue()
    for request_number in range(requests):
        queue.put_nowait(request_number)

    samples: list[RequestSample] = []
    sample_lock = asyncio.Lock()

    async def worker() -> None:
        while True:
            try:
                request_number = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            payload: dict[str, Any] = {
                "model": "auto",
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"benchmark {profile.name} repetition {repetition} "
                            f"request {request_number}"
                        ),
                    }
                ],
                "max_tokens": 64,
                "routing": {"policy": profile.policy},
            }
            if profile.preferred_provider is not None:
                payload["routing"]["preferred_provider"] = profile.preferred_provider

            started = time.perf_counter()
            provider: str | None = None
            estimated_cost = "0"
            fallback_count = 0
            try:
                response = await client.post(
                    "/v1/chat/completions",
                    headers={
                        "X-Request-ID": (f"load-{profile.name}-{repetition}-{request_number}")
                    },
                    json=payload,
                )
                if response.status_code == 200:
                    body = response.json()
                    provider = body["routing"]["provider"]
                    estimated_cost = body["routing"]["estimated_cost_usd"]
                    fallback_count = body["routing"]["fallback_count"]
                status_code = response.status_code
            except httpx.HTTPError:
                status_code = 0
            sample = RequestSample(
                status_code=status_code,
                latency_ms=(time.perf_counter() - started) * 1000,
                provider=provider,
                estimated_cost_usd=estimated_cost,
                fallback_count=fallback_count,
            )
            async with sample_lock:
                samples.append(sample)
            queue.task_done()

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(min(concurrency, requests))))
    duration = time.perf_counter() - started
    return summarize_samples(
        profile=profile,
        repetition=repetition,
        concurrency=concurrency,
        duration_seconds=duration,
        samples=samples,
    )


async def run_matrix(
    *,
    base_url: str,
    requests: int,
    concurrency: int,
    repetitions: int,
    profiles: tuple[LoadProfile, ...] = DEFAULT_PROFILES,
    timeout_seconds: float = 10.0,
) -> dict[str, object]:
    """Run each policy repeatedly and return an auditable JSON-compatible report."""
    started_at = int(time.time())
    runs: list[LoadRun] = []
    limits = httpx.Limits(
        max_connections=concurrency,
        max_keepalive_connections=concurrency,
    )
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout_seconds,
        limits=limits,
        trust_env=False,
    ) as client:
        health = await client.get("/health/ready")
        health.raise_for_status()
        for profile in profiles:
            for repetition in range(1, repetitions + 1):
                runs.append(
                    await run_load(
                        client=client,
                        profile=profile,
                        repetition=repetition,
                        requests=requests,
                        concurrency=concurrency,
                    )
                )

    total_requests = sum(run.requests for run in runs)
    total_successes = sum(run.successful_requests for run in runs)
    aggregates = aggregate_runs(runs)
    return {
        "schema_version": 1,
        "kind": "load-benchmark",
        "generated_at_unix": started_at,
        "configuration": {
            "base_url": base_url,
            "requests_per_run": requests,
            "concurrency": concurrency,
            "repetitions": repetitions,
            "profiles": [profile.name for profile in profiles],
            "cache_bypass": "unique prompt per request; run server with CACHE_ENABLED=false",
        },
        "summary": {
            "runs": len(runs),
            "total_requests": total_requests,
            "successful_requests": total_successes,
            "failed_requests": total_requests - total_successes,
            "success_rate": round(total_successes / total_requests, 6),
        },
        "profile_aggregates": aggregates,
        "adaptive_comparisons": compare_adaptive(aggregates),
        "runs": [asdict(run) for run in runs],
    }
