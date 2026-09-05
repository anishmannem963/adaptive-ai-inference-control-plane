"""Provider isolation, health tracking, rate limits, and circuit breaking."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from control_plane.contracts import ChatCompletionRequest, ProviderResult
from control_plane.providers.base import InferenceProvider


class ProviderCallError(RuntimeError):
    """Provider invocation failed safely."""


class CircuitOpenError(ProviderCallError):
    """Circuit breaker does not currently permit traffic."""


class ProviderRateLimitedError(ProviderCallError):
    """Local provider admission rate was exceeded."""


class ProviderOverloadedError(ProviderCallError):
    """Provider concurrency bulkhead has no capacity."""


class ProviderTimeoutError(ProviderCallError):
    """Provider exceeded its bounded deadline."""


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False
        self._lock = asyncio.Lock()

    async def allow_request(self) -> None:
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return
            if self._state == CircuitState.OPEN:
                if self._clock() - self._opened_at < self.recovery_timeout_seconds:
                    raise CircuitOpenError("provider circuit is open")
                self._state = CircuitState.HALF_OPEN
            if self._probe_in_flight:
                raise CircuitOpenError("provider recovery probe is already in flight")
            self._probe_in_flight = True

    async def record_success(self) -> None:
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._probe_in_flight = False

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            self._probe_in_flight = False
            if (
                self._state == CircuitState.HALF_OPEN
                or self._failures >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = self._clock()

    async def snapshot(self) -> tuple[CircuitState, int]:
        async with self._lock:
            return self._state, self._failures


class TokenBucket:
    def __init__(
        self,
        rate_per_second: float = 100.0,
        capacity: float = 100.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate = rate_per_second
        self._capacity = capacity
        self._tokens = capacity
        self._clock = clock
        self._updated_at = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            elapsed = max(0.0, now - self._updated_at)
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._updated_at = now
            if self._tokens < 1:
                raise ProviderRateLimitedError("provider admission rate exceeded")
            self._tokens -= 1


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    provider: str
    circuit: str
    consecutive_failures: int
    total_requests: int
    total_successes: int
    total_failures: int
    average_latency_ms: float
    available: bool


class ProviderRuntime:
    def __init__(
        self,
        provider: InferenceProvider,
        *,
        timeout_seconds: float = 5.0,
        max_concurrency: int = 32,
        rate_per_second: float = 100.0,
        burst_capacity: float = 100.0,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 10.0,
    ) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout_seconds=recovery_timeout_seconds,
        )
        self.rate_limiter = TokenBucket(rate_per_second, burst_capacity)
        self.bulkhead = asyncio.Semaphore(max_concurrency)
        self.total_requests = 0
        self.total_successes = 0
        self.total_failures = 0
        self.total_latency_ms = 0.0
        self._metrics_lock = asyncio.Lock()

    async def invoke(self, request: ChatCompletionRequest) -> ProviderResult:
        await self.breaker.allow_request()
        await self.rate_limiter.acquire()
        if self.bulkhead.locked():
            raise ProviderOverloadedError("provider concurrency capacity exhausted")

        started = time.perf_counter()
        async with self._metrics_lock:
            self.total_requests += 1
        try:
            async with self.bulkhead:
                async with asyncio.timeout(self.timeout_seconds):
                    result = await self.provider.complete(request)
        except TimeoutError as exc:
            await self._record_failure(started)
            await self.breaker.record_failure()
            raise ProviderTimeoutError("provider deadline exceeded") from exc
        except ProviderCallError:
            await self._record_failure(started)
            await self.breaker.record_failure()
            raise
        except Exception as exc:
            await self._record_failure(started)
            await self.breaker.record_failure()
            raise ProviderCallError("provider invocation failed") from exc

        await self._record_success(started)
        await self.breaker.record_success()
        return result

    async def _record_success(self, started: float) -> None:
        latency = (time.perf_counter() - started) * 1000
        async with self._metrics_lock:
            self.total_successes += 1
            self.total_latency_ms += latency

    async def _record_failure(self, started: float) -> None:
        latency = (time.perf_counter() - started) * 1000
        async with self._metrics_lock:
            self.total_failures += 1
            self.total_latency_ms += latency

    async def snapshot(self) -> HealthSnapshot:
        state, failures = await self.breaker.snapshot()
        async with self._metrics_lock:
            average = (
                self.total_latency_ms / self.total_requests
                if self.total_requests
                else 0.0
            )
            return HealthSnapshot(
                provider=self.provider.descriptor.name,
                circuit=state.value,
                consecutive_failures=failures,
                total_requests=self.total_requests,
                total_successes=self.total_successes,
                total_failures=self.total_failures,
                average_latency_ms=round(average, 3),
                available=state != CircuitState.OPEN,
            )


class ReliabilityManager:
    def __init__(self, providers: tuple[InferenceProvider, ...]) -> None:
        self._runtimes = {
            provider.descriptor.name: ProviderRuntime(provider)
            for provider in providers
        }

    async def invoke(
        self,
        provider: InferenceProvider,
        request: ChatCompletionRequest,
    ) -> ProviderResult:
        return await self._runtimes[provider.descriptor.name].invoke(request)

    async def health(self) -> list[HealthSnapshot]:
        return [
            await runtime.snapshot()
            for runtime in self._runtimes.values()
        ]
