"""FastAPI service entrypoint."""

from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

from control_plane import __version__
from control_plane.config import Settings
from control_plane.contracts import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ResponseMessage,
    RoutingMetadata,
    TokenUsage,
)
from control_plane.providers.deterministic import default_providers
from control_plane.providers.registry import ProviderRegistry, UnknownModelError
from control_plane.routing import NoEligibleProviderError, RoutingEngine


class Health(BaseModel):
    status: str
    version: str


class Status(BaseModel):
    environment: str
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


def create_app(
    settings: Settings | None = None,
    registry: ProviderRegistry | None = None,
) -> FastAPI:
    config = settings or Settings.from_env()
    providers = registry or ProviderRegistry(default_providers())
    router = RoutingEngine(providers)
    app = FastAPI(title="Adaptive AI Inference Control Plane", version=__version__)

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
            aws_bedrock_enabled=config.aws_bedrock_enabled,
            aws_session_budget_usd=str(config.aws_session_budget_usd),
            registered_providers=len(providers.list()),
        )

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
    ) -> ChatCompletionResponse:
        request_id = x_request_id or str(uuid.uuid4())
        response.headers["X-Request-ID"] = request_id
        if request.stream:
            raise HTTPException(status_code=501, detail="streaming is not implemented yet")
        try:
            decision = await router.select(request)
        except UnknownModelError as exc:
            raise HTTPException(status_code=404, detail=f"unknown model: {request.model}") from exc
        except NoEligibleProviderError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        started = time.perf_counter()
        try:
            async with asyncio.timeout(5.0):
                result = await decision.provider.complete(request)
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="provider deadline exceeded") from exc
        latency_ms = (time.perf_counter() - started) * 1000

        return ChatCompletionResponse(
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
                request_id=request_id,
                simulated=decision.provider.descriptor.simulated,
                estimated_cost_usd=result.estimated_cost_usd,
                latency_ms=round(latency_ms, 3),
            ),
        )

    return app


app = create_app()
