import asyncio
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from control_plane.config import Settings
from control_plane.contracts import ChatCompletionRequest
from control_plane.providers.bedrock import (
    BedrockProvider,
    SessionBudget,
    SessionBudgetExceededError,
)
from control_plane.providers.factory import build_providers
from control_plane.providers.ollama import OllamaProvider


def request(model: str) -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Explain quorum."},
            ],
            "max_tokens": 32,
            "temperature": 0,
        }
    )


def test_ollama_adapter_maps_chat_contract_and_usage() -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path == "/api/chat"
        payload = json.loads(http_request.content)
        assert payload["model"] == "qwen2.5:0.5b"
        assert payload["stream"] is False
        assert payload["options"]["num_predict"] == 32
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "A quorum is a majority."},
                "prompt_eval_count": 9,
                "eval_count": 6,
                "done_reason": "stop",
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://ollama:11434",
            transport=httpx.MockTransport(handler),
        ) as client:
            provider = OllamaProvider(
                base_url="http://ollama:11434",
                model="qwen2.5:0.5b",
                model_alias="ollama-local",
                nominal_latency_ms=800,
                quality_score=0.75,
                client=client,
            )
            result = await provider.complete(request("ollama-local"))
            assert result.text == "A quorum is a majority."
            assert result.prompt_tokens == 9
            assert result.completion_tokens == 6
            assert result.estimated_cost_usd == "0"

    asyncio.run(run())


class FakeBedrockClient:
    def __init__(self) -> None:
        self.count_payload: dict[str, Any] = {}
        self.converse_payload: dict[str, Any] = {}

    def count_tokens(self, **kwargs: Any) -> dict[str, Any]:
        self.count_payload = kwargs
        return {"inputTokens": 10}

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.converse_payload = kwargs
        return {
            "output": {"message": {"content": [{"text": "Two of three nodes."}]}},
            "usage": {"inputTokens": 10, "outputTokens": 5},
            "stopReason": "end_turn",
        }


def bedrock_provider(client: FakeBedrockClient, budget: str = "1") -> BedrockProvider:
    return BedrockProvider(
        client=client,
        model_id="example.model-v1",
        model_alias="bedrock-primary",
        input_cost_per_million_tokens_usd=Decimal("1"),
        output_cost_per_million_tokens_usd=Decimal("2"),
        nominal_latency_ms=1200,
        quality_score=0.9,
        budget=SessionBudget(Decimal(budget)),
    )


def test_bedrock_adapter_counts_tokens_reserves_budget_and_maps_response() -> None:
    async def run() -> None:
        client = FakeBedrockClient()
        provider = bedrock_provider(client)
        result = await provider.complete(request("bedrock-primary"))

        assert client.count_payload["modelId"] == "example.model-v1"
        converse = client.count_payload["input"]["converse"]
        assert converse["system"] == [{"text": "Be concise."}]
        assert converse["messages"][0]["role"] == "user"
        assert client.converse_payload["inferenceConfig"]["maxTokens"] == 32
        assert result.text == "Two of three nodes."
        assert result.estimated_cost_usd == "0.00002"
        assert provider.budget.spent_usd == Decimal("0.00002")
        assert provider.budget.reserved_usd == Decimal("0")

    asyncio.run(run())


def test_bedrock_fails_closed_before_inference_when_budget_is_insufficient() -> None:
    async def run() -> None:
        client = FakeBedrockClient()
        provider = bedrock_provider(client, budget="0.000001")
        with pytest.raises(SessionBudgetExceededError, match="budget"):
            await provider.complete(request("bedrock-primary"))
        assert client.converse_payload == {}

    asyncio.run(run())


def test_factory_keeps_real_adapters_opt_in() -> None:
    assert len(build_providers(Settings())) == 3

    settings = Settings(
        ollama_enabled=True,
        aws_bedrock_enabled=True,
        aws_model_id="example.model-v1",
        aws_input_cost_per_million_tokens_usd=Decimal("1"),
        aws_output_cost_per_million_tokens_usd=Decimal("2"),
        aws_session_budget_usd=Decimal("1"),
    )
    providers = build_providers(settings, bedrock_client=FakeBedrockClient())
    assert [provider.descriptor.name for provider in providers] == [
        "mock-economy",
        "mock-fast",
        "mock-quality",
        "ollama-local",
        "aws-bedrock",
    ]
    assert providers[-1].descriptor.simulated is False
