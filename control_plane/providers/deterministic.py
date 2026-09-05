"""Deterministic zero-cost providers for tests, demos, and benchmarks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from control_plane.contracts import ChatCompletionRequest, ProviderResult
from control_plane.providers.base import ProviderDescriptor


@dataclass(slots=True)
class DeterministicProvider:
    descriptor: ProviderDescriptor
    latency_scale: float = 0.001

    async def complete(self, request: ChatCompletionRequest) -> ProviderResult:
        await asyncio.sleep(self.descriptor.nominal_latency_ms * self.latency_scale / 1000)
        prompt = next(
            message.content for message in reversed(request.messages) if message.role == "user"
        )
        prompt_tokens = max(1, len(" ".join(message.content for message in request.messages)) // 4)
        text = f"[{self.descriptor.name}] {prompt}"
        completion_tokens = min(request.max_tokens, max(1, len(text) // 4))
        input_cost = (
            Decimal(prompt_tokens)
            * Decimal(self.descriptor.input_cost_per_million_tokens_usd)
            / Decimal(1_000_000)
        )
        output_cost = (
            Decimal(completion_tokens)
            * Decimal(self.descriptor.output_cost_per_million_tokens_usd)
            / Decimal(1_000_000)
        )
        return ProviderResult(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=str(input_cost + output_cost),
        )


def default_providers() -> tuple[DeterministicProvider, ...]:
    return (
        DeterministicProvider(
            ProviderDescriptor(
                name="mock-economy",
                models=("mock-economy",),
                simulated=True,
                nominal_latency_ms=180,
                input_cost_per_million_tokens_usd="0.10",
                output_cost_per_million_tokens_usd="0.40",
                quality_score=0.72,
            )
        ),
        DeterministicProvider(
            ProviderDescriptor(
                name="mock-fast",
                models=("mock-fast",),
                simulated=True,
                nominal_latency_ms=45,
                input_cost_per_million_tokens_usd="0.80",
                output_cost_per_million_tokens_usd="2.40",
                quality_score=0.81,
            )
        ),
        DeterministicProvider(
            ProviderDescriptor(
                name="mock-quality",
                models=("mock-quality",),
                simulated=True,
                nominal_latency_ms=260,
                input_cost_per_million_tokens_usd="2.00",
                output_cost_per_million_tokens_usd="8.00",
                quality_score=0.94,
            )
        ),
    )
