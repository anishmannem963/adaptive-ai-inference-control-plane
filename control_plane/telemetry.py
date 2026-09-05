"""Prometheus metrics, OpenTelemetry traces, and bounded runtime summaries."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from threading import Lock

from fastapi import Request
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


@dataclass(frozen=True, slots=True)
class InferenceEvent:
    timestamp: int
    request_id: str
    trace_id: str
    provider: str
    policy: str
    cache_status: str
    latency_ms: float
    fallback_count: int


@dataclass(slots=True)
class ProviderAggregate:
    calls: int = 0
    successes: int = 0
    failures: int = 0
    cumulative_latency_ms: float = 0.0

    def snapshot(self) -> dict[str, int | float]:
        average = self.cumulative_latency_ms / self.calls if self.calls else 0.0
        return {
            "calls": self.calls,
            "successes": self.successes,
            "failures": self.failures,
            "average_latency_ms": round(average, 3),
        }


class Telemetry:
    """Owns an isolated metrics registry, tracer provider, and bounded event buffer."""

    def __init__(
        self,
        service_name: str,
        otlp_endpoint: str = "",
        recent_event_limit: int = 100,
    ) -> None:
        self.registry = CollectorRegistry()
        self.http_requests = Counter(
            "control_plane_http_requests_total",
            "HTTP requests handled by the control plane.",
            ("method", "path", "status"),
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "control_plane_http_request_duration_seconds",
            "HTTP request duration in seconds.",
            ("method", "path"),
            registry=self.registry,
        )
        self.http_in_flight = Gauge(
            "control_plane_http_requests_in_flight",
            "HTTP requests currently executing.",
            registry=self.registry,
        )
        self.inference_requests = Counter(
            "control_plane_inference_requests_total",
            "Completed inference requests.",
            ("provider", "policy", "cache_status"),
            registry=self.registry,
        )
        self.inference_duration = Histogram(
            "control_plane_inference_duration_seconds",
            "End-to-end inference request duration in seconds.",
            ("provider", "cache_status"),
            registry=self.registry,
        )
        self.provider_calls = Counter(
            "control_plane_provider_calls_total",
            "Inference provider calls by outcome.",
            ("provider", "outcome"),
            registry=self.registry,
        )
        self.provider_duration = Histogram(
            "control_plane_provider_call_duration_seconds",
            "Inference provider call duration in seconds.",
            ("provider",),
            registry=self.registry,
        )
        self.fallbacks = Counter(
            "control_plane_fallbacks_total",
            "Fallback transitions completed by auto-routed requests.",
            registry=self.registry,
        )
        self.estimated_provider_cost = Counter(
            "control_plane_estimated_provider_cost_usd_total",
            "Estimated cost of provider calls in US dollars.",
            ("provider",),
            registry=self.registry,
        )

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        if otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        self._tracer_provider = provider
        self.tracer = provider.get_tracer("control_plane.telemetry")

        self._events: deque[InferenceEvent] = deque(maxlen=recent_event_limit)
        self._providers: dict[str, ProviderAggregate] = {}
        self._completed_requests = 0
        self._cache_hits = 0
        self._cache_replays = 0
        self._fallback_count = 0
        self._cumulative_latency_ms = 0.0
        self._lock = Lock()

    @contextmanager
    def provider_span(self, provider: str) -> Iterator[Span]:
        with self.tracer.start_as_current_span(
            "inference.provider",
            attributes={"inference.provider": provider},
        ) as span:
            yield span

    @staticmethod
    def trace_id(span: Span) -> str:
        return f"{span.get_span_context().trace_id:032x}"

    def current_trace_id(self) -> str:
        return self.trace_id(trace.get_current_span())

    def annotate_inference(
        self,
        *,
        request_id: str,
        model: str,
        policy: str,
        provider: str | None = None,
        cache_status: str | None = None,
        fallback_count: int | None = None,
    ) -> None:
        span = trace.get_current_span()
        span.set_attribute("inference.request_id", request_id)
        span.set_attribute("inference.model", model)
        span.set_attribute("inference.routing_policy", policy)
        if provider is not None:
            span.set_attribute("inference.provider", provider)
        if cache_status is not None:
            span.set_attribute("inference.cache_status", cache_status)
        if fallback_count is not None:
            span.set_attribute("inference.fallback_count", fallback_count)

    def observe_http(self, method: str, path: str, status: int, duration_seconds: float) -> None:
        self.http_requests.labels(method=method, path=path, status=str(status)).inc()
        self.http_duration.labels(method=method, path=path).observe(duration_seconds)

    def record_provider_call(
        self,
        provider: str,
        outcome: str,
        latency_ms: float,
        estimated_cost_usd: str = "0",
    ) -> None:
        self.provider_calls.labels(provider=provider, outcome=outcome).inc()
        self.provider_duration.labels(provider=provider).observe(latency_ms / 1000)
        if outcome == "success":
            self.estimated_provider_cost.labels(provider=provider).inc(float(estimated_cost_usd))
        with self._lock:
            aggregate = self._providers.setdefault(provider, ProviderAggregate())
            aggregate.calls += 1
            aggregate.cumulative_latency_ms += latency_ms
            if outcome == "success":
                aggregate.successes += 1
            else:
                aggregate.failures += 1

    def record_inference(
        self,
        *,
        request_id: str,
        trace_id: str,
        provider: str,
        policy: str,
        cache_status: str,
        latency_ms: float,
        fallback_count: int,
    ) -> None:
        self.inference_requests.labels(
            provider=provider,
            policy=policy,
            cache_status=cache_status,
        ).inc()
        self.inference_duration.labels(
            provider=provider,
            cache_status=cache_status,
        ).observe(latency_ms / 1000)
        if fallback_count:
            self.fallbacks.inc(fallback_count)

        event = InferenceEvent(
            timestamp=int(time.time()),
            request_id=request_id,
            trace_id=trace_id,
            provider=provider,
            policy=policy,
            cache_status=cache_status,
            latency_ms=round(latency_ms, 3),
            fallback_count=fallback_count,
        )
        with self._lock:
            self._completed_requests += 1
            self._cumulative_latency_ms += latency_ms
            self._fallback_count += fallback_count
            if cache_status == "HIT":
                self._cache_hits += 1
            elif cache_status == "REPLAY":
                self._cache_replays += 1
            self._events.appendleft(event)

    def prometheus_payload(self) -> bytes:
        return generate_latest(self.registry)

    def summary(self) -> dict[str, object]:
        with self._lock:
            average = (
                self._cumulative_latency_ms / self._completed_requests
                if self._completed_requests
                else 0.0
            )
            return {
                "completed_requests": self._completed_requests,
                "cache_hits": self._cache_hits,
                "cache_replays": self._cache_replays,
                "fallback_count": self._fallback_count,
                "average_latency_ms": round(average, 3),
                "providers": {
                    provider: aggregate.snapshot()
                    for provider, aggregate in sorted(self._providers.items())
                },
                "recent_events": [asdict(event) for event in self._events],
            }


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, telemetry: Telemetry) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._telemetry = telemetry

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        started = time.perf_counter()
        status = 500
        with self._telemetry.tracer.start_as_current_span(
            "http.request",
            attributes={
                "http.request.method": request.method,
                "url.path": request.url.path,
            },
        ) as span:
            self._telemetry.http_in_flight.inc()
            try:
                response = await call_next(request)
                status = response.status_code
            finally:
                self._telemetry.http_in_flight.dec()
                self._telemetry.observe_http(
                    request.method,
                    request.url.path,
                    status,
                    time.perf_counter() - started,
                )
            span.set_attribute("http.response.status_code", status)
            response.headers["X-Trace-ID"] = self._telemetry.trace_id(span)
            return response


PROMETHEUS_CONTENT_TYPE = CONTENT_TYPE_LATEST
