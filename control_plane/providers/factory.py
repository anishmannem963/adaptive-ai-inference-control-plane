"""Configuration-driven provider construction."""

from __future__ import annotations

from typing import cast

import httpx

from control_plane.config import Settings
from control_plane.providers.base import InferenceProvider
from control_plane.providers.bedrock import BedrockProvider, BedrockRuntimeClient, SessionBudget
from control_plane.providers.deterministic import default_providers
from control_plane.providers.ollama import OllamaProvider


def build_providers(
    settings: Settings,
    *,
    ollama_client: httpx.AsyncClient | None = None,
    bedrock_client: BedrockRuntimeClient | None = None,
) -> tuple[InferenceProvider, ...]:
    providers: list[InferenceProvider] = []
    if settings.mock_providers_enabled:
        providers.extend(default_providers())
    if settings.ollama_enabled:
        providers.append(
            OllamaProvider(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                model_alias=settings.ollama_model_alias,
                nominal_latency_ms=settings.ollama_nominal_latency_ms,
                quality_score=settings.ollama_quality_score,
                client=ollama_client,
            )
        )
    if settings.aws_bedrock_enabled:
        if bedrock_client is None:
            import boto3  # type: ignore[import-untyped]

            bedrock_client = cast(
                BedrockRuntimeClient,
                boto3.client("bedrock-runtime", region_name=settings.aws_region),
            )
        providers.append(
            BedrockProvider(
                client=bedrock_client,
                model_id=settings.aws_model_id,
                model_alias=settings.aws_model_alias,
                input_cost_per_million_tokens_usd=(settings.aws_input_cost_per_million_tokens_usd),
                output_cost_per_million_tokens_usd=(
                    settings.aws_output_cost_per_million_tokens_usd
                ),
                nominal_latency_ms=settings.aws_nominal_latency_ms,
                quality_score=settings.aws_quality_score,
                budget=SessionBudget(settings.aws_session_budget_usd),
            )
        )
    return tuple(providers)
