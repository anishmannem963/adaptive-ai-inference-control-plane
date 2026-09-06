"""FastAPI service entrypoint."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from control_plane import __version__
from control_plane.cache import (
    AsyncKeyValue,
    CacheStatistics,
    ExactResponseCache,
    IdempotencyConflictError,
    IdempotencyStore,
    MemoryKeyValue,
    RedisKeyValue,
)
from control_plane.config import Settings
from control_plane.contracts import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ProviderResult,
    ResponseMessage,
    RoutingMetadata,
    TokenUsage,
)
from control_plane.providers.factory import build_providers
from control_plane.providers.registry import ProviderRegistry, UnknownModelError
from control_plane.reliability import ProviderCallError, ReliabilityManager
from control_plane.routing import NoEligibleProviderError, RouteDecision, RoutingEngine
from control_plane.telemetry import PROMETHEUS_CONTENT_TYPE, HTTPMetricsMiddleware, Telemetry


class Health(BaseModel):
    status: str
    version: str


class Status(BaseModel):
    environment: str
    mock_providers_enabled: bool
    ollama_enabled: bool
    aws_bedrock_enabled: bool
    aws_session_budget_usd: str
    registered_providers: int


class ModelInfo(BaseModel):
    id: str
    provider: str
    simulated: bool


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


class ProviderHealth(BaseModel):
    provider: str
    circuit: str
    consecutive_failures: int
    total_requests: int
    total_successes: int
    total_failures: int
    average_latency_ms: float
    available: bool


class CacheStatus(BaseModel):
    enabled: bool
    backend: str
    ttl_seconds: int
    idempotency_ttl_seconds: int
    hits: int
    misses: int
    writes: int
    backend_errors: int
    idempotent_replays: int
    idempotency_conflicts: int


def create_app(
    settings: Settings | None = None,
    registry: ProviderRegistry | None = None,
    reliability: ReliabilityManager | None = None,
    cache_backend: AsyncKeyValue | None = None,
) -> FastAPI:
    config = settings or Settings.from_env()
    providers = registry or ProviderRegistry(build_providers(config))
    router = RoutingEngine(providers)
    runtime = reliability or ReliabilityManager(
        providers.list(),
        rate_per_second=config.provider_rate_per_second,
        burst_capacity=config.provider_burst_capacity,
    )

    selected_backend: AsyncKeyValue
    if cache_backend is not None:
        selected_backend = cache_backend
        cache_backend_name = "injected"
    elif config.redis_url:
        selected_backend = RedisKeyValue(config.redis_url)
        cache_backend_name = "redis"
    else:
        selected_backend = MemoryKeyValue()
        cache_backend_name = "memory"

    cache_statistics = CacheStatistics()
    response_cache = ExactResponseCache(
        selected_backend,
        config.cache_ttl_seconds,
        cache_statistics,
    )
    idempotency_store = IdempotencyStore(
        selected_backend,
        config.idempotency_ttl_seconds,
        cache_statistics,
    )
    telemetry = Telemetry(
        service_name=config.telemetry_service_name,
        otlp_endpoint=config.otel_exporter_otlp_endpoint,
        recent_event_limit=config.telemetry_recent_events_limit,
    )
    app = FastAPI(title="Adaptive AI Inference Control Plane", version=__version__)
    app.add_middleware(HTTPMetricsMiddleware, telemetry=telemetry)
    if config.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_allowed_origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=[
                "Content-Type",
                "X-Client-ID",
                "X-Idempotency-Key",
                "X-Request-ID",
            ],
            expose_headers=["X-Cache", "X-Idempotent-Replay", "X-Request-ID", "X-Trace-ID"],
        )

    @app.get("/health/live", response_model=Health, tags=["health"])
    async def live() -> Health:
        return Health(status="alive", version=__version__)

    @app.get("/health/ready", response_model=Health, tags=["health"])
    async def ready() -> Health:
        return Health(status="ready", version=__version__)

    @app.get("/v1/system/status", response_model=Status, tags=["system"])
    async def status() -> Status:
        return Status(
            environment=config.environment,
            mock_providers_enabled=config.mock_providers_enabled,
            ollama_enabled=config.ollama_enabled,
            aws_bedrock_enabled=config.aws_bedrock_enabled,
            aws_session_budget_usd=str(config.aws_session_budget_usd),
            registered_providers=len(providers.list()),
        )

    @app.get("/v1/providers/health", response_model=list[ProviderHealth], tags=["system"])
    async def provider_health() -> list[ProviderHealth]:
        return [ProviderHealth(**asdict(snapshot)) for snapshot in await runtime.health()]

    @app.get("/v1/cache/status", response_model=CacheStatus, tags=["system"])
    async def cache_status() -> CacheStatus:
        return CacheStatus(
            enabled=config.cache_enabled,
            backend=cache_backend_name,
            ttl_seconds=config.cache_ttl_seconds,
            idempotency_ttl_seconds=config.idempotency_ttl_seconds,
            **asdict(cache_statistics),
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(
            content=telemetry.prometheus_payload(),
            headers={"Content-Type": PROMETHEUS_CONTENT_TYPE},
        )

    @app.get("/v1/telemetry/summary", tags=["system"])
    async def telemetry_summary() -> dict[str, object]:
        return telemetry.summary()

    @app.get("/v1/models", response_model=ModelList, tags=["inference"])
    async def models() -> ModelList:
        return ModelList(
            data=[
                ModelInfo(
                    id=model,
                    provider=provider.descriptor.name,
                    simulated=provider.descriptor.simulated,
                )
                for provider in providers.list()
                for model in provider.descriptor.models
            ]
        )

    @app.post(
        "/v1/chat/completions",
        response_model=ChatCompletionResponse,
        tags=["inference"],
    )
    async def chat_completion(
        request: ChatCompletionRequest,
        response: Response,
        x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
        x_client_id: str | None = Header(default=None, alias="X-Client-ID"),
        x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    ) -> ChatCompletionResponse:
        request_id = x_request_id or str(uuid.uuid4())
        response.headers["X-Request-ID"] = request_id
        started = time.perf_counter()
        telemetry.annotate_inference(
            request_id=request_id,
            model=request.model,
            policy=request.routing.policy,
        )
        trace_id = telemetry.current_trace_id()
        if request.stream:
            raise HTTPException(status_code=501, detail="streaming is not implemented yet")

        if (x_client_id is None) != (x_idempotency_key is None):
            raise HTTPException(
                status_code=400,
                detail="X-Client-ID and X-Idempotency-Key must be supplied together",
            )
        if x_client_id is not None and x_idempotency_key is not None:
            if not x_client_id.strip() or not x_idempotency_key.strip():
                raise HTTPException(
                    status_code=400,
                    detail="idempotency headers must not be empty",
                )
            try:
                replayed = await idempotency_store.replay(
                    x_client_id,
                    x_idempotency_key,
                    request,
                )
            except IdempotencyConflictError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if replayed is not None:
                latency_ms = (time.perf_counter() - started) * 1000
                response.headers["X-Request-ID"] = replayed.routing.request_id
                response.headers["X-Idempotent-Replay"] = "true"
                response.headers["X-Cache"] = "REPLAY"
                telemetry.annotate_inference(
                    request_id=replayed.routing.request_id,
                    model=replayed.model,
                    policy=replayed.routing.policy,
                    provider=replayed.routing.provider,
                    cache_status="REPLAY",
                    fallback_count=replayed.routing.fallback_count,
                )
                telemetry.record_inference(
                    request_id=replayed.routing.request_id,
                    trace_id=trace_id,
                    provider=replayed.routing.provider,
                    policy=replayed.routing.policy,
                    cache_status="REPLAY",
                    latency_ms=latency_ms,
                    fallback_count=replayed.routing.fallback_count,
                )
                return replayed

        excluded: set[str] = set()
        attempted: list[str] = []
        decision: RouteDecision | None = None
        result: ProviderResult | None = None
        cache_hit = False
        started = time.perf_counter()
        max_attempts = len(providers.list()) if request.model == "auto" else 1

        for _ in range(max_attempts):
            try:
                decision = await router.select(request, frozenset(excluded))
            except UnknownModelError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=f"unknown model: {request.model}",
                ) from exc
            except NoEligibleProviderError as exc:
                if attempted:
                    break
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            provider_name = decision.provider.descriptor.name
            attempted.append(provider_name)
            if config.cache_enabled:
                result = await response_cache.get(request, provider_name)
                if result is not None:
                    cache_hit = True
                    break
            provider_started = time.perf_counter()
            try:
                with telemetry.provider_span(provider_name):
                    result = await runtime.invoke(decision.provider, request)
            except ProviderCallError:
                telemetry.record_provider_call(
                    provider_name,
                    "failure",
                    (time.perf_counter() - provider_started) * 1000,
                )
                excluded.add(provider_name)
            else:
                telemetry.record_provider_call(
                    provider_name,
                    "success",
                    (time.perf_counter() - provider_started) * 1000,
                    result.estimated_cost_usd,
                )
                if config.cache_enabled:
                    await response_cache.set(request, provider_name, result)
                break

        if decision is None or result is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "all eligible providers failed or rejected traffic",
                    "attempted_providers": attempted,
                },
            )

        latency_ms = (time.perf_counter() - started) * 1000
        completion = ChatCompletionResponse(
            id=f"chatcmpl-{request_id}",
            model=request.model,
            choices=[
                ChatChoice(
                    message=ResponseMessage(content=result.text),
                    finish_reason=result.finish_reason,
                )
            ],
            usage=TokenUsage(
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.prompt_tokens + result.completion_tokens,
            ),
            routing=RoutingMetadata(
                provider=decision.provider.descriptor.name,
                policy=decision.policy,
                decision_reason=decision.reason,
                eligible_providers=list(decision.eligible_providers),
                attempted_providers=attempted,
                fallback_count=len(attempted) - 1,
                request_id=request_id,
                simulated=decision.provider.descriptor.simulated,
                cache_hit=cache_hit,
                estimated_cost_usd=result.estimated_cost_usd,
                latency_ms=round(latency_ms, 3),
            ),
        )
        if x_client_id is not None and x_idempotency_key is not None:
            await idempotency_store.store(
                x_client_id,
                x_idempotency_key,
                request,
                completion,
            )
        if config.cache_enabled:
            cache_status = "HIT" if cache_hit else "MISS"
        else:
            cache_status = "BYPASS"
        response.headers["X-Cache"] = cache_status
        telemetry.annotate_inference(
            request_id=request_id,
            model=request.model,
            policy=decision.policy,
            provider=decision.provider.descriptor.name,
            cache_status=cache_status,
            fallback_count=len(attempted) - 1,
        )
        telemetry.record_inference(
            request_id=request_id,
            trace_id=trace_id,
            provider=decision.provider.descriptor.name,
            policy=decision.policy,
            cache_status=cache_status,
            latency_ms=latency_ms,
            fallback_count=len(attempted) - 1,
        )
        return completion

    return app


app = create_app()
