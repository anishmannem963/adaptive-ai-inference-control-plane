"""Inference provider protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from control_plane.contracts import ChatCompletionRequest, ProviderResult


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    name: str
    models: tuple[str, ...]
    simulated: bool
    nominal_latency_ms: int
    input_cost_per_million_tokens_usd: str
    output_cost_per_million_tokens_usd: str
    quality_score: float


class InferenceProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    async def complete(self, request: ChatCompletionRequest) -> ProviderResult: ...
