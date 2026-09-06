import asyncio
from decimal import Decimal

import httpx

from control_plane.config import Settings
from control_plane.contracts import ChatCompletionRequest, ProviderResult
from control_plane.evaluation.cloud import (
    CloudSample,
    summarize_cloud_samples,
    validate_bedrock,
    validate_free_gateway,
)
from control_plane.main import create_app
from control_plane.providers.base import ProviderDescriptor
from control_plane.providers.registry import ProviderRegistry


class RealTestProvider:
    descriptor = ProviderDescriptor(
        name="aws-bedrock",
        models=("bedrock-primary",),
        simulated=False,
        nominal_latency_ms=10,
        input_cost_per_million_tokens_usd="1",
        output_cost_per_million_tokens_usd="1",
        quality_score=0.9,
    )

    async def complete(self, request: ChatCompletionRequest) -> ProviderResult:
        return ProviderResult(
            text="validation passed",
            prompt_tokens=2,
            completion_tokens=2,
            estimated_cost_usd="0.000004",
        )


def test_cloud_summary_uses_successful_samples_for_latency_and_cost() -> None:
    report = summarize_cloud_samples(
        kind="test",
        samples=[
            CloudSample(1, 200, 10, "provider", "0.001"),
            CloudSample(2, 200, 20, "provider", "0.002"),
            CloudSample(3, 503, 100, None, "0"),
        ],
    )

    assert report["summary"] == {
        "requests": 3,
        "successful_requests": 2,
        "failed_requests": 1,
        "success_rate": 0.666667,
        "latency_ms": {"p50": 10, "p95": 20, "p99": 20, "max": 20},
        "total_estimated_cost_usd": "0.003",
    }


def test_free_cloud_validation_uses_only_mock_provider() -> None:
    app = create_app(Settings(cache_enabled=False))

    async def execute() -> dict[str, object]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await validate_free_gateway(
                client,
                requests=3,
                expected_cache_backend="memory",
                allowed_origin="http://localhost:5173",
            )

    report = asyncio.run(execute())

    assert report["summary"]["successful_requests"] == 3
    assert {sample["provider"] for sample in report["samples"]} == {"mock-fast"}
    assert report["deployment_checks"] == {
        "ready": True,
        "mock_providers_enabled": True,
        "ollama_enabled": False,
        "aws_bedrock_enabled": False,
        "aws_session_budget_usd": "0",
        "all_models_simulated": True,
        "cache_backend": "memory",
        "allowed_origin": "http://localhost:5173",
    }


def test_bedrock_validation_requires_and_measures_real_provider() -> None:
    provider = RealTestProvider()
    registry = ProviderRegistry((provider,))
    settings = Settings(
        mock_providers_enabled=False,
        aws_bedrock_enabled=True,
        aws_model_id="test-model",
        aws_input_cost_per_million_tokens_usd=Decimal("1"),
        aws_output_cost_per_million_tokens_usd=Decimal("1"),
        aws_session_budget_usd=Decimal("1"),
        cache_enabled=False,
    )
    app = create_app(settings, registry=registry)

    async def execute() -> dict[str, object]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await validate_bedrock(
                client,
                requests=3,
                maximum_total_estimated_cost_usd=Decimal("0.01"),
            )

    report = asyncio.run(execute())
    assert report["summary"]["successful_requests"] == 3
    assert report["summary"]["total_estimated_cost_usd"] == "0.000012"
    assert {sample["provider"] for sample in report["samples"]} == {"aws-bedrock"}
