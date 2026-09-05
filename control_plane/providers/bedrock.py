"""Budget-guarded Amazon Bedrock Converse adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from control_plane.contracts import ChatCompletionRequest, ProviderResult
from control_plane.providers.base import ProviderDescriptor


class BedrockRuntimeClient(Protocol):
    def count_tokens(self, **kwargs: Any) -> dict[str, Any]: ...

    def converse(self, **kwargs: Any) -> dict[str, Any]: ...


class SessionBudgetExceededError(RuntimeError):
    """The configured Bedrock session budget cannot cover a request."""


@dataclass(slots=True)
class SessionBudget:
    limit_usd: Decimal
    spent_usd: Decimal = Decimal("0")
    reserved_usd: Decimal = Decimal("0")
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def reserve(self, amount: Decimal) -> None:
        async with self._lock:
            if self.spent_usd + self.reserved_usd + amount > self.limit_usd:
                raise SessionBudgetExceededError("Bedrock session budget would be exceeded")
            self.reserved_usd += amount

    async def settle(self, reserved: Decimal, actual: Decimal) -> None:
        async with self._lock:
            self.reserved_usd -= reserved
            self.spent_usd += actual

    async def release(self, reserved: Decimal) -> None:
        async with self._lock:
            self.reserved_usd -= reserved


@dataclass(slots=True)
class BedrockProvider:
    client: BedrockRuntimeClient
    model_id: str
    model_alias: str
    input_cost_per_million_tokens_usd: Decimal
    output_cost_per_million_tokens_usd: Decimal
    nominal_latency_ms: int
    quality_score: float
    budget: SessionBudget

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            name="aws-bedrock",
            models=(self.model_alias,),
            simulated=False,
            nominal_latency_ms=self.nominal_latency_ms,
            input_cost_per_million_tokens_usd=str(self.input_cost_per_million_tokens_usd),
            output_cost_per_million_tokens_usd=str(self.output_cost_per_million_tokens_usd),
            quality_score=self.quality_score,
        )

    def _converse_input(self, request: ChatCompletionRequest) -> dict[str, Any]:
        messages = [
            {
                "role": message.role,
                "content": [{"text": message.content}],
            }
            for message in request.messages
            if message.role != "system"
        ]
        payload: dict[str, Any] = {"messages": messages}
        system = [
            {"text": message.content} for message in request.messages if message.role == "system"
        ]
        if system:
            payload["system"] = system
        return payload

    def _cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            Decimal(input_tokens) * self.input_cost_per_million_tokens_usd
            + Decimal(output_tokens) * self.output_cost_per_million_tokens_usd
        ) / Decimal(1_000_000)

    async def complete(self, request: ChatCompletionRequest) -> ProviderResult:
        converse_input = self._converse_input(request)
        token_response = await asyncio.to_thread(
            self.client.count_tokens,
            modelId=self.model_id,
            input={"converse": converse_input},
        )
        input_tokens = token_response.get("inputTokens")
        if not isinstance(input_tokens, int) or input_tokens < 0:
            raise ValueError("Bedrock CountTokens returned invalid usage")

        reserved = self._cost(input_tokens, request.max_tokens)
        await self.budget.reserve(reserved)
        try:
            response = await asyncio.to_thread(
                self.client.converse,
                modelId=self.model_id,
                **converse_input,
                inferenceConfig={
                    "maxTokens": request.max_tokens,
                    "temperature": request.temperature,
                },
            )
        except Exception:
            await self.budget.release(reserved)
            raise

        usage = response.get("usage")
        output = response.get("output")
        if not isinstance(usage, dict) or not isinstance(output, dict):
            await self.budget.release(reserved)
            raise ValueError("Bedrock response omitted output or usage")
        response_input_tokens = usage.get("inputTokens")
        output_tokens = usage.get("outputTokens")
        message = output.get("message")
        if (
            not isinstance(response_input_tokens, int)
            or not isinstance(output_tokens, int)
            or not isinstance(message, dict)
        ):
            await self.budget.release(reserved)
            raise ValueError("Bedrock response contained invalid usage or message")
        content = message.get("content")
        if not isinstance(content, list):
            await self.budget.release(reserved)
            raise ValueError("Bedrock response omitted message content")
        text = "".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
        if not text:
            await self.budget.release(reserved)
            raise ValueError("Bedrock response did not contain assistant text")

        actual = self._cost(response_input_tokens, output_tokens)
        await self.budget.settle(reserved, actual)
        return ProviderResult(
            text=text,
            prompt_tokens=response_input_tokens,
            completion_tokens=output_tokens,
            finish_reason="length" if response.get("stopReason") == "max_tokens" else "stop",
            estimated_cost_usd=str(actual),
        )
